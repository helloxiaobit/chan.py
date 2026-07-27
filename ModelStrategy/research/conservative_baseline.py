"""Assembly, calibration, and reporting for conservative-v2."""

import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from .conservative import (
    ConservativeConfig,
    ConservativeResult,
    conservative_portfolio_eval,
)
from .execution import ExecutionTrade, ReplayOutcome, build_intent, replay_trade
from .market import (
    FundingEvent,
    MarketSeries,
    load_funding_events,
    load_market_series,
    require_funding_coverage,
)
from .provenance import file_manifest, git_provenance, runtime_provenance
from .schema import ResearchTrade, load_trades
from .spec import ResearchSpec, load_spec


S1_STACK = "S1[4H,1H]"
S2_STACK = "S2py10[1D,4H]"
SYMBOL = "BTC/USDT"


@dataclass(frozen=True)
class ConservativeAssembly:
    trades: tuple[ExecutionTrade, ...]
    outcomes: tuple[ReplayOutcome, ...]
    marks: MarketSeries
    funding: tuple[FundingEvent, ...]
    inputs: dict[str, Any]


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


def _require_trade_window(
    trades: Iterable[ResearchTrade], spec: ResearchSpec, input_name: str
) -> None:
    for index, trade in enumerate(trades):
        if not (
            spec.begin_ts <= trade.open_ts < spec.end_ts
            and spec.begin_ts <= trade.close_ts < spec.end_ts
        ):
            raise ValueError(
                f"{input_name} trade {index} is outside declared window"
            )


def normalize_source_timestamps(
    trades: Iterable[ResearchTrade],
    *,
    offset_seconds: int,
    begin_ts: float,
    end_ts: float,
    input_name: str,
) -> tuple[ResearchTrade, ...]:
    """Translate declared legacy epochs before any market or boundary decision."""
    if type(offset_seconds) is not int:
        raise ValueError("timestamp offset must be a whole-second integer")
    corrected = tuple(
        replace(
            trade,
            open_ts=trade.open_ts + offset_seconds,
            close_ts=trade.close_ts + offset_seconds,
        )
        for trade in trades
    )
    for index, trade in enumerate(corrected):
        if not (
            begin_ts <= trade.open_ts < end_ts
            and begin_ts <= trade.close_ts < end_ts
        ):
            raise ValueError(
                f"{input_name} trade {index} is outside declared window"
            )
    return corrected


def _trade_manifest(
    path: Path,
    relative: Path,
    raw_trades: Iterable[ResearchTrade],
    corrected_trades: Iterable[ResearchTrade],
    offset_seconds: int,
) -> dict[str, Any]:
    raw_values = tuple(raw_trades)
    values = tuple(corrected_trades)
    return {
        "path": relative.as_posix(),
        **file_manifest(path),
        "trade_count": len(values),
        "timestamp_offset_seconds": offset_seconds,
        "raw_first_open_ts": min(
            (trade.open_ts for trade in raw_values), default=None
        ),
        "raw_last_close_ts": max(
            (trade.close_ts for trade in raw_values), default=None
        ),
        "corrected_first_open_ts": min(
            (trade.open_ts for trade in values), default=None
        ),
        "corrected_last_close_ts": max(
            (trade.close_ts for trade in values), default=None
        ),
        "first_open_ts": min(
            (trade.open_ts for trade in values), default=None
        ),
        "last_close_ts": max(
            (trade.close_ts for trade in values), default=None
        ),
    }


def _execution_key(trade: ExecutionTrade) -> tuple[Any, ...]:
    return (
        trade.fill_ts,
        trade.close_ts,
        trade.symbol,
        trade.stack,
        trade.bs_type,
        trade.is_buy,
        trade.open_price,
        trade.close_price,
        trade.reason,
    )


