"""Portable, price-bearing candidate inputs for formal certification."""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .boundary import require_is_timestamp


_ENVELOPE_KEYS = {
    "schema_version",
    "entry_kind",
    "symbol",
    "stack",
    "source",
    "trades",
}
_SOURCE_KEYS = {"path", "size", "sha256"}
_TRADE_KEYS = {
    "entry_ts",
    "close_ts",
    "open_price",
    "close_price",
    "risk_rate",
    "bs_type",
    "is_buy",
    "is_pyramid",
    "reason",
    "is_closed",
}


def _exact_keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{name} keys must be exactly {sorted(expected)}")


def _non_empty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _finite(value: Any, name: str, *, positive: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        suffix = " and positive" if positive else ""
        raise ValueError(f"{name} must be finite{suffix}")
    return result


@dataclass(frozen=True)
class CandidateSource:
    path: str
    size: int
    sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CandidateSource":
        _exact_keys(value, _SOURCE_KEYS, "source")
        path_text = _non_empty(value.get("path"), "source.path")
        path = Path(path_text)
        if path.is_absolute() or path.drive or ".." in path.parts:
            raise ValueError("source.path must be a relative path")
        size = value.get("size")
        if type(size) is not int or size < 0:
            raise ValueError("source.size must be a non-negative integer")
        digest = value.get("sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("source.sha256 must be lowercase hexadecimal")
        return cls(path_text, size, digest)


@dataclass(frozen=True)
class CandidateTrade:
    entry_ts: float
    close_ts: float
    open_price: float
    close_price: float
    risk_rate: float
    bs_type: str
    is_buy: bool
    is_pyramid: bool
    reason: str
    is_closed: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CandidateTrade":
        _exact_keys(value, _TRADE_KEYS, "trade")
        entry_ts = require_is_timestamp(_finite(value.get("entry_ts"), "entry_ts"))
        close_ts = require_is_timestamp(_finite(value.get("close_ts"), "close_ts"))
        if close_ts < entry_ts:
            raise ValueError("close_ts must not precede entry_ts")
        is_buy = value.get("is_buy")
        is_pyramid = value.get("is_pyramid")
        is_closed = value.get("is_closed")
        if type(is_buy) is not bool:
            raise ValueError("is_buy must be a boolean")
        if type(is_pyramid) is not bool:
            raise ValueError("is_pyramid must be a boolean")
        if type(is_closed) is not bool:
            raise ValueError("is_closed must be a boolean")
        return cls(
            entry_ts=entry_ts,
            close_ts=close_ts,
            open_price=_finite(value.get("open_price"), "open_price", positive=True),
            close_price=_finite(
                value.get("close_price"), "close_price", positive=True
            ),
            risk_rate=_finite(value.get("risk_rate"), "risk_rate", positive=True),
            bs_type=_non_empty(value.get("bs_type"), "bs_type"),
            is_buy=is_buy,
            is_pyramid=is_pyramid,
            reason=_non_empty(value.get("reason"), "reason"),
            is_closed=is_closed,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "entry_ts": self.entry_ts,
            "close_ts": self.close_ts,
            "open_price": self.open_price,
            "close_price": self.close_price,
            "risk_rate": self.risk_rate,
            "bs_type": self.bs_type,
            "is_buy": self.is_buy,
            "is_pyramid": self.is_pyramid,
            "reason": self.reason,
            "is_closed": self.is_closed,
        }


@dataclass(frozen=True)
class CandidateDataset:
    entry_kind: str
    symbol: str
    stack: str
    source: CandidateSource
    trades: tuple[CandidateTrade, ...]


def load_candidate_dataset(
    path: str | Path,
    *,
    expected_symbol: str | None = None,
    expected_stack: str | None = None,
    expected_entry_kind: str | None = None,
) -> CandidateDataset:
    """Load an IS-only candidate JSON envelope; formal paths never use pickle."""
    with Path(path).open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, Mapping):
        raise ValueError("candidate dataset must contain an object")
    _exact_keys(payload, _ENVELOPE_KEYS, "candidate dataset")
    if payload.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    entry_kind = payload.get("entry_kind")
    if entry_kind not in {"strategy_fill", "signal_intent"}:
        raise ValueError("entry_kind must be strategy_fill or signal_intent")
    symbol = _non_empty(payload.get("symbol"), "symbol")
    stack = _non_empty(payload.get("stack"), "stack")
    if expected_symbol is not None and symbol != expected_symbol:
        raise ValueError("candidate symbol does not match expected symbol")
    if expected_stack is not None and stack != expected_stack:
        raise ValueError("candidate stack does not match expected stack")
    if expected_entry_kind is not None and entry_kind != expected_entry_kind:
        raise ValueError("candidate entry_kind does not match expected entry_kind")
    source_value = payload.get("source")
    if not isinstance(source_value, Mapping):
        raise ValueError("source must be an object")
    trades_value = payload.get("trades")
    if not isinstance(trades_value, list):
        raise ValueError("trades must be a list")
    trades = []
    for index, item in enumerate(trades_value):
        if not isinstance(item, Mapping):
            raise ValueError(f"trade {index} must be an object")
        trades.append(CandidateTrade.from_mapping(item))
    return CandidateDataset(
        entry_kind=entry_kind,
        symbol=symbol,
        stack=stack,
        source=CandidateSource.from_mapping(source_value),
        trades=tuple(trades),
    )
