"""Actual configured cycle and fresh CLI processes; only public update I/O is fake."""
import hashlib
import json
import os
import subprocess
import sys
import shutil
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path

import pytest
from Common.ChanException import CChanException

from Config.EnvConfig import CEnv
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.PaperState import CPersistentPaperState
from Trade.Script.Deployment import CDeployment, publish_deployment
from Trade.Script.RunTradeCycle import run_trade_cycle
from Trade.db_util import CChanDB
from .test_deployment_workflow import deployment_model, future_candidate
from .test_linear_paper_account import paper_account, CODE
from .test_linear_paper_engine import paper_engine
from .test_configured_paper_runtime import publish_quotes

ROOT = Path(__file__).resolve().parents[1]
CHILD = r'''
import runpy, sys
from Common import KLineTime
module, stamp = sys.argv[1], int(sys.argv[2])
KLineTime.utc_now_ms = lambda: stamp
sys.argv = ["Trade.Script.RunTradeStage", module]
runpy.run_module("Trade.Script.RunTradeStage", run_name="__main__")
'''


@pytest.fixture()
def workflow(deployment_model, tmp_path, monkeypatch):
    manifest = tmp_path/"deployment.json"
    original_model = Path(deployment_model["model"].GetModelPath())
    shutil.copytree(original_model.parent, tmp_path/"models")
    publish_deployment(manifest, tmp_path/"models"/original_model.name, candidate_score=0, entry_score=0, post_score=0)
    deployed = CDeployment(manifest)
    chan, signal = future_candidate(deployment_model)
    now = signal.sig_klu.close_ms+900_000
    deployed.prepare_signal(chan, signal, observed_ms=now)
    chan[0].cbsp_strategy.publish_signals(chan, 0, signals=[signal])
    price = (Decimal(str(signal.open_thred))*Decimal("1.001" if signal.is_buy else "0.999")/Decimal("0.1")).to_integral_value(
        rounding=ROUND_CEILING if signal.is_buy else ROUND_FLOOR)*Decimal("0.1")
    config = {"db": {"type": "sqlite", "sqlite_path": str(tmp_path/"trade.db")},
        "offline_data": {"sqlite_path": str(deployment_model["root"]/"kline.db"), "source_identity": deployed.source_identity},
        "ccxt": {"mode": "dry_run", "default_type": "swap", "exchange": "binance"},
        "snapshot_engine": "sina", "notify": {"backend": "none"},
        "trade": {"deployment_manifest": str(manifest), "bench_price": float(price)*0.035, "quote_max_age_ms": 1000,
            "open_para": {}, "paper": {"server_path": str(tmp_path/"server.json"),
                "quote_path": str(tmp_path/"quotes.json"), "quote_max_age_ms": 1000}}}
    path = tmp_path/"runtime.json"
    path.write_bytes(canonical_bytes(config))
    db = CChanDB(db_conf=config["db"])
    key = db.add_signal(signal)
    with CPersistentPaperState.create(tmp_path/"server.json", account=paper_account(mode="one_way"), database=config["db"]["sqlite_path"]) as server:
        engine = paper_engine(db, state=server.state)
        engine.set_sim_fill_plan(engine.make_client_order_id(db.get_record(key), "open"), [0.01, 0.03])
    document = publish_quotes(tmp_path/"quotes.json", now)
    bid, ask = (price-Decimal("0.1"), price) if signal.is_buy else (price, price+Decimal("0.1"))
    document["payload"]["quotes"][0].update(bid=str(bid), ask=str(ask), mark=str(price), last=float(price))
    document["payload_sha256"] = hashlib.sha256(canonical_bytes(document["payload"])).hexdigest()
    (tmp_path/"quotes.json").write_bytes(canonical_bytes(document))
    monkeypatch.setenv("CHANPY_CONFIG", str(path))
    CEnv.reset_instance()
    try:
        yield db, path, key, now, tmp_path
    finally:
        db.close()
        CEnv.reset_instance()


def actual_dispatch(now, trace):
    def command(module, args, *, cwd, env):
        if module == "OfflineData.ccxt_update":
            trace.append((module, 0, "fixture already contains raw rows"))
            return 0
        result = subprocess.run([sys.executable, "-c", CHILD, module, str(now)], cwd=cwd, env=env,
            capture_output=True, text=True, timeout=60)
        trace.append((module, result.returncode, result.stdout+result.stderr))
        return result.returncode
    return command


