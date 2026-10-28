"""Actual SDK execution functions/routes must remain original, bottom fake only."""
import ast
import inspect
import types

import pytest

from Common.ChanException import CChanException
from Trade import NativePreparedIntent as Prepared
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import single_case
from .test_native_monetary_prepared_intent import acquire
from .test_native_prepared_last import install_last
from .test_native_monetary_engine import claimed_order


@pytest.mark.parametrize("body", [
    "try:\n        def owned(): pass\n    except Exception: pass",
    "if True:\n        def owned(): pass",
    "with source():\n        def owned(): pass",
])
def test_fresh_identity_ast_resolves_control_flow_without_entering_another_function(body):
    source = "def outer():\n    "+body+"\n    def unrelated():\n        def owned(): pass\n"
    node = Prepared.Prepare._function_node(ast.parse(source), "outer.<locals>.owned")
    assert isinstance(node, ast.FunctionDef) and node.name == "owned" and node.lineno == 3


@pytest.mark.parametrize("body", [
    "def unrelated():\n        def owned(): pass",
    "if True:\n        def owned(): pass\n    else:\n        def owned(): pass",
])
def test_fresh_identity_ast_refuses_missing_or_ambiguous_lexical_functions(body):
    with pytest.raises(CChanException):
        Prepared.Prepare._function_node(ast.parse("def outer():\n    "+body+"\n"), "outer.<locals>.owned")


@pytest.mark.parametrize("name", ["create_order", "create_order_request", "parse_order", "safe_order",
    "fetch_order", "cancel_order", "sign", "request", "fetch2", "fetch", "fapiPrivatePostOrder",
    "prepare_request_headers", "set_headers", "check_proxy_url_settings", "check_proxy_settings",
    "check_conflicting_proxies", "value_is_defined",
    "handle_option_integer_and_params", "handle_option_and_params", "check_option_integer"])
def test_monetary_acquire_refuses_altered_sdk_execution_before_any_source(single_case, monkeypatch, name):
    case = single_case
    install_last(case, monkeypatch)
    invoked = []
    def changed(*args, **kwargs):
        invoked.append(1)
        raise RuntimeError("PRIVATE_MUTATED_SDK_MUST_NOT_EXECUTE")
    monkeypatch.setattr(case["client"], name, types.MethodType(changed, case["client"]))
    with pytest.raises(CChanException) as error:
        acquire(case)
    assert invoked == [] and not case["http_calls"]
    assert "PRIVATE_" not in str(error.value)
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("options", [{"maxRetriesOnFailure": 1}, {"defaultMaxRetriesOnFailure": 1},
    {"maxRetriesOnFailure": -1}, {"maxRetriesOnFailure": False}])
def test_order_route_retry_policy_must_be_exact_zero_before_any_monetary_source(single_case, monkeypatch, options):
    case = single_case
    install_last(case, monkeypatch)
    case["client"].options["order"] = dict(options)
    before = case["db"].get_record(case["key"])
    with pytest.raises(CChanException):
        acquire(case)
    assert not case["http_calls"] and case["db"].get_record(case["key"]) == before


def test_new_risk_retry_policy_does_not_block_existing_order_query(single_case, monkeypatch):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    case["client"].options["order"] = {"maxRetriesOnFailure": 1}
    result = case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert result.order_id == "123456" and result.filled == .02
    assert [method for method, _ in state["requests"]] == ["GET"]
    assert case["db"].get_record(case["key"])["open_order_status"] == "submitting"


@pytest.mark.parametrize("callback_name", ["proxyUrlCallback", "proxy_url_callback", "httpProxyCallback", "http_proxy_callback",
    "httpsProxyCallback", "https_proxy_callback", "socksProxyCallback", "socks_proxy_callback", "proxy"])
def test_unproven_proxy_callback_is_rejected_before_any_new_risk_source(single_case, monkeypatch, callback_name):
    case = single_case
    install_last(case, monkeypatch)
    invoked = []
    def callback(*args, **kwargs):
        invoked.append(callback_name)
        return None
    monkeypatch.setattr(case["client"], callback_name, callback)
    before = case["db"].get_record(case["key"])
    with pytest.raises(CChanException):
        acquire(case)
    assert invoked == [] and case["http_calls"] == [] and case["db"].get_record(case["key"]) == before


@pytest.mark.parametrize("callback_name", ["proxyUrlCallback", "proxy"])
def test_a_callback_added_after_l1_invalidates_current_without_renewing_it(single_case, monkeypatch, callback_name):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    before, calls, invoked = case["db"].get_record(case["key"]), list(case["http_calls"]), []
    with case["db"].db.transaction():
        assert Prepared.assert_native_prepared_intent_current(case["trade"], case["key"]) is None
    def callback(*args, **kwargs):
        invoked.append(callback_name)
        return None
    monkeypatch.setattr(case["client"], callback_name, callback)
    with case["db"].db.transaction(), pytest.raises(CChanException):
        Prepared.assert_native_prepared_intent_current(case["trade"], case["key"])
    assert invoked == [] and case["http_calls"] == calls and case["db"].get_record(case["key"]) == before


