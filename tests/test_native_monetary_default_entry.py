"""Original configured add_trade must own sources/CAS, not a caller permit."""
import copy
import json
import sys
from contextlib import closing
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.OpenQuotaGen import CBenchPriceQuotaGen
from Trade.Script.OpeningInputs import COpeningInputs
from Trade.NativeOrderTransition import read_native_order_transition
from Trade.NativeAccountReconcile import observe_native_account_components
from Trade.AccountRiskStore import _sha
from Trade.db_util import CChanDB
from Trade import NativePreparedClient, NativePreparedIntent
from Trade import OrderAudit as Audit
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import single_case, capacity_case
from .test_native_monetary_execution import install_order_transport, prepare_for_engine
from .test_native_monetary_engine import install_recovery_transport
from .test_native_monetary_consumers import component_sources
from .test_native_monetary_terminal_observation import apply_native_filled_account_rows
from .test_native_prepared_last import install_last


def install_profile(case, *, damage=None):
    profile = {"schema": "chan-native-entry-profile-v1", "before_id": case["before_id"],
        "account_scope": "owned-default-entry", "policy": copy.deepcopy(case["policy"]),
        **{name+suffix: 60000 for name in ("instrument", "capacity", "last")
           for suffix in ("_max_age_ms", "_max_observation_span_ms")}}
    if damage is not None:
        damage(profile)
    data = json.loads(case["config"].read_bytes())
    data["trade"]["native_admission"] = profile
    case["config"].write_bytes(canonical_bytes(data))
    case["trade"].opening_inputs = COpeningInputs(case["config"], now_ms=lambda: case["clock"]["now"])
    case["trade"].quota_gen = CBenchPriceQuotaGen(10)
    return profile


@pytest.mark.parametrize("cold", [False, True])
def test_default_guarded_entry_collects_sources_once_and_sends_from_original_claim(capacity_case, monkeypatch, cold):
    case = capacity_case
    install_profile(case)
    install_last(case, monkeypatch)
    posts = install_order_transport(case, monkeypatch)
    if cold:
        previous = case["client"].session.request
        monkeypatch.setattr("requests.sessions.Session.request", lambda session, method, url, **kw: previous(method, url, **kw))
        case["trade"].exchange = None
    result = case["trade"].add_trade(case["db"].get_record(case["key"]), 100)
    document = read_native_order_transition(case["db"], case["key"])
    binding = document["payload"]["root"]["preparation"]
    row = case["db"].get_record(case["key"])
    contract = json.loads(row["open_order_contract"])
    assert document["payload"]["stage"] == "claim"
    assert binding["schema"] == "chan-native-prepared-intent-binding-v4"
    assert binding["monetary"]["payload"]["status"] == "within_model_capacity"
    assert contract["schema"] == "chan-native-client-order-v1"
    assert row["open_attempt"] == 1 and row["open_order_status"] == "open" and row["open_order_id"] == "123456"
    assert row["open_requested_qty"] == .1 and contract["price"] == "100"
    assert [name for name, _ in case["http_calls"]].count("fapiPrivateGetFeeBurn") == 1
    assert len(posts) == 1 and result.order_id == "123456" and result.filled == 0
    assert posts[0]["newClientOrderId"] == row["open_client_order_id"]
    events = case["db"].get_order_history(case["key"])["attempts"][0]["events"]
    assert [event["kind"] for event in events][:3] == ["intent", "claim", "ack"]


