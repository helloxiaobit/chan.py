"""Original Engine recovery consumers, real monetary L2 and bottom-only fake."""
import copy
import json
import types
from contextlib import closing
from urllib.parse import parse_qs, urlsplit

import pytest
import ccxt
from requests import Response

from Common.ChanException import CChanException
from Trade import NativeOrderTransition as Transition
from Trade import db_util as db_module
from Trade.db_util import CChanDB
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import capacity_case, single_case
from .test_native_monetary_claim import claim_context
from .test_native_monetary_prepared_intent import acquire
from .test_native_prepared_last import install_last
from .test_native_pending_orders import regular_row


def install_recovery_transport(case, monkeypatch):
    # The source fixture uses a fixed future UTC epoch; original client-only
    # recovery must use that same fake business clock, not the desktop clock.
    monkeypatch.setattr("Trade.CCXTTradeEngine.utc_now_ms", lambda: case["clock"]["now"])
    previous, observed = case["client"].session.request, []
    state = {"row": None}
    def transport(method, url, **kwargs):
        target = urlsplit(url)
        if target.path != "/fapi/v1/order":
            return previous(method, url, **kwargs)
        assert method in {"GET", "DELETE"}, "recovery must never submit a new order"
        assert target.hostname == "fapi.binance.com" and kwargs["verify"] is True
        assert not case["db"].db.conn.in_transaction
        params = {key: values[0] for key, values in parse_qs(target.query).items()}
        assert params["symbol"] == "TESTUSDT" and {"timestamp", "signature"} <= set(params)
        assert params.get("orderId") == "123456" or params.get("origClientOrderId") == state["row"]["clientOrderId"]
        observed.append((method, copy.deepcopy(params)))
        row = copy.deepcopy(state["row"])
        if method == "DELETE":
            row["status"] = "CANCELED"
            state["row"] = copy.deepcopy(row)
        response = Response()
        response.status_code, response.reason, response.url = 200, "OK", url
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(row).encode()
        return response
    monkeypatch.setattr(case["client"].session, "request", transport)
    state["requests"] = observed
    return state


def claimed_order(case, monkeypatch, *, price=100, post_only=False):
    install_last(case, monkeypatch)
    state = install_recovery_transport(case, monkeypatch)
    assert acquire(case, price=price, post_only=post_only)
    with case["db"].db.transaction():
        context = claim_context(case)
        assert case["db"].claim_order_submission(case["key"], "open", native_claim=context)
    record = case["db"].get_record(case["key"])
    contract = json.loads(record["open_order_contract"])
    row = regular_row("binance", contract["market"]["id"], 123456)
    row.update(clientOrderId=record["open_client_order_id"], origQty=contract["exchange_amount"], executedQty="0.02",
        avgPrice="100", cumQuote="2", side="BUY" if record["is_buy"] else "SELL", positionSide=record["position_side"],
        type="MARKET" if price is None else "LIMIT", origType="MARKET" if price is None else "LIMIT",
        price=contract["price"] or "0", timeInForce="GTX" if post_only else "GTC", reduceOnly=False,
        status="PARTIALLY_FILLED", time=case["clock"]["now"], updateTime=case["clock"]["now"])
    state["row"] = row
    return state, record, contract


@pytest.mark.parametrize("kind,post_only", [("limit", False), ("limit", True), ("market", False)])
def test_original_engine_queries_real_claim_then_original_report_consumer_applies_base_units(capacity_case, monkeypatch, kind, post_only):
    case = capacity_case
    state, record, contract = claimed_order(case, monkeypatch, price=None if kind == "market" else 100, post_only=post_only)
    claim = Transition.read_native_order_transition(case["db"], case["key"])
    result = case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert result.order_id == "123456" and result.requested == .1 and result.filled == .02
    assert result.avg_price == 100 and result.status == "open" and result.client_order_id == record["open_client_order_id"]
    after = case["db"].get_record(case["key"])
    assert after["open_order_id"] == "123456" and after["open_order_status"] == "submitting" and after["current_qty"] == 0
    assert case["db"].apply_open_fill(case["key"], result.filled, result.avg_price, result.status,
        client_order_id=result.client_order_id, order_id=result.order_id, expected_attempt=1) == .02
    assert case["db"].get_record(case["key"])["current_qty"] == .02
    assert Transition.read_native_order_transition(case["db"], case["key"]) == claim
    assert len(state["requests"]) == 1 and state["requests"][0][0] == "GET" and len(case["created"]) == 3


