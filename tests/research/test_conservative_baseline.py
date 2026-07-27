import csv
import json
import os
import sqlite3
from pathlib import Path

import pytest

from ModelStrategy.research.boundary import parse_utc
from ModelStrategy.research.conservative_baseline import (
    compare_conservative_reference,
    conservative_reference_payload,
    normalize_source_timestamps,
    run_conservative_comparison,
)
from ModelStrategy.research.schema import ResearchTrade
from tests.research.test_spec import conservative_spec, write_spec


HOUR = 3600


def make_conservative_fixture(tmp_path):
    begin = parse_utc("2021-01-01")
    end = begin + 24 * HOUR
    raw_spec = conservative_spec()
    raw_spec["window"] = {
        "begin": "2021-01-01T00:00:00Z",
        "end_exclusive": "2021-01-02T00:00:00Z",
    }
    raw_spec["risk_grid"] = [0.005, 0.01]
    raw_spec["splits"] = {
        "fixture": [
            "2021-01-01T00:00:00Z",
            "2021-01-02T00:00:00Z",
        ]
    }
    spec_path = write_spec(tmp_path, raw_spec)

    (tmp_path / "from_session_b").mkdir()
    (tmp_path / "from_session_b" / "cache_2125_S1.json").write_text(
        json.dumps(
            [
                {
                    "open_ts": begin + HOUR,
                    "close_ts": begin + 5 * HOUR,
                    "profit_rate": 5.0,
                    "risk_rate": 0.05,
                    "bs_type": "1",
                    "is_buy": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "cache_2125_S2py10_ispyr.json").write_text(
        json.dumps(
            [
                {
                    "open_ts": begin + 4 * HOUR,
                    "close_ts": begin + 12 * HOUR,
                    "profit_rate": -2.0,
                    "risk_rate": 0.05,
                    "bs_type": "1p",
                    "is_buy": False,
                    "is_pyramid": False,
                }
            ]
        ),
        encoding="utf-8",
    )
    with sqlite3.connect(tmp_path / "btc_mlv.db") as connection:
        connection.execute(
            "create table kline ("
            "ts integer, symbol text, lv text, o real, h real, l real, c real)"
        )
        rows = []
        for level, interval in (("K_60M", HOUR), ("K_4H", 4 * HOUR)):
            for bar_end in range(int(begin), int(end), interval):
                rows.append(
                    (
                        (bar_end - interval) * 1000,
                        "BTC/USDT",
                        level,
                        100.0,
                        101.0,
                        99.0,
                        100.0,
                    )
                )
        connection.executemany(
            "insert into kline values (?, ?, ?, ?, ?, ?, ?)", rows
        )

    funding_path = tmp_path / "btc" / "btc_funding_rate.csv"
    funding_path.parent.mkdir()
    with funding_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["symbol", "fundingTime", "fundingRate", "markPrice"])
        for offset in (0, 8, 16):
            writer.writerow(
                [
                    "BTCUSDT",
                    f"2021-01-01T{offset:02d}:00:00+00:00",
                    0.0001,
                    "",
                ]
            )
    legacy_reference = {
        "schema_version": 1,
        "strategy_id": "freeze_v4",
        "execution_model": "legacy-v1",
        "risk_pct": 0.0075,
        "is_2125": {
            "cagr": 0.2,
            "full_dd": 0.1,
            "worst_dd": 0.1,
            "splits": {
                "fixture": {"cagr": 0.2, "dd": 0.1, "calmar": 2.0}
            },
        },
    }
    legacy_path = tmp_path / "legacy-reference.json"
    legacy_path.write_text(json.dumps(legacy_reference), encoding="utf-8")
    return spec_path, legacy_path, legacy_reference


def test_conservative_report_contains_models_costs_and_is_manifests(tmp_path):
    spec_path, _, legacy_reference = make_conservative_fixture(tmp_path)
    report = run_conservative_comparison(
        spec_path,
        research_root=tmp_path,
        market_data_root=tmp_path,
        legacy_reference=legacy_reference,
        provenance={"commit": "test", "dirty": False},
    )
    assert report["execution_model"] == "conservative-v2"
    assert report["legacy_reference"]["risk_pct"] == 0.0075
    assert report["conservative"]["risk_pct"] in (0.005, 0.01)
    assert report["conservative"]["fees"] >= 0
    assert math_is_finite(report["conservative"]["funding_pnl"])
    assert report["execution"] == {
        "filled": 2,
        "maker_fills": 2,
        "taker_fills": 0,
        "same_bar_stops": 0,
        "unfilled": 0,
    }
    assert report["inputs"]["marks"]["row_count"] == 24
    assert report["inputs"]["funding"]["row_count"] == 3
    assert report["inputs"]["marks"]["last_ts"] < report["window"][
        "end_exclusive_ts"
    ]
    assert len(report["risk_calibration"]) == 2


def math_is_finite(value):
    return isinstance(value, (int, float)) and value == value and abs(value) < 1e300


def test_conservative_reference_reports_exact_mismatch_path(tmp_path):
    spec_path, _, legacy_reference = make_conservative_fixture(tmp_path)
    report = run_conservative_comparison(
        spec_path,
        research_root=tmp_path,
        market_data_root=tmp_path,
        legacy_reference=legacy_reference,
        provenance={"commit": "test", "dirty": False},
    )
    reference = conservative_reference_payload(report)
    assert compare_conservative_reference(report, reference) == []
    reference["risk_pct"] = 0.123
    assert compare_conservative_reference(report, reference) == [
        {
            "path": "risk_pct",
            "expected": 0.123,
            "actual": report["conservative"]["risk_pct"],
        }
    ]


def test_source_timestamp_offset_is_applied_before_execution_replay(tmp_path):
    spec_path, _, legacy_reference = make_conservative_fixture(tmp_path)
    baseline = run_conservative_comparison(
        spec_path,
        research_root=tmp_path,
        market_data_root=tmp_path,
        legacy_reference=legacy_reference,
        provenance={"commit": "test", "dirty": False},
    )
    for relative in (
        Path("from_session_b/cache_2125_S1.json"),
        Path("cache_2125_S2py10_ispyr.json"),
    ):
        path = tmp_path / relative
        values = json.loads(path.read_text(encoding="utf-8"))
        for value in values:
            value["open_ts"] -= HOUR
            value["close_ts"] -= HOUR
        path.write_text(json.dumps(values), encoding="utf-8")
    raw_spec = json.loads(spec_path.read_text(encoding="utf-8"))
    raw_spec["execution"]["source_timestamp_offset_seconds"] = HOUR
    spec_path.write_text(json.dumps(raw_spec), encoding="utf-8")
    corrected = run_conservative_comparison(
        spec_path,
        research_root=tmp_path,
        market_data_root=tmp_path,
        legacy_reference=legacy_reference,
        provenance={"commit": "test", "dirty": False},
    )
    assert corrected["conservative"] == baseline["conservative"]
    assert corrected["execution"] == baseline["execution"]
    manifest = corrected["inputs"]["s1_trades"]
    assert manifest["timestamp_offset_seconds"] == HOUR
    assert manifest["corrected_first_open_ts"] == (
        manifest["raw_first_open_ts"] + HOUR
    )


def test_corrected_timestamp_must_remain_inside_declared_is_window():
    trade = ResearchTrade.from_mapping(
        {
            "open_ts": 5 * HOUR,
            "close_ts": 9 * HOUR,
            "profit_rate": 1.0,
            "risk_rate": 0.05,
            "bs_type": "1",
            "is_buy": True,
        }
    )
    with pytest.raises(ValueError, match="outside declared window"):
        normalize_source_timestamps(
            [trade],
            offset_seconds=HOUR,
            begin_ts=0,
            end_ts=10 * HOUR,
            input_name="test_trades",
        )


@pytest.mark.skipif(
    "CHANPY_RESEARCH_ROOT" not in os.environ
    or "CHANPY_MARKET_DATA_ROOT" not in os.environ,
    reason="set research and market roots to verify the tracked IS reference",
)
def test_real_conservative_report_matches_tracked_reference():
    repo_root = Path(__file__).resolve().parents[2]
    reference_path = (
        repo_root
        / "ModelStrategy"
        / "research"
        / "baselines"
        / "freeze_v4_conservative_v2.json"
    )
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    legacy_reference = json.loads(
        (
            repo_root
            / "ModelStrategy"
            / "research"
            / "baselines"
            / "freeze_v4_legacy_v1.json"
        ).read_text(encoding="utf-8")
    )
    report = run_conservative_comparison(
        repo_root
        / "ModelStrategy"
        / "research"
        / "configs"
        / "freeze_v4_conservative_v2.json",
        research_root=Path(os.environ["CHANPY_RESEARCH_ROOT"]),
        market_data_root=Path(os.environ["CHANPY_MARKET_DATA_ROOT"]),
        legacy_reference=legacy_reference,
        provenance={"commit": "test", "dirty": False},
    )
    assert compare_conservative_reference(report, reference) == []
