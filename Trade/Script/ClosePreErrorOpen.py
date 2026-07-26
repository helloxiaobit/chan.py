"""修复错误开仓:open_err 记录尽快平掉(无论盈亏)

用法: python -m Trade.Script.ClosePreErrorOpen
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


def close_pre_error_open(
    db: CChanDB,
    engine: CTradeEngine,
    price_map: Optional[Dict[str, float]] = None,
) -> List[int]:
    closed = []
    for rec in db.get_error_opens():
        if rec["cover_order_id"]:  # 已提交平仓单,交给 RetradeCoverOrder 轮询
            continue
        code = rec["stock_code"]
        price = price_map.get(code) if price_map else None
        try:
            if price is not None and hasattr(engine, "set_sim_price"):
                engine.set_sim_price(code, price)
            engine.cover_trade(rec, price, reason=f"open_err: {rec['open_err_reason']}")
            closed.append(rec["id"])
        except CChanException as e:
            db.set_close_err(rec["id"], str(e))
            send_msg("错误开仓修复失败", f"{code} id={rec['id']}: {e}", level="ERROR")
    return closed


if __name__ == "__main__":
    from Trade.CCXTTradeEngine import CCCXTTradeEngine
    chan_db = CChanDB()
    close_pre_error_open(chan_db, CCCXTTradeEngine(chan_db))