def apply_query(case, record):
    result = case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    case["db"].apply_open_fill(case["key"], result.filled, result.avg_price, result.status,
        client_order_id=result.client_order_id, order_id=result.order_id, expected_attempt=1)
    return result


def test_original_cancel_then_query_does_not_guess_terminal_state_from_delete(capacity_case, monkeypatch):
    case = capacity_case
    state, record, _ = claimed_order(case, monkeypatch)
    apply_query(case, record)
    before, history = case["db"].get_record(case["key"]), case["db"].get_order_history(case["key"])
    assert case["trade"].cancel_order(record["stock_code"], "123456") is True
    assert case["db"].get_record(case["key"]) == before and case["db"].get_order_history(case["key"]) == history
    canceled = apply_query(case, record)
    assert canceled.status == "canceled" and canceled.filled == .02 and canceled.requested == .1
    after = case["db"].get_record(case["key"])
    assert after["current_qty"] == .02 and after["open_order_status"] == "canceled"
    assert [method for method, _ in state["requests"]] == ["GET", "DELETE", "GET"]
    assert len(case["created"]) == 3


def test_reduce_only_preparation_inherits_original_client_order_account_and_leg(capacity_case, monkeypatch):
    case = capacity_case
    state, record, original = claimed_order(case, monkeypatch)
    apply_query(case, record)
    opened = case["db"].get_record(case["key"])
    # Keep the real fixture's notional minimum; no new close-order exemption.
    amount, price, close = case["trade"].prepare_order(record["stock_code"], .02, 300, reduce_only=True, record=opened)
    assert amount == .02 and price == 300
    assert close["schema"] == "chan-ccxt-order-v3" and close["reduce_only"] is True
    assert close["execution"] == original["execution"] and close["account_context"] == original["account_context"]
    assert "monetary_basis_sha256" not in close  # Management is not a new monetary admission.
    assert [method for method, _ in state["requests"]] == ["GET"] and len(case["created"]) == 3


@pytest.mark.parametrize("field,value", [("orderId", 999999), ("clientOrderId", "not-the-original-client"),
    ("positionSide", "SHORT"), ("timeInForce", "GTX"), ("reduceOnly", True)])
def test_changed_native_cancel_response_cannot_report_success(single_case, monkeypatch, field, value):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    apply_query(case, record)
    before, history = case["db"].get_record(case["key"]), case["db"].get_order_history(case["key"])
    state["row"][field] = value
    with pytest.raises(CChanException):
        case["trade"].cancel_order(record["stock_code"], "123456")
    assert case["db"].get_record(case["key"]) == before and case["db"].get_order_history(case["key"]) == history
    assert [method for method, _ in state["requests"]] == ["GET", "DELETE"]


@pytest.mark.parametrize("damage", ["expired", "kill", "freeze"])
def test_existing_order_query_and_cancel_do_not_require_new_risk_admission(single_case, monkeypatch, damage):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    apply_query(case, record)
    if damage == "expired":
        case["clock"]["now"] += 2001
    elif damage == "kill":
        case["trade"].safety_policy.environ["CHANPY_KILL_SWITCH"] = "YES"
    else:
        case["db"].reconcile_account(account_context=case["before"]["payload"]["account_context"], before_id="0"*64,
                                     after_id="1"*64, wallet_ids=[], execution_scan_ids=[])
    assert case["trade"].query_order(record["stock_code"], "123456").filled == .02
    assert case["trade"].cancel_order(record["stock_code"], "123456") is True
    assert case["db"].get_record(case["key"])["open_order_status"] == "open"
    assert [method for method, _ in state["requests"]] == ["GET", "GET", "DELETE"]


@pytest.mark.parametrize("damage", ["positionSide", "timeInForce", "reduceOnly"])
def test_native_query_terms_remain_checked_before_any_ack_or_fill(single_case, monkeypatch, damage):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    state["row"][damage] = {"positionSide": "SHORT", "timeInForce": "GTX", "reduceOnly": True}[damage]
    before, history = case["db"].get_record(case["key"]), case["db"].get_order_history(case["key"])
    with pytest.raises(CChanException):
        case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert case["db"].get_record(case["key"]) == before and case["db"].get_order_history(case["key"]) == history


