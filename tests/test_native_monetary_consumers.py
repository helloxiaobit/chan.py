"""Original monetary roots in real original consumers; bottom-only fake I/O."""
import copy
import hashlib
import json
import subprocess
import sys
from contextlib import closing

import pytest

from Common.ChanException import CChanException
from Trade import NativePendingOrders as Pending
from Trade import NativePendingOwnership as Ownership
from Trade.NativeOrderTransition import read_native_order_transition
from Trade import NativeOrderTransition as Transition
from Trade import NativePreparedIntent as Prepared
from Trade import NativeCapacityEvidence as Capacity
from Trade import NativeInstrumentEvidence as Instrument
from Trade.AccountRiskStore import _sha, _ledger
from Trade.AccountRiskStore import SCHEMA as CHECK_SCHEMA
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.AccountIdentity import observe_account_context
from Trade.ExecutionFacts import collect_execution_scan
from Trade.ExecutionReconcile import build_execution_ownership
from Trade.AccountSources import collect_account_snapshot, collect_wallet_scan
from Trade.NativeBalanceReservations import collect_native_balance_reservations
from Trade.NativeAccountReconcile import observe_native_account_components
from Trade.db_util import CChanDB
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import capacity_case, single_case
from .test_native_prepared_last import install_last
from .test_native_monetary_prepared_intent import acquire
from .test_native_pending_orders import regular_row
from .test_execution_facts import fill
from .test_execution_ownership import scenario, source_scan
from .test_execution_account_binding import observation
from .test_m6_trade import make_signal


def observe_pending(case):
    document = Pending.collect_native_pending_orders(case["client"], case["units"], mode=case["trade"].mode)
    return document, Ownership.observe_native_pending_ownership(case["db"], pending_orders=document)


def collect_unclaimed_execution(case):
    record = case["db"].get_record(case["key"])
    case["db"].record_open_submission(case["key"], "123456", "open",
        client_order_id=record["open_client_order_id"], expected_attempt=1)
    row = fill("binance", case["clock"]["now"], key=202, quantity=".02",
        side="buy" if record["is_buy"] else "sell", leg=record["position_side"])
    row["orderId"] = "123456"
    case["execution_io"][case["units"][0]["id"]].rows.append(row)
    started = case["clock"]["now"]
    account = observe_account_context(case["client"], case["trade"].mode)
    source = collect_execution_scan(case["client"], case["units"][0], account_scope="owned-capacity-fixture",
        mode=case["trade"].mode, start_ms=case["before"]["payload"]["started_ms"], end_ms=started+1)
    case["db"].store_execution_scan(source, account_observation={"before": account,
        "after": observe_account_context(case["client"], case["trade"].mode),
        "started_ms": started, "finished_ms": case["clock"]["now"]})
    return source


def component_sources(case):
    client, db, mode = case["client"], case["db"], case["trade"].mode
    case["clock"]["now"] += 10
    pending = Pending.collect_native_pending_orders(client, case["units"], mode=mode)
    balance = collect_native_balance_reservations(client, mode=mode)
    case["clock"]["now"] += 1
    after = collect_account_snapshot(client, case["units"], mode=mode)
    case["clock"]["now"] += 1
    end = case["clock"]["now"]
    start = case["before"]["payload"]["started_ms"]
    executions = []
    for market in case["units"]:
        started = case["clock"]["now"]
        account = observe_account_context(client, mode)
        scan = collect_execution_scan(client, market, account_scope="owned-capacity-fixture", mode=mode, start_ms=start, end_ms=end)
        executions.append(db.store_execution_scan(scan, account_observation={"before": account,
            "after": observe_account_context(client, mode), "started_ms": started, "finished_ms": case["clock"]["now"]}))
    wallet = collect_wallet_scan(client, mode=mode, start_ms=start, end_ms=end)
    params = {"account_context": after["payload"]["account_context"], "before_id": case["before_id"],
        "after_id": db.store_account_evidence(after), "wallet_ids": [db.store_account_evidence(wallet)],
        "execution_scan_ids": executions, "pending_orders": pending, "balance_reservations": balance}
    request = {key: value for key, value in params.items() if key not in {"pending_orders", "balance_reservations"}}
    request.update(pending_id=db.store_native_account_observation(pending), balance_id=db.store_native_account_observation(balance))
    return params, request


