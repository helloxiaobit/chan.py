"""峰值价更新:维护 peak_price_after_open(动态止损基准)

用法: python -m Trade.Script.UpdatePeakPrice
"""
import os
import sys
from typing import Dict, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".."))

from Trade.db_util import CChanDB

from .MakeOpenTrade import get_price_map


def update_peak_price(db: CChanDB, price_map: Optional[Dict[str, float]] = None) -> int:
    records = db.get_open_records()
    if not records:
        return 0
    if price_map is None:
        price_map = get_price_map(sorted({rec["stock_code"] for rec in records}))
    cnt = 0
    for rec in records:
        price = price_map.get(rec["stock_code"])
        if price is not None:
            db.update_peak_price(rec["id"], price)
            cnt += 1
    return cnt


if __name__ == "__main__":
    update_peak_price(CChanDB())
