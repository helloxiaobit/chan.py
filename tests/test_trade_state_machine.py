import sqlite3

import pytest

from Common.ChanException import CChanException, ErrCode
from Trade.CCXTTradeEngine import CCCXTTradeEngine
from Trade.db_util import CChanDB
from Trade.MysqlDB import CREATE_TABLE_SQL as MYSQL_CREATE_TABLE_SQL
from Trade.OpenQuotaGen import CBenchPriceQuotaGen
from Trade.Script.MakeOpenTrade import make_open_trade
from Trade.Script.OpenConfig import COpenConfig
from Trade.Script.RealTimeTracker import real_time_track

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
        "open_order_contract",
        "cover_order_contract",
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
    assert record["open_order_contract"] is None and record["cover_order_contract"] is None
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
        "open_order_contract",
        "cover_order_contract",
        "order_last_update",
        "position_side",
        "strategy_version",
        "risk_multiplier",
    ):
        assert column in MYSQL_CREATE_TABLE_SQL


def dry_engine(db, sim_state=None):
    return CCCXTTradeEngine(
        db,
        quota_gen=CBenchPriceQuotaGen(1000.0),
        ccxt_conf={"mode": "dry_run", "default_type": "spot"},
        trade_conf={},
        environ={},
        sim_state=sim_state,
        push_msg=False,
    )


def test_add_trade_persists_intent_first_and_zero_fill_is_not_open(
    trade_db, monkeypatch
):
    record_id = trade_db.add_signal(make_signal(open_thred=100.0))
    record = trade_db.get_record(record_id)
    engine = dry_engine(trade_db)
    client_id = engine.make_client_order_id(record, "open")
    engine.set_sim_fill_plan(client_id, [0.0])
    original_place_order = engine.place_order

    def inspect_then_place(*args, **kwargs):
        persisted = trade_db.get_record(record_id)
        assert persisted["status"] == "submitted"
        assert persisted["open_client_order_id"] == client_id
        assert persisted["open_order_id"] is None
        return original_place_order(*args, **kwargs)

    monkeypatch.setattr(engine, "place_order", inspect_then_place)
    result = engine.add_trade(record, 100.0)

    persisted = trade_db.get_record(record_id)
    assert result.filled == 0.0
    assert persisted["status"] == "submitted"
    assert not persisted["is_open"]
    assert persisted["quota"] == 0.0
    assert persisted["open_order_id"] == result.order_id


def test_make_open_trade_does_not_report_zero_fill_as_open(trade_db):
    record_id = trade_db.add_signal(make_signal(open_thred=100.0))
    record = trade_db.get_record(record_id)
    engine = dry_engine(trade_db)
    engine.set_sim_fill_plan(
        engine.make_client_order_id(record, "open"), [0.0]
    )

    opened = make_open_trade(
        trade_db,
        engine,
        COpenConfig(),
        price_map={"TEST/USDT": 100.5},
    )

    assert opened == []
    assert trade_db.get_record(record_id)["status"] == "submitted"


def test_restart_recovers_open_by_client_id_without_resubmission(trade_db):
    record_id = trade_db.add_signal(make_signal())
    record = trade_db.get_record(record_id)
    engine1 = dry_engine(trade_db)
    client_id = engine1.make_client_order_id(record, "open")
    assert trade_db.acquire_open_intent(record_id, 10.0, client_id)
    engine1.set_sim_fill_plan(client_id, [0.0, 4.0, 10.0])
    placed = engine1.place_order(
        "TEST/USDT", True, 10.0, 100.0, client_order_id=client_id
    )
    assert placed.filled == 0.0
    assert trade_db.get_record(record_id)["open_order_id"] is None

    engine2 = dry_engine(trade_db, sim_state=engine1.sim_state)
    engine2.restore()
    partial = trade_db.get_record(record_id)
    assert partial["status"] == "partially_filled"
    assert partial["open_order_id"] == placed.order_id
    assert partial["current_qty"] == 4.0
    assert len(engine2.sim_state.orders) == 1

    engine2.restore()
    opened = trade_db.get_record(record_id)
    assert opened["status"] == "open"
    assert opened["current_qty"] == 10.0
    assert engine2.get_position("TEST/USDT") == 10.0
    assert len(engine2.sim_state.orders) == 1


