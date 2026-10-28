"""Original query evidence survives in the original journal, not a permit."""
import copy
import json
import sys
from contextlib import closing
from decimal import Decimal
from urllib.parse import urlsplit

import pytest

from Common.ChanException import CChanException
from Trade.AccountRiskStore import _sha
from Trade.db_util import CChanDB
from Trade.NativeAccountReconcile import observe_native_account_components
from Trade.NativePendingOwnership import observe_native_pending_ownership
from Trade.NativePendingOrders import collect_native_pending_orders
from Trade import NativeOrderTransition as Transition
from Trade import NativeCurrentComponents as Current
from Trade import OrderAudit as Audit
from CustomBuySellPoint.Decision import canonical_bytes
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import single_case, capacity_case
from .test_native_monetary_engine import claimed_order
from .test_native_monetary_consumers import component_sources
from .test_execution_facts import fill
from .test_native_account_sources import wallet_row


def test_original_query_persists_native_terminal_evidence_without_applying_or_releasing(single_case, monkeypatch):
    case = single_case
    state, record, contract = claimed_order(case, monkeypatch)
    state["row"]["status"] = "CANCELED"
    claim = Transition.read_native_order_transition(case["db"], case["key"])
    result = case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert result.status == "canceled" and result.filled == .02
    history = case["db"].get_order_history(case["key"])
    assert history["schema"] == "chan-order-history-v2"
    assert history["coverage"] == "intents_applied_reports_and_native_query_observations"
    observations = [event for event in history["attempts"][0]["events"]
                    if event["kind"] == "native_terminal_observation"]
    assert len(observations) == 1, "the real native query terminal source is missing from the original journal"
    evidence = observations[0]["native_order_observation"]
    assert evidence["schema"] == "chan-native-order-terminal-observation-v1"
    payload = evidence["payload"]
    expected_raw = copy.deepcopy(state["row"])
    expected_raw.pop("private_note")
    assert payload["raw"] == expected_raw
    assert "PRIVATE_" not in str(evidence)
    assert payload["account_context"] == contract["account_context"]
    assert payload["contract_id"] == contract["contract_id"]
    assert payload["requested_base_quantity"] == "0.1" and payload["filled_base_quantity"] == "0.02"
    assert payload["status"] == "canceled" and payload["average_price"] == "100"
    assert payload["economics_complete"] is payload["native_admission_verified"] is False
    assert case["db"].get_record(case["key"])["open_order_status"] == "submitting"
    assert case["db"].get_record(case["key"])["current_qty"] == 0
    assert Transition.read_native_order_transition(case["db"], case["key"]) == claim
    assert [method for method, _ in state["requests"]] == ["GET"]


def test_complete_original_account_interval_can_observe_a_native_zero_fill_terminal(single_case, monkeypatch):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    state["row"].update(status="CANCELED", executedQty="0", avgPrice="0", cumQuote="0")
    result = case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    case["db"].apply_open_fill(case["key"], result.filled, result.avg_price, result.status,
        client_order_id=result.client_order_id, order_id=result.order_id, expected_attempt=1)
    params, request = component_sources(case)
    report = observe_native_account_components(case["db"], **params)
    assert report["payload"]["status"] == "matched_components", report["payload"]["issues"]
    assert report["schema"] == "chan-native-account-components-v3"
    pending = report["payload"]["pending"]
    assert pending["schema"] == "chan-native-pending-ownership-v3"
    assert not [row for row in pending["payload"]["reservations"] if row["attempt"]["record_id"] == case["key"]]
    assert len(pending["payload"]["terminal_observations"]) == 1
    check = case["db"].reconcile_native_account(**request)
    assert check["schema"] == "chan-native-account-check-v3"
    assert check["payload"]["report"]["payload"]["status"] == "matched_observations"
    assert case["db"].get_account_risk_state(request["account_context"])["frozen"] is False
    assert report["payload"]["native_admission_verified"] is False


def test_original_current_reader_rebuilds_a_complete_native_terminal_check(single_case, monkeypatch):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    claim = Transition.read_native_order_transition(case["db"], case["key"])
    market = claim["payload"]["root"]["preparation"]["components"]["payload"]["market_evidence"]
    state["row"].update(status="CANCELED", executedQty="0", avgPrice="0", cumQuote="0")
    result = case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    case["db"].apply_open_fill(case["key"], result.filled, result.avg_price, result.status,
        client_order_id=result.client_order_id, order_id=result.order_id, expected_attempt=1)
    _, request = component_sources(case)
    check = case["db"].reconcile_native_account(**request)
    with case["db"].db.transaction():
        actual = Current._sources_snapshot(case["db"], request["account_context"], _sha(check), market)
    assert actual["check"] == check
    assert actual["check"]["schema"] == "chan-native-account-check-v3"


