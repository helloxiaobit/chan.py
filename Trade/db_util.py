"""交易后端数据库封装:CChanDB()

无参构造,自动读 config.yaml(db.type: sqlite/mysql);
按信号生命周期状态机封装增删改查:
    signal → watching → open(突破+分数达标) → tracking(峰值/止损/止盈) → cover(平仓)
任何环节可 unwatch(记 reason);崩溃重启后从 DB 恢复现场,不重复开仓。
"""
import datetime
import json
from typing import List, Optional

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Signal import CSignal


def now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


class CChanDB:
    def __init__(self, table_name: str = "chan_trade", db_conf: Optional[dict] = None):
        if db_conf is None:
            from Config.EnvConfig import CEnv
            db_conf = CEnv.get_instance().db_conf
        db_type = db_conf.get("type", "sqlite")
        if db_type == "sqlite":
            from Config.EnvConfig import CEnv
            from .SqliteDB import CSqliteDB
            path = db_conf.get("sqlite_path", "Trade/chan_trade.db")
            try:
                path = CEnv.get_instance().abs_path(path)
            except Exception:
                pass
            self.db = CSqliteDB(path, table_name)
        elif db_type == "mysql":
            from .MysqlDB import CMysqlDB
            self.db = CMysqlDB(db_conf.get("mysql", {}), table_name)
        else:
            raise CChanException(f"未知数据库类型: {db_type}", ErrCode.UNKNOWN_DB_TYPE)
        self.table = table_name

    def close(self):
        self.db.close()

    # ===== 信号 =====
    def add_signal(self, signal: CSignal, stock_name: str = "") -> int:
        """信号入库(同code+级别+方向+目标K线时间的在途信号只保留一条),返回记录id"""
        exist = self.db.query_one(
            f"SELECT id FROM {self.table} WHERE stock_code=? AND lv=? AND is_buy=? "
            f"AND target_klu_time=? AND watching=1 AND is_open=0",
            (signal.code, signal.lv.name, int(signal.is_buy), str(signal.target_klu_time)),
        )
        if exist is not None:
            raise CChanException(f"信号已存在 id={exist['id']}", ErrCode.SIGNAL_EXISTED)
        return self.db.execute(
            f"INSERT INTO {self.table}(add_date, stock_code, stock_name, status, lv, bstype, is_buy,"
            f" open_thred, sl_thred, target_klu_time, watching, model_score_before)"
            f" VALUES(?,?,?,?,?,?,?,?,?,?,1,?)",
            (now_str(), signal.code, stock_name, "signal", signal.lv.name, signal.bs_type,
             int(signal.is_buy), signal.open_thred, signal.sl_thred, str(signal.target_klu_time),
             signal.score),
        )

    def get_watching_signals(self, code: Optional[str] = None) -> List[dict]:
        sql = f"SELECT * FROM {self.table} WHERE watching=1 AND is_open=0"
        args: tuple = ()
        if code is not None:
            sql += " AND stock_code=?"
            args = (code,)
        return self.db.query(sql, args)

    def unwatch(self, record_id: int, reason: str):
        cnt = self.db.execute(
            f"UPDATE {self.table} SET watching=0, unwatch_reason=?, signal_last_modify=? WHERE id=?",
            (reason, now_str(), record_id),
        )
        if cnt == 0:
            raise CChanException(f"记录不存在 id={record_id}", ErrCode.RECORD_NOT_EXIST)

    # ===== 开仓 =====
    def mark_open(self, record_id: int, open_price: float, quota: float,
                  order_id: str = "", score_before: Optional[float] = None,
                  snapshot: Optional[dict] = None, image_url: str = ""):
        rec = self.get_record(record_id)
        if rec["is_open"]:
            raise CChanException(f"记录已开仓 id={record_id}", ErrCode.RECORD_ALREADY_OPENED)
        if not rec["watching"]:
            raise CChanException(f"记录未在监控中 id={record_id}", ErrCode.OPEN_RECORD_NOT_WATCHING)
        self.db.execute(
            f"UPDATE {self.table} SET is_open=1, status='open', open_price=?, quota=?, open_date=?,"
            f" open_order_id=?, model_score_before=COALESCE(?, model_score_before), snapshot_before=?,"
            f" peak_price_after_open=?, open_image_url=? WHERE id=?",
            (open_price, quota, now_str(), order_id, score_before,
             json.dumps(snapshot or {}, ensure_ascii=False, default=str), open_price, image_url, record_id),
        )

    def get_open_records(self, code: Optional[str] = None) -> List[dict]:
        # 已开仓未平仓(跟踪中)
        sql = f"SELECT * FROM {self.table} WHERE is_open=1 AND status!='cover' AND is_cover_record=0"
        args: tuple = ()
        if code is not None:
            sql += " AND stock_code=?"
            args = (code,)
        return self.db.query(sql, args)

    def update_peak_price(self, record_id: int, price: float):
        rec = self.get_record(record_id)
        peak = rec["peak_price_after_open"]
        new_peak = max(peak, price) if rec["is_buy"] else min(peak, price)
        if new_peak != peak:
            self.db.execute(
                f"UPDATE {self.table} SET peak_price_after_open=? WHERE id=?", (new_peak, record_id))
        return new_peak

    def set_score_after(self, record_id: int, score: float, snapshot: Optional[dict] = None):
        self.db.execute(
            f"UPDATE {self.table} SET model_score_after=?, snapshot_after=? WHERE id=?",
            (score, json.dumps(snapshot or {}, ensure_ascii=False, default=str), record_id),
        )

    def set_open_err(self, record_id: int, reason: str):
        self.db.execute(
            f"UPDATE {self.table} SET open_err=1, open_err_reason=? WHERE id=?", (reason, record_id))

    def set_close_err(self, record_id: int, reason: str):
        self.db.execute(
            f"UPDATE {self.table} SET close_err=1, close_err_reason=? WHERE id=?", (reason, record_id))

    def get_error_opens(self) -> List[dict]:
        return self.db.query(
            f"SELECT * FROM {self.table} WHERE open_err=1 AND is_open=1 AND status!='cover'")

    # ===== 平仓 =====
    def mark_cover_order(self, record_id: int, cover_order_id: str, cover_quota: float, reason: str):
        rec = self.get_record(record_id)
        if not rec["is_open"]:
            raise CChanException(f"记录未开仓 id={record_id}", ErrCode.RECORD_NOT_OPENED)
        if rec["status"] == "cover":
            raise CChanException(f"记录已平仓 id={record_id}", ErrCode.RECORD_CLOSED)
        self.db.execute(
            f"UPDATE {self.table} SET cover_order_id=?, cover_quota=?, cover_date=?, cover_reason=? WHERE id=?",
            (cover_order_id, cover_quota, now_str(), reason, record_id),
        )

    def mark_cover_done(self, record_id: int, avg_price: float, image_url: str = ""):
        self.db.execute(
            f"UPDATE {self.table} SET status='cover', cover_avg_price=?, watching=0, cover_image_url=? WHERE id=?",
            (avg_price, image_url, record_id),
        )

    def get_uncovered_orders(self) -> List[dict]:
        # 已提交平仓单但未确认成交(修复用)
        return self.db.query(
            f"SELECT * FROM {self.table} WHERE is_open=1 AND status!='cover'"
            f" AND cover_order_id IS NOT NULL AND cover_order_id != ''")

    # ===== 通用 =====
    def get_record(self, record_id: int) -> dict:
        rec = self.db.query_one(f"SELECT * FROM {self.table} WHERE id=?", (record_id,))
        if rec is None:
            raise CChanException(f"记录不存在 id={record_id}", ErrCode.RECORD_NOT_EXIST)
        return rec

    def query_all(self) -> List[dict]:
        return self.db.query(f"SELECT * FROM {self.table} ORDER BY id")
