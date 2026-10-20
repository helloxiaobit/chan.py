"""加密行情的 UTC 半开周期；原始存储为开盘时刻，框架使用收盘边界。"""
from datetime import datetime, timedelta, timezone
from time import time_ns
import math

from Common.CEnum import DATA_FIELD, KL_TYPE
from Common.ChanException import CChanException, ErrCode
from Common.CTime import CTime

KLTYPE_TO_MS = {
    KL_TYPE.K_1M: 60_000,
    KL_TYPE.K_3M: 180_000,
    KL_TYPE.K_5M: 300_000,
    KL_TYPE.K_10M: 600_000,
    KL_TYPE.K_15M: 900_000,
    KL_TYPE.K_30M: 1_800_000,
    KL_TYPE.K_60M: 3_600_000,
    KL_TYPE.K_2H: 7_200_000,
    KL_TYPE.K_4H: 14_400_000,
    KL_TYPE.K_DAY: 86_400_000,
    KL_TYPE.K_WEEK: 604_800_000,
}


def utc_now_ms():
    return time_ns() // 1_000_000


def bar_close_ms(open_ms, lv):
    if isinstance(lv, str):
        lv = KL_TYPE[lv]
    if lv in KLTYPE_TO_MS:
        return open_ms + KLTYPE_TO_MS[lv]
    if lv == KL_TYPE.K_MON:
        dt = datetime.fromtimestamp(open_ms / 1000, tz=timezone.utc)
        if (dt.day, dt.hour, dt.minute, dt.second, dt.microsecond) != (1, 0, 0, 0, 0):
            raise CChanException("月线必须从 UTC 月初开始", ErrCode.KL_DATA_INVALID)
        next_month = (dt.replace(day=28) + timedelta(days=4)).replace(day=1)
        return int(next_month.timestamp() * 1000)
    raise CChanException(f"不支持的 UTC K线周期: {lv}", ErrCode.SRC_DATA_TYPE_ERR)


def make_crypto_klu(ohlcv, lv, now_ms=None):
    from KLine.KLine_Unit import CKLine_Unit
    ohlcv = validate_ohlcv_page([ohlcv], lv)[0]
    open_ms = ohlcv[0]
    close_ms = bar_close_ms(open_ms, lv)
    dt = datetime.fromtimestamp(close_ms / 1000, tz=timezone.utc)
    klu = CKLine_Unit({
        DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute,
                                     dt.second, auto=False, tzinfo=timezone.utc),
        DATA_FIELD.FIELD_OPEN: float(ohlcv[1]),
        DATA_FIELD.FIELD_HIGH: float(ohlcv[2]),
        DATA_FIELD.FIELD_LOW: float(ohlcv[3]),
        DATA_FIELD.FIELD_CLOSE: float(ohlcv[4]),
        DATA_FIELD.FIELD_VOLUME: float(ohlcv[5]) if len(ohlcv) > 5 and ohlcv[5] is not None else 0.0,
    })
    klu.open_ms = open_ms
    klu.close_ms = klu.available_at_ms = close_ms
    klu.is_final = close_ms <= (utc_now_ms() if now_ms is None else now_ms)
    return klu


def validate_ohlcv_page(rows, lv, *, since=None, previous_open=None):
    """整页先校验再交给存储；缺口不填充、坏行不自动修正。"""
    if isinstance(lv, str):
        lv = KL_TYPE[lv]
    result = []
    for item in rows:
        if len(item) < 5 or type(item[0]) is not int or item[0] < 0:
            raise CChanException("OHLCV 时间格式错误", ErrCode.KL_DATA_INVALID)
        ts = item[0]
        offset = 3 * KLTYPE_TO_MS[KL_TYPE.K_DAY] if lv == KL_TYPE.K_WEEK else 0
        if lv in KLTYPE_TO_MS and (ts + offset) % KLTYPE_TO_MS[lv]:
            raise CChanException("K线开盘时间未对齐 UTC 周期", ErrCode.KL_TIME_INCONSISTENT)
        if since is not None and ts < since:
            raise CChanException("行情分页未前进或回绕", ErrCode.KL_NOT_MONOTONOUS)
        if previous_open is not None and ts != bar_close_ms(previous_open, lv):
            raise CChanException("K线重复、乱序或缺口", ErrCode.KL_TIME_INCONSISTENT)
        try:
            o, h, l, c = (float(v) for v in item[1:5])
            v = float(item[5]) if len(item) > 5 and item[5] is not None else 0.0
        except (ValueError, TypeError) as exc:
            raise CChanException("OHLCV 数字格式错误", ErrCode.KL_DATA_INVALID) from exc
        if not all(math.isfinite(n) for n in (o, h, l, c, v)) or min(o, h, l, c) <= 0 or v < 0:
            raise CChanException("OHLCV 必须有限、价格正数、成交量非负", ErrCode.KL_DATA_INVALID)
        if not l <= min(o, c) <= max(o, c) <= h:
            raise CChanException("OHLCV 高低价不一致", ErrCode.KL_DATA_INVALID)
        result.append((ts, o, h, l, c, v))
        previous_open = ts
    return result
