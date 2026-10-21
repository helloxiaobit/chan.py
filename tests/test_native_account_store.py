"""SQLite account evidence is atomic/append-only and cannot certify itself."""
import copy
import hashlib
import json
import sqlite3

import pytest

from Common.ChanException import CChanException
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.AccountSources import collect_account_snapshot, collect_wallet_scan
from Trade.CCXTTradeEngine import CCCXTTradeEngine
from Trade.db_util import CChanDB
from .test_crypto_order_contract import CODE
from .test_crypto_venue_parameters import venue_engine
from .test_execution_facts import definition
from .test_execution_store import store
from .test_native_account_snapshot import snapshot_client
from .test_native_account_sources import wallet_client, wallet_row


TABLE = "chanpy_account_evidence"


def wallet(monkeypatch, venue="binance", *, key=101, amount="25", native_type="TRANSFER"):
    at = utc_now_ms()-5000
    client, _, _, _ = wallet_client(monkeypatch, venue, [wallet_row(venue, at, key=key, kind=native_type, amount=amount)])
    return collect_wallet_scan(client, mode="testnet", start_ms=at, end_ms=at+100)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_account_snapshot_and_cashflows_have_verified_canonical_bytes_after_restart(store, monkeypatch, venue):
    db, conf = store
    client, _, _, _, _, _ = snapshot_client(monkeypatch, venue)
    snapshot = collect_account_snapshot(client, [definition(venue)], mode="testnet")
    cash = wallet(monkeypatch, venue)
    ids = [db.store_account_evidence(doc) for doc in (snapshot, cash)]
    assert len(set(ids)) == 2
    assert db.db.query("SELECT * FROM chan_trade") == []
    restarted = CChanDB(db_conf=conf)
    try:
        assert [restarted.get_account_evidence(key) for key in ids] == [snapshot, cash]
        assert [db.store_account_evidence(copy.deepcopy(doc)) for doc in (snapshot, cash)] == ids
        assert db.db.query_one(f"SELECT count(*) AS n FROM {TABLE}")["n"] == 2
        assert all(doc["payload"]["economics_complete"] is False for doc in (snapshot, cash))
    finally:
        restarted.close()


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_wallet_native_id_conflict_is_rejected_without_a_second_document(store, monkeypatch, venue):
    db, _ = store
    first = wallet(monkeypatch, venue)
    db.store_account_evidence(first)
    at = first["payload"]["start_ms"]
    client, _, _, _ = wallet_client(monkeypatch, venue, [wallet_row(venue, at, amount="26")])
    second = collect_wallet_scan(client, mode="testnet", start_ms=at, end_ms=at+100)
    with pytest.raises(CChanException):
        db.store_account_evidence(second)
    assert db.db.query_one(f"SELECT count(*) AS n FROM {TABLE}")["n"] == 1
    assert db.get_account_evidence(hashlib.sha256(canonical_bytes(first)).hexdigest()) == first


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_same_native_id_in_another_account_is_not_a_duplicate(store, monkeypatch, venue):
    db, _ = store
    first = wallet(monkeypatch, venue)
    db.store_account_evidence(first)
    at = first["payload"]["start_ms"]
    client, _, _, identity = wallet_client(monkeypatch, venue, [wallet_row(venue, at, amount="26")])
    if venue == "binance":
        for row in identity:
            row["accountAlias"] = "other-Futures-account"
    else:
        identity["data"][0]["uid"] = "98765432"
    second = collect_wallet_scan(client, mode="testnet", start_ms=at, end_ms=at+100)
    key = db.store_account_evidence(second)
    assert db.get_account_evidence(key) == second
    assert db.db.query_one(f"SELECT count(*) AS n FROM {TABLE}")["n"] == 2


@pytest.mark.parametrize("verb", ["UPDATE", "DELETE", "REPLACE"])
def test_account_evidence_cannot_be_overwritten_even_with_sqlite_replace(store, monkeypatch, verb):
    db, _ = store
    receipt = wallet(monkeypatch)
    key = db.store_account_evidence(receipt)
    sql = f"DELETE FROM {TABLE}" if verb == "DELETE" else f"UPDATE {TABLE} SET observed_ms=0" if verb == "UPDATE" else f"INSERT OR REPLACE INTO {TABLE} SELECT * FROM {TABLE}"
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.db.execute(sql)
    assert db.get_account_evidence(key) == receipt


def test_account_evidence_failure_rolls_back_without_order_side_effects(store, monkeypatch):
    db, _ = store
    receipt = wallet(monkeypatch)
    db.db.execute(f"CREATE TRIGGER fail_account BEFORE INSERT ON {TABLE} BEGIN SELECT RAISE(ABORT,'failed'); END")
    with pytest.raises(CChanException):
        db.store_account_evidence(receipt)
    assert db.db.query(f"SELECT * FROM {TABLE}") == []
    assert db.db.query("SELECT * FROM chan_trade") == [] and not db.db.conn.in_transaction


