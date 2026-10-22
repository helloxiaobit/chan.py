"""只查询恢复原在途订单；未知退出非零，不重下，也不授予新增风险。"""
import sys

from Common.ChanException import CChanException


def restore_orders(db, engine):
    pending = {row["id"] for row in db.get_recoverable_records()}
    restored = engine.restore()
    known = {row["id"] for row in restored}
    return {"restored": len(known), "unresolved": sorted(pending-known)}


def main():
    from .TradeRuntime import configured_trade_engine
    from Trade.db_util import CChanDB
    try:
        db = CChanDB()
        try:
            with configured_trade_engine(db) as engine:
                result = restore_orders(db, engine)
                issues = engine.paper_inputs.issues if engine.paper_inputs is not None else []
        finally:
            db.close()
        print(f"RestoreOrders: restored={result['restored']} unresolved={len(result['unresolved'])} paper_input_issues={len(issues)}")
        return 1 if result["unresolved"] or issues else 0
    except Exception:
        print("RestoreOrders: original account/order evidence unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
