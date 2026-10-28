"""Historical attempts survive slot replacement; actual SQLite, no network."""
import json
import sqlite3

import pytest

from Common.ChanException import CChanException
from Trade.db_util import CChanDB
from .test_m6_trade import make_signal


@pytest.fixture()
def store(tmp_path):
    conf = {"type": "sqlite", "sqlite_path": str(tmp_path/"history.db")}
    db = CChanDB(db_conf=conf)
    try:
        yield db, conf
    finally:
        db.close()


def opening(db):
    key = db.add_signal(make_signal())
    assert db.acquire_open_intent(key, 10, f"open-{key}")
    assert db.claim_order_submission(key, "open")
    db.record_order_ack(key, "open", f"server-{key}", client_order_id=f"open-{key}", expected_attempt=1)
    return key


def opened(db):
    key = opening(db)
    db.apply_open_fill(key, 10, 100, "closed")
    return key


def attempts(db, key):
    return db.get_order_history(key)["attempts"]


def test_new_intent_claim_ack_and_reports_have_ordered_immutable_evidence(store):
    db, _ = store
    key = opening(db)
    db.apply_open_fill(key, 4, 101, "open")
    db.apply_open_fill(key, 10, 100, "closed")
    history = db.get_order_history(key)
    assert history["coverage"] == "intents_and_applied_reports_only"
    assert history["economics_complete"] is False
    assert history["gaps"] == []
    attempt, = history["attempts"]
    assert attempt["origin"] == "new_intent"
    assert attempt["identity"]["client_order_id"] == f"open-{key}"
    assert attempt["identity"]["requested_qty"] == 10
    assert attempt["identity"]["intent_ms"] == db.get_record(key)["open_intent_ms"]
    assert attempt["identity"]["order_contract"] is None
    assert [event["kind"] for event in attempt["events"]] == ["intent", "claim", "ack", "report", "report"]
    assert [event["state"]["filled_qty"] for event in attempt["events"]] == [0, 0, 0, 4, 10]
    assert attempt["events"][2]["state"]["order_id"] == f"server-{key}"
    assert [event["ordinal"] for event in attempt["events"]] == [1, 2, 3, 4, 5]
    assert all(type(event["observed_ms"]) is int for event in attempt["events"])


def test_partial_canceled_close_and_later_close_are_both_available_after_restart(store):
    db, conf = store
    key = opened(db)
    assert db.acquire_close_intent(key, 10, "first-exit", "partial")
    db.record_close_submission(key, "exit-server-1", "open")
    db.apply_close_fill(key, 4, 105, "canceled")
    first = attempts(db, key)[1]
    assert db.acquire_close_intent(key, 6, "next-exit", "finish", previous_attempt=1)
    db.record_close_submission(key, "exit-server-2", "open")
    db.apply_close_fill(key, 6, 102, "closed")
    restarted = CChanDB(db_conf=conf)
    try:
        history = restarted.get_order_history(key)
        assert history["attempts"][1] == first
        assert [(a["identity"]["phase"], a["identity"]["attempt"]) for a in history["attempts"]] == [
            ("open", 1), ("close", 1), ("close", 2)]
        assert history["attempts"][1]["events"][-1]["state"]["filled_qty"] == 4
        assert history["attempts"][2]["events"][-1]["state"]["current_qty"] == 0
        assert history["gaps"] == []
        # The historical lookup is deliberately NOT a current execution intent.
        assert restarted.get_order_intent("first-exit") is None
    finally:
        restarted.close()


def test_duplicates_and_failed_cas_do_not_append_facts(store):
    db, _ = store
    key = opened(db)
    before = db.get_order_history(key)
    assert db.acquire_open_intent(key, 10, "losing-intent") is False
    assert db.claim_order_submission(key, "open") is False
    assert db.apply_open_fill(key, 10, 100, "closed") == 0
    db.record_order_ack(key, "open", f"server-{key}", client_order_id=f"open-{key}", expected_attempt=1)
    assert db.get_order_history(key) == before


