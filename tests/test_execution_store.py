"""Actual SQLite imports: atomic, immutable, idempotent, never order writes."""
import copy
import sqlite3

import pytest

from Common.ChanException import CChanException
from Common.KLineTime import utc_now_ms
from Trade.db_util import CChanDB
from Trade.CCXTTradeEngine import CCCXTTradeEngine
from .test_execution_facts import NativeSources, collect, fill, funding
from .test_crypto_order_contract import CODE
from .test_crypto_venue_parameters import venue_engine


@pytest.fixture()
def store(tmp_path):
    conf = {"type": "sqlite", "sqlite_path": str(tmp_path/"economics.db")}
    db = CChanDB(db_conf=conf)
    try:
        yield db, conf
    finally:
        db.close()


def scan(venue="binance", *, fee="0.003"):
    start = utc_now_ms()-10_000
    return collect(NativeSources(venue, [fill(venue, start+1, fee=fee)], [funding(venue, start+2)]), start, start+100)


def counts(db):
    return [db.db.query_one(f"SELECT count(*) AS n FROM {table}")["n"] for table in ("chanpy_execution_facts", "chanpy_execution_scans")]


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_native_facts_are_atomic_and_available_after_restart_without_applying_an_order(store, venue):
    db, conf = store
    receipt = scan(venue)
    assert db.store_execution_scan(receipt) == receipt["payload_sha256"]
    assert counts(db) == [2, 1]
    assert db.db.query("SELECT * FROM chan_trade") == []
    restarted = CChanDB(db_conf=conf)
    try:
        assert restarted.get_execution_scans("offline-account", CODE) == [receipt]
        facts = restarted.get_execution_facts("offline-account", CODE, venue=venue, mode="testnet")
        assert facts == receipt["payload"]["facts"]
        facts[0]["price"] = "wrong local edit"
        assert restarted.get_execution_facts("offline-account", CODE, venue=venue, mode="testnet")[0]["price"] == "100"
    finally:
        restarted.close()


def test_duplicate_scan_does_not_duplicate_any_cash_flow(store):
    db, _ = store
    receipt = scan()
    db.store_execution_scan(receipt)
    db.store_execution_scan(copy.deepcopy(receipt))
    assert counts(db) == [2, 1]
    assert db.get_execution_scans("offline-account", CODE) == [receipt]


def test_failure_when_publishing_scan_rolls_back_its_new_facts(store):
    db, _ = store
    db.db.execute("CREATE TRIGGER fail_scan BEFORE INSERT ON chanpy_execution_scans BEGIN SELECT RAISE(ABORT,'scan failed'); END")
    with pytest.raises((CChanException, sqlite3.IntegrityError)):
        db.store_execution_scan(scan())
    assert counts(db) == [0, 0]
    assert not db.db.conn.in_transaction


def test_changed_native_fee_rejects_the_entire_new_scan_not_just_the_duplicate(store):
    db, _ = store
    first = scan()
    db.store_execution_scan(first)
    begin = first["payload"]["start_ms"]
    second = collect(NativeSources("binance", [fill("binance", begin+1, fee="0.004")],
                                   [funding("binance", begin, key=902)]), begin, begin+100)
    with pytest.raises(CChanException):
        db.store_execution_scan(second)
    assert counts(db) == [2, 1]
    assert db.get_execution_scans("offline-account", CODE) == [first]


@pytest.mark.parametrize("table", ["chanpy_execution_facts", "chanpy_execution_scans"])
@pytest.mark.parametrize("verb", ["UPDATE", "DELETE", "REPLACE"])
def test_execution_evidence_is_append_only_even_for_sqlite_replace(store, table, verb):
    db, _ = store
    db.store_execution_scan(scan())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        sql = f"DELETE FROM {table}" if verb == "DELETE" else (f"UPDATE {table} SET observed_ms=0" if verb == "UPDATE" else f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}")
        db.db.execute(sql)
    assert counts(db) == [2, 1]


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_engine_sync_uses_existing_read_session_and_does_not_create_or_change_orders(store, tmp_path, monkeypatch, venue):
    db, _ = store
    trade = venue_engine(db, tmp_path, venue)
    start = utc_now_ms()-10_000
    native = NativeSources(venue, [fill(venue, start+1)], [funding(venue, start+2)])
    for name in ("fapiPrivateGetUserTrades", "fapiPrivateGetIncome", "privateGetTradeFillsHistory", "privateGetTradeFills", "privateGetAccountBillsArchive"):
        monkeypatch.setattr(trade.exchange, name, getattr(native, name), raising=False)
    receipt = trade.sync_execution_facts(CODE, account_scope="offline-account", start_ms=start, end_ms=start+100)
    assert db.get_execution_scans("offline-account", CODE) == [receipt]
    assert trade.exchange.created == []
    assert db.db.query("SELECT * FROM chan_trade") == []


