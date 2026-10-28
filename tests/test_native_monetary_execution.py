"""WIP original Engine end-to-end matrix; preserve all trading safety gates.

This is not a passing claim-only acceptance test and must not be hidden behind
xfail, caller permits or a fabricated successful L2 while the chain is WIP.
Only the bottom transport is fake; the original default Engine must own it all.
"""
import copy
import inspect
import json
import threading
import time
import traceback
import types
from contextlib import closing
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import requests
import pytest
from requests import Response

from Common.ChanException import CChanException, ErrCode
from Trade.db_util import CChanDB
from Trade import NativeOrderTransition as Transition
from Trade import NativePreparedIntent as Prepared
from Trade.NativeAccountReconcile import observe_native_account_components
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import capacity_case, single_case
from .test_native_monetary_prepared_intent import acquire
from .test_native_prepared_last import install_last
from .test_native_pending_orders import regular_row
from .test_native_monetary_engine import install_recovery_transport
from .test_native_monetary_consumers import component_sources
from .test_native_monetary_terminal_observation import set_native_filled_account


_ORIGINAL_REQUESTS_REQUEST = requests.Session.request


def install_order_transport(case, monkeypatch):
    if "create_order" in case["client"].__dict__:
        monkeypatch.delattr(case["client"], "create_order")
    previous, posts = case["client"].session.request, []
    def transport(method, url, **kwargs):
        if method == "GET":
            return previous(method, url, **kwargs)
        parsed = urlsplit(url)
        assert method == "POST" and parsed.hostname == "fapi.binance.com" and parsed.path == "/fapi/v1/order"
        assert kwargs["verify"] is True and not case["db"].db.conn.in_transaction
        body = kwargs.get("data", "")
        if isinstance(body, bytes):
            body = body.decode()
        params = {key: values[0] for key, values in parse_qs(body).items()}
        assert {"symbol", "side", "type", "quantity", "newClientOrderId", "timestamp", "signature"} <= set(params)
        posts.append(copy.deepcopy(params))
        row = regular_row("binance", params["symbol"], 123456)
        row.update(clientOrderId=params["newClientOrderId"], side=params["side"], origQty=params["quantity"], executedQty="0",
            type=params["type"], origType=params["type"], price=params.get("price", "0"),
            positionSide=params.get("positionSide", "BOTH"), timeInForce=params.get("timeInForce", "GTC"),
            reduceOnly=False, avgPrice="0", status="NEW", time=case["clock"]["now"], updateTime=case["clock"]["now"])
        response = Response()
        response.status_code, response.reason, response.url = 200, "OK", url
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(row).encode()
        return response
    monkeypatch.setattr(case["client"].session, "request", transport)
    return posts


def prepare_for_engine(case, monkeypatch, *, price=100, post_only=False):
    """Reuse the matrix's explicit fake budget, never construct a claim/L2."""
    install_last(case, monkeypatch)
    posts = install_order_transport(case, monkeypatch)
    policy = copy.deepcopy(case["policy"])
    for field in ("max_age_ms", "max_observation_span_ms"):
        policy[field] = {role: 60000 for role in policy[field]}  # Explicit fake budget, not a production default.
    assert acquire(case, price=price, post_only=post_only, policy=policy,
        instrument_max_age_ms=60000, instrument_max_observation_span_ms=60000,
        capacity_max_age_ms=60000, capacity_max_observation_span_ms=60000,
        last_max_age_ms=60000, last_max_observation_span_ms=60000)
    return posts


@pytest.mark.parametrize("kind,post_only", [("limit", False), ("market", False), ("limit", True)])
def test_original_engine_claims_the_same_monetary_intent_before_one_sdk_post(capacity_case, monkeypatch, kind, post_only):
    case = capacity_case
    price = None if kind == "market" else 100
    posts = prepare_for_engine(case, monkeypatch, price=price, post_only=post_only)
    before = case["db"].get_record(case["key"])
    intent = Transition.read_native_order_transition(case["db"], case["key"])
    result = case["trade"].place_order(before["stock_code"], bool(before["is_buy"]), .1, price,
        client_order_id=before["open_client_order_id"], position_side=before["position_side"], post_only=post_only)
    claim = Transition.read_native_order_transition(case["db"], case["key"])
    assert claim["payload"]["stage"] == "claim" and claim["payload"]["root"] == intent["payload"]["root"]
    assert claim["payload"]["binding_sha256"] == intent["payload"]["binding_sha256"]
    assert claim["payload"]["journal_prefix"]["event_count"] == intent["payload"]["journal_prefix"]["event_count"]+1
    history = case["db"].get_order_history(case["key"])
    assert [event["kind"] for event in history["attempts"][0]["events"]][:2] == ["intent", "claim"]
    assert result.order_id == "123456" and result.requested == .1 and result.filled == 0 and result.status == "open"
    assert len(posts) == 1 and posts[0]["newClientOrderId"] == before["open_client_order_id"]
    assert posts[0]["quantity"] == ".1" or posts[0]["quantity"] == "0.1"
    assert posts[0]["side"] == ("BUY" if before["is_buy"] else "SELL")
    assert posts[0]["type"] == kind.upper()
    assert posts[0]["positionSide"] == before["position_side"]
    assert posts[0].get("timeInForce") == (None if kind == "market" else "GTX" if post_only else "GTC")
    after = case["db"].get_record(case["key"])
    assert after["open_attempt"] == 1 and after["open_order_id"] == "123456" and after["open_order_status"] == "submitting"