def apply_execution_conviction(
    trades: Iterable[ExecutionTrade], conviction: Mapping[str, Any]
) -> tuple[ExecutionTrade, ...]:
    """Restamp conviction using actual fills and same-bar atomic ordering."""
    values = tuple(trades)
    events = []
    for trade in values:
        key = _execution_key(trade)
        if trade.fill_ts == trade.close_ts:
            events.append((trade.fill_ts, 1, key, "round_trip", trade))
        else:
            events.append((trade.close_ts, 0, key, "close", trade))
            events.append((trade.fill_ts, 2, key, "open", trade))
    events.sort(key=lambda item: (item[0], item[1], item[2]))
    open_directions: dict[ExecutionTrade, bool] = {}
    adjusted = {}

    def stamp(trade: ExecutionTrade) -> ExecutionTrade:
        same = sum(
            direction == trade.is_buy
            for direction in open_directions.values()
        )
        opposite = len(open_directions) - same
        multiplier = 1.0
        if same:
            multiplier *= conviction["co_dir_mult"]
        if opposite:
            multiplier *= conviction["opp_dir_mult"]
        multiplier *= conviction["bs_mults"].get(trade.bs_type, 1.0)
        return replace(
            trade,
            risk_mult=min(multiplier, conviction["mult_cap"]),
        )

    for _, _, _, kind, trade in events:
        if kind == "close":
            open_directions.pop(trade, None)
        elif kind == "round_trip":
            adjusted[trade] = stamp(trade)
        else:
            adjusted[trade] = stamp(trade)
            open_directions[trade] = trade.is_buy
    return tuple(
        sorted((adjusted[trade] for trade in values), key=_execution_key)
    )


def assemble_conservative(
    spec: ResearchSpec,
    research_root: str | Path,
    market_data_root: str | Path,
) -> ConservativeAssembly:
    if spec.execution_model != "conservative-v2":
        raise ValueError("conservative assembly requires conservative-v2")
    research = Path(research_root)
    market = Path(market_data_root)
    if not research.is_dir():
        raise FileNotFoundError(research)
    if not market.is_dir():
        raise FileNotFoundError(market)
    paths = {
        "s1_trades": _input_path(research, spec.inputs["s1_trades"]),
        "s2_trades": _input_path(research, spec.inputs["s2_trades"]),
        "bars_db": _input_path(research, spec.inputs["bars_db"]),
        "funding_rates": _input_path(
            market, spec.inputs["funding_rates"]
        ),
    }
    raw_s1 = load_trades(paths["s1_trades"], is_only=False)
    raw_s2 = load_trades(paths["s2_trades"], is_only=False)
    offset = spec.execution["source_timestamp_offset_seconds"]
    s1 = normalize_source_timestamps(
        raw_s1,
        offset_seconds=offset,
        begin_ts=spec.begin_ts,
        end_ts=spec.end_ts,
        input_name="s1_trades",
    )
    s2 = normalize_source_timestamps(
        raw_s2,
        offset_seconds=offset,
        begin_ts=spec.begin_ts,
        end_ts=spec.end_ts,
        input_name="s2_trades",
    )
    _require_trade_window(s1, spec, "s1_trades")
    _require_trade_window(s2, spec, "s2_trades")

    loaded_series = {}

    def series(level: str, interval_ms: int) -> MarketSeries:
        key = (level, interval_ms)
        if key not in loaded_series:
            loaded_series[key] = load_market_series(
                paths["bars_db"],
                SYMBOL,
                level,
                interval_ms,
                spec.begin_ts,
                spec.end_ts,
            )
        return loaded_series[key]

    s1_bars = series(spec.zlimit["s1_level"], spec.zlimit["s1_ms"])
    s2_bars = series(spec.zlimit["s2_level"], spec.zlimit["s2_ms"])
    outcomes = []
    for stack, source, bars in (
        (S1_STACK, s1, s1_bars),
        (S2_STACK, s2, s2_bars),
    ):
        for source_trade in source:
            intent = build_intent(
                source_trade, bars, stack=stack, symbol=SYMBOL
            )
            outcomes.append(
                replay_trade(
                    intent,
                    bars,
                    patience=spec.execution["entry_patience"],
                    stop_slippage=spec.execution["stop_slippage"],
                )
            )
    filled = tuple(
        outcome.trade for outcome in outcomes if outcome.trade is not None
    )
    stamped = apply_execution_conviction(filled, spec.conviction)

    raw_marks = series(
        spec.execution["mark_level"], spec.execution["mark_ms"]
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
        SYMBOL,
        spec.begin_ts,
        spec.end_ts,
    )
    require_funding_coverage(
        funding,
        SYMBOL,
        spec.begin_ts,
        spec.end_ts,
        spec.execution["funding_interval_ms"] // 1000,
    )
    input_manifest = {
        "s1_trades": _trade_manifest(
            paths["s1_trades"],
            spec.inputs["s1_trades"],
            raw_s1,
            s1,
            offset,
        ),
        "s2_trades": _trade_manifest(
            paths["s2_trades"],
            spec.inputs["s2_trades"],
            raw_s2,
            s2,
            offset,
        ),
        "bars_db": {"path": spec.inputs["bars_db"].as_posix()},
        "entry_bars": {
            S1_STACK: s1_bars.manifest,
            S2_STACK: s2_bars.manifest,
        },
        "marks": marks.manifest,
        "funding": {
            "path": spec.inputs["funding_rates"].as_posix(),
            **funding_manifest,
        },
    }
    return ConservativeAssembly(
        trades=stamped,
        outcomes=tuple(outcomes),
        marks=marks,
        funding=funding,
        inputs=input_manifest,
    )