def install_filled_venue_response(case, monkeypatch, state):
    """Install the same bottom-only FILLED response before the SDK invocation."""
    previous, risk = case["client"].session.request, {}

    def filled_venue(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        if method == "POST":
            state["row"] = response.json()
            native_fill = {"is_buy": state["row"]["side"] == "BUY", "position_side": state["row"]["positionSide"]}
            risk.update(apply_native_filled_account_rows(case, state, native_fill, native_status="FILLED", quantity="0.1",
                maker=state["row"]["timeInForce"] == "GTX"))
            response._content = json.dumps(state["row"]).encode()
        elif urlsplit(url).path == "/fapi/v3/positionRisk" and risk:
            rows = response.json()
            native = next(row for row in rows if row["symbol"] == case["units"][0]["id"])
            native.update(risk)
            response._content = json.dumps(rows).encode()
        return response

    monkeypatch.setattr(case["client"].session, "request", filled_venue)


def install_filled_default_venue(case, monkeypatch):
    """Install all fake I/O before the original default entry owns its scope."""
    install_profile(case)
    install_last(case, monkeypatch)
    state = install_recovery_transport(case, monkeypatch)
    posts = install_order_transport(case, monkeypatch)
    initial = case["db"].get_record(case["key"])
    install_filled_venue_response(case, monkeypatch, state)
    return posts, state, initial


def assert_filled_entry_source_account_and_cold(case, monkeypatch, store, posts, state, result):
    row = case["db"].get_record(case["key"])
    claim = read_native_order_transition(case["db"], case["key"])
    assert result.status == "closed" and result.requested == .1 and result.filled == .1 and result.avg_price == 100
    assert len(posts) == 1 and row["open_attempt"] == 1 and row["current_qty"] == .1
    assert posts[0]["newClientOrderId"] == row["open_client_order_id"]
    native_fill = case["execution_io"][case["units"][0]["id"]].rows[-1]
    assert native_fill["positionSide"] == posts[0]["positionSide"] == row["position_side"]
    assert native_fill["side"] == posts[0]["side"]
    assert claim["payload"]["stage"] == "claim"
    events = case["db"].get_order_history(case["key"])["attempts"][0]["events"]
    observations = [event for event in events if event["kind"] == "native_terminal_observation"]
    assert len(observations) == 1, "a complete FILLED POST must not bypass the original terminal GET source"
    assert [method for method, _ in state["requests"]] == ["GET"]
    params, request = component_sources(case)
    report = observe_native_account_components(case["db"], **params)
    assert report["payload"]["status"] == "matched_components", report["payload"]["issues"]
    assert not [item for item in report["payload"]["pending"]["payload"]["reservations"]
                if item["attempt"]["record_id"] == case["key"]]
    check = case["db"].reconcile_native_account(**request)
    assert check["payload"]["report"]["payload"]["status"] == "matched_observations"
    assert case["db"].get_account_risk_state(request["account_context"])["frozen"] is False

    original_db, old_client, trade = case["db"], case["client"], case["trade"]
    original_request, cold_requests = old_client.session.request, []
    def cold_transport(session, method, url, **kwargs):
        assert session is not old_client.session and method == "GET"
        assert not trade.chan_db.db.conn.in_transaction
        cold_requests.append(urlsplit(url).path)
        return original_request(method, url, **kwargs)
    monkeypatch.setattr("requests.sessions.Session.request", cold_transport)
    with closing(CChanDB(db_conf=store[1])) as restarted:
        try:
            trade.chan_db, case["db"], trade.exchange = restarted, restarted, None
            case["clock"]["now"] += 3600_000
            trade.safety_policy.environ["CHANPY_KILL_SWITCH"] = "YES"
            cold = trade.query_order(row["stock_code"], client_order_id=row["open_client_order_id"])
            assert cold.status == "closed" and cold.filled == .1 and cold.avg_price == 100
            assert type(trade.exchange) is type(old_client) and trade.exchange is not old_client
            case["client"] = trade.exchange
            before_duplicate = restarted.get_record(case["key"])
            trade._apply_order_report(case["key"], "open", cold, row["open_client_order_id"], 1)
            assert restarted.get_record(case["key"]) == before_duplicate
            _, cold_request = component_sources(case)
            cold_check = restarted.reconcile_native_account(**cold_request)
            assert cold_check["payload"]["report"]["payload"]["status"] == "matched_observations"
            assert restarted.get_account_risk_state(cold_request["account_context"])["frozen"] is False
            assert trade.safety_policy.environ["CHANPY_KILL_SWITCH"] == "YES"
            assert read_native_order_transition(restarted, case["key"]) == claim
        finally:
            trade.chan_db, case["db"], case["client"], trade.exchange = original_db, original_db, old_client, old_client
    assert cold_requests and "/fapi/v1/exchangeInfo" in cold_requests and len(posts) == 1


def test_default_filled_post_obtains_native_terminal_source_before_account_reconciliation(capacity_case, monkeypatch, store):
    case = capacity_case
    posts, state, initial = install_filled_default_venue(case, monkeypatch)
    result = case["trade"].add_trade(initial, 100)
    assert posts[0]["type"] == "LIMIT" and posts[0]["timeInForce"] == "GTC"
    assert_filled_entry_source_account_and_cold(case, monkeypatch, store, posts, state, result)


@pytest.mark.parametrize("kind,post_only", [("market", False), ("limit", True)])
def test_direct_filled_order_style_preserves_native_account_roundtrip(capacity_case, monkeypatch, store, kind, post_only):
    case = capacity_case
    state = install_recovery_transport(case, monkeypatch)
    price = None if kind == "market" else 100
    posts = prepare_for_engine(case, monkeypatch, price=price, post_only=post_only)
    install_filled_venue_response(case, monkeypatch, state)
    record = case["db"].get_record(case["key"])
    result = case["trade"].place_order(record["stock_code"], bool(record["is_buy"]), .1, price,
        client_order_id=record["open_client_order_id"], position_side=record["position_side"], post_only=post_only)
    case["trade"]._apply_order_report(case["key"], "open", result, record["open_client_order_id"], record["open_attempt"])
    assert posts[0]["type"] == kind.upper()
    assert posts[0].get("timeInForce") == ("GTX" if post_only else None)
    native_fill = case["execution_io"][case["units"][0]["id"]].rows[-1]
    assert native_fill["maker"] is post_only
    assert Decimal(native_fill["commission"]) == Decimal("0.002" if post_only else "0.004")
    assert_filled_entry_source_account_and_cold(case, monkeypatch, store, posts, state, result)


@pytest.mark.parametrize("observation", ["stale", "average", "unavailable"])
def test_default_filled_post_cannot_replace_known_fills_with_unconfirmed_query(single_case, monkeypatch, observation):
    case = single_case
    posts, state, initial = install_filled_default_venue(case, monkeypatch)
    previous = case["client"].session.request
    def changed_get(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        if method == "GET" and urlsplit(url).path == "/fapi/v1/order":
            if observation == "unavailable":
                raise requests.exceptions.Timeout("synthetic terminal query unavailable")
            row = response.json()
            if observation == "stale":
                row.update(status="NEW", executedQty="0", avgPrice="0", cumQuote="0")
            else:
                row.update(avgPrice="99", cumQuote="9.9")
            response._content = json.dumps(row).encode()
        return response
    monkeypatch.setattr(case["client"].session, "request", changed_get)
    with pytest.raises(CChanException):
        case["trade"].add_trade(initial, 100)
    record = case["db"].get_record(case["key"])
    assert record["open_attempt"] == 1 and record["open_order_status"] == "submitting"
    assert record["open_order_id"] == "123456" and record["current_qty"] == 0
    assert read_native_order_transition(case["db"], case["key"])["payload"]["stage"] == "claim"
    assert len(posts) == 1 and [method for method, _ in state["requests"]] == ["GET"]
    with pytest.raises(CChanException):
        case["trade"].add_trade(record, 100)
    assert len(posts) == 1 and case["db"].get_record(case["key"])["current_qty"] == 0


@pytest.mark.parametrize("observation", ["stale", "average"])
def test_known_filled_post_survives_unavailable_query_and_cold_restore(single_case, monkeypatch, store, observation):
    case = single_case
    posts, state, initial = install_filled_default_venue(case, monkeypatch)
    previous, phase = case["client"].session.request, {"value": "unavailable"}

    def changed_get(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        if method == "GET" and urlsplit(url).path == "/fapi/v1/order":
            if phase["value"] == "unavailable":
                raise requests.exceptions.Timeout("synthetic first terminal query unavailable")
            row = response.json()
            if phase["value"] == "stale":
                row.update(status="NEW", executedQty="0", avgPrice="0", cumQuote="0")
            elif phase["value"] == "average":
                row.update(avgPrice="99", cumQuote="9.9")
            response._content = json.dumps(row).encode()
        return response

    monkeypatch.setattr(case["client"].session, "request", changed_get)
    with pytest.raises(CChanException) as failure:
        case["trade"].add_trade(initial, 100)
    assert failure.value.errcode == ErrCode.LIST_ORDER_FAIL
    record = case["db"].get_record(case["key"])
    assert len(posts) == 1 and [method for method, _ in state["requests"]] == ["GET"]
    assert state["row"]["status"] == "FILLED" and Decimal(state["row"]["executedQty"]) == Decimal("0.1")
    assert Decimal(state["row"]["avgPrice"]) == Decimal("100")
    assert record["open_attempt"] == 1 and record["open_order_id"] == "123456"
    assert record["open_order_status"] == "submitting" and record["current_qty"] == 0
    claim = read_native_order_transition(case["db"], case["key"])
    submitted_history = case["db"].get_order_history(case["key"])
    submitted_events = submitted_history["attempts"][0]["events"]
    assert submitted_history["schema"] == "chan-order-history-v3"
    assert submitted_history["coverage"] == "intents_applied_reports_and_sdk_submission_reports"
    reports = [event["submission_report"] for event in submitted_events if event["kind"] == "sdk_submission_report"]
    assert reports == [{"order_id": "123456", "client_order_id": record["open_client_order_id"],
        "requested": "0.1", "filled": "0.1", "avg_price": "100", "status": "closed"}]
    assert not any(event["kind"] == "native_terminal_observation" for event in submitted_events)
    legacy = case["db"].get_order_intent(case["pending_raw"]["clientOrderId"])["record"]
    assert legacy["id"] != case["key"] and legacy["status"] == "partially_filled"
    legacy_fields = ("open_attempt", "open_order_id", "open_client_order_id", "open_order_status",
                     "open_filled_qty", "current_qty", "open_price")

    original_db, old_client, trade = case["db"], case["client"], case["trade"]
    cold_requests = []
    def cold_transport(session, method, url, **kwargs):
        assert session is not old_client.session and method == "GET"
        assert not trade.chan_db.db.conn.in_transaction
        assert kwargs["verify"] is True
        target = urlsplit(url)
        cold_requests.append(target.path)
        body = None
        if target.hostname == "api.binance.com" and target.path in {
                "/sapi/v1/capital/config/getall", "/sapi/v1/margin/allPairs", "/sapi/v1/margin/isolated/allPairs"}:
            body = []
        elif (target.hostname, target.path) in {("api.binance.com", "/api/v3/exchangeInfo"),
                                              ("dapi.binance.com", "/dapi/v1/exchangeInfo")}:
            body = {"timezone": "UTC", "serverTime": case["clock"]["now"], "symbols": []}
        elif (target.hostname, target.path) == ("fapi.binance.com", "/fapi/v1/order"):
            params = parse_qs(target.query)
            if params.get("symbol") == [case["pending_raw"]["symbol"]]:
                assert params.get("orderId") == [str(case["pending_raw"]["orderId"])]
                body = copy.deepcopy(case["pending_raw"])
                body["cumQuote"] = str(Decimal(body["executedQty"])*Decimal(body["avgPrice"]))
        if body is not None:
            response = requests.Response()
            response.status_code, response.reason, response.url = 200, "OK", url
            response.headers["Content-Type"] = "application/json"
            response._content = json.dumps(body).encode()
            return response
        return changed_get(method, url, **kwargs)

    monkeypatch.setattr("requests.sessions.Session.request", cold_transport)
    with closing(CChanDB(db_conf=store[1])) as restarted:
        try:
            trade.chan_db, case["db"], trade.exchange = restarted, restarted, None
            case["clock"]["now"] += 3600_000
            trade.safety_policy.environ["CHANPY_KILL_SWITCH"] = "YES"
            phase["value"] = observation
            before, history = restarted.get_record(case["key"]), restarted.get_order_history(case["key"])
            restored = trade.restore()
            assert type(trade.exchange) is type(old_client) and trade.exchange is not old_client
            assert [method for method, _ in state["requests"]] == ["GET", "GET"]
            assert "/fapi/v1/exchangeInfo" in cold_requests
            assert {item["id"] for item in restored} == {legacy["id"]}, \
                "cold recovery must keep the legacy order but reject facts contradicting the complete POST"
            assert restarted.get_record(case["key"]) == before
            assert restarted.get_order_history(case["key"]) == history
            assert read_native_order_transition(restarted, case["key"]) == claim
            current_legacy = restarted.get_record(legacy["id"])
            assert {key: current_legacy[key] for key in legacy_fields} == {key: legacy[key] for key in legacy_fields}
            assert len(posts) == 1

            phase["value"] = "healthy"
            assert {item["id"] for item in trade.restore()} == {legacy["id"], case["key"]}
            recovered = restarted.get_record(case["key"])
            assert recovered["current_qty"] == .1 and recovered["open_price"] == 100
            assert recovered["open_attempt"] == 1 and recovered["open_order_status"] == "closed"
            assert {item["id"] for item in trade.restore()} == {legacy["id"]}
            case["client"] = trade.exchange
            params, request = component_sources(case)
            report = observe_native_account_components(restarted, **params)
            assert report["payload"]["status"] == "matched_components", report["payload"]["issues"]
            check = restarted.reconcile_native_account(**request)
            assert check["payload"]["report"]["payload"]["status"] == "matched_observations"
            assert trade.safety_policy.environ["CHANPY_KILL_SWITCH"] == "YES" and len(posts) == 1
            assert read_native_order_transition(restarted, case["key"]) == claim
        finally:
            trade.chan_db, case["db"], case["client"], trade.exchange = original_db, original_db, old_client, old_client
    assert cold_requests and "/fapi/v1/exchangeInfo" in cold_requests


def test_missing_native_profile_cannot_fall_back_to_legacy_prepare_or_intent(single_case, monkeypatch):
    case = single_case
    posts = install_order_transport(case, monkeypatch)
    with pytest.raises(CChanException, match="原生.*profile"):
        case["trade"].add_trade(case["db"].get_record(case["key"]), 100)
    assert not case["http_calls"] and not posts
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("cold", [False, True])
def test_original_before_anchor_is_validated_before_any_cold_or_warm_source(single_case, monkeypatch, cold):
    case = single_case
    install_profile(case, damage=lambda p: p.update(before_id="0"*64))
    previous = case["client"].session.request
    if cold:
        monkeypatch.setattr("requests.sessions.Session.request", lambda session, method, url, **kw: previous(method, url, **kw))
        case["trade"].exchange = None
    with pytest.raises(CChanException):
        case["trade"].add_trade(case["db"].get_record(case["key"]), 100)
    assert case["http_calls"] == []
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("replacement", ["database", "connection"])
def test_quota_callback_cannot_redirect_native_default_acquire_to_any_foreign_sql(single_case, monkeypatch, tmp_path, replacement):
    case = single_case
    install_profile(case)
    chan, database, connection = case["db"], case["db"].db, case["db"].db.conn
    quota = case["trade"].quota_gen.get_quota
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"foreign-default.db")})) as foreign:
        statements = []
        foreign.db.conn.set_trace_callback(statements.append)
        def changed(*args):
            amount = quota(*args)
            if replacement == "database":
                case["trade"].chan_db = foreign
            else:
                database.conn = foreign.db.conn
            return amount
        monkeypatch.setattr(case["trade"].quota_gen, "get_quota", changed)
        try:
            with pytest.raises(CChanException):
                case["trade"].add_trade(chan.get_record(case["key"]), 100)
        finally:
            case["trade"].chan_db, database.conn = chan, connection
        assert statements == []
    assert case["http_calls"] == [] and chan.get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("field", [name+suffix for name in ("instrument", "capacity", "last")
    for suffix in ("_max_age_ms", "_max_observation_span_ms")])
