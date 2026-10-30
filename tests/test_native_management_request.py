"""Owned close request terms are not a send/CAS capability."""
from decimal import Decimal
import copy
import json
from urllib.parse import urlsplit

import pytest
import requests

from Common.ChanException import CChanException
from Trade import NativeManagement as Management
from Trade import NativeLastPrice as Last
from Trade.CCXTTradeEngine import CCCXTTradeEngine
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import single_case, capacity_case
from .test_native_management_role import configuration
from .test_native_management_interval import complete_management_case, unchanged_database
from .test_native_management_sources import source_options
from .test_native_monetary_engine import apply_query


def request_entry():
    assert hasattr(Management, "collect_native_management_close_request"), "owned original close-request binding is missing"
    return Management.collect_native_management_close_request


def request_options(case):
    return {**source_options(case), "last_max_age_ms": 2000, "last_max_observation_span_ms": 2000}


def terminal_case(case, monkeypatch, *, cold=False):
    engine, state, record, contract = complete_management_case(case, monkeypatch, cold=cold)
    assert case["trade"].cancel_order(record["stock_code"], "123456") is True
    apply_query(case, record)
    return engine, state, case["db"].get_record(case["key"]), contract


def assert_only_original_terminal_observation(case, before):
    """Original GET may append exactly its new verified terminal observation."""
    after = unchanged_database(case)
    assert after[0] == before[0] and after[2] == before[2]+1
    for record, old, new in zip(before[0], before[1], after[1]):
        if record["id"] != case["key"]:
            assert old == new
            continue
        assert {k: v for k, v in old.items() if k != "attempts"} == {k: v for k, v in new.items() if k != "attempts"}
        assert len(old["attempts"]) == len(new["attempts"]) == 1
        left, right = old["attempts"][0], new["attempts"][0]
        assert {k: v for k, v in left.items() if k != "events"} == {k: v for k, v in right.items() if k != "events"}
        assert right["events"][:-1] == left["events"]
        event = right["events"][-1]
        assert event["kind"] == "native_terminal_observation" and event["state"] == left["events"][-1]["state"]
        assert event["native_order_observation"]["payload"]["raw"]["orderId"] == 123456
    return after


@pytest.mark.parametrize("cold", [False, True])
def test_terminal_original_order_binds_downward_sdk_close_request_without_a_write_or_permission(single_case, monkeypatch, cold):
    collect = request_entry()
    case = single_case
    engine, state, record, original = terminal_case(case, monkeypatch, cold=cold)
    before, begin = unchanged_database(case), len(state["requests"])
    document = collect(engine, case["key"], .0199, 300, post_only=True, **request_options(case))
    payload = document["payload"]
    request = payload["close_request"]
    assert document["schema"] == "chan-native-management-sources-v4"
    assert request["requested_base_quantity"] == "0.0199" and request["quantity"] == "0.019"
    assert request["contract"]["execution"] == original["execution"]
    assert request["contract"]["account_context"] == original["account_context"]
    assert request["client_order_id"] == engine.make_client_order_id(record, "close")
    wire = request["sdk_request"]
    assert wire["symbol"] == "TESTUSDT" and wire["side"] == "SELL" and wire["positionSide"] == "BOTH"
    assert wire["quantity"] == "0.019" and wire["price"] == "300" and wire["type"] == "LIMIT"
    assert wire["timeInForce"] == "GTX" and wire["reduceOnly"] is True
    assert wire["newClientOrderId"] == request["client_order_id"]
    assert Decimal(request["quantity"]) <= Decimal(payload["quantity"]["payload"]["observed_available_base_quantity"])
    assert payload["native_quantity_verified"] is payload["operation_authorized"] is False
    observed = assert_only_original_terminal_observation(case, before)
    assert [method for method, _ in state["requests"]][begin:] == ["GET"]
    with pytest.raises(CChanException):
        engine.place_order(record["stock_code"], False, .019, 300, reduce_only=True,
            client_order_id=request["client_order_id"], position_side="BOTH", post_only=True)
    assert unchanged_database(case) == observed


