"""IS-only market and funding timelines for conservative research."""

import bisect
import csv
import hashlib
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .boundary import IS_END_EXCLUSIVE
from .provenance import canonical_json_bytes


class MarketDataError(ValueError):
    """Raised when a market timeline cannot support deterministic replay."""


def _finite(name: str, value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise MarketDataError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise MarketDataError(f"{name} must be finite")
    return result


def _validate_window(begin_ts: float, end_ts: float) -> tuple[float, float]:
    begin = _finite("begin_ts", begin_ts)
    end = _finite("end_ts", end_ts)
    if begin >= end:
        raise MarketDataError("market window must be increasing")
    if end > IS_END_EXCLUSIVE:
        raise MarketDataError("market window cannot extend beyond 2026-01-01")
    return begin, end


@dataclass(frozen=True)
class MarketBar:
    ts: float
    open: float
    high: float
    low: float
    close: float
    synthetic: bool = False

    def __post_init__(self) -> None:
        values = {
            name: _finite(name, value)
            for name, value in (
                ("ts", self.ts),
                ("open", self.open),
                ("high", self.high),
                ("low", self.low),
                ("close", self.close),
            )
        }
        if values["low"] > min(values["open"], values["close"]) or max(
            values["open"], values["close"]
        ) > values["high"]:
            raise MarketDataError("OHLC values are inconsistent")
        if type(self.synthetic) is not bool:
            raise MarketDataError("synthetic flag must be a boolean")
        for name, value in values.items():
            object.__setattr__(self, name, value)


@dataclass(frozen=True)
class FundingEvent:
    ts: float
    symbol: str
    rate: float

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise MarketDataError("funding symbol must be non-empty")
        object.__setattr__(self, "ts", _finite("funding ts", self.ts))
        object.__setattr__(self, "rate", _finite("funding rate", self.rate))


@dataclass(frozen=True)
class MarketSeries:
    symbol: str
    interval_seconds: int
    bars: tuple[MarketBar, ...]
    manifest: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise MarketDataError("market symbol must be non-empty")
        if type(self.interval_seconds) is not int or self.interval_seconds <= 0:
            raise MarketDataError("market interval must be a positive integer")
        bars = tuple(self.bars)
        if any(left.ts >= right.ts for left, right in zip(bars, bars[1:])):
            raise MarketDataError("market timestamps must be strictly increasing")
        object.__setattr__(self, "bars", bars)

    @property
    def timestamps(self) -> tuple[float, ...]:
        return tuple(bar.ts for bar in self.bars)

    def at(self, ts: float) -> MarketBar:
        target = _finite("market timestamp", ts)
        index = bisect.bisect_left(self.timestamps, target)
        if index >= len(self.bars) or self.bars[index].ts != target:
            raise MarketDataError(
                f"missing {self.symbol} market bar at {target}"
            )
        return self.bars[index]

    def bars_between(self, begin_ts: float, end_ts: float) -> tuple[MarketBar, ...]:
        """Return bars in the inclusive timestamp interval."""
        begin = _finite("coverage begin", begin_ts)
        end = _finite("coverage end", end_ts)
        timestamps = self.timestamps
        first = bisect.bisect_left(timestamps, begin)
        last = bisect.bisect_right(timestamps, end)
        return self.bars[first:last]

    def require_coverage(self, begin_ts: float, end_ts: float) -> None:
        """Require every interval endpoint in an inclusive holding window."""
        begin = _finite("coverage begin", begin_ts)
        end = _finite("coverage end", end_ts)
        if begin > end:
            raise MarketDataError("coverage window must be increasing")
        steps = (end - begin) / self.interval_seconds
        rounded_steps = round(steps)
        if not math.isclose(steps, rounded_steps, abs_tol=1e-9):
            raise MarketDataError("coverage window is not interval-aligned")
        required = int(rounded_steps) + 1
        actual = self.bars_between(begin, end)
        if len(actual) != required:
            raise MarketDataError(
                f"market gap for {self.symbol} inside {begin}..{end}"
            )
        for index, current in enumerate(actual):
            expected = begin + index * self.interval_seconds
            if current.ts != expected:
                raise MarketDataError(
                    f"market gap for {self.symbol} at {expected}"
                )

    def carry_forward_gaps(self, max_missing_intervals: int) -> "MarketSeries":
        """Fill bounded venue-data gaps with explicit last-known-price bars."""
        if (
            type(max_missing_intervals) is not int
            or max_missing_intervals < 0
        ):
            raise MarketDataError(
                "max_missing_intervals must be a non-negative integer"
            )
        if not self.bars:
            return self

        filled = [self.bars[0]]
        gaps = []
        for previous, current in zip(self.bars, self.bars[1:]):
            steps = (current.ts - previous.ts) / self.interval_seconds
            rounded_steps = round(steps)
            if not math.isclose(steps, rounded_steps, abs_tol=1e-9):
                raise MarketDataError("market gap is not interval-aligned")
            missing = int(rounded_steps) - 1
            if missing > max_missing_intervals:
                raise MarketDataError(
                    f"market gap of {missing} intervals exceeds "
                    f"configured cap {max_missing_intervals}"
                )
            if missing:
                gaps.append(
                    {
                        "after_ts": previous.ts,
                        "before_ts": current.ts,
                        "missing_intervals": missing,
                    }
                )
                for offset in range(1, missing + 1):
                    filled.append(
                        MarketBar(
                            ts=previous.ts + offset * self.interval_seconds,
                            open=previous.close,
                            high=previous.close,
                            low=previous.close,
                            close=previous.close,
                            synthetic=True,
                        )
                    )
            filled.append(current)
        manifest = {
            **self.manifest,
            "gap_policy": "carry_forward",
            "max_missing_intervals": max_missing_intervals,
            "synthetic_bar_count": sum(
                gap["missing_intervals"] for gap in gaps
            ),
            "gaps": gaps,
        }
        return MarketSeries(
            self.symbol,
            self.interval_seconds,
            tuple(filled),
            manifest,
        )


def _manifest(
    *,
    symbol: str,
    level: str,
    begin_ts: float,
    end_ts: float,
    rows: Iterable[tuple[Any, ...]],
    timestamps: Iterable[float],
) -> dict[str, Any]:
    digest = hashlib.sha256()
    row_count = 0
    for row in rows:
        digest.update(canonical_json_bytes(list(row)))
        row_count += 1
    times = tuple(timestamps)
    return {
        "symbol": symbol,
        "level": level,
        "begin_ts": begin_ts,
        "end_exclusive_ts": end_ts,
        "row_count": row_count,
        "first_ts": times[0] if times else None,
        "last_ts": times[-1] if times else None,
        "sha256": digest.hexdigest(),
    }


def load_market_series(
    path: str | Path,
    symbol: str,
    level: str,
    interval_ms: int,
    begin_ts: float,
    end_ts: float,
) -> MarketSeries:
    """Load bars by end timestamp and hash only the selected logical rows."""
    db_path = Path(path)
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    if type(interval_ms) is not int or interval_ms <= 0:
        raise MarketDataError("market interval_ms must be a positive integer")
    begin, end = _validate_window(begin_ts, end_ts)
    raw_begin = int(begin * 1000) - interval_ms
    raw_end = int(end * 1000) - interval_ms
    with sqlite3.connect(db_path) as connection:
        selected = connection.execute(
            "select ts, o, h, l, c from kline "
            "where symbol = ? and lv = ? and ts >= ? and ts < ? order by ts",
            (symbol, level, raw_begin, raw_end),
        ).fetchall()
    if not selected:
        raise MarketDataError(f"no market bars found for {symbol} {level}")

    logical_rows = []
    bars = []
    for raw_ts, open_price, high, low, close in selected:
        bar_ts = (int(raw_ts) + interval_ms) / 1000.0
        normalized = (
            int(raw_ts),
            float(open_price),
            float(high),
            float(low),
            float(close),
        )
        logical_rows.append(normalized)
        bars.append(
            MarketBar(
                ts=bar_ts,
                open=normalized[1],
                high=normalized[2],
                low=normalized[3],
                close=normalized[4],
            )
        )
    manifest = _manifest(
        symbol=symbol,
        level=level,
        begin_ts=begin,
        end_ts=end,
        rows=logical_rows,
        timestamps=(bar.ts for bar in bars),
    )
    return MarketSeries(symbol, interval_ms // 1000, tuple(bars), manifest)


def _normalize_symbol(value: str) -> str:
    compact = value.strip().upper().replace("/", "").replace("-", "")
    if compact.endswith("USDT") and len(compact) > 4:
        return f"{compact[:-4]}/USDT"
    return value.strip().upper()


def _aware_timestamp(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MarketDataError("invalid funding timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MarketDataError("funding timestamp must include a timezone")
    return parsed.astimezone(timezone.utc).timestamp()


def load_funding_events(
    path: str | Path,
    symbol: str,
    begin_ts: float,
    end_ts: float,
) -> tuple[tuple[FundingEvent, ...], dict[str, Any]]:
    """Load and logically hash funding rows inside an IS-only window."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    begin, end = _validate_window(begin_ts, end_ts)
    requested_symbol = _normalize_symbol(symbol)
    events = []
    logical_rows = []
    with source.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"symbol", "fundingTime", "fundingRate"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise MarketDataError("funding CSV is missing required columns")
        for row in reader:
            row_symbol = _normalize_symbol(row["symbol"])
            if row_symbol != requested_symbol:
                continue
            timestamp = _aware_timestamp(row["fundingTime"])
            if timestamp < begin or timestamp >= end:
                continue
            rate = _finite("funding rate", row["fundingRate"])
            event = FundingEvent(timestamp, requested_symbol, rate)
            if events and events[-1].ts >= event.ts:
                raise MarketDataError(
                    "funding timestamps must be strictly increasing"
                )
            events.append(event)
            logical_rows.append((requested_symbol, timestamp, rate))
    manifest = _manifest(
        symbol=requested_symbol,
        level="funding",
        begin_ts=begin,
        end_ts=end,
        rows=logical_rows,
        timestamps=(event.ts for event in events),
    )
    return tuple(events), manifest


def require_funding_coverage(
    events: Iterable[FundingEvent],
    symbol: str,
    begin_ts: float,
    end_ts: float,
    interval_seconds: int,
) -> None:
    """Require one funding settlement at every configured IS interval."""
    begin, end = _validate_window(begin_ts, end_ts)
    if type(interval_seconds) is not int or interval_seconds <= 0:
        raise MarketDataError("funding interval must be a positive integer")
    span = (end - begin) / interval_seconds
    expected_count = round(span)
    if not math.isclose(span, expected_count, abs_tol=1e-9):
        raise MarketDataError("funding window is not interval-aligned")
    requested_symbol = _normalize_symbol(symbol)
    selected = tuple(
        event
        for event in events
        if event.symbol == requested_symbol and begin <= event.ts < end
    )
    if len(selected) != expected_count:
        raise MarketDataError(
            f"funding gap for {requested_symbol}: expected {expected_count} "
            f"events, found {len(selected)}"
        )
    for index, event in enumerate(selected):
        expected_ts = begin + index * interval_seconds
        if event.ts != expected_ts:
            raise MarketDataError(
                f"funding gap for {requested_symbol} at {expected_ts}"
            )
