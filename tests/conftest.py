import math
import os
import random
import sys
from datetime import date, timedelta

import pytest

# 保证从仓库根目录 import(Chan/ChanConfig 等都在根目录)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("MPLBACKEND", "Agg")  # 测试环境无显示器


def gen_synthetic_bars(n=1000, seed=7, start_year=2020):
    """确定性合成日K线:趋势+双周期正弦+噪声,保证产生足够的分型/笔/段/中枢/买卖点"""
    rnd = random.Random(seed)
    bars = []
    day = date(start_year, 1, 1)
    prev_close = 100.0
    for i in range(n):
        base = 100 + 35 * math.sin(i / 17) + 10 * math.sin(i / 4.5) + i * 0.03
        close = max(base + rnd.uniform(-1.5, 1.5), 1.0)
        open_ = prev_close
        high = max(open_, close) + rnd.uniform(0, 1.5)
        low = max(min(open_, close) - rnd.uniform(0, 1.5), 0.5)
        volume = round(1000 + rnd.uniform(0, 500), 2)
        bars.append({
            "year": day.year, "month": day.month, "day": day.day,
            "open": round(open_, 4), "high": round(high, 4),
            "low": round(low, 4), "close": round(close, 4),
            "volume": volume,
        })
        prev_close = close
        day += timedelta(days=1)
    return bars


def make_klu(bar, include_volume=False):
    """由合成bar构造 CKLine_Unit(每次调用都构造新对象,供 trigger_load 使用)"""
    from Common.CEnum import DATA_FIELD
    from Common.CTime import CTime
    from KLine.KLine_Unit import CKLine_Unit
    kl_dict = {
        DATA_FIELD.FIELD_TIME: CTime(bar["year"], bar["month"], bar["day"], 0, 0),
        DATA_FIELD.FIELD_OPEN: bar["open"],
        DATA_FIELD.FIELD_HIGH: bar["high"],
        DATA_FIELD.FIELD_LOW: bar["low"],
        DATA_FIELD.FIELD_CLOSE: bar["close"],
    }
    if include_volume:
        kl_dict[DATA_FIELD.FIELD_VOLUME] = bar["volume"]
    return CKLine_Unit(kl_dict)


@pytest.fixture(scope="session")
def synthetic_bars():
    return gen_synthetic_bars()


@pytest.fixture(scope="session")
def synthetic_csv_code(synthetic_bars):
    """把合成K线写到仓库根目录 test_synthetic_day.csv(csvAPI 的查找路径),返回 code"""
    code = "test_synthetic"
    path = os.path.join(ROOT, f"{code}_day.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write("datetime,open,high,low,close,volume\n")
        for b in synthetic_bars:
            f.write(f"{b['year']:04}-{b['month']:02}-{b['day']:02},{b['open']},{b['high']},{b['low']},{b['close']},{b['volume']}\n")
    yield code
    if os.path.exists(path):
        os.remove(path)
