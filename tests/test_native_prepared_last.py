"""Actual original prepare handle and SDK with bottom-only fake Last V2."""
import copy
import gc
import json
import weakref
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit

import pytest
from requests import Response

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade import NativePreparedIntent as Prepared
from Trade import NativeLastPrice as Last
from Trade import NativePreparation as Prepare
from Trade import NativeInstrumentCurrent as Instrument
from Trade.db_util import CChanDB
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import capacity_case, single_case


def collect(case, context, **changes):
    entry = getattr(Prepared, "collect_prepared_binance_last_prices", None)
    assert callable(entry), "Last collector is not attached to the original live prepare context"
    return entry(case["trade"], context, **({"max_age_ms": 2000, "max_observation_span_ms": 2000} | changes))


def install_last(case, monkeypatch):
    original, calls = case["client"].session.request, []
    def transport(method, url, **kwargs):
        parsed = urlsplit(url)
        if parsed.path != "/fapi/v2/ticker/price": return original(method, url, **kwargs)
        assert method == "GET" and parsed.hostname == "fapi.binance.com" and kwargs["verify"] is True
        assert not case["db"].db.conn.in_transaction
        params = parse_qs(parsed.query)
        assert set(params) == {"symbol"}
        case["clock"]["now"] += 1
        calls.append(params["symbol"][0])
        response = Response()
        response.status_code, response.reason, response.url = 200, "OK", url
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps({"symbol": params["symbol"][0], "price": "102.12345678901234567890123456789",
                                      "time": case["clock"]["now"]}).encode()
        return response
    monkeypatch.setattr(case["client"].session, "request", transport)
    monkeypatch.setattr(Last, "utc_now_ms", lambda: case["clock"]["now"])
    monkeypatch.setattr(Last, "_monotonic_ns", lambda: 0)
    monkeypatch.setattr(Prepared, "_monotonic_ns", lambda: 0)
    return calls


@pytest.mark.parametrize("price", [100, None])
def test_original_unconsumed_context_owns_full_scope_last_without_a_new_intent_or_prepare(capacity_case, monkeypatch, price):
    case = capacity_case
    calls = install_last(case, monkeypatch)
    context = Prepare._capture_native_prepare_context(case["trade"], case["key"], .1, price)
    entry = Prepare._PREPARED[context]
    before = canonical_bytes(case["db"].get_record(case["key"]))
    changes, orders, private_calls = case["db"].db.conn.total_changes, len(case["created"]), list(case["http_calls"])
    document = collect(case, context)
    assert document["schema"] == Last.SCHEMA
    assert calls == ["ALTUSDT", "TESTUSDT"] and document["payload"]["requests"] == 2
    assert document["payload"]["economics_complete"] is document["payload"]["native_admission_verified"] is False
    assert Prepare._PREPARED[context] is entry and len(entry) == 3
    assert case["db"].db.conn.total_changes == changes and len(case["created"]) == orders
    assert case["http_calls"] == private_calls
    assert canonical_bytes(case["db"].get_record(case["key"])) == before


@pytest.mark.parametrize("damage", ["record", "sdk_options", "engine_owner", "input_owner", "table"])
def test_terminal_code_check_cannot_leave_a_change_after_the_original_view(single_case, monkeypatch, damage):
    case = single_case
    calls = install_last(case, monkeypatch)
    context = Prepare._capture_native_prepare_context(case["trade"], case["key"], .1, 100)
    implementation, touched = Prepared._implementation, []
    def changed():
        value = implementation()
        touched.append(1)
        if len(touched) == 3:
            if damage == "record":
                case["db"].db.execute(f"UPDATE {case['db'].table} SET unwatch_reason='late-last' WHERE id=?", (case["key"],))
            elif damage == "sdk_options":
                case["client"].options["late-last-binding"] = True
            elif damage == "engine_owner":
                case["trade"].chan_db = object()
            elif damage == "input_owner":
                case["trade"].opening_inputs = object()
            else:
                case["db"].table = "unapproved_last_table"
        return value
    monkeypatch.setattr(Prepared, "_implementation", changed)
    with pytest.raises(CChanException):
        collect(case, context)
    assert len(touched) == 3 and calls == ["ALTUSDT", "TESTUSDT"]
    assert len(case["created"]) == 3


@pytest.mark.parametrize("field", ["max_age_ms", "max_observation_span_ms"])
@pytest.mark.parametrize("bad", [None, True, -1, "2000", 0.5, 2**63])
def test_explicit_budgets_reject_before_any_source_get(single_case, monkeypatch, field, bad):
    case = single_case
    calls = install_last(case, monkeypatch)
    context = Prepare._capture_native_prepare_context(case["trade"], case["key"], .1, 100)
    changes = case["db"].db.conn.total_changes
    with pytest.raises(CChanException):
        collect(case, context, **{field: bad})
    assert not calls and case["db"].db.conn.total_changes == changes