@pytest.mark.parametrize("bad", [None, True, -1, "60000", 60000.5, 2**63])
def test_each_profile_budget_is_explicit_and_typed_before_source_io(single_case, monkeypatch, field, bad):
    case = single_case
    install_profile(case, damage=lambda profile: profile.update({field: bad}))
    posts = install_order_transport(case, monkeypatch)
    with pytest.raises(CChanException, match="原生.*profile"):
        case["trade"].add_trade(case["db"].get_record(case["key"]), 100)
    assert case["http_calls"] == [] and not posts
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("damage", ["schema", "extra", "missing", "policy"])
def test_native_profile_has_no_pass_field_missing_default_or_policy_downgrade(single_case, monkeypatch, damage):
    case = single_case
    def alter(profile):
        if damage == "schema": profile["schema"] = "chan-native-entry-profile-v0"
        elif damage == "extra": profile["passed"] = True
        elif damage == "missing": del profile["before_id"]
        else: del profile["policy"]["max_age_ms"]["balance"]
    install_profile(case, damage=alter)
    posts = install_order_transport(case, monkeypatch)
    with pytest.raises(CChanException, match="原生.*profile"):
        case["trade"].add_trade(case["db"].get_record(case["key"]), 100)
    assert case["http_calls"] == [] and not posts
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


