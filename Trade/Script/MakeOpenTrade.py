"""开仓例行:检查 watching 信号是否突破(实时价 Snapshot)→ 模型分数校验 → 开仓

用法: python -m Trade.Script.MakeOpenTrade
"""
import os
import sys
import math
import re
from typing import Dict, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".."))

from Common.ChanException import CChanException, ErrCode
from Common.send_msg_cmd import send_msg
from Common.KLineTime import utc_now_ms
from Trade.db_util import CChanDB
from Trade.TradeEngine import CTradeEngine

from .OpenConfig import COpenConfig


def get_price_map(code_list: List[str]) -> Dict[str, Optional[float]]:
    from Config.EnvConfig import CEnv
    from DataAPI.SnapshotAPI.StockSnapshotAPI import priceQuery
    engine = CEnv.get_instance().snapshot_engine
    res = priceQuery(code_list, engine=engine, return_klu=False)
    return {code: (v["price"] if v else None) for code, v in res.items()}


def make_open_trade(
    db: CChanDB,
    engine: CTradeEngine,
    open_conf: Optional[COpenConfig] = None,
    price_map: Optional[Dict[str, float]] = None,  # 测试/演练可注入实时价
    deployment=None,
    now_ms=None,
    failures=None,
) -> List[int]:
    from .Deployment import CDeployment
    open_conf = open_conf or COpenConfig()
    guard = getattr(engine, "opening_inputs", None)
    failures = [] if failures is None else failures
    def blocked(stage, record=None, code=ErrCode.TRADE_UNLOCK_FAIL):
        failures.append({"stage": stage, "record_id": None if record is None else record["id"], "error_code": int(code)})
    signals = db.get_watching_signals()
    if not signals:
        return []
    if guard is not None:
        try:
            guard.assert_current()
            scope = guard.scope
            signals = [record for record in signals if record["stock_code"] in scope["code_list"] and record["lv"] == scope["trade_lv"]]
            if not signals:
                return []
        except CChanException:
            blocked("opening_inputs")
            return []
    try:
        deployment = deployment or CDeployment.configured()
    except CChanException as error:
        if guard is not None:
            blocked("deployment", code=error.errcode)
            return []
        for rec in signals:
            db.unwatch(rec["id"], reason=f"deployment_unavailable: {error}")
        return []
    if price_map is None:
        try:
            price_map = get_price_map(sorted({rec["stock_code"] for rec in signals}))
        except Exception:
            if guard is None:
                raise
            blocked("price", code=ErrCode.SNAPSHOT_ERR)
            return []
    if guard is not None and (not isinstance(price_map, dict) or any(type(price_map.get(rec["stock_code"])) not in (int, float)
            or not math.isfinite(price_map[rec["stock_code"]]) or price_map[rec["stock_code"]] <= 0 for rec in signals)):
        blocked("price", code=ErrCode.SNAPSHOT_ERR)
        return []
    opened = []
    for rec in signals:
        if guard is not None:
            try:
                guard.check(rec, engine=engine)
            except CChanException:
                blocked("opening_inputs", rec)
                break
        code = rec["stock_code"]
        price = price_map.get(code)
        if price is None:
            continue
        # 突破判断
        breakout = price > rec["open_thred"] if rec["is_buy"] else price < rec["open_thred"]
        if not breakout:
            continue
        if not open_conf.pass_bsp_type(rec["bstype"]):
            db.unwatch(rec["id"], reason="bsp_type_filtered")
            continue
        if deployment is None and not rec.get("deployment_id") and not open_conf.pass_score(rec["model_score_before"]):
            db.unwatch(rec["id"], reason=f"score {rec['model_score_before']} < {open_conf.score_thred}")
            continue
        try:
            if deployment is not None or rec.get("deployment_id") or rec.get("model_version"):
                if deployment is None or rec.get("deployment_id") != deployment.deployment_id:
                    raise CChanException("deployment_unavailable_or_changed", ErrCode.MODEL_ERROR)
                rec["entry_assessment"] = deployment.assess_entry(rec, price, observed_ms=(now_ms or utc_now_ms)())
            if hasattr(engine, "set_sim_price") and getattr(getattr(engine, "sim_state", None), "paper_account", None) is None:
                # 完整 paper 的显式 UTC/bid/ask/mark 必须由调用者提供，不能用一个 last price 补造。
                engine.set_sim_price(code, price)
            order = engine.add_trade(rec, price)
            if order.filled > 0:
                opened.append(rec["id"])
        except CChanException as e:
            if guard is not None:
                blocked("open", rec, e.errcode)
                break  # 已取得的意图不回退；原 query/cancel/reduce 仍交恢复管理。
            if rec.get("deployment_id") or deployment is not None:
                current = db.get_record(rec["id"])
                if current["status"] == "signal":
                    db.unwatch(rec["id"], reason=f"model_entry_rejected: {e}")
            send_msg("开仓失败", f"{code} id={rec['id']}: {e}", level="ERROR")
    return opened


