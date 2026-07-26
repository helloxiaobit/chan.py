"""交易库 mysql 后端(可选;需 pip install pymysql,连接参数来自 config.yaml db.mysql)"""
from typing import List, Optional, Tuple

from Common.ChanException import CChanException, ErrCode

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}(
    id INT(11) NOT NULL AUTO_INCREMENT,
    add_date DATETIME(6),
    stock_code VARCHAR(20) NOT NULL,
    stock_name VARCHAR(64) NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'signal',
    lv CHAR(8) NOT NULL,
    bstype CHAR(10) NOT NULL,
    is_buy BOOLEAN DEFAULT TRUE,
    open_thred FLOAT,
    sl_thred FLOAT,
    target_klu_time VARCHAR(20),

    watching BOOLEAN DEFAULT TRUE,
    unwatch_reason VARCHAR(256),
    signal_last_modify DATETIME(6),
    model_version VARCHAR(256),
    model_score_before FLOAT,
    snapshot_before VARCHAR(256),
    model_score_after FLOAT,
    snapshot_after VARCHAR(256),

    is_open BOOLEAN DEFAULT FALSE,
    open_price FLOAT,
    quota FLOAT DEFAULT 0,
    open_date DATETIME(6),
    open_order_id VARCHAR(32),
    open_image_url VARCHAR(64),
    cover_image_url VARCHAR(64),
    peak_price_after_open FLOAT,

    cover_avg_price FLOAT,
    cover_quota FLOAT DEFAULT 0,
    cover_date DATETIME(6),
    cover_reason VARCHAR(256),
    cover_order_id VARCHAR(256),

    open_err BOOLEAN DEFAULT FALSE,
    close_err BOOLEAN DEFAULT FALSE,
    open_err_reason VARCHAR(256),
    close_err_reason VARCHAR(256),

    relate_cover_id INT,
    is_cover_record BOOL DEFAULT FALSE,
    PRIMARY KEY (id)
)
"""


class CMysqlDB:
    def __init__(self, conf: dict, table_name: str = "chan_trade"):
        try:
            import pymysql  # 懒加载,可选依赖
            import pymysql.cursors
        except ImportError as e:
            raise CChanException("mysql 后端需要 pymysql,请先 pip install pymysql", ErrCode.UNKNOWN_DB_TYPE) from e
        self.table_name = table_name
        self.conn = pymysql.connect(
            host=conf.get("host", "127.0.0.1"),
            port=int(conf.get("port", 3306)),
            user=conf.get("user", "root"),
            password=str(conf.get("password", "")),
            database=conf.get("database", "chan"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        with self.conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL.format(table_name=table_name))

    def execute(self, sql: str, args: Tuple = ()) -> int:
        sql = sql.replace("?", "%s")  # 与 sqlite 占位符统一
        with self.conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.lastrowid if sql.strip().upper().startswith("INSERT") else cur.rowcount

    def query(self, sql: str, args: Tuple = ()) -> List[dict]:
        sql = sql.replace("?", "%s")
        with self.conn.cursor() as cur:
            cur.execute(sql, args)
            return list(cur.fetchall())

    def query_one(self, sql: str, args: Tuple = ()) -> Optional[dict]:
        rows = self.query(sql, args)
        return rows[0] if rows else None

    def close(self):
        self.conn.close()