def test_original_terminal_source_failure_rolls_back_the_ack_without_private_sql_leak(single_case, monkeypatch):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    state["row"]["status"] = "CANCELED"
    before, history = case["db"].get_record(case["key"]), case["db"].get_order_history(case["key"])
    case["db"].db.execute(f"CREATE TRIGGER fail_native_terminal BEFORE INSERT ON {Audit.EVENTS} "
        "WHEN NEW.kind='native_terminal_observation' BEGIN SELECT RAISE(ABORT,'PRIVATE_SOURCE_WRITE_FAILURE'); END")
    with pytest.raises(CChanException) as error:
        case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert "PRIVATE_" not in str(error.value)
    assert case["db"].get_record(case["key"]) == before and case["db"].get_order_history(case["key"]) == history
    assert not case["db"].db.conn.in_transaction


def test_terminal_history_rebuild_checks_original_bytes_and_all_derived_fields(single_case, monkeypatch, store):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    state["row"]["status"] = "CANCELED"
    case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    expected = case["db"].get_order_history(case["key"])
    with closing(CChanDB(db_conf=store[1])) as restarted:
        assert restarted.get_order_history(case["key"]) == expected
    row = case["db"].db.query_one(f"SELECT * FROM {Audit.EVENTS} WHERE kind='native_terminal_observation'")
    original = json.loads(row["payload"])
    for damage in ("shape", "missing_field", "quantity", "account", "contract", "window", "raw_id", "source"):
        changed = copy.deepcopy(original)
        source = changed["native_order_observation"]
        value = source["payload"]
        if damage == "shape":
            changed["native_order_observation"] = []
        elif damage == "missing_field":
            del value["raw"]
        elif damage == "quantity":
            value["filled_base_quantity"] = "0.03"
        elif damage == "account":
            value["account_context"]["identifier_sha256"] = "f"*64
        elif damage == "contract":
            value["contract_id"] = "f"*64
        elif damage == "window":
            value["finished_ms"] = changed["observed_ms"]+1
        elif damage == "raw_id":
            value["raw"]["orderId"] = 789
        else:
            value["source"] = "caller_asserted_terminal"
        if isinstance(changed["native_order_observation"], dict):
            source["payload_sha256"] = _sha(value)
        data_sha = _sha({"state": changed["state"], "native_order_observation": changed["native_order_observation"]})
        case["db"].db.execute(f"DROP TRIGGER {Audit.EVENTS}_no_update")
        case["db"].db.execute(f"UPDATE {Audit.EVENTS} SET payload=?,payload_sha256=?,data_sha256=? WHERE event_id=?",
            (canonical_bytes(changed).decode(), _sha(changed), data_sha, row["event_id"]))
        case["db"].db.execute(Audit.SCHEMA[f"{Audit.EVENTS}_no_update"])
        with pytest.raises(CChanException):
            case["db"].get_order_history(case["key"])
        case["db"].db.execute(f"DROP TRIGGER {Audit.EVENTS}_no_update")
        case["db"].db.execute(f"UPDATE {Audit.EVENTS} SET payload=?,payload_sha256=?,data_sha256=? WHERE event_id=?",
            (row["payload"], row["payload_sha256"], row["data_sha256"], row["event_id"]))
        case["db"].db.execute(Audit.SCHEMA[f"{Audit.EVENTS}_no_update"])
    assert case["db"].get_order_history(case["key"]) == expected


