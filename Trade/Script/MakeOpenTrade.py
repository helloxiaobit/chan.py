"""开仓例行:检查 watching 信号是否突破(实时价 Snapshot)→ 模型分数校验 → 开仓

用法: python -m Trade.Script.MakeOpenTrade
"""
import os
import sys
from typing import Dict, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".."))

from Common.ChanException import CChanException
from Common.send_msg_cmd import send_msg
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
) -> List[int]:
    open_conf = open_conf or COpenConfig()
    signals = db.get_watching_signals()
    if not signals:
        return []
    if price_map is None:
        price_map = get_price_map(sorted({rec["stock_code"] for rec in signals}))
    opened = []
    for rec in signals:
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
        if not open_conf.pass_score(rec["model_score_before"]):
            db.unwatch(rec["id"], reason=f"score {rec['model_score_before']} < {open_conf.score_thred}")
            continue
        try:
            if hasattr(engine, "set_sim_price"):  # dry_run 引擎注入市价参考
                engine.set_sim_price(code, price)
            engine.add_trade(rec, price)
            opened.append(rec["id"])
        except CChanException as e:
            send_msg("开仓失败", f"{code} id={rec['id']}: {e}", level="ERROR")
    return opened


if __name__ == "__main__":
    from Trade.CCXTTradeEngine import CCCXTTradeEngine
    chan_db = CChanDB()
    make_open_trade(chan_db, CCCXTTradeEngine(chan_db))
