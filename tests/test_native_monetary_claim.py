"""The original SQLite writer owns monetary L1->L2; no send permission."""
import copy
import gc
import json
import weakref
from contextlib import closing
from pathlib import Path

import pytest

from Common.ChanException import CChanException
from Trade.db_util import CChanDB
from Trade import NativeOrderTransition as Transition
from Trade import NativePreparedIntent as Prepared
from Trade import NativePreparation as Prepare
from Trade import NativeCapacityEvidence as Capacity
from Trade import db_util as db_module
from Trade import OrderAudit
from Trade.Script.OpeningInputs import COpeningInputs
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import capacity_case, single_case
from .test_native_capacity_prepared_intent import acquire as acquire_diagnostic_capacity, options
from .test_native_monetary_prepared_intent import acquire
from .test_native_prepared_last import install_last
from .test_native_monetary_consumers import observe_pending
from .test_native_pending_orders import regular_row


def claim_context(case):
    capture = getattr(Prepared, "_capture_native_claim_context", None)
    assert callable(capture), "the original Engine has no owned monetary claim context"
    return capture(case["trade"], case["key"])


@pytest.mark.parametrize("kind,post_only", [("limit", False), ("limit", True), ("market", False)])
def test_original_writer_claims_same_monetary_root_without_an_extra_source_or_send(capacity_case, monkeypatch, kind, post_only):
    case = capacity_case
    install_last(case, monkeypatch)
    assert acquire(case, price=None if kind == "market" else 100, post_only=post_only)
    chan = case["db"]
    intent = Transition.read_native_order_transition(chan, case["key"])
    old_rows = [chan.get_record(key) for key in case["history_keys"]]
    calls = copy.deepcopy(case["http_calls"])
    with chan.db.transaction():
        context = claim_context(case)
        assert chan.claim_order_submission(case["key"], "open", native_claim=context) is True
    claim = Transition.read_native_order_transition(chan, case["key"])
    assert claim["payload"]["stage"] == "claim"
    assert claim["payload"]["root"] == intent["payload"]["root"]
    assert claim["payload"]["binding_sha256"] == intent["payload"]["binding_sha256"]
    assert claim["payload"]["previous_sha256"] == intent["payload_sha256"]
    assert claim["payload"]["journal_prefix"]["event_count"] == intent["payload"]["journal_prefix"]["event_count"]+1
    assert claim["payload"]["journal_prefix"]["attempt_count"] == intent["payload"]["journal_prefix"]["attempt_count"]
    assert [event["kind"] for event in chan.get_order_history(case["key"])["attempts"][0]["events"]] == ["intent", "claim"]
    assert chan.get_record(case["key"])["open_order_status"] == "submitting"
    assert [chan.get_record(key) for key in case["history_keys"]] == old_rows
    assert case["http_calls"] == calls and len(case["created"]) == 3
    # Existing public intent-only validation must not silently start accepting L2.
    with chan.db.transaction(), pytest.raises(CChanException):
        Prepared.assert_native_prepared_intent_current(case["trade"], case["key"])
    assert chan.claim_order_submission(case["key"], "open") is False


@pytest.mark.parametrize("replacement", ["database", "connection"])
def test_original_claim_rejects_a_replaced_owner_before_any_foreign_sql(single_case, monkeypatch, tmp_path, replacement):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    chan, backend = case["db"], case["db"].db
    connection = backend.conn
    with backend.transaction():
        context = claim_context(case)
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"foreign-claim.db")})) as foreign:
        statements = []
        foreign.db.conn.set_trace_callback(statements.append)
        try:
            if replacement == "database":
                chan.db = foreign.db
            else:
                backend.conn = foreign.db.conn
            with pytest.raises(CChanException):
                chan.claim_order_submission(case["key"], "open", native_claim=context)
        finally:
            chan.db, backend.conn = backend, connection
        assert statements == [], "an owned claim must reject before opening a foreign transaction"
    assert chan.get_record(case["key"])["open_order_status"] == "created"


