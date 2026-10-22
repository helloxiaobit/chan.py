"""Full raw-history verification stays byte-identical without retaining that history."""
import gc
import hashlib
import tracemalloc

import pytest

from Common.CEnum import KL_TYPE
from Common.ChanException import CChanException
from Common.KLineTime import bar_close_ms, validate_ohlcv_page
from Config.EnvConfig import CEnv
from CustomBuySellPoint.Decision import canonical_bytes
from OfflineData.offline_data_util import CKLineDB
from Trade.Script.OpeningInputs import inspect_opening_inputs, read_cycle_scope
from .test_crypto_data_contract import bar, ms
from .test_trade_cycle import cycle, CODES, HOUR, NOW, SOURCE


def legacy_quality(db, code, level, now_ms, *, market_active=None):
    # Freeze the pre-streaming contract, including status precedence and raw count.
    closed = [row for row in db.query_klines(code, level) if bar_close_ms(row[0], level) <= now_ms]
    status = "ready"
    if not db.source_identity:
        status = "unknown_source"
    elif market_active is False:
        status = "inactive"
    elif not closed:
        status = "no_data"
    else:
        try:
            validate_ohlcv_page(closed, level)
        except CChanException:
            status = "gap"
        if status == "ready" and bar_close_ms(bar_close_ms(closed[-1][0], level), level) <= now_ms:
            status = "stale"
    return {"status": status, "ready": status == "ready", "source": db.source_identity,
            "symbol": code, "timeframe": level.name, "closed_count": len(closed),
            "latest_close_ms": bar_close_ms(closed[-1][0], level) if closed else None}


def legacy_inputs(env, now_ms):
    scope = read_cycle_scope(env)
    quality, manifests = [], []
    with CKLineDB(env.abs_path(env.offline_data_conf["sqlite_path"]), read_only=True) as db:
        db.conn.execute("BEGIN")
        db.check_source(scope["source"])
        for code in scope["code_list"]:
            for name in scope["lv_list"]:
                level = KL_TYPE[name]
                item = legacy_quality(db, code, level, now_ms)
                assert item["ready"]
                rows = [row for row in db.query_klines(code, level) if bar_close_ms(row[0], level) <= now_ms]
                manifests.append({"code": code, "level": name,
                    "rows_sha256": hashlib.sha256(canonical_bytes(rows)).hexdigest(),
                    "count": len(rows), "latest_close_ms": item["latest_close_ms"]})
                quality.append(item)
    return {"scope": scope, "quality": quality, "scope_sha256": hashlib.sha256(canonical_bytes(scope)).hexdigest(),
            "inputs_sha256": hashlib.sha256(canonical_bytes({"scope": scope, "manifests": manifests})).hexdigest()}


def no_bulk_query(*args, **kwargs):
    pytest.fail("input/quality verification must not load the full history with query_klines")


def test_iterator_preserves_raw_columns_order_and_half_open_range(tmp_path):
    path = tmp_path / "range.sqlite"
    with CKLineDB(str(path)) as db:
        db.bind_source(SOURCE)
        db.upsert_klines(CODES[0], KL_TYPE.K_60M, [bar(2*HOUR), bar(0), bar(HOUR)])
    with CKLineDB(str(path), read_only=True) as db:
        expected = db.query_klines(CODES[0], "K_60M", HOUR, 2*HOUR)
        rows = db.iter_klines(CODES[0], KL_TYPE.K_60M, HOUR, 2*HOUR)
        assert iter(rows) is rows and not isinstance(rows, list)
        assert list(rows) == expected == [(HOUR, 100.0, 110.0, 90.0, 100.0, 1.0)]
        assert list(db.iter_klines(CODES[0], KL_TYPE.K_60M, 2*HOUR, 2*HOUR)) == []
        assert list(db.iter_klines("absent", KL_TYPE.K_60M)) == []
        rows = db.iter_klines(CODES[0], KL_TYPE.K_60M)
        assert next(rows)[0] == 0
        rows.close()
        assert db.count(CODES[0], KL_TYPE.K_60M) == 3


@pytest.mark.parametrize("kind", ["ready", "empty", "gap", "stale", "bad_price", "bad_volume",
                                      "misaligned", "unknown_source", "inactive", "partial_bad"])
def test_streaming_quality_keeps_the_exact_legacy_receipt(tmp_path, monkeypatch, kind):
    with CKLineDB(str(tmp_path / "quality.sqlite")) as db:
        if kind != "unknown_source":
            db.bind_source(SOURCE)
        rows = [] if kind == "empty" else [bar(0), bar(HOUR), bar(2*HOUR)]
        if kind in {"unknown_source", "inactive", "bad_price"}:
            rows[0][4] = -1
        if kind == "bad_volume":
            rows[0][5] = float("inf")
        if kind == "gap":
            del rows[1]
        if kind == "misaligned":
            rows[0][0] = 1
        if kind == "partial_bad":
            rows.append([3*HOUR, -1, -1, -1, -1, -1])
        db.upsert_klines(CODES[0], KL_TYPE.K_60M, rows)
        now = (4 if kind == "stale" else 3)*HOUR
        active = kind != "inactive"
        expected = legacy_quality(db, CODES[0], KL_TYPE.K_60M, now, market_active=active)
        monkeypatch.setattr(CKLineDB, "query_klines", no_bulk_query)
        actual = db.inspect_quality(CODES[0], KL_TYPE.K_60M, now_ms=now, market_active=active)
        assert canonical_bytes(actual) == canonical_bytes(expected)