def test_accepted_post_response_loss_keeps_claim_and_recovers_without_resubmission(single_case, monkeypatch):
    case = single_case
    posts = prepare_for_engine(case, monkeypatch)
    transport = case["client"].session.request
    accepted, lookups = {}, []
    def interrupted(method, url, **kwargs):
        target = urlsplit(url)
        if method == "GET" and target.path == "/fapi/v1/order":
            params = {key: values[0] for key, values in parse_qs(target.query).items()}
            assert params["origClientOrderId"] == accepted["row"]["clientOrderId"]
            assert kwargs["verify"] is True and not case["db"].db.conn.in_transaction
            lookups.append(params)
            response = Response()
            response.status_code, response.reason, response.url = 200, "OK", url
            response.headers["Content-Type"] = "application/json"
            response._content = json.dumps(accepted["row"]).encode()
            return response
        response = transport(method, url, **kwargs)
        if method == "POST":
            accepted["row"] = response.json()
            raise requests.exceptions.Timeout("synthetic accepted response was lost")
        return response
    monkeypatch.setattr(case["client"].session, "request", interrupted)
    monkeypatch.setattr("Trade.CCXTTradeEngine.utc_now_ms", lambda: case["clock"]["now"])
    before = case["db"].get_record(case["key"])
    args = (before["stock_code"], bool(before["is_buy"]), .1, 100)
    options = {"client_order_id": before["open_client_order_id"], "position_side": before["position_side"]}
    with pytest.raises(CChanException) as caught:
        case["trade"].place_order(*args, **options)
    assert caught.value.errcode == ErrCode.PLACE_ORDER_FAIL and len(posts) == 1
    pending = case["db"].get_record(case["key"])
    assert pending["open_order_status"] == "submitting" and pending["open_order_id"] is None
    assert pending["open_attempt"] == 1 and pending["current_qty"] == 0
    assert [event["kind"] for event in case["db"].get_order_history(case["key"])["attempts"][0]["events"]] == ["intent", "claim"]
    with pytest.raises(CChanException):
        case["trade"].place_order(*args, **options)
    result = case["trade"].query_order(before["stock_code"], client_order_id=before["open_client_order_id"])
    assert result.order_id == "123456" and result.filled == 0 and len(lookups) == 1 and len(posts) == 1
    after = case["db"].get_record(case["key"])
    assert after["open_order_id"] == "123456" and after["open_attempt"] == 1
    assert Transition.read_native_order_transition(case["db"], case["key"])["payload"]["stage"] == "claim"


def test_post_callback_cannot_redirect_ack_or_query_to_a_foreign_database(single_case, monkeypatch, tmp_path):
    case = single_case
    posts = prepare_for_engine(case, monkeypatch)
    transport, chan = case["client"].session.request, case["db"]
    before = chan.get_record(case["key"])
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"foreign-after-post.db")})) as foreign:
        statements = []
        foreign.db.conn.set_trace_callback(statements.append)
        def changed(method, url, **kwargs):
            response = transport(method, url, **kwargs)
            if method == "POST":
                case["trade"].chan_db = foreign
            return response
        monkeypatch.setattr(case["client"].session, "request", changed)
        try:
            with pytest.raises(CChanException):
                case["trade"].place_order(before["stock_code"], bool(before["is_buy"]), .1, 100,
                    client_order_id=before["open_client_order_id"], position_side=before["position_side"])
        finally:
            case["trade"].chan_db = chan
        assert statements == [] and len(posts) == 1
    pending = chan.get_record(case["key"])
    assert pending["open_order_status"] == "submitting" and pending["open_order_id"] is None
    assert [event["kind"] for event in chan.get_order_history(case["key"])["attempts"][0]["events"]] == ["intent", "claim"]


@pytest.mark.parametrize("replacement", ["engine_database", "connection"])
def test_intent_lookup_cannot_redirect_public_native_send_to_foreign_sql(single_case, monkeypatch, tmp_path, replacement):
    case = single_case
    posts = prepare_for_engine(case, monkeypatch)
    chan, database = case["db"], case["db"].db
    connection, original = database.conn, chan.get_order_intent
    before = chan.get_record(case["key"])
    history = chan.get_order_history(case["key"])
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"foreign-intent-lookup.db")})) as foreign:
        statements, touched = [], []
        foreign.db.conn.set_trace_callback(statements.append)
        def changed(*args, **kwargs):
            intent = original(*args, **kwargs)
            if not touched:
                touched.append(True)
                if replacement == "engine_database":
                    case["trade"].chan_db = foreign
                else:
                    database.conn = foreign.db.conn
            return intent
        monkeypatch.setattr(chan, "get_order_intent", changed)
        try:
            with pytest.raises(CChanException):
                case["trade"].place_order(before["stock_code"], bool(before["is_buy"]), .1, 100,
                    client_order_id=before["open_client_order_id"], position_side=before["position_side"])
        finally:
            case["trade"].chan_db, database.conn = chan, connection
        assert touched and statements == [] and posts == []
    assert chan.get_record(case["key"]) == before and chan.get_order_history(case["key"]) == history


def test_preclaim_mode_response_cannot_switch_credentials_before_the_next_get(single_case, monkeypatch):
    case = single_case
    posts = prepare_for_engine(case, monkeypatch)
    transport, client = case["client"].session.request, case["client"]
    before = case["db"].get_record(case["key"])
    history = case["db"].get_order_history(case["key"])
    touched, late = [], []
    def changed(method, url, **kwargs):
        path = urlsplit(url).path
        if touched:
            late.append((method, path))
        response = transport(method, url, **kwargs)
        if method == "GET" and path == "/fapi/v1/positionSide/dual" and not touched:
            touched.append(True)
            client.apiKey = "changed-fake-key"
        return response
    monkeypatch.setattr(client.session, "request", changed)
    try:
        with pytest.raises(CChanException):
            case["trade"].place_order(before["stock_code"], bool(before["is_buy"]), .1, 100,
                client_order_id=before["open_client_order_id"], position_side=before["position_side"])
    finally:
        client.apiKey = "key"
    assert touched and late == [] and posts == []
    assert case["db"].get_record(case["key"]) == before and case["db"].get_order_history(case["key"]) == history


def test_native_post_error_redacts_private_sdk_body_without_releasing_or_retrying_claim(single_case, monkeypatch):
    case = single_case
    posts = prepare_for_engine(case, monkeypatch)
    transport = case["client"].session.request
    def failed(method, url, **kwargs):
        response = transport(method, url, **kwargs)
        if method == "POST":
            response.status_code, response.reason = 400, "Bad Request"
            response._content = json.dumps({"code": -2010, "msg": "PRIVATE_ORDER_BODY synthetic-account-secret"}).encode()
        return response
    monkeypatch.setattr(case["client"].session, "request", failed)
    before = case["db"].get_record(case["key"])
    args = (before["stock_code"], bool(before["is_buy"]), .1, 100)
    options = {"client_order_id": before["open_client_order_id"], "position_side": before["position_side"]}
    with pytest.raises(CChanException) as caught:
        case["trade"].place_order(*args, **options)
    assert caught.value.errcode == ErrCode.PLACE_ORDER_FAIL and len(posts) == 1
    assert "PRIVATE_ORDER_BODY" not in str(caught.value)
    assert "PRIVATE_ORDER_BODY" not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    pending = case["db"].get_record(case["key"])
    assert pending["open_order_status"] == "submitting" and pending["open_order_id"] is None
    assert pending["open_attempt"] == 1 and pending["current_qty"] == 0
    with pytest.raises(CChanException):
        case["trade"].place_order(*args, **options)
    assert len(posts) == 1