def test_caller_trade_info_cannot_substitute_a_profile_for_the_original_config(single_case, monkeypatch):
    case = single_case
    record = case["db"].get_record(case["key"])
    record.update(native_admission={"passed": True}, before_id=case["before_id"], policy=case["policy"])
    posts = install_order_transport(case, monkeypatch)
    with pytest.raises(CChanException, match="原生.*profile"):
        case["trade"].add_trade(record, 100)
    assert case["http_calls"] == [] and not posts
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


def test_default_owned_intent_preserves_actual_original_risk_and_score_metadata(single_case, monkeypatch):
    case = single_case
    install_profile(case)
    install_last(case, monkeypatch)
    posts = install_order_transport(case, monkeypatch)
    case["db"].db.execute(f"UPDATE {case['db'].table} SET risk_multiplier=?, model_score_before=? WHERE id=?", (.5, .75, case["key"]))
    result = case["trade"].add_trade(case["db"].get_record(case["key"]), 100)
    row = case["db"].get_record(case["key"])
    assert row["open_attempt"] == 1 and row["risk_multiplier"] == .5 and row["model_score_before"] == .75
    assert row["open_requested_qty"] == .1 and len(posts) == 1 and result.order_id == "123456"


@pytest.mark.parametrize("dependency", ["cold", "acquire", "acquire_body", "claim_capture", "claim_owner",
    "claim_live", "claim_consume", "claim_finish"])