@pytest.mark.parametrize("field", ["markets", "source", "checked_at_ms", "passed", "client", "receipt"])
def test_no_caller_source_scope_clock_or_approval_replaces_owned_collection(single_case, monkeypatch, field):
    case = single_case
    calls = install_last(case, monkeypatch)
    context = Prepare._capture_native_prepare_context(case["trade"], case["key"], .1, 100)
    with pytest.raises(TypeError):
        collect(case, context, **{field: True})
    assert not calls


@pytest.mark.parametrize("damage", ["json", "copy", "new", "other_engine", "already_bound", "removed"])
def test_only_the_original_unbound_live_handle_can_collect(single_case, monkeypatch, damage):
    case = single_case
    calls = install_last(case, monkeypatch)
    context = Prepare._capture_native_prepare_context(case["trade"], case["key"], .1, 100)
    entry = Prepare._PREPARED[context]
    handle = context
    if damage == "json": handle = json.loads(entry[1])
    elif damage == "copy": handle = copy.copy(context)
    elif damage == "new": handle = Prepare._NativePrepareContext()
    elif damage == "other_engine": case = {**case, "trade": copy.copy(case["trade"])}
    elif damage == "already_bound": Prepare._PREPARED[context] = (*entry, b'{}')
    else: del Prepare._PREPARED[context]
    with pytest.raises(CChanException):
        collect(case, handle)
    assert not calls


def test_collection_does_not_keep_a_dead_prepare_handle_alive(single_case, monkeypatch):
    case = single_case
    install_last(case, monkeypatch)
    context = Prepare._capture_native_prepare_context(case["trade"], case["key"], .1, 100)
    reference = weakref.ref(context)
    count = len(Prepare._PREPARED)
    assert collect(case, context)["payload"]["native_admission_verified"] is False
    del context
    gc.collect()
    assert reference() is None and len(Prepare._PREPARED) < count


@pytest.mark.parametrize("raw", [False, True])
def test_outer_transactions_refuse_before_source_io(single_case, monkeypatch, raw):
    case = single_case
    calls = install_last(case, monkeypatch)
    context = Prepare._capture_native_prepare_context(case["trade"], case["key"], .1, 100)
    if raw:
        case["db"].db.conn.execute("BEGIN")
        try:
            with pytest.raises(CChanException): collect(case, context)
        finally:
            case["db"].db.conn.rollback()
    else:
        with case["db"].db.transaction(), pytest.raises(CChanException):
            collect(case, context)
    assert not calls


@pytest.mark.parametrize("damage", ["record", "sdk_options", "scope", "engine_config", "policy", "runtime"])
@pytest.mark.parametrize("point", ["before", "after_get", "final_clock"])
def test_original_context_stays_current_across_collection(single_case, monkeypatch, damage, point):
    case = single_case
    calls = install_last(case, monkeypatch)
    context = Prepare._capture_native_prepare_context(case["trade"], case["key"], .1, 100)
    def change():
        if damage == "record":
            case["db"].db.execute(f"UPDATE {case['db'].table} SET unwatch_reason='last-drift' WHERE id=?", (case["key"],))
        elif damage == "sdk_options": case["client"].options["last-drift"] = True
        elif damage == "scope": case["trade"].opening_inputs._scope["code_list"] = ["TEST/USDT:USDT"]
        elif damage == "engine_config": case["trade"].ccxt_conf["leverage"] = 5
        elif damage == "policy": case["trade"].safety_policy.environ["CHANPY_KILL_SWITCH"] = "YES"
        else: monkeypatch.setattr(case["trade"], "prepare_order", lambda *a, **kw: pytest.fail("must not prepare again"))
    if point == "before": change()
    elif point == "after_get":
        transport = case["client"].session.request
        def changed(method, url, **kwargs):
            result = transport(method, url, **kwargs)
            if len(calls) == 2: change()
            return result
        monkeypatch.setattr(case["client"].session, "request", changed)
    else:
        def clock():
            change()
            return case["clock"]["now"]
        monkeypatch.setattr(Prepared, "utc_now_ms", clock)
    with pytest.raises(CChanException): collect(case, context)
    assert calls == ([] if point == "before" else ["ALTUSDT", "TESTUSDT"])
    assert len(case["created"]) == 3


@pytest.mark.parametrize("point", ["collector", "reader", "clock"])
def test_each_external_callback_must_preserve_db_owner_before_further_sql(single_case, monkeypatch, tmp_path, point):
    case = single_case
    install_last(case, monkeypatch)
    context = Prepare._capture_native_prepare_context(case["trade"], case["key"], .1, 100)
    original = case["db"].db
    replacement = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"last-replacement.db")})
    queries, touched = [], []
    replacement.db.conn.set_trace_callback(queries.append)
    changes = replacement.db.conn.total_changes
    module, name = ((Prepared, "utc_now_ms") if point == "clock" else
                    (Last, "collect_binance_last_prices" if point == "collector" else "verify_binance_last_prices"))
    operation = getattr(module, name)
    def changed(*args, **kwargs):
        result = operation(*args, **kwargs)
        touched.append(1)
        case["db"].db = replacement.db
        return result
    monkeypatch.setattr(module, name, changed)
    try:
        with pytest.raises(CChanException): collect(case, context)
        assert touched and not queries and replacement.db.conn.total_changes == changes
    finally:
        case["db"].db = original
        replacement.close()