def test_sdk_order_retry_setting_cannot_repeat_an_accepted_but_lost_post(single_case, monkeypatch):
    case = single_case
    case["client"].options["order"] = {"maxRetriesOnFailure": 1}
    posts = None
    with pytest.raises(CChanException) as caught:
        # An unsafe setup may be refused before any source. If preparation
        # succeeds, the original SDK must still never repeat the unknown POST.
        posts = prepare_for_engine(case, monkeypatch)
        transport = case["client"].session.request
        def lost(method, url, **kwargs):
            response = transport(method, url, **kwargs)
            if method == "POST":
                raise requests.exceptions.Timeout("synthetic accepted response was lost")
            return response
        monkeypatch.setattr(case["client"].session, "request", lost)
        record = case["db"].get_record(case["key"])
        case["trade"].place_order(record["stock_code"], bool(record["is_buy"]), .1, 100,
            client_order_id=record["open_client_order_id"], position_side=record["position_side"])
    current = case["db"].get_record(case["key"])
    if posts is None:
        assert caught.value.errcode == ErrCode.TRADE_UNLOCK_FAIL
        assert not case["http_calls"] and current["open_attempt"] == 0
    else:
        assert caught.value.errcode == ErrCode.PLACE_ORDER_FAIL
        assert len(posts) == 1, "the real SDK repeated an accepted unknown POST inside a single Engine call"
        assert current["open_attempt"] == 1 and current["open_order_status"] == "submitting"
    assert current["open_order_id"] is None and current["current_qty"] == 0


@pytest.mark.parametrize("advance_utc", [True, False])
def test_original_sdk_wait_cannot_send_after_the_original_source_window_expires(single_case, monkeypatch, advance_utc):
    case = single_case
    delayed, elapsed_ns = [], [0]
    original_tick = Prepared._monotonic_ns
    def tick():
        return original_tick()+elapsed_ns[0]
    def simulated_sleep(seconds):
        caller = inspect.currentframe().f_back
        assert caller.f_code.co_name == "throttle"
        request = caller.f_back
        assert request.f_code.co_name == "fetch2"
        if request.f_locals["path"] == "order" and request.f_locals["method"] == "POST":
            assert seconds > 0
            delayed.append(seconds)
            # Simulate scheduler suspension inside the original SDK, not a
            # real sleep or a renewal of any original native observation.
            tick_before = Prepared._monotonic_ns()
            elapsed_ns[0] += 61000*1_000_000
            assert Prepared._monotonic_ns()-tick_before >= 61000*1_000_000
            if advance_utc:
                case["clock"]["now"] += 61000
    monkeypatch.setattr(time, "sleep", simulated_sleep)
    case["client"].enableRateLimit, case["client"].rateLimit = True, 10000
    posts = prepare_for_engine(case, monkeypatch)
    # install_last inside preparation pins this clock for its own fixture;
    # inject the SDK suspension only after that setup has finished.
    monkeypatch.setattr(Prepared, "_monotonic_ns", tick)
    before = case["db"].get_record(case["key"])
    failure = None
    try:
        case["trade"].place_order(before["stock_code"], bool(before["is_buy"]), .1, 100,
            client_order_id=before["open_client_order_id"], position_side=before["position_side"])
    except CChanException as error:
        failure = error
    assert delayed, "the original SDK POST throttle must actually reach the injected wait"
    assert posts == [], "a POST crossed the original 60000ms source budget after the SDK waited 61000ms"
    assert failure is not None and failure.errcode == ErrCode.TRADE_UNLOCK_FAIL
    current = case["db"].get_record(case["key"])
    assert current["open_order_status"] == "submitting" and current["open_order_id"] is None
    assert current["open_attempt"] == 1 and current["current_qty"] == 0
    assert [event["kind"] for event in case["db"].get_order_history(case["key"])["attempts"][0]["events"]] == ["intent", "claim"]


def submit_for_recovery(case, monkeypatch, *, price=100, post_only=False):
    posts = prepare_for_engine(case, monkeypatch, price=price, post_only=post_only)
    transport, actual_response = case["client"].session.request, {}
    def capture_post(method, url, **kwargs):
        response = transport(method, url, **kwargs)
        if method == "POST":
            actual_response["row"] = response.json()
        return response
    monkeypatch.setattr(case["client"].session, "request", capture_post)
    record = case["db"].get_record(case["key"])
    placed = case["trade"].place_order(record["stock_code"], bool(record["is_buy"]), .1, price,
        client_order_id=record["open_client_order_id"], position_side=record["position_side"], post_only=post_only)
    assert len(posts) == 1 and placed.order_id == "123456" and placed.filled == 0
    claim = Transition.read_native_order_transition(case["db"], case["key"])
    assert claim["payload"]["stage"] == "claim"
    state = install_recovery_transport(case, monkeypatch)
    state["row"] = copy.deepcopy(actual_response["row"])
    return posts, state, record, placed, claim