@pytest.mark.parametrize("damage", ["bytes", "context_column", "kind_column", "source_summary"])
def test_fresh_reader_refuses_damaged_bytes_columns_or_rehashed_sources(store, monkeypatch, damage):
    from Trade.AccountStore import SCHEMA
    db, _ = store
    receipt = wallet(monkeypatch)
    key = db.store_account_evidence(receipt)
    db.db.execute(f"DROP TRIGGER {TABLE}_no_update")
    if damage == "bytes":
        db.db.execute(f"UPDATE {TABLE} SET payload=payload || ' '")
    elif damage == "context_column":
        db.db.execute(f"UPDATE {TABLE} SET context_id=?", ("0"*64,))
    elif damage == "kind_column":
        db.db.execute(f"UPDATE {TABLE} SET kind='snapshot'")
    else:
        receipt["payload"]["facts"][0]["account_cash_delta"] = "999"
        receipt["payload_sha256"] = hashlib.sha256(canonical_bytes(receipt["payload"])).hexdigest()
        raw = canonical_bytes(receipt).decode()
        digest = hashlib.sha256(raw.encode()).hexdigest()
        db.db.execute(f"UPDATE {TABLE} SET evidence_id=?,payload=?,payload_sha256=?", (digest, raw, digest))
        key = digest
    db.db.execute(SCHEMA[f"{TABLE}_no_update"])
    with pytest.raises(CChanException):
        db.get_account_evidence(key)


def test_foreign_account_table_is_not_adopted_and_schema_upgrade_is_atomic(tmp_path):
    path = str(tmp_path/"foreign-account.db")
    with sqlite3.connect(path) as conn:
        conn.execute(f"CREATE TABLE {TABLE}(preserve TEXT)")
        conn.execute(f"INSERT INTO {TABLE} VALUES('original')")
    with pytest.raises(CChanException):
        CChanDB(db_conf={"type": "sqlite", "sqlite_path": path})
    with sqlite3.connect(path) as conn:
        assert conn.execute(f"SELECT * FROM {TABLE}").fetchall() == [("original",)]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='chan_trade'").fetchall() == []


def test_document_is_frozen_before_publication_under_writer_lock(store, monkeypatch):
    db, _ = store
    document = wallet(monkeypatch)
    original, execute = copy.deepcopy(document), db.db.execute

    def mutated(sql, args=()):
        document["payload"]["facts"][0]["account_cash_delta"] = "999"
        return execute(sql, args)

    monkeypatch.setattr(db.db, "execute", mutated)
    key = db.store_account_evidence(document)
    assert db.get_account_evidence(key) == original


@pytest.mark.parametrize("method", ["sync_account_snapshot", "sync_wallet_cashflows"])
def test_dry_run_account_sources_never_create_a_real_session(store, monkeypatch, method):
    db, _ = store
    trade = CCCXTTradeEngine(db, ccxt_conf={"mode": "dry_run", "default_type": "swap"}, push_msg=False)
    monkeypatch.setattr(trade, "get_exchange", lambda: pytest.fail("dry-run private I/O"))
    with pytest.raises(CChanException):
        if method == "sync_account_snapshot":
            trade.sync_account_snapshot([CODE])
        else:
            trade.sync_wallet_cashflows(start_ms=1, end_ms=2)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_explicit_engine_sync_saves_account_wide_sources_without_orders_or_implicit_reconcile(store, tmp_path, monkeypatch, venue):
    db, _ = store
    trade = venue_engine(db, tmp_path, venue)
    source, _, _, _, _, _ = snapshot_client(monkeypatch, venue)
    names = ("fapiPrivateV3GetAccount", "fapiPrivateV3GetPositionRisk", "fapiPrivateGetSymbolConfig", "fapiPrivateGetMultiAssetsMargin") if venue == "binance" else ("privateGetAccountBalance", "privateGetAccountPositions")
    for name in names:
        monkeypatch.setattr(trade.exchange, name, getattr(source, name), raising=False)
    snapshot = trade.sync_account_snapshot([CODE])
    at = utc_now_ms()-5_000
    native, _, _, _ = wallet_client(monkeypatch, venue, [wallet_row(venue, at)])
    name = "fapiPrivateGetIncome" if venue == "binance" else "privateGetAccountBillsArchive"
    monkeypatch.setattr(trade.exchange, name, getattr(native, name), raising=False)
    cash = trade.sync_wallet_cashflows(start_ms=at, end_ms=at+100)
    for doc in (snapshot, cash):
        key = hashlib.sha256(canonical_bytes(doc)).hexdigest()
        assert db.get_account_evidence(key) == doc
        assert doc["payload"]["economics_complete"] is False
    assert trade.exchange.created == [] and db.db.query("SELECT * FROM chan_trade") == []
