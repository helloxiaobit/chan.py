"""baostock A股日K增量更新:从库内最后一根之后续传

用法: python -m OfflineData.bao_update            # 更新库内全部A股code
      python -m OfflineData.bao_update sz.000001  # 更新指定code
"""
import os
import sys
from datetime import datetime, timezone
from typing import List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from Common.CEnum import KL_TYPE

from .bao_download import download_codes
from .offline_data_util import CKLineDB


def update_codes(code_list: Optional[List[str]] = None, db: Optional[CKLineDB] = None) -> int:
    own_db = db is None
    db = db or CKLineDB()
    total = 0
    try:
        if code_list is None:  # 更新库内已有的全部A股code
            code_list = [s for s, lv in db.symbols() if lv == KL_TYPE.K_DAY.name and s.startswith(("sz.", "sh.", "bj."))]
        for code in code_list:
            last = db.last_ts(code, KL_TYPE.K_DAY)
            begin = "2010-01-01" if last is None else \
                datetime.fromtimestamp(last / 1000 + 86400, tz=timezone.utc).strftime("%Y-%m-%d")
            total += download_codes([code], db=db, begin_time=begin)
    finally:
        if own_db:
            db.close()
    return total


if __name__ == "__main__":
    update_codes(sys.argv[1:] or None)