@pytest.mark.parametrize("kind,post_only", [("limit", False), ("market", False), ("limit", True)])
def test_actual_post_partial_cancel_native_account_and_cold_restart_form_one_chain(capacity_case, monkeypatch, store, kind, post_only):
    case = capacity_case
    price = None if kind == "market" else 100
    posts, state, record, placed, claim = submit_for_recovery(case, monkeypatch, price=price, post_only=post_only)
    assert posts[0]["type"] == kind.upper()
    assert posts[0].get("timeInForce") == (None if kind == "market" else "GTX" if post_only else "GTC")
    set_native_filled_account(case, monkeypatch, state, record, native_status="PARTIALLY_FILLED", maker=post_only)
    raw_fill = case["execution_io"][case["units"][0]["id"]].rows[-1]
    assert raw_fill["maker"] is post_only
    assert Decimal(raw_fill["commission"]) == Decimal("0.0004" if post_only else "0.0008")
    partial = case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert partial.filled == .02 and partial.status == "open"
    case["db"].apply_open_fill(case["key"], partial.filled, partial.avg_price, partial.status,
        client_order_id=partial.client_order_id, order_id=partial.order_id, expected_attempt=1)
    assert case["db"].get_record(case["key"])["current_qty"] == .02
    assert case["trade"].cancel_order(record["stock_code"], placed.order_id) is True
    assert not [event for event in case["db"].get_order_history(case["key"])["attempts"][0]["events"]
                if event["kind"] == "native_terminal_observation"], "DELETE must not substitute for the terminal GET source"
    terminal = case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert terminal.status == "canceled" and terminal.filled == .02
    case["db"].apply_open_fill(case["key"], terminal.filled, terminal.avg_price, terminal.status,
        client_order_id=terminal.client_order_id, order_id=terminal.order_id, expected_attempt=1)
    params, request = component_sources(case)
    report = observe_native_account_components(case["db"], **params)
    assert report["payload"]["status"] == "matched_components", report["payload"]["issues"]
    check = case["db"].reconcile_native_account(**request)
    assert check["payload"]["report"]["payload"]["status"] == "matched_observations"
    assert not [row for row in report["payload"]["pending"]["payload"]["reservations"]
                if row["attempt"]["record_id"] == case["key"]]
    assert len(report["payload"]["pending"]["payload"]["terminal_observations"]) == 1
    assert [method for method, _ in state["requests"]] == ["GET", "DELETE", "GET"]
    original_db, old_client, trade = case["db"], case["client"], case["trade"]
    previous, cold_requests = old_client.session.request, []
    def cold_transport(session, method, url, **kwargs):
        assert session is not old_client.session and method == "GET"
        assert not trade.chan_db.db.conn.in_transaction
        cold_requests.append(urlsplit(url).path)
        return previous(method, url, **kwargs)
    monkeypatch.setattr("requests.sessions.Session.request", cold_transport)
    with closing(CChanDB(db_conf=store[1])) as restarted:
        try:
            trade.chan_db, case["db"], trade.exchange = restarted, restarted, None
            case["clock"]["now"] += 3600_000
            trade.safety_policy.environ["CHANPY_KILL_SWITCH"] = "YES"
            cold = trade.query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
            assert cold.status == "canceled" and cold.filled == .02 and cold.order_id == placed.order_id
            assert type(trade.exchange) is type(old_client) and trade.exchange is not old_client
            case["client"] = trade.exchange
            before_duplicate = restarted.get_record(case["key"])
            restarted.apply_open_fill(case["key"], cold.filled, cold.avg_price, cold.status,
                client_order_id=cold.client_order_id, order_id=cold.order_id, expected_attempt=1)
            assert restarted.get_record(case["key"]) == before_duplicate
            _, cold_request = component_sources(case)
            cold_check = restarted.reconcile_native_account(**cold_request)
            assert cold_check["payload"]["report"]["payload"]["status"] == "matched_observations"
            assert restarted.get_account_risk_state(cold_request["account_context"])["frozen"] is False
            assert trade.safety_policy.environ["CHANPY_KILL_SWITCH"] == "YES"
            assert restarted.get_record(case["key"])["current_qty"] == .02
            assert Transition.read_native_order_transition(restarted, case["key"]) == claim
        finally:
            trade.chan_db, case["db"], case["client"], trade.exchange = original_db, original_db, old_client, old_client
    assert cold_requests and "/fapi/v1/exchangeInfo" in cold_requests and len(posts) == 1
    assert original_db.get_record(case["key"])["open_attempt"] == 1


