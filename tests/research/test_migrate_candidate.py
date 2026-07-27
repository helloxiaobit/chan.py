import json
import pickle
from types import SimpleNamespace

import pytest

from ModelStrategy.research.boundary import parse_utc
from ModelStrategy.research.candidate import load_candidate_dataset
from ModelStrategy.research.migrate_candidate import migrate_candidate_pickle
from ModelStrategy.research.provenance import file_manifest


def record(**overrides):
    values = {
        "code": "BTC/USDT",
        "open_ts": parse_utc("2021-02-01"),
        "close_ts": parse_utc("2021-02-02"),
        "open_price": 100.0,
        "close_price": 105.0,
        "risk_rate": 0.05,
        "bs_type": "z1",
        "is_buy": True,
        "is_pyramid": False,
        "reason": "trend_flip",
        "is_closed": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def write_pickle(tmp_path, rows):
    path = tmp_path / "trusted-is-cache.pkl"
    with path.open("wb") as stream:
        pickle.dump(rows, stream)
    return path


def migrate(tmp_path, rows, **overrides):
    source = write_pickle(tmp_path, rows)
    output = tmp_path / "normalized" / "candidate.json"
    options = {
        "symbol": "BTC/USDT",
        "stack": "S1bz[4H,1H,15M]",
        "entry_kind": "strategy_fill",
        "begin_ts": parse_utc("2021-01-01"),
        "end_ts": parse_utc("2026-01-01"),
        "timestamp_offset_seconds": 0,
    }
    options.update(overrides)
    migrate_candidate_pickle(source, output, **options)
    return source, output


def test_migration_is_atomic_portable_and_records_source_manifest(tmp_path):
    source, output = migrate(
        tmp_path,
        [
            record(
                open_ts=parse_utc("2021-03-01"),
                close_ts=parse_utc("2021-03-02"),
            ),
            record(),
        ],
    )
    dataset = load_candidate_dataset(output)
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == 2
    assert [item.entry_ts for item in dataset.trades] == sorted(
        item.entry_ts for item in dataset.trades
    )
    assert dataset.source.path == source.name
    assert dataset.source.size == file_manifest(source)["size"]
    assert dataset.source.sha256 == file_manifest(source)["sha256"]
    assert dataset.source.timestamp_offset_seconds == 0
    assert dataset.source.raw_entry_ts_min == parse_utc("2021-02-01")
    assert dataset.source.corrected_entry_ts_min == parse_utc("2021-02-01")
    assert not list(output.parent.glob("*.tmp"))


def test_migration_applies_declared_offset_before_is_boundary_checks(tmp_path):
    raw_entry = parse_utc("2020-12-31") + 16 * 60 * 60
    raw_close = parse_utc("2021-01-01") + 16 * 60 * 60
    _, output = migrate(
        tmp_path,
        [record(open_ts=raw_entry, close_ts=raw_close)],
        timestamp_offset_seconds=28800,
    )
    dataset = load_candidate_dataset(output)
    assert dataset.trades[0].entry_ts == parse_utc("2021-01-01")
    assert dataset.trades[0].close_ts == parse_utc("2021-01-02")
    assert dataset.source.timestamp_offset_seconds == 28800
    assert dataset.source.raw_entry_ts_min == raw_entry
    assert dataset.source.corrected_entry_ts_min == parse_utc("2021-01-01")


def test_migration_rejects_row_that_moves_into_oos_after_correction(tmp_path):
    raw_close = parse_utc("2025-12-31") + 16 * 60 * 60
    with pytest.raises(ValueError, match="OOS|window"):
        migrate(
            tmp_path,
            [record(close_ts=raw_close)],
            timestamp_offset_seconds=28800,
        )
    assert not (tmp_path / "normalized" / "candidate.json").exists()


@pytest.mark.parametrize("offset", [0.5, True, 86401, -86401])
def test_migration_rejects_invalid_timestamp_offset(tmp_path, offset):
    with pytest.raises(ValueError, match="timestamp_offset_seconds"):
        migrate(tmp_path, [record()], timestamp_offset_seconds=offset)
    assert not (tmp_path / "normalized" / "candidate.json").exists()


@pytest.mark.parametrize(
    "rows,options,match",
    [
        (
            [record()],
            {"symbol": "ETH/USDT"},
            "symbol",
        ),
        (
            [record(open_ts=parse_utc("2020-12-31"))],
            {},
            "window",
        ),
        (
            [record(close_ts=parse_utc("2026-01-01"))],
            {},
            "OOS",
        ),
    ],
)
def test_migration_rejects_identity_or_window_drift_without_output(
    tmp_path, rows, options, match
):
    with pytest.raises(ValueError, match=match):
        migrate(tmp_path, rows, **options)
    assert not (tmp_path / "normalized" / "candidate.json").exists()


def test_signal_intent_migration_never_defaults_missing_pyramid_identity(
    tmp_path,
):
    stale = record()
    del stale.is_pyramid
    with pytest.raises(ValueError, match="is_pyramid"):
        migrate(tmp_path, [stale], entry_kind="signal_intent")
    assert not (tmp_path / "normalized" / "candidate.json").exists()


def test_migration_rejects_duplicate_records(tmp_path):
    value = record()
    with pytest.raises(ValueError, match="duplicate"):
        migrate(tmp_path, [value, value])
