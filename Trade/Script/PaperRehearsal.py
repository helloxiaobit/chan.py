"""Bounded synthetic-only C6 rehearsal; no keys, transport, search or live mode.

python -m Trade.Script.PaperRehearsal --output <new-directory>
The phase switch is for the runner's serial fresh processes, not a daemon.
"""
import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import sys
from contextlib import contextmanager
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from ModelStrategy.parameterEvaluate.artifact import write_json_once

ROOT = Path(__file__).resolve().parents[2]
CODE = "DEMO/USDT:USDT"
SOURCE = {"exchange": "binance", "market_type": "swap", "settle": "USDT", "price_type": "contract"}
HOUR, START = 3_600_000, 1_577_836_800_000
PHASES = ("entry", "exit", "verify")


def _fail():
    raise CChanException("合成离线演练未完成；保留原产物，不新增风险或覆盖重试", ErrCode.TRADE_UNLOCK_FAIL) from None


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path):
    raw = path.read_bytes()
    result = json.loads(raw)
    if canonical_bytes(result) != raw:
        _fail()
    return result


@contextmanager
def _environment(root):
    from Config.EnvConfig import CEnv
    original = os.environ.get("CHANPY_CONFIG")
    os.environ["CHANPY_CONFIG"] = str(root/"runtime.json")
    CEnv.reset_instance()
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("CHANPY_CONFIG", None)
        else:
            os.environ["CHANPY_CONFIG"] = original
        CEnv.reset_instance()


def _synthetic_rows():
    # Fixed demonstration, deliberately no market downloads or parameter input.
    randomizer, previous, rows = random.Random(7), 100.0, []
    for index in range(1000):
        base = 100+35*math.sin(index/17)+10*math.sin(index/4.5)+index*0.03
        close = max(base+randomizer.uniform(-1.5, 1.5), 1.0)
        high = max(previous, close)+randomizer.uniform(0, 1.5)
        low = max(min(previous, close)-randomizer.uniform(0, 1.5), 0.5)
        volume = round(1000+randomizer.uniform(0, 500), 2)
        rows.append((START+index*HOUR, round(previous, 4), round(high, 4), round(low, 4), round(close, 4), volume))
        previous = close
    return rows


def _prepare(root):
    from Chan import CChan
    from ChanConfig import CChanConfig
    from Common.CEnum import AUTYPE, KL_TYPE
    from Common.KLineTime import make_crypto_klu
    from CustomBuySellPoint.CustomStrategy import CCustomStrategy
    from ModelStrategy.BacktestChanConfig import CBacktestConfig
    from ModelStrategy.backtest import run_backtest
    from ModelStrategy.models.Xgboost.XGBTrainModelGenerator import CXGBTrainModelGenerator
    from OfflineData.offline_data_util import CKLineDB
    from Trade.db_util import CChanDB
    from .Deployment import CDeployment, publish_deployment

    config = {"offline_data": {"sqlite_path": str(root/"market.db"), "source_identity": SOURCE},
        "db": {"type": "sqlite", "sqlite_path": str(root/"trade.db")}, "notify": {"backend": "none"},
        "ccxt": {"exchange": "binance", "mode": "dry_run", "default_type": "swap"},
        "trade": {"deployment_manifest": str(root/"deployment.json"), "quote_max_age_ms": 1000}}
    write_json_once(root/"runtime.json", config)
    write_json_once(root/"open.json", {})
    rows = _synthetic_rows()
    with CKLineDB(str(root/"market.db")) as market:
        market.bind_source(SOURCE)
        market.upsert_klines(CODE, KL_TYPE.K_60M, rows[:600])
    strategy = {"cbsp_strategy": CCustomStrategy, "divergence_rate": float("inf"), "min_zs_cnt": 0,
        "bs_type": "1,2,3a,1p,2s,3b", "kl_data_check": True, "mean_metrics": [5, 20, 60],
        "trend_metrics": [10, 20], "cal_rsi": True, "cal_kdj": True, "cal_demark": True}
    with _environment(root):
        samples = run_backtest(CBacktestConfig([CODE], lv_list=[KL_TYPE.K_60M], autype=AUTYPE.NONE,
            data_src="custom:OfflineDataAPI.CStockFileReader", chan_config=strategy, primary_label="label_ret_N",
            label_para={"ret_n": 1}, output_dir=str(root/"samples")))
        model = CXGBTrainModelGenerator(model_tag="synthetic-only", model_dir=str(root/"models"),
            folder_thred=0.6, num_boost_round=2)
        model.trainProcess(samples.output_dir)
        publish_deployment(root/"deployment.json", model.GetModelPath(), candidate_score=0, entry_score=0, post_score=0)
        deployed = CDeployment(root/"deployment.json")
        with CKLineDB(str(root/"market.db")) as market:
            market.upsert_klines(CODE, KL_TYPE.K_60M, rows[600:])
        online = CChan(CODE, lv_list=[KL_TYPE.K_60M], config=CChanConfig({**strategy, "trigger_step": True}))
        chosen = None
        for index, row in enumerate(rows):
            unit = make_crypto_klu(row, KL_TYPE.K_60M)
            unit.source_identity = SOURCE
            online.trigger_load({KL_TYPE.K_60M: [unit]})
            if index >= 600:
                signals = online[0].cbsp_strategy.bsp_signal(online, 0)
                if signals:
                    chosen = signals[0]  # First forward candidate, not a score/return ranking.
                    break
        if chosen is None:
            _fail()
        now = chosen.sig_klu.close_ms+HOUR//4
        assessment = deployed.prepare_signal(online, chosen, observed_ms=now)
        prefix = deployed.build_chan(CODE, now)
        counterpart = prefix[0].cbsp_strategy.bsp_signal(prefix, 0)[0]
        rebuilt = deployed.prepare_signal(prefix, counterpart, observed_ms=now)
        if canonical_bytes(assessment) != canonical_bytes(rebuilt):
            _fail()
        online[0].cbsp_strategy.publish_signals(online, 0, signals=[chosen])
        db = CChanDB(db_conf=config["db"])
        try:
            record_id = db.add_signal(chosen)
        finally:
            db.close()
        tick = Decimal("0.1")
        price = (Decimal(str(chosen.open_thred))*Decimal("1.001" if chosen.is_buy else "0.999")/tick).to_integral_value(
            rounding=ROUND_CEILING if chosen.is_buy else ROUND_FLOOR)*tick
        scenario = {"schema": "chan-synthetic-paper-scenario-v1", "record_id": record_id, "now_ms": now,
            "price": float(price), "is_buy": chosen.is_buy, "model_artifact_id": model.artifact_id,
            "deployment_id": deployed.deployment_id, "features_sha256": assessment["features_sha256"],
            "config_sha256": _sha((root/"runtime.json").read_bytes()), "code_sha256": _sha(Path(__file__).read_bytes()),
            "rows_sha256": _sha(canonical_bytes(rows)), "sample_count": len(samples.samples)}
        write_json_once(root/"scenario.json", scenario)
        return scenario