def test_partial_close_recovery_cancel_and_retry_use_only_remaining_qty(
    trade_db
):
    record_id = trade_db.add_signal(make_signal())
    engine1 = dry_engine(trade_db)
    engine1.add_trade(trade_db.get_record(record_id), 100.0)
    opened = trade_db.get_record(record_id)
    close_client_1 = engine1.make_client_order_id(opened, "close")
    engine1.set_sim_fill_plan(close_client_1, [0.0, 4.0])
    engine1.cover_trade(opened, 95.0, "stop_loss")
    assert trade_db.get_record(record_id)["status"] == "closing"

    engine2 = dry_engine(trade_db, sim_state=engine1.sim_state)
    engine2.restore()
    partial = trade_db.get_record(record_id)
    assert partial["current_qty"] == 6.0
    assert partial["cover_filled_qty"] == 4.0
    assert partial["cover_attempt"] == 1

    engine2.restore()
    repeated = trade_db.get_record(record_id)
    assert repeated["current_qty"] == 6.0
    assert repeated["cover_filled_qty"] == 4.0

    engine2.poll_orders(times=1, interval=0, adjust_price=True)
    closed = trade_db.get_record(record_id)
    assert closed["status"] == "closed"
    assert closed["current_qty"] == 0.0
    assert closed["cover_filled_qty"] == 10.0
    assert closed["cover_attempt"] == 2
    assert closed["cover_client_order_id"] != close_client_1
    assert engine2.get_position("TEST/USDT") == 0.0
    assert len(engine2.sim_state.orders) == 3


def test_close_is_not_retried_until_cancel_is_confirmed(
    trade_db, monkeypatch
):
    record_id = trade_db.add_signal(make_signal())
    engine = dry_engine(trade_db)
    engine.add_trade(trade_db.get_record(record_id), 100.0)
    opened = trade_db.get_record(record_id)
    client_id = engine.make_client_order_id(opened, "close")
    engine.set_sim_fill_plan(client_id, [0.0])
    engine.cover_trade(opened, 95.0, "stop_loss")

    monkeypatch.setattr(engine, "cancel_order", lambda code, order_id: True)
    engine.poll_orders(times=1, interval=0, adjust_price=True)

    pending = trade_db.get_record(record_id)
    assert pending["status"] == "closing"
    assert pending["cover_attempt"] == 1
    assert pending["current_qty"] == 10.0
    assert len(engine.sim_state.orders) == 2


