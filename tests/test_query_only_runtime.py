"""Cold original RestoreOrders is separate from permission to mutate orders."""
import json
from dataclasses import FrozenInstanceError

import pytest

from Common.ChanException import CChanException
from Config.EnvConfig import CEnv
from Trade.CCXTTradeEngine import CCCXTTradeEngine
from Trade.SafetyPolicy import QueryOnlyTradingSafetyPolicy, build_trading_safety_policy
from Trade.Script import RestoreOrders
from Trade.Script.TradeRuntime import configured_trade_engine
from Trade import NativePreparation
from Trade import SafetyPolicy
from .test_execution_store import store
from .test_m6_trade import make_signal
from .test_native_capacity_prepared_intent import single_case
from .test_native_admission_interval import explicit_path_environment
from .test_configured_paper_runtime import runtime


def test_original_restore_initializes_under_kill_without_new_risk_receipt_or_unlock(store, tmp_path, monkeypatch, capsys):
    _, conf = store
    config = {"db": conf, "ccxt": {"exchange": "binance", "mode": "live", "testnet": False,
        "default_type": "swap", "api_key": "fake-key", "secret": "fake-secret", "leverage": 3,
        "position_mode": "one_way", "position_side": "BOTH", "margin_mode": "cross"}, "trade": {}, "notify": {"backend": "none"}}
    path = tmp_path/"query-only.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(CEnv, "_instance", CEnv(str(path)))
    monkeypatch.setenv("CHANPY_KILL_SWITCH", "YES")
    monkeypatch.delenv("CHANPY_LIVE_TRADING_UNLOCK", raising=False)
    monkeypatch.setattr("requests.sessions.Session.request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP for an empty recovery set")))
    assert RestoreOrders.main() == 0, "cold read-only recovery must not require new-risk permission"
    output = capsys.readouterr()
    assert "restored=0 unresolved=0" in output.out


@pytest.mark.parametrize("action", ["add", "cover", "partial", "poll", "prepare", "place", "cancel"])
@pytest.mark.parametrize("mode", ["dry_run", "testnet", "live"])
def test_query_only_role_refuses_every_original_order_change_before_side_effects(store, monkeypatch, action, mode):
    db, _ = store
    key = db.add_signal(make_signal())
    record, before = db.get_record(key), db.get_order_history(key)
    config = {"exchange": "binance", "mode": mode, "testnet": mode == "testnet", "default_type": "swap",
              "api_key": "fake-key", "secret": "fake-secret"}
    engine = CCCXTTradeEngine(db, ccxt_conf=config, trade_conf={}, query_only=True, push_msg=False)
    monkeypatch.setattr("requests.sessions.Session.request", lambda *a, **k: pytest.fail("query-only mutations must make no HTTP"))
    calls = []
    monkeypatch.setattr(engine.quota_gen, "get_quota", lambda *a: calls.append("quota") or 1)
    monkeypatch.setattr(engine, "rate_limit", lambda: calls.append("rate_limit"))
    changes = db.db.conn.total_changes
    actions = {"add": lambda: engine.add_trade(record, 100), "cover": lambda: engine.cover_trade(record, 100, "fake"),
        "partial": lambda: engine.close_partial_open(record, 100, "fake"), "poll": lambda: engine.poll_orders(),
        "prepare": lambda: engine.prepare_order(record["stock_code"], 1, 100),
        "place": lambda: engine.place_order(record["stock_code"], True, 1, 100),
        "cancel": lambda: engine.cancel_order(record["stock_code"], "7")}
    with pytest.raises(CChanException, match="查单专用"):
        actions[action]()
    assert calls == []
    assert db.db.conn.total_changes == changes
    assert db.get_record(key) == record and db.get_order_history(key) == before
    assert not engine.sim_state.orders


def test_query_role_cannot_be_promoted_by_restoring_environment_or_changing_config(store):
    db, _ = store
    config = {"exchange": "binance", "mode": "live", "testnet": False, "default_type": "swap",
        "api_key": "fake-key", "secret": "fake-secret"}
    environment = {"CHANPY_KILL_SWITCH": "YES"}
    engine = CCCXTTradeEngine(db, ccxt_conf=config, trade_conf={}, environ=environment, query_only=True)
    assert type(engine.safety_policy) is QueryOnlyTradingSafetyPolicy
    environment.clear()
    environment["CHANPY_LIVE_TRADING_UNLOCK"] = "I_ACCEPT_REAL_ORDERS"
    config["mode"] = "dry_run"
    with pytest.raises(FrozenInstanceError):
        engine.safety_policy.mode = "dry_run"
    with pytest.raises(CChanException, match="查单专用"):
        engine.safety_policy.assert_order_allowed()
    with pytest.raises(CChanException):
        CCCXTTradeEngine(db, ccxt_conf={**config, "mode": "live"}, trade_conf={}, environ=environment)


