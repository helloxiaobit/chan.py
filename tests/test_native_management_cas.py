"""Management must bind original SQL dependencies before its original CAS."""
import json

import pytest

from Common.ChanException import CChanException
from Trade import NativeManagement as Management
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import single_case
from .test_native_management_interval import unchanged_database
from .test_native_management_request import terminal_case, request_options


def test_original_sql_dependencies_reject_late_replacement_before_foreign_calls(single_case, monkeypatch):
    case = single_case
    engine, state, _, _ = terminal_case(case, monkeypatch)
    database = case["db"].db
    methods = [(database, name) for name in ("query", "query_one", "transaction", "execute")]
    methods += [(case["db"], name) for name in ("get_record", "get_order_history", "_order_write",
        "acquire_close_intent", "claim_order_submission")]
    targets = methods+[(type(owner), name) for owner, name in methods]
    targets += [(database.conn, "row_factory"), (database.conn, "text_factory")]
    targets += [(Management, "_management_database_bindings")]
    with Management._native_management_close_context(engine, case["key"], .0199, 300, **request_options(case)) as context:
        before, reads, sources = unchanged_database(case), list(state["requests"]), list(case["http_calls"])
        violations = []
        for owner, name in targets:
            invoked, sql, rejected = [], [], False
            def foreign(*args, **kwargs):
                invoked.append(name)
                raise AssertionError("a foreign SQL dependency must not run")
            with database.transaction():
                database.conn.set_trace_callback(sql.append)
                try:
                    with monkeypatch.context() as patch:
                        patch.setattr(owner, name, foreign)
                        try:
                            Management._assert_native_management_context_current(engine, context)
                        except CChanException:
                            rejected = True
                finally:
                    database.conn.set_trace_callback(None)
            if not rejected or invoked or sql:
                violations.append({"owner": type(owner).__name__, "name": name,
                    "rejected": rejected, "foreign_calls": len(invoked), "sql_count": len(sql), "first_sql": sql[:1]})
        assert violations == [], json.dumps(violations)
        assert unchanged_database(case) == before
        assert state["requests"] == reads and case["http_calls"] == sources


def test_foreign_sql_dependencies_present_before_collection_never_run(single_case, monkeypatch):
    case = single_case
    engine, state, _, _ = terminal_case(case, monkeypatch)
    database = case["db"].db
    methods = [(database, name) for name in ("query", "query_one", "transaction", "execute")]
    methods += [(case["db"], name) for name in ("get_record", "get_order_history", "_order_write",
        "acquire_close_intent", "claim_order_submission")]
    targets = methods+[(type(owner), name) for owner, name in methods]
    targets += [(database.conn, "row_factory"), (database.conn, "text_factory")]
    before, reads, sources = unchanged_database(case), list(state["requests"]), list(case["http_calls"])
    for owner, name in targets:
        invoked, sql = [], []
        def foreign(*args, **kwargs):
            invoked.append(name)
            raise AssertionError("foreign SQL dependency must not establish its own baseline")
        database.conn.set_trace_callback(sql.append)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(owner, name, foreign)
                with pytest.raises(CChanException):
                    with Management._native_management_close_context(engine, case["key"], .0199, 300, **request_options(case)):
                        pytest.fail("a foreign database binding was accepted")
        finally:
            database.conn.set_trace_callback(None)
        assert invoked == [] and sql == []
    assert unchanged_database(case) == before
    assert state["requests"] == reads and case["http_calls"] == sources


def test_foreign_transaction_body_metadata_is_not_called_by_the_binding_check(single_case, monkeypatch):
    case = single_case
    engine, state, _, _ = terminal_case(case, monkeypatch)
    database = case["db"].db
    inspected, sql = [], []
    class ForeignBody:
        def __getattribute__(self, name):
            inspected.append(name)
            raise AssertionError("foreign wrapper metadata must not execute")
    with Management._native_management_close_context(engine, case["key"], .0199, 300, **request_options(case)) as context:
        before, reads, sources = unchanged_database(case), list(state["requests"]), list(case["http_calls"])
        with database.transaction():
            database.conn.set_trace_callback(sql.append)
            try:
                with monkeypatch.context() as patch:
                    patch.setattr(type(database).transaction, "__wrapped__", ForeignBody())
                    with pytest.raises(CChanException):
                        Management._assert_native_management_context_current(engine, context)
            finally:
                database.conn.set_trace_callback(None)
        assert inspected == [] and sql == []
        assert unchanged_database(case) == before
        assert state["requests"] == reads and case["http_calls"] == sources