def test_default_entry_checks_actual_source_dependencies_before_calling_them(single_case, monkeypatch, dependency):
    case = single_case
    install_profile(case)
    if dependency == "cold":
        case["trade"].exchange = None
    touched = []
    def changed(*args, **kwargs):
        touched.append(True)
        pytest.fail("a substituted native source dependency must not execute")
    names = {"acquire": "acquire_binance_standard_prepared_intent", "acquire_body": "_acquire_prepared_diagnostic_intent",
        "claim_capture": "_capture_native_claim_context", "claim_owner": "_assert_native_claim_owner",
        "claim_live": "_claim_live", "claim_consume": "consume_prepared_claim_context", "claim_finish": "finish_prepared_claim_context"}
    owner, name = ((NativePreparedClient, "initialize_native_prepared_client") if dependency == "cold"
                   else (NativePreparedIntent, names[dependency]))
    monkeypatch.setattr(owner, name, changed)
    with pytest.raises(CChanException):
        case["trade"].add_trade(case["db"].get_record(case["key"]), 100)
    assert touched == [] and not case["http_calls"]
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("replacement", ["database", "connection"])
def test_post_intent_read_cannot_redirect_the_original_transition_rebuild(single_case, monkeypatch, tmp_path, replacement):
    case = single_case
    install_profile(case)
    install_last(case, monkeypatch)
    posts = install_order_transport(case, monkeypatch)
    chan, database, connection = case["db"], case["db"].db, case["db"].db.conn
    original = chan.get_record
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"foreign-after-native-intent.db")})) as foreign, foreign.db.transaction():
        statements, touched = [], []
        foreign.db.conn.set_trace_callback(statements.append)
        def changed(record_id):
            row = original(record_id)
            caller = sys._getframe(1).f_code
            if (not touched and record_id == case["key"] and row["open_order_status"] == "created"
                    and caller.co_name == "_acquire_open_intent" and caller.co_filename.endswith("CCXTTradeEngine.py")):
                touched.append(True)
                if replacement == "database": chan.db = foreign.db
                else: database.conn = foreign.db.conn
            return row
        monkeypatch.setattr(chan, "get_record", changed)
        try:
            with pytest.raises(CChanException):
                case["trade"].add_trade(original(case["key"]), 100)
        finally:
            chan.db, database.conn = database, connection
        assert touched and statements == []
    assert not posts and original(case["key"])["open_attempt"] == 1
    assert original(case["key"])["open_order_status"] == "created"


