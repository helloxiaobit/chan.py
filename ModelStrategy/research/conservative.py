"""Event-driven mark-to-market portfolio evaluation."""

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .execution import ExecutionTrade
from .market import FundingEvent, MarketBar, MarketDataError, MarketSeries


class PortfolioError(ValueError):
    """Raised when a conservative portfolio invariant is violated."""


def _finite(name: str, value: Any, *, positive: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PortfolioError(f"{name} must be finite") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        suffix = " and positive" if positive else ""
        raise PortfolioError(f"{name} must be finite{suffix}")
    return result


@dataclass(frozen=True)
class ConservativeConfig:
    risk_pct: float = 0.01
    taker_fee: float = 0.0005
    maker_fee: float = 0.0002
    max_concurrent: int = 4
    max_leverage: float = 3.0
    max_pos_leverage: float = 1.5
    initial_equity: float = 1.0

    def __post_init__(self) -> None:
        for name in (
            "risk_pct",
            "max_leverage",
            "max_pos_leverage",
            "initial_equity",
        ):
            object.__setattr__(
                self, name, _finite(name, getattr(self, name), positive=True)
            )
        for name in ("taker_fee", "maker_fee"):
            value = _finite(name, getattr(self, name))
            if value < 0 or value >= 1:
                raise PortfolioError(f"{name} must be at least zero and below one")
            object.__setattr__(self, name, value)
        if type(self.max_concurrent) is not int or self.max_concurrent <= 0:
            raise PortfolioError("max_concurrent must be a positive integer")


@dataclass(frozen=True)
class EquityPoint:
    ts: float
    kind: str
    equity: float


@dataclass(frozen=True)
class SkippedTrade:
    trade: ExecutionTrade
    reason: str


@dataclass(frozen=True)
class TradeResult:
    trade: ExecutionTrade
    entry_notional: float
    quantity: float
    price_pnl: float
    entry_fee: float
    exit_fee: float
    funding_pnl: float

    @property
    def net_pnl(self) -> float:
        return (
            self.price_pnl
            + self.funding_pnl
            - self.entry_fee
            - self.exit_fee
        )


@dataclass(frozen=True)
class ConservativeResult:
    total_return: float
    cagr: float
    max_drawdown: float
    calmar: float
    fees: float
    funding_pnl: float
    price_pnl: float
    curve: tuple[EquityPoint, ...]
    accepted_trades: tuple[TradeResult, ...]
    skipped_trades: tuple[SkippedTrade, ...]
    span_days: float

    @property
    def trade_cnt(self) -> int:
        return len(self.accepted_trades)

    @property
    def win_rate(self) -> float:
        if not self.accepted_trades:
            return 0.0
        wins = sum(1 for item in self.accepted_trades if item.net_pnl > 0)
        return wins / len(self.accepted_trades)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_return": self.total_return,
            "cagr": self.cagr,
            "max_drawdown": self.max_drawdown,
            "calmar": self.calmar if math.isfinite(self.calmar) else None,
            "fees": self.fees,
            "funding_pnl": self.funding_pnl,
            "price_pnl": self.price_pnl,
            "trade_cnt": self.trade_cnt,
            "win_rate": self.win_rate,
            "skipped": len(self.skipped_trades),
            "span_days": self.span_days,
        }


@dataclass
class _OpenPosition:
    trade: ExecutionTrade
    entry_notional: float
    quantity: float
    last_price: float
    entry_fee: float
    funding_pnl: float = 0.0


def _trade_key(trade: ExecutionTrade) -> tuple[Any, ...]:
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


def _fee_rate(role: str, config: ConservativeConfig) -> float:
    if role == "maker":
        return config.maker_fee
    if role == "taker":
        return config.taker_fee
    raise PortfolioError(f"unknown fee role: {role}")


def _require_trade_coverage(
    trade: ExecutionTrade,
    series: MarketSeries,
    timestamp_set: set[float],
) -> None:
    steps = (trade.close_ts - trade.fill_ts) / series.interval_seconds
    rounded_steps = round(steps)
    if not math.isclose(steps, rounded_steps, abs_tol=1e-9):
        raise MarketDataError("holding window is not mark-interval aligned")
    for index in range(int(rounded_steps) + 1):
        expected = trade.fill_ts + index * series.interval_seconds
        if expected not in timestamp_set:
            raise MarketDataError(
                f"market gap for {trade.symbol} at {expected}"
            )


