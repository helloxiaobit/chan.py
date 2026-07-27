import csv
import os
import sqlite3
from pathlib import Path

import pytest

from ModelStrategy.research.boundary import parse_utc
from ModelStrategy.research.market import (
    FundingEvent,
    MarketBar,
    MarketDataError,
    MarketSeries,
    load_funding_events,
    load_market_series,
    require_funding_coverage,
)


HOUR = 3600


def bar(hour, *, open_price=100.0, high=101.0, low=99.0, close=100.0):
    return MarketBar(
        ts=hour * HOUR,
        open=open_price,
        high=high,
        low=low,
        close=close,
    )


def make_bar_db(tmp_path, rows):
    path = tmp_path / "bars.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "create table kline ("
            "ts integer, symbol text, lv text, o real, h real, l real, c real)"
        )
        connection.executemany(
            "insert into kline values (?, ?, ?, ?, ?, ?, ?)", rows
        )
    return path


def write_funding(tmp_path, rows):
    path = tmp_path / "funding.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["symbol", "fundingTime", "fundingRate", "markPrice"])
        for timestamp, rate in rows:
            writer.writerow(["BTCUSDT", timestamp, rate, ""])
    return path


def test_market_loader_uses_bar_end_timestamps_and_logical_manifest(tmp_path):
    raw_ts = 1609459200000
    db = make_bar_db(
        tmp_path,
        [
            (raw_ts, "BTC/USDT", "K_60M", 100, 101, 99, 100),
            (
                parse_utc("2026-01-01") * 1000,
                "BTC/USDT",
                "K_60M",
                999,
                999,
                999,
                999,
            ),
        ],
    )
    series = load_market_series(
        db,
        "BTC/USDT",
        "K_60M",
        3600000,
        parse_utc("2021-01-01"),
        parse_utc("2021-01-02"),
    )
    assert series.bars[0].ts == 1609459200 + HOUR
    assert series.manifest["row_count"] == 1
    assert series.manifest["last_ts"] < parse_utc("2026-01-01")


def test_market_loader_manifest_ignores_later_rows(tmp_path):
    raw_ts = 1609459200000
    later_ts = int(parse_utc("2026-01-01") * 1000)
    db = make_bar_db(
        tmp_path,
        [
            (raw_ts, "BTC/USDT", "K_60M", 100, 101, 99, 100),
            (later_ts, "BTC/USDT", "K_60M", 200, 201, 199, 200),
        ],
    )
    args = (
        db,
        "BTC/USDT",
        "K_60M",
        3600000,
        parse_utc("2021-01-01"),
        parse_utc("2026-01-01"),
    )
    first = load_market_series(*args).manifest
    with sqlite3.connect(db) as connection:
        connection.execute("update kline set c = 999 where ts = ?", (later_ts,))
    assert load_market_series(*args).manifest == first


def test_market_loader_rejects_gap_inside_required_window():
    series = MarketSeries("BTC/USDT", HOUR, (bar(0), bar(1), bar(3)))
    with pytest.raises(MarketDataError, match="gap"):
        series.require_coverage(0, 3 * HOUR)


def test_market_series_carries_forward_only_bounded_gaps():
    series = MarketSeries("BTC/USDT", HOUR, (bar(0), bar(1), bar(3)))
    filled = series.carry_forward_gaps(max_missing_intervals=2)
    synthetic = filled.at(2 * HOUR)
    assert synthetic.synthetic is True
    assert synthetic.open == synthetic.high == synthetic.low == synthetic.close
    assert synthetic.close == series.at(HOUR).close
    assert filled.manifest["synthetic_bar_count"] == 1
    filled.require_coverage(0, 3 * HOUR)


def test_market_series_rejects_gap_above_carry_forward_cap():
    series = MarketSeries("BTC/USDT", HOUR, (bar(0), bar(4)))
    with pytest.raises(MarketDataError, match="exceeds"):
        series.carry_forward_gaps(max_missing_intervals=2)


def test_market_series_rejects_duplicate_timestamp():
    with pytest.raises(MarketDataError, match="strictly increasing"):
        MarketSeries("BTC/USDT", HOUR, (bar(1), bar(1)))


