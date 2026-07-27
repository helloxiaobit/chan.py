import csv
import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from ModelStrategy.research.certification import (
    assemble_btc_candidate,
    certification_reference_payload,
    compare_certification_reference,
    evaluate_btc_gates,
    resolve_btc_inputs,
    run_btc_is_certification,
)
from ModelStrategy.research.boundary import parse_utc
from ModelStrategy.research.certification_spec import CertificationSpec
from ModelStrategy.research.provenance import canonical_json_bytes


def risk_row(
    risk_pct,
    *,
    calmar=2.5,
    full_dd=0.2,
    worst_dd=0.2,
    split_cagrs=(0.1, 0.2, 0.3),
):
    return {
        "risk_pct": risk_pct,
        "calmar": calmar,
        "full_dd": full_dd,
        "worst_dd": worst_dd,
        "splits": {
            name: {"cagr": value, "dd": worst_dd, "calmar": calmar}
            for name, value in zip(("A", "B", "C"), split_cagrs)
        },
    }


BTC_GATES = {
    "full_calmar_min": 2.0,
    "split_cagr_min_exclusive": 0.0,
    "max_drawdown": 0.25,
}


def test_btc_gates_select_highest_drawdown_compliant_risk_then_stop_in_order():
    decision = evaluate_btc_gates(
        [
            risk_row(0.005, calmar=3.0),
            risk_row(0.01, calmar=1.9),
            risk_row(0.015, worst_dd=0.26),
        ],
        target_max_drawdown=0.25,
        gates=BTC_GATES,
    )
    assert decision["selected"]["risk_pct"] == 0.01
    assert [gate["name"] for gate in decision["gates"]] == [
        "risk_selection",
        "btc_full_calmar",
    ]
    assert decision["status"] == "rejected"
    assert decision["stop_reason"] == "btc_full_calmar"


def test_btc_gates_require_every_split_positive_and_drawdown_compliant():
    decision = evaluate_btc_gates(
        [risk_row(0.005, split_cagrs=(0.1, 0.0, 0.2))],
        target_max_drawdown=0.25,
        gates=BTC_GATES,
    )
    assert [gate["name"] for gate in decision["gates"]] == [
        "risk_selection",
        "btc_full_calmar",
        "btc_split_cagr",
    ]
    assert decision["status"] == "rejected"
    assert decision["stop_reason"] == "btc_split_cagr"


def test_btc_gates_pass_only_after_all_preregistered_checks():
    decision = evaluate_btc_gates(
        [risk_row(0.005)],
        target_max_drawdown=0.25,
        gates=BTC_GATES,
    )
    assert [gate["name"] for gate in decision["gates"]] == [
        "risk_selection",
        "btc_full_calmar",
        "btc_split_cagr",
        "btc_max_drawdown",
    ]
    assert all(gate["passed"] for gate in decision["gates"])
    assert decision["status"] == "passed"
    assert decision["stop_reason"] is None


def test_btc_gates_freeze_rejection_when_no_risk_is_compliant():
    decision = evaluate_btc_gates(
        [risk_row(0.005, worst_dd=0.251)],
        target_max_drawdown=0.25,
        gates=BTC_GATES,
    )
    assert decision["selected"] is None
    assert decision["status"] == "rejected"
    assert decision["stop_reason"] == "risk_selection"
    assert len(decision["gates"]) == 1


def test_btc_input_resolution_never_touches_later_symbols(tmp_path):
    research_root = tmp_path / "research"
    market_root = tmp_path / "market"
    research_root.mkdir()
    market_root.mkdir()
    for relative in ("btc-s1.json", "btc-s2.json", "btc.db"):
        (research_root / relative).write_text("fixture", encoding="utf-8")
    (market_root / "btc-funding.csv").write_text("fixture", encoding="utf-8")
    spec = SimpleNamespace(
        bars_db=Path("btc.db"),
        symbol_inputs={
            "BTC/USDT": {
                "s1_trades": Path("btc-s1.json"),
                "s2_trades": Path("btc-s2.json"),
                "funding_rates": Path("btc-funding.csv"),
            },
            "ETH/USDT": {
                "s1_trades": Path("missing-eth-s1.json"),
                "s2_trades": Path("missing-eth-s2.json"),
                "funding_rates": Path("missing-eth-funding.csv"),
            },
        },
    )
    paths = resolve_btc_inputs(spec, research_root, market_root)
    assert set(paths) == {"s1_trades", "s2_trades", "bars_db", "funding_rates"}
    assert all("eth" not in str(path).lower() for path in paths.values())