def _account(now):
    from ModelStrategy.parameterEvaluate.crypto_account import CCryptoAccountConfig
    from Trade.LinearPaperAccount import CLinearPaperAccount
    return CLinearPaperAccount(CCryptoAccountConfig(initial_equity="1000", leverage="3",
        taker_fee="0.001", maker_fee="0.0002", taker_slippage="0.001"),
        markets=[{"exchange": "binance", "id": "DEMOUSDT", "symbol": CODE, "type": "swap", "base": "DEMO",
            "quote": "USDT", "settle": "USDT", "contractSize": "0.01", "amount_step": "1",
            "price_tick": "0.1", "min_notional": "1"}],
        position_mode="one_way", start_ms=now-1, identity_seed="c6-synthetic-only")


def _phase(root, phase):
    from Trade.CCXTTradeEngine import CCCXTTradeEngine
    from Trade.LinearPaperAccount import verify_linear_paper_report
    from Trade.OpenQuotaGen import CBenchPriceQuotaGen
    from Trade.PaperState import CPersistentPaperState
    from Trade.db_util import CChanDB
    from .Deployment import CDeployment
    from .MakeOpenTrade import make_open_trade
    from .OpenConfig import COpenConfig
    from .OpeningInputs import COpeningInputs
    from Common.MarketQuote import make_quote_batch

    scenario, config = _read(root/"scenario.json"), _read(root/"runtime.json")
    if (phase not in PHASES or (root/f"{phase}.json").exists()
            or set(config) != {"offline_data", "db", "notify", "ccxt", "trade"}
            or scenario["schema"] != "chan-synthetic-paper-scenario-v1"
            or scenario["code_sha256"] != _sha(Path(__file__).read_bytes())
            or scenario["config_sha256"] != _sha((root/"runtime.json").read_bytes())
            or config["ccxt"] != {"exchange": "binance", "mode": "dry_run", "default_type": "swap"}
            or config["db"] != {"type": "sqlite", "sqlite_path": str(root/"trade.db")}
            or config["notify"] != {"backend": "none"}
            or config["trade"] != {"deployment_manifest": str(root/"deployment.json"), "quote_max_age_ms": 1000}
            or config["offline_data"] != {"sqlite_path": str(root/"market.db"), "source_identity": SOURCE}):
        _fail()
    index = PHASES.index(phase)
    prior = _read(root/f"{PHASES[index-1]}.json") if index else None
    if prior is not None and prior["phase"] != PHASES[index-1]:
        _fail()
    now, price = scenario["now_ms"], scenario["price"]
    with _environment(root):
        deployed = CDeployment(root/"deployment.json")
        if deployed.model.artifact_id != scenario["model_artifact_id"] or deployed.deployment_id != scenario["deployment_id"]:
            _fail()
        db = CChanDB(db_conf=config["db"])
        try:
            server = (CPersistentPaperState.create(root/"server.json", account=_account(now), database=root/"trade.db")
                if phase == "entry" else CPersistentPaperState.open(root/"server.json", database=root/"trade.db"))
            with server:
                guard = COpeningInputs(root/"runtime.json", now_ms=lambda: now, require_quotes=True) if phase == "entry" else None
                engine = CCCXTTradeEngine(db, sim_state=server.state, quota_gen=CBenchPriceQuotaGen(price*0.035),
                    ccxt_conf=config["ccxt"], trade_conf=config["trade"], opening_inputs=guard, push_msg=False)
                engine.api_interval = 0
                bid, ask = (Decimal(str(price))-Decimal("0.1"), Decimal(str(price))) if scenario["is_buy"] else (
                    Decimal(str(price)), Decimal(str(price))+Decimal("0.1"))
                at = now+index if phase != "verify" else now+3
                engine.set_sim_quote(CODE, at_ms=at, bid=str(bid), ask=str(ask), mark_price=str(price))
                record_id = scenario["record_id"]
                if phase == "entry":
                    prices = guard.bind_quotes(make_quote_batch([{"symbol": CODE, "price": price, "timestamp_ms": now}],
                        source=SOURCE, started_ms=now, finished_ms=now), max_age_ms=1000)
                    engine.set_sim_fill_plan(engine.make_client_order_id(db.get_record(record_id), "open"), [0.01, 0.03])
                    failures = []
                    opened = make_open_trade(db, engine, COpenConfig(str(root/"open.json")), price_map=prices,
                        deployment=deployed, now_ms=lambda: now, failures=failures)
                    if opened != [record_id] or failures:
                        _fail()
                else:
                    engine.restore()
                    if phase == "exit":
                        engine.set_sim_quote(CODE, at_ms=now+2, bid=str(bid), ask=str(ask), mark_price=str(price))
                        engine.apply_sim_funding(CODE, at_ms=now+2, rate="0.0001", mark_price=str(price), event_id="demo-funding")
                        engine.set_sim_fill_plan(engine.make_client_order_id(db.get_record(record_id), "close"), [0.01, 0.03])
                        engine.cover_trade(db.get_record(record_id), None, "synthetic-only partial reduction")
                    else:
                        before = engine.get_sim_account_report()
                        engine.restore()
                        engine.apply_sim_funding(CODE, at_ms=now+2, rate="0.0001", mark_price=str(price), event_id="demo-funding")
                        if canonical_bytes(before) != canonical_bytes(engine.get_sim_account_report()):
                            _fail()
                account = engine.get_sim_account_report()
                if canonical_bytes(verify_linear_paper_report(account)) != canonical_bytes(account) or engine.exchange is not None:
                    _fail()
                history, record = db.get_order_history(record_id), db.get_record(record_id)
                if (history["gaps"] or record["current_qty"] != (0.01, 0.02, 0)[index]
                        or len(server.state.orders) != (1, 2, 2)[index]):
                    _fail()
                if prior and canonical_bytes(prior["account"]["effects"]) != canonical_bytes(account["effects"][:len(prior["account"]["effects"])]):
                    _fail()
                write_json_once(root/f"{phase}.json", {"phase": phase, "pid": os.getpid(), "account": account, "history": history,
                    "current_qty": record["current_qty"], "order_count": len(server.state.orders),
                    "model_artifact_id": record["model_version"], "deployment_id": record["deployment_id"]})
        finally:
            db.close()