@pytest.mark.parametrize("replacement", ["database", "connection", "chan"])
def test_query_response_cannot_redirect_the_original_ack_to_a_replaced_database(single_case, monkeypatch, tmp_path, replacement):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    chan, database = case["db"], case["db"].db
    connection = database.conn
    before, history = chan.get_record(case["key"]), chan.get_order_history(case["key"])
    previous = case["client"].session.request
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"foreign-query-ack.db")})) as foreign:
        statements, touched = [], []
        foreign.db.conn.set_trace_callback(statements.append)
        def changed(method, url, **kwargs):
            response = previous(method, url, **kwargs)
            if urlsplit(url).path == "/fapi/v1/order" and not touched:
                touched.append(replacement)
                if replacement == "database":
                    chan.db = foreign.db
                elif replacement == "connection":
                    database.conn = foreign.db.conn
                else:
                    case["trade"].chan_db = foreign
            return response
        monkeypatch.setattr(case["client"].session, "request", changed)
        try:
            with pytest.raises(CChanException):
                case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
        finally:
            case["trade"].chan_db, chan.db, database.conn = chan, database, connection
        assert touched == [replacement]
        assert statements == [], "post-response ownership must be checked before any ACK SQL"
    assert chan.get_record(case["key"]) == before and chan.get_order_history(case["key"]) == history
    assert len(state["requests"]) == 1 and len(case["created"]) == 3


@pytest.mark.parametrize("raw", [None, "{", "[]"])
def test_invalid_stored_contract_stays_a_closed_domain_error_without_recovery_io(single_case, monkeypatch, raw):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    case["db"].db.execute(f"UPDATE {case['db'].table} SET open_order_contract=? WHERE id=?", (raw, case["key"]))
    with pytest.raises(CChanException):
        case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert state["requests"] == []


@pytest.mark.parametrize("name", ["_validated_persisted_intent", "_read_order_contract", "_fetch_persisted_order",
    "_result_from_ccxt", "query_order", "cancel_order", "place_order", "_assert_persisted_monetary_contract",
    "_monetary_consumer_owner"])
def test_monetary_preparation_fingerprints_the_actual_engine_consumers(single_case, monkeypatch, name):
    case = single_case
    install_last(case, monkeypatch)
    calls = []
    def replaced(self, *args, **kwargs):
        calls.append(name)
        pytest.fail("changed execution callable must not be invoked or certified")
    monkeypatch.setattr(case["trade"], name, types.MethodType(replaced, case["trade"]))
    before = case["db"].get_record(case["key"])
    with pytest.raises(CChanException):
        acquire(case)
    assert calls == [] and case["db"].get_record(case["key"]) == before and len(case["created"]) == 3


@pytest.mark.parametrize("replacement", ["database", "connection"])
def test_query_ack_stamp_cannot_escape_to_a_foreign_writer(single_case, monkeypatch, tmp_path, replacement):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    chan, database = case["db"], case["db"].db
    connection = database.conn
    before, history = chan.get_record(case["key"]), chan.get_order_history(case["key"])
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"foreign-ack-stamp.db")})) as foreign:
        statements, touched = [], []
        foreign.db.conn.set_trace_callback(statements.append)
        original = db_module.now_str
        def changed():
            result = original()
            if not touched:
                touched.append(replacement)
                if replacement == "database":
                    chan.db = foreign.db
                else:
                    database.conn = foreign.db.conn
            return result
        monkeypatch.setattr(db_module, "now_str", changed)
        try:
            with pytest.raises(CChanException):
                case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
        finally:
            chan.db, database.conn = database, connection
        assert touched == [replacement] and statements == []
    assert chan.get_record(case["key"]) == before and chan.get_order_history(case["key"]) == history
    assert len(state["requests"]) == 1