@pytest.mark.parametrize("callback_name", ["proxyUrlCallback", "proxy_url_callback", "httpProxyCallback", "http_proxy_callback",
    "httpsProxyCallback", "https_proxy_callback", "socksProxyCallback", "socks_proxy_callback", "proxy"])
def test_existing_native_order_query_refuses_unproven_fetch_callbacks_before_transport(single_case, monkeypatch, callback_name):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    invoked = []
    def callback(*args, **kwargs):
        invoked.append(callback_name)
        return None
    monkeypatch.setattr(case["client"], callback_name, callback)
    before, history = case["db"].get_record(case["key"]), case["db"].get_order_history(case["key"])
    with pytest.raises(CChanException):
        case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert invoked == [] and state["requests"] == []
    assert case["db"].get_record(case["key"]) == before and case["db"].get_order_history(case["key"]) == history


@pytest.mark.parametrize("name", ["_read_native_prepared_claim_before_http", "_native_prepared_claim_http_use",
    "_assert_native_adapter_retry_policy", "_native_http_fetch_delegate", "_assert_native_fetch_policy"])
def test_actual_transport_dependency_is_checked_before_a_mutated_function_can_execute(single_case, monkeypatch, name):
    case = single_case
    install_last(case, monkeypatch)
    invoked = []
    def changed(*args, **kwargs):
        invoked.append(True)
        raise RuntimeError("PRIVATE_MUTATED_TRANSPORT_DEPENDENCY")
    monkeypatch.setattr(Prepared, name, changed, raising=False)
    with pytest.raises(CChanException):
        acquire(case)
    assert invoked == [] and case["http_calls"] == []
    assert case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("damage", ["nonzero", "unbounded", "negative", "bool", "raw_zero", "unknown_adapter"])
def test_order_adapter_policy_is_checked_before_any_monetary_source(single_case, monkeypatch, damage):
    from requests.adapters import BaseAdapter
    from urllib3.util.retry import Retry

    case = single_case
    install_last(case, monkeypatch)
    session = case["client"].session
    adapter = session.get_adapter(case["client"].urls["api"]["fapiPrivate"]+"/order")
    if damage == "unknown_adapter":
        session.mount("https://fapi.binance.com/", BaseAdapter())
    elif damage == "raw_zero":
        monkeypatch.setattr(adapter, "max_retries", 0)
    else:
        retry = Retry(total=0)
        monkeypatch.setattr(retry, "total", {"nonzero": 1, "unbounded": None, "negative": -1, "bool": False}[damage])
        monkeypatch.setattr(adapter, "max_retries", retry)
    before = case["db"].get_record(case["key"])
    with pytest.raises(CChanException):
        acquire(case)
    assert case["http_calls"] == [] and case["db"].get_record(case["key"]) == before


@pytest.mark.parametrize("damage", ["instance", "class_code"])
def test_request_adapter_selector_is_verified_before_it_can_execute(single_case, monkeypatch, damage):
    import requests

    case = single_case
    install_last(case, monkeypatch)
    session, invoked = case["client"].session, []
    monkeypatch.setattr(session, "_fake_selector_invocations", invoked, raising=False)
    def changed(self, url):
        self._fake_selector_invocations.append(True)
        raise RuntimeError("PRIVATE_UNTRUSTED_ADAPTER_SELECTOR")
    if damage == "instance":
        monkeypatch.setattr(session, "get_adapter", types.MethodType(changed, session))
    else:
        monkeypatch.setattr(requests.Session.get_adapter, "__code__", changed.__code__)
    before = case["db"].get_record(case["key"])
    with pytest.raises(CChanException) as error:
        acquire(case)
    assert invoked == [] and case["http_calls"] == []
    assert "PRIVATE_" not in str(error.value) and case["db"].get_record(case["key"]) == before


def test_unrelated_adapter_policy_does_not_veto_the_original_order_route(single_case, monkeypatch):
    from requests.adapters import HTTPAdapter

    case = single_case
    install_last(case, monkeypatch)
    case["client"].session.mount("https://unrelated.invalid/", HTTPAdapter(max_retries=1))
    assert acquire(case)
    assert case["db"].get_record(case["key"])["open_attempt"] == 1


def test_new_risk_adapter_policy_does_not_block_an_existing_l2_query(single_case, monkeypatch):
    from urllib3.util.retry import Retry

    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    for adapter in case["client"].session.adapters.values():
        monkeypatch.setattr(adapter, "max_retries", Retry(total=1, read=1, allowed_methods=None))
    result = case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert result.order_id == "123456" and result.filled == .02
    assert [method for method, _ in state["requests"]] == ["GET"]


@pytest.mark.parametrize("field,value", [("path", "algoOrder"), ("api", "sapi"), ("method", "GET"), ("config", {"cost": 999})])
def test_order_endpoint_descriptor_cannot_change_its_installed_route(single_case, monkeypatch, field, value):
    case = single_case
    install_last(case, monkeypatch)
    descriptor = inspect.getattr_static(type(case["client"]), "fapiPrivatePostOrder")
    monkeypatch.setattr(descriptor, field, value)
    with pytest.raises(CChanException):
        acquire(case)
    assert not case["http_calls"] and case["db"].get_record(case["key"])["open_attempt"] == 0


