"""Hard boundaries separating in-sample research from 2026 OOS data."""

from datetime import datetime, timezone


IS_END_EXCLUSIVE = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()


class ResearchBoundaryError(ValueError):
    """Raised when a research input crosses the pre-registered OOS boundary."""


def parse_utc(value: str) -> float:
    """Parse an ISO date or datetime as an absolute UTC timestamp."""
    text = value if "T" in value else f"{value}T00:00:00"
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).timestamp()


def require_is_timestamp(ts: float) -> float:
    """Accept a timestamp only when it belongs to the 2021-2025 IS side."""
    if ts >= IS_END_EXCLUSIVE:
        raise ResearchBoundaryError(
            "OOS timestamp is not allowed before the IS gate passes"
        )
    return ts


def require_is_window(begin: str, end_exclusive: str) -> tuple[float, float]:
    """Validate a non-empty, half-open research window ending by 2026."""
    begin_ts = parse_utc(begin)
    end_ts = parse_utc(end_exclusive)
    if begin_ts >= end_ts:
        raise ResearchBoundaryError("research window must be increasing")
    if end_ts > IS_END_EXCLUSIVE:
        raise ResearchBoundaryError("IS window cannot extend beyond 2026-01-01")
    return begin_ts, end_ts
