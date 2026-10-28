"""Actual original prepare/CAS and original SDK, with fake bottom transport."""
import copy
import gc
import hashlib
import json
from contextlib import closing

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade import NativeCapacityEvidence as Capacity
from Trade import NativePreparedIntent as Prepared
from Trade.NativeOrderTransition import read_native_order_transition
from Trade.db_util import CChanDB
from .native_capacity_preparation_case import native_capacity_prepare_case
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment


@pytest.fixture(params=[(mode, side) for mode in ("one_way", "hedged") for side in (True, False)])
def capacity_case(request, store, tmp_path, monkeypatch):
    db, conf = store
    mode, side = request.param
    return native_capacity_prepare_case(db, conf, tmp_path, monkeypatch, mode=mode, side=side)


@pytest.fixture
def single_case(store, tmp_path, monkeypatch):
    return native_capacity_prepare_case(*store, tmp_path, monkeypatch)


def options(case):
    return {"before_id": case["before_id"], "account_scope": "owned-capacity-fixture", "policy": case["policy"],
        "instrument_max_age_ms": 2000, "instrument_max_observation_span_ms": 2000, "client_order_id": "ownedCapacityIntent"}


def acquire(case, **changes):
    return Prepared.acquire_binance_capacity_prepared_diagnostic_intent(case["trade"], case["key"], .1, 100,
        **({**options(case), "capacity_max_age_ms": 2000, "capacity_max_observation_span_ms": 2000} | changes))


def test_original_v2_path_reaches_real_sdk_bottom_fake_without_capacity_gets(capacity_case):
    case = capacity_case
    assert Prepared.acquire_native_prepared_diagnostic_intent(case["trade"], case["key"], .1, 100, **options(case)) is True
    document = read_native_order_transition(case["db"], case["key"])
    assert document["payload"]["root"]["preparation"]["schema"] == "chan-native-prepared-intent-binding-v2"
    assert case["http_calls"] and not any(name in {"fapiPrivateGetFeeBurn", "fapiPrivateGetCommissionRate"} for name, _ in case["http_calls"])
    assert len(case["created"]) == 3


@pytest.mark.parametrize("price", [100, None])
def test_new_entry_owns_capacity_on_actual_prepared_intent_without_minting_money_or_send(capacity_case, price):
    case = capacity_case
    entry = getattr(Prepared, "acquire_binance_capacity_prepared_diagnostic_intent", None)
    assert callable(entry), "source-owned capacity prepare/CAS entry is missing"
    before = copy.deepcopy(case["db"].get_record(case["key"]))
    assert entry(case["trade"], case["key"], .1, price, capacity_max_age_ms=2000,
                 capacity_max_observation_span_ms=2000, **options(case)) is True
    document = read_native_order_transition(case["db"], case["key"])
    b = document["payload"]["root"]["preparation"]
    assert b["schema"] == "chan-native-prepared-intent-binding-v3"
    cap = b["capacity_evidence"]["payload"]
    assert cap["requests"] == 21 and cap["economics_complete"] is cap["native_admission_verified"] is False
    assert b["identity"]["payload"]["request"]["price"] == price
    assert b["identity"]["payload"]["record_sha256"] != document["payload"]["after_record_sha256"]
    assert before["open_attempt"] == 0 and case["db"].get_record(case["key"])["open_attempt"] == 1
    assert [name for name, _ in case["http_calls"]].count("fapiPrivateGetFeeBurn") == 1
    assert [name for name, _ in case["http_calls"]].count("fapiPrivateGetCommissionRate") == 2
    with pytest.raises(CChanException):
        case["db"].claim_order_submission(case["key"], "open")
    assert case["db"].get_record(case["key"])["open_order_status"] == "created" and len(case["created"]) == 3


def test_expired_source_keeps_original_history_readable_without_renewing_currentness(capacity_case):
    case = capacity_case
    assert acquire(case)
    original = read_native_order_transition(case["db"], case["key"])
    row, changes, calls = case["db"].get_record(case["key"]), case["db"].db.conn.total_changes, len(case["http_calls"])
    case["clock"]["now"] += 2001
    assert read_native_order_transition(case["db"], case["key"]) == original
    source = original["payload"]["root"]["preparation"]["capacity_evidence"]
    with pytest.raises(CChanException):
        Capacity.verify_binance_capacity_evidence(source, max_age_ms=2000, max_observation_span_ms=2000)
    with case["db"].db.transaction(), pytest.raises(CChanException):
        Prepared.assert_native_prepared_intent_current(case["trade"], case["key"])
    assert case["db"].get_record(case["key"]) == row and case["db"].db.conn.total_changes == changes
    assert len(case["http_calls"]) == calls