def main():
    from .OpeningInputs import COpeningInputs
    from .TradeRuntime import configured_trade_engine
    from Trade.OpenQuotaGen import CBenchPriceQuotaGen
    try:
        cycle = os.environ.get("CHANPY_CYCLE_ID", "")
        config = os.environ.get("CHANPY_CONFIG")
        if re.fullmatch(r"[0-9a-f]{32}", cycle) is None or not config:
            raise CChanException("开仓 CLI 需要配置运行壳提供原输入时代", ErrCode.TRADE_UNLOCK_FAIL)
        expected = {key: os.environ.get("CHANPY_CYCLE_"+key.upper())
                    for key in ("config_sha256", "scope_sha256", "inputs_sha256")}
        guard = COpeningInputs(config, expected=expected, now_ms=utc_now_ms, require_quotes=True)
        notional = guard.env.get_section("trade").get("bench_price",
            1000.0 if guard.env.ccxt_conf.get("mode") == "dry_run" else None)
        if type(notional) not in (int, float) or not math.isfinite(notional) or notional <= 0:
            raise CChanException("运行名义金额必须有限且为正", ErrCode.PARA_ERROR)
        chan_db = CChanDB(db_conf=guard.env.db_conf)
        try:
            scope = guard.scope
            eligible = any(record["stock_code"] in scope["code_list"] and record["lv"] == scope["trade_lv"]
                for record in chan_db.get_watching_signals())
            with configured_trade_engine(chan_db, env=guard.env, quota_gen=CBenchPriceQuotaGen(float(notional)),
                    opening_inputs=guard, now_ms=utc_now_ms) as engine:
                if not engine.dry_run:
                    if engine.market_type != "swap":
                        raise CChanException("配置原生开仓仅接入已验证的swap金额路径", ErrCode.TRADE_UNLOCK_FAIL)
                    # Configuration routing is not admission. Each add_trade
                    # still owns fresh sources and the original monetary CAS.
                    engine._native_entry_profile()
                prices = {}
                if eligible:
                    max_age = guard.env.get_section("trade").get("quote_max_age_ms")
                    if type(max_age) is not int or not 0 < max_age < 2**63:
                        raise CChanException("配置开仓需要显式报价年龄上限", ErrCode.SNAPSHOT_ERR)
                    if engine.paper_inputs is not None:
                        batch = engine.paper_inputs.price_batch(engine, symbols=scope["code_list"])
                    else:
                        if guard.env.snapshot_engine != "ccxt":
                            raise CChanException("非 paper 配置开仓需要明确 CCXT 来源", ErrCode.SNAPSHOT_ERR)
                        from DataAPI.SnapshotAPI.CCXTSnapshot import CCCXTSnapshot
                        batch = CCCXTSnapshot.query_quotes(scope["code_list"], now_ms=utc_now_ms)
                    prices = guard.bind_quotes(batch, max_age_ms=max_age)
                failures = []
                opened = make_open_trade(chan_db, engine, open_conf=COpenConfig.configured(guard.env),
                    price_map=prices, failures=failures, now_ms=utc_now_ms)
                issues = engine.paper_inputs.issues if engine.paper_inputs is not None else []
                print(f"MakeOpenTrade: opened={len(opened)} blocked={len(failures)} paper_input_issues={len(issues)}")
                return 1 if failures or issues else 0
        finally:
            chan_db.close()
    except Exception:
        print("MakeOpenTrade: configured input epoch unavailable; no new risk", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
