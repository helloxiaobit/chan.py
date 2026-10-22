"""Versioned native sources persist independently; never admission or orders."""
import copy
import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.db_util import CChanDB
from .test_execution_store import store
from .test_native_account_components import component_case
from .test_native_admission_interval import explicit_path_environment


TABLE = "chanpy_native_account_observations"


def source_api():
    assert importlib.util.find_spec("Trade.NativeAccountStore") is not None, "versioned native account observation store is missing"
    from Trade import NativeAccountStore
    return NativeAccountStore


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


@pytest.fixture(params=[(venue, kind) for venue in ("binance", "okx") for kind in ("pending", "balance")])
def native_document(request, store, tmp_path, monkeypatch):
    venue, kind = request.param
    db, _ = store
    params, _, _, key = component_case(db, tmp_path, monkeypatch, venue)
    return params["pending_orders" if kind == "pending" else "balance_reservations"], db.get_record(key)


def test_native_source_api_is_explicit_and_separate():
    api = source_api()
    assert api.TABLE == TABLE
    assert callable(api.store_observation) and callable(api.read_observation) and callable(api.read_account_observations)


def test_original_source_bytes_survive_restart_and_idempotence_without_old_table_or_order_writes(store, native_document):
    source_api()
    db, conf = store
    document, order = native_document
    old_count = db.db.query_one("SELECT count(*) AS n FROM chanpy_account_evidence")["n"]
    before = db.get_order_history(order["id"])
    key = db.store_native_account_observation(document)
    assert key == digest(document)
    assert db.store_native_account_observation(copy.deepcopy(document)) == key
    reopened = CChanDB(db_conf=conf)
    try:
        assert reopened.get_native_account_observation(key) == document
        assert reopened.get_native_account_observations(document["payload"]["account_context"]) == [document]
        assert reopened.get_record(order["id"]) == order
        assert reopened.get_order_history(order["id"]) == before
        assert reopened.db.query_one(f"SELECT count(*) AS n FROM {TABLE}")["n"] == 1
        assert reopened.db.query_one("SELECT count(*) AS n FROM chanpy_account_evidence")["n"] == old_count
        assert reopened.get_account_risk_state(document["payload"]["account_context"])["check_ids"] == []
        assert document["payload"]["economics_complete"] is document["payload"]["native_admission_verified"] is False
    finally:
        reopened.close()


@pytest.mark.parametrize("verb", ["UPDATE", "DELETE", "REPLACE"])
def test_native_observations_are_append_only_even_for_replace(store, native_document, verb):
    source_api()
    db, _ = store
    document, _ = native_document
    key = db.store_native_account_observation(document)
    sql = (f"UPDATE {TABLE} SET observed_ms=0" if verb == "UPDATE" else f"DELETE FROM {TABLE}"
           if verb == "DELETE" else f"INSERT OR REPLACE INTO {TABLE} SELECT * FROM {TABLE}")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.db.execute(sql)
    assert db.get_native_account_observation(key) == document


@pytest.mark.parametrize("damage", ["bytes", "account_key", "context_id", "kind", "time", "future_time", "rehashed_derived", "rehashed_amount"])
def test_reader_rebuilds_sources_and_all_indexed_metadata_before_account_filter(store, native_document, damage):
    api = source_api()
    db, _ = store
    document, _ = native_document
    key = db.store_native_account_observation(document)
    db.db.execute(f"DROP TRIGGER {TABLE}_no_update")
    if damage == "bytes":
        db.db.execute(f"UPDATE {TABLE} SET payload=payload || ' '")
    elif damage in {"account_key", "context_id"}:
        db.db.execute(f"UPDATE {TABLE} SET {damage}=?", ("0"*64,))
    elif damage == "kind":
        db.db.execute(f"UPDATE {TABLE} SET kind=CASE kind WHEN 'pending' THEN 'balance' ELSE 'pending' END")
    elif damage == "time":
        db.db.execute(f"UPDATE {TABLE} SET observed_ms=0")
    elif damage == "future_time":
        db.db.execute(f"UPDATE {TABLE} SET observed_ms=?", (9_000_000_000_000,))
    else:
        document = copy.deepcopy(document)
        if damage == "rehashed_derived":
            document["payload"]["economics_complete"] = True
        elif document["schema"] == "chan-native-pending-orders-v1":
            document["payload"]["orders"][0]["filled_base_quantity"] = "900"
        else:
            document["payload"]["assets"][0]["native_fields"]["walletBalance" if document["payload"]["venue"] == "binance" else "cashBal"] = "900"
        document["payload_sha256"] = digest(document["payload"])
        raw, key = canonical_bytes(document).decode(), digest(document)
        db.db.execute(f"UPDATE {TABLE} SET evidence_id=?,payload=?,payload_sha256=?", (key, raw, key))
    db.db.execute(api.SCHEMA[f"{TABLE}_no_update"])
    for read in (lambda: db.get_native_account_observation(key),
                 lambda: db.get_native_account_observations(document["payload"]["account_context"])):
        with pytest.raises(CChanException):
            read()


def test_native_source_failure_is_atomic_and_never_publishes_a_check(store, native_document):
    source_api()
    db, _ = store
    document, _ = native_document
    original = db.db.query("SELECT * FROM chan_trade")
    db.db.execute(f"CREATE TRIGGER fail_native_source BEFORE INSERT ON {TABLE} BEGIN SELECT RAISE(ABORT,'PRIVATE_FAIL'); END")
    with pytest.raises(CChanException) as caught:
        db.store_native_account_observation(document)
    assert "PRIVATE_FAIL" not in str(caught.value)
    assert db.db.query(f"SELECT * FROM {TABLE}") == []
    assert db.db.query("SELECT * FROM chanpy_account_checks") == []
    assert db.db.query("SELECT * FROM chan_trade") == original and not db.db.conn.in_transaction


