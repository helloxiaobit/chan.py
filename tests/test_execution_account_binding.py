"""Native scan association is atomic and never backfills legacy account proof."""
import copy
import hashlib
import json

import pytest

from Common.ChanException import CChanException
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.AccountIdentity import observe_account_context
from Trade.db_util import CChanDB
from .test_crypto_account_binding import switch_account
from .test_crypto_order_contract import CODE
from .test_crypto_venue_parameters import venue_engine
from .test_execution_facts import NativeSources, collect, fill, funding
from .test_execution_store import counts, scan, store


def observation(trade):
    at = utc_now_ms()
    return {"before": observe_account_context(trade.exchange, trade.mode),
        "after": observe_account_context(trade.exchange, trade.mode), "started_ms": at, "finished_ms": utc_now_ms()}


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_new_scan_binds_native_context_without_changing_original_receipt_and_survives_restart(store, tmp_path, venue):
    db, conf = store
    trade, receipt = venue_engine(db, tmp_path, venue), scan(venue)
    observed = observation(trade)
    original = copy.deepcopy(receipt)
    key = db.store_execution_scan(receipt, account_observation=observed)
    assert receipt == original
    reopened = CChanDB(db_conf=conf)
    try:
        assert reopened.get_execution_scans("offline-account", CODE) == [original]
        linked = reopened.get_execution_scan_account(key)
        assert linked["scan_id"] == original["payload_sha256"]
        assert linked["observation"]["account_context"] == observed["before"] == observed["after"]
        assert linked["observation"]["started_ms"] == observed["started_ms"]
        assert linked["observation"]["finished_ms"] == observed["finished_ms"]
        assert linked["observation"]["coverage"] == "native_context_observed_around_scan"
        assert original["payload"]["account_scope_verified"] is original["payload"]["economics_complete"] is False
        assert db.db.query("SELECT * FROM chan_trade") == []
    finally:
        reopened.close()


def test_legacy_scan_cannot_be_promoted_after_it_was_persisted(store, tmp_path):
    db, _ = store
    receipt = scan()
    db.store_execution_scan(receipt)
    with pytest.raises(CChanException):
        db.store_execution_scan(receipt, account_observation=observation(venue_engine(db, tmp_path, "binance")))
    assert db.get_execution_scan_account(receipt["payload_sha256"]) is None
    assert db.get_execution_scans("offline-account", CODE) == [receipt]
    assert counts(db) == [2, 1]


def test_duplicate_bound_scan_keeps_first_observation_and_cannot_strip_it(store, tmp_path):
    db, _ = store
    trade, receipt = venue_engine(db, tmp_path, "binance"), scan()
    db.store_execution_scan(receipt, account_observation=observation(trade))
    before = db.get_execution_scan_account(receipt["payload_sha256"])
    db.store_execution_scan(copy.deepcopy(receipt), account_observation=observation(trade))
    assert db.get_execution_scan_account(receipt["payload_sha256"]) == before
    with pytest.raises(CChanException):
        db.store_execution_scan(receipt)
    assert counts(db) == [2, 1]