def test_original_pending_consumer_keeps_the_actual_monetary_intent_as_unobserved_reservation(capacity_case, monkeypatch):
    case = capacity_case
    install_last(case, monkeypatch)
    assert acquire(case)
    row, changes = case["db"].get_record(case["key"]), case["db"].db.conn.total_changes
    pending = Pending.collect_native_pending_orders(case["client"], case["units"], mode=case["trade"].mode)
    calls = copy.deepcopy(case["http_calls"])
    report = Ownership.observe_native_pending_ownership(case["db"], pending_orders=pending)
    reservations = [item for item in report["payload"]["reservations"] if item["attempt"]["record_id"] == case["key"]]
    assert len(reservations) == 1, "the real new monetary intent must not disappear as unidentified schema"
    assert reservations[0]["local_order_status"] == "created"
    assert reservations[0]["remaining_base_quantity"] == "0.1"
    assert reservations[0]["native_pending_matched"] is False and reservations[0]["native_margin_amount"] is None
    assert any(item["reason"] == "local_pending_not_observed" and item["attempt"]["record_id"] == case["key"]
               for item in report["payload"]["issues"])
    assert not any(item["reason"] == "unidentified_attempt" and item.get("attempt", {}).get("record_id") == case["key"]
                   for item in report["payload"]["issues"])
    assert report["schema"] == "chan-native-pending-ownership-v2"
    root = read_native_order_transition(case["db"], case["key"])
    refs = report["payload"]["client_order_references"]
    assert len(refs) == 1 and refs[0]["target"] == root["payload"]["root"]["target"]
    assert refs[0]["binding_sha256"] == root["payload"]["binding_sha256"]
    assert refs[0]["transition_payload_sha256"] == root["payload_sha256"] and refs[0]["stage"] == "intent"
    assert report["payload"]["economics_complete"] is report["payload"]["native_admission_verified"] is False
    assert case["db"].get_record(case["key"]) == row and case["db"].db.conn.total_changes == changes
    assert case["http_calls"] == calls and len(case["created"]) == 3


def test_original_pending_history_does_not_require_renewing_expired_money_sources(single_case, monkeypatch):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    case["clock"]["now"] += 2001
    _, report = observe_pending(case)
    reservations = [item for item in report["payload"]["reservations"] if item["attempt"]["record_id"] == case["key"]]
    assert len(reservations) == 1, "historical ownership must retain expired unobserved intents, not renew or drop them"
    assert reservations[0]["native_pending_matched"] is False
    assert case["db"].get_record(case["key"])["open_order_status"] == "created"


def test_actual_pending_consumer_accepts_no_caller_reference_authority(single_case):
    with pytest.raises(TypeError):
        Ownership.observe_native_pending_ownership(single_case["db"], pending_orders={}, client_order_references={"passed": True})


def test_original_execution_reader_reloads_money_but_does_not_invent_the_missing_l2(capacity_case, monkeypatch, store):
    case = capacity_case
    install_last(case, monkeypatch)
    assert acquire(case)
    source = collect_unclaimed_execution(case)
    changes, record, calls = case["db"].db.conn.total_changes, case["db"].get_record(case["key"]), copy.deepcopy(case["http_calls"])
    report = case["db"].get_execution_ownership(source["payload_sha256"])
    trade = next(item for item in report["payload"]["trades"] if item["source_id"] == "202")
    assert trade["status"] == "unowned" and trade["reason"] == "client_claim_not_observed"
    assert report["schema"] == "chan-execution-ownership-v2"
    assert report["payload"]["client_order_references"][0]["monetary_basis_sha256"] == json.loads(record["open_order_contract"])["monetary_basis_sha256"]
    assert all(item["status"] == "owned" for item in report["payload"]["trades"] if item["source_id"] != "202")
    case["clock"]["now"] += 2001
    with closing(CChanDB(db_conf=store[1])) as restarted:
        assert restarted.get_execution_ownership(source["payload_sha256"]) == report
    assert case["db"].get_record(case["key"]) == record and case["db"].db.conn.total_changes == changes
    assert case["http_calls"] == calls and len(case["created"]) == 3


