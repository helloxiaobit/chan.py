"""Auditable, IS-only BTC gate for the preregistered v5 candidate."""

import math
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from .candidate import CandidateDataset, load_candidate_dataset
from .candidate_execution import (
    audit_strategy_fill,
    replay_signal_intent,
    replay_zexit,
)
from .boundary import IS_END_EXCLUSIVE
from .certification_spec import CertificationSpec, load_certification_spec
from .conservative_baseline import (
    ConservativeAssembly,
    apply_execution_conviction,
    evaluate_conservative_grid,
)
from .execution import ReplayOutcome
from .market import (
    MarketSeries,
    load_funding_events,
    load_market_series,
    require_funding_coverage,
)
from .provenance import file_manifest, git_provenance, runtime_provenance


BTC = "BTC/USDT"
UNOPENED_AFTER_BTC = (
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "shared_multi",
    "OOS",
)
_REFERENCE_KEYS = (
    "schema_version",
    "strategy_id",
    "execution_model",
    "status",
    "stop_reason",
    "spec_hash",
    "selected_risk_pct",
    "btc",
    "gates",
    "execution",
    "input_hashes",
    "unopened_tiers",
)


def _input_path(root: Path, relative: Path) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"input escapes configured root: {relative}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def resolve_btc_inputs(
    spec: CertificationSpec,
    research_root: str | Path,
    market_data_root: str | Path,
) -> dict[str, Path]:
    """Resolve only the current BTC tier; later symbols remain unopened."""
    research = Path(research_root)
    market = Path(market_data_root)
    if not research.is_dir():
        raise FileNotFoundError(research)
    if not market.is_dir():
        raise FileNotFoundError(market)
    btc_inputs = spec.symbol_inputs[BTC]
    return {
        "s1_trades": _input_path(research, btc_inputs["s1_trades"]),
        "s2_trades": _input_path(research, btc_inputs["s2_trades"]),
        "bars_db": _input_path(research, spec.bars_db),
        "funding_rates": _input_path(market, btc_inputs["funding_rates"]),
    }


def _candidate_manifest(
    dataset: CandidateDataset, path: Path, relative: Path
) -> dict[str, Any]:
    return {
        "path": relative.as_posix(),
        **file_manifest(path),
        "schema_version": 2,
        "entry_kind": dataset.entry_kind,
        "stack": dataset.stack,
        "trade_count": len(dataset.trades),
        "first_entry_ts": min(trade.entry_ts for trade in dataset.trades),
        "last_close_ts": max(trade.close_ts for trade in dataset.trades),
        "source": asdict(dataset.source),
    }


def _load_entry_series(
    spec: CertificationSpec, paths: Mapping[str, Path]
) -> tuple[MarketSeries, MarketSeries]:
    s1 = spec.stacks["s1"]
    s2 = spec.stacks["s2"]
    return (
        load_market_series(
            paths["bars_db"],
            BTC,
            s1["level"],
            s1["interval_ms"],
            spec.begin_ts,
            spec.end_ts,
        ),
        load_market_series(
            paths["bars_db"],
            BTC,
            s2["level"],
            s2["interval_ms"],
            spec.begin_ts,
            spec.end_ts,
        ),
    )


def _replay_candidate_entries(
    spec: CertificationSpec,
    s1_dataset: CandidateDataset,
    s2_dataset: CandidateDataset,
    s1_bars: MarketSeries,
    s2_bars: MarketSeries,
) -> tuple[ReplayOutcome, ...]:
    outcomes = []
    for source in s1_dataset.trades:
        trade = audit_strategy_fill(
            source,
            s1_bars,
            stack=s1_dataset.stack,
            stop_slippage=spec.execution["stop_slippage"],
        )
        trade = replay_zexit(
            trade,
            s1_bars,
            eligible_reasons=spec.exit_policy["eligible_reasons"],
            patience=spec.exit_policy["patience"],
            end_exclusive_ts=spec.end_ts,
        )
        outcomes.append(ReplayOutcome("filled", trade, "strategy_fill"))
    for source in s2_dataset.trades:
        outcome = replay_signal_intent(
            source,
            s2_bars,
            stack=s2_dataset.stack,
            patience=spec.execution["entry_patience"],
            stop_slippage=spec.execution["stop_slippage"],
        )
        if outcome.trade is not None:
            trade = replay_zexit(
                outcome.trade,
                s2_bars,
                eligible_reasons=spec.exit_policy["eligible_reasons"],
                patience=spec.exit_policy["patience"],
                end_exclusive_ts=spec.end_ts,
            )
            outcome = ReplayOutcome(outcome.status, trade, outcome.reason)
        outcomes.append(outcome)
    return tuple(outcomes)