def test_current_capacity_decoder_work_cannot_use_an_earlier_fresh_clock(single_case, monkeypatch):
    case = single_case
    assert acquire(case)
    original = read_native_order_transition(case["db"], case["key"])
    sdk = Capacity._sdk
    def delayed_sdk(*args):
        result = sdk(*args)
        case["clock"]["now"] += 2001
        return result
    monkeypatch.setattr(Capacity, "_sdk", delayed_sdk)
    root = original["payload"]["root"]
    with case["db"].db.transaction(), pytest.raises(CChanException):
        Prepared._windows(case["db"], root["preparation"], root["boundary"])


@pytest.mark.parametrize("field", ["capacity_max_age_ms", "capacity_max_observation_span_ms"])
@pytest.mark.parametrize("bad", [None, True, -1, "2000", 2000.5, 2**63])
def test_explicit_capacity_budgets_refuse_before_prepare_or_io(single_case, field, bad):
    case = single_case
    with pytest.raises(CChanException):
        acquire(case, **{field: bad})
    assert case["http_calls"] == [] and case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("field", ["capacity_evidence", "source", "check_id", "passed", "client", "checked_at_ms"])
def test_new_entry_cannot_take_caller_source_or_clock_authority(single_case, field):
    with pytest.raises(TypeError):
        acquire(single_case, **{field: True})
    assert single_case["http_calls"] == []


def test_public_source_reader_cannot_borrow_the_original_intent_time(single_case):
    case = single_case
    assert acquire(case)
    root = read_native_order_transition(case["db"], case["key"])["payload"]["root"]
    with pytest.raises(TypeError):
        Capacity.verify_binance_capacity_evidence(root["preparation"]["capacity_evidence"],
            max_age_ms=2000, max_observation_span_ms=2000, checked_ms=root["preparation"]["finished_ms"])


@pytest.mark.parametrize("damage", ["missing_fee", "configuration", "late_source", "client_options", "foreign_row"])
def test_original_source_failure_leaves_no_intent_and_uses_original_sticky_failure(single_case, monkeypatch, damage):
    case = single_case
    transport, touched = case["client"].session.request, []
    def changed(method, url, **kwargs):
        response = transport(method, url, **kwargs)
        if "/commissionRate?" in url and not touched:
            touched.append(1)
            if damage == "missing_fee":
                body = json.loads(response.text)
                del body["takerCommissionRate"]
                response._content = json.dumps(body).encode()
            elif damage == "late_source":
                case["clock"]["now"] += 2001
            elif damage == "client_options":
                case["client"].options["maxRetriesOnFailure"] = 1
            elif damage == "foreign_row":
                case["db"].db.execute(f"UPDATE {case['db'].table} SET unwatch_reason='owned-capacity-source-drift' WHERE id=?",
                                     (case["history_keys"][0],))
        elif "/symbolConfig?" in url and "symbol=" in url and damage == "configuration":
            body = json.loads(response.text)
            body[0]["leverage"] = 2
            response._content = json.dumps(body).encode()
        return response
    monkeypatch.setattr(case["client"].session, "request", changed)
    with pytest.raises(CChanException):
        acquire(case)
    assert touched == [1]
    assert case["db"].get_record(case["key"])["open_attempt"] == 0
    assert case["db"].get_order_history(case["key"])["attempts"] == []
    assert case["db"].get_account_risk_state(case["before"]["payload"]["account_context"])["frozen"] is True
    if damage == "foreign_row":
        assert case["db"].get_record(case["history_keys"][0])["unwatch_reason"] == "owned-capacity-source-drift"


