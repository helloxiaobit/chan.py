"""Original managed-close observations are scoped to one live invocation."""
import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from Common.ChanException import CChanException
from Trade import NativeManagement as Management
from Trade import NativeOrderBoundary as Boundary
from Trade import NativePreparation as Prepare
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import single_case
from .test_native_management_interval import unchanged_database
from .test_native_management_request import terminal_case, request_options, last_price_300


def context_api():
    assert callable(getattr(Management, "_native_management_close_context", None)), "owned same-call management context is missing"
    assert callable(getattr(Management, "_assert_native_management_context_current", None)), "owned management context recheck is missing"
    return Management


def test_owned_management_context_boundaries_exist():
    context_api()


def test_real_owned_context_rechecks_without_source_recollection_or_permission(single_case, monkeypatch):
    api = context_api()
    case = single_case
    engine, state, _, _ = terminal_case(case, monkeypatch)
    with api._native_management_close_context(engine, case["key"], .0199, 300, **request_options(case)) as context:
        assert not hasattr(context, "__dict__")
        before, reads, sources = unchanged_database(case), list(state["requests"]), list(case["http_calls"])
        document = json.loads(api._MANAGEMENT_CONTEXTS[context][2])
        assert document["payload"]["operation_authorized"] is document["payload"]["native_quantity_verified"] is False
        with case["db"].db.transaction():
            assert api._assert_native_management_context_current(engine, context) is None
        assert unchanged_database(case) == before and state["requests"] == reads and case["http_calls"] == sources
        with pytest.raises(CChanException):
            engine.assert_order_mutation_allowed()
    with pytest.raises(CChanException):
        api._assert_native_management_context_current(engine, context)


def test_copies_json_other_engine_and_foreign_thread_fail_before_any_sql(single_case, monkeypatch):
    api = context_api()
    case = single_case
    engine, state, _, _ = terminal_case(case, monkeypatch)
    with api._native_management_close_context(engine, case["key"], .0199, 300, **request_options(case)) as context:
        before, reads, sql = unchanged_database(case), list(state["requests"]), []
        case["db"].db.conn.set_trace_callback(sql.append)
        try:
            for supplied in (copy.copy(context), copy.deepcopy(context), type(context)(),
                    json.loads(api._MANAGEMENT_CONTEXTS[context][2]), {"passed": True}, True):
                with pytest.raises(CChanException):
                    api._assert_native_management_context_current(engine, supplied)
                assert sql == []
            with pytest.raises(CChanException):
                api._assert_native_management_context_current(copy.copy(engine), context)
            assert sql == []
            def foreign():
                with pytest.raises(CChanException):
                    api._assert_native_management_context_current(engine, context)
            with ThreadPoolExecutor(max_workers=1) as worker:
                worker.submit(foreign).result()
            assert sql == []
        finally:
            case["db"].db.conn.set_trace_callback(None)
        assert unchanged_database(case) == before and state["requests"] == reads


def test_original_owned_transaction_is_required_without_consuming_the_context(single_case, monkeypatch):
    api = context_api()
    case = single_case
    engine, _, _, _ = terminal_case(case, monkeypatch)
    with api._native_management_close_context(engine, case["key"], .0199, 300, **request_options(case)) as context:
        with pytest.raises(CChanException):
            api._assert_native_management_context_current(engine, context)
        with case["db"].db.transaction():
            assert api._assert_native_management_context_current(engine, context) is None


def test_late_owner_changes_fail_without_invoking_foreign_sql_or_transport(single_case, monkeypatch):
    api = context_api()
    case = single_case
    engine, state, _, _ = terminal_case(case, monkeypatch)
    database = case["db"].db
    with api._native_management_close_context(engine, case["key"], .0199, 300, **request_options(case)) as context:
        before, reads, sources = unchanged_database(case), list(state["requests"]), list(case["http_calls"])
        foreign_calls = []
        def foreign(*args, **kwargs):
            foreign_calls.append(1)
            raise AssertionError("foreign transport must not run")
        with sqlite3.connect(":memory:") as other:
            other_sql = []
            other.set_trace_callback(other_sql.append)
            for owner, name, value in ((engine, "chan_db", copy.copy(case["db"])),
                    (database, "conn", other), (case["db"], "table", "not_the_original_table"),
                    (engine, "exchange", copy.copy(engine.exchange)), (engine.exchange, "session", copy.copy(engine.exchange.session)),
                    (engine.exchange.session, "request", foreign), (engine, "safety_policy", object())):
                with database.transaction():
                    original_sql = []
                    database.conn.set_trace_callback(original_sql.append)
                    try:
                        with monkeypatch.context() as patch:
                            patch.setattr(owner, name, value)
                            with pytest.raises(CChanException):
                                api._assert_native_management_context_current(engine, context)
                        assert original_sql == [] and other_sql == [] and foreign_calls == []
                    finally:
                        database.conn.set_trace_callback(None)
        assert unchanged_database(case) == before and state["requests"] == reads and case["http_calls"] == sources


