"""实时跟踪:对已开仓记录检查止损/止盈/峰值回撤,触发则平仓

平仓条件(任一满足):
1. 跌破信号止损价 sl_thred
2. 收益超过 max_profit_rate(止盈)
3. 自峰值回撤超过 max_sl_rate(动态止损,peak_price_after_open 由 UpdatePeakPrice 维护)

用法: python -m Trade.Script.RealTimeTracker
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

from .MakeOpenTrade import get_price_map
from .OpenConfig import COpenConfig


def cal_cover_reason(rec: dict, price: float, open_conf: COpenConfig) -> Optional[str]:
    is_buy = bool(rec["is_buy"])
    open_price = rec["open_price"]
    # 1. 信号止损价
    if rec["sl_thred"] is not None:
        if (is_buy and price < rec["sl_thred"]) or (not is_buy and price > rec["sl_thred"]):
            return "stop_loss"
    rate = (price - open_price) / open_price if is_buy else (open_price - price) / open_price
    # 2. 止盈
    if open_conf.max_profit_rate is not None and rate > open_conf.max_profit_rate:
        return "max_profit"
    # 3. 峰值回撤动态止损
    peak = rec["peak_price_after_open"]
    if open_conf.max_sl_rate is not None and peak:
        dd = (peak - price) / peak if is_buy else (price - peak) / peak
        if dd > open_conf.max_sl_rate:
            return "peak_drawdown"
    return None


def real_time_track(
    db: CChanDB,
    engine: CTradeEngine,
    open_conf: Optional[COpenConfig] = None,
    price_map: Optional[Dict[str, float]] = None,
) -> List[int]:
    open_conf = open_conf or COpenConfig()
    records = [rec for rec in db.get_open_records() if not rec["cover_order_id"]]
    if not records:
        return []
    if price_map is None:
        price_map = get_price_map(sorted({rec["stock_code"] for rec in records}))
    covered = []
    for rec in records:
        code = rec["stock_code"]
        price = price_map.get(code)
        if price is None:
            continue
        db.update_peak_price(rec["id"], price)
        rec = db.get_record(rec["id"])  # 取更新后的 peak
        reason = cal_cover_reason(rec, price, open_conf)
        if reason is None:
            continue
        try:
            if hasattr(engine, "set_sim_price"):
                engine.set_sim_price(code, price)
            engine.cover_trade(rec, price, reason=reason)
            covered.append(rec["id"])
        except CChanException as e:
            db.set_close_err(rec["id"], str(e))
            send_msg("平仓失败", f"{code} id={rec['id']}: {e}", level="ERROR")
    return covered


if __name__ == "__main__":
    from Trade.CCXTTradeEngine import CCCXTTradeEngine
    chan_db = CChanDB()
    real_time_track(chan_db, CCCXTTradeEngine(chan_db))