@pytest.mark.parametrize("kind", ["none", "json", "blank", "copy", "prepare"])
def test_no_caller_receipt_or_copied_or_prepare_context_can_claim(single_case, monkeypatch, kind):
    case = single_case
    install_last(case, monkeypatch)
    prepare = Prepare._capture_native_prepare_context(case["trade"], case["key"], .1, 100) if kind == "prepare" else None
    assert acquire(case)
    chan = case["db"]
    before = chan.get_record(case["key"])
    document = Transition.read_native_order_transition(chan, case["key"])
    with chan.db.transaction():
        real = claim_context(case)
    supplied = {"none": None, "json": document, "blank": Prepared._NativeClaimContext(),
                "copy": copy.copy(real), "prepare": prepare}[kind]
    changes = chan.db.conn.total_changes
    with pytest.raises(CChanException):
        chan.claim_order_submission(case["key"], "open", native_claim=supplied)
    assert chan.get_record(case["key"]) == before and chan.db.conn.total_changes == changes


@pytest.mark.parametrize("raw", [False, True])
def test_capture_requires_the_original_owned_transaction(single_case, monkeypatch, raw):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    backend = case["db"].db
    if raw:
        backend.conn.execute("BEGIN")
    try:
        with pytest.raises(CChanException):
            claim_context(case)
    finally:
        if raw:
            backend.conn.rollback()


@pytest.mark.parametrize("version", [2, 3])
def test_old_prepared_diagnostics_do_not_acquire_a_claim_context(single_case, monkeypatch, version):
    case = single_case
    install_last(case, monkeypatch)
    if version == 3:
        assert acquire_diagnostic_capacity(case)
    else:
        assert Prepared.acquire_native_prepared_diagnostic_intent(case["trade"], case["key"], .1, 100, **options(case))
    before = case["db"].get_record(case["key"])
    with case["db"].db.transaction(), pytest.raises(CChanException):
        claim_context(case)
    assert case["db"].get_record(case["key"]) == before


@pytest.mark.parametrize("damage", ["own_row", "other_row", "config", "candidate", "kill", "scope", "engine_config",
                                  "metadata", "credential", "route", "freeze", "expired", "reverse_clock", "clock_owner"])
def test_claim_rechecks_original_currentness_not_just_a_once_checked_handle(single_case, monkeypatch, damage):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    chan, engine, client = case["db"], case["trade"], case["client"]
    with chan.db.transaction():
        context = claim_context(case)
    if damage in {"own_row", "other_row"}:
        key = case["key"] if damage == "own_row" else case["history_keys"][0]
        chan.db.execute(f"UPDATE {chan.table} SET unwatch_reason='changed after capture' WHERE id=?", (key,))
    elif damage == "config":
        case["config"].write_bytes(case["config"].read_bytes()+b"\n ")
    elif damage == "candidate":
        candidate = Path(engine.safety_policy.strategy_receipt["path"])
        candidate.write_bytes(candidate.read_bytes()+b"\n ")
    elif damage == "kill":
        engine.safety_policy.environ["CHANPY_KILL_SWITCH"] = "YES"
    elif damage == "scope":
        engine.opening_inputs._scope["code_list"] = ["TEST/USDT:USDT"]
    elif damage == "engine_config":
        engine.ccxt_conf["leverage"] = 4
    elif damage == "metadata":
        client.markets["TEST/USDT:USDT"]["precision"]["price"] = .2
    elif damage == "credential":
        client.secret = "fake-only-unobserved-change"
    elif damage == "route":
        client.urls["api"]["fapiPrivate"] = "https://changed.invalid"
    elif damage == "freeze":
        chan.reconcile_account(account_context=case["before"]["payload"]["account_context"], before_id="0"*64, after_id="1"*64,
                               wallet_ids=[], execution_scan_ids=[])
    elif damage == "expired":
        case["clock"]["now"] += 2001
    elif damage == "reverse_clock":
        case["clock"]["now"] -= 1
    else:
        engine.opening_inputs.now_ms = lambda: case["clock"]["now"]
    before, calls = chan.get_record(case["key"]), copy.deepcopy(case["http_calls"])
    with pytest.raises(CChanException):
        chan.claim_order_submission(case["key"], "open", native_claim=context)
    assert chan.get_record(case["key"]) == before
    assert len(chan.get_order_history(case["key"])["attempts"][0]["events"]) == 1
    assert case["http_calls"] == calls and len(case["created"]) == 3