def test_called_source_guard_replacements_are_rejected_before_the_foreign_callable(single_case, monkeypatch):
    api = context_api()
    case = single_case
    engine, state, _, _ = terminal_case(case, monkeypatch)
    with api._native_management_close_context(engine, case["key"], .0199, 300, **request_options(case)) as context:
        before, reads, sources, violations = unchanged_database(case), list(state["requests"]), list(case["http_calls"]), []
        for module, name in ((api, "_source_runtime"), (Boundary, "_same_database"), (Prepare, "_client_binding"),
                (Prepare, "_implementation")):
            invoked = []
            def foreign(*args, **kwargs):
                invoked.append(1)
                raise AssertionError("a replaced source guard must never execute")
            with case["db"].db.transaction():
                with monkeypatch.context() as patch:
                    patch.setattr(module, name, foreign)
                    with pytest.raises(CChanException):
                        api._assert_native_management_context_current(engine, context)
            if invoked:
                violations.append(module.__name__+":"+name)
        assert violations == []
        assert unchanged_database(case) == before and state["requests"] == reads and case["http_calls"] == sources


def test_recheck_retains_original_wallet_age_and_never_resets_monotonic_or_utc_windows(single_case, monkeypatch):
    api = context_api()
    case = single_case
    engine, state, _, _ = terminal_case(case, monkeypatch)
    options = copy.deepcopy(request_options(case))
    options["policy"]["max_age_ms"]["wallet"] = 50
    with api._native_management_close_context(engine, case["key"], .0199, 300, **options) as context:
        before, reads, sources = unchanged_database(case), list(state["requests"]), list(case["http_calls"])
        with case["db"].db.transaction():
            assert api._assert_native_management_context_current(engine, context) is None
            with monkeypatch.context() as patch:
                patch.setattr(api, "_monotonic_ns", lambda: 51_000_000)
                with pytest.raises(CChanException):
                    api._assert_native_management_context_current(engine, context)
            with monkeypatch.context() as patch:
                patch.setattr(api, "utc_now_ms", lambda: case["clock"]["now"]-1)
                with pytest.raises(CChanException):
                    api._assert_native_management_context_current(engine, context)
        assert unchanged_database(case) == before and state["requests"] == reads and case["http_calls"] == sources


def test_original_policy_and_other_record_remain_bound_in_the_owned_view(single_case, monkeypatch):
    api = context_api()
    case = single_case
    engine, state, _, _ = terminal_case(case, monkeypatch)
    options = request_options(case)
    with api._native_management_close_context(engine, case["key"], .0199, 300, **options) as context:
        reads, sources = list(state["requests"]), list(case["http_calls"])
        with case["db"].db.transaction():
            previous = options["policy"]["max_age_ms"]["wallet"]
            options["policy"]["max_age_ms"]["wallet"] += 1
            with pytest.raises(CChanException):
                api._assert_native_management_context_current(engine, context)
            options["policy"]["max_age_ms"]["wallet"] = previous
            other = next(row for row in case["db"].db.query(f"SELECT * FROM {case['db'].table} ORDER BY id") if row["id"] != case["key"])
            case["db"].db.execute(f"UPDATE {case['db'].table} SET current_qty=current_qty+0.001 WHERE id=?", (other["id"],))
            with pytest.raises(CChanException):
                api._assert_native_management_context_current(engine, context)
        assert state["requests"] == reads and case["http_calls"] == sources


def test_cold_market_context_owns_last_and_expires_on_exception_without_a_write(single_case, monkeypatch):
    api = context_api()
    case = single_case
    engine, state, _, _ = terminal_case(case, monkeypatch, cold=True)
    last_calls = last_price_300(engine, monkeypatch)
    with pytest.raises(RuntimeError, match="caller aborted"):
        with api._native_management_close_context(engine, case["key"], .0199, None, **request_options(case)) as context:
            assert len(last_calls) == 1
            before, reads, sources = unchanged_database(case), list(state["requests"]), list(case["http_calls"])
            with case["db"].db.transaction():
                assert api._assert_native_management_context_current(engine, context) is None
            assert len(last_calls) == 1 and unchanged_database(case) == before
            assert state["requests"] == reads and case["http_calls"] == sources
            raise RuntimeError("caller aborted")
    assert context not in api._MANAGEMENT_CONTEXTS
    with pytest.raises(CChanException):
        api._assert_native_management_context_current(engine, context)
