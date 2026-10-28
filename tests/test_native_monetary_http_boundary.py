"""Original L2/use-time boundary; no send permit, fabricated claim or real I/O."""
import copy
import json
import sys
import types
from contextlib import closing, contextmanager
from urllib.parse import urlsplit

import pytest
import requests

from Common.ChanException import CChanException

from Trade import NativePreparedIntent as Prepared
from Trade import NativeOrderTransition as Transition
from Trade.db_util import CChanDB
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import capacity_case, single_case
from .test_native_monetary_prepared_intent import acquire
from .test_native_prepared_last import install_last


WINDOW_MS = 60_000  # Explicit fixture choice, never a production default.


def claimed_for_http(case, monkeypatch, *, price=100, post_only=False):
    install_last(case, monkeypatch)
    policy = copy.deepcopy(case["policy"])
    for field in ("max_age_ms", "max_observation_span_ms"):
        policy[field] = {role: WINDOW_MS for role in policy[field]}
    assert acquire(case, price=price, post_only=post_only, policy=policy,
        instrument_max_age_ms=WINDOW_MS, instrument_max_observation_span_ms=WINDOW_MS,
        capacity_max_age_ms=WINDOW_MS, capacity_max_observation_span_ms=WINDOW_MS,
        last_max_age_ms=WINDOW_MS, last_max_observation_span_ms=WINDOW_MS)
    with case["db"].db.transaction():
        context = Prepared._capture_native_claim_context(case["trade"], case["key"])
        assert case["db"].claim_order_submission(case["key"], "open", native_claim=context)
    return Transition.read_native_order_transition(case["db"], case["key"])


def test_original_l2_is_rechecked_with_native_profile_outside_the_writer_lock(capacity_case, monkeypatch):
    case = capacity_case
    claim = claimed_for_http(case, monkeypatch)
    entry = getattr(Prepared, "assert_native_prepared_claim_before_http", None)
    assert callable(entry), "the original Engine has no complete L2/use-time HTTP boundary"
    record, history = case["db"].get_record(case["key"]), case["db"].get_order_history(case["key"])
    calls, changes = len(case["http_calls"]), case["db"].db.conn.total_changes
    assert entry(case["trade"], case["key"]) is None
    assert not case["db"].db.conn.in_transaction and case["db"].db._transaction_depth == 0
    assert case["db"].get_record(case["key"]) == record and case["db"].get_order_history(case["key"]) == history
    assert case["db"].db.conn.total_changes == changes and len(case["created"]) == 3
    assert [name for name, _ in case["http_calls"][calls:]] == [
        "fapiPrivateV3GetBalance", "fapiPrivateGetPositionSideDual", "fapiPrivateGetSymbolConfig"]
    assert Transition.read_native_order_transition(case["db"], case["key"]) == claim


@pytest.mark.parametrize("damage", ["elapsed", "bool", "reverse"])
def test_original_window_budget_includes_the_final_transaction_exit(single_case, monkeypatch, damage):
    case = single_case
    claim = claimed_for_http(case, monkeypatch)
    backend, tick, exits = case["db"].db, [2], []
    original = backend.transaction
    @contextmanager
    def delayed_exit():
        outer = backend._transaction_depth == 0
        with original():
            yield
        if outer:
            exits.append(1)
            if len(exits) == 2:
                tick[0] = {"elapsed": (WINDOW_MS+1)*1_000_000+2, "bool": True, "reverse": 1}[damage]
    monkeypatch.setattr(backend, "transaction", delayed_exit)
    monkeypatch.setattr(Prepared, "_monotonic_ns", lambda: tick[0])
    before = case["db"].get_record(case["key"])
    with pytest.raises(CChanException):
        Prepared.assert_native_prepared_claim_before_http(case["trade"], case["key"])
    assert len(exits) >= 2 and case["db"].get_record(case["key"]) == before
    assert Transition.read_native_order_transition(case["db"], case["key"]) == claim
    assert case["db"].get_account_risk_state(claim["payload"]["root"]["preparation"]["components"]["payload"]["account_context"])["frozen"] is True


