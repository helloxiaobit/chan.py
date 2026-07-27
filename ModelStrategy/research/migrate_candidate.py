"""Explicit trusted-pickle migration into the portable candidate schema."""

import math
import os
import pickle
import tempfile
from pathlib import Path
from typing import Any

from .boundary import IS_END_EXCLUSIVE
from .candidate import CandidateTrade
from .provenance import canonical_json_bytes, file_manifest


_REQUIRED_ATTRIBUTES = (
    "code",
    "open_ts",
    "close_ts",
    "open_price",
    "close_price",
    "risk_rate",
    "bs_type",
    "is_buy",
    "is_pyramid",
    "reason",
    "is_closed",
)


def _attribute(record: Any, name: str, index: int) -> Any:
    if not hasattr(record, name):
        raise ValueError(f"migration record {index} is missing {name}")
    return getattr(record, name)


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _source_timestamp(value: Any, name: str, index: int) -> float:
    if isinstance(value, bool):
        raise ValueError(f"migration record {index} {name} must be finite")
    try:
        timestamp = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"migration record {index} {name} must be finite"
        ) from exc
    if not math.isfinite(timestamp):
        raise ValueError(f"migration record {index} {name} must be finite")
    return timestamp


def migrate_candidate_pickle(
    source_path: str | Path,
    output_path: str | Path,
    *,
    symbol: str,
    stack: str,
    entry_kind: str,
    begin_ts: float,
    end_ts: float,
    timestamp_offset_seconds: int,
) -> dict[str, Any]:
    """Migrate one explicitly trusted IS pickle; never use this in certification."""
    source = Path(source_path)
    output = Path(output_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if entry_kind not in {"strategy_fill", "signal_intent"}:
        raise ValueError("entry_kind must be strategy_fill or signal_intent")
    if begin_ts >= end_ts:
        raise ValueError("migration window must be increasing")
    if end_ts > IS_END_EXCLUSIVE:
        raise ValueError("OOS migration window is not allowed")
    if (
        type(timestamp_offset_seconds) is not int
        or not -86400 <= timestamp_offset_seconds <= 86400
    ):
        raise ValueError(
            "timestamp_offset_seconds must be a whole-second integer between "
            "-86400 and 86400"
        )

    with source.open("rb") as stream:
        raw_records = pickle.load(stream)
    if not isinstance(raw_records, list):
        raise ValueError("trusted pickle must contain a list")

    trades = []
    raw_entry_timestamps = []
    raw_close_timestamps = []
    for index, record in enumerate(raw_records):
        values = {
            name: _attribute(record, name, index)
            for name in _REQUIRED_ATTRIBUTES
        }
        if values.pop("code") != symbol:
            raise ValueError(f"migration record {index} symbol mismatch")
        raw_entry_ts = _source_timestamp(values["open_ts"], "open_ts", index)
        raw_close_ts = _source_timestamp(values["close_ts"], "close_ts", index)
        raw_entry_timestamps.append(raw_entry_ts)
        raw_close_timestamps.append(raw_close_ts)
        trade = CandidateTrade.from_mapping(
            {
                "entry_ts": raw_entry_ts + timestamp_offset_seconds,
                "close_ts": raw_close_ts + timestamp_offset_seconds,
                "open_price": values["open_price"],
                "close_price": values["close_price"],
                "risk_rate": values["risk_rate"],
                "bs_type": values["bs_type"],
                "is_buy": values["is_buy"],
                "is_pyramid": values["is_pyramid"],
                "reason": values["reason"],
                "is_closed": values["is_closed"],
            }
        )
        if not (
            begin_ts <= trade.entry_ts < end_ts
            and begin_ts <= trade.close_ts < end_ts
        ):
            raise ValueError(f"migration record {index} is outside declared window")
        trades.append(trade)

    if not trades:
        raise ValueError("trusted pickle must contain at least one record")
    if len(set(trades)) != len(trades):
        raise ValueError("duplicate migration record")
    trades.sort(
        key=lambda trade: (
            trade.entry_ts,
            trade.close_ts,
            trade.bs_type,
            trade.is_buy,
            trade.open_price,
            trade.close_price,
            trade.reason,
        )
    )
    envelope = {
        "schema_version": 2,
        "entry_kind": entry_kind,
        "symbol": symbol,
        "stack": stack,
        "source": {
            "path": source.name,
            **file_manifest(source),
            "timestamp_offset_seconds": timestamp_offset_seconds,
            "raw_entry_ts_min": min(raw_entry_timestamps),
            "raw_close_ts_max": max(raw_close_timestamps),
            "corrected_entry_ts_min": min(
                trade.entry_ts for trade in trades
            ),
            "corrected_close_ts_max": max(
                trade.close_ts for trade in trades
            ),
        },
        "trades": [trade.to_mapping() for trade in trades],
    }
    _write_atomic(output, canonical_json_bytes(envelope))
    return envelope
