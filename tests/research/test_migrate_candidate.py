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
    assert [item.entry_ts for item in dataset.trades] == sorted(
        item.entry_ts for item in dataset.trades
    )
    assert dataset.source.path == source.name
    assert dataset.source.size == file_manifest(source)["size"]
    assert dataset.source.sha256 == file_manifest(source)["sha256"]
    assert not list(output.parent.glob("*.tmp"))


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