@pytest.mark.parametrize("stage", ["sql", "reference", "capacity_expired", "forged_context"])
def test_v3_uses_original_atomic_cas_and_rolls_back_its_reference(single_case, monkeypatch, stage):
    case, execute = single_case, single_case["db"].db.execute
    touched = []
    def changed(sql, params=()):
        if sql.startswith("UPDATE "+case["db"].table+" SET status='submitted'") and stage == "sql":
            touched.append(1)
            raise RuntimeError("PRIVATE_CAPACITY_SQL_MUST_NOT_LEAK")
        if sql.startswith("INSERT INTO chanpy_native_order_transitions"):
            touched.append(1)
            if stage == "reference":
                raise RuntimeError("PRIVATE_CAPACITY_REFERENCE_MUST_NOT_LEAK")
            result = execute(sql, params)
            if stage == "capacity_expired":
                case["clock"]["now"] += 2001
            return result
        return execute(sql, params)
    monkeypatch.setattr(case["db"].db, "execute", changed)
    if stage == "forged_context":
        write = case["db"]._order_write
        def forged(*args, **kwargs):
            touched.append(1)
            kwargs["native_preparation"] = {"source_collection_owned": True}
            return write(*args, **kwargs)
        monkeypatch.setattr(case["db"], "_order_write", forged)
    with pytest.raises(CChanException) as caught:
        acquire(case)
    if stage == "forged_context":
        # The original runtime check now rejects the replaced writer before
        # it can receive any live context or start source collection.
        assert touched == [] and case["http_calls"] == []
    else:
        assert touched
    assert "PRIVATE_" not in str(caught.value)
    assert case["db"].get_record(case["key"])["open_attempt"] == 0
    assert case["db"].get_order_history(case["key"])["attempts"] == []
    assert case["db"].db.query("SELECT * FROM chanpy_native_order_transitions") == []


def test_v3_history_survives_reopened_database_without_a_source_get_or_live_handle(capacity_case, store, monkeypatch):
    case = capacity_case
    assert acquire(case)
    original = read_native_order_transition(case["db"], case["key"])
    gc.collect()
    monkeypatch.setattr("Trade.NativePreparation._capture_native_prepare_context", lambda *a, **k: pytest.fail("historical read prepared"))
    case["clock"]["now"] += 2001
    calls = len(case["http_calls"])
    with closing(CChanDB(db_conf=store[1])) as restarted:
        row, changes = restarted.get_record(case["key"]), restarted.db.conn.total_changes
        assert read_native_order_transition(restarted, case["key"]) == original
        with pytest.raises(CChanException):
            restarted.claim_order_submission(case["key"], "open")
        assert restarted.get_record(case["key"]) == row and restarted.db.conn.total_changes == changes
    assert len(case["http_calls"]) == calls


@pytest.mark.parametrize("damage", ["raw_hash", "account", "sdk", "policy_bool", "policy_extra", "chronology", "extra", "market_pool"])
def test_resealed_capacity_packet_cannot_change_original_source_links(single_case, damage):
    case = single_case
    assert acquire(case)
    root = copy.deepcopy(read_native_order_transition(case["db"], case["key"])["payload"]["root"])
    binding = root["preparation"]
    source = binding["capacity_evidence"]
    if damage == "raw_hash":
        source["payload_sha256"] = "0"*64
    elif damage == "account":
        source["payload"]["account_context"]["mode"] = "testnet"
    elif damage == "sdk":
        source["payload"]["sdk"]["version"] = "0"
    elif damage == "policy_bool":
        binding["capacity_policy"]["max_age_ms"] = True
    elif damage == "policy_extra":
        binding["capacity_policy"]["passed"] = True
    elif damage == "chronology":
        source["payload"]["finished_ms"] = binding["finished_ms"]+1
    elif damage == "extra":
        binding["funding_verified"] = True
    else:
        source["payload"]["markets"] = source["payload"]["markets"][:1]
    if damage != "raw_hash":
        source["payload_sha256"] = hashlib.sha256(canonical_bytes(source["payload"])).hexdigest()
    attempt = case["db"].get_order_history(case["key"])["attempts"][0]
    with case["db"].db.transaction(), pytest.raises(CChanException):
        Prepared.validate_stored_preparation(case["db"], root, attempt)


def test_capacity_callback_cannot_touch_a_replacement_database_before_owner_recheck(single_case, tmp_path, monkeypatch):
    case = single_case
    original_db, transport, touched = case["db"].db, case["client"].session.request, []
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"replacement.db")})) as replacement:
        changes, queries = replacement.db.conn.total_changes, []
        replacement.db.conn.set_trace_callback(queries.append)
        def swapped(method, url, **kwargs):
            response = transport(method, url, **kwargs)
            if "/feeBurn?" in url and not touched:
                touched.append(1)
                case["db"].db = replacement.db
            return response
        monkeypatch.setattr(case["client"].session, "request", swapped)
        try:
            with pytest.raises(CChanException):
                acquire(case)
        finally:
            case["db"].db = original_db
        assert touched == [1] and queries == [] and replacement.db.conn.total_changes == changes
        assert case["db"].get_record(case["key"])["open_attempt"] == 0