def _portfolio_config(
    spec: ResearchSpec, risk_pct: float
) -> ConservativeConfig:
    return ConservativeConfig(
        risk_pct=risk_pct,
        taker_fee=spec.portfolio["taker_fee"],
        maker_fee=spec.portfolio["maker_fee"],
        max_concurrent=spec.portfolio["max_concurrent"],
        max_leverage=spec.portfolio["max_leverage"],
        max_pos_leverage=spec.portfolio["max_pos_leverage"],
    )


def _slice_series(
    series: MarketSeries, begin_ts: float, end_ts: float
) -> MarketSeries:
    bars = tuple(
        bar for bar in series.bars if begin_ts <= bar.ts < end_ts
    )
    if not bars:
        raise ValueError("split contains no mark bars")
    manifest = {
        **series.manifest,
        "slice_begin_ts": begin_ts,
        "slice_end_exclusive_ts": end_ts,
        "slice_row_count": len(bars),
    }
    return MarketSeries(
        series.symbol, series.interval_seconds, bars, manifest
    )


def _metrics(result: ConservativeResult) -> dict[str, Any]:
    return {
        "total_return": result.total_return,
        "cagr": result.cagr,
        "dd": result.max_drawdown,
        "calmar": result.calmar if math.isfinite(result.calmar) else None,
        "trade_cnt": result.trade_cnt,
        "win_rate": result.win_rate,
        "skipped": len(result.skipped_trades),
    }


