"""Owned full intervals must reject invisible-in-net external round trips."""
import copy
import json
from decimal import Decimal
from urllib.parse import urlsplit, parse_qs

import pytest
import requests

from Common.ChanException import CChanException
from Trade import NativeManagement as Management
from Trade import NativeOrderTransition as Transition
from Trade.AccountRiskStore import _sha
from Trade.AccountRiskStore import read_check
from Trade.CCXTTradeEngine import CCCXTTradeEngine
from Trade.AccountIdentity import observe_account_context
from Trade.AccountSources import collect_wallet_scan
from Trade.ExecutionFacts import collect_execution_scan
from .test_execution_facts import fill
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import single_case, capacity_case
from .test_native_management_attempts import original_close_attempt
from .test_native_management_sources import management_case, source_options
from .test_native_management_role import configuration
from .test_native_account_sources import wallet_row
from .test_native_monetary_engine import apply_query


def interval_api():
    assert hasattr(Management, "collect_native_management_interval"), "owned original-interval management collection is missing"
    return Management.collect_native_management_interval


def complete_management_case(case, monkeypatch, *, cold=False, phase="open"):
    engine, state, record, contract = management_case(case, monkeypatch, cold=cold)
    row = fill("binance", state["row"]["time"], key=1200, quantity=".02", price="100", fee="0",
        side="buy" if record["is_buy"] else "sell", leg=record["position_side"])
    row["orderId"] = state["row"]["orderId"]
    case["execution_io"]["TESTUSDT"].rows.append(row)
    if phase == "close":
        record, contract = original_close_attempt(case, state, record)
        realized = Decimal(".005")*(Decimal("300")-Decimal("100"))*(1 if record["is_buy"] else -1)
        closed = fill("binance", state["row"]["time"], key=1201, quantity=".005", price="300", fee="0",
            side="sell" if record["is_buy"] else "buy", leg=record["position_side"])
        closed.update(orderId=789123, realizedPnl=str(realized))
        case["execution_io"]["TESTUSDT"].rows.append(closed)
        flow = wallet_row("binance", state["row"]["time"], key=1201, kind="REALIZED_PNL", amount=str(realized), instrument="TESTUSDT")
        flow["tradeId"] = "1201"
        case["wallet_io"].rows.append(flow)
        def cash_response(response, url):
            if urlsplit(url).path == "/fapi/v3/account":
                body = json.loads(response.content)
                for key in ("totalWalletBalance", "totalCrossWalletBalance", "totalMarginBalance"):
                    body[key] = str(Decimal(body[key])+realized)
                asset = next(row for row in body["assets"] if row["asset"] == "USDT")
                for key in ("walletBalance", "crossWalletBalance", "marginBalance"):
                    asset[key] = str(Decimal(asset[key])+realized)
                response._content = json.dumps(body).encode()
            return response
        # Cold management's class-level transport delegates to the original
        # bottom fake captured at construction; wrap that same HTTP boundary.
        if cold:
            assert engine.exchange is None
            class_previous = requests.sessions.Session.request
            def cold_cash(session, method, url, **kwargs):
                return cash_response(class_previous(session, method, url, **kwargs), url)
            monkeypatch.setattr("requests.sessions.Session.request", cold_cash)
        else:
            previous = case["client"].session.request
            def closed_cash(method, url, **kwargs):
                return cash_response(previous(method, url, **kwargs), url)
            monkeypatch.setattr(case["client"].session, "request", closed_cash)
    return engine, state, record, contract


def unchanged_database(case):
    db = case["db"]
    records = copy.deepcopy(db.db.query(f"SELECT * FROM {db.table} ORDER BY id"))
    return records, [db.get_order_history(record["id"]) for record in records], db.db.conn.total_changes