def test_capacity_callback_cannot_switch_engine_client_then_collect_components(single_case, monkeypatch):
    case = single_case
    transport, touched = case["client"].session.request, []
    def swapped(method, url, **kwargs):
        response = transport(method, url, **kwargs)
        if "/feeBurn?" in url and not touched:
            touched.append(len(case["http_calls"]))
            case["trade"].exchange = object()
        return response
    monkeypatch.setattr(case["client"].session, "request", swapped)
    with pytest.raises(CChanException):
        acquire(case)
    assert len(touched) == 1
    assert not any(name == "fapiPrivateGetOpenOrders" for name, _ in case["http_calls"][touched[0]:])
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


def test_requested_capacity_cannot_silently_fall_back_to_v2_on_a_missing_result(single_case, monkeypatch):
    case = single_case
    collector = Capacity.collect_binance_capacity_evidence
    def missing(*args, **kwargs):
        collector(*args, **kwargs)
        return None
    monkeypatch.setattr(Capacity, "collect_binance_capacity_evidence", missing)
    with pytest.raises(CChanException):
        acquire(case)
    assert case["db"].get_record(case["key"])["open_attempt"] == 0
    assert case["db"].get_order_history(case["key"])["attempts"] == []


def test_v3_original_current_consumer_needs_owned_view_but_no_new_gets(capacity_case):
    case = capacity_case
    assert acquire(case)
    gc.collect()
    row, calls, changes = case["db"].get_record(case["key"]), len(case["http_calls"]), case["db"].db.conn.total_changes
    with pytest.raises(CChanException):
        Prepared.assert_native_prepared_intent_current(case["trade"], case["key"])
    with case["db"].db.transaction():
        assert Prepared.assert_native_prepared_intent_current(case["trade"], case["key"]) is None
    assert case["db"].get_record(case["key"]) == row and case["db"].db.conn.total_changes == changes
    assert len(case["http_calls"]) == calls


@pytest.mark.parametrize("expired", [False, True])
def test_real_cold_sdk_reads_original_v3_without_renewing_capacity(capacity_case, monkeypatch, expired):
    from Trade import NativePreparedClient as Cold
    case = capacity_case
    transport = case["client"].session.request
    def cold_transport(session, method, url, **kwargs):
        assert session is case["trade"].exchange.session
        return transport(method, url, **kwargs)
    monkeypatch.setattr("requests.sessions.Session.request", cold_transport)
    monkeypatch.setattr(Cold, "utc_now_ms", lambda: case["clock"]["now"])
    # Establish the original SDK from its source-owned allowlisted startup,
    # before any v3 intent. The old synthetic warm cache deliberately contains
    # extra `private_unused` metadata which must not be stripped after binding.
    case["trade"].exchange = None
    assert Cold.initialize_native_prepared_client(case["trade"], case["key"], instrument_max_age_ms=2000,
                                                  instrument_max_observation_span_ms=2000) is None
    case["client"] = first = case["trade"].exchange
    assert acquire(case)
    original = read_native_order_transition(case["db"], case["key"])
    row, changes, calls = case["db"].get_record(case["key"]), case["db"].db.conn.total_changes, len(case["http_calls"])
    case["trade"].exchange = None
    if expired:
        case["clock"]["now"] += 2001
        with pytest.raises(CChanException):
            Cold.initialize_native_prepared_client(case["trade"], case["key"], instrument_max_age_ms=2000,
                                                    instrument_max_observation_span_ms=2000)
        assert case["trade"].exchange is None and len(case["http_calls"]) == calls
    else:
        assert Cold.initialize_native_prepared_client(case["trade"], case["key"], instrument_max_age_ms=2000,
                                                      instrument_max_observation_span_ms=2000) is None
        assert case["trade"].exchange is not first
        with case["db"].db.transaction():
            assert Prepared.assert_native_prepared_intent_current(case["trade"], case["key"]) is None
        assert not any(name in {"fapiPrivateGetFeeBurn", "fapiPrivateGetCommissionRate"}
                       for name, _ in case["http_calls"][calls:])
    assert read_native_order_transition(case["db"], case["key"]) == original
    assert case["db"].get_record(case["key"]) == row and case["db"].db.conn.total_changes == changes