@pytest.mark.parametrize("at", ["balance", "mode"])
@pytest.mark.parametrize("replacement", ["database", "connection"])
def test_http_boundary_never_touches_a_replaced_database(single_case, monkeypatch, tmp_path, at, replacement):
    case = single_case
    claimed_for_http(case, monkeypatch)
    chan, backend = case["db"], case["db"].db
    connection, before = backend.conn, chan.get_record(case["key"])
    transport, touched = case["client"].session.request, []
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"foreign-http.db")})) as foreign:
        statements = []
        foreign.db.conn.set_trace_callback(statements.append)
        def changed(method, url, **kwargs):
            response = transport(method, url, **kwargs)
            target = "/fapi/v3/balance" if at == "balance" else "/fapi/v1/positionSide/dual"
            if urlsplit(url).path == target and not touched:
                touched.append(at)
                if replacement == "database":
                    chan.db = foreign.db
                else:
                    backend.conn = foreign.db.conn
            return response
        monkeypatch.setattr(case["client"].session, "request", changed)
        try:
            with pytest.raises(CChanException):
                Prepared.assert_native_prepared_claim_before_http(case["trade"], case["key"])
        finally:
            chan.db, backend.conn = backend, connection
        assert touched == [at] and statements == []
    assert chan.get_record(case["key"]) == before
    assert chan.get_account_risk_state(case["before"]["payload"]["account_context"])["frozen"] is False


@pytest.mark.parametrize("damage", ["account", "exception"])
def test_native_profile_failure_keeps_claim_and_publishes_original_sticky_failure(single_case, monkeypatch, damage):
    case = single_case
    claim = claimed_for_http(case, monkeypatch)
    before, calls = case["db"].get_record(case["key"]), len(case["http_calls"])
    transport = case["client"].session.request
    def changed(method, url, **kwargs):
        response = transport(method, url, **kwargs)
        if urlsplit(url).path == "/fapi/v3/balance":
            if damage == "exception":
                raise RuntimeError("PRIVATE_NATIVE_PROFILE_BODY")
            rows = json.loads(response.text)
            for row in rows:
                row["accountAlias"] = "fake-other-native-account"
            response._content = json.dumps(rows).encode()
        return response
    monkeypatch.setattr(case["client"].session, "request", changed)
    with pytest.raises(CChanException) as error:
        Prepared.assert_native_prepared_claim_before_http(case["trade"], case["key"])
    assert "PRIVATE_" not in str(error.value)
    assert [name for name, _ in case["http_calls"][calls:]] == ["fapiPrivateV3GetBalance"]
    assert case["db"].get_record(case["key"]) == before
    assert Transition.read_native_order_transition(case["db"], case["key"]) == claim
    assert case["db"].get_account_risk_state(case["before"]["payload"]["account_context"])["frozen"] is True


@pytest.mark.parametrize("field", ["root", "check_id", "passed", "checked_ms", "expected"])
def test_http_boundary_has_no_caller_receipt_or_clock_authority(single_case, field):
    case = single_case
    with pytest.raises(TypeError):
        Prepared.assert_native_prepared_claim_before_http(case["trade"], case["key"], **{field: True})
    assert not case["http_calls"] and case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("raw", [False, True])
def test_http_boundary_cannot_adopt_an_existing_writer_transaction(single_case, monkeypatch, raw):
    case = single_case
    claimed_for_http(case, monkeypatch)
    backend, calls = case["db"].db, len(case["http_calls"])
    if raw:
        backend.conn.execute("BEGIN")
        try:
            with pytest.raises(CChanException):
                Prepared.assert_native_prepared_claim_before_http(case["trade"], case["key"])
        finally:
            backend.conn.rollback()
    else:
        with backend.transaction(), pytest.raises(CChanException):
            Prepared.assert_native_prepared_claim_before_http(case["trade"], case["key"])
    assert len(case["http_calls"]) == calls


def test_an_actual_unclaimed_intent_cannot_borrow_the_http_boundary(single_case, monkeypatch):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    before, calls = case["db"].get_record(case["key"]), len(case["http_calls"])
    with pytest.raises(CChanException):
        Prepared.assert_native_prepared_claim_before_http(case["trade"], case["key"])
    assert case["db"].get_record(case["key"]) == before and len(case["http_calls"]) == calls


@pytest.mark.parametrize("name", ["_assert_native_prepared_transition_current", "_read_native_prepared_transition_current"])
def test_http_entry_runtime_is_checked_before_calling_its_consumer(single_case, monkeypatch, name):
    case = single_case
    claimed_for_http(case, monkeypatch)
    before, calls, invoked = case["db"].get_record(case["key"]), len(case["http_calls"]), []
    def changed(*args, **kwargs):
        invoked.append(name)
        raise RuntimeError("PRIVATE_REPLACED_HTTP_CONSUMER")
    monkeypatch.setattr(Prepared, name, changed)
    with pytest.raises(CChanException) as error:
        Prepared.assert_native_prepared_claim_before_http(case["trade"], case["key"])
    assert invoked == [] and len(case["http_calls"]) == calls
    assert "PRIVATE_" not in str(error.value) and case["db"].get_record(case["key"]) == before