@pytest.mark.parametrize("cold", [False, True])
def test_full_interval_uses_original_root_endpoint_and_owned_raw_sources_without_permission(single_case, monkeypatch, cold):
    observe = interval_api()
    case = single_case
    engine, state, _, _ = complete_management_case(case, monkeypatch, cold=cold)
    original = unchanged_database(case)
    transition = Transition.read_native_order_transition(case["db"], case["key"])
    document = observe(engine, case["key"], phase="open", **source_options(case))
    assert document["schema"] == "chan-native-management-sources-v3" and document["payload_sha256"] == _sha(document["payload"])
    payload = document["payload"]
    interval = payload["interval"]
    assert interval["schema"] == "chan-native-management-interval-v1" and interval["payload_sha256"] == _sha(interval["payload"])
    p = interval["payload"]
    assert [row["span_role"] for row in p["monotonic_windows"]] == ["open_orders", "account", "execution", "execution", "wallet", "market"]
    assert p["check_id"] == transition["payload"]["root"]["boundary"]["payload"]["check_id"]
    assert p["before"]["payload"]["finished_ms"] < payload["pending"]["payload"]["started_ms"]
    assert payload["pending"]["payload"]["finished_ms"] < payload["account"]["payload"]["started_ms"]
    assert p["report"]["payload"]["status"] == "matched_observations" and p["report"]["payload"]["issues"] == []
    assert len(p["executions"]) == 2 and len(p["wallets"]) == 1
    for source in p["executions"]:
        assert source["receipt"]["payload"]["start_ms"] == p["before"]["payload"]["started_ms"]
        assert source["receipt"]["payload"]["end_ms"] == payload["account"]["payload"]["finished_ms"]+1
        assert source["account_context"] == payload["account_context"]
    assert payload["native_quantity_verified"] is payload["operation_authorized"] is False
    assert unchanged_database(case) == original and Transition.read_native_order_transition(case["db"], case["key"]) == transition
    assert all(method == "GET" for method, _ in state["requests"])


def test_same_native_net_position_cannot_hide_unowned_zero_net_execution_round_trip(single_case, monkeypatch):
    observe = interval_api()
    case = single_case
    engine, state, record, _ = complete_management_case(case, monkeypatch)
    clean = observe(engine, case["key"], phase="open", **source_options(case))
    original = unchanged_database(case)
    for index, side in enumerate(("buy", "sell"), 1):
        row = fill("binance", case["clock"]["now"]+index, key=1200+index, quantity=".01", price="100", fee="0",
            side=side, leg=record["position_side"])
        row["orderId"] = 9000+index
        case["execution_io"]["TESTUSDT"].rows.append(row)
    case["clock"]["now"] += 10
    diagnostic = Management.collect_native_management_sources(engine, case["key"], phase="open", **source_options(case))
    assert diagnostic["payload"]["quantity"]["payload"]["native_leg_quantity"] == clean["payload"]["quantity"]["payload"]["native_leg_quantity"]
    assert [(row["currency"], row["cash_balance"]) for row in diagnostic["payload"]["account"]["payload"]["assets"]] == [
        (row["currency"], row["cash_balance"]) for row in clean["payload"]["account"]["payload"]["assets"]]
    with pytest.raises(CChanException):
        observe(engine, case["key"], phase="open", **source_options(case))
    assert unchanged_database(case) == original


@pytest.mark.parametrize("phase", ["open", "close"])
def test_full_cold_interval_preserves_account_leg_cash_and_original_attempt_in_all_binance_modes(capacity_case, monkeypatch, phase):
    case = capacity_case
    engine, state, record, contract = complete_management_case(case, monkeypatch, cold=True, phase=phase)
    original, begin = unchanged_database(case), len(state["requests"])
    payload = interval_api()(engine, case["key"], phase=phase, **source_options(case))["payload"]
    assert payload["identity"]["payload"]["target"]["phase"] == phase
    assert payload["identity"]["payload"]["identity"]["position_side"] == record["position_side"]
    assert payload["account_context"] == contract["account_context"]
    assert payload["interval"]["payload"]["report"]["payload"]["issues"] == []
    assert payload["quantity"]["payload"]["local_remaining_quantity"] == ("0.02" if phase == "open" else "0.015")
    assert payload["native_quantity_verified"] is payload["operation_authorized"] is False
    assert unchanged_database(case) == original
    assert [method for method, _ in state["requests"]][begin:] == ["GET"]