def apply_native_filled_account_rows(case, state, record, *, native_status="CANCELED", quantity="0.02",
                                     reported_average="100", maker=False):
    """Update only existing fake venue rows, never the live transport owner."""
    case["clock"]["now"] += 1
    at = case["clock"]["now"]
    quantity = Decimal(quantity)
    fee = quantity*Decimal("100")*Decimal("0.0002" if maker else "0.0004")
    state["row"].update(status=native_status, executedQty=str(quantity), avgPrice=reported_average,
        cumQuote=str(quantity*Decimal(reported_average)), updateTime=at)
    fact = fill("binance", at, key=202, quantity=str(quantity), price="100", fee=str(fee),
        side="buy" if record["is_buy"] else "sell", leg=record["position_side"])
    fact["orderId"] = 123456
    fact["maker"] = maker
    case["execution_io"][case["units"][0]["id"]].rows.append(fact)
    cash = wallet_row("binance", at, key=202, kind="COMMISSION", amount=str(-fee), instrument=case["units"][0]["id"])
    cash["tradeId"] = "202"
    case["wallet_io"].rows.append(cash)
    account = case["account_raw"]
    wallet, unrealized = Decimal("1000.169")-fee, (Decimal("0.04")+quantity)*20
    equity = wallet+unrealized
    account.update(totalWalletBalance=str(wallet), totalCrossWalletBalance=str(wallet), totalUnrealizedProfit=str(unrealized),
        totalCrossUnPnl=str(unrealized), totalMarginBalance=str(equity), availableBalance=str(equity-12))
    account["assets"][0].update(walletBalance=str(wallet), crossWalletBalance=str(wallet), unrealizedProfit=str(unrealized),
        crossUnPnl=str(unrealized), marginBalance=str(equity), availableBalance=str(equity-12))
    signed = (Decimal("0.04")+quantity)*(1 if record["is_buy"] else -1)
    mark = Decimal("120" if record["is_buy"] else "80")
    native_position = next(row for row in account["positions"] if row["symbol"] == case["units"][0]["id"])
    native_position.update(positionAmt=str(signed), unrealizedProfit=str(unrealized), notional=str(signed*mark), updateTime=at)
    return {"positionAmt": str(signed), "unRealizedProfit": str(unrealized), "notional": str(signed*mark), "updateTime": at}


def set_native_filled_account(case, monkeypatch, state, record, *, native_status="CANCELED", quantity="0.02",
                              reported_average="100", maker=False):
    risk_fields = apply_native_filled_account_rows(case, state, record, native_status=native_status,
        quantity=quantity, reported_average=reported_average, maker=maker)
    previous = case["client"].session.request
    def updated_risk(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        if urlsplit(url).path == "/fapi/v3/positionRisk":
            rows = json.loads(response.text)
            native = next(row for row in rows if row["symbol"] == case["units"][0]["id"])
            native.update(risk_fields)
            response._content = json.dumps(rows).encode()
        return response
    monkeypatch.setattr(case["client"].session, "request", updated_risk)


def apply_observed_native_fill(case, monkeypatch, *, native_status="CANCELED", quantity="0.02", reported_average="100"):
    state, record, _ = claimed_order(case, monkeypatch)
    set_native_filled_account(case, monkeypatch, state, record,
        native_status=native_status, quantity=quantity, reported_average=reported_average)
    result = case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    case["db"].apply_open_fill(case["key"], result.filled, result.avg_price, result.status,
        client_order_id=result.client_order_id, order_id=result.order_id, expected_attempt=1)
    return component_sources(case)


@pytest.mark.parametrize("status,quantity", [("CANCELED", "0.02"), ("FILLED", "0.1")])
def test_real_nonempty_account_terminal_closes_exact_fills_fee_funding_and_native_positions(capacity_case, monkeypatch, status, quantity):
    case = capacity_case
    params, request = apply_observed_native_fill(case, monkeypatch, native_status=status, quantity=quantity)
    report = observe_native_account_components(case["db"], **params)
    assert report["payload"]["status"] == "matched_components", report["payload"]["issues"]
    assert report["schema"] == "chan-native-account-components-v3"
    assert len(report["payload"]["pending"]["payload"]["terminal_observations"]) == 1
    assert case["db"].get_record(case["key"])["current_qty"] == float(quantity)
    check = case["db"].reconcile_native_account(**request)
    assert check["schema"] == "chan-native-account-check-v3"
    assert check["payload"]["report"]["payload"]["status"] == "matched_observations"
    assert case["db"].get_account_risk_state(request["account_context"])["frozen"] is False


def test_observed_terminal_never_replaces_missing_execution_cash_evidence_or_resets_a_freeze(single_case, monkeypatch):
    case = single_case
    params, request = apply_observed_native_fill(case, monkeypatch)
    for key, reason in (("execution_scan_ids", "execution_window_missing"), ("wallet_ids", "wallet_window_missing")):
        report = observe_native_account_components(case["db"], **{**params, key: []})
        assert report["payload"]["status"] == "incomplete"
        assert any(issue["reason"] == reason for issue in report["payload"]["issues"])
    failed = case["db"].reconcile_native_account(**{**request, "execution_scan_ids": []})
    assert failed["payload"]["report"]["payload"]["status"] == "incomplete"
    matched = case["db"].reconcile_native_account(**request)
    assert matched["payload"]["report"]["payload"]["status"] == "matched_observations"
    assert case["db"].get_account_risk_state(request["account_context"])["frozen"] is True


@pytest.mark.parametrize("replacement", ["database", "connection"])
def test_terminal_stamp_cannot_redirect_any_native_source_insert(single_case, monkeypatch, tmp_path, replacement):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    state["row"]["status"] = "CANCELED"
    chan, backend = case["db"], case["db"].db
    connection = backend.conn
    before, history = chan.get_record(case["key"]), chan.get_order_history(case["key"])
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"foreign-terminal.db")})) as foreign:
        foreign_sql, local_after_stamp, touched = [], [], []
        foreign.db.conn.set_trace_callback(foreign_sql.append)
        connection.set_trace_callback(lambda sql: local_after_stamp.append(sql) if touched else None)
        clock = Audit.utc_now_ms
        def changed_clock():
            frame = sys._getframe(1)
            if frame.f_code.co_name == "_append" and frame.f_locals.get("kind") == "native_terminal_observation" and not touched:
                touched.append(replacement)
                if replacement == "database":
                    chan.db = foreign.db
                else:
                    backend.conn = foreign.db.conn
            return clock()
        monkeypatch.setattr(Audit, "utc_now_ms", changed_clock)
        try:
            with pytest.raises(CChanException):
                case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
        finally:
            chan.db, backend.conn = backend, connection
            connection.set_trace_callback(None)
        assert touched == [replacement]
        assert foreign_sql == [], "the original stamp must not redirect INSERT or rollback to a foreign connection"
        assert not any(sql.lstrip().upper().startswith("INSERT") for sql in local_after_stamp)
    assert chan.get_record(case["key"]) == before and chan.get_order_history(case["key"]) == history