def test_cold_reader_will_not_strip_unreconstructible_warm_metadata_after_binding(single_case, monkeypatch):
    from Trade import NativePreparedClient as Cold
    case = single_case
    assert "private_unused" in case["client"].markets["TEST/USDT:USDT"]["info"]
    assert acquire(case)
    original = read_native_order_transition(case["db"], case["key"])
    transport = case["client"].session.request
    def cold_transport(session, method, url, **kwargs):
        assert session is case["trade"].exchange.session
        return transport(method, url, **kwargs)
    monkeypatch.setattr("requests.sessions.Session.request", cold_transport)
    monkeypatch.setattr(Cold, "utc_now_ms", lambda: case["clock"]["now"])
    case["trade"].exchange = None
    with pytest.raises(CChanException):
        Cold.initialize_native_prepared_client(case["trade"], case["key"], instrument_max_age_ms=2000,
                                                instrument_max_observation_span_ms=2000)
    assert case["trade"].exchange is None
    assert read_native_order_transition(case["db"], case["key"]) == original


@pytest.mark.parametrize("damage", ["record", "other_row", "client", "freeze"])
def test_v3_current_keeps_original_row_ledger_client_and_freeze_guards(single_case, damage):
    case = single_case
    assert acquire(case)
    if damage in {"record", "other_row"}:
        key = case["key"] if damage == "record" else case["history_keys"][0]
        case["db"].db.execute(f"UPDATE {case['db'].table} SET unwatch_reason='v3-current-drift' WHERE id=?", (key,))
    elif damage == "client":
        case["client"].options["unexpected"] = True
    else:
        case["db"].reconcile_account(account_context=case["before"]["payload"]["account_context"],
            before_id="0"*64, after_id="1"*64, wallet_ids=[], execution_scan_ids=[])
    calls, changes = len(case["http_calls"]), case["db"].db.conn.total_changes
    with case["db"].db.transaction(), pytest.raises(CChanException):
        Prepared.assert_native_prepared_intent_current(case["trade"], case["key"])
    assert len(case["http_calls"]) == calls and case["db"].db.conn.total_changes == changes


def test_new_source_gets_are_refused_inside_an_outer_writer_transaction(single_case):
    case = single_case
    with case["db"].db.transaction(), pytest.raises(CChanException):
        acquire(case)
    assert case["http_calls"] == [] and case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("ticks", [(0, 1), (0, 1_000_000), (False, 0), (0, True), (10, 9)])
def test_joint_capacity_window_includes_validation_cost_without_extra_business_clock(single_case, monkeypatch, ticks):
    case = single_case
    assert acquire(case)
    root = copy.deepcopy(read_native_order_transition(case["db"], case["key"])["payload"]["root"])
    binding = root["preparation"]
    binding["capacity_policy"]["max_age_ms"] = case["clock"]["now"]-binding["capacity_evidence"]["payload"]["started_ms"]
    monkeypatch.setattr(Prepared, "_monotonic_ns", lambda: 0, raising=False)
    # The exact same isolated scalar window must pass with zero check cost.
    # This private window helper does not grant currentness to changed journal bytes.
    with case["db"].db.transaction():
        Prepared._windows(case["db"], binding, root["boundary"])
    samples = iter(ticks)
    monkeypatch.setattr(Prepared, "_monotonic_ns", lambda: next(samples))
    with case["db"].db.transaction(), pytest.raises(CChanException):
        Prepared._windows(case["db"], binding, root["boundary"])


def test_final_source_reader_clock_cannot_change_the_original_client_on_current_use(single_case, monkeypatch):
    case = single_case
    assert acquire(case)
    touched = []
    def changed():
        touched.append(1)
        case["client"].secret = "FAKE_LATE_CAPACITY_KEY_DRIFT"
        return case["clock"]["now"]
    monkeypatch.setattr(Capacity, "utc_now_ms", changed)
    with case["db"].db.transaction(), pytest.raises(CChanException):
        Prepared.assert_native_prepared_intent_current(case["trade"], case["key"])
    assert touched


def test_final_source_reader_clock_cannot_change_original_client_after_cas(single_case, monkeypatch):
    case = single_case
    touched = []
    def changed():
        if case["db"].get_record(case["key"])["open_attempt"]:
            touched.append(1)
            case["client"].secret = "FAKE_LATE_CAPACITY_KEY_DRIFT"
        return case["clock"]["now"]
    monkeypatch.setattr(Capacity, "utc_now_ms", changed)
    with pytest.raises(CChanException):
        acquire(case)
    assert touched and case["db"].get_record(case["key"])["open_attempt"] == 0
    assert case["db"].get_order_history(case["key"])["attempts"] == []
    assert case["db"].db.query("SELECT * FROM chanpy_native_order_transitions") == []