@pytest.mark.parametrize("level,dates", [
    (KL_TYPE.K_60M, ["2024-01-01T23:00", "2024-01-02T00:00", "2024-01-02T01:00"]),
    (KL_TYPE.K_WEEK, ["2024-02-19T00:00", "2024-02-26T00:00", "2024-03-04T00:00"]),
    (KL_TYPE.K_MON, ["2024-01-01T00:00", "2024-02-01T00:00", "2024-03-01T00:00"]),
    (KL_TYPE.K_MON, ["2024-11-01T00:00", "2024-12-01T00:00", "2025-01-01T00:00"]),
])
def test_streamed_array_hash_matches_full_legacy_bytes(cycle, monkeypatch, level, dates):
    env = CEnv(str(cycle[0]))
    env.conf["trade"]["lv_list"] = [level.name]
    starts = [ms(value) for value in dates]
    with CKLineDB(cycle[2]["offline_data"]["sqlite_path"]) as db:
        db.conn.execute("DELETE FROM kline")
        for code in CODES:
            db.upsert_klines(code, level, [(ts, 100.125, 110.5, 90.25, 101.75,
                None if code == CODES[0] else 0.00001) for ts in starts])
    expected = legacy_inputs(env, starts[-1])  # last row is still provisional
    monkeypatch.setattr(CKLineDB, "query_klines", no_bulk_query)
    actual = inspect_opening_inputs(env, now_ms=starts[-1])
    assert canonical_bytes(actual) == canonical_bytes(expected)
    assert all(item["closed_count"] == 2 and item["latest_close_ms"] == starts[-1]
               for item in actual["quality"])


@pytest.mark.parametrize("column,value", [("o", 100.25), ("h", 111), ("l", 89), ("c", 100.5), ("v", 7)])
def test_every_historical_raw_value_still_changes_the_input_hash(cycle, column, value):
    env = CEnv(str(cycle[0]))
    first = inspect_opening_inputs(env, now_ms=NOW)
    with CKLineDB(cycle[2]["offline_data"]["sqlite_path"]) as db:
        # Column names are fixed test literals, never caller-controlled SQL.
        db.conn.execute(f"UPDATE kline SET {column}=? WHERE symbol=? AND lv='K_60M' AND ts=?",
                        (value, CODES[0], HOUR))
        db.conn.commit()
    second = inspect_opening_inputs(env, now_ms=NOW)
    assert first["quality"] == second["quality"]
    assert first["inputs_sha256"] != second["inputs_sha256"]
    assert canonical_bytes(second) == canonical_bytes(legacy_inputs(env, NOW))


def test_quality_and_hash_share_the_original_read_transaction(cycle, monkeypatch):
    path = cycle[2]["offline_data"]["sqlite_path"]
    with CKLineDB(path) as db:
        db.conn.execute("PRAGMA journal_mode=WAL")
    env = CEnv(str(cycle[0]))
    expected = legacy_inputs(env, NOW)
    original = CKLineDB.inspect_quality
    changed = False
    def concurrent_revision(db, *args, **kwargs):
        nonlocal changed
        item = original(db, *args, **kwargs)
        if not changed:
            with CKLineDB(path) as writer:
                writer.conn.execute("UPDATE kline SET v=8 WHERE symbol=? AND lv='K_60M' AND ts=?", (CODES[0], HOUR))
                writer.conn.commit()
            changed = True
        return item
    monkeypatch.setattr(CKLineDB, "inspect_quality", concurrent_revision)
    assert canonical_bytes(inspect_opening_inputs(env, now_ms=NOW)) == canonical_bytes(expected)
    assert inspect_opening_inputs(env, now_ms=NOW)["inputs_sha256"] != expected["inputs_sha256"]


def peak_bytes(call):
    gc.collect()
    tracemalloc.start()
    try:
        result = call()
        return result, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_large_sqlite_input_verification_does_not_retain_raw_history(cycle, monkeypatch, request):
    env = CEnv(str(cycle[0]))
    env.conf["trade"].update(code_list=[CODES[0]], lv_list=["K_60M"])
    inspect_opening_inputs(env, now_ms=NOW)  # warm normal imports before measuring
    monkeypatch.setattr(CKLineDB, "query_klines", no_bulk_query)
    small, small_peak = peak_bytes(lambda: inspect_opening_inputs(env, now_ms=NOW))
    count = 50_000
    with CKLineDB(cycle[2]["offline_data"]["sqlite_path"]) as db:
        db.upsert_klines(CODES[0], KL_TYPE.K_60M,
                         ((index*HOUR, 100, 101, 99, 100, index+1) for index in range(24, count)))
    large, large_peak = peak_bytes(lambda: inspect_opening_inputs(env, now_ms=count*HOUR))
    request.node.user_properties.extend([
        ("small_rows", 24), ("large_rows", count),
        ("small_peak_bytes", small_peak), ("large_peak_bytes", large_peak),
    ])
    assert small["quality"][0]["closed_count"] == 24
    assert large["quality"][0]["closed_count"] == count
    assert large["quality"][0]["latest_close_ms"] == count*HOUR
    assert large_peak <= small_peak + 512*1024  # 50k row tuples alone would be multiple MiB
    with CKLineDB(cycle[2]["offline_data"]["sqlite_path"]) as db:
        db.conn.execute("UPDATE kline SET c=-1 WHERE symbol=? AND lv='K_60M' AND ts=?", (CODES[0], HOUR))
        db.conn.commit()
    with pytest.raises(CChanException):
        inspect_opening_inputs(env, now_ms=count*HOUR)
