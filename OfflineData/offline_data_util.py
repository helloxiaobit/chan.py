"""离线K线通用存储层:sqlite 落地/增量合并/csv 导入

表结构 kline: symbol/lv/ts/o/h/l/c/v,唯一索引(symbol,lv,ts),增量更新用 upsert。
lv 存 KL_TYPE.name(如 K_60M),ts 为该K线开始时间的 epoch 毫秒(UTC)。
"""
import os
import sqlite3
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Tuple, Union

from Common.CEnum import KL_TYPE

ROW_TYPE = Tuple[int, float, float, float, float, float]  # ts, o, h, l, c, v


def lv_name(lv: Union[KL_TYPE, str]) -> str:
    return lv.name if isinstance(lv, KL_TYPE) else str(lv)


def default_db_path() -> str:
    try:
        from Config.EnvConfig import CEnv
        env = CEnv.get_instance()
        return env.abs_path(env.offline_data_conf.get("sqlite_path", "OfflineData/data/kline.db"))
    except Exception:
        return os.path.join(os.path.dirname(os.path.realpath(__file__)), "data", "kline.db")


class CKLineDB:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or default_db_path()
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.ensure_table()

    def ensure_table(self):
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS kline ("
            " symbol TEXT NOT NULL, lv TEXT NOT NULL, ts INTEGER NOT NULL,"
            " o REAL, h REAL, l REAL, c REAL, v REAL,"
            " UNIQUE(symbol, lv, ts))"
        )
        self.conn.commit()

    def upsert_klines(self, symbol: str, lv: Union[KL_TYPE, str], rows: Iterable[ROW_TYPE]) -> int:
        cur = self.conn.executemany(
            "INSERT INTO kline(symbol, lv, ts, o, h, l, c, v) VALUES(?,?,?,?,?,?,?,?)"
            " ON CONFLICT(symbol, lv, ts) DO UPDATE SET o=excluded.o, h=excluded.h,"
            " l=excluded.l, c=excluded.c, v=excluded.v",
            [(symbol, lv_name(lv), *row) for row in rows],
        )
        self.conn.commit()
        return cur.rowcount

    def query_klines(
        self,
        symbol: str,
        lv: Union[KL_TYPE, str],
        begin_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
    ) -> List[ROW_TYPE]:
        sql = "SELECT ts, o, h, l, c, v FROM kline WHERE symbol=? AND lv=?"
        args: list = [symbol, lv_name(lv)]
        if begin_ts is not None:
            sql += " AND ts>=?"
            args.append(begin_ts)
        if end_ts is not None:
            sql += " AND ts<?"
            args.append(end_ts)
        sql += " ORDER BY ts ASC"
        return list(self.conn.execute(sql, args))

    def last_ts(self, symbol: str, lv: Union[KL_TYPE, str]) -> Optional[int]:
        row = self.conn.execute(
            "SELECT MAX(ts) FROM kline WHERE symbol=? AND lv=?", (symbol, lv_name(lv))
        ).fetchone()
        return row[0]

    def count(self, symbol: str, lv: Union[KL_TYPE, str]) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM kline WHERE symbol=? AND lv=?", (symbol, lv_name(lv))
        ).fetchone()[0]

    def symbols(self) -> List[Tuple[str, str]]:
        return list(self.conn.execute("SELECT DISTINCT symbol, lv FROM kline"))

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def parse_dt_to_ts(s: str) -> int:
    # "2020-11-02 00:00:00" / "2020-11-02" (UTC) → epoch 毫秒
    fmt = "%Y-%m-%d %H:%M:%S" if len(s) > 10 else "%Y-%m-%d"
    dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def import_csv(db: CKLineDB, symbol: str, lv: Union[KL_TYPE, str], csv_path: str, tz_utc: bool = True) -> int:
    """导入 csv(表头 datetime,open,high,low,close[,volume])到 sqlite,返回导入行数

    用于把已有的本地历史数据(如 binance 导出)一次性灌库,之后由 ccxt_update 增量续传。
    """
    rows: List[ROW_TYPE] = []
    with open(csv_path, encoding="utf-8") as f:
        header = f.readline().strip().lower().split(",")
        has_vol = "volume" in header
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 5:
                continue
            ts = parse_dt_to_ts(parts[0])
            v = float(parts[5]) if has_vol and len(parts) > 5 and parts[5] else 0.0
            rows.append((ts, float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]), v))
    db.upsert_klines(symbol, lv, rows)
    return len(rows)
