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


def main():
    from .TradeRuntime import configured_trade_engine
    try:
        db = CChanDB()
        try:
            with configured_trade_engine(db) as engine:
                retrade_cover_order(db, engine)
                unresolved = sum(row["status"] == "closing" for row in db.get_recoverable_records())
                issues = engine.paper_inputs.issues if engine.paper_inputs is not None else []
        finally:
            db.close()
        print(f"RetradeCoverOrder: unresolved={unresolved} paper_input_issues={len(issues)}")
        return 1 if unresolved or issues else 0
    except Exception:
        print("RetradeCoverOrder: original order/quote evidence unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
