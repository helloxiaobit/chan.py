"""交易后端数据库封装:CChanDB()

无参构造,自动读 config.yaml(db.type: sqlite/mysql);
按信号生命周期状态机封装增删改查:
    signal → watching → open(突破+分数达标) → tracking(峰值/止损/止盈) → cover(平仓)
任何环节可 unwatch(记 reason);崩溃重启后从 DB 恢复现场,不重复开仓。
"""
import datetime
import json
import math
import sqlite3
from decimal import Context, Decimal, Inexact, localcontext
from typing import List, Optional

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Signal import CSignal
from CustomBuySellPoint.Decision import canonical_bytes, read_decision


def now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


ORDER_STATUSES = {"open", "closed", "canceled", "rejected"}
_FILL_CAS_FIELDS = {
    "status": "", "is_open": 0, "watching": 0, "quota": 0, "current_qty": 0,
    "open_client_order_id": "", "open_order_id": "", "open_order_status": "", "open_attempt": 0,
    "open_requested_qty": 0, "open_filled_qty": 0, "open_price": 0, "open_date": "",
    "peak_price_after_open": 0,
    "cover_client_order_id": "", "cover_order_id": "", "cover_order_status": "", "cover_attempt": 0,
    "cover_requested_qty": 0, "cover_order_filled_qty": 0, "cover_order_avg_price": 0,
    "cover_filled_qty": 0, "cover_avg_price": 0,
}


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


def _exact_qty_float(value: Decimal) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0 or Decimal(str(result)) != value:
        raise CChanException("数量无法经 DB 数值边界原样保存", ErrCode.PARA_ERROR)
    return result


def _order_status(value: str) -> str:
    if value not in ORDER_STATUSES:
        raise CChanException(f"未知订单状态: {value}", ErrCode.PARA_ERROR)
    return value