@pytest.mark.parametrize("damage", ["fake_hash", "caller_row", "unclaimed"])
def test_new_schema_or_hash_dto_cannot_replace_the_original_monetary_l2(single_case, monkeypatch, damage):
    case = single_case
    install_last(case, monkeypatch)
    state = install_recovery_transport(case, monkeypatch)
    assert acquire(case)
    if damage != "unclaimed":
        with case["db"].db.transaction():
            context = claim_context(case)
            assert case["db"].claim_order_submission(case["key"], "open", native_claim=context)
    record = case["db"].get_record(case["key"])
    contract = json.loads(record["open_order_contract"])
    if damage == "fake_hash":
        contract["monetary_basis_sha256"] = "0"*64
        from Trade.CCXTTradeEngine import _contract_id
        from CustomBuySellPoint.Decision import canonical_bytes
        contract["contract_id"] = _contract_id(contract)
        record["open_order_contract"] = canonical_bytes(contract).decode()
    elif damage == "caller_row":
        record["unwatch_reason"] = "not the original row"
    with pytest.raises(CChanException):
        case["trade"]._read_order_contract(record["stock_code"], {"phase": "open", "record": record})
    assert state["requests"] == []


def test_default_recovery_builds_a_new_sdk_from_native_instruments_without_renewing_admission(capacity_case, monkeypatch):
    case = capacity_case
    state, record, _ = claimed_order(case, monkeypatch)
    old = case["client"]
    previous, paths = old.session.request, []
    def cold_transport(session, method, url, **kwargs):
        assert session is not old.session
        paths.append(urlsplit(url).path)
        return previous(method, url, **kwargs)
    monkeypatch.setattr("requests.sessions.Session.request", cold_transport)
    case["trade"].exchange = None
    # This is existing-risk management, not a fresh prepare after a kill/TTL.
    case["clock"]["now"] += 3600_000
    case["trade"].safety_policy.environ["CHANPY_KILL_SWITCH"] = "YES"
    before = Transition.read_native_order_transition(case["db"], case["key"])
    result = case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert result.order_id == "123456" and result.filled == .02 and result.status == "open"
    fresh = case["trade"].exchange
    assert type(fresh) is type(old) and fresh is not old
    assert set(fresh.markets) == {"TEST/USDT:USDT", "ALT/USDT:USDT"}
    assert paths and set(paths) <= {"/fapi/v1/exchangeInfo", "/fapi/v3/balance", "/fapi/v1/order"}
    assert Transition.read_native_order_transition(case["db"], case["key"]) == before
    assert len(state["requests"]) == 1 and len(case["created"]) == 3


@pytest.mark.parametrize("damage", ["foreign_account", "record", "database", "connection"])
def test_cold_management_source_failures_cannot_publish_ack_or_use_foreign_sql(single_case, monkeypatch, tmp_path, damage):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    chan, database, connection = case["db"], case["db"].db, case["db"].db.conn
    previous = case["client"].session.request
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"foreign-cold-reader.db")})) as foreign:
        statements, touched = [], []
        foreign.db.conn.set_trace_callback(statements.append)
        def cold_transport(session, method, url, **kwargs):
            response = previous(method, url, **kwargs)
            path = urlsplit(url).path
            if damage == "foreign_account" and path == "/fapi/v3/balance":
                rows = json.loads(response.text)
                for row in rows:
                    row["accountAlias"] = "another-native-account"
                response._content = json.dumps(rows).encode()
                touched.append(damage)
            elif path == "/fapi/v1/exchangeInfo" and not touched and damage != "foreign_account":
                touched.append(damage)
                if damage == "record":
                    database.execute(f"UPDATE {chan.table} SET unwatch_reason='changed during native recovery' WHERE id=?", (case["key"],))
                elif damage == "database":
                    chan.db = foreign.db
                else:
                    database.conn = foreign.db.conn
            return response
        monkeypatch.setattr("requests.sessions.Session.request", cold_transport)
        case["trade"].exchange = None
        try:
            with pytest.raises(CChanException):
                case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
        finally:
            chan.db, database.conn = database, connection
        assert touched and statements == []
    assert state["requests"] == [] and case["trade"].exchange is None
    current = chan.get_record(case["key"])
    assert current["open_order_id"] is None and current["open_order_status"] == "submitting"
    assert len(chan.get_order_history(case["key"])["attempts"][0]["events"]) == 2