def test_latest_native_cumulative_source_is_not_dropped_when_local_state_is_unchanged(single_case, monkeypatch):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    state["row"]["status"] = "CANCELED"
    first = case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    case["clock"]["now"] += 1
    state["row"].update(executedQty="0.03", cumQuote="3", updateTime=case["clock"]["now"])
    second = case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert first.filled == .02 and second.filled == .03
    history = case["db"].get_order_history(case["key"])
    observations = [event for event in history["attempts"][0]["events"] if event["kind"] == "native_terminal_observation"]
    assert len(observations) == 2
    assert observations[0]["state"] == observations[1]["state"]
    case["db"].apply_open_fill(case["key"], first.filled, first.avg_price, first.status,
        client_order_id=first.client_order_id, order_id=first.order_id, expected_attempt=1)
    pending = collect_native_pending_orders(case["client"], case["units"], mode=case["trade"].mode)
    report = observe_native_pending_ownership(case["db"], pending_orders=pending)
    assert any(row["attempt"]["record_id"] == case["key"] for row in report["payload"]["reservations"])
    assert any(row["reason"] == "client_terminal_not_observed" and row["attempt"]["record_id"] == case["key"]
               for row in report["payload"]["issues"])


def test_public_query_and_original_ack_accept_no_caller_terminal_proof_or_clock(single_case):
    case = single_case
    calls, changes = copy.deepcopy(case["http_calls"]), case["db"].db.conn.total_changes
    for key in ("native_order_observation", "raw", "passed", "observed_ms"):
        with pytest.raises(TypeError):
            case["trade"].query_order(case["units"][0]["symbol"], client_order_id="caller-proof", **{key: {"passed": True}})
        with pytest.raises(TypeError):
            case["db"].record_order_ack(case["key"], "open", "123456", **{key: {"passed": True}})
    assert case["http_calls"] == calls and case["db"].db.conn.total_changes == changes