def test_original_execution_reader_cannot_hide_the_actual_money_attempt_in_another_table(single_case, monkeypatch, store):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    source = collect_unclaimed_execution(case)
    expected = case["db"].get_execution_ownership(source["payload_sha256"])
    with closing(CChanDB(table_name="other_trade", db_conf=store[1])) as other:
        actual = other.get_execution_ownership(source["payload_sha256"])
    assert actual == expected, "the original stable-account ledger is not limited to the caller's trade table"


def test_original_execution_reader_has_no_caller_root_override(single_case):
    with pytest.raises(TypeError):
        single_case["db"].get_execution_ownership("0"*64, client_roots={"passed": True})


def test_legacy_execution_report_keeps_the_original_empty_signal_history_bytes(store, tmp_path, monkeypatch):
    db, _ = store
    trade, key, history, rows, start, end = scenario(db, tmp_path, monkeypatch, "binance")
    empty_key = db.add_signal(make_signal(code=history["attempts"][0]["identity"]["instrument"]))
    source = source_scan("binance", rows, start, end)
    account = observation(trade)
    db.store_execution_scan(source, account_observation=account)
    expected = build_execution_ownership(source, account["before"], [history, db.get_order_history(empty_key)])
    assert expected["schema"] == "chan-execution-ownership-v1"
    assert db.get_execution_ownership(source["payload_sha256"]) == expected


def test_original_bound_reader_keeps_a_verified_intent_prefix_after_later_ack(single_case, monkeypatch):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    root = read_native_order_transition(case["db"], case["key"])
    prefix = copy.deepcopy(case["db"].get_order_history(case["key"])["attempts"][0])
    case["db"].record_open_submission(case["key"], "123456", "open",
        client_order_id=prefix["identity"]["client_order_id"], expected_attempt=1)
    with case["db"].db.transaction():
        assert Transition._read_bound_attempt(case["db"], prefix) == root


def test_original_native_components_and_check_keep_money_references_without_releasing_risk(single_case, monkeypatch, store):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    params, request = component_sources(case)
    changes = case["db"].db.conn.total_changes
    component = observe_native_account_components(case["db"], **params)
    issues = component["payload"]["issues"]
    assert component["schema"] == "chan-native-account-components-v2"
    assert component["payload"]["interval"]["schema"] == "chan-account-reconciliation-pending-v3"
    assert not any(item["reason"] == "unidentified_attempt" for item in issues)
    assert any(item["reason"] == "native_pending_local_pending_not_observed" for item in issues)
    assert component["payload"]["pending"]["payload"]["client_order_references"]
    assert case["db"].db.conn.total_changes == changes
    document = case["db"].reconcile_native_account(**request)
    assert document["schema"] == "chan-native-account-check-v2"
    assert document["payload"]["inputs"]["client_roots"]
    assert document["payload"]["report"]["payload"]["components"] == component
    assert document["payload"]["report"]["payload"]["status"] == "incomplete"
    assert document["payload"]["report"]["payload"]["native_admission_verified"] is False
    assert case["db"].get_account_risk_state(request["account_context"])["frozen"] is True
    check_id = _sha(document)
    before_ack = copy.deepcopy(document)
    case["db"].record_open_submission(case["key"], "123456", "open",
        client_order_id=case["db"].get_record(case["key"])["open_client_order_id"], expected_attempt=1)
    case["clock"]["now"] += 2001
    calls = copy.deepcopy(case["http_calls"])
    with closing(CChanDB(db_conf=store[1])) as restarted:
        assert restarted.get_account_check(check_id) == before_ack
        assert restarted.get_account_risk_state(request["account_context"])["frozen"] is True
    assert case["http_calls"] == calls and len(case["created"]) == 3