def test_partial_original_open_cannot_bind_a_new_close_request_from_current_fill(single_case, monkeypatch):
    collect = request_entry()
    case = single_case
    engine, _, _, _ = complete_management_case(case, monkeypatch)
    before = unchanged_database(case)
    with pytest.raises(CChanException):
        collect(engine, case["key"], .01, 1000, **request_options(case))
    assert unchanged_database(case) == before


def last_price_300(engine, monkeypatch, *, age_ms=0):
    """Only the fake venue's raw Last changes; no collector/SDK override."""
    calls = []
    def changed(response, url):
        if urlsplit(url).path == "/fapi/v2/ticker/price":
            row = json.loads(response.content)
            row["price"] = "300"
            row["time"] -= age_ms
            response._content = json.dumps(row).encode()
            calls.append(url)
        return response
    if engine.exchange is None:
        previous = requests.sessions.Session.request
        def cold_transport(session, method, url, **kwargs):
            return changed(previous(session, method, url, **kwargs), url)
        monkeypatch.setattr("requests.sessions.Session.request", cold_transport)
    else:
        previous = engine.exchange.session.request
        def transport(method, url, **kwargs):
            return changed(previous(method, url, **kwargs), url)
        monkeypatch.setattr(engine.exchange.session, "request", transport)
    return calls


def test_market_reference_is_owned_last_v2_not_a_ticker_cache_or_caller_price(single_case, monkeypatch):
    case = single_case
    engine, _, _, _ = terminal_case(case, monkeypatch)
    calls = last_price_300(engine, monkeypatch)
    document = request_entry()(engine, case["key"], .0199, None, **request_options(case))
    request = document["payload"]["close_request"]
    assert len(calls) == 1 and request["contract"]["reference_price"] == "300"
    assert request["sdk_request"]["type"] == "MARKET"
    assert "price" not in request["sdk_request"] and "timeInForce" not in request["sdk_request"]
    assert request["last"]["schema"] == Last.SCHEMA and request["last"]["payload"]["requests"] == 1


def test_final_last_decoder_work_cannot_leave_other_source_monotonic_budgets_at_an_earlier_clock(single_case, monkeypatch):
    case = single_case
    engine, _, _, _ = terminal_case(case, monkeypatch)
    calls = last_price_300(engine, monkeypatch)
    reads, elapsed = [], [0]
    def last_tick():
        reads.append(1)
        # The original collector makes four reads; its final decoder makes
        # the next pair. Its own 2s window allows this 51ms, wallet does not.
        if len(reads) >= 6:
            elapsed[0] = 51_000_000
        return elapsed[0]
    monkeypatch.setattr(Management, "_monotonic_ns", lambda: elapsed[0])
    monkeypatch.setattr(Last, "_monotonic_ns", last_tick)
    options = copy.deepcopy(request_options(case))
    options["policy"]["max_age_ms"]["wallet"] = 50
    with pytest.raises(CChanException):
        request_entry()(engine, case["key"], .0199, None, **options)
    assert len(calls) == 1 and len(reads) >= 6


def test_native_last_transaction_age_is_rechecked_after_its_final_owner_work(single_case, monkeypatch):
    case = single_case
    engine, _, _, _ = terminal_case(case, monkeypatch)
    calls = last_price_300(engine, monkeypatch, age_ms=1950)
    reads, advanced = [], []
    def last_tick():
        reads.append(1)
        return 0
    def tail_clock():
        if len(reads) >= 6 and not advanced:
            advanced.append(1)
            case["clock"]["now"] += 60
        return case["clock"]["now"]
    monkeypatch.setattr(Last, "_monotonic_ns", last_tick)
    monkeypatch.setattr(Management, "utc_now_ms", tail_clock)
    with pytest.raises(CChanException):
        request_entry()(engine, case["key"], .0199, None, **request_options(case))
    assert len(calls) == 1 and advanced == [1]