@pytest.mark.parametrize("action", ["prepare", "place", "cancel", "add"])
def test_replacing_public_policy_cannot_promote_the_original_query_engine(store, action):
    db, _ = store
    key = db.add_signal(make_signal())
    record = db.get_record(key)
    engine = CCCXTTradeEngine(db, ccxt_conf={"mode": "dry_run"}, trade_conf={}, query_only=True, push_msg=False)
    engine.safety_policy = build_trading_safety_policy({"mode": "dry_run"}, {}, environ={})
    actions = {"prepare": lambda: engine.prepare_order(record["stock_code"], 1, 100),
        "place": lambda: engine.place_order(record["stock_code"], True, 1, 100),
        "cancel": lambda: engine.cancel_order(record["stock_code"], "7"),
        "add": lambda: engine.add_trade(record, 100)}
    changes = db.db.conn.total_changes
    with pytest.raises(CChanException, match="查单专用"):
        actions[action]()
    assert not engine.sim_state.orders and db.get_record(key) == record
    assert db.db.conn.total_changes == changes


@pytest.mark.parametrize("field,value", [("mode", "unknown"), ("testnet", True), ("api_key", ""),
    ("secret", None), ("exchange", "unknown"), ("default_type", "option"), ("api_key", True)])
def test_query_role_preserves_explicit_native_route_and_credential_structure(store, field, value):
    config = {"exchange": "binance", "mode": "live", "testnet": False, "default_type": "swap",
        "api_key": "fake-key", "secret": "fake-secret", field: value}
    with pytest.raises(CChanException):
        CCCXTTradeEngine(store[0], ccxt_conf=config, trade_conf={}, query_only=True)


@pytest.mark.parametrize("value", [None, 1, "true", []])
def test_query_only_constructor_does_not_coerce_a_role_flag(store, value):
    with pytest.raises(CChanException):
        CCCXTTradeEngine(store[0], ccxt_conf={"mode": "dry_run"}, trade_conf={}, query_only=value)


def test_original_native_runtime_reader_pins_the_new_mutation_role_dispatch(single_case, monkeypatch):
    engine = single_case["trade"]
    NativePreparation._selected_runtime(engine, engine.opening_inputs, engine.safety_policy)
    monkeypatch.setattr(engine, "assert_order_mutation_allowed", lambda: None)
    with pytest.raises(CChanException):
        NativePreparation._selected_runtime(engine, engine.opening_inputs, engine.safety_policy)


@pytest.mark.parametrize("name", ["_configured_mode", "_assert_private_configuration"])
def test_original_native_runtime_reader_pins_the_shared_configuration_checks(single_case, monkeypatch, name):
    engine = single_case["trade"]
    NativePreparation._selected_runtime(engine, engine.opening_inputs, engine.safety_policy)
    monkeypatch.setattr(SafetyPolicy, name, lambda *args: None)
    with pytest.raises(CChanException):
        NativePreparation._selected_runtime(engine, engine.opening_inputs, engine.safety_policy)


@pytest.mark.parametrize("name", ["query_only", "read_only"])
def test_user_trade_config_cannot_select_or_weaken_the_constructor_role(store, name):
    config = {"exchange": "binance", "mode": "live", "testnet": False, "default_type": "swap",
              "api_key": "fake-key", "secret": "fake-secret"}
    with pytest.raises(CChanException):
        CCCXTTradeEngine(store[0], ccxt_conf=config, trade_conf={name: True}, environ={})


@pytest.mark.parametrize("action", ["add", "cover", "partial", "poll", "prepare", "place", "cancel"])
def test_query_only_persistent_paper_context_cannot_change_orders_or_server_bytes(runtime, action):
    from pathlib import Path
    db, path, config = runtime
    record = db.get_record(db.add_signal(make_signal()))
    with configured_trade_engine(db, env=CEnv(str(path)), query_only=True, now_ms=lambda: 1001, push_msg=False) as engine:
        server = Path(config["trade"]["paper"]["server_path"])
        original, changes = server.read_bytes(), db.db.conn.total_changes
        report = engine.get_sim_account_report()
        actions = {"add": lambda: engine.add_trade(record, 100), "cover": lambda: engine.cover_trade(record, 100, "fake"),
            "partial": lambda: engine.close_partial_open(record, 100, "fake"), "poll": lambda: engine.poll_orders(),
            "prepare": lambda: engine.prepare_order(record["stock_code"], 1, 100),
            "place": lambda: engine.place_order(record["stock_code"], True, 1, 100),
            "cancel": lambda: engine.cancel_order(record["stock_code"], "7")}
        with pytest.raises(CChanException, match="查单专用"):
            actions[action]()
        assert server.read_bytes() == original and db.db.conn.total_changes == changes
        assert engine.get_sim_account_report() == report and db.get_record(record["id"]) == record
