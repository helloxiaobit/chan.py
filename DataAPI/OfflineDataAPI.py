"""离线落地数据读取:data_src="custom:OfflineDataAPI.CStockFileReader"

优先读 sqlite(OfflineData/ccxt_update 等落地的 kline.db),
库里没有时回退到 offline_data.root 下的 csv({code}_{k_type}.csv,表头带列名)。
"""
import os
from datetime import datetime, timezone

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.ChanException import CChanException, ErrCode
from Common.CTime import CTime
from Common.func_util import kltype_lt_day
from KLine.KLine_Unit import CKLine_Unit

from .CommonStockAPI import CCommonStockApi


class CStockFileReader(CCommonStockApi):
    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ):
        super(CStockFileReader, self).__init__(code, k_type, begin_date, end_date, autype)

    def get_kl_data(self):
        from OfflineData.offline_data_util import CKLineDB, default_db_path, parse_dt_to_ts
        db_path = default_db_path()
        begin_ts = parse_dt_to_ts(self.begin_date) if self.begin_date else None
        end_ts = parse_dt_to_ts(self.end_date) if self.end_date else None
        if os.path.exists(db_path):
            with CKLineDB(db_path) as db:
                rows = db.query_klines(self.code, self.k_type, begin_ts, end_ts)
            if rows:
                for ts, o, h, l, c, v in rows:
                    yield self.make_klu(ts, o, h, l, c, v)
                return
        # sqlite 无数据 → 回退 csv
        yield from self.read_csv_fallback()

    def make_klu(self, ts, o, h, l, c, v) -> CKLine_Unit:
        # 落地数据的 ts 是K线开始时间(binance约定);框架约定日内K线时间为结束时间,
        # 多级别父子对齐依赖这一转换(如 4H 08:00-12:00 的子K线 1H 09:00~12:00 均 ≤ 12:00)
        from OfflineData.offline_data_util import KLTYPE_TO_MS
        if kltype_lt_day(self.k_type) and self.k_type in KLTYPE_TO_MS:
            ts = ts + KLTYPE_TO_MS[self.k_type]
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        return CKLine_Unit({
            DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute,
                                         auto=not kltype_lt_day(self.k_type)),
            DATA_FIELD.FIELD_OPEN: o,
            DATA_FIELD.FIELD_HIGH: h,
            DATA_FIELD.FIELD_LOW: l,
            DATA_FIELD.FIELD_CLOSE: c,
            DATA_FIELD.FIELD_VOLUME: v,
        }, autofix=True)

    def read_csv_fallback(self):
        from Config.EnvConfig import CEnv
        from OfflineData.offline_data_util import parse_dt_to_ts
        try:
            env = CEnv.get_instance()
            root = env.abs_path(env.offline_data_conf.get("root", "OfflineData/data"))
        except Exception:
            root = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "OfflineData", "data")
        k_type_str = self.k_type.name[2:].lower()
        safe_code = self.code.replace("/", "_")  # BTC/USDT → BTC_USDT
        csv_path = os.path.join(root, f"{safe_code}_{k_type_str}.csv")
        if not os.path.exists(csv_path):
            raise CChanException(
                f"离线数据不存在: sqlite 无 {self.code}/{self.k_type.name},csv 不存在 {csv_path};"
                f"请先运行 OfflineData/ccxt_update.py 或 bao_download.py 落地数据",
                ErrCode.SRC_DATA_NOT_FOUND,
            )
        begin_ts = parse_dt_to_ts(self.begin_date) if self.begin_date else None
        end_ts = parse_dt_to_ts(self.end_date) if self.end_date else None
        with open(csv_path, encoding="utf-8") as f:
            header = f.readline().strip().lower().split(",")
            has_vol = "volume" in header
            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 5:
                    continue
                ts = parse_dt_to_ts(parts[0])
                if begin_ts is not None and ts < begin_ts:
                    continue
                if end_ts is not None and ts >= end_ts:
                    break
                v = float(parts[5]) if has_vol and len(parts) > 5 and parts[5] else 0.0
                yield self.make_klu(ts, float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]), v)

    def SetBasciInfo(self):
        pass

    @classmethod
    def do_init(cls):
        pass

    @classmethod
    def do_close(cls):
        pass
