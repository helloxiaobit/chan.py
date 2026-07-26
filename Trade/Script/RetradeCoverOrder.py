"""修复未成交平仓单:轮询在途平仓单,未成交则撤单重下(市价)

用法: python -m Trade.Script.RetradeCoverOrder
"""
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".."))

from Trade.db_util import CChanDB
from Trade.TradeEngine import CTradeEngine


def retrade_cover_order(db: CChanDB, engine: CTradeEngine, times: int = 3, interval: float = 5.0):
    engine.poll_orders(times=times, interval=interval, adjust_price=True)


if __name__ == "__main__":
    from Trade.CCXTTradeEngine import CCCXTTradeEngine
    chan_db = CChanDB()
    retrade_cover_order(chan_db, CCCXTTradeEngine(chan_db))
