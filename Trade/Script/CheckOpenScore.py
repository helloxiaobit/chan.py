"""后验校验:K线完成后复查突破与分数(model_score_after)

开仓往往发生在K线未完成时(盘中价格突破),K线完成后需要复查:
- 完成K线的收盘价是否仍突破 open_thred
- 配置模型时复查分数是否仍达标
不通过则标记 open_err,由 ClosePreErrorOpen 尽快平掉。

用法: python -m Trade.Script.CheckOpenScore
"""
import os
import sys
from typing import Callable, Dict, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".."))

from Common.CEnum import KL_TYPE
from Common.send_msg_cmd import send_msg
from Trade.db_util import CChanDB

from .OpenConfig import COpenConfig
from .StaticsChanConfig import get_trade_conf


def get_last_closed_kline_close(code: str, lv: KL_TYPE) -> Optional[float]:
    # 从离线库读最新完成K线收盘价(要求 update_data 例行先跑)
    from OfflineData.offline_data_util import CKLineDB
    with CKLineDB() as db:
        rows = db.query_klines(code, lv)
        return rows[-1][4] if rows else None


def check_open_score(
    db: CChanDB,
    open_conf: Optional[COpenConfig] = None,
    close_map: Optional[Dict[str, float]] = None,       # 测试可注入完成K线收盘价
    score_func: Optional[Callable[[dict], float]] = None,  # 配置模型时注入打分函数
    lv: Optional[KL_TYPE] = None,
) -> List[int]:
    open_conf = open_conf or COpenConfig()
    lv = lv or get_trade_conf()["lv"]
    err_ids = []
    for rec in db.get_open_records():
        if rec["open_err"]:
            continue
        code = rec["stock_code"]
        close = close_map.get(code) if close_map is not None else get_last_closed_kline_close(code, lv)
        if close is None:
            continue
        breakout = close > rec["open_thred"] if rec["is_buy"] else close < rec["open_thred"]
        if not breakout:
            db.set_open_err(rec["id"], reason=f"K线完成后未突破: close={close} thred={rec['open_thred']}")
            err_ids.append(rec["id"])
            continue
        if score_func is not None:
            score_after = score_func(rec)
            db.set_score_after(rec["id"], score_after)
            if not open_conf.pass_score(score_after):
                db.set_open_err(rec["id"], reason=f"复查分数不达标: {score_after}")
                err_ids.append(rec["id"])
    if err_ids:
        send_msg("CheckOpenScore", f"{len(err_ids)} 条开仓后验失败,待修复: {err_ids}", level="WARNING")
    return err_ids


if __name__ == "__main__":
    check_open_score(CChanDB())