def test_caller_source_is_frozen_before_writer_lock_and_reader_returns_a_copy(store, native_document, monkeypatch):
    source_api()
    db, _ = store
    document, _ = native_document
    original, execute = copy.deepcopy(document), db.db.execute
    def mutate(sql, args=()):
        document["payload"]["economics_complete"] = True
        return execute(sql, args)
    monkeypatch.setattr(db.db, "execute", mutate)
    key = db.store_native_account_observation(document)
    read = db.get_native_account_observation(key)
    assert read == original
    read["payload"]["native_admission_verified"] = True
    assert db.get_native_account_observation(key) == original


def test_store_owns_only_its_savepoint_not_the_callers_transaction(store, native_document):
    source_api()
    db, _ = store
    document, _ = native_document
    with pytest.raises(RuntimeError, match="caller rollback"):
        with db.db.transaction():
            key = db.store_native_account_observation(document)
            assert db.get_native_account_observation(key) == document
            assert db.db.conn.in_transaction
            raise RuntimeError("caller rollback")
    assert db.db.query(f"SELECT * FROM {TABLE}") == [] and not db.db.conn.in_transaction


def test_source_of_one_native_account_cannot_be_listed_under_another(store, native_document):
    source_api()
    db, _ = store
    document, _ = native_document
    db.store_native_account_observation(document)
    other = copy.deepcopy(document["payload"]["account_context"])
    other["identifier_sha256"] = "f"*64
    other["context_id"] = digest({k: v for k, v in other.items() if k != "context_id"})
    assert db.get_native_account_observations(other) == []


def test_original_account_evidence_is_not_resealed_into_the_native_source_table(store, native_document):
    source_api()
    db, _ = store
    evidence_id = db.db.query_one("SELECT evidence_id FROM chanpy_account_evidence ORDER BY evidence_id")["evidence_id"]
    original = db.get_account_evidence(evidence_id)
    with pytest.raises(CChanException):
        db.store_native_account_observation(original)
    assert db.db.query(f"SELECT * FROM {TABLE}") == []
    assert db.get_account_evidence(evidence_id) == original


@pytest.mark.parametrize("evidence_id", [None, True, "0"*63, "z"*64, "0"*64])
def test_missing_or_malformed_native_source_id_is_not_an_empty_observation(store, evidence_id):
    source_api()
    db, _ = store
    with pytest.raises(CChanException):
        db.get_native_account_observation(evidence_id)
    assert db.db.query(f"SELECT * FROM {TABLE}") == []


def test_missing_append_only_guard_is_refused_even_with_valid_document_bytes(store, native_document):
    source_api()
    db, _ = store
    document, _ = native_document
    key = db.store_native_account_observation(document)
    db.db.execute(f"DROP TRIGGER {TABLE}_no_delete")
    with pytest.raises(CChanException):
        db.get_native_account_observation(key)


def test_mysql_is_not_silently_promoted_to_native_source_support():
    source_api()
    db = CChanDB.__new__(CChanDB)
    db.db_type = "mysql"
    for call in (lambda: db.store_native_account_observation({}), lambda: db.get_native_account_observation("0"*64),
                 lambda: db.get_native_account_observations({})):
        with pytest.raises(CChanException):
            call()


def test_foreign_native_table_is_not_adopted_and_old_schema_changes_roll_back(tmp_path):
    source_api()
    path = str(tmp_path/"foreign-native.db")
    with sqlite3.connect(path) as conn:
        conn.execute(f"CREATE TABLE {TABLE}(original TEXT)")
        conn.execute(f"INSERT INTO {TABLE} VALUES('retain')")
    with pytest.raises(CChanException):
        CChanDB(db_conf={"type": "sqlite", "sqlite_path": path})
    with sqlite3.connect(path) as conn:
        assert conn.execute(f"SELECT * FROM {TABLE}").fetchall() == [("retain",)]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='chan_trade'").fetchall() == []


def test_native_table_name_is_reserved_as_an_order_projection(tmp_path):
    source_api()
    path = str(tmp_path/"reserved.db")
    with pytest.raises(ValueError, match="Reserved"):
        CChanDB(table_name=TABLE, db_conf={"type": "sqlite", "sqlite_path": path})


def test_no_sdk_or_configuration_is_needed_for_restart_reader(store, native_document):
    source_api()
    db, conf = store
    document, _ = native_document
    key = db.store_native_account_observation(document)
    code = """
import importlib.abc, json, sys
class NoOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ccxt', 'yaml', 'torch', 'xgboost', 'matplotlib', 'PIL', 'PySide6'}:
            raise ImportError('blocked optional dependency')
sys.meta_path.insert(0, NoOptional())
from Config.EnvConfig import CEnv
env = CEnv.__new__(CEnv)
env.conf = {}
CEnv._instance = env
from Trade.db_util import CChanDB
db = CChanDB(db_conf=json.loads(sys.argv[1]))
try:
    changes = db.db.conn.total_changes
    assert db.get_native_account_observation(sys.argv[2]) == json.loads(sys.argv[3])
    assert db.get_native_account_observations(json.loads(sys.argv[3])['payload']['account_context']) == [json.loads(sys.argv[3])]
    assert db.db.conn.total_changes == changes
finally:
    db.close()
"""
    child = subprocess.run([sys.executable, "-c", code, json.dumps(conf), key, canonical_bytes(document).decode()],
                           capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stderr