@pytest.mark.parametrize("changes", [{"amount": True}, {"amount": 0}, {"amount": float("inf")}, {"amount": "0.01"},
    {"price": float("nan")}, {"price": -1}, {"post_only": 1}, {"price": None, "post_only": True},
    {"last_max_age_ms": True}, {"last_max_observation_span_ms": None}, {"last_max_age_ms": -1}])
def test_invalid_request_values_fail_before_sdk_initialization_or_database_reads(store, changes):
    engine = CCCXTTradeEngine(store[0], ccxt_conf=configuration(), trade_conf={}, environ={}, management_only=True)
    values = {"amount": .01, "price": 100, "post_only": False, "policy": {}, "instrument_max_age_ms": 2000,
        "instrument_max_observation_span_ms": 2000, "order_max_age_ms": 2000, "order_max_observation_span_ms": 2000,
        "last_max_age_ms": 2000, "last_max_observation_span_ms": 2000, **changes}
    before = store[0].db.conn.total_changes
    statements = []
    store[0].db.conn.set_trace_callback(statements.append)
    try:
        with pytest.raises(CChanException):
            request_entry()(engine, 1, **values)
    finally:
        store[0].db.conn.set_trace_callback(None)
    assert engine.exchange is None and store[0].db.conn.total_changes == before and statements == []


@pytest.mark.parametrize("kind,post_only", [("limit", False), ("limit", True), ("market", False)])
def test_cold_request_preserves_original_direction_and_leg_across_all_binance_modes(capacity_case, monkeypatch, kind, post_only):
    case = capacity_case
    engine, state, record, original = terminal_case(case, monkeypatch, cold=True)
    last_calls = last_price_300(engine, monkeypatch)
    before, begin, created = unchanged_database(case), len(state["requests"]), len(case["created"])
    document = request_entry()(engine, case["key"], .0199, None if kind == "market" else 300,
        post_only=post_only, **request_options(case))
    bound = document["payload"]["close_request"]
    wire, execution = bound["sdk_request"], bound["contract"]["execution"]
    assert execution == original["execution"] and bound["contract"]["account_context"] == original["account_context"]
    assert wire["side"] == ("SELL" if record["is_buy"] else "BUY") and wire["positionSide"] == record["position_side"]
    assert wire["quantity"] == "0.019" and wire["newClientOrderId"] == engine.make_client_order_id(record, "close")
    assert bound["next_close_attempt"] == 1 and bound["contract"]["reference_price"] == "300"
    assert wire["type"] == kind.upper()
    if execution["position_mode"] == "one_way":
        assert wire["reduceOnly"] is True
    else:
        assert "reduceOnly" not in wire and record["position_side"] in {"LONG", "SHORT"}
    if kind == "limit":
        assert wire["timeInForce"] == ("GTX" if post_only else "GTC") and last_calls == []
    else:
        assert len(last_calls) == 1 and "timeInForce" not in wire and "price" not in wire
    assert_only_original_terminal_observation(case, before)
    assert len(case["created"]) == created and [method for method, _ in state["requests"]][begin:] == ["GET"]
    assert document["payload"]["operation_authorized"] is bound["operation_authorized"] is False


@pytest.mark.parametrize("amount,price", [(.02001, 300), (.00001, 100000), (.01, 100)])
def test_original_available_quantity_round_to_zero_and_min_notional_are_not_relaxed(single_case, monkeypatch, amount, price):
    case = single_case
    engine, _, _, _ = terminal_case(case, monkeypatch)
    before, created = unchanged_database(case), len(case["created"])
    with pytest.raises(CChanException):
        request_entry()(engine, case["key"], amount, price, **request_options(case))
    assert_only_original_terminal_observation(case, before)
    assert len(case["created"]) == created