def test_market_bar_rejects_invalid_ohlc():
    with pytest.raises(MarketDataError, match="OHLC"):
        MarketBar(ts=HOUR, open=100, high=99, low=98, close=100)


def test_funding_loader_excludes_2026_rows_from_manifest(tmp_path):
    path = write_funding(
        tmp_path,
        [
            ("2025-12-31T16:00:00+00:00", 0.001),
            ("2026-01-01T00:00:00+00:00", 0.9),
        ],
    )
    events, manifest = load_funding_events(
        path,
        "BTC/USDT",
        parse_utc("2025-01-01"),
        parse_utc("2026-01-01"),
    )
    assert [event.rate for event in events] == [0.001]
    assert manifest["row_count"] == 1
    assert manifest["last_ts"] == parse_utc("2025-12-31T16:00:00Z")


def test_funding_manifest_ignores_later_rate_changes(tmp_path):
    path = write_funding(
        tmp_path,
        [
            ("2025-12-31T16:00:00+00:00", 0.001),
            ("2026-01-01T00:00:00+00:00", 0.9),
        ],
    )
    args = (
        path,
        "BTC/USDT",
        parse_utc("2025-01-01"),
        parse_utc("2026-01-01"),
    )
    first = load_funding_events(*args)[1]
    write_funding(
        tmp_path,
        [
            ("2025-12-31T16:00:00+00:00", 0.001),
            ("2026-01-01T00:00:00+00:00", -99.0),
        ],
    )
    assert load_funding_events(*args)[1] == first


def test_sealed_is_funding_loader_does_not_parse_2026_rows(tmp_path):
    path = write_funding(
        tmp_path,
        [
            ("2025-12-31T16:00:00+00:00", 0.001),
            ("2026-not-a-valid-timestamp", "not-a-rate"),
        ],
    )
    events, manifest = load_funding_events(
        path,
        "BTC/USDT",
        parse_utc("2025-12-31T16:00:00Z"),
        parse_utc("2026-01-01"),
        sealed_end_year=2026,
    )
    assert [event.rate for event in events] == [0.001]
    assert manifest["sealed_end_year"] == 2026
    assert manifest["stopped_at_sealed_year"] is True


def test_funding_loader_rejects_naive_timestamp(tmp_path):
    path = write_funding(tmp_path, [("2025-12-31 16:00:00", 0.001)])
    with pytest.raises(MarketDataError, match="timezone"):
        load_funding_events(
            path,
            "BTC/USDT",
            parse_utc("2025-01-01"),
            parse_utc("2026-01-01"),
        )


def test_funding_coverage_rejects_missing_settlement():
    events = (
        FundingEvent(0, "BTC/USDT", 0.001),
        FundingEvent(8 * HOUR, "BTC/USDT", 0.001),
        FundingEvent(24 * HOUR, "BTC/USDT", 0.001),
    )
    with pytest.raises(MarketDataError, match="funding gap"):
        require_funding_coverage(
            events,
            "BTC/USDT",
            begin_ts=0,
            end_ts=32 * HOUR,
            interval_seconds=8 * HOUR,
        )


@pytest.mark.skipif(
    "CHANPY_RESEARCH_ROOT" not in os.environ
    or "CHANPY_MARKET_DATA_ROOT" not in os.environ,
    reason="set research and market roots to verify external IS data",
)
def test_real_btc_market_and_funding_cover_is_window():
    begin = parse_utc("2021-01-01")
    end = parse_utc("2026-01-01")
    research_root = Path(os.environ["CHANPY_RESEARCH_ROOT"])
    market_root = Path(os.environ["CHANPY_MARKET_DATA_ROOT"])
    raw = load_market_series(
        research_root / "btc_mlv.db",
        "BTC/USDT",
        "K_60M",
        3600000,
        begin,
        end,
    )
    marks = raw.carry_forward_gaps(max_missing_intervals=16)
    marks.require_coverage(begin, end - HOUR)
    assert marks.manifest["synthetic_bar_count"] == 29
    assert len(marks.manifest["gaps"]) == 8

    events, manifest = load_funding_events(
        market_root / "btc" / "btc_funding_rate.csv",
        "BTC/USDT",
        begin,
        end,
    )
    require_funding_coverage(events, "BTC/USDT", begin, end, 8 * HOUR)
    assert manifest["row_count"] == 5478