def unavailable_filled_submission(case, monkeypatch):
    """New verification cases share the original SDK and bottom-only timeout."""
    posts, state, initial = install_filled_default_venue(case, monkeypatch)
    previous = case["client"].session.request
    def unavailable_get(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        if method == "GET" and urlsplit(url).path == "/fapi/v1/order":
            raise requests.exceptions.Timeout("synthetic submission query unavailable")
        return response
    monkeypatch.setattr(case["client"].session, "request", unavailable_get)
    with pytest.raises(CChanException) as error:
        case["trade"].add_trade(initial, 100)
    assert error.value.errcode == ErrCode.LIST_ORDER_FAIL
    assert len(posts) == 1 and [method for method, _ in state["requests"]] == ["GET"]
    assert state["row"]["status"] == "FILLED" and Decimal(state["row"]["executedQty"]) == Decimal("0.1")
    return posts, state


def assert_unpublished_submission_stays_unknown(case, posts, state):
    record = case["db"].get_record(case["key"])
    assert len(posts) == 1 and state["requests"] == []
    assert record["open_order_id"] == "123456" and record["open_attempt"] == 1
    assert record["open_order_status"] == "submitting" and record["current_qty"] == 0
    assert [event["kind"] for event in case["db"].get_order_history(case["key"])["attempts"][0]["events"]] == ["intent", "claim", "ack"]
    assert read_native_order_transition(case["db"], case["key"])["payload"]["stage"] == "claim"
    assert not case["db"].db.conn.in_transaction
    return record


def test_sdk_submission_alone_never_releases_unknown_reservation(single_case, monkeypatch):
    case = single_case
    posts, state = unavailable_filled_submission(case, monkeypatch)
    params, _ = component_sources(case)
    report = observe_native_account_components(case["db"], **params)
    pending = report["payload"]["pending"]["payload"]
    assert report["payload"]["status"] != "matched_components"
    reservations = [item for item in pending["reservations"] if item["attempt"]["record_id"] == case["key"]]
    assert len(reservations) == 1 and reservations[0]["remaining_base_quantity"] == "0.1"
    assert not pending.get("terminal_observations", [])
    assert case["db"].get_record(case["key"])["current_qty"] == 0
    assert len(posts) == 1 and [method for method, _ in state["requests"]] == ["GET"]


def test_sdk_submission_history_checks_canonical_contract_and_prefix(single_case, monkeypatch, store):
    case = single_case
    unavailable_filled_submission(case, monkeypatch)
    expected = case["db"].get_order_history(case["key"])
    with closing(CChanDB(db_conf=store[1])) as restarted:
        assert restarted.get_order_history(case["key"]) == expected
    row = case["db"].db.query_one(f"SELECT * FROM {Audit.EVENTS} WHERE record_id=? AND kind='sdk_submission_report'", (case["key"],))
    original = json.loads(row["payload"])
    for damage in ("shape", "requested", "normal_form", "client", "order", "kind", "future_stamp", "extra"):
        changed = copy.deepcopy(original)
        report = changed["submission_report"]
        if damage == "shape":
            changed["submission_report"] = []
        elif damage == "requested":
            report.update(requested="0.2", filled="0.2")
        elif damage == "normal_form":
            report["filled"] = "0.10"
        elif damage == "client":
            report["client_order_id"] = "different"
        elif damage == "order":
            report["order_id"] = "654321"
        elif damage == "kind":
            changed["kind"] = "native_terminal_observation"
        elif damage == "future_stamp":
            changed["observed_ms"] = case["clock"]["now"]+2000
        else:
            report["native_admission_verified"] = True
        data_sha = _sha({"state": changed["state"], "submission_report": changed["submission_report"]})
        case["db"].db.execute(f"DROP TRIGGER {Audit.EVENTS}_no_update")
        case["db"].db.execute(f"UPDATE {Audit.EVENTS} SET payload=?,payload_sha256=?,data_sha256=?,kind=?,observed_ms=? WHERE event_id=?",
            (canonical_bytes(changed).decode(), _sha(changed), data_sha, changed["kind"], changed["observed_ms"], row["event_id"]))
        case["db"].db.execute(Audit.SCHEMA[f"{Audit.EVENTS}_no_update"])
        with pytest.raises(CChanException):
            case["db"].get_order_history(case["key"])
        case["db"].db.execute(f"DROP TRIGGER {Audit.EVENTS}_no_update")
        case["db"].db.execute(f"UPDATE {Audit.EVENTS} SET payload=?,payload_sha256=?,data_sha256=?,kind=?,observed_ms=? WHERE event_id=?",
            (row["payload"], row["payload_sha256"], row["data_sha256"], row["kind"], row["observed_ms"], row["event_id"]))
        case["db"].db.execute(Audit.SCHEMA[f"{Audit.EVENTS}_no_update"])
    assert case["db"].get_order_history(case["key"]) == expected
    old_prefix = copy.deepcopy(expected)
    old_prefix["attempts"][0]["events"] = old_prefix["attempts"][0]["events"][:3]
    old_prefix.update(Audit._history_header(old_prefix["attempts"]))
    assert old_prefix["schema"] == "chan-order-history-v1"
    Audit.verify_history_prefix(case["db"].db, [old_prefix])
    wrong_header = copy.deepcopy(expected)
    wrong_header["schema"] = "chan-order-history-v2"
    with pytest.raises(CChanException):
        Audit.verify_history_prefix(case["db"].db, [wrong_header])


def test_sdk_submission_publication_failure_keeps_original_ack_unknown(single_case, monkeypatch):
    case = single_case
    posts, state, initial = install_filled_default_venue(case, monkeypatch)
    case["db"].db.execute(f"CREATE TRIGGER reject_sdk_submission BEFORE INSERT ON {Audit.EVENTS} "
        "WHEN NEW.kind='sdk_submission_report' BEGIN SELECT RAISE(ABORT,'PRIVATE_SDK_REPORT_WRITE_FAILURE'); END")
    with pytest.raises(CChanException) as error:
        case["trade"].add_trade(initial, 100)
    assert "PRIVATE_" not in str(error.value)
    record = assert_unpublished_submission_stays_unknown(case, posts, state)
    with pytest.raises(CChanException):
        case["trade"].add_trade(record, 100)
    assert len(posts) == 1 and case["db"].get_record(case["key"]) == record


@pytest.mark.parametrize("damage", ["bool", "float", "backward", "future"])
def test_sdk_submission_stamp_rejects_invalid_time_before_commit(single_case, monkeypatch, damage):
    case = single_case
    posts, state, initial = install_filled_default_venue(case, monkeypatch)
    clock = Audit.utc_now_ms
    def invalid_stamp():
        frame, now = sys._getframe(1), clock()
        if frame.f_code.co_name == "_append" and frame.f_locals.get("kind") == "sdk_submission_report":
            return {"bool": True, "float": float(now), "backward": now-2000, "future": now+2000}[damage]
        return now
    monkeypatch.setattr(Audit, "utc_now_ms", invalid_stamp)
    with pytest.raises(CChanException):
        case["trade"].add_trade(initial, 100)
    assert_unpublished_submission_stays_unknown(case, posts, state)


@pytest.mark.parametrize("replacement", ["database", "connection"])
def test_sdk_submission_stamp_cannot_write_through_foreign_owner(single_case, monkeypatch, tmp_path, replacement):
    case = single_case
    posts, state, initial = install_filled_default_venue(case, monkeypatch)
    chan, backend = case["db"], case["db"].db
    connection = backend.conn
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"foreign-submission.db")})) as foreign:
        foreign_sql, local_after_stamp, touched = [], [], []
        foreign.db.conn.set_trace_callback(foreign_sql.append)
        connection.set_trace_callback(lambda sql: local_after_stamp.append(sql) if touched else None)
        clock = Audit.utc_now_ms
        def changed_clock():
            frame = sys._getframe(1)
            if frame.f_code.co_name == "_append" and frame.f_locals.get("kind") == "sdk_submission_report" and not touched:
                touched.append(replacement)
                if replacement == "database":
                    chan.db = foreign.db
                else:
                    backend.conn = foreign.db.conn
            return clock()
        monkeypatch.setattr(Audit, "utc_now_ms", changed_clock)
        try:
            with pytest.raises(CChanException):
                case["trade"].add_trade(initial, 100)
        finally:
            chan.db, backend.conn = backend, connection
            connection.set_trace_callback(None)
        assert touched == [replacement] and foreign_sql == []
        assert not any(sql.lstrip().upper().startswith("INSERT") for sql in local_after_stamp)
    assert_unpublished_submission_stays_unknown(case, posts, state)