def calibrate_conservative(
    assembly: ConservativeAssembly, spec: ResearchSpec
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = evaluate_conservative_grid(assembly, spec)
    selected = next((row for row in reversed(rows) if row["passed"]), None)
    if selected is None:
        raise ValueError("no risk_grid value satisfies target_max_drawdown")
    return rows, selected


def evaluate_conservative_grid(
    assembly: ConservativeAssembly, spec: ResearchSpec
) -> list[dict[str, Any]]:
    """Evaluate every frozen risk row without requiring one to pass."""
    rows = []
    interval = assembly.marks.interval_seconds
    for risk_pct in spec.risk_grid:
        config = _portfolio_config(spec, risk_pct)
        full = conservative_portfolio_eval(
            assembly.trades,
            {SYMBOL: assembly.marks},
            assembly.funding,
            config,
        )
        splits = {}
        for name, (begin_ts, end_ts) in spec.splits.items():
            split_trades = tuple(
                trade
                for trade in assembly.trades
                if begin_ts <= trade.fill_ts < end_ts
            )
            horizon_end = max(
                end_ts,
                max(
                    (trade.close_ts + interval for trade in split_trades),
                    default=end_ts,
                ),
            )
            split_marks = _slice_series(
                assembly.marks, begin_ts, horizon_end
            )
            split_funding = tuple(
                event
                for event in assembly.funding
                if begin_ts <= event.ts < horizon_end
            )
            splits[name] = _metrics(
                conservative_portfolio_eval(
                    split_trades,
                    {SYMBOL: split_marks},
                    split_funding,
                    config,
                )
            )
        worst_dd = max(
            full.max_drawdown,
            max(value["dd"] for value in splits.values()),
        )
        row = {
            "risk_pct": risk_pct,
            "total_return": full.total_return,
            "cagr": full.cagr,
            "full_dd": full.max_drawdown,
            "worst_dd": worst_dd,
            "calmar": full.calmar if math.isfinite(full.calmar) else None,
            "fees": full.fees,
            "funding_pnl": full.funding_pnl,
            "price_pnl": full.price_pnl,
            "trade_cnt": full.trade_cnt,
            "win_rate": full.win_rate,
            "skipped": len(full.skipped_trades),
            "splits": splits,
            "passed": worst_dd <= spec.portfolio["target_max_drawdown"],
        }
        rows.append(row)
    return rows


def _execution_stats(outcomes: Iterable[ReplayOutcome]) -> dict[str, int]:
    values = tuple(outcomes)
    filled = tuple(
        outcome.trade for outcome in values if outcome.trade is not None
    )
    return {
        "filled": len(filled),
        "maker_fills": sum(trade.entry_role == "maker" for trade in filled),
        "taker_fills": sum(trade.entry_role == "taker" for trade in filled),
        "same_bar_stops": sum(
            trade.reason == "same_bar_stop" for trade in filled
        ),
        "unfilled": sum(outcome.status == "unfilled" for outcome in values),
    }


def _input_hashes(inputs: Mapping[str, Any]) -> dict[str, str]:
    return {
        "s1_trades": inputs["s1_trades"]["sha256"],
        "s2_trades": inputs["s2_trades"]["sha256"],
        "s1_bars": inputs["entry_bars"][S1_STACK]["sha256"],
        "s2_bars": inputs["entry_bars"][S2_STACK]["sha256"],
        "marks": inputs["marks"]["sha256"],
        "funding": inputs["funding"]["sha256"],
    }


def run_conservative_comparison(
    spec: ResearchSpec | str | Path,
    research_root: str | Path,
    market_data_root: str | Path,
    legacy_reference: Mapping[str, Any],
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    loaded_spec = load_spec(spec) if not isinstance(spec, ResearchSpec) else spec
    if legacy_reference.get("execution_model") != "legacy-v1":
        raise ValueError("legacy_reference must use legacy-v1")
    if legacy_reference.get("strategy_id") != loaded_spec.strategy_id:
        raise ValueError("legacy_reference strategy_id does not match spec")
    assembly = assemble_conservative(
        loaded_spec, research_root, market_data_root
    )
    rows, selected = calibrate_conservative(assembly, loaded_spec)
    execution = _execution_stats(assembly.outcomes)
    legacy_is = legacy_reference["is_2125"]
    legacy_calmar = (
        legacy_is["cagr"] / legacy_is["full_dd"]
        if legacy_is["full_dd"] > 0
        else None
    )
    conservative_calmar = selected["calmar"]
    report_provenance = {
        **git_provenance(Path(__file__).resolve().parents[2]),
        "runtime": runtime_provenance(),
    }
    if provenance is not None:
        report_provenance.update(provenance)
    conservative = {
        "risk_pct": selected["risk_pct"],
        "is_2125": {
            "total_return": selected["total_return"],
            "cagr": selected["cagr"],
            "full_dd": selected["full_dd"],
            "worst_dd": selected["worst_dd"],
            "calmar": conservative_calmar,
            "splits": selected["splits"],
        },
        "fees": selected["fees"],
        "funding_pnl": selected["funding_pnl"],
        "price_pnl": selected["price_pnl"],
        "trade_cnt": selected["trade_cnt"],
        "win_rate": selected["win_rate"],
        "skipped": selected["skipped"],
    }
    return {
        "schema_version": 1,
        "strategy_id": loaded_spec.strategy_id,
        "execution_model": loaded_spec.execution_model,
        "window": {
            "begin_ts": loaded_spec.begin_ts,
            "end_exclusive_ts": loaded_spec.end_ts,
        },
        "spec_hash": loaded_spec.spec_hash,
        "legacy_reference": dict(legacy_reference),
        "conservative": conservative,
        "delta": {
            "cagr": selected["cagr"] - legacy_is["cagr"],
            "max_drawdown": selected["full_dd"] - legacy_is["full_dd"],
            "calmar": (
                conservative_calmar - legacy_calmar
                if conservative_calmar is not None
                and legacy_calmar is not None
                else None
            ),
        },
        "execution": execution,
        "inputs": assembly.inputs,
        "input_hashes": _input_hashes(assembly.inputs),
        "risk_calibration": rows,
        "provenance": report_provenance,
    }


def conservative_reference_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    conservative = report["conservative"]
    return {
        "schema_version": report["schema_version"],
        "strategy_id": report["strategy_id"],
        "execution_model": report["execution_model"],
        "spec_hash": report["spec_hash"],
        "risk_pct": conservative["risk_pct"],
        "is_2125": conservative["is_2125"],
        "fees": conservative["fees"],
        "funding_pnl": conservative["funding_pnl"],
        "price_pnl": conservative["price_pnl"],
        "trade_cnt": conservative["trade_cnt"],
        "win_rate": conservative["win_rate"],
        "skipped": conservative["skipped"],
        "execution": report["execution"],
        "input_hashes": report["input_hashes"],
    }


def compare_conservative_reference(
    report: Mapping[str, Any], reference: Mapping[str, Any]
) -> list[dict[str, Any]]:
    actual = conservative_reference_payload(report)
    mismatches = []

    def visit(path: str, expected: Any, observed: Any) -> None:
        if isinstance(expected, Mapping):
            if not isinstance(observed, Mapping):
                mismatches.append(
                    {"path": path, "expected": expected, "actual": observed}
                )
                return
            for key, value in expected.items():
                child = f"{path}.{key}" if path else str(key)
                visit(child, value, observed.get(key))
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