def test_original_interval_check_uses_the_same_money_root_and_immutable_prefix(single_case, monkeypatch, store):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    _, request = component_sources(case)
    document = case["db"].reconcile_account(**{key: value for key, value in request.items() if key not in {"pending_id", "balance_id"}})
    assert document["schema"] == "chan-account-check-v2"
    assert document["payload"]["inputs"]["client_roots"]
    assert document["payload"]["inputs"]["journal_prefix"]["attempt_count"] == 4
    report = document["payload"]["report"]
    assert report["schema"] == "chan-account-reconciliation-v2"
    assert not any(item["reason"] == "unidentified_attempt" for item in report["payload"]["issues"])
    assert report["payload"]["status"] == "incomplete" and report["payload"]["economics_complete"] is False
    case["db"].record_open_submission(case["key"], "123456", "open",
        client_order_id=case["db"].get_record(case["key"])["open_client_order_id"], expected_attempt=1)
    case["clock"]["now"] += 2001
    calls = copy.deepcopy(case["http_calls"])
    with closing(CChanDB(db_conf=store[1])) as restarted:
        assert restarted.get_account_check(_sha(document)) == document
        assert restarted.get_account_risk_state(request["account_context"])["frozen"] is True
    assert case["http_calls"] == calls and len(case["created"]) == 3


@pytest.mark.parametrize("native", [True, False])
@pytest.mark.parametrize("damage", ["missing_roots", "duplicate_roots", "downgrade", "root_body", "root_target", "event_prefix", "unavailable_v2"])
def test_resealed_stored_account_check_cannot_replace_the_actual_money_history(single_case, monkeypatch, native, damage):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    _, request = component_sources(case)
    if native:
        original = case["db"].reconcile_native_account(**request)
    else:
        original = case["db"].reconcile_account(**{key: value for key, value in request.items() if key not in {"pending_id", "balance_id"}})
    changed = copy.deepcopy(original)
    inputs = changed["payload"]["inputs"]
    assert inputs is not None and inputs["client_roots"]
    if damage == "missing_roots":
        inputs["client_roots"] = []
    elif damage == "duplicate_roots":
        inputs["client_roots"].append(copy.deepcopy(inputs["client_roots"][0]))
    elif damage == "downgrade":
        changed["schema"] = changed["schema"].replace("-v2", "-v1")
    elif damage == "root_body":
        root = inputs["client_roots"][0]
        root["payload"]["root"]["preparation"]["monetary"]["payload"]["native_admission_verified"] = True
        root["payload_sha256"] = _sha(root["payload"])
    elif damage == "root_target":
        inputs["client_roots"][0]["payload"]["root"]["target"]["record_id"] += 1
    elif damage == "event_prefix":
        inputs["histories"][-1]["attempts"][0]["events"][0]["state"]["order_status"] = "closed"
    else:
        from Trade.AccountRiskStore import _failure
        changed["payload"]["inputs"] = None
        changed["payload"]["report"] = _failure(request["account_context"])
    changed["payload_sha256"] = _sha(changed["payload"])
    old_id, new_id = _sha(original), _sha(changed)
    db = case["db"].db
    with db.transaction():
        db.execute("DROP TRIGGER chanpy_account_checks_no_update")
        db.execute("UPDATE chanpy_account_checks SET check_id=?,payload=?,payload_sha256=?,status=? WHERE check_id=?",
            (new_id, canonical_bytes(changed).decode(), new_id, changed["payload"]["report"]["payload"]["status"], old_id))
        db.execute(CHECK_SCHEMA["chanpy_account_checks_no_update"])
    calls, changes = copy.deepcopy(case["http_calls"]), db.conn.total_changes
    with pytest.raises(CChanException):
        case["db"].get_account_check(new_id)
    with pytest.raises(CChanException):
        case["db"].get_account_risk_state(request["account_context"])
    assert case["http_calls"] == calls and db.conn.total_changes == changes


@pytest.mark.parametrize("status", ["canceled", "rejected", "closed"])
def test_local_terminal_without_native_completion_does_not_release_the_monetary_reservation(single_case, monkeypatch, status):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    case["db"].record_open_submission(case["key"], "123456", status,
        client_order_id=case["db"].get_record(case["key"])["open_client_order_id"], expected_attempt=1)
    _, report = observe_pending(case)
    reservations = [item for item in report["payload"]["reservations"] if item["attempt"]["record_id"] == case["key"]]
    assert len(reservations) == 1, "local status plus an empty native subset is not terminal observation authority"
    assert reservations[0]["native_pending_matched"] is False
    assert any(item["reason"] == "client_terminal_not_observed" and item["attempt"]["record_id"] == case["key"]
               for item in report["payload"]["issues"])