def test_fresh_engine_and_connection_can_claim_but_not_borrow_the_old_owner(single_case, monkeypatch, store):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    chan = case["db"]
    with chan.db.transaction():
        old_context = claim_context(case)
    with closing(CChanDB(db_conf=store[1])) as reopened:
        engine = copy.copy(case["trade"])
        engine.chan_db = reopened
        engine.opening_inputs = COpeningInputs(case["config"], now_ms=lambda: case["clock"]["now"])
        statements = []
        reopened.db.conn.set_trace_callback(statements.append)
        with pytest.raises(CChanException):
            reopened.claim_order_submission(case["key"], "open", native_claim=old_context)
        assert statements == []
        with reopened.db.transaction():
            fresh_context = Prepared._capture_native_claim_context(engine, case["key"])
            assert reopened.claim_order_submission(case["key"], "open", native_claim=fresh_context)
    assert chan.get_record(case["key"])["open_order_status"] == "submitting"


def test_claim_handles_are_not_kept_alive_after_the_invocation(single_case, monkeypatch):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    with case["db"].db.transaction():
        context = claim_context(case)
        reference = weakref.ref(context)
        assert context in Prepared._CLAIMS
    del context
    gc.collect()
    assert reference() is None


@pytest.mark.parametrize("at", ["stamp", "source"])
def test_claim_callbacks_cannot_send_sql_or_rollback_to_a_foreign_connection(single_case, monkeypatch, tmp_path, at):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    chan, backend = case["db"], case["db"].db
    connection = backend.conn
    before = chan.get_record(case["key"])
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"late-claim-owner.db")})) as foreign:
        statements, touched = [], []
        foreign.db.conn.set_trace_callback(statements.append)
        with backend.transaction():
            context = claim_context(case)
            module, name = (db_module, "now_str") if at == "stamp" else (Capacity, "_sdk")
            original = getattr(module, name)
            def changed(*args, **kwargs):
                result = original(*args, **kwargs)
                if not touched:
                    touched.append(at)
                    backend.conn = foreign.db.conn
                return result
            monkeypatch.setattr(module, name, changed)
            try:
                with pytest.raises(CChanException):
                    chan.claim_order_submission(case["key"], "open", native_claim=context)
            finally:
                backend.conn = connection
        assert touched == [at]
        assert statements == [], "neither the writer nor its rollback may run SQL on a replacement"
    assert chan.get_record(case["key"]) == before
    assert len(chan.get_order_history(case["key"])["attempts"][0]["events"]) == 1


@pytest.mark.parametrize("damage", ["own_row", "other_row", "credential", "clock", "extra_ack",
                                  "tail_elapsed", "tail_bool", "tail_reverse"])