@pytest.mark.parametrize("name", ["place_order", "query_order", "cancel_order"])
def test_forged_wrapped_metadata_does_not_hide_a_different_executing_closure(single_case, monkeypatch, name):
    from functools import wraps
    case = single_case
    install_last(case, monkeypatch)
    original = getattr(case["trade"], name).__func__
    @wraps(original)
    def changed(self, *args, **kwargs):
        return original(self, *args, **kwargs)
    monkeypatch.setattr(case["trade"], name, types.MethodType(changed, case["trade"]))
    with pytest.raises(CChanException):
        acquire(case)
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("kind,name", [("cold", "initialize_native_order_recovery_client"), ("factory", "create_exchange"),
    ("writer", "_order_write"), ("writer", "claim_order_submission"), ("writer", "record_order_ack")])
def test_execution_dependency_replacement_is_rejected_before_any_mutated_callable(single_case, monkeypatch, kind, name):
    from Trade import NativePreparedClient
    from DataAPI import ccxt as data_module
    case = single_case
    install_last(case, monkeypatch)
    calls = []
    def replaced(*args, **kwargs):
        calls.append(name)
        pytest.fail("unverified loaded execution dependency was invoked")
    owner = NativePreparedClient if kind == "cold" else data_module if kind == "factory" else case["db"]
    monkeypatch.setattr(owner, name, replaced)
    with pytest.raises(CChanException):
        acquire(case)
    assert calls == []
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("operation", ["query", "cancel"])
def test_relabeling_a_native_projection_as_v3_cannot_bypass_its_original_lineage(single_case, monkeypatch, operation):
    from Trade.CCXTTradeEngine import _contract_id
    from CustomBuySellPoint.Decision import canonical_bytes
    case = single_case
    state, record, contract = claimed_order(case, monkeypatch)
    apply_query(case, record)
    changed = {key: value for key, value in contract.items() if key != "monetary_basis_sha256"}
    changed["schema"] = "chan-ccxt-order-v3"
    changed["contract_id"] = _contract_id(changed)
    chan = case["db"]
    chan.db.execute(f"UPDATE {chan.table} SET open_order_contract=? WHERE id=?", (canonical_bytes(changed).decode(), case["key"]))
    before = chan.get_record(case["key"])
    events = chan.db.query(f"SELECT * FROM {Transition.EVENTS} ORDER BY event_id")
    with pytest.raises(CChanException):
        if operation == "query":
            case["trade"].query_order(record["stock_code"], "123456")
        else:
            case["trade"].cancel_order(record["stock_code"], "123456")
    assert [method for method, _ in state["requests"]] == ["GET"], "the downgraded projection is not native I/O authority"
    assert chan.get_record(case["key"]) == before and chan.db.query(f"SELECT * FROM {Transition.EVENTS} ORDER BY event_id") == events


@pytest.mark.parametrize("damage", ["credential", "options", "market"])
def test_same_sdk_object_cannot_change_identity_between_response_and_ack(single_case, monkeypatch, damage):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    previous, touched = case["client"].session.request, []
    before, history = case["db"].get_record(case["key"]), case["db"].get_order_history(case["key"])
    def changed(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        if urlsplit(url).path == "/fapi/v1/order" and not touched:
            touched.append(damage)
            if damage == "credential":
                case["client"].secret = "fake-only-response-secret-change"
            elif damage == "options":
                case["client"].options["unobserved-recovery-option"] = True
            else:
                case["client"].markets[record["stock_code"]]["precision"]["price"] = .2
        return response
    monkeypatch.setattr(case["client"].session, "request", changed)
    with pytest.raises(CChanException):
        case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert touched == [damage]
    assert case["db"].get_record(case["key"]) == before and case["db"].get_order_history(case["key"]) == history
    assert len(state["requests"]) == 1


def test_native_reduce_only_flag_never_contradicts_the_frozen_monetary_candidate(capacity_case, monkeypatch):
    case = capacity_case
    state, record, contract = claimed_order(case, monkeypatch)
    assert contract["reduce_only"] is False
    state["row"]["reduceOnly"] = True
    before, history = case["db"].get_record(case["key"]), case["db"].get_order_history(case["key"])
    with pytest.raises(CChanException):
        case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert case["db"].get_record(case["key"]) == before and case["db"].get_order_history(case["key"]) == history
