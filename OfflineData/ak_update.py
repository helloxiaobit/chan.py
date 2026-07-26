"""akshare A股日K更新(baostock 的备用数据源;需 pip install akshare)

用法: python -m OfflineData.ak_update sz.000001 ...
"""
import os
import sys
from typing import List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from Common.CEnum import KL_TYPE
from Common.ChanException import CChanException, ErrCode

from .offline_data_util import CKLineDB, parse_dt_to_ts


def update_codes(code_list: List[str], db: Optional[CKLineDB] = None, begin_time: str = "2010-01-01") -> int:
    try:
        import akshare as ak  # 懒加载
    except ImportError as e:
        raise CChanException("ak_update 需要 akshare,请先 pip install akshare", ErrCode.SRC_DATA_NOT_FOUND) from e
    own_db = db is None
    db = db or CKLineDB()
    total = 0
    try:
        for code in code_list:
            symbol = code.split(".")[-1]  # sz.000001 → 000001
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                                    start_date=begin_time.replace("-", ""), adjust="qfq")
            rows = [
                (parse_dt_to_ts(str(r["日期"])[:10]), float(r["开盘"]), float(r["最高"]),
                 float(r["最低"]), float(r["收盘"]), float(r["成交量"]))
                for _, r in df.iterrows()
            ]
            db.upsert_klines(code, KL_TYPE.K_DAY, rows)
            total += len(rows)
            print(f"[ak_update] {code}: {len(rows)} 根日K入库")
    finally:
        if own_db:
            db.close()
    return total


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m OfflineData.ak_update <code> [code ...]")
        sys.exit(1)
    update_codes(sys.argv[1:])