def candidate_report():
    return {
        "schema_version": 1,
        "strategy_id": "freeze_v5_candidate_v1",
        "execution_model": "conservative-v2",
        "status": "rejected",
        "stop_reason": "btc_full_calmar",
        "spec_hash": "a" * 64,
        "selected_risk_pct": 0.005,
        "btc": {"cagr": 0.3, "full_dd": 0.2, "calmar": 1.5},
        "gates": [{"name": "btc_full_calmar", "passed": False}],
        "execution": {"filled": 1},
        "input_hashes": {"s1_trades": "b" * 64},
        "unopened_tiers": ["ETH/USDT", "SOL/USDT", "BNB/USDT", "OOS"],
    }


def test_candidate_reference_is_compact_and_reports_exact_mismatch_path():
    report = candidate_report()
    reference = certification_reference_payload(report)
    assert compare_certification_reference(report, reference) == []
    reference["selected_risk_pct"] = 0.01
    assert compare_certification_reference(report, reference) == [
        {
            "path": "selected_risk_pct",
            "expected": 0.01,
            "actual": 0.005,
        }
    ]


def test_candidate_reference_rejects_empty_or_partial_shapes():
    report = candidate_report()
    assert compare_certification_reference(report, {})
    reference = certification_reference_payload(report)
    reference.pop("execution")
    assert compare_certification_reference(report, reference)
    reference = certification_reference_payload(report)
    reference["btc"].pop("calmar")
    assert compare_certification_reference(report, reference)


def _write_candidate(path, *, stack, entry_kind, entry_ts, close_ts, bs_type):
    payload = {
        "schema_version": 2,
        "entry_kind": entry_kind,
        "symbol": "BTC/USDT",
        "stack": stack,
        "source": {
            "path": "trusted.pkl",
            "size": 1,
            "sha256": "a" * 64,
            "timestamp_offset_seconds": 0,
            "raw_entry_ts_min": entry_ts,
            "raw_close_ts_max": close_ts,
            "corrected_entry_ts_min": entry_ts,
            "corrected_close_ts_max": close_ts,
        },
        "trades": [
            {
                "entry_ts": entry_ts,
                "close_ts": close_ts,
                "open_price": 100.0,
                "close_price": 105.0,
                "risk_rate": 0.05,
                "bs_type": bs_type,
                "is_buy": True,
                "is_pyramid": False,
                "reason": "stop_loss",
                "is_closed": True,
            }
        ],
    }
    path.write_bytes(canonical_json_bytes(payload))