def test_changed_execution_account_stops_before_the_first_raw_execution_endpoint(single_case, monkeypatch):
    case = single_case
    engine, _, _, _ = complete_management_case(case, monkeypatch)
    previous, state = engine.exchange.session.request, {"account": False, "balances": 0}
    def changed(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        path = urlsplit(url).path
        if path == "/fapi/v3/account":
            state["account"] = True
        elif path == "/fapi/v3/balance" and state["account"]:
            state["balances"] += 1
            if state["balances"] >= 2:
                rows = json.loads(response.content)
                for row in rows:
                    row["accountAlias"] = "foreign-Futures-B"
                response._content = json.dumps(rows).encode()
        return response
    monkeypatch.setattr(engine.exchange.session, "request", changed)
    original, begin = unchanged_database(case), len(case["http_calls"])
    with pytest.raises(CChanException):
        interval_api()(engine, case["key"], phase="open", **source_options(case))
    assert state["balances"] >= 2
    assert not any(name == "fapiPrivateGetUserTrades" for name, _ in case["http_calls"][begin:])
    assert unchanged_database(case) == original


def test_foreign_but_internally_consistent_account_snapshot_stops_before_execution_reads(single_case, monkeypatch):
    case = single_case
    engine, _, _, _ = complete_management_case(case, monkeypatch)
    previous, state = engine.exchange.session.request, {"pending": False, "balances": 0}
    def changed(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        path = urlsplit(url).path
        if path == "/fapi/v1/openAlgoOrders":
            state["pending"] = True
        elif path == "/fapi/v3/balance" and state["pending"]:
            state["balances"] += 1
            # Pending's closing identity, interval separator, then the two
            # account-snapshot identity endpoints. No SDK/collector override.
            if state["balances"] in {3, 4}:
                rows = json.loads(response.content)
                for row in rows:
                    row["accountAlias"] = "foreign-Futures-B"
                response._content = json.dumps(rows).encode()
        return response
    monkeypatch.setattr(engine.exchange.session, "request", changed)
    original, begin = unchanged_database(case), len(case["http_calls"])
    with pytest.raises(CChanException):
        interval_api()(engine, case["key"], phase="open", **source_options(case))
    assert state["balances"] >= 4
    assert not any(name == "fapiPrivateGetUserTrades" for name, _ in case["http_calls"][begin:])
    assert unchanged_database(case) == original


@pytest.mark.parametrize("module,name", [("Trade.AccountReconcile", name) for name in
    ("verify_account_context", "verify_account_snapshot", "verify_wallet_scan", "_order_ids", "build_execution_ownership")]
    +[("Trade.ExecutionReconcile", "verify_account_context"), ("Trade.ExecutionReconcile", "verify_execution_scan")]
    +[(module, name) for module, names in (
        ("Trade.AccountStore", ("verify_account_snapshot", "verify_wallet_scan", "validate_schema", "read_evidence")),
        ("Trade.ExecutionStore", ("verify_account_context", "verify_execution_fact", "verify_execution_scan", "validate_schema", "read_scan_with_account")),
        ("Trade.NativeCurrentComponents", ("_fail_sources", "_known_facts", "_latest")),
        ("Trade.NativeManagement", ("_known_management_interval_sources",)),
    ) for name in names])
def test_interval_runtime_pins_actual_readers_and_called_aliases_before_io(store, monkeypatch, module, name):
    engine = CCCXTTradeEngine(store[0], ccxt_conf=configuration(), trade_conf={}, environ={}, management_only=True)
    invoked = []
    def foreign(*args, **kwargs):
        invoked.append(1)
        raise AssertionError("foreign source checker must not execute")
    monkeypatch.setattr(module+"."+name, foreign)
    with pytest.raises(CChanException):
        Management._source_runtime(engine, include_interval=True)
    assert invoked == [] and engine.exchange is None


@pytest.mark.parametrize("damage", ["missing_fill", "wrong_price", "conflicting_duplicate"])
def test_incomplete_or_inconsistent_raw_fill_cannot_be_replaced_by_local_cumulative_quantity(single_case, monkeypatch, damage):
    case = single_case
    engine, _, _, _ = complete_management_case(case, monkeypatch)
    rows = case["execution_io"]["TESTUSDT"].rows
    added = next(row for row in rows if row["id"] == 1200)
    if damage == "missing_fill":
        rows.remove(added)
    elif damage == "wrong_price":
        added["price"] = "101"
    else:
        rows.append({**added, "price": "101"})
    original = unchanged_database(case)
    with pytest.raises(CChanException):
        interval_api()(engine, case["key"], phase="open", **source_options(case))
    assert unchanged_database(case) == original


@pytest.mark.parametrize("field", ["before_id", "check_id", "executions", "checked_ms"])
def test_complete_interval_entry_never_accepts_a_caller_baseline_receipt_or_clock(store, field):
    engine = CCCXTTradeEngine(store[0], ccxt_conf=configuration(), trade_conf={}, environ={}, management_only=True)
    with pytest.raises(TypeError):
        interval_api()(engine, 1, phase="open", policy={}, instrument_max_age_ms=2000,
            instrument_max_observation_span_ms=2000, order_max_age_ms=2000, order_max_observation_span_ms=2000, **{field: {}})
    assert engine.exchange is None


@pytest.mark.parametrize("role", ["wallet", "execution"])
def test_full_interval_source_age_is_checked_after_the_last_market_callback(single_case, monkeypatch, role):
    case = single_case
    engine, _, _, _ = complete_management_case(case, monkeypatch)
    previous, books = engine.exchange.session.request, []
    def delayed(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        if urlsplit(url).path == "/fapi/v1/ticker/bookTicker":
            books.append(url)
            if len(books) == 2:
                case["clock"]["now"] += 51
        return response
    monkeypatch.setattr(engine.exchange.session, "request", delayed)
    options = copy.deepcopy(source_options(case))
    options["policy"]["max_age_ms"][role] = 50
    original = unchanged_database(case)
    with pytest.raises(CChanException):
        interval_api()(engine, case["key"], phase="open", **options)
    assert len(books) == 2 and unchanged_database(case) == original


def test_a_late_change_to_another_original_record_invalidates_the_full_ledger_not_only_the_target(single_case, monkeypatch):
    case = single_case
    engine, _, _, _ = complete_management_case(case, monkeypatch)
    db = case["db"]
    other = next(row for row in db.db.query(f"SELECT * FROM {db.table} ORDER BY id") if row["id"] != case["key"])
    previous, books = engine.exchange.session.request, []
    def changed(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        if urlsplit(url).path == "/fapi/v1/ticker/bookTicker":
            books.append(url)
            if len(books) == 2:
                db.db.execute(f"UPDATE {db.table} SET current_qty=999 WHERE id=?", (other["id"],))
        return response
    monkeypatch.setattr(engine.exchange.session, "request", changed)
    target, changes = db.get_record(case["key"]), db.db.conn.total_changes
    with pytest.raises(CChanException):
        interval_api()(engine, case["key"], phase="open", **source_options(case))
    assert len(books) == 2 and db.get_record(case["key"]) == target
    assert db.db.query_one(f"SELECT current_qty FROM {db.table} WHERE id=?", (other["id"],))["current_qty"] == 999
    assert db.db.conn.total_changes == changes+1  # Only the deliberate raw fixture mutation.


def test_zero_new_risk_available_balance_does_not_block_reading_the_proven_original_remaining_position(single_case, monkeypatch):
    case = single_case
    engine, state, record, _ = complete_management_case(case, monkeypatch)
    assert case["trade"].cancel_order(record["stock_code"], "123456") is True
    apply_query(case, record)
    raw = case["account_raw"]
    raw["availableBalance"] = "0"
    next(row for row in raw["assets"] if row["asset"] == "USDT")["availableBalance"] = "0"
    payload = interval_api()(engine, case["key"], phase="open", **source_options(case))["payload"]
    assert payload["interval"]["payload"]["report"]["payload"]["issues"] == []
    assert payload["quantity"]["payload"]["observed_available_base_quantity"] == "0.02"
    assert payload["native_quantity_verified"] is payload["operation_authorized"] is False
    assert case["db"].get_record(case["key"])["current_qty"] == .02


@pytest.mark.parametrize("role", ["wallet", "execution"])
@pytest.mark.parametrize("budget", ["age", "span"])
def test_individual_source_monotonic_budget_cannot_hide_inside_a_wider_total_window(single_case, monkeypatch, role, budget):
    case = single_case
    engine, _, _, _ = complete_management_case(case, monkeypatch)
    previous, elapsed, seen = engine.exchange.session.request, [0], {"books": 0, "hit": False}
    monkeypatch.setattr(Management, "_monotonic_ns", lambda: elapsed[0])
    def delayed(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        parsed = urlsplit(url)
        if parsed.path == "/fapi/v1/ticker/bookTicker":
            seen["books"] += 1
        age_hit = budget == "age" and parsed.path == "/fapi/v1/ticker/bookTicker" and seen["books"] == 2
        span_hit = budget == "span" and ((role == "execution" and parsed.path == "/fapi/v1/userTrades")
            or (role == "wallet" and parsed.path == "/fapi/v1/income" and "incomeType" not in parse_qs(parsed.query)))
        if not seen["hit"] and (age_hit or span_hit):
            elapsed[0] += 51_000_000
            seen["hit"] = True
        return response
    monkeypatch.setattr(engine.exchange.session, "request", delayed)
    options = copy.deepcopy(source_options(case))
    options["policy"]["max_age_ms" if budget == "age" else "max_observation_span_ms"][role] = 50
    original = unchanged_database(case)
    with pytest.raises(CChanException):
        interval_api()(engine, case["key"], phase="open", **options)
    assert seen["hit"] and unchanged_database(case) == original


@pytest.mark.parametrize("channel", ["execution", "wallet"])
def test_new_owned_interval_cannot_erase_known_zero_net_native_facts(single_case, monkeypatch, channel):
    case = single_case
    engine, _, record, _ = complete_management_case(case, monkeypatch)
    root = Transition.read_native_order_transition(case["db"], case["key"])["payload"]["root"]
    before = read_check(case["db"].db, root["boundary"]["payload"]["check_id"])["payload"]["inputs"]["after"]
    at = case["clock"]["now"]
    if channel == "execution":
        for index, side in enumerate(("buy", "sell"), 1):
            row = fill("binance", at+index, key=3100+index, quantity=".01", price="100", fee="0", side=side, leg=record["position_side"])
            row["orderId"] = 9100+index
            case["execution_io"]["TESTUSDT"].rows.append(row)
    else:
        for index, amount in enumerate(("25", "-25"), 1):
            case["wallet_io"].rows.append(wallet_row("binance", at+index, key=3100+index, kind="TRANSFER", amount=amount))
    case["clock"]["now"] += 10
    if channel == "execution":
        started = case["clock"]["now"]
        first = observe_account_context(case["client"], engine.mode)
        receipt = collect_execution_scan(case["client"], engine._market_contract(record["stock_code"])[0],
            account_scope="known-native-facts", mode=engine.mode, start_ms=before["payload"]["started_ms"], end_ms=at+10)
        last = observe_account_context(case["client"], engine.mode)
        case["db"].store_execution_scan(receipt, account_observation={"before": first, "after": last,
            "started_ms": started, "finished_ms": case["clock"]["now"]})
        rows = case["execution_io"]["TESTUSDT"].rows
        rows[:] = [row for row in rows if row["id"] not in {3101, 3102}]
    else:
        receipt = collect_wallet_scan(case["client"], mode=engine.mode, start_ms=before["payload"]["started_ms"], end_ms=at+10)
        case["db"].store_account_evidence(receipt)
        rows = case["wallet_io"].rows
        rows[:] = [row for row in rows if row["tranId"] not in {3101, 3102}]
    assert len([fact for fact in receipt["payload"]["facts"] if fact["source_id"] in {"3101", "3102", "TRANSFER:3101", "TRANSFER:3102"}]) == 2
    original = unchanged_database(case)
    with pytest.raises(CChanException):
        interval_api()(engine, case["key"], phase="open", **source_options(case))
    assert unchanged_database(case) == original


def test_an_unbound_same_venue_scan_is_not_assumed_to_belong_to_another_account(single_case, monkeypatch):
    case = single_case
    engine, _, record, _ = complete_management_case(case, monkeypatch)
    root = Transition.read_native_order_transition(case["db"], case["key"])["payload"]["root"]
    before = read_check(case["db"].db, root["boundary"]["payload"]["check_id"])["payload"]["inputs"]["after"]
    receipt = collect_execution_scan(case["client"], engine._market_contract(record["stock_code"])[0],
        account_scope="namespace-is-not-native-uid", mode=engine.mode, start_ms=before["payload"]["started_ms"], end_ms=case["clock"]["now"])
    case["db"].store_execution_scan(receipt)
    original = unchanged_database(case)
    with pytest.raises(CChanException):
        interval_api()(engine, case["key"], phase="open", **source_options(case))
    assert unchanged_database(case) == original


def test_known_sources_published_during_the_last_market_read_are_not_adopted_by_an_earlier_interval(single_case, monkeypatch):
    case = single_case
    engine, _, _, _ = complete_management_case(case, monkeypatch)
    root = Transition.read_native_order_transition(case["db"], case["key"])["payload"]["root"]
    before = read_check(case["db"].db, root["boundary"]["payload"]["check_id"])["payload"]["inputs"]["after"]
    previous, books, evidence = engine.exchange.session.request, [], []
    def changed(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        if urlsplit(url).path == "/fapi/v1/ticker/bookTicker":
            books.append(url)
            if len(books) == 2:
                receipt = collect_wallet_scan(case["client"], mode=engine.mode,
                    start_ms=before["payload"]["started_ms"], end_ms=case["clock"]["now"])
                evidence.append(case["db"].store_account_evidence(receipt))
        return response
    monkeypatch.setattr(engine.exchange.session, "request", changed)
    original, changes = case["db"].get_record(case["key"]), case["db"].db.conn.total_changes
    with pytest.raises(CChanException):
        interval_api()(engine, case["key"], phase="open", **source_options(case))
    assert len(books) == 2 and len(evidence) == 1
    assert case["db"].get_account_evidence(evidence[0])["payload"]["facts"] == []
    assert case["db"].get_record(case["key"]) == original and case["db"].db.conn.total_changes == changes+1