def test_actual_default_cycle_reaches_the_same_persistent_paper_order(workflow):
    db, path, key, now, root = workflow
    trace = []
    result = run_trade_cycle(path, report_path=root/"first.jsonl", command=actual_dispatch(now, trace), now_ms=lambda: now)
    assert result["status"] == "completed", (result, trace)
    row = db.get_record(key)
    assert row["open_attempt"] == 1 and row["current_qty"] == 0.01
    assert json.loads(row["open_order_contract"])["schema"] == "chan-paper-order-v3"
    assert json.loads(row["snapshot_before"])["opening_inputs"]["schema"] == "chan-opening-input-check-v2"
    with CPersistentPaperState.open(root/"server.json", database=root/"trade.db") as server:
        assert len(server.state.orders) == 1 and server.state.paper_account.position_quantity(f"chan_trade:{key}") == Decimal("0.01")
    assert all(code == 0 for _, code, _ in trace)
    assert all(row["observation"]["state"] == "complete" for row in result["notifications"] if not row["stage"].startswith("update:")), "actual CLI stages must publish their own summaries"
    trace.clear()
    repeated = run_trade_cycle(path, report_path=root/"repeat.jsonl", command=actual_dispatch(now, trace), now_ms=lambda: now)
    assert repeated["status"] == "completed", (repeated, trace)
    assert db.get_record(key)["open_attempt"] == 1 and db.get_record(key)["current_qty"] == 0.03
    with CPersistentPaperState.open(root/"server.json", database=root/"trade.db") as server:
        assert len(server.state.orders) == 1
    manifest = json.loads((root/"deployment.json").read_bytes())
    model = (root/manifest["model_path"]).resolve()
    model.write_bytes(model.read_bytes()+b"broken-model-fixture")
    quote_file = root/"quotes.json"
    quote = json.loads(quote_file.read_bytes())
    quote["payload"]["at_ms"] = now+10
    quote["payload_sha256"] = hashlib.sha256(canonical_bytes(quote["payload"])).hexdigest()
    quote_file.write_bytes(canonical_bytes(quote))
    trace.clear()
    failed = run_trade_cycle(path, report_path=root/"model-failed.jsonl", command=actual_dispatch(now+10, trace), now_ms=lambda: now+10)
    assert failed["status"] == "failed" and failed["failed_stage"] == "scope", (failed, trace)
    assert "Trade.Script.MakeOpenTrade" not in [module for module, _, _ in trace]
    assert db.get_record(key)["current_qty"] == 0
    with CPersistentPaperState.open(root/"server.json", database=root/"trade.db") as server:
        assert len(server.state.orders) == 2


@pytest.mark.parametrize("mode", ["missing_profile", "loosened_policy"])
def test_software_order_cannot_drop_its_reader_or_loosen_original_quote_age(workflow, mode):
    from Trade.Script.TradeRuntime import configured_trade_engine
    db, path, key, now, root = workflow
    trace = []
    result = run_trade_cycle(path, report_path=root/"first.jsonl", command=actual_dispatch(now, trace), now_ms=lambda: now)
    assert result["status"] == "completed", (result, trace)
    row = db.get_record(key)
    if mode == "missing_profile":
        with CPersistentPaperState.open(root/"server.json", database=root/"trade.db") as server:
            engine = paper_engine(db, state=server.state)
            assert engine.query_order(CODE, row["open_order_id"]).filled == 0.01
            with pytest.raises(CChanException):
                engine.cover_trade(row, None, "cannot invent a fresh software observation")
    else:
        config = json.loads(path.read_bytes())
        config["trade"]["paper"]["quote_max_age_ms"] = 5000
        path.write_bytes(canonical_bytes(config))
        with configured_trade_engine(db, env=CEnv(str(path)), now_ms=lambda: now+1001, push_msg=False) as engine:
            engine.api_interval = 0
            assert engine.query_order(CODE, row["open_order_id"]).filled == 0.01
            with pytest.raises(CChanException):
                engine.cover_trade(row, None, "old order keeps its original age bound")
            assert engine.paper_inputs.issues
    assert db.get_record(key)["current_qty"] == 0.01
