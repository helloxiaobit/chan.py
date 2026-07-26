"""交易库 sqlite 后端(默认;文件路径来自 config.yaml db.sqlite_path)"""
import sqlite3
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
    model_score_before FLOAT,
    snapshot_before VARCHAR(256),
    model_score_after FLOAT,
    snapshot_after VARCHAR(256),

    is_open BOOLEAN DEFAULT 0,
    open_price FLOAT,
    quota FLOAT DEFAULT 0,
    open_date TEXT,
    open_order_id VARCHAR(32),
    open_image_url VARCHAR(64),
    cover_image_url VARCHAR(64),
    peak_price_after_open FLOAT,

    cover_avg_price FLOAT,
    cover_quota FLOAT DEFAULT 0,
    cover_date TEXT,
    cover_reason VARCHAR(256),
    cover_order_id VARCHAR(256),

    open_err BOOLEAN DEFAULT 0,
    close_err BOOLEAN DEFAULT 0,
    open_err_reason VARCHAR(256),
    close_err_reason VARCHAR(256),

    relate_cover_id INTEGER,
    is_cover_record BOOLEAN DEFAULT 0
)
"""


class CSqliteDB:
    def __init__(self, db_path: str, table_name: str = "chan_trade"):
        self.table_name = table_name
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(CREATE_TABLE_SQL.format(table_name=table_name))
        self.conn.commit()

    def execute(self, sql: str, args: Tuple = ()) -> int:
        # 返回 lastrowid(INSERT)或影响行数
        cur = self.conn.execute(sql, args)
        self.conn.commit()
        return cur.lastrowid if sql.strip().upper().startswith("INSERT") else cur.rowcount

    def query(self, sql: str, args: Tuple = ()) -> List[dict]:
        return [dict(row) for row in self.conn.execute(sql, args)]

    def query_one(self, sql: str, args: Tuple = ()) -> Optional[dict]:
        rows = self.query(sql, args)
        return rows[0] if rows else None

    def close(self):
        self.conn.close()
