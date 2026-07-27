import json
import os
import sqlite3
from pathlib import Path

import pytest

from ModelStrategy.research.baseline import (
    BarSeries,
    apply_zlimit,
    calibrate_risk,
    compare_reference,
    run_baseline,
)
from ModelStrategy.research.boundary import parse_utc
from ModelStrategy.research.schema import ResearchTrade
from ModelStrategy.research.spec import load_spec


def make_trade(**overrides):
    values = {
        "open_ts": 100.0,
        "close_ts": 300.0,
        "profit_rate": 1.0,
        "risk_rate": 0.02,
        "bs_type": "1",
        "is_buy": True,
        "is_pyramid": False,
    }
    values.update(overrides)
    return ResearchTrade.from_mapping(values)


def make_spec(tmp_path, *, fees=0.0):
    value = {
        "schema_version": 1,
        "strategy_id": "freeze_v4",
        "execution_model": "legacy-v1",
        "window": {"begin": "2021-01-01", "end_exclusive": "2026-01-01"},
        "inputs": {
            "s1_trades": "s1.json",
            "s2_trades": "s2.json",
            "bars_db": "bars.db",
        },
        "risk_grid": [0.005, 0.0075, 0.01],
        "portfolio": {
            "taker_fee": fees,
            "maker_fee": fees,
            "max_concurrent": 4,
            "max_leverage": 3.0,
            "max_pos_leverage": 1.5,
            "target_max_drawdown": 0.25,
        },
        "conviction": {
            "co_dir_mult": 1.5,
            "opp_dir_mult": 1.0,
            "bs_mults": {"1": 0.8, "1p": 1.2},
            "mult_cap": 2.0,
        },
        "zlimit": {
            "patience": 8,
            "s1_level": "K_60M",
            "s1_ms": 3600000,
            "s2_level": "K_4H",
            "s2_ms": 14400000,
        },
        "splits": {
            "A(21-23)": ["2021-01-01", "2024-01-01"],
            "B(2024)": ["2024-01-01", "2025-01-01"],
            "C(2025)": ["2025-01-01", "2026-01-01"],
        },
    }
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return load_spec(path)


def test_pyramid_trade_is_never_reclassified_as_maker():
    normal = make_trade()
    pyramid = make_trade(is_pyramid=True)
    bars = BarSeries(
        end_timestamps=(100.0, 200.0),
        low_high=((100.0, 100.0), (99.0, 101.0)),
        close_by_end={100.0: 100.0},
    )
    apply_zlimit([normal, pyramid], bars, patience=8)
    assert normal.bs_type == "z1"
    assert pyramid.bs_type == "1"


def test_unreached_limit_remains_taker():
    trade = make_trade(is_buy=True)
    bars = BarSeries(
        end_timestamps=tuple(float(i) for i in range(100, 1000, 100)),
        low_high=((101.0, 102.0),) * 9,
        close_by_end={100.0: 100.0},
    )
    apply_zlimit([trade], bars, patience=8)
    assert trade.bs_type == "1"


def test_calibrate_risk_selects_highest_feasible_value(tmp_path):
    spec = make_spec(tmp_path)
    trade = make_trade(
        open_ts=parse_utc("2021-06-01"),
        close_ts=parse_utc("2021-06-02"),
        profit_rate=-2.0,
    )
    rows, selected = calibrate_risk([trade], spec)
    feasible = [row for row in rows if row["passed"]]
    assert selected["risk_pct"] == max(row["risk_pct"] for row in feasible)


def test_reference_comparison_reports_metric_path():
    report = {
        "schema_version": 1,
        "strategy_id": "freeze_v4",
        "execution_model": "legacy-v1",
        "result": {"risk_pct": 0.0075, "is_2125": {"cagr": 0.4}},
    }
    reference = {
        "schema_version": 1,
        "strategy_id": "freeze_v4",
        "execution_model": "legacy-v1",
        "risk_pct": 0.0075,
        "is_2125": {"cagr": 0.5},
    }
    assert compare_reference(report, reference) == [
        {"path": "is_2125.cagr", "expected": 0.5, "actual": 0.4}
    ]


def write_fixture_inputs(tmp_path):
    s1_open = parse_utc("2021-06-01T01:00:00Z")
    s2_open = parse_utc("2025-06-01T04:00:00Z")
    (tmp_path / "s1.json").write_text(
        json.dumps(
            [
                {
                    "open_ts": s1_open,
                    "close_ts": s1_open + 3600,
                    "profit_rate": 2.0,
                    "risk_rate": 0.02,
                    "bs_type": "1",
                    "is_buy": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "s2.json").write_text(
        json.dumps(
            [
                {
                    "open_ts": s2_open,
                    "close_ts": s2_open + 14400,
                    "profit_rate": -1.0,
                    "risk_rate": 0.02,
                    "bs_type": "1p",
                    "is_buy": False,
                    "is_pyramid": False,
                }
            ]
        ),
        encoding="utf-8",
    )
    with sqlite3.connect(tmp_path / "bars.db") as connection:
        connection.execute(
            "create table kline ("
            "ts integer, symbol text, lv text, o real, h real, l real, c real)"
        )
        for open_ts, level, interval in (
            (s1_open, "K_60M", 3600000),
            (s2_open, "K_4H", 14400000),
        ):
            raw_ts = int(open_ts * 1000) - interval
            connection.executemany(
                "insert into kline values (?, 'BTC/USDT', ?, ?, ?, ?, ?)",
                [
                    (raw_ts, level, 100.0, 100.0, 100.0, 100.0),
                    (raw_ts + interval, level, 100.0, 101.0, 99.0, 100.0),
                ],
            )


def test_run_baseline_builds_provenance_rich_is_report(tmp_path):
    spec = make_spec(tmp_path)
    write_fixture_inputs(tmp_path)
    report = run_baseline(
        spec,
        research_root=tmp_path,
        provenance={"commit": "test", "dirty": False},
    )
    assert report["execution_model"] == "legacy-v1"
    assert report["result"]["risk_pct"] == 0.01
    assert report["inputs"]["s1_trades"]["trade_count"] == 1
    assert report["inputs"]["bars"]["K_60M"]["row_count"] == 2
    assert report["provenance"]["commit"] == "test"


@pytest.mark.skipif(
    "CHANPY_RESEARCH_ROOT" not in os.environ,
    reason="set CHANPY_RESEARCH_ROOT to verify the external research data",
)
def test_real_freeze_v4_matches_reference():
    repo_root = Path(__file__).resolve().parents[2]
    spec = load_spec(
        repo_root
        / "ModelStrategy/research/configs/freeze_v4_legacy_v1.json"
    )
    report = run_baseline(
        spec,
        research_root=Path(os.environ["CHANPY_RESEARCH_ROOT"]),
        provenance={"commit": "test", "dirty": False},
    )
    reference = json.loads(
        (
            repo_root
            / "ModelStrategy/research/baselines/freeze_v4_legacy_v1.json"
        ).read_text(encoding="utf-8")
    )
    assert compare_reference(report, reference) == []
