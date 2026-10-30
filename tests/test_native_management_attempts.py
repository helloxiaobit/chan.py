"""Original cold management sources across native legs and original attempts."""
import copy

import pytest

from Common.ChanException import CChanException
from Trade import NativeOrderTransition as Transition
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import capacity_case
from .test_native_management_sources import management_case, source_api, source_options
from .test_native_monetary_engine import apply_query
from .test_native_pending_orders import regular_row


def original_close_attempt(case, state, record):
    """Original local writer/ACK/report; not a management POST or capability."""
    engine, db, key = case["trade"], case["db"], case["key"]
    assert engine.cancel_order(record["stock_code"], "123456") is True
    apply_query(case, record)
    current = db.get_record(key)
    amount, price, contract = engine.prepare_order(current["stock_code"], .02, 300, reduce_only=True, record=current)
    client_id = "originalManagedClose1"
    assert db.acquire_close_intent(key, amount, client_id, "fake local close", order_contract=contract, previous_attempt=0)
    assert db.claim_order_submission(key, "close")
    db.record_order_ack(key, "close", "789123", client_order_id=client_id, expected_attempt=1)
    db.apply_close_fill(key, .005, price, "open", client_order_id=client_id, order_id="789123", expected_attempt=1)
    current = db.get_record(key)
    row = regular_row("binance", contract["market"]["id"], 789123)
    row.update(clientOrderId=client_id, origQty=contract["exchange_amount"], executedQty=".005", avgPrice="300", cumQuote="1.5",
        side="SELL" if current["is_buy"] else "BUY", positionSide=current["position_side"], type="LIMIT", origType="LIMIT",
        price="300", timeInForce="GTC", reduceOnly=contract["execution"]["position_mode"] == "one_way", status="PARTIALLY_FILLED",
        time=case["clock"]["now"], updateTime=case["clock"]["now"])
    state["row"] = row
    state["requested_native_order_id"] = "789123"
    state["position_added_base"] = "0.015"
    return current, contract


@pytest.mark.parametrize("phase", ["open", "close"])
def test_cold_management_get_keeps_original_attempt_account_leg_and_remaining_across_modes(capacity_case, monkeypatch, phase):
    case = capacity_case
    engine, state, record, contract = management_case(case, monkeypatch, cold=True)
    if phase == "close":
        record, contract = original_close_attempt(case, state, record)
    original, history = case["db"].get_record(case["key"]), case["db"].get_order_history(case["key"])
    root = Transition.read_native_order_transition(case["db"], case["key"])
    calls = copy.deepcopy(state["requests"])
    payload = source_api()(engine, case["key"], phase=phase, **source_options(case))["payload"]
    identity = payload["identity"]["payload"]
    assert identity["target"]["phase"] == phase and identity["target"]["attempt"] == 1
    assert identity["identity"]["position_side"] == original["position_side"]
    assert identity["identity"]["is_buy"] == original["is_buy"]
    assert identity["identity"]["order_contract"]["execution"] == contract["execution"]
    assert identity["local_remaining_quantity"] == ("0.02" if phase == "open" else "0.015")
    assert payload["account_context"] == contract["account_context"]
    assert payload["order"]["order_id"] == ("123456" if phase == "open" else "789123")
    assert payload["order"]["filled"] == (.02 if phase == "open" else .005)
    assert payload["native_quantity_verified"] is payload["operation_authorized"] is False
    assert [method for method, _ in state["requests"]][len(calls):] == ["GET"]
    assert case["db"].get_record(case["key"]) == original and case["db"].get_order_history(case["key"]) == history
    assert Transition.read_native_order_transition(case["db"], case["key"]) == root
    assert engine.exchange is not case["client"]
    with pytest.raises(CChanException, match="管理专用"):
        engine.cancel_order(original["stock_code"], payload["order"]["order_id"])