def test_offline_restart_acceptance_covers_full_order_lifecycle(
    tmp_path, monkeypatch
):
    from DataAPI import ccxt as data_ccxt

    def forbid_exchange(*args, **kwargs):
        raise AssertionError("离线验收不得创建交易所或调用真实 create_order")

    monkeypatch.setattr(data_ccxt, "create_exchange", forbid_exchange)
    path = tmp_path / "restart-acceptance.db"

    db1 = CChanDB(
        db_conf={"type": "sqlite", "sqlite_path": str(path)}
    )
    record_id = db1.add_signal(make_signal())
    engine1 = dry_engine(db1)
    open_client = engine1.make_client_order_id(
        db1.get_record(record_id), "open"
    )
    engine1.set_sim_fill_plan(open_client, [0.0, 4.0, 10.0])
    placed = engine1.add_trade(db1.get_record(record_id), 100.0)
    sim_state = engine1.sim_state
    assert placed.filled == 0.0
    assert db1.get_record(record_id)["status"] == "submitted"
    assert engine1.get_balance()["USDT"] == 100000.0
    db1.close()

    db2 = CChanDB(
        db_conf={"type": "sqlite", "sqlite_path": str(path)}
    )
    engine2 = dry_engine(db2, sim_state=sim_state)
    engine2.restore()
    partial_open = db2.get_record(record_id)
    assert partial_open["status"] == "partially_filled"
    assert partial_open["current_qty"] == 4.0
    assert engine2.get_position("TEST/USDT") == 4.0
    assert engine2.get_balance()["USDT"] == 99600.0
    db2.close()

    db3 = CChanDB(
        db_conf={"type": "sqlite", "sqlite_path": str(path)}
    )
    engine3 = dry_engine(db3, sim_state=sim_state)
    engine3.restore()
    fully_open = db3.get_record(record_id)
    assert fully_open["status"] == "open"
    assert fully_open["current_qty"] == 10.0
    assert fully_open["open_client_order_id"] == open_client
    assert engine3.get_position("TEST/USDT") == 10.0
    assert engine3.get_balance()["USDT"] == 99000.0

    close_client = engine3.make_client_order_id(fully_open, "close")
    engine3.set_sim_fill_plan(close_client, [0.0, 3.0, 10.0])
    close_order = engine3.cover_trade(fully_open, 110.0, "acceptance")
    assert close_order.filled == 0.0
    assert db3.get_record(record_id)["status"] == "closing"
    db3.close()

    db4 = CChanDB(
        db_conf={"type": "sqlite", "sqlite_path": str(path)}
    )
    engine4 = dry_engine(db4, sim_state=sim_state)
    engine4.restore()
    partial_close = db4.get_record(record_id)
    assert partial_close["status"] == "closing"
    assert partial_close["current_qty"] == 7.0
    assert partial_close["cover_filled_qty"] == 3.0
    assert engine4.get_position("TEST/USDT") == 7.0
    assert engine4.get_balance()["USDT"] == 99330.0
    db4.close()

    db5 = CChanDB(
        db_conf={"type": "sqlite", "sqlite_path": str(path)}
    )
    engine5 = dry_engine(db5, sim_state=sim_state)
    engine5.restore()
    closed = db5.get_record(record_id)
    assert closed["status"] == "closed"
    assert not closed["is_open"]
    assert closed["current_qty"] == 0.0
    assert closed["open_filled_qty"] == 10.0
    assert closed["cover_filled_qty"] == 10.0
    assert closed["open_client_order_id"] == open_client
    assert closed["cover_client_order_id"] == close_client
    assert closed["open_attempt"] == 1
    assert closed["cover_attempt"] == 1
    assert engine5.get_position("TEST/USDT") == 0.0
    assert engine5.get_balance()["USDT"] == 100100.0
    assert len(sim_state.orders) == 2
    db5.close()


def test_partial_open_stop_cancels_entry_then_closes_actual_exposure(
    trade_db
):
    record_id = trade_db.add_signal(
        make_signal(open_thred=100.0, sl_thred=95.0)
    )
    engine = dry_engine(trade_db)
    record = trade_db.get_record(record_id)
    open_client = engine.make_client_order_id(record, "open")
    engine.set_sim_fill_plan(open_client, [0.0, 4.0])
    engine.add_trade(record, 100.0)
    engine.restore()
    partial = trade_db.get_record(record_id)
    assert partial["status"] == "partially_filled"
    assert partial["current_qty"] == 4.0

    closed_ids = real_time_track(
        trade_db,
        engine,
        COpenConfig(),
        price_map={"TEST/USDT": 90.0},
    )

    closed = trade_db.get_record(record_id)
    assert closed_ids == [record_id]
    assert closed["status"] == "closed"
    assert closed["open_order_status"] == "canceled"
    assert closed["open_filled_qty"] == 4.0
    assert closed["cover_requested_qty"] == 4.0
    assert closed["cover_filled_qty"] == 4.0
    assert closed["current_qty"] == 0.0
    assert engine.get_position("TEST/USDT") == 0.0
    assert len(engine.sim_state.orders) == 2
