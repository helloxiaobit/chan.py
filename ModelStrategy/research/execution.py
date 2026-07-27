"""Deterministic execution replay for conservative research."""

import math
from dataclasses import dataclass
from typing import Any

from .market import MarketBar, MarketDataError, MarketSeries
from .schema import ResearchTrade


def _finite(name: str, value: Any, *, positive: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        suffix = " and positive" if positive else ""
        raise ValueError(f"{name} must be finite{suffix}")
    return result


@dataclass(frozen=True)
class ExecutionIntent:
    symbol: str
    signal_ts: float
    close_ts: float
    limit_price: float
    close_price: float
    initial_sl_price: float
    risk_rate: float
    risk_mult: float
    bs_type: str
    is_buy: bool
    is_pyramid: bool
    stack: str
    exit_role: str
    reason: str | None

    def __post_init__(self) -> None:
        if not self.symbol or not self.stack or not self.bs_type:
            raise ValueError("execution intent strings must be non-empty")
        signal_ts = _finite("signal_ts", self.signal_ts)
        close_ts = _finite("close_ts", self.close_ts)
        if close_ts < signal_ts:
            raise ValueError("close_ts must not precede signal_ts")
        for name in (
            "limit_price",
            "close_price",
            "initial_sl_price",
            "risk_rate",
            "risk_mult",
        ):
            object.__setattr__(
                self, name, _finite(name, getattr(self, name), positive=True)
            )
        if type(self.is_buy) is not bool or type(self.is_pyramid) is not bool:
            raise ValueError("execution intent direction flags must be boolean")
        if self.exit_role not in {"maker", "taker"}:
            raise ValueError("exit_role must be maker or taker")
        object.__setattr__(self, "signal_ts", signal_ts)
        object.__setattr__(self, "close_ts", close_ts)


@dataclass(frozen=True)
class ExecutionTrade:
    symbol: str
    signal_ts: float
    fill_ts: float
    close_ts: float
    is_buy: bool
    open_price: float
    close_price: float
    initial_sl_price: float
    risk_rate: float
    risk_mult: float
    bs_type: str
    stack: str
    entry_role: str
    entry_timing: str
    exit_role: str
    is_pyramid: bool
    reason: str

    def __post_init__(self) -> None:
        if not self.symbol or not self.stack or not self.bs_type or not self.reason:
            raise ValueError("execution trade strings must be non-empty")
        signal_ts = _finite("signal_ts", self.signal_ts)
        fill_ts = _finite("fill_ts", self.fill_ts)
        close_ts = _finite("close_ts", self.close_ts)
        if signal_ts > fill_ts or fill_ts > close_ts:
            raise ValueError("execution timestamps must satisfy signal <= fill <= close")
        for name in (
            "open_price",
            "close_price",
            "initial_sl_price",
            "risk_rate",
            "risk_mult",
        ):
            object.__setattr__(
                self, name, _finite(name, getattr(self, name), positive=True)
            )
        if type(self.is_buy) is not bool or type(self.is_pyramid) is not bool:
            raise ValueError("execution trade direction flags must be boolean")
        if self.entry_role not in {"maker", "taker"}:
            raise ValueError("entry_role must be maker or taker")
        if self.exit_role not in {"maker", "taker"}:
            raise ValueError("exit_role must be maker or taker")
        if self.entry_timing not in {"intrabar_limit", "bar_close"}:
            raise ValueError(
                "entry_timing must be intrabar_limit or bar_close"
            )
        object.__setattr__(self, "signal_ts", signal_ts)
        object.__setattr__(self, "fill_ts", fill_ts)
        object.__setattr__(self, "close_ts", close_ts)

    @property
    def direction(self) -> int:
        return 1 if self.is_buy else -1


@dataclass(frozen=True)
class ReplayOutcome:
    status: str
    trade: ExecutionTrade | None
    reason: str

    def __post_init__(self) -> None:
        if self.status not in {"filled", "unfilled"}:
            raise ValueError("replay status must be filled or unfilled")
        if (self.status == "filled") != (self.trade is not None):
            raise ValueError("filled replay status must match trade presence")
        if not self.reason:
            raise ValueError("replay reason must be non-empty")


def build_intent(
    trade: ResearchTrade,
    bars: MarketSeries,
    *,
    stack: str,
    symbol: str,
) -> ExecutionIntent:
    """Reconstruct price-bearing intent fields from a legacy trade cache."""
    if bars.symbol != symbol:
        raise ValueError("intent symbol does not match market series")
    signal_bar = bars.at(trade.open_ts)
    if signal_bar.synthetic:
        raise MarketDataError("synthetic market bar cannot define a signal price")
    limit_price = signal_bar.close
    direction = 1 if trade.is_buy else -1
    close_price = (
        trade.close_price
        if trade.close_price is not None
        else limit_price * (1 + direction * trade.profit_rate / 100.0)
    )
    initial_sl_price = limit_price * (1 - direction * trade.risk_rate)
    return ExecutionIntent(
        symbol=symbol,
        signal_ts=trade.open_ts,
        close_ts=trade.close_ts,
        limit_price=limit_price,
        close_price=close_price,
        initial_sl_price=initial_sl_price,
        risk_rate=trade.risk_rate,
        risk_mult=trade.risk_mult,
        bs_type=trade.bs_type,
        is_buy=trade.is_buy,
        is_pyramid=trade.is_pyramid,
        stack=stack,
        exit_role="maker" if trade.exit_maker else "taker",
        reason=trade.reason,
    )


def _stop_touched(intent: ExecutionIntent, bar: MarketBar) -> bool:
    if intent.is_buy:
        return bar.low <= intent.initial_sl_price
    return bar.high >= intent.initial_sl_price


def _filled_trade(
    intent: ExecutionIntent,
    *,
    fill_ts: float,
    open_price: float,
    entry_role: str,
    entry_timing: str,
    fill_bar: MarketBar | None,
    stop_slippage: float,
) -> ExecutionTrade:
    close_ts = intent.close_ts
    close_price = intent.close_price
    exit_role = intent.exit_role
    reason = intent.reason or "strategy_exit"
    if (
        entry_role == "maker"
        and fill_bar is not None
        and _stop_touched(intent, fill_bar)
    ):
        close_ts = fill_ts
        close_price = intent.initial_sl_price * (
            1 - stop_slippage if intent.is_buy else 1 + stop_slippage
        )
        exit_role = "taker"
        reason = "same_bar_stop"
    return ExecutionTrade(
        symbol=intent.symbol,
        signal_ts=intent.signal_ts,
        fill_ts=fill_ts,
        close_ts=close_ts,
        is_buy=intent.is_buy,
        open_price=open_price,
        close_price=close_price,
        initial_sl_price=intent.initial_sl_price,
        risk_rate=abs(open_price - intent.initial_sl_price) / open_price,
        risk_mult=intent.risk_mult,
        bs_type=intent.bs_type,
        stack=intent.stack,
        entry_role=entry_role,
        entry_timing=entry_timing,
        exit_role=exit_role,
        is_pyramid=intent.is_pyramid,
        reason=reason,
    )


def replay_trade(
    intent: ExecutionIntent,
    bars: MarketSeries,
    *,
    patience: int,
    stop_slippage: float,
) -> ReplayOutcome:
    """Replay a limit intent with first-touch, chase, and adverse-stop rules."""
    if bars.symbol != intent.symbol:
        raise ValueError("replay symbol does not match market series")
    if type(patience) is not int or patience <= 0:
        raise ValueError("patience must be a positive integer")
    slippage = _finite("stop_slippage", stop_slippage)
    if slippage < 0 or slippage >= 1:
        raise ValueError("stop_slippage must be at least zero and below one")

    if intent.is_pyramid:
        replayed = _filled_trade(
            intent,
            fill_ts=intent.signal_ts,
            open_price=intent.limit_price,
            entry_role="taker",
            entry_timing="bar_close",
            fill_bar=None,
            stop_slippage=slippage,
        )
        return ReplayOutcome("filled", replayed, "pyramid_market")

    real_bars_seen = 0
    for current in bars.bars:
        if current.ts <= intent.signal_ts or current.synthetic:
            continue
        if current.ts > intent.close_ts:
            break
        real_bars_seen += 1
        touched = (
            current.low <= intent.limit_price
            if intent.is_buy
            else current.high >= intent.limit_price
        )
        if touched:
            stop_touched = _stop_touched(intent, current)
            if current.ts == intent.close_ts and not stop_touched:
                return ReplayOutcome(
                    "unfilled", None, "touch_at_original_close"
                )
            replayed = _filled_trade(
                intent,
                fill_ts=current.ts,
                open_price=intent.limit_price,
                entry_role="maker",
                entry_timing="intrabar_limit",
                fill_bar=current,
                stop_slippage=slippage,
            )
            return ReplayOutcome("filled", replayed, "limit_touch")
        if real_bars_seen >= patience:
            if current.ts >= intent.close_ts:
                return ReplayOutcome(
                    "unfilled", None, "patience_reached_at_close"
                )
            replayed = _filled_trade(
                intent,
                fill_ts=current.ts,
                open_price=current.close,
                entry_role="taker",
                entry_timing="bar_close",
                fill_bar=None,
                stop_slippage=slippage,
            )
            return ReplayOutcome("filled", replayed, "patience_chase")
    return ReplayOutcome("unfilled", None, "no_fill_before_close")