def test_matching_native_row_and_local_ack_without_original_l2_cannot_own_a_client_order(single_case, monkeypatch):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    record = case["db"].get_record(case["key"])
    contract = json.loads(record["open_order_contract"])
    case["db"].record_open_submission(case["key"], "123456", "open",
        client_order_id=record["open_client_order_id"], expected_attempt=1)
    transport = case["client"].session.request
    def with_order(method, url, **kwargs):
        response = transport(method, url, **kwargs)
        if "/openOrders?" in url:
            rows = json.loads(response.text)
            order = regular_row("binance", contract["market"]["id"], 123456)
            order.update(clientOrderId=record["open_client_order_id"], origQty=contract["quantity"], executedQty="0",
                side="BUY", positionSide=record["position_side"], price=contract["price"],
                time=case["clock"]["now"], updateTime=case["clock"]["now"])
            rows.append(order)
            response._content = json.dumps(rows).encode()
        return response
    monkeypatch.setattr(case["client"].session, "request", with_order)
    _, report = observe_pending(case)
    records = [item for item in report["payload"]["orders"] if item["native_order"][-1] == "123456"]
    assert len(records) == 1 and records[0]["status"] == "unowned"
    assert records[0]["reason"] == "client_claim_not_observed"


def test_private_pure_client_link_rejects_a_changed_monetary_body_even_with_resealed_outer_links(single_case, monkeypatch):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    root = copy.deepcopy(read_native_order_transition(case["db"], case["key"]))
    attempt = copy.deepcopy(case["db"].get_order_history(case["key"])["attempts"][0])
    root["payload"]["root"]["preparation"]["monetary"]["payload"]["native_admission_verified"] = True
    root["payload"]["binding_sha256"] = _sha(root["payload"]["root"])
    attempt["events"][0]["native_boundary_sha256"] = root["payload"]["binding_sha256"]
    root["payload_sha256"] = _sha(root["payload"])
    with pytest.raises(CChanException):
        Transition._client_reference(attempt, [root])


def test_original_bound_attempt_reader_refuses_a_caller_dto_or_another_database(single_case, monkeypatch, tmp_path):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    original = read_native_order_transition(case["db"], case["key"])
    attempt = case["db"].get_order_history(case["key"])["attempts"][0]
    with case["db"].db.transaction():
        assert Transition._read_bound_attempt(case["db"], attempt) == original
        changed = copy.deepcopy(attempt)
        changed["identity"]["requested_qty"] = 99
        with pytest.raises(CChanException): Transition._read_bound_attempt(case["db"], changed)
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"foreign-roots.db")})) as other:
        with other.db.transaction(), pytest.raises(CChanException):
            Transition._read_bound_attempt(other, attempt)


@pytest.mark.parametrize("replacement", ["database", "connection"])
def test_money_root_loader_refuses_a_replaced_owner_before_foreign_sql(single_case, monkeypatch, tmp_path, replacement):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    histories = [case["db"].get_order_history(case["key"])]
    original = case["db"].db
    connection = original.conn
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"foreign-owner.db")})) as foreign:
        statements = []
        foreign.db.conn.set_trace_callback(statements.append)
        with original.transaction():
            try:
                if replacement == "database":
                    case["db"].db = foreign.db
                else:
                    original.conn = foreign.db.conn
                with pytest.raises(CChanException):
                    Transition._client_order_roots(case["db"], histories)
            finally:
                case["db"].db = original
                original.conn = connection
        assert statements == []


