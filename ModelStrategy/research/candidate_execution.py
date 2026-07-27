"""Conservative entry auditing and z-exit replay for the v5 candidate."""

import math
from dataclasses import replace
from typing import Iterable

from .boundary import ResearchBoundaryError
from .candidate import CandidateTrade
from .execution import (
    ExecutionIntent,
    ExecutionTrade,
    ReplayOutcome,
    build_intent,
    record_fill,
    replay_trade,
)
from .market import MarketDataError, MarketSeries
from .schema import ResearchTrade


def _signal_type(bs_type: str) -> str:
    return ",".join(part.removeprefix("z") for part in bs_type.split(","))


def _initial_stop(source: CandidateTrade) -> float:
    direction = 1 if source.is_buy else -1
    return source.open_price * (1 - direction * source.risk_rate)


def _require_closed(source: CandidateTrade) -> None:
    if not source.is_closed:
        raise ValueError("open candidate trade cannot be certified")


def audit_strategy_fill(
    source: CandidateTrade,
    bars: MarketSeries,
    *,
    stack: str,
    stop_slippage: float,
) -> ExecutionTrade:
    """Audit a strategy-owned fill against its exact raw market bar."""
    _require_closed(source)
    fill_bar = bars.at(source.entry_ts)
    if fill_bar.synthetic:
        raise MarketDataError("synthetic bar cannot support a strategy fill")
    maker = source.bs_type.startswith("z") and not source.is_pyramid
    if maker:
        if not fill_bar.low <= source.open_price <= fill_bar.high:
            raise MarketDataError("strategy maker fill price was not touched")
        entry_role = "maker"
        entry_timing = "intrabar_limit"
        adverse_bar = fill_bar
    else:
        if not math.isclose(
            source.open_price,
            fill_bar.close,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise MarketDataError("strategy taker fill must equal bar close")
        entry_role = "taker"
        entry_timing = "bar_close"
        adverse_bar = None
    intent = ExecutionIntent(
        symbol=bars.symbol,
        signal_ts=source.entry_ts,
        close_ts=source.close_ts,
        limit_price=source.open_price,
        close_price=source.close_price,
        initial_sl_price=_initial_stop(source),
        risk_rate=source.risk_rate,
        risk_mult=1.0,
        bs_type=_signal_type(source.bs_type),
        is_buy=source.is_buy,
        is_pyramid=source.is_pyramid,
        stack=stack,
        exit_role="taker",
        reason=source.reason,
    )
    return record_fill(
        intent,
        fill_ts=source.entry_ts,
        open_price=source.open_price,
        entry_role=entry_role,
        entry_timing=entry_timing,
        fill_bar=adverse_bar,
        stop_slippage=stop_slippage,
    )


def replay_signal_intent(
    source: CandidateTrade,
    bars: MarketSeries,
    *,
    stack: str,
    patience: int,
    stop_slippage: float,
) -> ReplayOutcome:
    """Replay a normalized strategy signal through the Stage-2 entry model."""
    _require_closed(source)
    signal_bar = bars.at(source.entry_ts)
    if not math.isclose(
        source.open_price,
        signal_bar.close,
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise MarketDataError("source signal price does not match market close")
    direction = 1 if source.is_buy else -1
    profit_rate = (
        direction * (source.close_price / source.open_price - 1) * 100
    )
    intent_source = ResearchTrade(
        open_ts=source.entry_ts,
        close_ts=source.close_ts,
        profit_rate=profit_rate,
        risk_rate=source.risk_rate,
        bs_type=_signal_type(source.bs_type),
        is_buy=source.is_buy,
        is_pyramid=source.is_pyramid,
        reason=source.reason,
        close_price=source.close_price,
    )
    intent = build_intent(
        intent_source, bars, stack=stack, symbol=bars.symbol
    )
    return replay_trade(
        intent,
        bars,
        patience=patience,
        stop_slippage=stop_slippage,
    )


def replay_zexit(
    trade: ExecutionTrade,
    bars: MarketSeries,
    *,
    eligible_reasons: Iterable[str],
    patience: int,
    end_exclusive_ts: float,
) -> ExecutionTrade:
    """Replay a close-signal limit through first touch, then patience chase."""
    if bars.symbol != trade.symbol:
        raise ValueError("exit symbol does not match market series")
    if type(patience) is not int or patience <= 0:
        raise ValueError("exit patience must be a positive integer")
    if trade.reason not in set(eligible_reasons):
        return trade
    coverage_begin = trade.close_ts + bars.interval_seconds
    coverage_end = trade.close_ts + patience * bars.interval_seconds
    if coverage_end >= end_exclusive_ts:
        raise ResearchBoundaryError(
            "OOS data would be required to finish z-exit replay"
        )
    real_bars = {
        current.ts: current
        for current in bars.bars
        if not current.synthetic
    }
    window = []
    for index in range(patience):
        expected = coverage_begin + index * bars.interval_seconds
        current = real_bars.get(expected)
        if current is None:
            raise MarketDataError(
                f"exit market gap for {trade.symbol} at {expected}"
            )
        window.append(current)
    for current in window:
        if current.low <= trade.close_price <= current.high:
            return replace(
                trade,
                close_ts=current.ts,
                exit_role="maker",
            )
    chased = window[-1]
    return replace(
        trade,
        close_ts=chased.ts,
        close_price=chased.close,
        exit_role="taker",
    )