def test_actual_native_cancel_error_keeps_unknown_state_without_private_body_or_resubmission(single_case, monkeypatch):
    case = single_case
    posts, state, record, placed, claim = submit_for_recovery(case, monkeypatch)
    before, history = case["db"].get_record(case["key"]), case["db"].get_order_history(case["key"])
    previous = case["client"].session.request
    def ambiguous_cancel(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        if method == "DELETE":
            response.status_code, response.reason = 400, "Bad Request"
            response._content = json.dumps({"code": -1000, "msg": "PRIVATE_NATIVE_CANCEL_RESPONSE_BODY"}).encode()
        return response
    monkeypatch.setattr(case["client"].session, "request", ambiguous_cancel)
    with pytest.raises(CChanException) as error:
        case["trade"].cancel_order(record["stock_code"], placed.order_id)
    assert error.value.errcode == ErrCode.CANDEL_ORDER_FAIL
    assert "PRIVATE_NATIVE_CANCEL_RESPONSE_BODY" not in str(error.value)
    assert "PRIVATE_NATIVE_CANCEL_RESPONSE_BODY" not in "".join(traceback.format_exception(error.value))
    assert error.value.__cause__ is None
    assert case["db"].get_record(case["key"]) == before and case["db"].get_order_history(case["key"]) == history
    assert Transition.read_native_order_transition(case["db"], case["key"]) == claim and len(posts) == 1
    confirmed = case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert confirmed.status == "canceled" and confirmed.filled == 0
    assert [method for method, _ in state["requests"]] == ["DELETE", "GET"] and len(posts) == 1


@pytest.mark.parametrize("had_override", [True, False])
@pytest.mark.parametrize("response_lost", [False, True])
def test_request_override_is_restored_after_the_actual_sdk_invocation(single_case, monkeypatch, had_override, response_lost):
    case = single_case
    posts = prepare_for_engine(case, monkeypatch)
    session, delegate = case["client"].session, case["client"].session.request
    def response(method, url, **kwargs):
        value = delegate(method, url, **kwargs)
        if response_lost and method == "POST":
            raise requests.exceptions.Timeout("synthetic accepted response was lost")
        return value
    if had_override:
        monkeypatch.setattr(session, "request", response)
    else:
        def class_request(actual, method, url, **kwargs):
            assert actual is session
            return response(method, url, **kwargs)
        monkeypatch.setattr(requests.Session, "request", class_request)
        monkeypatch.delattr(session, "request")
    record = case["db"].get_record(case["key"])
    args = (record["stock_code"], bool(record["is_buy"]), .1, 100)
    options = {"client_order_id": record["open_client_order_id"], "position_side": record["position_side"]}
    if response_lost:
        with pytest.raises(CChanException) as error:
            case["trade"].place_order(*args, **options)
        assert error.value.errcode == ErrCode.PLACE_ORDER_FAIL
    else:
        assert case["trade"].place_order(*args, **options).order_id == "123456"
    assert len(posts) == 1 and ("request" in session.__dict__) is had_override
    if had_override:
        assert session.request is response
    else:
        assert session.request.__self__ is session and session.request.__func__ is class_request
    current = case["db"].get_record(case["key"])
    assert current["open_attempt"] == 1 and current["current_qty"] == 0
    assert current["open_order_id"] == (None if response_lost else "123456")


def test_transport_cleanup_does_not_overwrite_an_external_request_replacement(single_case, monkeypatch):
    case = single_case
    posts = prepare_for_engine(case, monkeypatch)
    session, delegate, foreign_calls = case["client"].session, case["client"].session.request, []
    def foreign(*args, **kwargs):
        foreign_calls.append(True)
        raise RuntimeError("the external replacement must not execute")
    def changed(method, url, **kwargs):
        response = delegate(method, url, **kwargs)
        if method == "POST":
            session.request = foreign
        return response
    monkeypatch.setattr(session, "request", changed)
    record = case["db"].get_record(case["key"])
    try:
        with pytest.raises(CChanException):
            case["trade"].place_order(record["stock_code"], bool(record["is_buy"]), .1, 100,
                client_order_id=record["open_client_order_id"], position_side=record["position_side"])
        assert session.request is foreign and foreign_calls == [] and len(posts) == 1
    finally:
        session.request = changed
    current = case["db"].get_record(case["key"])
    assert current["open_order_status"] == "submitting" and current["open_order_id"] is None


@pytest.mark.parametrize("replacement", ["session", "request"])
def test_sdk_wait_transport_replacement_is_rejected_before_foreign_request(single_case, monkeypatch, replacement):
    case = single_case
    original_session, touched, foreign_calls = case["client"].session, [], []
    with requests.Session() as foreign:
        def unsafe(*args, **kwargs):
            foreign_calls.append(True)
            raise RuntimeError("a foreign transport must not execute")
        monkeypatch.setattr(foreign, "request", unsafe)
        def simulated_sleep(seconds):
            caller = inspect.currentframe().f_back
            assert caller.f_code.co_name == "throttle"
            request = caller.f_back
            assert request.f_code.co_name == "fetch2"
            if request.f_locals["path"] == "order" and request.f_locals["method"] == "POST":
                assert seconds > 0
                touched.append(replacement)
                if replacement == "session":
                    case["client"].session = foreign
                else:
                    original_session.request = unsafe
        monkeypatch.setattr(time, "sleep", simulated_sleep)
        case["client"].enableRateLimit, case["client"].rateLimit = True, 10000
        posts = prepare_for_engine(case, monkeypatch)
        delegate = original_session.request
        record = case["db"].get_record(case["key"])
        try:
            with pytest.raises(CChanException):
                case["trade"].place_order(record["stock_code"], bool(record["is_buy"]), .1, 100,
                    client_order_id=record["open_client_order_id"], position_side=record["position_side"])
        finally:
            case["client"].session, original_session.request = original_session, delegate
        assert touched == [replacement] and foreign_calls == [], "SDK wait reached an unowned request before rejection"
        assert posts == []
    current = case["db"].get_record(case["key"])
    assert current["open_attempt"] == 1 and current["open_order_status"] == "submitting"
    assert current["open_order_id"] is None and current["current_qty"] == 0


@pytest.mark.parametrize("preprocessor,is_callback", [
    (name, False) for name in ("prepare_request_headers", "set_headers", "check_proxy_url_settings",
        "check_proxy_settings", "check_conflicting_proxies", "value_is_defined")
]+[(name, True) for name in ("proxyUrlCallback", "proxy_url_callback", "httpProxyCallback", "http_proxy_callback",
    "httpsProxyCallback", "https_proxy_callback", "socksProxyCallback", "socks_proxy_callback", "proxy")])
def test_sdk_fetch_preprocessing_cannot_execute_an_unproven_session_switch(single_case, monkeypatch, preprocessor, is_callback):
    case = single_case
    client, session = case["client"], case["client"].session
    touched, invoked, foreign_calls = [], [], []
    with requests.Session() as foreign:
        def unsafe(*args, **kwargs):
            foreign_calls.append(True)
            raise RuntimeError("PRIVATE_FOREIGN_PREPROCESS_TRANSPORT")
        monkeypatch.setattr(foreign, "request", unsafe)
        original = None if is_callback else getattr(client, preprocessor)
        def changed(actual, *args, **kwargs):
            assert actual is client
            invoked.append(preprocessor)
            client.session = foreign
            return original(*args, **kwargs)
        def callback(*args, **kwargs):
            invoked.append(preprocessor)
            client.session = foreign
            return None
        def simulated_sleep(seconds):
            caller = inspect.currentframe().f_back
            assert caller.f_code.co_name == "throttle"
            request = caller.f_back
            assert request.f_code.co_name == "fetch2"
            if request.f_locals["path"] == "order" and request.f_locals["method"] == "POST":
                assert seconds > 0
                touched.append(preprocessor)
                monkeypatch.setattr(client, preprocessor, callback if is_callback else types.MethodType(changed, client))
        monkeypatch.setattr(time, "sleep", simulated_sleep)
        # Force the fake SDK suspension without changing original source clocks/budgets.
        client.enableRateLimit, client.rateLimit = True, 60000
        posts = prepare_for_engine(case, monkeypatch)
        record = case["db"].get_record(case["key"])
        try:
            with pytest.raises(CChanException):
                case["trade"].place_order(record["stock_code"], bool(record["is_buy"]), .1, 100,
                    client_order_id=record["open_client_order_id"], position_side=record["position_side"])
        finally:
            client.session = session
        assert touched == [preprocessor]
        assert invoked == [] and foreign_calls == [] and posts == [], (
            f"unproven preprocessors={invoked!r}; foreign_requests={foreign_calls!r}; original_posts={len(posts)}")
    current = case["db"].get_record(case["key"])
    assert current["open_attempt"] == 1 and current["open_order_status"] == "submitting" and current["open_order_id"] is None


@pytest.mark.parametrize("replacement", ["database", "connection", "chan", "table"])
def test_sdk_wait_database_owner_change_cannot_reach_any_sql(single_case, monkeypatch, tmp_path, replacement):
    case = single_case
    chan, backend = case["db"], case["db"].db
    connection, table = backend.conn, chan.table
    touched, original_sql = [], []
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"foreign-sdk-wait.db")})) as foreign:
        foreign_sql = []
        foreign.db.conn.set_trace_callback(foreign_sql.append)
        def simulated_sleep(seconds):
            caller = inspect.currentframe().f_back
            assert caller.f_code.co_name == "throttle"
            request = caller.f_back
            assert request.f_code.co_name == "fetch2"
            if request.f_locals["path"] == "order" and request.f_locals["method"] == "POST":
                assert seconds > 0
                touched.append(replacement)
                connection.set_trace_callback(original_sql.append)
                if replacement == "database":
                    chan.db = foreign.db
                elif replacement == "connection":
                    backend.conn = foreign.db.conn
                elif replacement == "chan":
                    case["trade"].chan_db = foreign
                else:
                    chan.table = "foreign_table_must_not_be_queried"
        monkeypatch.setattr(time, "sleep", simulated_sleep)
        case["client"].enableRateLimit, case["client"].rateLimit = True, 10000
        posts = prepare_for_engine(case, monkeypatch)
        record = chan.get_record(case["key"])
        try:
            with pytest.raises(CChanException):
                case["trade"].place_order(record["stock_code"], bool(record["is_buy"]), .1, 100,
                    client_order_id=record["open_client_order_id"], position_side=record["position_side"])
        finally:
            case["trade"].chan_db, chan.db, backend.conn, chan.table = chan, backend, connection, table
            connection.set_trace_callback(None)
        assert touched == [replacement] and original_sql == foreign_sql == [] and posts == []
    current = chan.get_record(case["key"])
    assert current["open_attempt"] == 1 and current["open_order_status"] == "submitting" and current["open_order_id"] is None
    assert [event["kind"] for event in chan.get_order_history(case["key"])["attempts"][0]["events"]] == ["intent", "claim"]
    assert chan.get_account_risk_state(case["before"]["payload"]["account_context"])["frozen"] is False


