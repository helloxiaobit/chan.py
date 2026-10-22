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
        if ((rec["cover_order_id"] or rec.get("cover_client_order_id"))
                and rec.get("cover_order_status") not in {"closed", "canceled", "rejected"}):
            # Only confirmed terminal orders permit an original-record retry;
            # an unknown/submitting request still belongs to recovery.
            continue
        code = rec["stock_code"]
        price = price_map.get(code) if price_map else None
        try:
            if price is not None and hasattr(engine, "set_sim_price") and getattr(getattr(engine, "sim_state", None), "paper_account", None) is None:
                engine.set_sim_price(code, price)
            engine.cover_trade(rec, price, reason=f"open_err: {rec['open_err_reason']}")
            if db.get_record(rec["id"])["status"] in {"closed", "cover"}:
                closed.append(rec["id"])
        except CChanException as e:
            db.set_close_err(rec["id"], str(e))
            send_msg("错误开仓修复失败", f"{code} id={rec['id']}: {e}", level="ERROR")
    return closed


def main():
    from .TradeRuntime import configured_trade_engine
    try:
        db = CChanDB()
        try:
            with configured_trade_engine(db) as engine:
                closed = close_pre_error_open(db, engine)
                unresolved = len(db.get_error_opens())
                issues = engine.paper_inputs.issues if engine.paper_inputs is not None else []
        finally:
            db.close()
        print(f"ClosePreErrorOpen: closed={len(closed)} unresolved={unresolved} paper_input_issues={len(issues)}")
        return 1 if unresolved or issues else 0
    except Exception:
        print("ClosePreErrorOpen: original order/quote evidence unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