@pytest.mark.parametrize("damage", ["account", "unbound", "venue", "mode", "before_after", "bool_clock", "reversed_clock", "future_clock"])
def test_bound_namespace_or_invalid_observation_cannot_publish_new_facts(store, tmp_path, damage):
    db, _ = store
    trade, first = venue_engine(db, tmp_path, "binance"), scan()
    db.store_execution_scan(first, account_observation=observation(trade))
    start = first["payload"]["start_ms"]
    second = collect(NativeSources("binance", [fill("binance", start+3, key=202)], []), start, start+100)
    if damage == "account":
        switch_account(trade.exchange)
    observed = observation(trade)
    if damage in {"venue", "mode"}:
        for side in ("before", "after"):
            observed[side][damage] = "okx" if damage == "venue" else "live"
            observed[side]["context_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in observed[side].items() if k != "context_id"})).hexdigest()
    elif damage == "before_after":
        switch_account(trade.exchange)
        observed["after"] = observe_account_context(trade.exchange, trade.mode)
    elif damage == "bool_clock":
        observed["started_ms"] = True
    elif damage == "reversed_clock":
        observed["started_ms"] = observed["finished_ms"]+1
    elif damage == "future_clock":
        observed["finished_ms"] += 86_400_000
    with pytest.raises(CChanException):
        db.store_execution_scan(second, account_observation=None if damage == "unbound" else observed)
    assert counts(db) == [2, 1]
    assert db.get_execution_scans("offline-account", CODE) == [first]


def test_new_bound_scan_does_not_relabel_older_unbound_scan_with_same_scope(store, tmp_path):
    db, _ = store
    first = scan()
    db.store_execution_scan(first)
    start = first["payload"]["start_ms"]
    second = collect(NativeSources("binance", [fill("binance", start+3, key=202)], []), start, start+100)
    db.store_execution_scan(second, account_observation=observation(venue_engine(db, tmp_path, "binance")))
    assert db.get_execution_scan_account(first["payload_sha256"]) is None
    assert db.get_execution_scan_account(second["payload_sha256"]) is not None
    assert all(s["payload"]["account_scope_verified"] is False for s in db.get_execution_scans("offline-account", CODE))


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("changed", [False, True])
def test_engine_associates_new_scan_only_if_native_account_stays_stable(store, tmp_path, monkeypatch, venue, changed):
    db, _ = store
    trade = venue_engine(db, tmp_path, venue)
    start = utc_now_ms()-10_000
    native = NativeSources(venue, [fill(venue, start+1)], [funding(venue, start+2)])
    original_request = native.request

    def request(*args, **kwargs):
        result = original_request(*args, **kwargs)
        if changed:
            switch_account(trade.exchange)
        return result

    native.request = request
    for name in ("fapiPrivateGetUserTrades", "fapiPrivateGetIncome", "privateGetTradeFillsHistory", "privateGetTradeFills", "privateGetAccountBillsArchive"):
        monkeypatch.setattr(trade.exchange, name, getattr(native, name), raising=False)
    if changed:
        with pytest.raises(CChanException):
            trade.sync_execution_facts(CODE, account_scope="offline-account", start_ms=start, end_ms=start+100)
        assert counts(db) == [0, 0]
    else:
        receipt = trade.sync_execution_facts(CODE, account_scope="offline-account", start_ms=start, end_ms=start+100)
        assert db.get_execution_scan_account(receipt["payload_sha256"])["observation"]["account_context"] == observe_account_context(trade.exchange, trade.mode)
        assert db.get_execution_scans("offline-account", CODE) == [receipt]
    assert trade.exchange.created == []
    assert db.db.query("SELECT * FROM chan_trade") == []


@pytest.mark.parametrize("damage", ["missing_context", "missing_schema", "null_context", "wrong_clock", "wrong_account", "scan_id", "invalid_reference", "missing_reference", "missing_scope", "missing_observation"])
def test_rehashed_bound_manifest_damage_is_a_closed_domain_failure(store, tmp_path, damage):
    from Trade.ExecutionStore import SCHEMA
    db, _ = store
    receipt = scan()
    db.store_execution_scan(receipt, account_observation=observation(venue_engine(db, tmp_path, "binance")))
    row = db.db.query_one("SELECT * FROM chanpy_execution_scans")
    manifest = json.loads(row["payload"])
    if damage == "missing_context":
        del manifest["context"]
    elif damage == "missing_schema":
        del manifest["schema"]
    elif damage == "null_context":
        manifest["context"] = None
    elif damage == "wrong_clock":
        manifest["native_account"]["finished_ms"] = True
    elif damage == "wrong_account":
        manifest["native_account"]["account_context"]["context_id"] = "0"*64
    elif damage == "scan_id":
        manifest["receipt_sha256"] = "0"*64
    elif damage == "invalid_reference":
        manifest["facts"][0] = None
    elif damage == "missing_reference":
        del manifest["facts"][0]["kind"]
    elif damage == "missing_observation":
        del manifest["native_account"]
    else:
        del manifest["context"]["account_scope"]
    raw = canonical_bytes(manifest).decode()
    db.db.execute("DROP TRIGGER chanpy_execution_scans_no_update")
    db.db.execute("UPDATE chanpy_execution_scans SET payload=?,payload_sha256=?", (raw, hashlib.sha256(raw.encode()).hexdigest()))
    db.db.execute(SCHEMA["chanpy_execution_scans_no_update"])
    with pytest.raises(CChanException):
        db.get_execution_scan_account(receipt["payload_sha256"])


def test_failure_of_first_bound_manifest_insert_rolls_back_facts_and_context(store, tmp_path):
    db, _ = store
    receipt = scan()
    db.db.execute("CREATE TRIGGER fail_bound BEFORE INSERT ON chanpy_execution_scans BEGIN SELECT RAISE(ABORT,'bound scan failed'); END")
    with pytest.raises(CChanException):
        db.store_execution_scan(receipt, account_observation=observation(venue_engine(db, tmp_path, "binance")))
    assert counts(db) == [0, 0] and not db.db.conn.in_transaction


def test_source_and_observation_are_one_owned_snapshot_before_first_insert(store, tmp_path, monkeypatch):
    db, _ = store
    receipt, observed = scan(), observation(venue_engine(db, tmp_path, "binance"))
    original, native = copy.deepcopy(receipt), copy.deepcopy(observed)
    execute = db.db.execute

    def changed(sql, args=()):
        result = execute(sql, args)
        if sql.startswith("INSERT INTO chanpy_execution_facts"):
            observed["after"]["context_id"] = "changed-after-lock"
            receipt["payload"]["facts"][-1]["cash_delta"] = "999"
        return result

    monkeypatch.setattr(db.db, "execute", changed)
    key = db.store_execution_scan(receipt, account_observation=observed)
    assert db.get_execution_scans("offline-account", CODE) == [original]
    assert db.get_execution_scan_account(key)["observation"]["account_context"] == native["before"]


def test_already_open_second_connection_observes_first_account_binding(store, tmp_path):
    db, conf = store
    second = CChanDB(db_conf=conf)
    try:
        trade = venue_engine(db, tmp_path, "binance")
        first = scan()
        db.store_execution_scan(first, account_observation=observation(trade))
        switch_account(trade.exchange)
        start = first["payload"]["start_ms"]
        receipt = collect(NativeSources("binance", [fill("binance", start+3, key=202)], []), start, start+100)
        with pytest.raises(CChanException):
            second.store_execution_scan(receipt, account_observation=observation(trade))
        assert counts(db) == counts(second) == [2, 1]
        assert second.get_execution_scan_account(first["payload_sha256"])["observation"]["account_context"] != observation(trade)["before"]
    finally:
        second.close()


@pytest.mark.parametrize("damage", ["missing_fact", "non_object", "missing_market"])
def test_bound_scan_missing_fact_document_fields_is_a_closed_domain_failure(store, tmp_path, damage):
    from Trade.ExecutionStore import SCHEMA
    db, _ = store
    receipt = scan()
    db.store_execution_scan(receipt, account_observation=observation(venue_engine(db, tmp_path, "binance")))
    row = db.db.query_one("SELECT * FROM chanpy_execution_facts WHERE kind='trade'")
    value = json.loads(row["payload"])
    if damage == "non_object":
        value = []
    else:
        del value["fact" if damage == "missing_fact" else "market"]
    raw, digest = canonical_bytes(value).decode(), hashlib.sha256(canonical_bytes(value)).hexdigest()
    db.db.execute("DROP TRIGGER chanpy_execution_facts_no_update")
    db.db.execute("UPDATE chanpy_execution_facts SET payload=?,payload_sha256=? WHERE kind='trade'", (raw, digest))
    db.db.execute(SCHEMA["chanpy_execution_facts_no_update"])
    # Link hashes still point at the original fact, but the direct fact reader
    # must also reject structural damage rather than leaking a parser exception.
    with pytest.raises(CChanException):
        db.get_execution_facts("offline-account", CODE, venue="binance", mode="testnet")
