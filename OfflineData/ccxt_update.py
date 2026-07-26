"""ccxt 离线K线增量更新:按 exchange+symbol+timeframe 增量拉取落 sqlite

用法:
    python -m OfflineData.ccxt_update BTC/USDT K_60M [K_DAY ...]
首次全量(从 begin_ts 或交易所最早数据),之后增量(从库内最后一根之后续传)。
"""
import os
import sys
from typing import Optional, Union

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from Common.CEnum import KL_TYPE
from Common.ChanException import CChanException, ErrCode
from DataAPI.ccxt import KLTYPE2TIMEFRAME, PAGE_LIMIT, create_exchange

from .offline_data_util import CKLineDB, parse_dt_to_ts

DEFAULT_BEGIN = "2017-01-01"  # 首次全量的起始时间(binance 现货最早 2017-07)


def update_symbol(
    symbol: str,
    lv: Union[KL_TYPE, str],
    db: Optional[CKLineDB] = None,
    exchange=None,
    begin_time: str = DEFAULT_BEGIN,
    verbose: bool = True,
) -> int:
    """增量更新单个 symbol+级别,返回新增/更新K线数;网络失败抛出带明确提示的异常"""
    import ccxt  # 懒加载

    own_db = db is None
    db = db or CKLineDB()
    exchange = exchange or create_exchange(for_data=True)
    if isinstance(lv, str):
        lv = KL_TYPE[lv]
    if lv not in KLTYPE2TIMEFRAME:
        raise CChanException(f"ccxt 不支持K线级别: {lv}", ErrCode.SRC_DATA_TYPE_ERR)
    timeframe = KLTYPE2TIMEFRAME[lv]

    last = db.last_ts(symbol, lv)
    since = last + 1 if last is not None else parse_dt_to_ts(begin_time)
    total = 0
    try:
        while True:
            data = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=PAGE_LIMIT)
            if not data:
                break
            rows = [
                (item[0], float(item[1]), float(item[2]), float(item[3]), float(item[4]),
                 float(item[5]) if len(item) > 5 and item[5] is not None else 0.0)
                for item in data
            ]
            db.upsert_klines(symbol, lv, rows)
            total += len(rows)
            since = data[-1][0] + 1
            if verbose:
                print(f"[ccxt_update] {symbol} {lv.name}: +{len(rows)} (累计{total}), 已到 ts={data[-1][0]}")
            if len(data) < PAGE_LIMIT:
                break
    except ccxt.NetworkError as e:
        raise CChanException(
            f"ccxt 网络请求失败({symbol} {timeframe}),已入库 {total} 根;"
            f"请检查网络或在 config.yaml 配置 ccxt.proxy 后重试: {e}",
            ErrCode.SRC_DATA_NOT_FOUND,
        ) from e
    finally:
        if own_db:
            db.close()
    return total


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python -m OfflineData.ccxt_update <symbol> <KL_TYPE> [KL_TYPE ...]")
        print("       e.g. python -m OfflineData.ccxt_update BTC/USDT K_60M K_DAY")
        sys.exit(1)
    arg_symbol = sys.argv[1]
    with CKLineDB() as arg_db:
        for lv_str in sys.argv[2:]:
            cnt = update_symbol(arg_symbol, lv_str, db=arg_db)
            print(f"[ccxt_update] {arg_symbol} {lv_str} 完成,共更新 {cnt} 根,"
                  f"库内共 {arg_db.count(arg_symbol, lv_str)} 根")