def test_dry_run_sync_never_creates_a_real_exchange_session(store, monkeypatch):
    db, _ = store
    trade = CCCXTTradeEngine(db, ccxt_conf={"mode": "dry_run", "default_type": "swap"}, push_msg=False)
    def forbidden():
        raise AssertionError("must not reach a real session")
    monkeypatch.setattr(trade, "get_exchange", forbidden)
    with pytest.raises(CChanException):
        trade.sync_execution_facts(CODE, account_scope="offline-account", start_ms=1, end_ms=2)
    assert counts(db) == [0, 0]


def test_a_foreign_execution_schema_is_not_adopted_or_destroyed(tmp_path):
    path = str(tmp_path/"foreign.db")
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE chanpy_execution_facts(keep TEXT)")
        conn.execute("INSERT INTO chanpy_execution_facts VALUES('original')")
    with pytest.raises(CChanException):
        CChanDB(db_conf={"type": "sqlite", "sqlite_path": path})
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM chanpy_execution_facts").fetchall() == [("original",)]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='chan_trade'").fetchall() == []


@pytest.mark.parametrize("damage", ["fact_bytes", "manifest_bytes", "missing_fact"])
def test_reader_verifies_persisted_bytes_and_manifest_links(store, damage):
    from Trade.ExecutionStore import SCHEMA
    db, _ = store
    receipt = scan()
    db.store_execution_scan(receipt)
    table = "chanpy_execution_scans" if damage == "manifest_bytes" else "chanpy_execution_facts"
    verb = "delete" if damage == "missing_fact" else "update"
    trigger = f"{table}_no_{verb}"
    db.db.execute(f"DROP TRIGGER {trigger}")
    if damage == "missing_fact":
        db.db.execute(f"DELETE FROM {table} WHERE kind='trade'")
    else:
        db.db.execute(f"UPDATE {table} SET payload=payload || ' '")
    db.db.execute(SCHEMA[trigger])
    with pytest.raises(CChanException):
        db.get_execution_scans("offline-account", CODE)


def test_a_rehashed_promotion_of_source_observation_to_reconciliation_is_rejected(store):
    import hashlib
    from CustomBuySellPoint.Decision import canonical_bytes
    db, _ = store
    receipt = scan()
    receipt["payload"]["economics_complete"] = True
    receipt["payload_sha256"] = hashlib.sha256(canonical_bytes(receipt["payload"])).hexdigest()
    with pytest.raises(CChanException):
        db.store_execution_scan(receipt)
    assert counts(db) == [0, 0]


def test_okx_bill_id_cannot_pay_as_both_trade_and_funding(store):
    db, _ = store
    first = scan("okx")
    db.store_execution_scan(first)
    start = first["payload"]["start_ms"]
    # fills.billId and bills.billId share the account-wide bill namespace.
    conflicting = collect(NativeSources("okx", cash=[funding("okx", start+1, key=1101)]), start, start+100)
    with pytest.raises(CChanException):
        db.store_execution_scan(conflicting)
    assert counts(db) == [2, 1]


def test_funding_id_cannot_be_reassigned_to_another_symbol_and_returns_typed_failure(store):
    from Trade.ExecutionFacts import collect_execution_scan
    from .test_execution_facts import definition
    db, _ = store
    first = scan()
    db.store_execution_scan(first)
    start = first["payload"]["start_ms"]
    market = definition("binance")
    market.update(id="OTHERUSDT", symbol="OTHER/USDT:USDT", base="OTHER")
    raw = funding("binance", start+2)
    raw["symbol"] = "OTHERUSDT"
    second = collect_execution_scan(NativeSources("binance", cash=[raw]), market, account_scope="offline-account",
                                    mode="testnet", start_ms=start, end_ms=start+100)
    with pytest.raises(CChanException):
        db.store_execution_scan(second)
    assert counts(db) == [2, 1]


def test_import_publishes_one_frozen_input_even_if_the_callers_dictionary_changes(store, monkeypatch):
    db, _ = store
    receipt = scan()
    frozen = copy.deepcopy(receipt)
    execute = db.db.execute
    changed = []
    def interleave(sql, args=()):
        result = execute(sql, args)
        if sql.startswith("INSERT INTO chanpy_execution_facts") and not changed:
            cash = receipt["payload"]["facts"][1]
            cash["raw"]["income"] = "-0.04"
            cash["cash_delta"] = "-0.04"
            changed.append(True)
        return result
    monkeypatch.setattr(db.db, "execute", interleave)
    db.store_execution_scan(receipt)
    assert changed and receipt != frozen
    assert db.get_execution_scans("offline-account", CODE) == [frozen]
    assert db.get_execution_facts("offline-account", CODE, venue="binance", mode="testnet") == frozen["payload"]["facts"]