@pytest.mark.parametrize("at", ["balance", "mode"])
@pytest.mark.parametrize("damage", ["credential", "sdk", "engine"])
def test_profile_response_drift_stops_before_another_native_call(single_case, monkeypatch, damage, at):
    case = single_case
    claimed_for_http(case, monkeypatch)
    client, engine = case["client"], case["trade"]
    before, calls = case["db"].get_record(case["key"]), len(case["http_calls"])
    transport, touched, invoked = client.session.request, [], []
    def changed(method, url, **kwargs):
        response = transport(method, url, **kwargs)
        target = "/fapi/v3/balance" if at == "balance" else "/fapi/v1/positionSide/dual"
        if urlsplit(url).path == target and not touched:
            touched.append(damage)
            if damage == "credential":
                client.secret = "fake-http-boundary-drift"
            else:
                owner, name = (client, "fetch_leverage") if damage == "sdk" else (engine, "_observe_account")
                original = getattr(owner, name)
                def replaced(self, *args, **kwargs):
                    invoked.append(damage)
                    return original(*args, **kwargs)
                monkeypatch.setattr(owner, name, types.MethodType(replaced, owner))
        return response
    monkeypatch.setattr(client.session, "request", changed)
    with pytest.raises(CChanException):
        Prepared.assert_native_prepared_claim_before_http(engine, case["key"])
    assert touched == [damage] and invoked == []
    expected = ["fapiPrivateV3GetBalance"]+(["fapiPrivateGetPositionSideDual"] if at == "mode" else [])
    assert [name for name, _ in case["http_calls"][calls:]] == expected
    assert case["db"].get_record(case["key"]) == before


@pytest.mark.parametrize("at", ["balance", "mode"])
def test_profile_session_replacement_cannot_reach_a_foreign_transport(single_case, monkeypatch, at):
    case = single_case
    claimed_for_http(case, monkeypatch)
    client, original_session = case["client"], case["client"].session
    transport, touched, foreign_calls = original_session.request, [], []
    before = case["db"].get_record(case["key"])
    with requests.Session() as foreign:
        def unsafe(*args, **kwargs):
            foreign_calls.append(True)
            raise RuntimeError("a foreign transport must never execute")
        monkeypatch.setattr(foreign, "request", unsafe)
        def changed(method, url, **kwargs):
            response = transport(method, url, **kwargs)
            target = "/fapi/v3/balance" if at == "balance" else "/fapi/v1/positionSide/dual"
            if urlsplit(url).path == target and not touched:
                touched.append(at)
                client.session = foreign
            return response
        monkeypatch.setattr(original_session, "request", changed)
        try:
            with pytest.raises(CChanException):
                Prepared.assert_native_prepared_claim_before_http(case["trade"], case["key"])
        finally:
            client.session = original_session
        assert touched == [at] and foreign_calls == []
    assert case["db"].get_record(case["key"]) == before


@pytest.mark.parametrize("target", ["own", "other"])
def test_last_input_read_cannot_hide_a_late_ledger_write(single_case, monkeypatch, target):
    case = single_case
    guard, state = case["trade"].opening_inputs, {"armed": False, "touched": []}
    original_clock = guard.now_ms
    def clock():
        frame = sys._getframe()
        inside_final = False
        while frame is not None:
            inside_final |= frame.f_code.co_name == "final_check" and frame.f_globals.get("__name__") == Prepared.__name__
            frame = frame.f_back
        if state["armed"] and inside_final and not state["touched"]:
            state["touched"].append(target)
            key = case["key"] if target == "own" else case["history_keys"][0]
            case["db"].db.execute(f"UPDATE {case['db'].table} SET unwatch_reason='last local read drift' WHERE id=?", (key,))
        return original_clock()
    monkeypatch.setattr(guard, "now_ms", clock)
    claim = claimed_for_http(case, monkeypatch)
    before = [case["db"].get_record(key) for key in [case["key"], *case["history_keys"]]]
    transport = case["client"].session.request
    def changed(method, url, **kwargs):
        response = transport(method, url, **kwargs)
        if urlsplit(url).path == "/fapi/v1/symbolConfig":
            state["armed"] = True
        return response
    monkeypatch.setattr(case["client"].session, "request", changed)
    with pytest.raises(CChanException):
        Prepared.assert_native_prepared_claim_before_http(case["trade"], case["key"])
    assert state["touched"] == [target]
    assert [case["db"].get_record(key) for key in [case["key"], *case["history_keys"]]] == before
    assert Transition.read_native_order_transition(case["db"], case["key"]) == claim
