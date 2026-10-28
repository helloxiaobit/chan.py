"""Sticky account-wide freezes survive restart and never block proven reduction."""
import copy
import hashlib
import sqlite3

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.db_util import CChanDB
from .test_account_reconciliation import interval_case
from .test_crypto_order_contract import CODE, open_legacy_history
from .test_crypto_venue_parameters import venue_engine
from .test_execution_store import store
from .test_m6_trade import make_signal


TABLE = "chanpy_account_checks"


def persist(db, inputs):
    return {"account_context": inputs["before"]["payload"]["account_context"],
        "before_id": db.store_account_evidence(inputs["before"]), "after_id": db.store_account_evidence(inputs["after"]),
        "wallet_ids": [db.store_account_evidence(d) for d in inputs["wallets"]],
        "execution_scan_ids": [d["receipt"]["payload_sha256"] for d in inputs["executions"]]}


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_check_reloads_sources_and_histories_from_one_db_snapshot_and_is_replayable(store, tmp_path, monkeypatch, venue):
    db, conf = store
    inputs, _, key = interval_case(db, tmp_path, monkeypatch, venue)
    params = persist(db, inputs)
    before = db.get_record(key)
    check = db.reconcile_account(**params)
    assert check["payload"]["report"]["payload"]["status"] == "matched_observations"
    check_id = hashlib.sha256(canonical_bytes(check)).hexdigest()
    assert db.get_account_check(check_id) == check
    assert db.get_record(key) == before
    assert db.get_account_risk_state(params["account_context"])["frozen"] is False
    assert db.get_account_risk_state(params["account_context"])["admission_verified"] is False
    assert db.reconcile_account(**params) == check
    assert db.db.query_one(f"SELECT count(*) AS n FROM {TABLE}")["n"] == 1
    reopened = CChanDB(db_conf=conf)
    try:
        assert reopened.get_account_check(check_id) == check
    finally:
        reopened.close()


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_missing_evidence_freezes_atomically_and_later_match_never_unlocks(store, tmp_path, monkeypatch, venue):
    db, conf = store
    inputs, trade, key = interval_case(db, tmp_path, monkeypatch, venue)
    params = persist(db, inputs)
    failed = db.reconcile_account(**{**params, "wallet_ids": []})
    assert failed["payload"]["report"]["payload"]["status"] == "incomplete"
    assert db.get_account_risk_state(params["account_context"])["frozen"] is True
    matched = db.reconcile_account(**params)
    assert matched["payload"]["report"]["payload"]["status"] == "matched_observations"
    reopened = CChanDB(db_conf=conf)
    try:
        state = reopened.get_account_risk_state(params["account_context"])
        assert state["frozen"] is True and len(state["check_ids"]) == 2
        next_key = db.add_signal(make_signal(code=CODE, is_buy=False))
        for connection in (db, reopened):
            _, _, contract = trade.prepare_order(CODE, 0.03, 100, reduce_only=True, record=db.get_record(key))
            # New-risk gate is based on phase, not the caller's reduce_only flag.
            with pytest.raises(CChanException):
                connection.acquire_open_intent(next_key, 0.03, f"frozen-{next_key}-{id(connection)}", order_contract=contract)
            assert connection.get_record(next_key)["open_attempt"] == 0
            assert connection.get_order_history(next_key)["attempts"] == []
    finally:
        reopened.close()
    with pytest.raises(CChanException):
        trade.prepare_order(CODE, 0.03, 100)
    # Account freeze does not repeal the original account/kill/candidate gates.
    trade.exchange.fill, trade.exchange.status = 2, "closed"
    trade.cover_trade(db.get_record(key), 111, "frozen account reduction")
    assert db.get_record(key)["current_qty"] == 0
    assert db.get_account_risk_state(params["account_context"])["frozen"] is True