def conservative_portfolio_eval(
    trades: Iterable[ExecutionTrade],
    marks: Mapping[str, MarketSeries],
    funding_events: Iterable[FundingEvent],
    config: ConservativeConfig | None = None,
) -> ConservativeResult:
    """Evaluate fills using marked equity and explicit cash-flow events."""
    conf = config or ConservativeConfig()
    ordered_trades = tuple(sorted(trades, key=_trade_key))
    if len(set(ordered_trades)) != len(ordered_trades):
        raise PortfolioError("duplicate execution trade")
    if not marks:
        raise PortfolioError("at least one mark series is required")

    timestamp_sets = {
        symbol: set(series.timestamps) for symbol, series in marks.items()
    }
    for trade in ordered_trades:
        series = marks.get(trade.symbol)
        if series is None:
            raise MarketDataError(f"missing mark series for {trade.symbol}")
        _require_trade_coverage(
            trade, series, timestamp_sets[trade.symbol]
        )

    events = []
    for event in funding_events:
        events.append((event.ts, 0, (event.symbol,), "funding", event))
    for trade in ordered_trades:
        key = _trade_key(trade)
        if trade.fill_ts == trade.close_ts:
            events.append((trade.fill_ts, 2, key, "round_trip", trade))
        else:
            events.append((trade.close_ts, 1, key, "close", trade))
            events.append((trade.fill_ts, 3, key, "open", trade))
    for symbol, series in marks.items():
        for bar in series.bars:
            events.append((bar.ts, 4, (symbol,), "mark", (symbol, bar)))
    if not events:
        raise PortfolioError("portfolio timeline is empty")
    events.sort(key=lambda item: (item[0], item[1], item[2]))

    cash = conf.initial_equity
    positions: dict[ExecutionTrade, _OpenPosition] = {}
    accepted = []
    skipped = []
    curve = [EquityPoint(events[0][0], "initial", cash)]
    total_fees = 0.0
    total_funding = 0.0
    total_price_pnl = 0.0

    def equity() -> float:
        unrealized = sum(
            position.trade.direction
            * position.quantity
            * (position.last_price - position.trade.open_price)
            for position in positions.values()
        )
        return cash + unrealized

    def record(ts: float, kind: str) -> None:
        current = equity()
        if not math.isfinite(current) or current <= 0:
            raise PortfolioError(
                f"portfolio equity must remain finite and positive at {kind}"
            )
        curve.append(EquityPoint(ts, kind, current))

    def open_trade(ts: float, trade: ExecutionTrade) -> bool:
        nonlocal cash, total_fees
        if len(positions) >= conf.max_concurrent:
            skipped.append(SkippedTrade(trade, "max_concurrent"))
            return False
        current_equity = equity()
        current_gross = sum(
            position.quantity * position.last_price
            for position in positions.values()
        )
        entry_fee_rate = _fee_rate(trade.entry_role, conf)
        risk_cap = (
            current_equity
            * conf.risk_pct
            * trade.risk_mult
            / trade.risk_rate
        )
        position_cap = (
            conf.max_pos_leverage
            * current_equity
            / (1 + conf.max_pos_leverage * entry_fee_rate)
        )
        leverage_cap = (
            conf.max_leverage * current_equity - current_gross
        ) / (1 + conf.max_leverage * entry_fee_rate)
        notional = min(risk_cap, position_cap, leverage_cap)
        if notional <= 0:
            skipped.append(SkippedTrade(trade, "max_leverage"))
            return False
        entry_fee = notional * entry_fee_rate
        cash -= entry_fee
        total_fees += entry_fee
        positions[trade] = _OpenPosition(
            trade=trade,
            entry_notional=notional,
            quantity=notional / trade.open_price,
            last_price=trade.open_price,
            entry_fee=entry_fee,
        )
        record(ts, "open")
        post_equity = equity()
        post_gross = current_gross + notional
        tolerance = max(1e-12, post_equity * 1e-12)
        if notional > post_equity * conf.max_pos_leverage + tolerance:
            raise PortfolioError("per-position leverage cap was exceeded")
        if post_gross > post_equity * conf.max_leverage + tolerance:
            raise PortfolioError("total leverage cap was exceeded")
        return True

    def close_trade(ts: float, trade: ExecutionTrade) -> None:
        nonlocal cash, total_fees, total_price_pnl
        position = positions.pop(trade, None)
        if position is None:
            return
        price_pnl = (
            trade.direction
            * position.quantity
            * (trade.close_price - trade.open_price)
        )
        exit_value = position.quantity * trade.close_price
        exit_fee = exit_value * _fee_rate(trade.exit_role, conf)
        cash += price_pnl - exit_fee
        total_fees += exit_fee
        total_price_pnl += price_pnl
        accepted.append(
            TradeResult(
                trade=trade,
                entry_notional=position.entry_notional,
                quantity=position.quantity,
                price_pnl=price_pnl,
                entry_fee=position.entry_fee,
                exit_fee=exit_fee,
                funding_pnl=position.funding_pnl,
            )
        )
        record(ts, "close")

    for ts, _, _, kind, payload in events:
        if kind == "funding":
            event = payload
            affected = False
            for position in sorted(positions.values(), key=lambda item: _trade_key(item.trade)):
                if position.trade.symbol != event.symbol:
                    continue
                payment = (
                    -position.trade.direction
                    * position.quantity
                    * position.last_price
                    * event.rate
                )
                cash += payment
                position.funding_pnl += payment
                total_funding += payment
                affected = True
            if affected:
                record(ts, "funding")
        elif kind == "close":
            close_trade(ts, payload)
        elif kind == "round_trip":
            if open_trade(ts, payload):
                close_trade(ts, payload)
        elif kind == "open":
            open_trade(ts, payload)
        elif kind == "mark":
            symbol, bar = payload
            for position in positions.values():
                if position.trade.symbol == symbol:
                    position.last_price = bar.close
            record(ts, "mark_synthetic" if bar.synthetic else "mark")
        else:
            raise PortfolioError(f"unknown portfolio event: {kind}")

    if positions:
        raise PortfolioError("portfolio timeline ended with open positions")
    initial = curve[0].equity
    final = curve[-1].equity
    total_return = final / initial - 1
    span_days = (curve[-1].ts - curve[0].ts) / 86400
    years = max(span_days / 365.0, 1e-6)
    cagr = (final / initial) ** (1 / years) - 1
    peak = initial
    max_drawdown = 0.0
    for point in curve:
        peak = max(peak, point.equity)
        max_drawdown = max(
            max_drawdown, (peak - point.equity) / peak
        )
    calmar = cagr / max_drawdown if max_drawdown > 0 else math.inf
    return ConservativeResult(
        total_return=total_return,
        cagr=cagr,
        max_drawdown=max_drawdown,
        calmar=calmar,
        fees=total_fees,
        funding_pnl=total_funding,
        price_pnl=total_price_pnl,
        curve=tuple(curve),
        accepted_trades=tuple(accepted),
        skipped_trades=tuple(skipped),
        span_days=span_days,
    )