@pytest.mark.parametrize("target", ["current_claim", "owners", "source_failure"])
def test_sdk_wait_cannot_replace_the_live_fetch_claim_closure(single_case, monkeypatch, target):
    case = single_case
    session, touched, foreign_calls, bypassed = case["client"].session, [], [], []
    def unsafe(*args, **kwargs):
        foreign_calls.append(True)
        raise RuntimeError("PRIVATE_FOREIGN_TRANSPORT_MUST_NOT_EXECUTE")
    def bypass(*args, **kwargs):
        bypassed.append(target)
    def simulated_sleep(seconds):
        caller = inspect.currentframe().f_back
        assert caller.f_code.co_name == "throttle"
        request = caller.f_back
        assert request.f_code.co_name == "fetch2"
        if request.f_locals["path"] == "order" and request.f_locals["method"] == "POST":
            assert seconds > 0
            bridge = case["client"].fetch
            cells = dict(zip(bridge.__code__.co_freevars, bridge.__closure__))
            selected = cells["source_failure"] if target == "source_failure" else cells["current_claim"]
            if target == "owners":
                checker = selected.cell_contents
                selected = dict(zip(checker.__code__.co_freevars, checker.__closure__))["owners"]
            selected.cell_contents = bypass
            session.request = unsafe
            touched.append(target)
    monkeypatch.setattr(time, "sleep", simulated_sleep)
    case["client"].enableRateLimit, case["client"].rateLimit = True, 10000
    posts = prepare_for_engine(case, monkeypatch)
    delegate = session.request
    record = case["db"].get_record(case["key"])
    try:
        with pytest.raises(CChanException):
            case["trade"].place_order(record["stock_code"], bool(record["is_buy"]), .1, 100,
                client_order_id=record["open_client_order_id"], position_side=record["position_side"])
    finally:
        session.request = delegate
    assert touched == [target]
    assert bypassed == [] and foreign_calls == [] and posts == [], "a replaced live closure executed before rejection"
    current = case["db"].get_record(case["key"])
    assert current["open_attempt"] == 1 and current["open_order_status"] == "submitting"
    assert current["open_order_id"] is None and current["current_qty"] == 0
    assert "fetch" not in case["client"].__dict__


@pytest.mark.parametrize("had_override", [False, True])
@pytest.mark.parametrize("response_lost", [False, True])
def test_fetch_override_is_restored_and_the_finished_bridge_cannot_be_reused(single_case, monkeypatch, had_override, response_lost):
    case = single_case
    posts = prepare_for_engine(case, monkeypatch)
    client, original_fetch = case["client"], case["client"].fetch
    if had_override:
        client.fetch = original_fetch  # An actual original bound SDK method, not a substitute.
    delegate, bridges = client.session.request, []
    def response(method, url, **kwargs):
        value = delegate(method, url, **kwargs)
        if method == "POST":
            assert type(client.fetch) is types.FunctionType and client.fetch is not original_fetch
            Prepared.Prepare._assert_execution_sdk(client, case["trade"].mode)
            bridges.append(client.fetch)
            if response_lost:
                raise requests.exceptions.Timeout("synthetic accepted response was lost")
        return value
    monkeypatch.setattr(client.session, "request", response)
    record = case["db"].get_record(case["key"])
    args = (record["stock_code"], bool(record["is_buy"]), .1, 100)
    options = {"client_order_id": record["open_client_order_id"], "position_side": record["position_side"]}
    if response_lost:
        with pytest.raises(CChanException) as error:
            case["trade"].place_order(*args, **options)
        assert error.value.errcode == ErrCode.PLACE_ORDER_FAIL
    else:
        assert case["trade"].place_order(*args, **options).order_id == "123456"
    assert len(posts) == len(bridges) == 1 and ("fetch" in client.__dict__) is had_override
    assert client.fetch == original_fetch
    if had_override:
        assert client.fetch is original_fetch
    before_reuse = case["db"].db.conn.total_changes
    with pytest.raises(CChanException):
        bridges[0](client.urls["api"]["fapiPrivate"]+"/order", "POST", {}, "")
    assert case["db"].db.conn.total_changes == before_reuse
    assert len(posts) == 1 and case["db"].get_record(case["key"])["open_attempt"] == 1


