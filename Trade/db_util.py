"""交易后端数据库封装:CChanDB()

无参构造,自动读 config.yaml(db.type: sqlite/mysql);
按信号生命周期状态机封装增删改查:
    signal → watching → open(突破+分数达标) → tracking(峰值/止损/止盈) → cover(平仓)
任何环节可 unwatch(记 reason);崩溃重启后从 DB 恢复现场,不重复开仓。
"""
import datetime
import json
import math
from typing import List, Optional

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Signal import CSignal


def now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


ORDER_STATUSES = {"open", "closed", "canceled", "rejected"}


def _positive_qty(value: float, name: str) -> float:
    quantity = float(value)
    if not math.isfinite(quantity) or quantity <= 0:
        raise CChanException(f"{name}必须大于 0", ErrCode.PARA_ERROR)
    return quantity


def _cumulative_qty(value: float) -> float:
    quantity = float(value)
    if not math.isfinite(quantity) or quantity < 0:
        raise CChanException("累计成交量无效", ErrCode.PARA_ERROR)
    return quantity


def _order_status(value: str) -> str:
    if value not in ORDER_STATUSES:
        raise CChanException(f"未知订单状态: {value}", ErrCode.PARA_ERROR)
    return value


def _illegal_transition(record_id: int, current: str, action: str):
    raise CChanException(
        f"记录 {record_id} 状态 {current} 不能执行 {action}", ErrCode.PARA_ERROR
    )


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
        sql = (
            f"SELECT * FROM {self.table} "
            "WHERE watching=1 AND is_open=0 AND status='signal'"
        )
        args: tuple = ()
        if code is not None:
            sql += " AND stock_code=?"
            args = (code,)
        return self.db.query(sql, args)

    # ===== 可恢复订单状态机 =====
    def acquire_open_intent(
        self,
        record_id: int,
        requested_qty: float,
        client_order_id: str,
        position_side: str = "BOTH",
        strategy_version: str = "",
        risk_multiplier: float = 1.0,
    ) -> bool:
        requested = _positive_qty(requested_qty, "开仓请求量")
        if not client_order_id:
            raise CChanException("开仓客户端订单号不能为空", ErrCode.PARA_ERROR)
        side = str(position_side).upper()
        if side not in {"BOTH", "LONG", "SHORT"}:
            raise CChanException("持仓方向无效", ErrCode.PARA_ERROR)
        risk = float(risk_multiplier)
        if not math.isfinite(risk) or risk <= 0:
            raise CChanException("风险乘数必须大于 0", ErrCode.PARA_ERROR)
        changed = self.db.execute(
            f"UPDATE {self.table} SET status='submitted', "
            "open_client_order_id=?, open_requested_qty=?, "
            "open_filled_qty=0, current_qty=0, "
            "open_order_status='created', "
            "open_attempt=COALESCE(open_attempt, 0)+1, "
            "order_last_update=?, position_side=?, strategy_version=?, "
            "risk_multiplier=? "
            "WHERE id=? AND status='signal' AND watching=1 AND is_open=0 "
            "AND COALESCE(open_client_order_id, '')=''",
            (
                client_order_id,
                requested,
                now_str(),
                side,
                strategy_version,
                risk,
                record_id,
            ),
        )
        return changed == 1

    def record_open_submission(
        self, record_id: int, order_id: str, order_status: str
    ) -> None:
        raw_status = _order_status(order_status)
        if not order_id:
            raise CChanException("开仓交易所订单号不能为空", ErrCode.PARA_ERROR)
        changed = self.db.execute(
            f"UPDATE {self.table} SET open_order_id=?, open_order_status=?, "
            "order_last_update=? WHERE id=? "
            "AND status IN ('submitted', 'partially_filled')",
            (order_id, raw_status, now_str(), record_id),
        )
        if changed != 1:
            rec = self.get_record(record_id)
            _illegal_transition(record_id, rec["status"], "记录开仓提交")

    def apply_open_fill(
        self,
        record_id: int,
        cumulative_filled: float,
        avg_price: Optional[float],
        order_status: str,
    ) -> float:
        filled = _cumulative_qty(cumulative_filled)
        raw_status = _order_status(order_status)
        rec = self.get_record(record_id)
        current_status = rec["status"]
        if current_status not in {"submitted", "partially_filled", "open"}:
            _illegal_transition(record_id, current_status, "应用开仓成交")
        previous = float(rec["open_filled_qty"] or 0)
        requested = float(rec["open_requested_qty"] or 0)
        if current_status == "open" and filled != previous:
            _illegal_transition(record_id, current_status, "增加开仓成交")
        if filled < previous:
            raise CChanException("开仓累计成交量不能回退", ErrCode.PARA_ERROR)
        if requested <= 0 or filled > requested:
            raise CChanException("开仓累计成交量超过请求量", ErrCode.PARA_ERROR)
        if filled and (avg_price is None or float(avg_price) <= 0):
            raise CChanException("开仓成交均价无效", ErrCode.PARA_ERROR)

        if filled == 0:
            next_status = (
                raw_status if raw_status in {"canceled", "rejected"}
                else "submitted"
            )
        elif filled >= requested or raw_status in {
            "closed", "canceled", "rejected"
        }:
            next_status = "open"
        else:
            next_status = "partially_filled"
        is_open = int(filled > 0)
        watching = 0 if next_status in {"canceled", "rejected"} else 1
        open_date = now_str() if filled and not rec.get("open_date") else rec.get("open_date")
        open_price = float(avg_price) if filled else rec.get("open_price")
        peak = rec.get("peak_price_after_open")
        if filled and peak is None:
            peak = open_price
        self.db.execute(
            f"UPDATE {self.table} SET status=?, is_open=?, watching=?, "
            "open_filled_qty=?, current_qty=?, quota=?, open_price=?, "
            "open_date=?, peak_price_after_open=?, open_order_status=?, "
            "order_last_update=? WHERE id=?",
            (
                next_status,
                is_open,
                watching,
                filled,
                filled,
                filled,
                open_price,
                open_date,
                peak,
                raw_status,
                now_str(),
                record_id,
            ),
        )
        return filled - previous

    def acquire_close_intent(
        self,
        record_id: int,
        requested_qty: float,
        client_order_id: str,
        reason: str,
    ) -> bool:
        requested = _positive_qty(requested_qty, "平仓请求量")
        if not client_order_id:
            raise CChanException("平仓客户端订单号不能为空", ErrCode.PARA_ERROR)
        rec = self.get_record(record_id)
        current = float(rec["current_qty"] or 0)
        if requested > current:
            raise CChanException("平仓请求量超过当前仓位", ErrCode.PARA_ERROR)
        changed = self.db.execute(
            f"UPDATE {self.table} SET status='closing', "
            "cover_client_order_id=?, cover_requested_qty=?, "
            "cover_order_filled_qty=0, cover_order_avg_price=NULL, "
            "cover_order_status='created', cover_order_id=NULL, "
            "cover_attempt=COALESCE(cover_attempt, 0)+1, "
            "cover_quota=?, cover_date=?, cover_reason=?, "
            "order_last_update=? WHERE id=? AND status='open' "
            "AND is_open=1 AND current_qty>=?",
            (
                client_order_id,
                requested,
                requested,
                now_str(),
                reason,
                now_str(),
                record_id,
                requested,
            ),
        )
        return changed == 1

    def record_close_submission(
        self, record_id: int, order_id: str, order_status: str
    ) -> None:
        raw_status = _order_status(order_status)
        if not order_id:
            raise CChanException("平仓交易所订单号不能为空", ErrCode.PARA_ERROR)
        changed = self.db.execute(
            f"UPDATE {self.table} SET cover_order_id=?, cover_order_status=?, "
            "order_last_update=? WHERE id=? AND status='closing'",
            (order_id, raw_status, now_str(), record_id),
        )
        if changed != 1:
            rec = self.get_record(record_id)
            _illegal_transition(record_id, rec["status"], "记录平仓提交")

    def apply_close_fill(
        self,
        record_id: int,
        cumulative_filled: float,
        avg_price: Optional[float],
        order_status: str,
    ) -> float:
        filled = _cumulative_qty(cumulative_filled)
        raw_status = _order_status(order_status)
        rec = self.get_record(record_id)
        current_status = rec["status"]
        if current_status not in {"closing", "open", "closed"}:
            _illegal_transition(record_id, current_status, "应用平仓成交")
        previous_order = float(rec["cover_order_filled_qty"] or 0)
        requested = float(rec["cover_requested_qty"] or 0)
        if current_status in {"open", "closed"} and filled != previous_order:
            _illegal_transition(record_id, current_status, "增加平仓成交")
        if filled < previous_order:
            raise CChanException("平仓累计成交量不能回退", ErrCode.PARA_ERROR)
        if requested <= 0 or filled > requested:
            raise CChanException("平仓累计成交量超过请求量", ErrCode.PARA_ERROR)
        if filled and (avg_price is None or float(avg_price) <= 0):
            raise CChanException("平仓成交均价无效", ErrCode.PARA_ERROR)
        delta = filled - previous_order
        previous_current = float(rec["current_qty"] or 0)
        if delta > previous_current:
            raise CChanException("平仓成交量超过当前仓位", ErrCode.PARA_ERROR)
        current = previous_current - delta

        previous_total = float(rec["cover_filled_qty"] or 0)
        total = previous_total + delta
        previous_total_avg = float(rec["cover_avg_price"] or 0)
        previous_order_avg = float(rec["cover_order_avg_price"] or 0)
        other_notional = (
            previous_total * previous_total_avg
            - previous_order * previous_order_avg
        )
        total_avg = (
            (other_notional + filled * float(avg_price)) / total
            if total and avg_price is not None
            else rec.get("cover_avg_price")
        )

        if current <= 1e-12:
            current = 0.0
            next_status = "closed"
            is_open = 0
            watching = 0
        elif raw_status == "open":
            next_status = "closing"
            is_open = 1
            watching = 1
        else:
            # 当前订单已结束但仍有仓位，回到 open 后才能获取新的重试意图。
            next_status = "open"
            is_open = 1
            watching = 1
        self.db.execute(
            f"UPDATE {self.table} SET status=?, is_open=?, watching=?, "
            "current_qty=?, cover_order_filled_qty=?, "
            "cover_order_avg_price=?, cover_filled_qty=?, cover_avg_price=?, "
            "cover_order_status=?, order_last_update=? WHERE id=?",
            (
                next_status,
                is_open,
                watching,
                current,
                filled,
                float(avg_price) if filled else rec.get("cover_order_avg_price"),
                total,
                total_avg,
                raw_status,
                now_str(),
                record_id,
            ),
        )
        return delta

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
            f" peak_price_after_open=?, open_image_url=?, open_requested_qty=?,"
            f" open_filled_qty=?, current_qty=?, open_order_status='closed',"
            f" order_last_update=? WHERE id=?",
            (open_price, quota, now_str(), order_id, score_before,
             json.dumps(snapshot or {}, ensure_ascii=False, default=str), open_price,
             image_url, quota, quota, quota, now_str(), record_id),
        )

    def get_open_records(self, code: Optional[str] = None) -> List[dict]:
        # 已开仓未平仓(跟踪中)
        sql = (
            f"SELECT * FROM {self.table} WHERE is_open=1 "
            "AND status NOT IN ('cover', 'closed', 'canceled', 'rejected') "
            "AND is_cover_record=0"
        )
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
            f"SELECT * FROM {self.table} WHERE open_err=1 AND is_open=1 "
            "AND status NOT IN ('cover', 'closed')")

    # ===== 平仓 =====
    def mark_cover_order(self, record_id: int, cover_order_id: str, cover_quota: float, reason: str):
        rec = self.get_record(record_id)
        if not rec["is_open"]:
            raise CChanException(f"记录未开仓 id={record_id}", ErrCode.RECORD_NOT_OPENED)
        if rec["status"] in {"cover", "closed"}:
            raise CChanException(f"记录已平仓 id={record_id}", ErrCode.RECORD_CLOSED)
        self.db.execute(
            f"UPDATE {self.table} SET status='closing', cover_order_id=?, "
            "cover_quota=?, cover_requested_qty=?, cover_order_filled_qty=0, "
            "cover_order_avg_price=NULL, cover_order_status='open', "
            "cover_attempt=COALESCE(cover_attempt, 0)+1, cover_date=?, "
            "cover_reason=?, order_last_update=? WHERE id=?",
            (
                cover_order_id,
                cover_quota,
                cover_quota,
                now_str(),
                reason,
                now_str(),
                record_id,
            ),
        )

    def mark_cover_done(self, record_id: int, avg_price: float, image_url: str = ""):
        rec = self.get_record(record_id)
        if rec["status"] in {"cover", "closed"}:
            return
        requested = float(rec["cover_requested_qty"] or rec["current_qty"] or rec["quota"] or 0)
        previous_order = float(rec["cover_order_filled_qty"] or 0)
        target = max(requested, previous_order)
        if rec["status"] != "closing":
            self.db.execute(
                f"UPDATE {self.table} SET status='closing', "
                "cover_requested_qty=?, cover_order_filled_qty=? WHERE id=?",
                (target, previous_order, record_id),
            )
        self.apply_close_fill(record_id, target, avg_price, "closed")
        self.db.execute(
            f"UPDATE {self.table} SET cover_image_url=? WHERE id=?",
            (image_url, record_id),
        )

    def get_uncovered_orders(self) -> List[dict]:
        # 已提交平仓单但未确认成交(修复用)
        return self.db.query(
            f"SELECT * FROM {self.table} WHERE is_open=1 "
            "AND status NOT IN ('cover', 'closed')"
            f" AND cover_order_id IS NOT NULL AND cover_order_id != ''")

    # ===== 通用 =====
    def get_record(self, record_id: int) -> dict:
        rec = self.db.query_one(f"SELECT * FROM {self.table} WHERE id=?", (record_id,))
        if rec is None:
            raise CChanException(f"记录不存在 id={record_id}", ErrCode.RECORD_NOT_EXIST)
        return rec

    def query_all(self) -> List[dict]:
        return self.db.query(f"SELECT * FROM {self.table} ORDER BY id")
