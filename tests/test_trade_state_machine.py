import sqlite3

import pytest

from Common.ChanException import CChanException, ErrCode
from Trade.db_util import CChanDB
from Trade.MysqlDB import CREATE_TABLE_SQL as MYSQL_CREATE_TABLE_SQL

from .test_m6_trade import make_signal


@pytest.fixture()
def trade_db(tmp_path):
    db = CChanDB(
        db_conf={
            "type": "sqlite",
            "sqlite_path": str(tmp_path / "state-machine.db"),
        }
    )
    yield db
    db.close()


def acquire_open(db, requested=10.0):
    record_id = db.add_signal(make_signal())
    acquired = db.acquire_open_intent(
        record_id,
        requested_qty=requested,
        client_order_id=f"open-{record_id}-1",
        position_side="BOTH",
        strategy_version="certified-v1",
        risk_multiplier=0.5,
    )
    assert acquired is True
    return record_id


def fill_open(db, record_id, requested=10.0):
    db.record_open_submission(record_id, "exchange-open-1", "open")
    db.apply_open_fill(record_id, requested, 100.0, "closed")


def test_zero_fill_stays_submitted_and_intent_is_acquired_once(trade_db):
    record_id = acquire_open(trade_db)
    assert trade_db.acquire_open_intent(
        record_id, 10.0, "duplicate-client"
    ) is False

    trade_db.record_open_submission(record_id, "exchange-open-1", "open")
    delta = trade_db.apply_open_fill(record_id, 0.0, None, "open")

    record = trade_db.get_record(record_id)
    assert delta == 0.0
    assert record["status"] == "submitted"
    assert not record["is_open"]
    assert record["quota"] == 0.0
    assert record["current_qty"] == 0.0
    assert record["open_requested_qty"] == 10.0
    assert record["open_filled_qty"] == 0.0
    assert record["open_client_order_id"] == f"open-{record_id}-1"
    assert record["open_order_id"] == "exchange-open-1"
    assert record["open_order_status"] == "open"
    assert record["open_attempt"] == 1
    assert record["strategy_version"] == "certified-v1"
    assert record["risk_multiplier"] == 0.5
    assert trade_db.get_watching_signals() == []


def test_open_fills_are_actual_monotonic_and_idempotent(trade_db):
    record_id = acquire_open(trade_db)
    trade_db.record_open_submission(record_id, "exchange-open-1", "open")

    assert trade_db.apply_open_fill(record_id, 4.0, 101.0, "open") == 4.0
    partial = trade_db.get_record(record_id)
    assert partial["status"] == "partially_filled"
    assert partial["is_open"]
    assert partial["quota"] == 4.0
    assert partial["current_qty"] == 4.0
    assert partial["open_filled_qty"] == 4.0
    assert partial["open_price"] == 101.0

    assert trade_db.apply_open_fill(record_id, 4.0, 101.0, "open") == 0.0
    with pytest.raises(CChanException, match="回退") as caught:
        trade_db.apply_open_fill(record_id, 3.0, 101.0, "open")
    assert caught.value.errcode == ErrCode.PARA_ERROR

    assert trade_db.apply_open_fill(record_id, 10.0, 100.5, "closed") == 6.0
    opened = trade_db.get_record(record_id)
    assert opened["status"] == "open"
    assert opened["quota"] == 10.0
    assert opened["current_qty"] == 10.0
    assert opened["open_filled_qty"] == 10.0
    assert opened["open_price"] == 100.5
    assert trade_db.apply_open_fill(
        record_id, 10.0, 100.5, "closed"
    ) == 0.0


def test_illegal_state_transition_and_unknown_order_status_fail(trade_db):
    record_id = trade_db.add_signal(make_signal())
    with pytest.raises(CChanException, match="状态") as caught:
        trade_db.apply_open_fill(record_id, 1.0, 100.0, "open")
    assert caught.value.errcode == ErrCode.PARA_ERROR

    assert trade_db.acquire_open_intent(
        record_id, 10.0, "open-illegal-test"
    )
    with pytest.raises(CChanException, match="订单状态"):
        trade_db.record_open_submission(
            record_id, "exchange-open-1", "pending"
        )


