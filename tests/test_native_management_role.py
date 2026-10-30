"""The approved management role starts locked, not as generic send permission."""
from dataclasses import FrozenInstanceError

import pytest

from Common.ChanException import CChanException
from Trade.CCXTTradeEngine import CCCXTTradeEngine
from Trade import SafetyPolicy
from Trade import NativePreparation
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import single_case
from .test_m6_trade import make_signal


def configuration(mode="live"):
    return {"exchange": "binance", "mode": mode, "testnet": mode == "testnet", "default_type": "swap",
        "api_key": "fake-key", "secret": "fake-secret", "position_mode": "one_way",
        "position_side": "BOTH", "margin_mode": "cross", "leverage": 3}


def test_cold_management_role_does_not_mint_general_order_permission(store, monkeypatch):
    db, _ = store
    environment = {"CHANPY_KILL_SWITCH": "YES"}
    monkeypatch.setattr("requests.sessions.Session.request", lambda *a, **k: pytest.fail("empty role must perform no HTTP"))
    engine = CCCXTTradeEngine(db, ccxt_conf=configuration(), trade_conf={}, environ=environment,
        management_only=True, push_msg=False)
    assert type(engine.safety_policy) is SafetyPolicy.ManagementOnlyTradingSafetyPolicy
    assert engine.exchange is None and engine.restore() == []
    with pytest.raises(FrozenInstanceError):
        engine.safety_policy.mode = "dry_run"
    with pytest.raises(CChanException, match="管理专用"):
        engine.safety_policy.assert_order_allowed()
    with pytest.raises(CChanException, match="管理专用"):
        engine.assert_order_mutation_allowed()
    # The new role cannot be selected by ordinary configuration or unlock.
    with pytest.raises(CChanException):
        CCCXTTradeEngine(db, ccxt_conf=configuration(), trade_conf={"management_only": True},
            environ=environment, push_msg=False)


@pytest.mark.parametrize("action", ["add", "cover", "partial", "poll", "prepare", "place", "cancel"])
@pytest.mark.parametrize("mode", ["dry_run", "testnet", "live"])
def test_management_role_without_this_operation_proof_refuses_before_side_effects(store, monkeypatch, action, mode):
    db, _ = store
    record = db.get_record(db.add_signal(make_signal()))
    history = db.get_order_history(record["id"])
    engine = CCCXTTradeEngine(db, ccxt_conf=configuration(mode), trade_conf={}, environ={}, management_only=True, push_msg=False)
    monkeypatch.setattr("requests.sessions.Session.request", lambda *a, **k: pytest.fail("no operation proof permits no HTTP"))
    calls = []
    monkeypatch.setattr(engine.quota_gen, "get_quota", lambda *a: calls.append("quota") or 1)
    monkeypatch.setattr(engine, "rate_limit", lambda: calls.append("rate_limit"))
    before = db.db.conn.total_changes
    actions = {"add": lambda: engine.add_trade(record, 100), "cover": lambda: engine.cover_trade(record, 100, "fake"),
        "partial": lambda: engine.close_partial_open(record, 100, "fake"), "poll": lambda: engine.poll_orders(),
        "prepare": lambda: engine.prepare_order(record["stock_code"], 1, 100, reduce_only=True, record=record),
        "place": lambda: engine.place_order(record["stock_code"], False, 1, 100, reduce_only=True),
        "cancel": lambda: engine.cancel_order(record["stock_code"], "7")}
    with pytest.raises(CChanException, match="管理专用"):
        actions[action]()
    assert calls == [] and db.db.conn.total_changes == before and not engine.sim_state.orders
    assert db.get_record(record["id"]) == record and db.get_order_history(record["id"]) == history


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}])
def test_management_role_flag_is_explicit_bool_not_a_caller_permission(store, value):
    with pytest.raises(CChanException):
        CCCXTTradeEngine(store[0], ccxt_conf=configuration(), trade_conf={}, environ={}, management_only=value)


def test_management_role_cannot_be_combined_with_query_only(store):
    with pytest.raises(CChanException):
        CCCXTTradeEngine(store[0], ccxt_conf=configuration(), trade_conf={}, environ={}, management_only=True, query_only=True)


@pytest.mark.parametrize("field,value", [("mode", "unknown"), ("testnet", True), ("api_key", ""),
    ("secret", None), ("exchange", "unknown"), ("default_type", "option"), ("api_key", True)])
def test_management_constructor_reuses_original_read_route_structure(store, field, value):
    config = {**configuration(), field: value}
    with pytest.raises(CChanException):
        CCCXTTradeEngine(store[0], ccxt_conf=config, trade_conf={}, environ={}, management_only=True)


def test_management_role_cannot_be_promoted_by_mutable_public_policy_or_environment(store):
    config, environment = configuration(), {"CHANPY_KILL_SWITCH": "YES"}
    engine = CCCXTTradeEngine(store[0], ccxt_conf=config, trade_conf={}, environ=environment, management_only=True)
    environment.clear()
    environment["CHANPY_LIVE_TRADING_UNLOCK"] = "I_ACCEPT_REAL_ORDERS"
    config["mode"] = "dry_run"
    engine.safety_policy = SafetyPolicy.build_trading_safety_policy({"mode": "dry_run"}, {}, environ={})
    with pytest.raises(CChanException, match="管理专用"):
        engine.assert_order_mutation_allowed()
    with pytest.raises(CChanException, match="管理专用"):
        engine.place_order("TEST/USDT:USDT", False, 1, 100, reduce_only=True)


@pytest.mark.parametrize("name", ["build_management_only_safety_policy", "build_query_only_safety_policy"])
def test_original_runtime_pins_shared_existing_risk_policy_builders(single_case, monkeypatch, name):
    engine = single_case["trade"]
    NativePreparation._selected_runtime(engine, engine.opening_inputs, engine.safety_policy)
    monkeypatch.setattr(SafetyPolicy, name, lambda *a, **k: None)
    with pytest.raises(CChanException):
        NativePreparation._selected_runtime(engine, engine.opening_inputs, engine.safety_policy)