def _has_order_contract(record):
    return any(record.get(f"{side}_order_contract") is not None for side in ("open", "cover"))


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
        self.db_type = db_type
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
        if self.db_type == "sqlite":
            with self.db.transaction():
                return self._add_signal(signal, stock_name)
        return self._add_signal(signal, stock_name)

    def _add_signal(self, signal: CSignal, stock_name: str) -> int:
        """冻结信号按原机会键全生命周期去重；旧无冻结信号保留在途语义。"""
        version, deployment_id = signal.model_artifact_id, signal.deployment_id
        if version or deployment_id:
            from Trade.Script.Deployment import CDeployment, verify_signal_assessment
            if self.db_type != "sqlite":
                raise CChanException("模型部署暂仅通过 SQLite 验收，MySQL 迁移未认证", ErrCode.MODEL_ERROR)
            if not version or not deployment_id or signal.decision is None or not signal.deployment_path:
                raise CChanException("模型信号缺少冻结部署身份", ErrCode.MODEL_ERROR)
            decision = read_decision(signal.decision)
            identity, payload = decision["identity"], decision["payload"]
            if (identity["code"] != signal.code or identity["level"] != signal.lv.name
                    or identity["is_buy"] != signal.is_buy or identity["bs_type"] != signal.bs_type
                    or payload["target_klu_ms"] != (int(signal.target_klu_time.ts*1000) if signal.target_klu_time is not None else None)
                    or payload["score"] != signal.score or payload["model_artifact_id"] != version
                    or payload["deployment_id"] != deployment_id or payload["open_thred"] != signal.open_thred
                    or payload["deployment_path"] != signal.deployment_path
                    or payload["sl_thred"] != signal.sl_thred):
                raise CChanException("信号可变字段与已发布字节漂移", ErrCode.MODEL_ERROR)
            snapshot = verify_signal_assessment(CDeployment(signal.deployment_path), decision)
            if not snapshot["passed"]:
                raise CChanException("候选模型分数未达到冻结阈值", ErrCode.MODEL_ERROR)
        frozen = self.db_type == "sqlite" and type(signal.decision) is bytes
        if frozen:
            read_decision(signal.decision)
            matches = self.get_signal_records(signal.code, signal.lv.name, signal.is_buy, signal.target_klu_time)
            exist = matches[0] if matches else None
        else:
            exist = self.db.query_one(
                f"SELECT id FROM {self.table} WHERE stock_code=? AND lv=? AND is_buy=? "
                f"AND target_klu_time=? AND watching=1 AND is_open=0",
                (signal.code, signal.lv.name, int(signal.is_buy), str(signal.target_klu_time)),
            )
        if exist is not None:
            raise CChanException(f"信号已存在 id={exist['id']}", ErrCode.SIGNAL_EXISTED)
        extra_columns = ",model_version,deployment_id,deployment_path,signal_decision" if self.db_type == "sqlite" else ""
        extra_values = ",?,?,?,?" if self.db_type == "sqlite" else ""
        extra_args = (version, deployment_id, signal.deployment_path,
                      signal.decision.decode("utf-8") if signal.decision is not None else None) if self.db_type == "sqlite" else ()
        return self.db.execute(
            f"INSERT INTO {self.table}(add_date, stock_code, stock_name, status, lv, bstype, is_buy,"
            f" open_thred, sl_thred, target_klu_time, watching, model_score_before{extra_columns})"
            f" VALUES(?,?,?,?,?,?,?,?,?,?,1,?{extra_values})",
            (now_str(), signal.code, stock_name, "signal", signal.lv.name, signal.bs_type,
             int(signal.is_buy), signal.open_thred, signal.sl_thred, str(signal.target_klu_time),
             signal.score) + extra_args,
        )

    def get_signal_records(self, code, level, is_buy, target_klu_time):
        """Original opportunity key across all lifecycle states; never pick a winner."""
        return self.db.query(f"SELECT * FROM {self.table} WHERE stock_code=? AND lv=? AND is_buy=? "
            "AND target_klu_time=? ORDER BY id", (code, level, int(is_buy), str(target_klu_time)))

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
    def _order_write(self, record_id, prefix, kind, sql, args, *, native_boundary=None, native_updates=None, native_preparation=None):
        if self.db_type != "sqlite":
            return self.db.execute(sql, args)  # Legacy only; no crypto migration certification.
        from .OrderAudit import read_history, record_transition
        with self.db.transaction():
            before = self.get_record(record_id)
            history = read_history(self.db, self.table, before)
            transition = None
            if prefix == "open" and kind in {"intent", "claim"}:
                from .NativeOrderTransition import prepare_transition
                preparation = {} if native_preparation is None else {"prepared_context": native_preparation}
                transition = prepare_transition(self, before, kind, native_updates, native_boundary, history=history, **preparation)
            changed = self.db.execute(sql, args)
            if changed == 1:
                after = self.get_record(record_id)
                if prefix == "open" and kind in {"intent", "claim"} and after.get("open_order_contract") is not None:
                    from .AccountRiskStore import assert_new_risk_allowed
                    contract = json.loads(after["open_order_contract"])
                    if contract.get("schema") == "chan-ccxt-order-v3":
                        assert_new_risk_allowed(self.db, contract["account_context"])
                if transition is None:
                    record_transition(self.db, self.table, before, after, prefix, kind)
                else:
                    from .NativeOrderTransition import finish_transition
                    record_transition(self.db, self.table, before, after, prefix, kind,
                                      native_boundary_sha256=transition["binding_sha256"], native_delta=transition["native_delta"])
                    finish_transition(self, before, after, transition)
        return changed

    def get_order_history(self, record_id):
        if self.db_type != "sqlite":
            raise CChanException("MySQL 订单历史迁移/事务未认证", ErrCode.LIST_ORDER_FAIL)
        from .OrderAudit import read_history
        with self.db.transaction():
            return read_history(self.db, self.table, self.get_record(record_id))

    def store_execution_scan(self, receipt, *, account_observation=None):
        self._require_execution_sqlite()
        from .ExecutionStore import store_scan
        snapshot = json.loads(canonical_bytes({"receipt": receipt, "account": account_observation}))
        try:
            with self.db.transaction():
                return store_scan(self.db, snapshot["receipt"], snapshot["account"])
        except sqlite3.DatabaseError:
            raise CChanException("逐笔来源存储冲突/失败，整组回滚且禁止重下", ErrCode.LIST_ORDER_FAIL) from None

    def get_execution_scan_account(self, scan_id):
        self._require_execution_sqlite()
        from .ExecutionStore import read_scan_account
        with self.db.transaction():
            return read_scan_account(self.db, scan_id)

    def get_execution_ownership(self, scan_id):
        self._require_execution_sqlite()
        from .ExecutionStore import read_scan_with_account
        from .ExecutionReconcile import build_execution_ownership
        from .OrderAudit import read_history
        with self.db.transaction():
            receipt, linked = read_scan_with_account(self.db, scan_id)
            if linked is None:
                raise CChanException("旧扫描缺少本次原生账户观察，不能回填归属", ErrCode.LIST_ORDER_FAIL)
            records = self.db.query(f"SELECT * FROM {self.table} WHERE stock_code=? ORDER BY id", (receipt["payload"]["market"]["symbol"],))
            histories = [read_history(self.db, self.table, row) for row in records]
            return build_execution_ownership(receipt, linked["observation"]["account_context"], histories)

    def get_execution_scans(self, account_scope, instrument):
        self._require_execution_sqlite()
        from .ExecutionStore import read_scans
        with self.db.transaction():
            return read_scans(self.db, account_scope, instrument)

    def get_execution_facts(self, account_scope, instrument, *, venue, mode):
        self._require_execution_sqlite()
        from .ExecutionStore import read_facts
        with self.db.transaction():
            return read_facts(self.db, account_scope, instrument, venue, mode)

    def _require_execution_sqlite(self):
        if self.db_type != "sqlite":
            raise CChanException("MySQL 逐笔经济来源迁移/事务未认证", ErrCode.LIST_ORDER_FAIL)

    def store_account_evidence(self, document):
        self._require_execution_sqlite()
        from .AccountStore import store_evidence
        document = json.loads(canonical_bytes(document))
        try:
            with self.db.transaction():
                return store_evidence(self.db, document)
        except sqlite3.DatabaseError:
            raise CChanException("账户来源发布失败/冲突，整份证据回滚", ErrCode.LIST_ORDER_FAIL) from None

    def get_account_evidence(self, evidence_id):
        self._require_execution_sqlite()
        from .AccountStore import read_evidence
        with self.db.transaction():
            return read_evidence(self.db, evidence_id)

    def store_native_account_observation(self, document):
        self._require_execution_sqlite()
        from .NativeAccountStore import store_observation
        document = json.loads(canonical_bytes(document))
        try:
            with self.db.transaction():
                return store_observation(self.db, document)
        except sqlite3.DatabaseError:
            raise CChanException("原生账户来源发布失败，整份观察回滚", ErrCode.LIST_ORDER_FAIL) from None

    def get_native_account_observation(self, evidence_id):
        self._require_execution_sqlite()
        from .NativeAccountStore import read_observation
        with self.db.transaction():
            return read_observation(self.db, evidence_id)

    def get_native_account_observations(self, account_context):
        self._require_execution_sqlite()
        from .NativeAccountStore import read_account_observations
        account_context = json.loads(canonical_bytes(account_context))
        with self.db.transaction():
            return read_account_observations(self.db, account_context)

    def reconcile_account(self, *, account_context, before_id, after_id, wallet_ids, execution_scan_ids):
        self._require_execution_sqlite()
        from .AccountRiskStore import reconcile
        snapshot = json.loads(canonical_bytes({"context": account_context, "request": {
            "before": before_id, "after": after_id, "wallets": wallet_ids, "executions": execution_scan_ids}}))
        try:
            with self.db.transaction():
                return reconcile(self, snapshot["context"], snapshot["request"])
        except sqlite3.DatabaseError:
            raise CChanException("账户对账/冻结发布失败，禁止新增风险", ErrCode.TRADE_UNLOCK_FAIL) from None

    def get_account_check(self, check_id):
        self._require_execution_sqlite()
        from .AccountRiskStore import read_check
        with self.db.transaction():
            return read_check(self.db, check_id)

    def reconcile_native_account(self, *, account_context, before_id, after_id, wallet_ids, execution_scan_ids, pending_id, balance_id):
        self._require_execution_sqlite()
        from .NativeAccountCheck import reconcile_native_account
        snapshot = json.loads(canonical_bytes({"context": account_context, "request": {
            "before": before_id, "after": after_id, "wallets": wallet_ids, "executions": execution_scan_ids,
            "pending": pending_id, "balance": balance_id}}))
        try:
            with self.db.transaction():
                return reconcile_native_account(self, snapshot["context"], snapshot["request"])
        except sqlite3.DatabaseError:
            raise CChanException("原生账户检查/失败冻结发布失败，禁止新增风险", ErrCode.TRADE_UNLOCK_FAIL) from None

    def get_account_risk_state(self, account_context):
        self._require_execution_sqlite()
        from .AccountRiskStore import risk_state
        with self.db.transaction():
            return risk_state(self.db, account_context)

    def assert_account_new_risk_allowed(self, account_context):
        self._require_execution_sqlite()
        from .AccountRiskStore import assert_new_risk_allowed
        with self.db.transaction():
            assert_new_risk_allowed(self.db, account_context)

    def _write_fill(self, record, prefix, assignments, values):
        # Compare the complete read/write ledger snapshot, including both
        # attempts. One SQL statement is atomic across independent connections;
        # never recompute a stale report against whichever attempt happens next.
        guards = " AND ".join(f"COALESCE({name}, ?)=?" for name in _FILL_CAS_FIELDS)
        observed = tuple(value for name, default in _FILL_CAS_FIELDS.items()
                         for value in (default, record[name] if record.get(name) is not None else default))
        changed = self._order_write(record["id"], prefix, "report",
            f"UPDATE {self.table} SET {assignments} WHERE id=? AND {guards}",
            (*values, record["id"], *observed),
        )
        if changed != 1:
            raise CChanException("成交行已并发改变，保留赢家并重新查单，禁止重下", ErrCode.LIST_ORDER_FAIL)

    def _finish_duplicate_fill(self, record, prefix, raw_status):
        saved_status = record.get(f"{prefix}_order_status")
        if saved_status == raw_status or (saved_status in {"closed", "canceled", "rejected"} and raw_status == "open"):
            return 0.0
        if saved_status in {"closed", "canceled", "rejected"}:
            raise CChanException("已应用终态与回报矛盾，禁止回绕", ErrCode.LIST_ORDER_FAIL)
        # A fully filled order may report its final status later. Confirm it
        # without resetting current_qty after an actual partial/final exit.
        self._write_fill(record, prefix, f"{prefix}_order_status=?, order_last_update=?", (raw_status, now_str()))
        return 0.0

    @staticmethod
    def _fill_identity(record, prefix, client_order_id, order_id, expected_attempt):
        known = record.get(f"{prefix}_order_id")
        has_contract = _has_order_contract(record)
        if has_contract and (client_order_id is None or expected_attempt is None):
            raise CChanException("合约回报必须绑定当前 client/attempt/id", ErrCode.LIST_ORDER_FAIL)
        if (expected_attempt is not None and (type(expected_attempt) is not int or expected_attempt <= 0
                or record.get(f"{prefix}_attempt") != expected_attempt)):
            raise CChanException("回报不属于当前尝试次数，禁止 ABA 串单", ErrCode.LIST_ORDER_FAIL)
        if client_order_id is None:
            # Compatibility for old non-contract DB callers, not certification
            # of a client-less crypto execution path.
            if order_id is not None and known is not None and str(known) != str(order_id):
                raise CChanException("回报不能替换已知订单号", ErrCode.LIST_ORDER_FAIL)
            return known if order_id is None else str(order_id)
        if (not isinstance(client_order_id, str) or not client_order_id
                or not isinstance(order_id, str) or not order_id
                or record.get(f"{prefix}_client_order_id") != client_order_id
                or (known is not None and str(known) != order_id)):
            raise CChanException("回报不属于当前 client/id，禁止串单", ErrCode.LIST_ORDER_FAIL)
        return order_id

    def acquire_open_intent(
        self,
        record_id: int,
        requested_qty: float,
        client_order_id: str,
        position_side: str = "BOTH",
        strategy_version: str = "",
        risk_multiplier: float = 1.0,
        score_before: Optional[float] = None,
        snapshot: Optional[dict] = None,
        order_contract: Optional[dict] = None,
        native_boundary: Optional[dict] = None,
        native_preparation=None,
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
        if order_contract is not None and self.db_type != "sqlite":
            raise CChanException("MySQL 订单单位契约迁移尚未验收", ErrCode.TRADE_UNLOCK_FAIL)
        from .NativeOrderTransition import CONTRACT_SCHEMA, CLIENT_CONTRACT_SCHEMA
        monetary = isinstance(order_contract, dict) and order_contract.get("schema") == CLIENT_CONTRACT_SCHEMA
        diagnostic = isinstance(order_contract, dict) and order_contract.get("schema") in {CONTRACT_SCHEMA, CLIENT_CONTRACT_SCHEMA}
        if monetary and native_preparation is None:
            raise CChanException("条件金额契约必须由同次原prepare与原CAS创建", ErrCode.TRADE_UNLOCK_FAIL)
        if diagnostic != (native_boundary is not None):
            raise CChanException("原生 CAS 诊断契约必须绑定本次 L0，不能替代普通 v3 或资金许可", ErrCode.TRADE_UNLOCK_FAIL)
        if native_preparation is not None and native_boundary is None:
            raise CChanException("实际准备上下文必须由原生诊断 CAS 消费", ErrCode.TRADE_UNLOCK_FAIL)
        if native_boundary is not None and score_before is not None and (type(score_before) not in (int, float) or not math.isfinite(score_before)):
            raise CChanException("原生 CAS 分数须是有限数字，不接受隐式类型转换", ErrCode.TRADE_UNLOCK_FAIL)
        contract_clause = ", open_order_contract=?, open_intent_ms=?" if self.db_type == "sqlite" else ""
        contract_args = (canonical_bytes(order_contract).decode() if order_contract is not None else None, utc_now_ms()) if contract_clause else ()
        if native_boundary is not None and self.db_type != "sqlite":
            raise CChanException("原生逐单边界仅适用原 SQLite 事务", ErrCode.TRADE_UNLOCK_FAIL)
        updated_at = now_str()
        snapshot_raw = json.dumps(snapshot or {}, ensure_ascii=False, default=str)
        native_updates = None if native_boundary is None else {
            "status": "submitted", "open_client_order_id": client_order_id, "open_requested_qty": requested,
            "open_filled_qty": 0.0, "current_qty": 0.0, "open_order_status": "created", "order_last_update": updated_at,
            "position_side": side, "strategy_version": strategy_version, "risk_multiplier": risk,
            "model_score_before": None if score_before is None else float(score_before), "snapshot_before": snapshot_raw,
            "open_order_contract": contract_args[0], "open_intent_ms": contract_args[1]}
        changed = self._order_write(record_id, "open", "intent",
            f"UPDATE {self.table} SET status='submitted', "
            "open_client_order_id=?, open_requested_qty=?, "
            "open_filled_qty=0, current_qty=0, "
            "open_order_status='created', "
            "open_attempt=COALESCE(open_attempt, 0)+1, "
            "order_last_update=?, position_side=?, strategy_version=?, "
            "risk_multiplier=?, "
            "model_score_before=COALESCE(?, model_score_before), "
            "snapshot_before=?" + contract_clause + " "
            "WHERE id=? AND status='signal' AND watching=1 AND is_open=0 "
            "AND COALESCE(open_client_order_id, '')=''",
            (
                client_order_id,
                requested,
                updated_at,
                side,
                strategy_version,
                risk,
                score_before,
                snapshot_raw,
                *contract_args,
                record_id,
            ), native_boundary=native_boundary, native_updates=native_updates,
            **({} if native_preparation is None else {"native_preparation": native_preparation}),
        )
        return changed == 1

    def record_order_ack(self, record_id: int, phase: str, order_id: str, *, client_order_id: Optional[str] = None,
                         expected_attempt: Optional[int] = None) -> None:
        """ACK 只证明 id；不伪造 status/零成交，也不允许替换已知 id。"""
        if phase not in {"open", "close"} or not isinstance(order_id, str) or not order_id.strip():
            raise CChanException("ACK 阶段/交易所订单号无效", ErrCode.LIST_ORDER_FAIL)
        prefix = "open" if phase == "open" else "cover"
        record = self.get_record(record_id)
        self._fill_identity(record, prefix, client_order_id, order_id, expected_attempt)
        observed_client = record.get(f"{prefix}_client_order_id") or ""
        observed_attempt = record.get(f"{prefix}_attempt") or 0
        states = "('submitted', 'partially_filled')" if phase == "open" else "('closing')"
        changed = self._order_write(record_id, prefix, "ack",
            f"UPDATE {self.table} SET {prefix}_order_id=?, order_last_update=? WHERE id=? "
            f"AND status IN {states} AND {prefix}_order_status='submitting' AND {prefix}_order_id IS NULL "
            f"AND COALESCE({prefix}_client_order_id, '')=? AND COALESCE({prefix}_attempt, 0)=?",
            (order_id, now_str(), record_id, observed_client, observed_attempt),
        )
        if changed != 1:
            fresh = self.get_record(record_id)
            if (fresh.get(f"{prefix}_order_id") != order_id
                    or (fresh.get(f"{prefix}_client_order_id") or "") != observed_client
                    or (fresh.get(f"{prefix}_attempt") or 0) != observed_attempt):
                raise CChanException("ACK 不能换单/串到其他意图或越过提交边界", ErrCode.LIST_ORDER_FAIL)

    def get_recoverable_records(self) -> List[dict]:
        return self.db.query(
            f"SELECT * FROM {self.table} WHERE "
            "status IN ('submitted', 'partially_filled', 'closing') "
            "ORDER BY id"
        )

    def get_order_intent(self, client_order_id: str) -> Optional[dict]:
        if not client_order_id:
            return None
        rows = self.db.query(
            f"SELECT * FROM {self.table} WHERE "
            "open_client_order_id=? OR cover_client_order_id=?",
            (client_order_id, client_order_id),
        )
        matches = []
        for record in rows:
            if record.get("open_client_order_id") == client_order_id:
                matches.append({"phase": "open", "record": record})
            if record.get("cover_client_order_id") == client_order_id:
                matches.append({"phase": "close", "record": record})
        return matches[0] if len(matches) == 1 else None

    def get_order_intent_by_order_id(self, code: str, order_id: str) -> Optional[dict]:
        rows = self.db.query(
            f"SELECT * FROM {self.table} WHERE stock_code=? AND (open_order_id=? OR cover_order_id=?)",
            (code, order_id, order_id),
        )
        matches = [{"phase": phase, "record": record} for record in rows for phase, field in
                   (("open", "open_order_id"), ("close", "cover_order_id")) if record.get(field) == order_id]
        return matches[0] if len(matches) == 1 else None

    def claim_order_submission(self, record_id: int, phase: str) -> bool:
        if phase == "open":
            updated_at = now_str()
            changed = self._order_write(record_id, "open", "claim",
                f"UPDATE {self.table} SET open_order_status='submitting', "
                "order_last_update=? WHERE id=? "
                "AND status IN ('submitted', 'partially_filled') "
                "AND open_order_status='created' AND open_order_id IS NULL",
                (updated_at, record_id), native_updates={"open_order_status": "submitting", "order_last_update": updated_at},
            )
        elif phase == "close":
            changed = self._order_write(record_id, "cover", "claim",
                f"UPDATE {self.table} SET cover_order_status='submitting', "
                "order_last_update=? WHERE id=? AND status='closing' "
                "AND cover_order_status='created' AND cover_order_id IS NULL",
                (now_str(), record_id),
            )
        else:
            raise CChanException("订单意图阶段无效", ErrCode.PARA_ERROR)
        return changed == 1

    def record_open_submission(
        self, record_id: int, order_id: str, order_status: str, *, client_order_id: Optional[str] = None,
        expected_attempt: Optional[int] = None,
    ) -> None:
        self._record_submission(record_id, "open", order_id, order_status, client_order_id, expected_attempt)

    def _record_submission(self, record_id, prefix, order_id, order_status, client_order_id, expected_attempt):
        """Compatibility API. Normal execution commits status and fills together."""
        raw_status = _order_status(order_status)
        if not order_id:
            raise CChanException("交易所订单号不能为空", ErrCode.PARA_ERROR)
        record = self.get_record(record_id)
        self._fill_identity(record, prefix, client_order_id, order_id, expected_attempt)
        states = "('submitted', 'partially_filled')" if prefix == "open" else "('closing')"
        changed = self._order_write(record_id, prefix, "submission",
            f"UPDATE {self.table} SET {prefix}_order_id=?, {prefix}_order_status=?, order_last_update=? WHERE id=? "
            f"AND status IN {states} AND ({prefix}_order_id IS NULL OR {prefix}_order_id=?) "
            f"AND COALESCE({prefix}_client_order_id, '')=? AND COALESCE({prefix}_attempt, 0)=?",
            (order_id, raw_status, now_str(), record_id, order_id, record.get(f"{prefix}_client_order_id") or "",
             record.get(f"{prefix}_attempt") or 0),
        )
        if changed != 1:
            raise CChanException("提交回报意图/状态已改变，需重新核验", ErrCode.LIST_ORDER_FAIL)

    def apply_open_fill(
        self,
        record_id: int,
        cumulative_filled: float,
        avg_price: Optional[float],
        order_status: str,
        *, client_order_id: Optional[str] = None, order_id: Optional[str] = None,
        expected_attempt: Optional[int] = None,
    ) -> float:
        filled = _cumulative_qty(cumulative_filled)
        raw_status = _order_status(order_status)
        rec = self.get_record(record_id)
        server_id = self._fill_identity(rec, "open", client_order_id, order_id, expected_attempt)
        current_status = rec["status"]
        if current_status not in {"submitted", "partially_filled", "open", "closing", "closed", "canceled", "rejected"}:
            _illegal_transition(record_id, current_status, "应用开仓成交")
        previous = float(rec["open_filled_qty"] or 0)
        requested = float(rec["open_requested_qty"] or 0)
        if current_status not in {"submitted", "partially_filled"} and filled != previous:
            _illegal_transition(record_id, current_status, "增加开仓成交")
        if filled < previous:
            raise CChanException("开仓累计成交量不能回退", ErrCode.PARA_ERROR)
        if requested <= 0 or filled > requested:
            raise CChanException("开仓累计成交量超过请求量", ErrCode.PARA_ERROR)
        if raw_status == "closed" and filled != requested and _has_order_contract(rec):
            raise CChanException("合约 closed 与未完成请求量矛盾", ErrCode.PARA_ERROR)
        if filled and (avg_price is None or isinstance(avg_price, bool) or not math.isfinite(float(avg_price)) or float(avg_price) <= 0):
            raise CChanException("开仓成交均价无效", ErrCode.PARA_ERROR)
        if filled == previous and filled and float(avg_price) != rec.get("open_price"):
            raise CChanException("同一累计开仓量不能改写成交均价", ErrCode.PARA_ERROR)
        if current_status not in {"submitted", "partially_filled"}:
            return self._finish_duplicate_fill(rec, "open", raw_status)
        with localcontext(Context(prec=50)) as context:
            delta = _exact_qty_float(Decimal(str(filled))-Decimal(str(previous)))
            if context.flags[Inexact]:
                raise CChanException("开仓数量超出精确计算范围", ErrCode.PARA_ERROR)

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
        self._write_fill(rec, "open",
            "status=?, is_open=?, watching=?, "
            "open_filled_qty=?, current_qty=?, quota=?, open_price=?, "
            "open_date=?, peak_price_after_open=?, open_order_status=?, open_order_id=?, "
            "order_last_update=?",
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
                server_id,
                now_str(),
            ),
        )
        return delta

    def acquire_close_intent(
        self,
        record_id: int,
        requested_qty: float,
        client_order_id: str,
        reason: str,
        order_contract: Optional[dict] = None,
        *, previous_attempt: Optional[int] = None,
    ) -> bool:
        requested = _positive_qty(requested_qty, "平仓请求量")
        if not client_order_id:
            raise CChanException("平仓客户端订单号不能为空", ErrCode.PARA_ERROR)
        rec = self.get_record(record_id)
        observed_attempt = rec.get("cover_attempt") or 0
        if order_contract is not None and previous_attempt is None:
            raise CChanException("合约平仓意图缺少准备时的尝试次数", ErrCode.LIST_ORDER_FAIL)
        if previous_attempt is not None:
            if type(previous_attempt) is not int or previous_attempt < 0:
                raise CChanException("平仓意图尝试次数无效", ErrCode.PARA_ERROR)
            if previous_attempt != observed_attempt:
                return False
        current = float(rec["current_qty"] or 0)
        if requested > current:
            raise CChanException("平仓请求量超过当前仓位", ErrCode.PARA_ERROR)
        if order_contract is not None and self.db_type != "sqlite":
            raise CChanException("MySQL 订单单位契约迁移尚未验收", ErrCode.TRADE_UNLOCK_FAIL)
        contract_clause = ", cover_order_contract=?, cover_intent_ms=?" if self.db_type == "sqlite" else ""
        contract_args = (canonical_bytes(order_contract).decode() if order_contract is not None else None, utc_now_ms()) if contract_clause else ()
        changed = self._order_write(record_id, "cover", "intent",
            f"UPDATE {self.table} SET status='closing', "
            "cover_client_order_id=?, cover_requested_qty=?, "
            "cover_order_filled_qty=0, cover_order_avg_price=NULL, "
            "cover_order_status='created', cover_order_id=NULL, "
            "cover_attempt=COALESCE(cover_attempt, 0)+1, "
            "cover_quota=?, cover_date=?, cover_reason=?, "
            "order_last_update=?" + contract_clause + " WHERE id=? AND status='open' "
            "AND is_open=1 AND current_qty>=? AND COALESCE(cover_attempt, 0)=?",
            (
                client_order_id,
                requested,
                requested,
                now_str(),
                reason,
                now_str(),
                *contract_args,
                record_id,
                requested,
                observed_attempt,
            ),
        )
        return changed == 1

    def record_close_submission(
        self, record_id: int, order_id: str, order_status: str, *, client_order_id: Optional[str] = None,
        expected_attempt: Optional[int] = None,
    ) -> None:
        self._record_submission(record_id, "cover", order_id, order_status, client_order_id, expected_attempt)

    def apply_close_fill(
        self,
        record_id: int,
        cumulative_filled: float,
        avg_price: Optional[float],
        order_status: str,
        *, client_order_id: Optional[str] = None, order_id: Optional[str] = None,
        expected_attempt: Optional[int] = None,
    ) -> float:
        filled = _cumulative_qty(cumulative_filled)
        raw_status = _order_status(order_status)
        rec = self.get_record(record_id)
        server_id = self._fill_identity(rec, "cover", client_order_id, order_id, expected_attempt)
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
        if raw_status == "closed" and filled != requested and _has_order_contract(rec):
            raise CChanException("合约 closed 与未完成请求量矛盾", ErrCode.PARA_ERROR)
        if filled and (avg_price is None or isinstance(avg_price, bool) or not math.isfinite(float(avg_price)) or float(avg_price) <= 0):
            raise CChanException("平仓成交均价无效", ErrCode.PARA_ERROR)
        if filled == previous_order and filled and float(avg_price) != rec.get("cover_order_avg_price"):
            raise CChanException("同一累计平仓量不能改写成交均价", ErrCode.PARA_ERROR)
        if current_status in {"open", "closed"}:
            return self._finish_duplicate_fill(rec, "cover", raw_status)
        previous_current = float(rec["current_qty"] or 0)
        previous_total = float(rec["cover_filled_qty"] or 0)
        with localcontext(Context(prec=50)) as context:
            delta_decimal = Decimal(str(filled))-Decimal(str(previous_order))
            if delta_decimal > Decimal(str(previous_current)):
                raise CChanException("平仓成交量超过当前仓位", ErrCode.PARA_ERROR)
            delta = _exact_qty_float(delta_decimal)
            current = _exact_qty_float(Decimal(str(previous_current))-delta_decimal)
            total = _exact_qty_float(Decimal(str(previous_total))+delta_decimal)
            if context.flags[Inexact]:
                raise CChanException("平仓数量超出精确计算范围", ErrCode.PARA_ERROR)
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

        if current == 0:
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
        self._write_fill(rec, "cover",
            "status=?, is_open=?, watching=?, "
            "current_qty=?, cover_order_filled_qty=?, "
            "cover_order_avg_price=?, cover_filled_qty=?, cover_avg_price=?, "
            "cover_order_status=?, cover_order_id=?, order_last_update=?",
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
                server_id,
                now_str(),
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
        self._require_legacy_manual_record(rec)
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
        self._require_legacy_manual_record(rec)
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
        self._require_legacy_manual_record(rec)
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

    @staticmethod
    def _require_legacy_manual_record(record):
        if _has_order_contract(record):
            raise CChanException("新合约必须用绑定成交回报，不可手工猜测开平仓", ErrCode.TRADE_UNLOCK_FAIL)

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