def assemble_btc_candidate(
    spec: CertificationSpec,
    research_root: str | Path,
    market_data_root: str | Path,
) -> ConservativeAssembly:
    """Assemble the current BTC IS tier without resolving later-tier inputs."""
    if spec.execution_model != "conservative-v2":
        raise ValueError("candidate assembly requires conservative-v2")
    if spec.execution["source_timestamp_offset_seconds"] != 0:
        raise ValueError("normalized candidate inputs must use zero execution offset")
    paths = resolve_btc_inputs(spec, research_root, market_data_root)
    relative = spec.symbol_inputs[BTC]
    s1_dataset = load_candidate_dataset(
        paths["s1_trades"],
        expected_symbol=BTC,
        expected_stack=spec.stacks["s1"]["name"],
        expected_entry_kind=spec.stacks["s1"]["entry_kind"],
    )
    s2_dataset = load_candidate_dataset(
        paths["s2_trades"],
        expected_symbol=BTC,
        expected_stack=spec.stacks["s2"]["name"],
        expected_entry_kind=spec.stacks["s2"]["entry_kind"],
    )
    s1_bars, s2_bars = _load_entry_series(spec, paths)
    outcomes = _replay_candidate_entries(
        spec, s1_dataset, s2_dataset, s1_bars, s2_bars
    )
    filled = tuple(
        outcome.trade for outcome in outcomes if outcome.trade is not None
    )
    trades = apply_execution_conviction(filled, spec.conviction)

    if (
        spec.execution["mark_level"] == spec.stacks["s1"]["level"]
        and spec.execution["mark_ms"] == spec.stacks["s1"]["interval_ms"]
    ):
        raw_marks = s1_bars
    else:
        raw_marks = load_market_series(
            paths["bars_db"],
            BTC,
            spec.execution["mark_level"],
            spec.execution["mark_ms"],
            spec.begin_ts,
            spec.end_ts,
        )
    marks = raw_marks.carry_forward_gaps(
        spec.execution["max_mark_gap_intervals"]
    )
    marks.require_coverage(
        spec.begin_ts,
        spec.end_ts - spec.execution["mark_ms"] / 1000,
    )
    funding, funding_manifest = load_funding_events(
        paths["funding_rates"],
        BTC,
        spec.begin_ts,
        spec.end_ts,
        sealed_end_year=(
            2026 if spec.end_ts == IS_END_EXCLUSIVE else None
        ),
    )
    require_funding_coverage(
        funding,
        BTC,
        spec.begin_ts,
        spec.end_ts,
        spec.execution["funding_interval_ms"] // 1000,
    )
    inputs = {
        "s1_trades": _candidate_manifest(
            s1_dataset, paths["s1_trades"], relative["s1_trades"]
        ),
        "s2_trades": _candidate_manifest(
            s2_dataset, paths["s2_trades"], relative["s2_trades"]
        ),
        "bars_db": {"path": spec.bars_db.as_posix()},
        "entry_bars": {
            s1_dataset.stack: s1_bars.manifest,
            s2_dataset.stack: s2_bars.manifest,
        },
        "marks": marks.manifest,
        "funding": {
            "path": relative["funding_rates"].as_posix(),
            **funding_manifest,
        },
    }
    return ConservativeAssembly(
        trades=trades,
        outcomes=outcomes,
        marks=marks,
        funding=funding,
        inputs=inputs,
    )


def _gate(
    name: str, rule: Mapping[str, Any], observed: Any, passed: bool
) -> dict[str, Any]:
    return {
        "name": name,
        "rule": dict(rule),
        "observed": observed,
        "passed": bool(passed),
    }