def test_original_native_query_failure_does_not_publish_or_leak_private_server_body(single_case, monkeypatch):
    case = single_case
    _, record, _ = claimed_order(case, monkeypatch)
    before, history = case["db"].get_record(case["key"]), case["db"].get_order_history(case["key"])
    previous = case["client"].session.request
    def unavailable(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        if urlsplit(url).path == "/fapi/v1/order":
            response.status_code, response.reason = 400, "Bad Request"
            response._content = json.dumps({"code": -1000, "msg": "PRIVATE_NATIVE_QUERY_RESPONSE_BODY"}).encode()
        return response
    monkeypatch.setattr(case["client"].session, "request", unavailable)
    with pytest.raises(CChanException) as error:
        case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert "PRIVATE_" not in str(error.value)
    assert case["db"].get_record(case["key"]) == before and case["db"].get_order_history(case["key"]) == history


@pytest.mark.parametrize("damage", ["bool", "float", "backward", "future"])
def test_native_terminal_stamp_is_typed_and_valid_before_any_ack_commits(single_case, monkeypatch, damage):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    state["row"]["status"] = "CANCELED"
    before, history = case["db"].get_record(case["key"]), case["db"].get_order_history(case["key"])
    clock = Audit.utc_now_ms
    def invalid_stamp():
        frame = sys._getframe(1)
        now = clock()
        if frame.f_code.co_name == "_append" and frame.f_locals.get("kind") == "native_terminal_observation":
            return {"bool": True, "float": float(now), "backward": now-2000, "future": now+2000}[damage]
        return now
    monkeypatch.setattr(Audit, "utc_now_ms", invalid_stamp)
    with pytest.raises(CChanException):
        case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert case["db"].get_record(case["key"]) == before and case["db"].get_order_history(case["key"]) == history
    assert not case["db"].db.conn.in_transaction


@pytest.mark.parametrize("field,value", [("avgPrice", "99"), ("cumQuote", "3")])
def test_native_terminal_cumulative_average_and_quote_must_agree_before_publication(single_case, monkeypatch, field, value):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    state["row"]["status"] = "CANCELED"
    state["row"][field] = value
    before, history = case["db"].get_record(case["key"]), case["db"].get_order_history(case["key"])
    with pytest.raises(CChanException):
        case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert case["db"].get_record(case["key"]) == before and case["db"].get_order_history(case["key"]) == history


def test_coherent_native_order_average_cannot_contradict_all_of_its_observed_fills(single_case, monkeypatch):
    case = single_case
    params, request = apply_observed_native_fill(case, monkeypatch, reported_average="99")
    report = observe_native_account_components(case["db"], **params)
    assert report["payload"]["status"] == "mismatch", report["payload"]["issues"]
    assert any(issue["reason"] == "native_terminal_notional_difference" for issue in report["payload"]["issues"])
    check = case["db"].reconcile_native_account(**request)
    assert check["payload"]["report"]["payload"]["status"] == "mismatch"
    assert case["db"].get_account_risk_state(request["account_context"])["frozen"] is True


def submission_values(**changes):
    return {"order_id": "123456", "client_order_id": "owned-entry", "requested": .1,
            "filled": .1, "avg_price": 100, "status": "closed", **changes}


def test_sdk_submission_report_normalizes_only_the_six_known_fields():
    values = submission_values()
    before = copy.deepcopy(values)
    assert Audit._sdk_submission_report(values) == {"order_id": "123456", "client_order_id": "owned-entry",
        "requested": "0.1", "filled": "0.1", "avg_price": "100", "status": "closed"}
    assert values == before


@pytest.mark.parametrize("changes", [
    {"order_id": True}, {"client_order_id": None}, {"requested": True}, {"requested": 0},
    {"filled": -.01}, {"filled": .2}, {"filled": 0}, {"avg_price": None},
    {"avg_price": float("nan")}, {"status": "unknown"}, {"private_note": "not-a-report-field"},
])
def test_sdk_submission_report_rejects_invalid_or_extra_fields(changes):
    with pytest.raises(CChanException):
        Audit._sdk_submission_report(submission_values(**changes))


@pytest.mark.parametrize("known,observed", [
    ({}, {}),
    ({"status": "open", "filled": 0, "avg_price": None}, {"status": "open", "filled": 0, "avg_price": None}),
    ({"status": "open", "filled": .02}, {"filled": .1, "avg_price": 101}),
])
def test_sdk_submission_guard_allows_equal_terminal_or_progressing_open_reports(known, observed):
    report = Audit._sdk_submission_report(submission_values(**known))
    attempt = {"events": [{"kind": "sdk_submission_report", "submission_report": report}]}
    assert Audit._assert_sdk_submission(attempt, submission_values(**observed)) is None


@pytest.mark.parametrize("known,observed", [
    ({}, {"order_id": "654321"}), ({}, {"client_order_id": "different"}),
    ({}, {"requested": .2, "filled": .2}), ({}, {"avg_price": 99}),
    ({}, {"status": "canceled"}), ({}, {"status": "open", "filled": 0, "avg_price": None}),
    ({"status": "open", "filled": .02}, {"status": "open", "filled": .01}),
    ({"status": "open", "filled": .02}, {"status": "open", "filled": .02, "avg_price": 99}),
])
def test_sdk_submission_guard_rejects_terminal_changes_or_known_fill_regression(known, observed):
    report = Audit._sdk_submission_report(submission_values(**known))
    attempt = {"events": [{"kind": "sdk_submission_report", "submission_report": report}]}
    with pytest.raises(CChanException):
        Audit._assert_sdk_submission(attempt, submission_values(**observed))


def test_sdk_submission_guard_rejects_multiple_reports_for_one_send_attempt():
    report = Audit._sdk_submission_report(submission_values())
    event = {"kind": "sdk_submission_report", "submission_report": report}
    with pytest.raises(CChanException):
        Audit._assert_sdk_submission({"events": [event, copy.deepcopy(event)]}, submission_values())
