"""futu 港美股K线下载(可选依赖;需 pip install futu-api 且本地运行 FutuOpenD)

用法: python -m OfflineData.futu_download HK.00700 ...
"""
import os
import sys
from typing import List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from Common.CEnum import KL_TYPE
from Common.ChanException import CChanException, ErrCode

from .offline_data_util import CKLineDB, parse_dt_to_ts


def download_codes(code_list: List[str], db: Optional[CKLineDB] = None, begin_time: str = "2015-01-01") -> int:
    try:
        import futu as ft  # 懒加载,可选依赖
    except ImportError as e:
        raise CChanException(
            "futu_download 需要 futu-api,请先 pip install futu-api 并启动 FutuOpenD",
            ErrCode.SRC_DATA_NOT_FOUND,
        ) from e
    try:
        from Config.EnvConfig import CEnv
        futu_conf = CEnv.get_instance().futu_conf
    except Exception:
        futu_conf = {}
    own_db = db is None
    db = db or CKLineDB()
    quote_ctx = ft.OpenQuoteContext(
        host=futu_conf.get("host", "127.0.0.1"), port=int(futu_conf.get("port", 11111)))
    total = 0
    try:
        for code in code_list:
            ret, df, _ = quote_ctx.request_history_kline(
                code, start=begin_time, ktype=ft.KLType.K_DAY, autype=ft.AuType.QFQ)
            if ret != ft.RET_OK:
                print(f"[futu_download] {code} 获取失败: {df}")
                continue
            rows = [
                (parse_dt_to_ts(str(r["time_key"])[:10]), float(r["open"]), float(r["high"]),
                 float(r["low"]), float(r["close"]), float(r["volume"]))
                for _, r in df.iterrows()
            ]
            db.upsert_klines(code, KL_TYPE.K_DAY, rows)
            total += len(rows)
            print(f"[futu_download] {code}: {len(rows)} 根日K入库")
    finally:
        quote_ctx.close()
        if own_db:
            db.close()
    return total


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m OfflineData.futu_download <code> [code ...]")
        sys.exit(1)
    download_codes(sys.argv[1:])