def test_original_claim_and_l2_publication_roll_back_together_on_late_drift(single_case, monkeypatch, damage):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    chan = case["db"]
    before, history = chan.get_record(case["key"]), chan.get_order_history(case["key"])
    rows = [chan.get_record(key) for key in case["history_keys"]]
    with chan.db.transaction():
        context = claim_context(case)
    original, touched = OrderAudit.record_transition, []
    def changed(database, table, old, after, phase, kind, **kwargs):
        result = original(database, table, old, after, phase, kind, **kwargs)
        if kind == "claim" and not touched:
            touched.append(damage)
            if damage in {"own_row", "other_row"}:
                key = case["key"] if damage == "own_row" else case["history_keys"][0]
                chan.db.execute(f"UPDATE {chan.table} SET unwatch_reason='late claim change' WHERE id=?", (key,))
            elif damage == "credential":
                case["client"].secret = "fake-only-late-credential"
            elif damage == "clock":
                case["clock"]["now"] += 2001
            elif damage == "extra_ack":
                chan.record_order_ack(case["key"], "open", "123456", client_order_id=before["open_client_order_id"], expected_attempt=1)
            else:
                values = {"tail_elapsed": [0, 2_001_000_000], "tail_bool": [True, True], "tail_reverse": [2, 1]}[damage]
                ticks = iter(values)
                monkeypatch.setattr(Prepared, "_monotonic_ns", lambda: next(ticks))
        return result
    monkeypatch.setattr(OrderAudit, "record_transition", changed)
    with pytest.raises(CChanException):
        chan.claim_order_submission(case["key"], "open", native_claim=context)
    assert touched == [damage]
    assert chan.get_record(case["key"]) == before and chan.get_order_history(case["key"]) == history
    assert [chan.get_record(key) for key in case["history_keys"]] == rows
    assert chan.db.query_one(f"SELECT count(*) AS n FROM {Transition.TABLE}")["n"] == 1
    assert len(case["created"]) == 3


def test_same_l1_on_two_real_connections_cannot_publish_a_second_claim(single_case, monkeypatch, store):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    chan = case["db"]
    with chan.db.transaction():
        first = claim_context(case)
    with closing(CChanDB(db_conf=store[1])) as other:
        engine = copy.copy(case["trade"])
        engine.chan_db = other
        engine.opening_inputs = COpeningInputs(case["config"], now_ms=lambda: case["clock"]["now"])
        with other.db.transaction():
            second = Prepared._capture_native_claim_context(engine, case["key"])
        assert chan.claim_order_submission(case["key"], "open", native_claim=first)
        assert other.claim_order_submission(case["key"], "open", native_claim=second) is False
        assert other.get_record(case["key"]) == chan.get_record(case["key"])
    assert len(chan.get_order_history(case["key"])["attempts"][0]["events"]) == 2
    assert chan.db.query_one(f"SELECT count(*) AS n FROM {Transition.TABLE}")["n"] == 2


@pytest.mark.parametrize("target", ["record", "table", "close"])
def test_claim_context_is_not_transferable_to_another_record_table_or_phase(single_case, monkeypatch, target):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    chan = case["db"]
    before = chan.get_record(case["key"])
    with chan.db.transaction():
        context = claim_context(case)
    table = chan.table
    try:
        if target == "table":
            chan.table = "not_the_original_trade_table"
        with pytest.raises(CChanException):
            chan.claim_order_submission(case["history_keys"][0] if target == "record" else case["key"],
                                        "close" if target == "close" else "open", native_claim=context)
    finally:
        chan.table = table
    assert chan.get_record(case["key"]) == before
    assert len(chan.get_order_history(case["key"])["attempts"][0]["events"]) == 1


@pytest.mark.parametrize("replacement", ["database", "connection"])
def test_monetary_intent_stamp_cannot_start_a_transaction_on_a_foreign_owner(single_case, monkeypatch, tmp_path, replacement):
    case = single_case
    install_last(case, monkeypatch)
    chan, backend = case["db"], case["db"].db
    connection, before = backend.conn, chan.get_record(case["key"])
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"intent-stamp-owner.db")})) as foreign:
        statements, touched = [], []
        foreign.db.conn.set_trace_callback(statements.append)
        original = db_module.now_str
        def changed():
            result = original()
            bound = any(entry[0] is case["trade"] and type(entry[-1]) is bytes
                        and b'"schema":"chan-native-prepared-intent-binding-v4"' in entry[-1]
                        for entry in Prepare._PREPARED.values())
            if bound and not touched:
                touched.append(replacement)
                if replacement == "database":
                    chan.db = foreign.db
                else:
                    backend.conn = foreign.db.conn
            return result
        monkeypatch.setattr(db_module, "now_str", changed)
        try:
            with pytest.raises(CChanException):
                acquire(case)
        finally:
            chan.db, backend.conn = backend, connection
        assert touched == [replacement]
        assert statements == [], "the original monetary writer must check its live owner after its stamp"
    assert chan.get_record(case["key"]) == before
    assert chan.get_order_history(case["key"])["attempts"] == []
    assert chan.db.query_one(f"SELECT count(*) AS n FROM {Transition.TABLE}")["n"] == 0