def evaluate_btc_gates(
    risk_rows: Iterable[Mapping[str, Any]],
    *,
    target_max_drawdown: float,
    gates: Mapping[str, Any],
) -> dict[str, Any]:
    """Select the frozen risk first, then stop at the first failed BTC gate."""
    rows = [dict(row) for row in risk_rows]
    eligible = [
        row
        for row in rows
        if row.get("worst_dd") is not None
        and row["worst_dd"] <= target_max_drawdown
    ]
    selected = max(eligible, key=lambda row: row["risk_pct"]) if eligible else None
    attempted = [
        _gate(
            "risk_selection",
            {
                "policy": "highest_grid_risk_with_worst_dd_lte",
                "max_drawdown": target_max_drawdown,
            },
            {
                "eligible_risk_pct": [row["risk_pct"] for row in eligible],
                "selected_risk_pct": (
                    selected["risk_pct"] if selected is not None else None
                ),
            },
            selected is not None,
        )
    ]
    if selected is None:
        return {
            "selected": None,
            "gates": attempted,
            "status": "rejected",
            "stop_reason": "risk_selection",
        }

    calmar = selected.get("calmar")
    passed = calmar is not None and calmar >= gates["full_calmar_min"]
    attempted.append(
        _gate(
            "btc_full_calmar",
            {"minimum_inclusive": gates["full_calmar_min"]},
            calmar,
            passed,
        )
    )
    if not passed:
        return {
            "selected": selected,
            "gates": attempted,
            "status": "rejected",
            "stop_reason": "btc_full_calmar",
        }

    split_cagrs = {
        name: metrics["cagr"]
        for name, metrics in selected["splits"].items()
    }
    floor = gates["split_cagr_min_exclusive"]
    passed = all(value > floor for value in split_cagrs.values())
    attempted.append(
        _gate(
            "btc_split_cagr",
            {"minimum_exclusive": floor},
            split_cagrs,
            passed,
        )
    )
    if not passed:
        return {
            "selected": selected,
            "gates": attempted,
            "status": "rejected",
            "stop_reason": "btc_split_cagr",
        }

    observed_dd = selected["worst_dd"]
    passed = observed_dd <= gates["max_drawdown"]
    attempted.append(
        _gate(
            "btc_max_drawdown",
            {"maximum_inclusive": gates["max_drawdown"]},
            observed_dd,
            passed,
        )
    )
    return {
        "selected": selected,
        "gates": attempted,
        "status": "passed" if passed else "rejected",
        "stop_reason": None if passed else "btc_max_drawdown",
    }


def _execution_stats(outcomes: Iterable[ReplayOutcome]) -> dict[str, int]:
    values = tuple(outcomes)
    filled = tuple(
        outcome.trade for outcome in values if outcome.trade is not None
    )
    return {
        "intents": len(values),
        "filled": len(filled),
        "unfilled": sum(outcome.status == "unfilled" for outcome in values),
        "maker_entries": sum(trade.entry_role == "maker" for trade in filled),
        "taker_entries": sum(trade.entry_role == "taker" for trade in filled),
        "maker_exits": sum(trade.exit_role == "maker" for trade in filled),
        "taker_exits": sum(trade.exit_role == "taker" for trade in filled),
        "same_bar_stops": sum(
            trade.reason == "same_bar_stop" for trade in filled
        ),
    }


def _input_hashes(inputs: Mapping[str, Any]) -> dict[str, str]:
    s1_stack = "S1bz[4H,1H,15M]"
    s2_stack = "S2py10[1D,4H]"
    return {
        "s1_trades": inputs["s1_trades"]["sha256"],
        "s2_trades": inputs["s2_trades"]["sha256"],
        "s1_bars": inputs["entry_bars"][s1_stack]["sha256"],
        "s2_bars": inputs["entry_bars"][s2_stack]["sha256"],
        "marks": inputs["marks"]["sha256"],
        "funding": inputs["funding"]["sha256"],
    }


def _validate_freeze_v4_reference(reference: Mapping[str, Any]) -> None:
    if reference.get("strategy_id") != "freeze_v4":
        raise ValueError("freeze_v4_reference must use strategy_id freeze_v4")
    if reference.get("execution_model") != "conservative-v2":
        raise ValueError(
            "freeze_v4_reference must use execution_model conservative-v2"
        )
    is_result = reference.get("is_2125")
    if not isinstance(is_result, Mapping):
        raise ValueError("freeze_v4_reference must contain is_2125")
    for name in ("cagr", "full_dd", "calmar"):
        value = is_result.get(name)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"freeze_v4_reference is_2125.{name} must be finite")