@pytest.mark.parametrize("point", ["intent", "claim", "ack", "report", "next_close"])
def test_a_failed_audit_append_rolls_back_the_projection_too(store, point):
    db, _ = store
    key = db.add_signal(make_signal()) if point == "intent" else opening(db)
    if point == "next_close":
        db.apply_open_fill(key, 10, 100, "closed")
        assert db.acquire_close_intent(key, 10, "old-exit", "old")
        db.apply_close_fill(key, 0, None, "canceled")
    if point == "claim":
        key = db.add_signal(make_signal(code="OTHER"))
        assert db.acquire_open_intent(key, 10, "unclaimed")
    if point == "ack":
        key = db.add_signal(make_signal(code="OTHER"))
        assert db.acquire_open_intent(key, 10, "noack")
        assert db.claim_order_submission(key, "open")
    before = db.get_record(key)
    prior = db.get_order_history(key)
    db.db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON chanpy_order_events BEGIN SELECT RAISE(ABORT, 'audit failed'); END")
    with pytest.raises((sqlite3.DatabaseError, CChanException)):
        if point == "intent":
            db.acquire_open_intent(key, 10, "rollback")
        elif point == "claim":
            db.claim_order_submission(key, "open")
        elif point == "ack":
            db.record_order_ack(key, "open", "new-server", client_order_id="noack", expected_attempt=1)
        elif point == "report":
            db.apply_open_fill(key, 4, 101, "open")
        else:
            db.acquire_close_intent(key, 10, "replacement", "new", previous_attempt=1)
    assert db.get_record(key) == before
    assert db.get_order_history(key) == prior
    assert not db.db.conn.in_transaction


@pytest.mark.parametrize("phase", ["open", "close"])
def test_a_historical_client_cannot_be_reused_in_another_phase_or_attempt(store, phase):
    db, _ = store
    key = opened(db)
    assert db.acquire_close_intent(key, 10, "spent-client", "old")
    db.apply_close_fill(key, 0, None, "canceled")
    target = key if phase == "close" else db.add_signal(make_signal(code="OTHER"))
    before = db.get_record(target)
    with pytest.raises((CChanException, sqlite3.IntegrityError)):
        if phase == "open":
            db.acquire_open_intent(target, 10, "spent-client")
        else:
            db.acquire_close_intent(target, 10, "spent-client", "new", previous_attempt=1)
    assert db.get_record(target) == before


@pytest.mark.parametrize("table", ["chanpy_order_attempts", "chanpy_order_events"])
@pytest.mark.parametrize("verb", ["UPDATE", "DELETE"])
def test_audit_tables_reject_in_place_changes(store, table, verb):
    db, _ = store
    opening(db)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.db.execute(f"DELETE FROM {table}" if verb == "DELETE" else f"UPDATE {table} SET observed_ms=0")


def test_legacy_snapshot_is_not_a_fabricated_past_intent(store):
    db, _ = store
    key = db.add_signal(make_signal())
    db.db.execute("UPDATE chan_trade SET status='open', is_open=1, open_requested_qty=10, open_filled_qty=10, "
                  "current_qty=10, open_price=100, open_attempt=1, open_client_order_id='old-open', "
                  "cover_attempt=2, cover_client_order_id='last-old-exit', cover_order_status='canceled' WHERE id=?", (key,))
    assert db.get_order_history(key)["gaps"]
    assert db.acquire_close_intent(key, 5, "new-exit", "new", previous_attempt=2)
    history = db.get_order_history(key)
    old_open, old_close, new_close = history["attempts"]
    assert [a["origin"] for a in history["attempts"]] == ["legacy_snapshot", "legacy_snapshot", "new_intent"]
    assert old_open["identity"]["intent_ms"] is None
    assert old_open["identity"]["order_contract"] is None
    assert old_close["identity"]["attempt"] == 2
    assert [event["kind"] for event in old_close["events"]] == ["legacy_snapshot"]
    assert new_close["identity"]["attempt"] == 3
    assert {gap["reason"] for gap in history["gaps"]} == {"legacy_snapshot", "missing_attempts"}