def test_loaded_class_code_is_not_proved_by_a_shared_sdk_reference(single_case, monkeypatch):
    case = single_case
    install_last(case, monkeypatch)
    function = case["client"].create_order.__func__
    def changed(self, *args, **kwargs):
        raise RuntimeError("PRIVATE_CHANGED_CLASS_CODE")
    monkeypatch.setattr(function, "__code__", changed.__code__)
    with pytest.raises(CChanException):
        acquire(case)
    assert not case["http_calls"] and case["db"].get_record(case["key"])["open_attempt"] == 0


def test_mutable_sdk_default_is_not_accepted_as_installed_source(single_case, monkeypatch):
    case = single_case
    install_last(case, monkeypatch)
    function = case["client"].create_order.__func__
    monkeypatch.setattr(function, "__defaults__", (None, {"portfolioMargin": True}))
    with pytest.raises(CChanException):
        acquire(case)
    assert not case["http_calls"] and case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("stage", ["intent", "claim"])
@pytest.mark.parametrize("name", ["create_order_request", "sign", "fapiPrivatePostOrder"])
def test_original_current_reader_checks_actual_sdk_again_after_acquisition(single_case, monkeypatch, stage, name):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    if stage == "claim":
        with case["db"].db.transaction():
            context = Prepared._capture_native_claim_context(case["trade"], case["key"])
            assert case["db"].claim_order_submission(case["key"], "open", native_claim=context)
    before, calls = case["db"].get_record(case["key"]), list(case["http_calls"])
    def changed(*args, **kwargs):
        pytest.fail("the modified execution function must not run")
    monkeypatch.setattr(case["client"], name, types.MethodType(changed, case["client"]))
    with case["db"].db.transaction(), pytest.raises(CChanException):
        Prepared._assert_native_prepared_transition_current(case["trade"], case["key"], stage=stage)
    assert case["db"].get_record(case["key"]) == before and case["http_calls"] == calls


@pytest.mark.parametrize("name", ["create_order_request", "sign", "fapiPrivatePostOrder"])
def test_existing_order_management_refuses_a_changed_sdk_before_query(single_case, monkeypatch, name):
    case = single_case
    state, record, _ = claimed_order(case, monkeypatch)
    def changed(*args, **kwargs):
        pytest.fail("management must reject before any modified SDK call")
    monkeypatch.setattr(case["client"], name, types.MethodType(changed, case["client"]))
    with pytest.raises(CChanException):
        case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert state["requests"] == [] and case["db"].get_record(case["key"]) == record


@pytest.mark.parametrize("name", ["sign", "request"])
def test_cold_sdk_is_checked_before_its_first_instrument_source(single_case, monkeypatch, name):
    case = single_case
    _, record, _ = claimed_order(case, monkeypatch)
    case["trade"].exchange = None
    invoked = []
    def changed(*args, **kwargs):
        invoked.append(1)
        raise RuntimeError("PRIVATE_COLD_SDK_MUST_NOT_EXECUTE")
    monkeypatch.setattr(type(case["client"]), name, changed)
    with pytest.raises(CChanException) as error:
        case["trade"].query_order(record["stock_code"], client_order_id=record["open_client_order_id"])
    assert invoked == [] and case["trade"].exchange is None
    assert "PRIVATE_" not in str(error.value)
    assert case["db"].get_record(case["key"]) == record


@pytest.mark.parametrize("owner_key,name", [("client", "create_order"), ("client", "fapiPrivatePostOrder"),
    ("trade", "get_exchange"), ("trade", "place_order"), ("db", "_order_write")])
def test_a_callable_metadata_dto_is_not_an_original_bound_method(single_case, monkeypatch, owner_key, name):
    case = single_case
    install_last(case, monkeypatch)
    owner = case[owner_key]
    original = getattr(owner, name)
    class MetadataDTO:
        def __init__(self):
            # Instance data avoids Python binding this fake __func__ itself.
            self.__self__, self.__func__ = original.__self__, original.__func__
        def __call__(self, *args, **kwargs):
            return original(*args, **kwargs)
    monkeypatch.setattr(owner, name, MetadataDTO())
    with pytest.raises(CChanException):
        acquire(case)
    assert not case["http_calls"] and case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("name", ["create_order", "create_order_request", "cancel_order"])
def test_another_original_sdk_function_cannot_replace_the_installed_method_name(single_case, monkeypatch, name):
    case = single_case
    install_last(case, monkeypatch)
    client = case["client"]
    owner = next(cls for cls in type(client).__mro__ if name in vars(cls))
    # A shared reference instance sees this same replacement. Its source is
    # genuinely installed CCXT code, but it is not the installed name binding.
    monkeypatch.setattr(owner, name, client.fetch_order.__func__)
    with pytest.raises(CChanException):
        acquire(case)
    assert not case["http_calls"] and case["db"].get_record(case["key"])["open_attempt"] == 0
