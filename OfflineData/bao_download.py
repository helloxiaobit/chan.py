"""baostock A股日K全量下载落 sqlite(研究用;lv 固定 K_DAY,前复权)

用法: python -m OfflineData.bao_download sz.000001 sh.600000 ...
"""
import os
import sys
from typing import List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from Common.CEnum import KL_TYPE

from .offline_data_util import CKLineDB, parse_dt_to_ts


def download_codes(code_list: List[str], db: Optional[CKLineDB] = None,
                   begin_time: str = "2010-01-01", end_time: Optional[str] = None) -> int:
    import baostock as bs  # 懒加载
    own_db = db is None
    db = db or CKLineDB()
    bs.login()
    total = 0
    try:
        for code in code_list:
            rs = bs.query_history_k_data_plus(
                code, "date,open,high,low,close,volume",
                start_date=begin_time, end_date=end_time or "", frequency="d", adjustflag="2",
            )
            rows = []
            while rs.next():
                r = rs.get_row_data()
                if not all(r[:5]):
                    continue
                vol = float(r[5]) if len(r) > 5 and r[5] else 0.0
                rows.append((parse_dt_to_ts(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), vol))
            db.upsert_klines(code, KL_TYPE.K_DAY, rows)
            total += len(rows)
            print(f"[bao_download] {code}: {len(rows)} 根日K入库")
    finally:
        bs.logout()
        if own_db:
            db.close()
    return total


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m OfflineData.bao_download <code> [code ...]")
        sys.exit(1)
    download_codes(sys.argv[1:])