def test_unidentified_legacy_position_does_not_gain_a_fake_client_or_unit(store):
    db, _ = store
    key = db.add_signal(make_signal())
    db.mark_open(key, 100, 10, "legacy-server")
    history = db.get_order_history(key)
    assert history["attempts"] == []
    assert history["gaps"] == [{"phase": "open", "reason": "unidentified_legacy_order"}]
    assert db.acquire_close_intent(key, 5, "first-proven-exit", "manage legacy")
    assert len(attempts(db, key)) == 1
    assert db.get_order_history(key)["gaps"]


def test_reader_does_not_return_a_mutable_cached_ledger(store):
    db, _ = store
    key = opening(db)
    history = db.get_order_history(key)
    history["attempts"][0]["identity"]["client_order_id"] = "changed locally"
    history["attempts"][0]["events"].clear()
    assert len(attempts(db, key)[0]["events"]) == 3
    assert attempts(db, key)[0]["identity"]["client_order_id"] == f"open-{key}"


def test_whitelist_does_not_copy_errors_or_arbitrary_payloads_into_evidence(store):
    db, _ = store
    key = opening(db)
    db.set_open_err(key, "secret broker response")
    db.set_score_after(key, 0.5, {"apiKey": "do not log"})
    db.apply_open_fill(key, 4, 100, "open")
    raw = json.dumps(db.get_order_history(key))
    assert "secret broker response" not in raw
    assert "do not log" not in raw


def test_colliding_audit_schema_is_not_silently_adopted_or_overwritten(tmp_path):
    path = str(tmp_path/"foreign.db")
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE chanpy_order_attempts(secret TEXT)")
        conn.execute("INSERT INTO chanpy_order_attempts VALUES('keep')")
    with pytest.raises(CChanException):
        CChanDB(db_conf={"type": "sqlite", "sqlite_path": path})
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM chanpy_order_attempts").fetchall() == [("keep",)]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='chan_trade'").fetchall() == []


@pytest.mark.parametrize("damage", ["identity_bytes", "event_bytes", "ordinal", "previous_sha", "tail", "projection"])
def test_reader_recomputes_bytes_chain_and_current_identity_after_offline_damage(store, damage):
    from Trade.OrderAudit import SCHEMA
    db, _ = store
    key = opening(db)
    db.apply_open_fill(key, 4, 101, "open")
    # Simulate offline/corrupt writes, restore the production guard before read.
    if damage == "projection":
        db.db.execute("UPDATE chan_trade SET open_client_order_id='foreign' WHERE id=?", (key,))
    else:
        table = "chanpy_order_attempts" if damage == "identity_bytes" else "chanpy_order_events"
        verb = "delete" if damage == "tail" else "update"
        trigger = f"{table}_no_{verb}"
        db.db.execute(f"DROP TRIGGER {trigger}")
        if damage == "identity_bytes":
            db.db.execute(f"UPDATE {table} SET payload=payload || ' '")
        elif damage == "event_bytes":
            db.db.execute(f"UPDATE {table} SET payload=replace(payload, '101.0', '999.0') WHERE kind='report'")
        elif damage == "ordinal":
            db.db.execute(f"UPDATE {table} SET ordinal=8 WHERE ordinal=4")
        elif damage == "previous_sha":
            db.db.execute(f"UPDATE {table} SET previous_sha256='wrong' WHERE ordinal=4")
        else:
            db.db.execute(f"DELETE FROM {table} WHERE ordinal=4")
        db.db.execute(SCHEMA[trigger])
    with pytest.raises(CChanException):
        db.get_order_history(key)


def test_reopening_with_a_removed_immutability_guard_is_rejected(store):
    db, conf = store
    opening(db)
    db.db.execute("DROP TRIGGER chanpy_order_events_no_delete")
    with pytest.raises(CChanException):
        CChanDB(db_conf=conf)


@pytest.mark.parametrize("table", ["chanpy_order_attempts", "chanpy_order_events"])
def test_sqlite_replace_cannot_bypass_the_append_only_guard(store, table):
    db, _ = store
    opening(db)
    before = db.db.query(f"SELECT * FROM {table}")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.db.execute(f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}")
    assert db.db.query(f"SELECT * FROM {table}") == before


