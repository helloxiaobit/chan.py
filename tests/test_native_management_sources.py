"""Owned management reads reuse the original SDK and never permit mutation."""
import copy
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from Common.ChanException import CChanException
from Trade.CCXTTradeEngine import CCCXTTradeEngine
from Trade import NativePreparation
from Trade import NativeManagement as Management
from Trade import NativeOrderTransition as Transition
from Trade.AccountRiskStore import _sha
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_management_role import configuration
from .test_native_capacity_prepared_intent import single_case
from .test_native_monetary_engine import claimed_order, apply_query


def test_original_runtime_enumeration_accepts_only_the_saved_management_role_without_opening_inputs(store):
    engine = CCCXTTradeEngine(store[0], ccxt_conf=configuration(), trade_conf={},
        environ={"CHANPY_KILL_SWITCH": "YES"}, management_only=True, push_msg=False)
    runtime = NativePreparation._selected_runtime(engine, None, engine._management_only_policy)
    assert runtime["coverage"] == "selected_management_callables"
    assert "Trade.SafetyPolicy:ManagementOnlyTradingSafetyPolicy.assert_order_allowed" in runtime["callables"]
    assert not any(key.startswith("Trade.Script.OpeningInputs:") for key in runtime["callables"])
    with pytest.raises(CChanException, match="管理专用"):
        engine.assert_order_mutation_allowed()


@pytest.mark.parametrize("role", ["ordinary", "query"])
def test_absent_opening_inputs_cannot_promote_another_role_into_management_runtime(store, role):
    engine = CCCXTTradeEngine(store[0], ccxt_conf={"mode": "dry_run"}, trade_conf={},
        environ={}, query_only=role == "query", push_msg=False)
    with pytest.raises(CChanException):
        NativePreparation._selected_runtime(engine, None, engine.safety_policy)


def source_api():
    assert hasattr(Management, "collect_native_management_sources"), "owned current management source collector is missing"
    return Management.collect_native_management_sources


def source_options(case):
    return {"policy": case["policy"], "instrument_max_age_ms": 2000, "instrument_max_observation_span_ms": 2000,
        "order_max_age_ms": 2000, "order_max_observation_span_ms": 2000}


def management_case(case, monkeypatch, *, cold=False):
    state, record, contract = claimed_order(case, monkeypatch)
    apply_query(case, record)
    engine = CCCXTTradeEngine(case["db"], ccxt_conf=copy.deepcopy(case["trade"].ccxt_conf), trade_conf={},
        environ={"CHANPY_KILL_SWITCH": "YES"}, management_only=True, push_msg=False)
    monkeypatch.setattr(Management, "utc_now_ms", lambda: case["clock"]["now"], raising=False)
    monkeypatch.setattr(Management, "_monotonic_ns", lambda: 0, raising=False)
    if cold:
        old = case["client"]
        previous = old.session.request
        def transport(session, method, url, **kwargs):
            assert session is not old.session and method == "GET", "cold management only reads original sources"
            return previous(method, url, **kwargs)
        monkeypatch.setattr("requests.sessions.Session.request", transport)
    else:
        engine.exchange = case["client"]
    return engine, state, record, contract


@pytest.mark.parametrize("cold", [False, True])
def test_owned_current_sources_under_kill_use_original_sdk_reads_not_candidate_or_send_permission(single_case, monkeypatch, tmp_path, cold):
    observe = source_api()
    case = single_case
    engine, state, record, contract = management_case(case, monkeypatch, cold=cold)
    db, key = case["db"], case["key"]
    original, history = db.get_record(key), db.get_order_history(key)
    transition = Transition.read_native_order_transition(db, key)
    if cold:
        # Remove only this fixture's private config/candidate, never real paths.
        for value in (case["config"], case["trade"].safety_policy.strategy_receipt["path"]):
            path = Path(value).resolve()
            assert path.is_relative_to(tmp_path.resolve())
            path.unlink()
    calls, order_calls = len(case["http_calls"]), len(state["requests"])
    document = observe(engine, key, phase="open", **source_options(case))
    payload = document["payload"]
    assert document["schema"] == "chan-native-management-sources-v1" and document["payload_sha256"] == _sha(payload)
    assert payload["account_context"] == contract["account_context"]
    assert payload["identity"]["payload"]["local_remaining_quantity"] == "0.02"
    assert payload["order"]["order_id"] == "123456" and payload["order"]["filled"] == .02
    assert payload["native_quantity_verified"] is payload["operation_authorized"] is False
    assert [row[0] for row in state["requests"]][order_calls:] == ["GET"]
    source_names = {name for name, _ in case["http_calls"][calls:]}
    assert {"fapiPrivateV3GetAccount", "fapiPrivateV3GetPositionRisk", "fapiPrivateGetOpenOrders",
        "fapiPrivateGetOpenAlgoOrders", "fapiPublicGetPremiumIndex", "fapiPublicGetTickerBookTicker"} <= source_names
    assert len(payload["account"]["payload"]["markets"]) == 2
    assert len(payload["market"]["payload"]["observations"]) == 2
    assert payload["pending"]["payload"]["coverage"] == "observed_regular_and_algo_order_channels"
    assert db.get_record(key) == original and db.get_order_history(key) == history
    assert Transition.read_native_order_transition(db, key) == transition
    assert not db.db.conn.in_transaction
    if cold:
        assert engine.exchange is not case["client"] and type(engine.exchange) is type(case["client"])
    with pytest.raises(CChanException, match="管理专用"):
        engine.cancel_order(record["stock_code"], "123456")