@pytest.mark.parametrize("damage", ["missing_document", "corrupt_source", "projection_drift"])
def test_unreadable_input_persists_redacted_failure_instead_of_rolling_back_freeze(store, tmp_path, monkeypatch, damage):
    db, _ = store
    inputs, _, key = interval_case(db, tmp_path, monkeypatch, "binance")
    params = persist(db, inputs)
    if damage == "missing_document":
        params["after_id"] = "0"*64
    elif damage == "projection_drift":
        db.db.execute("UPDATE chan_trade SET current_qty=9 WHERE id=?", (key,))
    else:
        from Trade.AccountStore import SCHEMA
        db.db.execute("DROP TRIGGER chanpy_account_evidence_no_update")
        db.db.execute("UPDATE chanpy_account_evidence SET payload=payload || ' '")
        db.db.execute(SCHEMA["chanpy_account_evidence_no_update"])
    failed = db.reconcile_account(**params)
    assert failed["payload"]["inputs"] is None
    assert failed["payload"]["report"]["payload"]["issues"] == [{"reason": "evidence_unavailable", "severity": "incomplete"}]
    assert db.get_account_risk_state(params["account_context"])["frozen"] is True
    assert not db.db.conn.in_transaction


@pytest.mark.parametrize("verb", ["UPDATE", "DELETE", "REPLACE"])
def test_check_is_append_only_including_sqlite_replace(store, tmp_path, monkeypatch, verb):
    db, _ = store
    inputs, _, _ = interval_case(db, tmp_path, monkeypatch, "binance")
    params = persist(db, inputs)
    db.reconcile_account(**{**params, "wallet_ids": []})
    sql = f"UPDATE {TABLE} SET status='matched_observations'" if verb == "UPDATE" else f"DELETE FROM {TABLE}" if verb == "DELETE" else f"INSERT OR REPLACE INTO {TABLE} SELECT * FROM {TABLE}"
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.db.execute(sql)
    assert db.get_account_risk_state(params["account_context"])["frozen"] is True


def test_other_connection_freeze_between_intent_and_claim_rolls_back_claim_only(store, tmp_path, monkeypatch):
    db, conf = store
    inputs, trade, _ = interval_case(db, tmp_path, monkeypatch, "binance")
    params = persist(db, inputs)
    quantity, price, contract = trade.prepare_order(CODE, 0.03, 100)
    key = db.add_signal(make_signal(code=CODE, is_buy=False))
    assert db.acquire_open_intent(key, quantity, "before-freeze", order_contract=contract)
    original = db.get_order_history(key)
    other = CChanDB(db_conf=conf)
    try:
        other.reconcile_account(**{**params, "wallet_ids": []})
        with pytest.raises(CChanException):
            db.claim_order_submission(key, "open")
        assert db.get_record(key)["open_order_status"] == "created"
        assert db.get_order_history(key) == original
    finally:
        other.close()