def test_close_fills_reduce_current_quantity_once(trade_db):
    record_id = acquire_open(trade_db)
    fill_open(trade_db, record_id)
    assert trade_db.acquire_close_intent(
        record_id,
        requested_qty=10.0,
        client_order_id="close-1-1",
        reason="stop_loss",
    ) is True
    assert trade_db.acquire_close_intent(
        record_id, 10.0, "duplicate-close", "stop_loss"
    ) is False
    trade_db.record_close_submission(record_id, "exchange-close-1", "open")

    assert trade_db.apply_close_fill(record_id, 4.0, 95.0, "open") == 4.0
    partial = trade_db.get_record(record_id)
    assert partial["status"] == "closing"
    assert partial["current_qty"] == 6.0
    assert partial["cover_order_filled_qty"] == 4.0
    assert partial["cover_filled_qty"] == 4.0
    assert partial["cover_avg_price"] == 95.0

    assert trade_db.apply_close_fill(record_id, 4.0, 95.0, "open") == 0.0
    assert trade_db.get_record(record_id)["current_qty"] == 6.0
    with pytest.raises(CChanException, match="回退"):
        trade_db.apply_close_fill(record_id, 3.0, 95.0, "open")

    assert trade_db.apply_close_fill(record_id, 10.0, 96.0, "closed") == 6.0
    closed = trade_db.get_record(record_id)
    assert closed["status"] == "closed"
    assert not closed["is_open"]
    assert closed["current_qty"] == 0.0
    assert closed["cover_filled_qty"] == 10.0
    assert closed["cover_avg_price"] == 96.0
    assert trade_db.apply_close_fill(
        record_id, 10.0, 96.0, "closed"
    ) == 0.0


def test_old_sqlite_schema_migrates_without_losing_legacy_cover(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE chan_trade(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'signal',
            lv TEXT NOT NULL,
            bstype TEXT NOT NULL,
            is_buy BOOLEAN DEFAULT 1,
            watching BOOLEAN DEFAULT 1,
            is_open BOOLEAN DEFAULT 0,
            quota FLOAT DEFAULT 0,
            cover_quota FLOAT DEFAULT 0,
            open_order_id TEXT,
            cover_order_id TEXT,
            is_cover_record BOOLEAN DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        INSERT INTO chan_trade(
            stock_code, status, lv, bstype, watching, is_open, quota,
            cover_quota, open_order_id, cover_order_id
        ) VALUES('BTC/USDT', 'cover', 'K_60M', '1', 0, 1, 2, 2, 'o1', 'c1')
        """
    )
    conn.commit()
    conn.close()

    db = CChanDB(
        db_conf={"type": "sqlite", "sqlite_path": str(path)}
    )
    columns = {
        row["name"]
        for row in db.db.query("PRAGMA table_info(chan_trade)")
    }
    expected = {
        "open_client_order_id",
        "cover_client_order_id",
        "open_requested_qty",
        "open_filled_qty",
        "cover_requested_qty",
        "cover_order_filled_qty",
        "cover_filled_qty",
        "current_qty",
        "open_order_status",
        "cover_order_status",
        "open_attempt",
        "cover_attempt",
        "order_last_update",
        "position_side",
        "strategy_version",
        "risk_multiplier",
    }
    assert expected <= columns
    record = db.get_record(1)
    assert record["status"] == "cover"
    assert record["open_filled_qty"] == 2.0
    assert record["cover_filled_qty"] == 2.0
    assert record["current_qty"] == 0.0
    assert db.get_open_records() == []
    db.close()


def test_mysql_fresh_schema_has_state_machine_parity():
    for column in (
        "open_client_order_id",
        "cover_client_order_id",
        "open_requested_qty",
        "open_filled_qty",
        "cover_requested_qty",
        "cover_order_filled_qty",
        "cover_filled_qty",
        "current_qty",
        "open_order_status",
        "cover_order_status",
        "open_attempt",
        "cover_attempt",
        "order_last_update",
        "position_side",
        "strategy_version",
        "risk_multiplier",
    ):
        assert column in MYSQL_CREATE_TABLE_SQL