def test_management_runtime_checks_actual_inherited_query_dispatch_before_any_native_read(store, monkeypatch):
    engine = CCCXTTradeEngine(store[0], ccxt_conf=configuration(), trade_conf={}, environ={}, management_only=True)
    calls = []
    monkeypatch.setattr(engine, "_query_persisted_order", lambda *a: calls.append("foreign query"))
    with pytest.raises(CChanException):
        Management._source_runtime(engine)
    assert calls == []


@pytest.mark.parametrize("damage", ["record", "request", "session", "source_endpoint"])
def test_instrument_callback_cannot_change_original_owner_before_the_next_order_get(single_case, monkeypatch, damage):
    case = single_case
    engine, state, _, _ = management_case(case, monkeypatch)
    previous = engine.exchange.session.request
    before = len(state["requests"])
    def changed(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        if urlsplit(url).path == "/fapi/v1/exchangeInfo":
            if damage == "record":
                case["db"].db.execute(f"UPDATE {case['db'].table} SET unwatch_reason='late source change' WHERE id=?", (case["key"],))
            elif damage == "request":
                engine.exchange.session.request = lambda *a, **k: previous(*a, **k)
            elif damage == "session":
                from requests import Session
                foreign = Session()
                foreign.request = lambda *a, **k: previous(*a, **k)
                engine.exchange.session = foreign
            else:
                native = engine.exchange.fapiPrivateV3GetAccount
                engine.exchange.fapiPrivateV3GetAccount = lambda p: native(p)
        return response
    monkeypatch.setattr(engine.exchange.session, "request", changed)
    with pytest.raises(CChanException):
        source_api()(engine, case["key"], phase="open", **source_options(case))
    assert len(state["requests"]) == before, "source callback drift must be rejected before the next original order GET"


def test_management_source_windows_are_explicit_typed_and_checked_before_any_io(single_case):
    case = single_case
    engine = CCCXTTradeEngine(case["db"], ccxt_conf=copy.deepcopy(case["trade"].ccxt_conf), trade_conf={},
        environ={}, management_only=True)
    calls, changes = len(case["http_calls"]), case["db"].db.conn.total_changes
    options = source_options(case)
    for field in options.keys()-{"policy"}:
        for invalid in (None, True, -1, "2000", 2.5, 2**63):
            with pytest.raises(CChanException):
                source_api()(engine, case["key"], phase="open", **(options | {field: invalid}))
    with pytest.raises(CChanException):
        source_api()(engine, case["key"], phase="open", **(options | {"policy": {}}))
    assert len(case["http_calls"]) == calls and case["db"].db.conn.total_changes == changes
    assert engine.exchange is None


def test_native_new_fill_must_use_original_report_consumer_not_a_management_quantity_guess(single_case, monkeypatch):
    case = single_case
    engine, state, _, _ = management_case(case, monkeypatch)
    original, history = case["db"].get_record(case["key"]), case["db"].get_order_history(case["key"])
    before = len(state["requests"])
    state["row"].update(executedQty=".03", cumQuote="3")
    with pytest.raises(CChanException):
        source_api()(engine, case["key"], phase="open", **source_options(case))
    assert [method for method, _ in state["requests"]][before:] == ["GET"]
    assert case["db"].get_record(case["key"]) == original and case["db"].get_order_history(case["key"]) == history


@pytest.mark.parametrize("late", ["instrument_age", "monotonic_total", "monotonic_instrument", "monotonic_order"])
def test_all_source_budgets_are_checked_at_final_use_not_just_immediate_collection(single_case, monkeypatch, late):
    case = single_case
    engine, state, _, _ = management_case(case, monkeypatch)
    previous, books = engine.exchange.session.request, []
    elapsed = [0]
    monkeypatch.setattr(Management, "_monotonic_ns", lambda: elapsed[0])
    def delayed(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        if urlsplit(url).path == "/fapi/v1/ticker/bookTicker":
            books.append(url)
            if len(books) == 2:
                if late == "instrument_age":
                    case["clock"]["now"] += 100
                elif late == "monotonic_total":
                    elapsed[0] += 2001_000_000
                else:
                    elapsed[0] += 1000_000_000
        return response
    monkeypatch.setattr(engine.exchange.session, "request", delayed)
    options = source_options(case)
    if late == "instrument_age":
        options["instrument_max_age_ms"] = 10
    elif late == "monotonic_instrument":
        options["instrument_max_age_ms"] = 100
    elif late == "monotonic_order":
        options["order_max_age_ms"] = 100
    original, history = case["db"].get_record(case["key"]), case["db"].get_order_history(case["key"])
    with pytest.raises(CChanException):
        source_api()(engine, case["key"], phase="open", **options)
    assert len(books) == 2 and all(method == "GET" for method, _ in state["requests"])
    assert case["db"].get_record(case["key"]) == original and case["db"].get_order_history(case["key"]) == history
