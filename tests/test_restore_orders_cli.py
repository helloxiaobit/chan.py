"""复用实际 SQLite 与既有恢复状态机，不把未知订单当可重新提交。"""
from Trade.CCXTTradeEngine import CCCXTTradeEngine
from Trade.Script.RestoreOrders import restore_orders
from .test_trade_state_machine import acquire_open, trade_db
from .test_m6_trade import make_signal
from Trade.OpenQuotaGen import CBenchPriceQuotaGen


def test_unknown_server_state_is_reported_without_claim_fill_or_resubmission(trade_db):
    key = acquire_open(trade_db)
    before = trade_db.get_record(key)
    engine = CCCXTTradeEngine(trade_db, ccxt_conf={"mode": "dry_run"}, trade_conf={}, environ={}, push_msg=False)
    stat = restore_orders(trade_db, engine)
    assert stat == {"restored": 0, "unresolved": [key]}
    assert trade_db.get_record(key) == before and engine.sim_state.orders == {} and engine.exchange is None


def test_no_recoverable_orders_is_a_completed_empty_check_not_a_synthetic_fill(trade_db):
    engine = CCCXTTradeEngine(trade_db, ccxt_conf={"mode": "dry_run"}, trade_conf={}, environ={}, push_msg=False)
    assert restore_orders(trade_db, engine) == {"restored": 0, "unresolved": []}


def test_known_partial_can_be_restored_without_being_mistaken_for_an_unknown_order(trade_db):
    engine = CCCXTTradeEngine(trade_db, quota_gen=CBenchPriceQuotaGen(1000),
        ccxt_conf={"mode": "dry_run"}, trade_conf={}, environ={}, push_msg=False)
    engine.api_interval = 0
    key = trade_db.add_signal(make_signal())
    client = engine.make_client_order_id(trade_db.get_record(key), "open")
    engine.set_sim_fill_plan(client, [0, 4, 10])
    engine.add_trade(trade_db.get_record(key), 100)
    assert restore_orders(trade_db, engine) == {"restored": 1, "unresolved": []}
    assert trade_db.get_record(key)["current_qty"] == 4
    assert restore_orders(trade_db, engine) == {"restored": 1, "unresolved": []}
    assert trade_db.get_record(key)["current_qty"] == 10 and len(engine.sim_state.orders) == 1


def test_cli_exits_nonzero_for_a_real_unresolved_sqlite_intent(trade_db, tmp_path):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    key = acquire_open(trade_db)
    before = trade_db.get_record(key)
    path = tmp_path/"runtime.json"
    path.write_text(json.dumps({"db": {"type": "sqlite", "sqlite_path": str(tmp_path/"state-machine.db")},
        "ccxt": {"mode": "dry_run"}, "notify": {"backend": "none"}}))
    result = subprocess.run([sys.executable, "-m", "Trade.Script.RestoreOrders"],
        cwd=Path(__file__).resolve().parents[1], env={**os.environ, "CHANPY_CONFIG": str(path)},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and "unresolved=1" in result.stdout
    assert trade_db.get_record(key) == before
