"""Original local order identity is necessary, never a send capability."""
import copy
import importlib
import importlib.util

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.AccountRiskStore import account_key, _sha
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import single_case
from .test_native_monetary_engine import claimed_order, apply_query
from .test_m6_trade import make_signal


def reader():
    assert importlib.util.find_spec("Trade.NativeManagement") is not None, "original management identity reader is missing"
    return importlib.import_module("Trade.NativeManagement").read_native_management_order_identity


def test_identity_is_rebuilt_from_original_db_history_and_l2_without_io_or_release(single_case, monkeypatch):
    case = single_case
    state, record, contract = claimed_order(case, monkeypatch)
    apply_query(case, record)
    db = case["db"]
    record = copy.deepcopy(db.get_record(case["key"]))
    history = copy.deepcopy(db.get_order_history(case["key"]))
    calls, changes = len(case["http_calls"]), db.db.conn.total_changes
    requests = copy.deepcopy(state["requests"])
    document = reader()(db, case["key"], phase="open")
    assert document["schema"] == "chan-native-management-identity-v1"
    payload = document["payload"]
    assert document["payload_sha256"] == _sha(payload)
    assert payload["account_key"] == account_key(contract["account_context"])
    assert payload["account_context"] == contract["account_context"]
    assert payload["target"] == {"trade_table": db.table, "record_id": case["key"], "phase": "open", "attempt": 1,
        "client_order_id": record["open_client_order_id"], "native_order_id": "123456"}
    assert payload["identity"] == history["attempts"][0]["identity"]
    assert payload["record_sha256"] == _sha(record) and payload["history_sha256"] == _sha(history)
    assert payload["local_remaining_quantity"] == "0.02"
    assert payload["native_quantity_verified"] is payload["operation_authorized"] is False
    assert len(payload["native_roots"]) == 1 and payload["native_roots"][0]["stage"] == "claim"
    assert len(case["http_calls"]) == calls and state["requests"] == requests
    assert db.db.conn.total_changes == changes
    assert db.get_record(case["key"]) == record and db.get_order_history(case["key"]) == history
    # Caller copies are neither original bytes nor permission to mutate.
    document["payload"]["account_context"]["identifier_sha256"] = "f"*64
    assert reader()(db, case["key"], phase="open")["payload"]["account_context"] == contract["account_context"]
    assert canonical_bytes(db.get_order_history(case["key"])) == canonical_bytes(history)


@pytest.mark.parametrize("record_id,phase", [(True, "open"), (0, "open"), (-1, "open"), ("1", "open"),
    (1, None), (1, "cover"), (1, "OPEN"), (1, True)])
def test_invalid_identity_request_is_rejected_before_reading_a_record(store, monkeypatch, record_id, phase):
    db, _ = store
    monkeypatch.setattr(db, "get_record", lambda *a: pytest.fail("invalid request must not reach DB records"))
    with pytest.raises(CChanException):
        reader()(db, record_id, phase=phase)


def test_original_connection_is_checked_before_the_next_history_query(store, monkeypatch):
    db, _ = store
    key = db.add_signal(make_signal())
    original = db.get_record
    database, connection = db.db, db.db.conn
    foreign_calls = []
    class ForeignConnection:
        def execute(self, *a, **k):
            foreign_calls.append(a)
            raise AssertionError("foreign connection must never be queried")
    def replaced(record_id):
        record = original(record_id)
        database.conn = ForeignConnection()
        return record
    monkeypatch.setattr(db, "get_record", replaced)
    try:
        with pytest.raises(CChanException):
            reader()(db, key, phase="open")
    finally:
        database.conn = connection
    assert foreign_calls == [], "owner drift must be refused before the next SQL, not after it"
    assert not connection.in_transaction


def test_missing_or_changed_original_projection_cannot_become_a_management_identity(single_case, monkeypatch):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    apply_query(case, record)
    db, key = case["db"], case["key"]
    original = copy.deepcopy(db.get_record(key))
    history = copy.deepcopy(db.get_order_history(key))
    calls, requests = len(case["http_calls"]), copy.deepcopy(state["requests"])
    observe = reader()
    with pytest.raises(CChanException):
        observe(db, key, phase="close")
    for field, value in [("current_qty", .03), ("open_filled_qty", .03), ("cover_filled_qty", .01),
                         ("open_attempt", 2), ("stock_code", "ALT/USDT:USDT"), ("position_side", "SHORT")]:
        with pytest.raises(CChanException):
            with db.db.transaction():
                db.db.execute(f"UPDATE {db.table} SET {field}=? WHERE id=?", (value, key))
                observe(db, key, phase="open")
        assert db.get_record(key) == original and db.get_order_history(key) == history
    assert len(case["http_calls"]) == calls and state["requests"] == requests


def test_local_remainder_sums_original_partial_close_attempts_without_claiming_native_capacity(single_case, monkeypatch):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    apply_query(case, record)
    engine, db, key = case["trade"], case["db"], case["key"]
    assert engine.cancel_order(record["stock_code"], "123456") is True
    apply_query(case, record)
    # Exercise only the original local close writer/claim/ACK/report contract.
    # These synthetic reports are not actual management POSTs or position proof.
    for attempt, quantity, filled, price in [(1, .02, .01, 300), (2, .01, .005, 600)]:
        current = db.get_record(key)
        amount, order_price, contract = engine.prepare_order(current["stock_code"], quantity, price,
            reduce_only=True, record=current)
        client_id = "originalManagementClose"+str(attempt)
        assert db.acquire_close_intent(key, amount, client_id, "fake local close", order_contract=contract,
            previous_attempt=attempt-1)
        assert db.claim_order_submission(key, "close")
        db.record_order_ack(key, "close", str(77+attempt), client_order_id=client_id, expected_attempt=attempt)
        db.apply_close_fill(key, filled, order_price, "canceled", client_order_id=client_id,
            order_id=str(77+attempt), expected_attempt=attempt)
    original, history = db.get_record(key), db.get_order_history(key)
    calls, changes, requests = len(case["http_calls"]), db.db.conn.total_changes, copy.deepcopy(state["requests"])
    document = reader()(db, key, phase="close")
    payload = document["payload"]
    assert payload["target"]["phase"] == "close" and payload["target"]["attempt"] == 2
    assert payload["target"]["native_order_id"] == "79"
    assert payload["local_remaining_quantity"] == "0.005"
    assert payload["native_quantity_verified"] is payload["operation_authorized"] is False
    assert db.get_record(key) == original and db.get_order_history(key) == history
    assert db.db.conn.total_changes == changes and len(case["http_calls"]) == calls and state["requests"] == requests