@pytest.mark.parametrize("changed", ["contract", "instrument"])
def test_a_successful_fill_cannot_silently_rewrite_attempt_identity(store, changed):
    db, _ = store
    key = opening(db)
    if changed == "contract":
        db.db.execute("UPDATE chan_trade SET open_order_contract='{}' WHERE id=?", (key,))
    else:
        db.db.execute("UPDATE chan_trade SET stock_code='OTHER' WHERE id=?", (key,))
    before = db.get_record(key)
    with pytest.raises(CChanException):
        db.apply_open_fill(key, 4, 100, "open", client_order_id=f"open-{key}", order_id=f"server-{key}", expected_attempt=1)
    assert db.get_record(key) == before


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_real_contract_and_both_historical_close_specs_survive_recovery(store, tmp_path, venue):
    from .test_crypto_order_contract import CODE, open_legacy_history
    from .test_crypto_order_recovery import recovery_engine
    db, _ = store
    trade = recovery_engine(db, tmp_path, venue)
    trade.exchange.fill, trade.exchange.status = 3, "closed"
    key = db.add_signal(make_signal(code=CODE))
    open_legacy_history(trade, db.get_record(key), 100)
    contract = json.loads(db.get_record(key)["open_order_contract"])
    trade.exchange.fill, trade.exchange.status = 1, "canceled"
    trade.cover_trade(db.get_record(key), 101, "partial exit")
    first = attempts(db, key)[1]
    trade.exchange.fill, trade.exchange.status = 2, "closed"
    trade.cover_trade(db.get_record(key), 102, "finish exit")
    history = db.get_order_history(key)
    assert history["gaps"] == []
    assert len(history["attempts"]) == 3
    assert history["attempts"][1] == first
    assert history["attempts"][0]["identity"]["order_contract"] == contract
    assert all(a["identity"]["contract_complete"] for a in history["attempts"])
    assert first["identity"]["order_contract"]["quantity"] == "0.03"
    assert history["attempts"][2]["identity"]["order_contract"]["quantity"] == "0.02"
    assert history["economics_complete"] is False  # A fee=None order is not zero-fee proof.


def test_next_report_cannot_hide_a_projection_that_disagrees_with_known_history(store):
    db, _ = store
    key = opening(db)
    db.db.execute("UPDATE chan_trade SET current_qty=9 WHERE id=?", (key,))
    before = db.get_record(key)
    with pytest.raises(CChanException):
        db.apply_open_fill(key, 4, 100, "open")
    assert db.get_record(key) == before


def test_failed_finite_encoding_rolls_back_new_identity_and_projection(store):
    db, _ = store
    key = opened(db)
    assert db.acquire_close_intent(key, 10, "old-close", "old")
    db.apply_close_fill(key, 0, None, "canceled")
    before = db.get_record(key)
    history = db.get_order_history(key)
    with pytest.raises(CChanException):
        db.acquire_close_intent(key, 10, "finite-check", "new", order_contract={"quantity": float("inf")}, previous_attempt=1)
    assert db.get_record(key) == before
    assert db.get_order_history(key) == history


def test_other_connection_never_sees_projection_without_its_audit_event(store, monkeypatch):
    db, conf = store
    key = opening(db)
    reader = sqlite3.connect(conf["sqlite_path"])
    execute = db.db.execute
    intermediate = []
    def observe(sql, args=()):
        result = execute(sql, args)
        if sql.startswith("UPDATE") or sql.startswith("INSERT"):
            qty = reader.execute("SELECT current_qty FROM chan_trade WHERE id=?", (key,)).fetchone()[0]
            events = reader.execute("SELECT count(*) FROM chanpy_order_events").fetchone()[0]
            intermediate.append((qty, events))
        return result
    try:
        monkeypatch.setattr(db.db, "execute", observe)
        db.apply_open_fill(key, 4, 100, "open")
        assert intermediate and set(intermediate) == {(0, 3)}
        assert reader.execute("SELECT current_qty FROM chan_trade WHERE id=?", (key,)).fetchone()[0] == 4
        assert reader.execute("SELECT count(*) FROM chanpy_order_events").fetchone()[0] == 4
    finally:
        reader.close()
