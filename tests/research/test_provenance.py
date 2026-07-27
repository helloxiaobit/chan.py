import sqlite3

from ModelStrategy.research.provenance import (
    canonical_json_bytes,
    sqlite_kline_manifest,
)


def build_fixture_db(tmp_path):
    path = tmp_path / "bars.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "create table kline ("
            "ts integer, symbol text, lv text, o real, h real, l real, c real)"
        )
        connection.executemany(
            "insert into kline values (?, ?, ?, ?, ?, ?, ?)",
            [
                (1609459200000, "BTC/USDT", "K_60M", 1, 2, 0.5, 1.5),
                (1767225600000, "BTC/USDT", "K_60M", 9, 9, 9, 9),
            ],
        )
    return path


def test_canonical_json_is_key_order_independent():
    assert canonical_json_bytes({"b": 2, "a": 1}) == canonical_json_bytes(
        {"a": 1, "b": 2}
    )


def test_sqlite_manifest_hashes_only_selected_rows(tmp_path):
    path = build_fixture_db(tmp_path)
    first = sqlite_kline_manifest(
        path,
        "BTC/USDT",
        "K_60M",
        1609459200000,
        1640995200000,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "update kline set c = 99 where ts = ?", (1767225600000,)
        )
    second = sqlite_kline_manifest(
        path,
        "BTC/USDT",
        "K_60M",
        1609459200000,
        1640995200000,
    )
    assert first == second
    assert first["row_count"] == 1
    assert first["first_ts"] == first["last_ts"] == 1609459200000