@pytest.mark.parametrize("stage", ["instrument", "capacity", "monetary"])
def test_original_money_history_source_tail_cannot_query_a_replaced_connection(single_case, monkeypatch, tmp_path, stage):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    histories = [case["db"].get_order_history(case["key"])]
    db, connection = case["db"].db, case["db"].db.conn
    module, name = {"instrument": (Instrument, "_sdk"), "capacity": (Capacity, "_sdk"),
                    "monetary": (Prepared, "_assert_monetary")}[stage]
    reader, replaced = getattr(module, name), []
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"foreign-tail.db")})) as foreign:
        statements = []
        foreign.db.conn.set_trace_callback(statements.append)
        def late(*args, **kwargs):
            result = reader(*args, **kwargs)
            if not replaced:
                replaced.append(stage)
                db.conn = foreign.db.conn
            return result
        monkeypatch.setattr(module, name, late)
        with db.transaction():
            try:
                with pytest.raises(CChanException):
                    Transition._client_order_roots(case["db"], histories)
            finally:
                db.conn = connection
        assert replaced == [stage]
        assert statements == [], "historical source/body validation must reject before any foreign SQL"


@pytest.mark.parametrize("raw", ["NATIVE_PRIVATE_ROOT", '{"private":"NATIVE_PRIVATE_ROOT"}'])
def test_original_execution_maps_a_corrupt_stored_money_root_to_a_closed_domain_error(single_case, monkeypatch, raw):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    source = collect_unclaimed_execution(case)
    db = case["db"].db
    with db.transaction():
        db.execute("DROP TRIGGER chanpy_native_order_transitions_no_update")
        db.execute("UPDATE chanpy_native_order_transitions SET payload=?,payload_sha256=? WHERE record_id=?",
            (raw, hashlib.sha256(raw.encode()).hexdigest(), case["key"]))
        db.execute(Transition.SCHEMA["chanpy_native_order_transitions_no_update"])
    changes, calls = db.conn.total_changes, copy.deepcopy(case["http_calls"])
    with pytest.raises(CChanException) as caught:
        case["db"].get_execution_ownership(source["payload_sha256"])
    assert "NATIVE_PRIVATE_ROOT" not in str(caught.value)
    assert db.conn.total_changes == changes and case["http_calls"] == calls


@pytest.mark.parametrize("native", [True, False])
def test_actual_account_check_cannot_relabel_an_unclaimed_trade_as_an_owned_money_fill(single_case, monkeypatch, native):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    collect_unclaimed_execution(case)
    _, request = component_sources(case)
    document = case["db"].reconcile_native_account(**request) if native else case["db"].reconcile_account(
        **{key: value for key, value in request.items() if key not in {"pending_id", "balance_id"}})
    assert document["payload"]["inputs"] is not None
    issues = document["payload"]["report"]["payload"]["issues"]
    assert any(item["reason"] == "unowned_execution" and item["source_id"] == "202"
               and item["ownership_reason"] == "client_claim_not_observed" for item in issues)
    assert not any(item["reason"] == "unidentified_attempt" for item in issues)
    assert case["db"].get_account_risk_state(request["account_context"])["frozen"] is True
    assert len(case["created"]) == 3


def test_legacy_execution_reason_keeps_native_transition_loading_outside_its_path():
    script = r'''
import importlib.abc, sys
from Trade.ExecutionReconcile import _reason
class NoNativeTransition(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'Trade.NativeOrderTransition':
            raise ImportError('legacy reader must not load native transition machinery')
sys.meta_path.insert(0, NoNativeTransition())
assert _reason({'origin': 'legacy_snapshot', 'identity': {'order_contract': None}}, {}, {}, {}) == 'legacy_attempt'
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_legacy_pending_rebuild_does_not_import_the_new_money_transition_path(single_case):
    case = single_case
    pending = Pending.collect_native_pending_orders(case["client"], case["units"], mode=case["trade"].mode)
    with case["db"].db.transaction():
        ledger = _ledger(case["db"])
    script = r'''
import importlib.abc, json, sys
from Trade.NativePendingOwnership import _build
assert 'Trade.NativeOrderTransition' not in sys.modules
class NoNativeTransition(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'Trade.NativeOrderTransition':
            raise ImportError('legacy pending must not import new money transition machinery')
sys.meta_path.insert(0, NoNativeTransition())
values = json.load(sys.stdin)
payload = _build(values['source'], values['ledger'])
assert not payload['issues'] and len(payload['reservations']) == 1
assert payload['reservations'][0]['native_pending_matched'] is True
assert 'client_order_references' not in payload
'''
    result = subprocess.run([sys.executable, "-c", script], input=canonical_bytes({"source": pending["payload"], "ledger": ledger}),
        capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
