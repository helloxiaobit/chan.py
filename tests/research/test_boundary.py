from datetime import datetime, timezone

import pytest

from ModelStrategy.research.boundary import (
    IS_END_EXCLUSIVE,
    ResearchBoundaryError,
    parse_utc,
    require_is_timestamp,
    require_is_window,
)


def test_parse_utc_is_timezone_independent():
    assert parse_utc("2026-01-01") == datetime(
        2026, 1, 1, tzinfo=timezone.utc
    ).timestamp()


def test_is_timestamp_rejects_2026_boundary():
    with pytest.raises(ResearchBoundaryError, match="OOS"):
        require_is_timestamp(IS_END_EXCLUSIVE)


def test_is_window_accepts_2021_through_2025_only():
    begin, end = require_is_window("2021-01-01", "2026-01-01")
    assert begin < end == IS_END_EXCLUSIVE


def test_is_window_rejects_end_after_2026_boundary():
    with pytest.raises(ResearchBoundaryError, match="2026-01-01"):
        require_is_window("2021-01-01", "2026-01-02")