def test_genuine_l2_remains_original_evidence_after_ack_and_observed_open_report(capacity_case, monkeypatch):
    case = capacity_case
    install_last(case, monkeypatch)
    assert acquire(case)
    chan = case["db"]
    record = chan.get_record(case["key"])
    contract = json.loads(record["open_order_contract"])
    with chan.db.transaction():
        context = claim_context(case)
        assert chan.claim_order_submission(case["key"], "open", native_claim=context)
    claim = Transition.read_native_order_transition(chan, case["key"])
    # Feed the original ACK consumer, not a handmade successful L2 or fill.
    chan.record_order_ack(case["key"], "open", "123456", client_order_id=record["open_client_order_id"], expected_attempt=1)
    created_ms = case["clock"]["now"]
    previous = case["client"].session.request
    def with_order(method, url, **kwargs):
        response = previous(method, url, **kwargs)
        if "/openOrders?" in url:
            rows = json.loads(response.text)
            row = regular_row("binance", contract["market"]["id"], 123456)
            row.update(clientOrderId=record["open_client_order_id"], origQty=contract["quantity"], executedQty="0",
                side="BUY" if record["is_buy"] else "SELL", positionSide=record["position_side"], price=contract["price"],
                time=created_ms, updateTime=created_ms)
            rows.append(row)
            response._content = json.dumps(rows).encode()
        return response
    monkeypatch.setattr(case["client"].session, "request", with_order)
    source, unresolved = observe_pending(case)
    unowned = [item for item in unresolved["payload"]["orders"] if item["native_order"][-1] == "123456"]
    assert len(unowned) == 1 and unowned[0]["reason"] == "local_order_state_unresolved"
    # ACK alone must not invent open/zero-fill. Apply the actual observed NEW
    # response via the real SDK parser and original cumulative DB consumer.
    native = next(row for row in source["payload"]["orders"] if row["native_order_id"] == "123456")
    parsed = case["client"].parse_order(native["raw"], case["client"].market(record["stock_code"]))
    assert parsed["id"] == "123456" and parsed["status"] == "open" and parsed["filled"] == 0
    chan.apply_open_fill(case["key"], float(native["filled_base_quantity"]), parsed["average"], parsed["status"],
        client_order_id=record["open_client_order_id"], order_id=parsed["id"], expected_attempt=1)
    _, report = observe_pending(case)
    observed = [item for item in report["payload"]["orders"] if item["native_order"][-1] == "123456"]
    assert len(observed) == 1 and observed[0]["status"] == "owned" and observed[0]["reason"] is None
    reservation = [item for item in report["payload"]["reservations"] if item["attempt"]["record_id"] == case["key"]]
    assert len(reservation) == 1 and reservation[0]["native_pending_matched"] is True
    assert reservation[0]["native_margin_amount"] is None  # No guessed lock amount or terminal release.
    assert Transition.read_native_order_transition(chan, case["key"]) == claim
    # Zero cumulative volume is an original report, not an invented trade fill.
    assert [event["kind"] for event in chan.get_order_history(case["key"])["attempts"][0]["events"]] == ["intent", "claim", "ack", "report"]
    assert len(case["created"]) == 3