@pytest.mark.parametrize("damage", ["account_key_column", "history_resealed", "source_ids_resealed"])
def test_fresh_risk_reader_does_not_trust_mutable_columns_or_resealed_journal_snapshots(store, tmp_path, monkeypatch, damage):
    from Trade.AccountRiskStore import SCHEMA
    db, _ = store
    inputs, _, _ = interval_case(db, tmp_path, monkeypatch, "binance")
    params = persist(db, inputs)
    check = db.reconcile_account(**params)
    db.db.execute(f"DROP TRIGGER {TABLE}_no_update")
    if damage == "account_key_column":
        db.db.execute(f"UPDATE {TABLE} SET account_key=?", ("0"*64,))
    else:
        if damage == "history_resealed":
            # An irrelevant event clock still belongs to the immutable journal;
            # rehashing the check alone must not create a second journal truth.
            check["payload"]["inputs"]["histories"][0]["attempts"][0]["events"][0]["observed_ms"] -= 1
            from Trade.AccountReconcile import build_account_reconciliation
            check["payload"]["report"] = build_account_reconciliation(**check["payload"]["inputs"])
        else:
            check["payload"]["source_ids"]["after"] = "0"*64
        check["payload_sha256"] = hashlib.sha256(canonical_bytes(check["payload"])).hexdigest()
        raw = canonical_bytes(check).decode()
        digest = hashlib.sha256(raw.encode()).hexdigest()
        db.db.execute(f"UPDATE {TABLE} SET check_id=?,payload=?,payload_sha256=?", (digest, raw, digest))
    db.db.execute(SCHEMA[f"{TABLE}_no_update"])
    with pytest.raises(CChanException):
        db.get_account_risk_state(params["account_context"])


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_stable_native_freeze_key_is_shared_by_custom_tables_not_caller_routes_or_scope(store, tmp_path, monkeypatch, venue):
    db, conf = store
    inputs, _, _ = interval_case(db, tmp_path, monkeypatch, venue)
    params = persist(db, inputs)
    db.reconcile_account(**{**params, "wallet_ids": []})
    other = CChanDB(table_name="second_strategy", db_conf=conf)
    try:
        assert other.get_account_risk_state(params["account_context"])["frozen"] is True
        engine = venue_engine(other, tmp_path, venue)
        if venue == "binance":
            engine.exchange.account_alias = "fake-Futures-A"
        with pytest.raises(CChanException):
            engine.prepare_order(CODE, 0.03, 100)
        changed_route = copy.deepcopy(params["account_context"])
        if venue == "okx":
            changed_route["environment"]["hostname"] = "www.okx.com"
            changed_route["context_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in changed_route.items() if k != "context_id"})).hexdigest()
            assert other.get_account_risk_state(changed_route)["frozen"] is True
        other_context = copy.deepcopy(params["account_context"])
        other_context["identifier_sha256"] = "f"*64
        other_context["context_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in other_context.items() if k != "context_id"})).hexdigest()
        assert other.get_account_risk_state(other_context)["frozen"] is False
    finally:
        other.close()


def test_existing_matched_check_does_not_reconcile_against_later_projection(store, tmp_path, monkeypatch):
    db, _ = store
    inputs, trade, key = interval_case(db, tmp_path, monkeypatch, "binance")
    params = persist(db, inputs)
    check = db.reconcile_account(**params)
    check_id = hashlib.sha256(canonical_bytes(check)).hexdigest()
    trade.exchange.fill, trade.exchange.status = 2, "closed"
    trade.cover_trade(db.get_record(key), 111, "later interval")
    assert db.get_account_check(check_id) == check
    assert db.get_account_risk_state(params["account_context"])["frozen"] is False


def test_other_native_account_in_same_database_is_not_netted_or_frozen_with_this_one(store, tmp_path, monkeypatch):
    db, conf = store
    inputs, _, _ = interval_case(db, tmp_path, monkeypatch, "binance")
    params = persist(db, inputs)
    other = CChanDB(table_name="another_native_account", db_conf=conf)
    try:
        engine = venue_engine(other, tmp_path, "binance")
        engine.exchange.account_alias = "different-Futures-account"
        engine.exchange.fill, engine.exchange.status = 3, "closed"
        key = other.add_signal(make_signal(code=CODE, is_buy=False))
        open_legacy_history(engine, other.get_record(key), 100)
        check = db.reconcile_account(**params)
        assert check["payload"]["report"]["payload"]["status"] == "matched_observations", check["payload"]["report"]
    finally:
        other.close()


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_freeze_after_successful_claim_stops_send_without_rearming_or_retrying_unknown(store, tmp_path, monkeypatch, venue):
    db, conf = store
    inputs, trade, _ = interval_case(db, tmp_path, monkeypatch, venue)
    params = persist(db, inputs)
    before_count = len(trade.exchange.created)
    key = db.add_signal(make_signal(code=CODE, is_buy=False))
    other = CChanDB(db_conf=conf)
    claim = db.claim_order_submission

    def freeze_after_claim(record_id, phase):
        result = claim(record_id, phase)
        other.reconcile_account(**{**params, "wallet_ids": []})
        return result

    monkeypatch.setattr(db, "claim_order_submission", freeze_after_claim)
    try:
        with pytest.raises(CChanException):
            open_legacy_history(trade, db.get_record(key), 100)
        assert db.get_record(key)["open_order_status"] == "submitting"
        assert db.get_record(key)["open_order_id"] is None
        assert db.get_record(key)["open_attempt"] == 1
        trade.restore()
        assert len(trade.exchange.created) == before_count
        assert db.get_record(key)["open_order_status"] == "submitting"
        assert db.get_record(key)["open_attempt"] == 1
    finally:
        other.close()


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_freeze_retains_original_account_cancel_and_query_paths(store, tmp_path, monkeypatch, venue):
    db, _ = store
    inputs, trade, _ = interval_case(db, tmp_path, monkeypatch, venue)
    params = persist(db, inputs)
    trade.exchange.fill, trade.exchange.status = 1, "open"
    key = db.add_signal(make_signal(code=CODE, is_buy=False))
    result = open_legacy_history(trade, db.get_record(key), 100)
    db.reconcile_account(**{**params, "wallet_ids": []})
    assert trade.cancel_order(CODE, result.order_id) is True
    result = trade.query_order(CODE, result.order_id, client_order_id=result.client_order_id)
    assert result.status == "canceled" and result.filled == 0.01
    assert db.get_account_risk_state(params["account_context"])["frozen"] is True


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_explicit_engine_reconciliation_uses_current_native_account_outside_writer_lock(store, tmp_path, monkeypatch, venue):
    db, _ = store
    inputs, trade, _ = interval_case(db, tmp_path, monkeypatch, venue)
    params = persist(db, inputs)
    profile_name = "fapiPrivateV3GetBalance" if venue == "binance" else "privateGetAccountConfig"
    profile = getattr(trade.exchange, profile_name)
    reads = []

    def observed(params):
        assert not db.db.conn.in_transaction
        reads.append(1)
        return profile(params)

    monkeypatch.setattr(trade.exchange, profile_name, observed)
    params.pop("account_context")
    before_count = len(trade.exchange.created)
    check = trade.reconcile_account_interval(**params)
    assert check["payload"]["report"]["payload"]["status"] == "matched_observations"
    assert len(reads) == 2 and len(trade.exchange.created) == before_count


def test_risk_schema_failure_does_not_partially_migrate_or_adopt_foreign_table(tmp_path):
    path = str(tmp_path/"foreign-risk.db")
    with sqlite3.connect(path) as connection:
        connection.execute(f"CREATE TABLE {TABLE}(foreign_payload TEXT)")
        connection.execute(f"INSERT INTO {TABLE} VALUES('keep-me')")
    with pytest.raises(CChanException):
        CChanDB(db_conf={"type": "sqlite", "sqlite_path": path})
    with sqlite3.connect(path) as connection:
        assert connection.execute(f"SELECT * FROM {TABLE}").fetchall() == [("keep-me",)]
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [(TABLE,)]


@pytest.mark.parametrize("pragma", ["recursive_triggers", "foreign_keys"])
def test_disabled_sqlite_integrity_pragmas_fail_closed_instead_of_skipping_freeze_validation(store, tmp_path, monkeypatch, pragma):
    db, _ = store
    inputs, _, _ = interval_case(db, tmp_path, monkeypatch, "binance")
    context = inputs["before"]["payload"]["account_context"]
    db.db.execute(f"PRAGMA {pragma}=OFF")
    with pytest.raises(CChanException):
        db.get_account_risk_state(context)


def test_check_publication_failure_leaves_no_partial_check_or_order_mutation(store, tmp_path, monkeypatch):
    db, _ = store
    inputs, _, key = interval_case(db, tmp_path, monkeypatch, "binance")
    params = persist(db, inputs)
    original = db.get_record(key)
    db.db.execute(f"CREATE TRIGGER reject_check BEFORE INSERT ON {TABLE} BEGIN SELECT RAISE(ABORT,'reject'); END")
    with pytest.raises(CChanException):
        db.reconcile_account(**{**params, "wallet_ids": []})
    assert db.db.query(f"SELECT * FROM {TABLE}") == []
    assert db.get_record(key) == original and not db.db.conn.in_transaction