def test_request_selects_the_actual_existing_close_attempt_and_never_overlaps_it(single_case, monkeypatch):
    case = single_case
    engine, state, _, _ = complete_management_case(case, monkeypatch, phase="close")
    before, begin = unchanged_database(case), len(state["requests"])
    with pytest.raises(CChanException):
        request_entry()(engine, case["key"], .01, 1000, **request_options(case))
    assert unchanged_database(case) == before
    assert state["requested_native_order_id"] == "789123" and [method for method, _ in state["requests"]][begin:] == ["GET"]


@pytest.mark.parametrize("target", ["sdk_builder", "terms", "client_id"])
def test_last_http_callback_cannot_replace_the_next_actual_request_callable(single_case, monkeypatch, target):
    case = single_case
    engine, _, _, _ = terminal_case(case, monkeypatch)
    last_price_300(engine, monkeypatch)
    previous, invoked, touched = engine.exchange.session.request, [], []
    def foreign(*args, **kwargs):
        invoked.append(1)
        raise AssertionError("foreign request callable must not run")
    def changed(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        if urlsplit(url).path == "/fapi/v2/ticker/price":
            touched.append(1)
            if target == "sdk_builder":
                monkeypatch.setattr(engine.exchange, "create_order_request", foreign)
            elif target == "terms":
                monkeypatch.setattr("Trade.CCXTTradeEngine._quantized_order_terms", foreign)
            else:
                monkeypatch.setattr(engine, "make_client_order_id", foreign)
        return response
    monkeypatch.setattr(engine.exchange.session, "request", changed)
    before, created = unchanged_database(case), len(case["created"])
    with pytest.raises(CChanException):
        request_entry()(engine, case["key"], .0199, None, **request_options(case))
    assert touched == [1] and invoked == [] and len(case["created"]) == created
    assert_only_original_terminal_observation(case, before)


@pytest.mark.parametrize("target", ["Trade.NativeLastPrice.collect_binance_last_prices", "Trade.NativeLastPrice.verify_binance_last_prices",
    "Trade.NativeLastPrice._windows", "Trade.NativeLastPrice._sdk", "Trade.NativeLastPrice._exact_response", "Trade.NativeLastPrice._budget",
    "Trade.CCXTTradeEngine._quantized_order_terms", "Trade.NativeManagement._build_native_management_close_request",
    "Trade.TradeEngine.CTradeEngine.make_client_order_id"])
def test_request_runtime_pins_actual_new_dependencies_before_io(store, monkeypatch, target):
    engine = CCCXTTradeEngine(store[0], ccxt_conf=configuration(), trade_conf={}, environ={}, management_only=True)
    invoked = []
    def foreign(*args, **kwargs):
        invoked.append(1)
        raise AssertionError("foreign dependency must not execute")
    monkeypatch.setattr(target, foreign)
    with pytest.raises(CChanException):
        Management._source_runtime(engine, include_interval=True, include_close=True)
    assert engine.exchange is None and invoked == []


@pytest.mark.parametrize("name", ["_https", "_raw", "_number", "_string", "_sha", "_original_method"])
def test_remaining_last_import_aliases_are_pinned_before_initialization(store, monkeypatch, name):
    engine = CCCXTTradeEngine(store[0], ccxt_conf=configuration(), trade_conf={}, environ={}, management_only=True)
    invoked = []
    def foreign(*args, **kwargs):
        invoked.append(1)
        raise AssertionError("foreign Last alias must not execute")
    monkeypatch.setattr(Last, name, foreign)
    with pytest.raises(CChanException):
        Management._source_runtime(engine, include_interval=True, include_close=True)
    assert engine.exchange is None and invoked == []


@pytest.mark.parametrize("interval,close", [(False, True), (True, 1), (1, False)])
def test_request_runtime_flags_are_exact_booleans_and_require_the_full_interval(store, interval, close):
    engine = CCCXTTradeEngine(store[0], ccxt_conf=configuration(), trade_conf={}, environ={}, management_only=True)
    with pytest.raises(CChanException):
        Management._source_runtime(engine, include_interval=interval, include_close=close)
    assert engine.exchange is None
