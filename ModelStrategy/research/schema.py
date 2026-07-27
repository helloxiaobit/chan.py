"""Validated trade-cache schema shared by reproducible research commands."""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .boundary import require_is_timestamp


def _finite_float(name: str, value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


@dataclass
class ResearchTrade:
    """Portable trade record with the attributes expected by portfolio_eval."""

    open_ts: float
    close_ts: float
    profit_rate: float
    risk_rate: float
    bs_type: str
    is_buy: bool
    is_pyramid: bool = False
    reason: str | None = None
    close_price: float | None = None
    stack: str | None = None
    exit_maker: bool = False
    risk_mult: float = 1.0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ResearchTrade":
        open_ts = _finite_float("open_ts", value.get("open_ts"))
        close_ts = _finite_float("close_ts", value.get("close_ts"))
        if close_ts < open_ts:
            raise ValueError("close_ts must be greater than or equal to open_ts")

        risk_rate = _finite_float("risk_rate", value.get("risk_rate"))
        if risk_rate <= 0:
            raise ValueError("risk_rate must be positive")

        bs_type = value.get("bs_type")
        if not isinstance(bs_type, str) or not bs_type:
            raise ValueError("bs_type must be a non-empty string")
        is_buy = value.get("is_buy")
        if type(is_buy) is not bool:
            raise ValueError("is_buy must be a boolean")
        is_pyramid = value.get("is_pyramid", False)
        if type(is_pyramid) is not bool:
            raise ValueError("is_pyramid must be a boolean")
        exit_maker = value.get("exit_maker", False)
        if type(exit_maker) is not bool:
            raise ValueError("exit_maker must be a boolean")

        close_price_value = value.get("close_price")
        close_price = (
            None
            if close_price_value is None
            else _finite_float("close_price", close_price_value)
        )
        risk_mult = _finite_float("risk_mult", value.get("risk_mult", 1.0))
        if risk_mult <= 0:
            raise ValueError("risk_mult must be positive")

        reason = value.get("reason")
        stack = value.get("stack")
        return cls(
            open_ts=open_ts,
            close_ts=close_ts,
            profit_rate=_finite_float("profit_rate", value.get("profit_rate")),
            risk_rate=risk_rate,
            bs_type=bs_type,
            is_buy=is_buy,
            is_pyramid=is_pyramid,
            reason=None if reason is None else str(reason),
            close_price=close_price,
            stack=None if stack is None else str(stack),
            exit_maker=exit_maker,
            risk_mult=risk_mult,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "open_ts": self.open_ts,
            "close_ts": self.close_ts,
            "profit_rate": self.profit_rate,
            "risk_rate": self.risk_rate,
            "bs_type": self.bs_type,
            "is_buy": self.is_buy,
            "is_pyramid": self.is_pyramid,
            "reason": self.reason,
            "close_price": self.close_price,
            "stack": self.stack,
            "exit_maker": self.exit_maker,
            "risk_mult": self.risk_mult,
        }


def load_trades(path: str | Path, *, is_only: bool = True) -> list[ResearchTrade]:
    """Load a JSON trade list and optionally enforce the IS-only boundary."""
    with Path(path).open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, list):
        raise ValueError("trade cache must contain a JSON list")

    trades = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise ValueError(f"trade cache item {index} must be an object")
        trade = ResearchTrade.from_mapping(item)
        if is_only:
            require_is_timestamp(trade.open_ts)
            require_is_timestamp(trade.close_ts)
        trades.append(trade)
    return trades