@pytest.mark.parametrize("damage", ["engine", "table", "sdk", "input_owner", "policy_owner", "clock_owner"])
def test_last_owned_view_exit_is_still_inside_original_ownership(single_case, monkeypatch, damage):
    case = single_case
    install_last(case, monkeypatch)
    context = Prepare._capture_native_prepare_context(case["trade"], case["key"], .1, 100)
    transaction, count = case["db"].db.transaction, []
    @contextmanager
    def changed():
        outer = not case["db"].db.conn.in_transaction
        with transaction(): yield
        if not outer: return
        count.append(1)
        if len(count) == 2:
            if damage == "engine": case["trade"].chan_db = object()
            elif damage == "table": case["db"].table = "unapproved_exit_table"
            elif damage == "sdk": case["client"].options["last-owned-exit"] = True
            elif damage == "input_owner": case["trade"].opening_inputs = object()
            elif damage == "policy_owner": case["trade"].safety_policy = object()
            else: case["trade"].opening_inputs.now_ms = lambda: case["clock"]["now"]
    monkeypatch.setattr(case["db"].db, "transaction", changed)
    with pytest.raises(CChanException): collect(case, context)
    assert len(count) == 2


@pytest.mark.parametrize("damage", ["record", "scope", "input_owner", "policy_owner"])
def test_terminal_cache_projection_is_followed_by_the_original_local_view(single_case, monkeypatch, damage):
    case = single_case
    install_last(case, monkeypatch)
    context = Prepare._capture_native_prepare_context(case["trade"], case["key"], .1, 100)
    projection, count = Instrument._cache_view, []
    def changed(*args, **kwargs):
        result = projection(*args, **kwargs)
        count.append(1)
        if len(count) == 2:
            if damage == "record":
                case["db"].db.execute(f"UPDATE {case['db'].table} SET unwatch_reason='last-cache-drift' WHERE id=?", (case["key"],))
            elif damage == "scope": case["trade"].opening_inputs._scope["code_list"] = ["TEST/USDT:USDT"]
            elif damage == "input_owner": case["trade"].opening_inputs = object()
            else: case["trade"].safety_policy = object()
        return result
    monkeypatch.setattr(Instrument, "_cache_view", changed)
    with pytest.raises(CChanException): collect(case, context)
    assert len(count) == 2


@pytest.mark.parametrize("extra_ns", [0, 1])
def test_final_view_work_uses_exact_age_and_rounds_fractional_milliseconds_up(single_case, monkeypatch, extra_ns):
    case = single_case
    install_last(case, monkeypatch)
    context = Prepare._capture_native_prepare_context(case["trade"], case["key"], .1, 100)
    collector, started, samples = Last.collect_binance_last_prices, [], []
    def observed(*args, **kwargs):
        result = collector(*args, **kwargs)
        started.append(result["payload"]["started_ms"])
        return result
    def elapsed():
        samples.append(1)
        return 0 if len(samples) == 1 else (2000-(case["clock"]["now"]-started[0]))*1_000_000+extra_ns
    monkeypatch.setattr(Last, "collect_binance_last_prices", observed)
    monkeypatch.setattr(Prepared, "_monotonic_ns", elapsed)
    if extra_ns:
        with pytest.raises(CChanException): collect(case, context)
    else:
        assert collect(case, context)["payload"]["native_admission_verified"] is False
    assert len(samples) == 2


@pytest.mark.parametrize("samples", [(True, 1), (0, True), (1, 0), (-1, 0), (0, 0.5)])
def test_terminal_elapsed_clock_is_typed_and_monotonic(single_case, monkeypatch, samples):
    case = single_case
    install_last(case, monkeypatch)
    context = Prepare._capture_native_prepare_context(case["trade"], case["key"], .1, 100)
    values = iter(samples)
    monkeypatch.setattr(Prepared, "_monotonic_ns", lambda: next(values))
    with pytest.raises(CChanException): collect(case, context)


def test_terminal_original_view_exit_cost_cannot_reuse_an_earlier_fresh_business_clock(single_case, monkeypatch):
    case = single_case
    install_last(case, monkeypatch)
    context = Prepare._capture_native_prepare_context(case["trade"], case["key"], .1, 100)
    transaction, count, elapsed_ns = case["db"].db.transaction, [], [0]
    @contextmanager
    def delayed():
        outer = not case["db"].db.conn.in_transaction
        with transaction(): yield
        if not outer: return
        count.append(1)
        if len(count) == 2: elapsed_ns[0] += 2_001_000_000
    monkeypatch.setattr(case["db"].db, "transaction", delayed)
    monkeypatch.setattr(Prepared, "_monotonic_ns", lambda: elapsed_ns[0])
    with pytest.raises(CChanException): collect(case, context)
    assert len(count) == 2