def run_btc_is_certification(
    spec: CertificationSpec | str | Path,
    research_root: str | Path,
    market_data_root: str | Path,
    freeze_v4_reference: Mapping[str, Any],
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run exactly the BTC 2021-2025 gate and return a freezeable receipt."""
    loaded_spec = (
        load_certification_spec(spec)
        if not isinstance(spec, CertificationSpec)
        else spec
    )
    _validate_freeze_v4_reference(freeze_v4_reference)
    assembly = assemble_btc_candidate(
        loaded_spec, research_root, market_data_root
    )
    rows = evaluate_conservative_grid(assembly, loaded_spec)
    decision = evaluate_btc_gates(
        rows,
        target_max_drawdown=loaded_spec.portfolio["target_max_drawdown"],
        gates=loaded_spec.gates["btc"],
    )
    selected = decision["selected"]
    btc = None
    delta = None
    if selected is not None:
        btc = {
            "total_return": selected["total_return"],
            "cagr": selected["cagr"],
            "full_dd": selected["full_dd"],
            "worst_dd": selected["worst_dd"],
            "calmar": selected["calmar"],
            "fees": selected["fees"],
            "funding_pnl": selected["funding_pnl"],
            "price_pnl": selected["price_pnl"],
            "trade_cnt": selected["trade_cnt"],
            "win_rate": selected["win_rate"],
            "skipped": selected["skipped"],
            "splits": selected["splits"],
        }
        baseline = freeze_v4_reference["is_2125"]
        delta = {
            "cagr": selected["cagr"] - baseline["cagr"],
            "max_drawdown": selected["full_dd"] - baseline["full_dd"],
            "calmar": selected["calmar"] - baseline["calmar"],
        }
    execution = _execution_stats(assembly.outcomes)
    input_hashes = _input_hashes(assembly.inputs)
    report_provenance = {
        **git_provenance(Path(__file__).resolve().parents[2]),
        "runtime": runtime_provenance(),
    }
    if provenance is not None:
        report_provenance.update(provenance)
    preconditions = [
        _gate(
            "freeze_v4_reference",
            {
                "strategy_id": "freeze_v4",
                "execution_model": "conservative-v2",
            },
            {
                "spec_hash": freeze_v4_reference.get("spec_hash"),
                "risk_pct": freeze_v4_reference.get("risk_pct"),
            },
            True,
        ),
        _gate(
            "btc_inputs",
            {
                "window": "half-open 2021-01-01..2026-01-01",
                "normalized_execution_offset_seconds": 0,
            },
            {"input_hashes": input_hashes, "execution": execution},
            True,
        ),
    ]
    return {
        "schema_version": 1,
        "strategy_id": loaded_spec.strategy_id,
        "execution_model": loaded_spec.execution_model,
        "status": decision["status"],
        "stop_reason": decision["stop_reason"],
        "next_tier": "ETH/USDT" if decision["status"] == "passed" else None,
        "window": {
            "begin_ts": loaded_spec.begin_ts,
            "end_exclusive_ts": loaded_spec.end_ts,
        },
        "spec_hash": loaded_spec.spec_hash,
        "selected_risk_pct": (
            selected["risk_pct"] if selected is not None else None
        ),
        "btc": btc,
        "delta_to_freeze_v4": delta,
        "freeze_v4_reference": dict(freeze_v4_reference),
        "gates": preconditions + decision["gates"],
        "execution": execution,
        "inputs": assembly.inputs,
        "input_hashes": input_hashes,
        "risk_calibration": rows,
        "unopened_tiers": list(UNOPENED_AFTER_BTC),
        "provenance": report_provenance,
    }


def certification_reference_payload(
    report: Mapping[str, Any],
) -> dict[str, Any]:
    return {name: deepcopy(report.get(name)) for name in _REFERENCE_KEYS}


def compare_certification_reference(
    report: Mapping[str, Any], reference: Mapping[str, Any]
) -> list[dict[str, Any]]:
    actual = certification_reference_payload(report)
    mismatches = []

    def visit(path: str, expected: Any, observed: Any) -> None:
        if isinstance(expected, Mapping):
            if not isinstance(observed, Mapping):
                mismatches.append(
                    {"path": path, "expected": expected, "actual": observed}
                )
                return
            if set(expected) != set(observed):
                mismatches.append(
                    {
                        "path": f"{path}.keys" if path else "keys",
                        "expected": sorted(expected),
                        "actual": sorted(observed),
                    }
                )
                return
            for key, value in expected.items():
                child = f"{path}.{key}" if path else str(key)
                visit(child, value, observed.get(key))
            return
        if isinstance(expected, list):
            if not isinstance(observed, list) or len(expected) != len(observed):
                mismatches.append(
                    {"path": path, "expected": expected, "actual": observed}
                )
                return
            for index, value in enumerate(expected):
                visit(f"{path}[{index}]", value, observed[index])
            return
        equal = expected == observed
        if isinstance(expected, float) and isinstance(observed, (int, float)):
            equal = math.isclose(
                expected, float(observed), rel_tol=0.0, abs_tol=1e-12
            )
        if not equal:
            mismatches.append(
                {"path": path, "expected": expected, "actual": observed}
            )

    visit("", reference, actual)
    return mismatches
