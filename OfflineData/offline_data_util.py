"""离线K线通用存储层:sqlite 落地/增量合并/csv 导入

表结构 kline: symbol/lv/ts/o/h/l/c/v,唯一索引(symbol,lv,ts),增量更新用 upsert。
lv 存 KL_TYPE.name(如 K_60M),ts 为该K线开始时间的 epoch 毫秒(UTC)。
"""
import os
import sqlite3
import json
from pathlib import Path
from contextlib import closing
from itertools import zip_longest
from datetime import datetime, timezone
from typing import Iterable, Iterator, List, Optional, Tuple, Union

from Common.CEnum import KL_TYPE
from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import KLTYPE_TO_MS, bar_close_ms, validate_ohlcv_page

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
    def __init__(self, db_path: Optional[str] = None, *, read_only: bool = False):
        self.db_path = db_path or default_db_path()
        if read_only:
            # 运行准入的观察不能为错误路径/旧库暗中创建或升级任何表。
            self.conn = sqlite3.connect(Path(self.db_path).resolve().as_uri()+"?mode=ro", uri=True)
            self.conn.execute("PRAGMA query_only=ON")
        else:
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

    @property
    def source_identity(self):
        if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='kline_source'").fetchone():
            return None
        row = self.conn.execute("SELECT payload FROM kline_source WHERE id=1").fetchone()
        return json.loads(row[0]) if row else None

    def check_source(self, identity):
        identity = validate_source_identity(identity)
        if self.source_identity != identity:
            raise CChanException("行情库来源缺失或不匹配，需显式迁移旧库来源或使用独立库", ErrCode.SRC_DATA_TYPE_ERR)

    def bind_source(self, identity, *, adopt_legacy=False):
        """一库一个来源，symbol/lv 保留行级索引；旧数据不自动推断来源。"""
        identity = validate_source_identity(identity)
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            current = self.source_identity
            if current is not None:
                self.check_source(identity)
                return
            if not adopt_legacy and self.conn.execute("SELECT 1 FROM kline LIMIT 1").fetchone():
                raise CChanException("旧库有数据但无来源；备份并显式映射来源后才能迁移", ErrCode.SRC_DATA_TYPE_ERR)
            self.conn.execute("CREATE TABLE IF NOT EXISTS kline_source (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
            self.conn.execute("INSERT INTO kline_source VALUES(1,?)", (json.dumps(identity, sort_keys=True),))

    def upsert_klines(self, symbol: str, lv: Union[KL_TYPE, str], rows: Iterable[ROW_TYPE]) -> int:
        cur = self.conn.executemany(
            "INSERT INTO kline(symbol, lv, ts, o, h, l, c, v) VALUES(?,?,?,?,?,?,?,?)"
            " ON CONFLICT(symbol, lv, ts) DO UPDATE SET o=excluded.o, h=excluded.h,"
            " l=excluded.l, c=excluded.c, v=excluded.v"
            " WHERE kline.o IS NOT excluded.o OR kline.h IS NOT excluded.h"
            " OR kline.l IS NOT excluded.l OR kline.c IS NOT excluded.c OR kline.v IS NOT excluded.v",
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
        return list(self.iter_klines(symbol, lv, begin_ts, end_ts))

    def iter_klines(
        self,
        symbol: str,
        lv: Union[KL_TYPE, str],
        begin_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
    ) -> Iterator[ROW_TYPE]:
        """Ordered raw rows without a retained history; close on exhaustion or iterator.close()."""
        sql = "SELECT ts, o, h, l, c, v FROM kline WHERE symbol=? AND lv=?"
        args: list = [symbol, lv_name(lv)]
        if begin_ts is not None:
            sql += " AND ts>=?"
            args.append(begin_ts)
        if end_ts is not None:
            sql += " AND ts<?"
            args.append(end_ts)
        sql += " ORDER BY ts ASC"
        with closing(self.conn.execute(sql, args)) as cursor:
            yield from cursor

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

    def inspect_quality(self, symbol, lv, *, now_ms, market_active=None):
        source = self.source_identity
        status = "unknown_source" if not source else "inactive" if market_active is False else "ready"
        count, latest_close, previous_open = 0, None, None
        with closing(self.iter_klines(symbol, lv)) as rows:
            for row in rows:
                close_ms = bar_close_ms(row[0], lv)
                if close_ms > now_ms:
                    continue
                count += 1
                latest_close = close_ms
                if status == "ready":
                    try:
                        validate_ohlcv_page((row,), lv, previous_open=previous_open)
                    except CChanException:
                        status = "gap"
                previous_open = row[0]
        if status == "ready":
            if not count:
                status = "no_data"
            elif bar_close_ms(latest_close, lv) <= now_ms:
                status = "stale"
        return {"status": status, "ready": status == "ready", "source": source,
                "symbol": symbol, "timeframe": lv_name(lv), "closed_count": count,
                "latest_close_ms": latest_close}

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def validate_source_identity(identity):
    keys = {"exchange", "market_type", "settle", "price_type"}
    if (not isinstance(identity, dict) or set(identity) != keys
            or not all(isinstance(v, str) for v in identity.values())
            or not identity["exchange"] or identity["market_type"] not in {"spot", "swap", "future"}
            or identity["price_type"] not in {"contract", "mark", "index"}
            or (identity["market_type"] != "spot" and not identity["settle"])
            or (identity["market_type"] == "spot" and identity["settle"])):
        raise CChanException("行情来源必须显式包含 exchange/market_type/settle/price_type", ErrCode.SRC_DATA_TYPE_ERR)
    return dict(identity)


def configured_source_identity(symbol):
    from Config.EnvConfig import CEnv
    env = CEnv.get_instance()
    identity = env.offline_data_conf.get("source_identity")
    if identity is None:
        conf = env.ccxt_conf
        identity = {"exchange": conf.get("exchange", ""),
                    "market_type": conf.get("default_type", "spot"),
                    "settle": symbol.split(":", 1)[1] if ":" in symbol else "",
                    "price_type": "contract"}
    return validate_source_identity(identity)


def migrate_legacy_source(db_path, identity, backup_path):
    """停用写入器后显式迁移，先保留完整 SQLite 备份，不覆盖已有备份。"""
    identity = validate_source_identity(identity)
    source, backup = Path(db_path).resolve(), Path(backup_path).resolve()
    if not source.is_file() or source == backup:
        raise CChanException("迁移需要存在的旧库和独立备份路径", ErrCode.SRC_DATA_TYPE_ERR)
    with CKLineDB(str(source)) as db:
        if db.source_identity is not None:
            raise CChanException("来源已绑定，不能重复迁移或更改来源", ErrCode.SRC_DATA_TYPE_ERR)
        with open(backup, "xb"):
            pass
        with closing(sqlite3.connect(str(backup))) as old:
            db.conn.backup(old)
            sql = "SELECT * FROM kline ORDER BY symbol,lv,ts"
            if any(a != b for a, b in zip_longest(old.execute(sql), db.conn.execute(sql))):
                raise CChanException("迁移期间行情改变，停止写入器后再迁移", ErrCode.SRC_DATA_TYPE_ERR)
        db.bind_source(identity, adopt_legacy=True)


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