@pytest.mark.parametrize("dependency", ["_sdk_submission_report", "_assert_sdk_submission", "read_history"])
def test_late_sdk_submission_dependency_is_refused_before_invocation(single_case, monkeypatch, dependency):
    case = single_case
    posts, state, initial = install_filled_default_venue(case, monkeypatch)
    previous, original = case["client"].session.request, getattr(Audit, dependency)
    calls, touched = [], []
    def unproved(*args, **kwargs):
        calls.append(True)
        raise AssertionError("unproved SDK submission dependency executed")
    def changed_get(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        if method == "GET" and urlsplit(url).path == "/fapi/v1/order":
            touched.append(dependency)
            monkeypatch.setattr(Audit, dependency, unproved)
        return response
    monkeypatch.setattr(case["client"].session, "request", changed_get)
    try:
        with pytest.raises(CChanException):
            case["trade"].add_trade(initial, 100)
    finally:
        monkeypatch.setattr(Audit, dependency, original)
    assert touched == [dependency] and calls == []
    record = case["db"].get_record(case["key"])
    assert record["open_order_status"] == "submitting" and record["current_qty"] == 0
    events = case["db"].get_order_history(case["key"])["attempts"][0]["events"]
    assert sum(event["kind"] == "sdk_submission_report" for event in events) == 1
    assert not any(event["kind"] == "native_terminal_observation" for event in events)
    assert read_native_order_transition(case["db"], case["key"])["payload"]["stage"] == "claim"
    assert len(posts) == 1 and [method for method, _ in state["requests"]] == ["GET"]