def run_paper_rehearsal(output):
    root = Path(output).resolve()
    try:
        root.mkdir()  # Explicit fresh directory only; retain failures, never clean user work.
        scenario = _prepare(root)
        for phase in PHASES:
            result = subprocess.run([sys.executable, "-m", "Trade.Script.PaperRehearsal", "--output", str(root), "--phase", phase],
                cwd=ROOT, capture_output=True, timeout=120, check=False)
            if result.returncode != 0:
                _fail()  # No arbitrary child logs, account data or transport text in a success receipt.
        stages = [_read(root/f"{phase}.json") for phase in PHASES]
        report = {"schema": "chan-offline-paper-rehearsal-v1", "status": "completed", "synthetic_only": True,
            "candidate_authorized": False, "exchange_certified": False, "rows": 1000, "training_rows": 600, "boost_rounds": 2,
            "model_artifact_id": scenario["model_artifact_id"], "deployment_id": scenario["deployment_id"],
            "worker_pids": [stage["pid"] for stage in stages], "sample_count": scenario["sample_count"],
            "rows_sha256": scenario["rows_sha256"], "decision_reconciled": True, "event_ledger_reconciled": True,
            "stage_sha256": {phase: _sha((root/f"{phase}.json").read_bytes()) for phase in PHASES}}
        write_json_once(root/"rehearsal.json", report)
        return report
    except Exception:
        _fail()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--phase", choices=PHASES)
    args = parser.parse_args()
    try:
        if args.phase:
            _phase(Path(args.output).resolve(), args.phase)
        else:
            run_paper_rehearsal(args.output)
            print("Synthetic paper rehearsal completed; not candidate/testnet/live authorization")
        return 0
    except Exception:
        print("Synthetic paper rehearsal failed; original artifacts retained; no completion receipt", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