@pytest.mark.parametrize("damage", ["clone", "clone_rebound", "defaults", "delegate", "original_code", "resolver"])
def test_sdk_wait_preserves_full_fetch_and_bridge_identity(single_case, monkeypatch, damage):
    case = single_case
    client, touched, invoked = case["client"], [], []
    def replaced(self, *args, **kwargs):
        self._fake_fetch_invocations.append(True)
        raise RuntimeError("PRIVATE_REPLACED_FETCH_MUST_NOT_EXECUTE")
    def resolver(*args, **kwargs):
        invoked.append(True)
        raise RuntimeError("PRIVATE_REPLACED_RESOLVER_MUST_NOT_EXECUTE")
    monkeypatch.setattr(client, "_fake_fetch_invocations", invoked, raising=False)
    def simulated_sleep(seconds):
        caller = inspect.currentframe().f_back
        assert caller.f_code.co_name == "throttle"
        request = caller.f_back
        assert request.f_code.co_name == "fetch2"
        if request.f_locals["path"] == "order" and request.f_locals["method"] == "POST":
            assert seconds > 0
            bridge = client.fetch
            cells = dict(zip(bridge.__code__.co_freevars, bridge.__closure__))
            if damage in {"clone", "clone_rebound"}:
                clone = types.FunctionType(bridge.__code__, bridge.__globals__, bridge.__name__, bridge.__defaults__, bridge.__closure__)
                clone.__qualname__, clone.__kwdefaults__ = bridge.__qualname__, bridge.__kwdefaults__
                if damage == "clone_rebound":
                    cells["fetch_guard"].cell_contents = clone
                client.fetch = clone
            elif damage == "defaults":
                monkeypatch.setattr(bridge, "__defaults__", ("POST", None, None))
            elif damage == "delegate":
                original = cells["fetch_delegate"].cell_contents
                cells["fetch_delegate"].cell_contents = types.MethodType(original.__func__, object())
            elif damage == "original_code":
                original = cells["fetch_delegate"].cell_contents
                monkeypatch.setattr(original.__func__, "__code__", replaced.__code__)
            else:
                monkeypatch.setattr(Prepared, "_native_http_fetch_delegate", resolver)
            touched.append(damage)
    monkeypatch.setattr(time, "sleep", simulated_sleep)
    client.enableRateLimit, client.rateLimit = True, 10000
    posts = prepare_for_engine(case, monkeypatch)
    record = case["db"].get_record(case["key"])
    try:
        with pytest.raises(CChanException):
            case["trade"].place_order(record["stock_code"], bool(record["is_buy"]), .1, 100,
                client_order_id=record["open_client_order_id"], position_side=record["position_side"])
        assert touched == [damage] and invoked == [] and posts == []
        if damage in {"clone", "clone_rebound"}:
            assert client.fetch.__closure__ is not None  # External replacement was not overwritten at cleanup.
        else:
            assert "fetch" not in client.__dict__
    finally:
        client.__dict__.pop("fetch", None)
    current = case["db"].get_record(case["key"])
    assert current["open_attempt"] == 1 and current["open_order_status"] == "submitting" and current["open_order_id"] is None


@pytest.mark.parametrize("attempt", ["repeat", "reentry", "other_thread"])
def test_live_fetch_bridge_reuse_has_no_transport_or_ledger_authority(single_case, monkeypatch, attempt):
    case = single_case
    posts = prepare_for_engine(case, monkeypatch)
    client, delegate, rejected, changes = case["client"], case["client"].session.request, [], []
    def attempted_reuse(method, url, kwargs):
        before = case["db"].db.conn.total_changes
        try:
            if attempt == "reentry":
                with Prepared._native_prepared_claim_http_use(case["trade"], case["key"]):
                    pytest.fail("fetch reentry acquired another original invocation")
            else:
                body = kwargs.get("data", b"")
                client.fetch(url, method, kwargs.get("headers"), body.decode() if type(body) is bytes else body)
        except CChanException:
            rejected.append(attempt)
        changes.append(case["db"].db.conn.total_changes-before)
    def response(method, url, **kwargs):
        value = delegate(method, url, **kwargs)
        if method == "POST":
            if attempt == "other_thread":
                worker = threading.Thread(target=attempted_reuse, args=(method, url, kwargs))
                worker.start()
                worker.join(timeout=5)
                assert not worker.is_alive()
            else:
                attempted_reuse(method, url, kwargs)
        return value
    monkeypatch.setattr(client.session, "request", response)
    record = case["db"].get_record(case["key"])
    result = case["trade"].place_order(record["stock_code"], bool(record["is_buy"]), .1, 100,
        client_order_id=record["open_client_order_id"], position_side=record["position_side"])
    assert result.order_id == "123456" and rejected == [attempt] and changes == [0] and len(posts) == 1
    assert "fetch" not in client.__dict__ and client.session.request is response


@pytest.mark.parametrize("attempt", ["repeat", "reentry", "other_thread"])
def test_live_transport_scope_cannot_delegate_another_order_request(single_case, monkeypatch, attempt):
    case = single_case
    posts = prepare_for_engine(case, monkeypatch)
    session, delegate, rejected = case["client"].session, case["client"].session.request, []
    def attempted_reuse(method, url, kwargs):
        try:
            if attempt == "reentry":
                with Prepared._native_prepared_claim_http_use(case["trade"], case["key"]):
                    pytest.fail("reentry obtained a second live context")
            else:
                session.request(method, url, **kwargs)
        except CChanException:
            rejected.append(attempt)
    def response(method, url, **kwargs):
        value = delegate(method, url, **kwargs)
        if method == "POST":
            if attempt == "other_thread":
                worker = threading.Thread(target=attempted_reuse, args=(method, url, kwargs))
                worker.start()
                worker.join(timeout=5)
                assert not worker.is_alive()
            else:
                attempted_reuse(method, url, kwargs)
        return value
    monkeypatch.setattr(session, "request", response)
    record = case["db"].get_record(case["key"])
    result = case["trade"].place_order(record["stock_code"], bool(record["is_buy"]), .1, 100,
        client_order_id=record["open_client_order_id"], position_side=record["position_side"])
    assert result.order_id == "123456" and rejected == [attempt] and len(posts) == 1
    assert session.request is response and case["db"].get_record(case["key"])["open_attempt"] == 1


@pytest.mark.parametrize("redirect", [None,
    (307, "https://fapi.binance.com/fapi/v1/order"),
    (308, "https://foreign.invalid/fapi/v1/order")],
    ids=["no_redirect", "same_origin_307", "foreign_308"])