def _candidate_fixture(tmp_path):
    begin = parse_utc("2021-01-01")
    end = parse_utc("2021-01-02")
    _write_candidate(
        tmp_path / "btc-s1.json",
        stack="S1bz[4H,1H,15M]",
        entry_kind="strategy_fill",
        entry_ts=begin + 3600,
        close_ts=begin + 5 * 3600,
        bs_type="z1",
    )
    _write_candidate(
        tmp_path / "btc-s2.json",
        stack="S2py10[1D,4H]",
        entry_kind="signal_intent",
        entry_ts=begin + 4 * 3600,
        close_ts=begin + 12 * 3600,
        bs_type="1p",
    )
    with sqlite3.connect(tmp_path / "btc.db") as connection:
        connection.execute(
            "create table kline ("
            "ts integer, symbol text, lv text, o real, h real, l real, c real)"
        )
        rows = []
        for level, interval in (("K_60M", 3600), ("K_4H", 14400)):
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
    with (tmp_path / "btc-funding.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(["symbol", "fundingTime", "fundingRate", "markPrice"])
        for hour in (0, 8, 16):
            writer.writerow(
                [
                    "BTCUSDT",
                    f"2021-01-01T{hour:02d}:00:00+00:00",
                    0.0001,
                    "",
                ]
            )
    symbol_inputs = {
        "BTC/USDT": {
            "s1_trades": Path("btc-s1.json"),
            "s2_trades": Path("btc-s2.json"),
            "funding_rates": Path("btc-funding.csv"),
        },
        "ETH/USDT": {
            "s1_trades": Path("missing-eth-s1.json"),
            "s2_trades": Path("missing-eth-s2.json"),
            "funding_rates": Path("missing-eth-funding.csv"),
        },
    }
    spec = CertificationSpec(
        source_path=tmp_path / "spec.json",
        raw={"fixture": True},
        strategy_id="freeze_v5_candidate_v1",
        execution_model="conservative-v2",
        begin_ts=begin,
        end_ts=end,
        oos_begin_ts=parse_utc("2026-01-01"),
        oos_end_ts=parse_utc("2026-07-27"),
        components=(),
        symbols=("BTC/USDT", "ETH/USDT"),
        bars_db=Path("btc.db"),
        symbol_inputs=symbol_inputs,
        stacks={
            "s1": {
                "name": "S1bz[4H,1H,15M]",
                "entry_kind": "strategy_fill",
                "level": "K_60M",
                "interval_ms": 3600000,
            },
            "s2": {
                "name": "S2py10[1D,4H]",
                "entry_kind": "signal_intent",
                "level": "K_4H",
                "interval_ms": 14400000,
            },
        },
        exit_policy={"eligible_reasons": (), "patience": 8},
        risk_grid=(0.005,),
        portfolio={
            "taker_fee": 0.0005,
            "maker_fee": 0.0002,
            "max_concurrent": 4,
            "max_leverage": 3.0,
            "max_pos_leverage": 1.5,
            "target_max_drawdown": 0.25,
        },
        conviction={
            "co_dir_mult": 1.5,
            "opp_dir_mult": 1.0,
            "bs_mults": {"1": 0.8, "1p": 1.2},
            "mult_cap": 2.0,
        },
        execution={
            "source_timestamp_offset_seconds": 0,
            "mark_level": "K_60M",
            "mark_ms": 3600000,
            "entry_patience": 8,
            "stop_slippage": 0.0005,
            "same_bar_policy": "adverse_first",
            "funding_order": "before_close",
            "funding_interval_ms": 28800000,
            "market_gap_policy": "carry_forward",
            "max_mark_gap_intervals": 16,
        },
        splits={"fixture": (begin, end)},
        gates={"btc": BTC_GATES},
    )
    return spec


def test_btc_assembly_and_report_use_only_current_is_tier(tmp_path):
    spec = _candidate_fixture(tmp_path)
    assembly = assemble_btc_candidate(spec, tmp_path, tmp_path)
    assert len(assembly.outcomes) == 2
    assert len(assembly.trades) == 2
    assert set(assembly.inputs) == {
        "s1_trades",
        "s2_trades",
        "bars_db",
        "entry_bars",
        "marks",
        "funding",
    }
    freeze_v4 = {
        "strategy_id": "freeze_v4",
        "execution_model": "conservative-v2",
        "risk_pct": 0.005,
        "spec_hash": "f" * 64,
        "is_2125": {"cagr": 0.1, "full_dd": 0.1, "calmar": 1.0},
    }
    report = run_btc_is_certification(
        spec,
        tmp_path,
        tmp_path,
        freeze_v4,
        provenance={"commit": "test", "dirty": False},
    )
    assert report["execution"]["intents"] == 2
    assert report["selected_risk_pct"] == 0.005
    assert report["unopened_tiers"][-1] == "OOS"
    assert report["inputs"]["s1_trades"]["last_close_ts"] < spec.end_ts


@pytest.mark.skipif(
    "CHANPY_RESEARCH_ROOT" not in os.environ
    or "CHANPY_MARKET_DATA_ROOT" not in os.environ,
    reason="set research and market roots to verify the frozen BTC receipt",
)
def test_real_btc_candidate_matches_frozen_rejection_reference():
    repo_root = Path(__file__).resolve().parents[2]
    reference = json.loads(
        (
            repo_root
            / "ModelStrategy"
            / "research"
            / "baselines"
            / "freeze_v5_candidate_v1_is.json"
        ).read_text(encoding="utf-8")
    )
    freeze_v4 = json.loads(
        (
            repo_root
            / "ModelStrategy"
            / "research"
            / "baselines"
            / "freeze_v4_conservative_v2.json"
        ).read_text(encoding="utf-8")
    )
    report = run_btc_is_certification(
        repo_root
        / "ModelStrategy"
        / "research"
        / "configs"
        / "freeze_v5_candidate_v1.json",
        os.environ["CHANPY_RESEARCH_ROOT"],
        os.environ["CHANPY_MARKET_DATA_ROOT"],
        freeze_v4,
        provenance={"commit": "test", "dirty": False},
    )
    assert compare_certification_reference(report, reference) == []
    assert report["status"] == "rejected"
    assert report["stop_reason"] == "btc_full_calmar"
    assert report["unopened_tiers"][-1] == "OOS"
