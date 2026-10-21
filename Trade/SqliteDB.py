"""交易库 sqlite 后端(默认;文件路径来自 config.yaml db.sqlite_path)"""
import sqlite3
from contextlib import contextmanager
from typing import List, Optional, Tuple

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    add_date TEXT,
    stock_code VARCHAR(20) NOT NULL,
    stock_name VARCHAR(64) NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'signal',
    lv CHAR(8) NOT NULL,
    bstype CHAR(10) NOT NULL,
    is_buy BOOLEAN DEFAULT 1,
    open_thred FLOAT,
    sl_thred FLOAT,
    target_klu_time VARCHAR(20),

    watching BOOLEAN DEFAULT 1,
    unwatch_reason VARCHAR(256),
    signal_last_modify TEXT,
    model_version VARCHAR(256),
    deployment_id VARCHAR(64),
    deployment_path TEXT,
    signal_decision TEXT,
    model_score_before FLOAT,
    snapshot_before VARCHAR(256),
    model_score_after FLOAT,
    snapshot_after VARCHAR(256),

    is_open BOOLEAN DEFAULT 0,
    open_price FLOAT,
    quota FLOAT DEFAULT 0,
    open_date TEXT,
    open_order_id VARCHAR(32),
    open_client_order_id VARCHAR(128),
    open_requested_qty FLOAT DEFAULT 0,
    open_filled_qty FLOAT DEFAULT 0,
    open_order_status VARCHAR(20),
    open_attempt INTEGER DEFAULT 0,
    open_order_contract TEXT,
    open_intent_ms INTEGER,
    open_image_url VARCHAR(64),
    cover_image_url VARCHAR(64),
    peak_price_after_open FLOAT,

    cover_avg_price FLOAT,
    cover_quota FLOAT DEFAULT 0,
    cover_date TEXT,
    cover_reason VARCHAR(256),
    cover_order_id VARCHAR(256),
    cover_client_order_id VARCHAR(128),
    cover_requested_qty FLOAT DEFAULT 0,
    cover_order_filled_qty FLOAT DEFAULT 0,
    cover_order_avg_price FLOAT,
    cover_filled_qty FLOAT DEFAULT 0,
    cover_order_status VARCHAR(20),
    cover_attempt INTEGER DEFAULT 0,
    cover_order_contract TEXT,
    cover_intent_ms INTEGER,

    current_qty FLOAT DEFAULT 0,
    order_last_update TEXT,
    position_side VARCHAR(10) DEFAULT 'BOTH',
    strategy_version VARCHAR(256),
    risk_multiplier FLOAT DEFAULT 1,

    open_err BOOLEAN DEFAULT 0,
    close_err BOOLEAN DEFAULT 0,
    open_err_reason VARCHAR(256),
    close_err_reason VARCHAR(256),

    relate_cover_id INTEGER,
    is_cover_record BOOLEAN DEFAULT 0
)
"""


MIGRATION_COLUMNS = {
    "model_version": "VARCHAR(256)",
    "deployment_id": "VARCHAR(64)",
    "deployment_path": "TEXT",
    "signal_decision": "TEXT",
    "open_client_order_id": "VARCHAR(128)",
    "open_requested_qty": "FLOAT DEFAULT 0",
    "open_filled_qty": "FLOAT DEFAULT 0",
    "open_order_status": "VARCHAR(20)",
    "open_attempt": "INTEGER DEFAULT 0",
    "open_order_contract": "TEXT",
    "open_intent_ms": "INTEGER",
    "cover_client_order_id": "VARCHAR(128)",
    "cover_requested_qty": "FLOAT DEFAULT 0",
    "cover_order_filled_qty": "FLOAT DEFAULT 0",
    "cover_order_avg_price": "FLOAT",
    "cover_filled_qty": "FLOAT DEFAULT 0",
    "cover_order_status": "VARCHAR(20)",
    "cover_attempt": "INTEGER DEFAULT 0",
    "cover_order_contract": "TEXT",
    "cover_intent_ms": "INTEGER",
    "current_qty": "FLOAT DEFAULT 0",
    "order_last_update": "TEXT",
    "position_side": "VARCHAR(10) DEFAULT 'BOTH'",
    "strategy_version": "VARCHAR(256)",
    "risk_multiplier": "FLOAT DEFAULT 1",
}


class CSqliteDB:
    def __init__(self, db_path: str, table_name: str = "chan_trade"):
        from .OrderAudit import SCHEMA, initialize_schema
        from .ExecutionStore import SCHEMA as execution_schema, initialize_schema as initialize_execution_schema
        from .AccountStore import SCHEMA as account_schema, initialize_schema as initialize_account_schema
        if table_name in SCHEMA or table_name in execution_schema or table_name in account_schema:
            raise ValueError("Reserved order audit table")
        self.table_name = table_name
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._transaction_depth = 0
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA recursive_triggers=ON")
        try:
            with self.transaction():
                self.conn.execute(CREATE_TABLE_SQL.format(table_name=table_name))
                self._migrate_state_machine()
                initialize_schema(self.conn)
                initialize_execution_schema(self.conn)
                initialize_account_schema(self.conn)
        except BaseException:
            self.conn.close()
            raise

    def _migrate_state_machine(self) -> None:
        existing = {
            row["name"]
            for row in self.conn.execute(
                f"PRAGMA table_info({self.table_name})"
            )
        }
        for name, definition in MIGRATION_COLUMNS.items():
            if name not in existing:
                self.conn.execute(
                    f"ALTER TABLE {self.table_name} ADD COLUMN {name} {definition}"
                )
        self.conn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS "
            f"idx_{self.table_name}_open_client_order_id "
            f"ON {self.table_name}(open_client_order_id) "
            "WHERE open_client_order_id IS NOT NULL "
            "AND open_client_order_id != ''"
        )
        self.conn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS "
            f"idx_{self.table_name}_cover_client_order_id "
            f"ON {self.table_name}(cover_client_order_id) "
            "WHERE cover_client_order_id IS NOT NULL "
            "AND cover_client_order_id != ''"
        )
        # 旧库仅补充可推导的数量；历史状态 cover 保持原样供审计读取。
        self.conn.execute(
            f"UPDATE {self.table_name} SET "
            "open_requested_qty=quota, open_filled_qty=quota, "
            "open_order_status=COALESCE(open_order_status, 'closed'), "
            "current_qty=CASE WHEN status='cover' THEN 0 ELSE quota END "
            "WHERE is_open=1 AND quota>0 AND open_filled_qty=0"
        )
        self.conn.execute(
            f"UPDATE {self.table_name} SET "
            "cover_requested_qty=cover_quota, "
            "cover_order_filled_qty=cover_quota, "
            "cover_filled_qty=cover_quota, "
            "cover_order_status=COALESCE(cover_order_status, 'closed') "
            "WHERE status='cover' AND cover_quota>0 AND cover_filled_qty=0"
        )

    def execute(self, sql: str, args: Tuple = ()) -> int:
        # 返回 lastrowid(INSERT)或影响行数
        try:
            cur = self.conn.execute(sql, args)
            if not self._transaction_depth:
                self.conn.commit()
        except BaseException:
            if not self._transaction_depth:
                self.conn.rollback()
            raise
        return cur.lastrowid if sql.strip().upper().startswith("INSERT") else cur.rowcount

    @contextmanager
    def transaction(self):
        """Publish related writes together; nested calls own only a savepoint."""
        depth = self._transaction_depth
        savepoint = f"chanpy_sp_{depth}"
        if depth:
            self.conn.execute(f"SAVEPOINT {savepoint}")
        else:
            if self.conn.in_transaction:
                raise RuntimeError("Cannot adopt an unowned SQLite transaction")
            self.conn.execute("BEGIN IMMEDIATE")
        self._transaction_depth += 1
        try:
            yield
            if depth:
                self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            else:
                self.conn.commit()
        except BaseException:
            if depth:
                self.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            else:
                self.conn.rollback()
            raise
        finally:
            self._transaction_depth = depth

    def query(self, sql: str, args: Tuple = ()) -> List[dict]:
        return [dict(row) for row in self.conn.execute(sql, args)]

    def query_one(self, sql: str, args: Tuple = ()) -> Optional[dict]:
        rows = self.query(sql, args)
        return rows[0] if rows else None

    def close(self):
        self.conn.close()