def test_original_requests_cannot_follow_an_order_post_redirect(single_case, monkeypatch, redirect):
    case = single_case
    posts = prepare_for_engine(case, monkeypatch)
    session, transport, sent = case["client"].session, case["client"].session.request, []
    def adapter_send(request, **kwargs):
        assert not case["db"].db.conn.in_transaction
        sent.append(request)
        if urlsplit(request.url).hostname == "foreign.invalid":
            response = Response()
            response.status_code, response.reason = 400, "Bad Request"
            response._content = b'{"code":-1000,"msg":"synthetic forbidden redirect target"}'
            response.headers["Content-Type"] = "application/json"
        else:
            response = transport(request.method, request.url, data=request.body or b"",
                headers=request.headers, verify=kwargs["verify"], timeout=kwargs.get("timeout"))
            post_count = len([row for row in sent if row.method == "POST"])
            if redirect is not None and request.method == "POST" and post_count == 1:
                response.status_code, response.reason = redirect[0], "Synthetic Redirect"
                response.headers["Location"] = redirect[1]
                response._content = b""
        response.url, response.request = request.url, request
        return response
    for adapter in session.adapters.values():
        monkeypatch.setattr(adapter, "send", adapter_send)
    monkeypatch.setattr(session, "trust_env", False)  # No user netrc/proxy reads in this fake fixture.
    # Keep Requests' actual preparation, send and redirect implementation;
    # both native hosts and forbidden redirect targets stay below fake I/O.
    # The shared fixture deliberately replaces the class method with no_http.
    # Bind the import-time original only to this isolated, adapter-faked Session;
    # keep the global deny-network class method in place for every other client.
    monkeypatch.setattr(session, "request", _ORIGINAL_REQUESTS_REQUEST.__get__(session, requests.Session))
    assert session.request.__func__ is _ORIGINAL_REQUESTS_REQUEST
    assert requests.Session.request is not _ORIGINAL_REQUESTS_REQUEST
    record = case["db"].get_record(case["key"])
    result, failure = None, None
    try:
        result = case["trade"].place_order(record["stock_code"], bool(record["is_buy"]), .1, 100,
            client_order_id=record["open_client_order_id"], position_side=record["position_side"])
    except CChanException as error:
        failure = error
    actual_posts = [row for row in sent if row.method == "POST"]
    if not actual_posts and failure is not None:
        raise failure  # Show an unrelated setup/owner failure before judging redirects.
    assert len(actual_posts) == 1, "one guarded request delegated more than one actual adapter POST"
    assert urlsplit(actual_posts[0].url).hostname == "fapi.binance.com"
    assert parse_qs(actual_posts[0].body.decode())["newClientOrderId"] == [record["open_client_order_id"]]
    assert session.request.__func__ is _ORIGINAL_REQUESTS_REQUEST
    current = case["db"].get_record(case["key"])
    assert current["open_attempt"] == 1 and current["current_qty"] == 0
    if redirect is None:
        assert failure is None and result.order_id == "123456" and len(posts) == 1
    else:
        assert failure is not None and current["open_order_status"] == "submitting" and current["open_order_id"] is None
        assert [event["kind"] for event in case["db"].get_order_history(case["key"])["attempts"][0]["events"]] == ["intent", "claim"]


@pytest.mark.parametrize("retry_total,response_lost,during_wait", [(0, False, False), (0, True, False),
    (1, True, False), (0, True, True)],
    ids=["zero_success", "zero_lost_response", "read_retry_lost_response", "late_sdk_wait_retry"])
def test_original_http_adapter_cannot_retry_an_accepted_order(single_case, monkeypatch, retry_total, response_lost, during_wait):
    from io import BytesIO
    from urllib3.connectionpool import HTTPConnectionPool
    from urllib3.exceptions import ReadTimeoutError
    from urllib3.response import HTTPResponse
    from urllib3.util.retry import Retry

    case = single_case
    session, changed = case["client"].session, []
    if during_wait:
        def simulated_sleep(seconds):
            caller = inspect.currentframe().f_back
            assert caller.f_code.co_name == "throttle"
            request = caller.f_back
            assert request.f_code.co_name == "fetch2"
            if request.f_locals["path"] == "order" and request.f_locals["method"] == "POST":
                assert seconds > 0
                changed.append(True)
                for adapter in session.adapters.values():
                    adapter.max_retries = Retry(total=1, read=1, allowed_methods=None)
        monkeypatch.setattr(time, "sleep", simulated_sleep)
        case["client"].enableRateLimit, case["client"].rateLimit = True, 60000  # Force the fake throttle callback, not a real wait.
    posts = prepare_for_engine(case, monkeypatch)
    session, transport, sent = case["client"].session, case["client"].session.request, []
    def no_socket(*args, **kwargs):
        pytest.fail("this fake retry fixture must never create a real socket")
    monkeypatch.setattr("urllib3.util.connection.create_connection", no_socket)
    def make_request(pool, connection, method, url, body=None, headers=None, **kwargs):
        assert pool.host == "fapi.binance.com" and pool.proxy is None
        assert not case["db"].db.conn.in_transaction
        sent.append((method, url, body))
        response = transport(method, "https://"+pool.host+url, data=body or b"", headers=headers, verify=True)
        post_count = len([row for row in sent if row[0] == "POST"])
        if method == "POST" and response_lost and post_count == 1:
            raise ReadTimeoutError(pool, url, "synthetic accepted response was lost")
        return HTTPResponse(body=BytesIO(response.content), status=response.status_code, reason=response.reason,
            headers=dict(response.headers), preload_content=False, decode_content=False,
            pool=pool, connection=kwargs.get("response_conn"), request_method=method, request_url=url)
    monkeypatch.setattr(HTTPConnectionPool, "_make_request", make_request)
    for adapter in session.adapters.values():
        monkeypatch.setattr(adapter, "max_retries", Retry(total=retry_total, connect=0,
            read=1 if retry_total else False, redirect=0, status=0, other=0,
            allowed_methods=None, backoff_factor=0))
    monkeypatch.setattr(session, "trust_env", False)
    monkeypatch.setattr(session, "request", _ORIGINAL_REQUESTS_REQUEST.__get__(session, requests.Session))
    assert requests.Session.request is not _ORIGINAL_REQUESTS_REQUEST
    record = case["db"].get_record(case["key"])
    result, failure = None, None
    try:
        result = case["trade"].place_order(record["stock_code"], bool(record["is_buy"]), .1, 100,
            client_order_id=record["open_client_order_id"], position_side=record["position_side"])
    except CChanException as error:
        failure = error
    actual_posts = [row for row in sent if row[0] == "POST"]
    assert changed == ([True] if during_wait else [])
    assert len(actual_posts) == (0 if retry_total or during_wait else 1), "an unsafe adapter reached or repeated the order send"
    assert session.request.__func__ is _ORIGINAL_REQUESTS_REQUEST
    current = case["db"].get_record(case["key"])
    assert current["open_attempt"] == 1 and current["current_qty"] == 0
    if retry_total or response_lost:
        assert failure is not None and result is None
        assert current["open_order_status"] == "submitting" and current["open_order_id"] is None
        assert [event["kind"] for event in case["db"].get_order_history(case["key"])["attempts"][0]["events"]] == ["intent", "claim"]
    else:
        assert failure is None and result.order_id == "123456" and len(posts) == 1
