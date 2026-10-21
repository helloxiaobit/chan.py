"""Deterministic interleavings on two real SQLite connections; no network."""
import pytest

from Common.ChanException import CChanException, ErrCode
from Trade.db_util import CChanDB
from .test_crypto_order_contract import CODE
from .test_crypto_order_recovery import lose_open, recovery_engine
from .test_m6_trade import make_signal


@pytest.fixture()
def databases(tmp_path):
    conf = {"type": "sqlite", "sqlite_path": str(tmp_path/"report-cas.db")}
    first, second = CChanDB(db_conf=conf), CChanDB(db_conf=conf)
    try:
        yield first, second
    finally:
        first.close()
        second.close()


def opening(db):
    record_id = db.add_signal(make_signal(code="TEST/USDT"))
    assert db.acquire_open_intent(record_id, 10, "open-1")
    db.record_open_submission(record_id, "server-open", "open")
    return record_id


def closing(db):
    record_id = opening(db)
    db.apply_open_fill(record_id, 10, 100, "closed")
    assert db.acquire_close_intent(record_id, 10, "close-1", "fixture")
    db.record_close_submission(record_id, "server-close", "open")
    return record_id


@pytest.mark.parametrize("phase", ["open", "close"])
def test_a_later_fill_between_read_and_write_cannot_be_overwritten(databases, monkeypatch, phase):
    db, peer = databases
    record_id = opening(db) if phase == "open" else closing(db)
    apply = db.apply_open_fill if phase == "open" else db.apply_close_fill
    apply_peer = peer.apply_open_fill if phase == "open" else peer.apply_close_fill
    execute = db.db.execute
    winner = []
    def interleave(sql, args=()):
        if "SET status=?" in sql and not winner:
            apply_peer(record_id, 6, 101, "open")
            winner.append(peer.get_record(record_id))
        return execute(sql, args)
    monkeypatch.setattr(db.db, "execute", interleave)
    with pytest.raises(CChanException) as caught:
        apply(record_id, 4, 101, "open")
    assert caught.value.errcode == ErrCode.LIST_ORDER_FAIL
    assert db.get_record(record_id) == winner[0]
    assert db.get_record(record_id)["current_qty"] == (6 if phase == "open" else 4)


@pytest.mark.parametrize("phase", ["open", "close"])
def test_a_terminal_report_between_read_and_write_cannot_be_reopened(databases, monkeypatch, phase):
    db, peer = databases
    record_id = opening(db) if phase == "open" else closing(db)
    apply = db.apply_open_fill if phase == "open" else db.apply_close_fill
    apply_peer = peer.apply_open_fill if phase == "open" else peer.apply_close_fill
    execute = db.db.execute
    winner = []
    def interleave(sql, args=()):
        if "SET status=?" in sql and not winner:
            apply_peer(record_id, 6, 101, "canceled")
            winner.append(peer.get_record(record_id))
        return execute(sql, args)
    monkeypatch.setattr(db.db, "execute", interleave)
    with pytest.raises(CChanException):
        apply(record_id, 6, 101, "open")
    assert db.get_record(record_id) == winner[0]
    assert db.get_record(record_id)["status"] == "open"


@pytest.mark.parametrize("phase", ["open", "close"])
def test_stale_nonterminal_report_after_terminal_is_a_position_preserving_noop(databases, phase):
    db, _ = databases
    record_id = opening(db) if phase == "open" else closing(db)
    apply = db.apply_open_fill if phase == "open" else db.apply_close_fill
    apply(record_id, 4, 101, "canceled")
    before = db.get_record(record_id)
    assert apply(record_id, 4, 101, "open") == 0
    assert db.get_record(record_id) == before


def test_opening_duplicate_does_not_erase_a_real_partial_exit(databases):
    db, _ = databases
    record_id = closing(db)
    db.apply_close_fill(record_id, 4, 101, "canceled")
    before = db.get_record(record_id)
    assert db.apply_open_fill(record_id, 10, 100, "closed") == 0
    assert db.get_record(record_id) == before
    assert db.get_record(record_id)["current_qty"] == 6


@pytest.mark.parametrize("phase", ["open", "close"])
def test_equal_cumulative_quantity_cannot_silently_reprice_a_known_fill(databases, phase):
    db, _ = databases
    record_id = opening(db) if phase == "open" else closing(db)
    apply = db.apply_open_fill if phase == "open" else db.apply_close_fill
    apply(record_id, 4, 101, "open")
    before = db.get_record(record_id)
    with pytest.raises(CChanException):
        apply(record_id, 4, 102, "open")
    assert db.get_record(record_id) == before


@pytest.mark.parametrize("phase", ["open", "close"])
@pytest.mark.parametrize("wrong", ["client", "server"])
def test_bound_fill_rejects_a_different_client_or_server_before_any_write(databases, phase, wrong):
    db, _ = databases
    record_id = opening(db) if phase == "open" else closing(db)
    apply = db.apply_open_fill if phase == "open" else db.apply_close_fill
    client = "open-1" if phase == "open" else "close-1"
    server = "server-open" if phase == "open" else "server-close"
    before = db.get_record(record_id)
    with pytest.raises(CChanException) as caught:
        apply(record_id, 4, 101, "open", client_order_id="wrong" if wrong == "client" else client,
              order_id="wrong" if wrong == "server" else server)
    assert caught.value.errcode == ErrCode.LIST_ORDER_FAIL
    assert db.get_record(record_id) == before


@pytest.mark.parametrize("phase", ["open", "close"])
def test_runtime_publishes_order_status_and_fill_in_one_atomic_update(databases, tmp_path, monkeypatch, phase):
    db, peer = databases
    trade = recovery_engine(db, tmp_path, "binance")
    trade.exchange.fill, trade.exchange.status = 3, "closed"
    record_id = db.add_signal(make_signal(code=CODE))
    if phase == "close":
        trade.add_trade(db.get_record(record_id), 100)
    prefix = "open" if phase == "open" else "cover"
    snapshots = []
    execute = db.db.execute
    def observe_commit(sql, args=()):
        result = execute(sql, args)
        if sql.startswith("UPDATE"):
            snapshots.append(peer.get_record(record_id))
        return result
    monkeypatch.setattr(db.db, "execute", observe_commit)
    if phase == "open":
        trade.add_trade(db.get_record(record_id), 100)
    else:
        trade.cover_trade(db.get_record(record_id), 101, "atomic close")
    filled = "open_filled_qty" if phase == "open" else "cover_order_filled_qty"
    assert snapshots and snapshots[-1][filled] == 0.03
    assert all(row[filled] == row[f"{prefix}_requested_qty"] for row in snapshots if row[f"{prefix}_order_status"] == "closed")


@pytest.mark.parametrize("phase", ["open", "close"])
def test_new_contract_fill_cannot_be_applied_without_current_attempt_identity(databases, tmp_path, phase):
    db, _ = databases
    trade = recovery_engine(db, tmp_path, "binance")
    record_id = db.add_signal(make_signal(code=CODE))
    if phase == "close":
        trade.exchange.fill, trade.exchange.status = 3, "closed"
        trade.add_trade(db.get_record(record_id), 100)
        trade.exchange.fill, trade.exchange.status = 1, "open"
        trade.cover_trade(db.get_record(record_id), 101, "fixture")
    else:
        trade.add_trade(db.get_record(record_id), 100)
    apply = db.apply_open_fill if phase == "open" else db.apply_close_fill
    before = db.get_record(record_id)
    with pytest.raises(CChanException) as caught:
        apply(record_id, 0.02, 100 if phase == "open" else 101, "open")
    assert caught.value.errcode == ErrCode.LIST_ORDER_FAIL
    assert db.get_record(record_id) == before


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("reuse_client", [False, True])
def test_ack_from_a_query_cannot_attach_to_the_next_close_attempt(databases, tmp_path, venue, reuse_client):
    db, peer = databases
    trade = recovery_engine(db, tmp_path, venue)
    exchange = trade.exchange
    exchange.fill, exchange.status = 3, "closed"
    record_id = db.add_signal(make_signal(code=CODE))
    trade.add_trade(db.get_record(record_id), 100)
    exchange.fill, exchange.status = 1, "open"
    old = trade.cover_trade(db.get_record(record_id), 101, "first close")
    old_client = db.get_record(record_id)["cover_client_order_id"]
    winner = []
    def advance_attempt_during_get():
        peer.apply_close_fill(record_id, 0.01, 101, "canceled", client_order_id=old_client, order_id=old.order_id, expected_attempt=1)
        quantity, _, contract = trade.prepare_order(CODE, 0.02, 102, reduce_only=True, record=peer.get_record(record_id))
        assert peer.acquire_close_intent(record_id, quantity, old_client if reuse_client else "nextclose", "new attempt",
                                         order_contract=contract, previous_attempt=1)
        assert peer.claim_order_submission(record_id, "close")
        exchange.orders[old.order_id]["status"] = "canceled"
        winner.append(peer.get_record(record_id))
    exchange.before_read = advance_attempt_during_get
    with pytest.raises(CChanException) as caught:
        trade.query_order(CODE, old.order_id, client_order_id=old_client)
    assert caught.value.errcode == ErrCode.LIST_ORDER_FAIL
    assert peer.get_record(record_id) == winner[0]
    assert peer.get_record(record_id)["cover_order_id"] is None
    assert len(exchange.created) == 2


@pytest.mark.parametrize("phase", ["open", "close"])
@pytest.mark.parametrize("write", ["ack", "submission"])
def test_new_contract_identity_writes_also_require_the_original_client(databases, tmp_path, phase, write):
    db, _ = databases
    trade = recovery_engine(db, tmp_path, "binance")
    record_id = db.add_signal(make_signal(code=CODE))
    if phase == "close":
        trade.exchange.fill, trade.exchange.status = 3, "closed"
        trade.add_trade(db.get_record(record_id), 100)
        trade.exchange.fill, trade.exchange.status = 1, "open"
        order = trade.cover_trade(db.get_record(record_id), 101, "fixture")
    else:
        order = trade.add_trade(db.get_record(record_id), 100)
    before = db.get_record(record_id)
    with pytest.raises(CChanException) as caught:
        if write == "ack":
            db.record_order_ack(record_id, phase, order.order_id)
        elif phase == "open":
            db.record_open_submission(record_id, order.order_id, order.status)
        else:
            db.record_close_submission(record_id, order.order_id, order.status)
    assert caught.value.errcode == ErrCode.LIST_ORDER_FAIL
    assert db.get_record(record_id) == before


@pytest.mark.parametrize("action", ["open", "cover_order", "cover_done"])
def test_legacy_manual_helpers_cannot_mutate_a_new_contract(databases, tmp_path, action):
    db, _ = databases
    trade = recovery_engine(db, tmp_path, "binance")
    trade.exchange.fill = 0 if action == "open" else 3
    trade.exchange.status = "open" if action == "open" else "closed"
    record_id = db.add_signal(make_signal(code=CODE))
    trade.add_trade(db.get_record(record_id), 100)
    before = db.get_record(record_id)
    with pytest.raises(CChanException):
        if action == "open":
            db.mark_open(record_id, 100, 5, "manual-guess")
        elif action == "cover_order":
            db.mark_cover_order(record_id, "manual-guess", 0.03, "legacy")
        else:
            db.mark_cover_done(record_id, 101)
    assert db.get_record(record_id) == before


def terminal_partial_close(trade):
    trade.exchange.fill, trade.exchange.status = 3, "closed"
    record_id = trade.chan_db.add_signal(make_signal(code=CODE))
    trade.add_trade(trade.chan_db.get_record(record_id), 100)
    trade.exchange.fill, trade.exchange.status = 1, "canceled"
    trade.cover_trade(trade.chan_db.get_record(record_id), 101, "first partial terminal")
    return record_id


def test_a_stale_cover_snapshot_cannot_authorize_a_later_close_attempt(databases, tmp_path):
    db, _ = databases
    trade = recovery_engine(db, tmp_path, "binance")
    record_id = terminal_partial_close(trade)
    stale = db.get_record(record_id)
    trade.cover_trade(stale, 102, "second partial terminal")
    before = db.get_record(record_id)
    assert before["current_qty"] == 0.01 and before["cover_attempt"] == 2
    trade.exchange.fill, trade.exchange.status = 1, "closed"
    with pytest.raises(CChanException) as caught:
        trade.cover_trade(stale, 103, "stale retry cannot refresh onto attempt three")
    assert caught.value.errcode == ErrCode.SIGNAL_TRADED
    assert db.get_record(record_id) == before
    assert len(trade.exchange.created) == 3


def test_close_preparation_cannot_cross_an_intervening_zero_fill_attempt(databases, tmp_path, monkeypatch):
    db, peer = databases
    trade = recovery_engine(db, tmp_path, "binance")
    record_id = terminal_partial_close(trade)
    stale = db.get_record(record_id)
    second = recovery_engine(peer, tmp_path, "binance")
    second.exchange = trade.exchange
    prepare = trade.prepare_order
    winner = []
    def after_prepare(*args, **kwargs):
        prepared = prepare(*args, **kwargs)
        second.exchange.fill, second.exchange.status = 0, "canceled"
        second.cover_trade(peer.get_record(record_id), 102, "other process finished zero-fill attempt")
        winner.append(peer.get_record(record_id))
        second.exchange.fill, second.exchange.status = 2, "closed"
        return prepared
    monkeypatch.setattr(trade, "prepare_order", after_prepare)
    with pytest.raises(CChanException) as caught:
        trade.cover_trade(stale, 103, "must not reuse another attempt's client id")
    assert caught.value.errcode == ErrCode.SIGNAL_TRADED
    assert db.get_record(record_id) == winner[0]
    assert len(trade.exchange.created) == 3


def test_new_contract_close_intent_requires_the_prepared_previous_attempt(databases, tmp_path):
    db, _ = databases
    trade = recovery_engine(db, tmp_path, "binance")
    record_id = terminal_partial_close(trade)
    before = db.get_record(record_id)
    quantity, _, contract = trade.prepare_order(CODE, 0.02, 102, reduce_only=True, record=before)
    with pytest.raises(CChanException):
        db.acquire_close_intent(record_id, quantity, "missingattempt", "must bind preparation", order_contract=contract)
    assert db.get_record(record_id) == before


@pytest.mark.parametrize("phase", ["open", "close"])
@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_known_terminal_state_not_an_older_open_packet_controls_cancel_and_retry(databases, tmp_path, phase, venue):
    import ccxt
    db, peer = databases
    trade = recovery_engine(db, tmp_path, venue)
    exchange = trade.exchange
    record_id = db.add_signal(make_signal(code=CODE))
    exchange.fill, exchange.status = (1, "open") if phase == "open" else (3, "closed")
    trade.add_trade(db.get_record(record_id), 100)
    if phase == "close":
        exchange.fill, exchange.status = 1, "open"
        trade.cover_trade(db.get_record(record_id), 101, "pending close")
    prefix = "open" if phase == "open" else "cover"
    pending = db.get_record(record_id)
    cancel_calls = []
    def already_terminal(*args, **kwargs):
        cancel_calls.append(args)
        raise ccxt.OrderNotFound("terminal is already proved by another reader")
    exchange.cancel_order = already_terminal
    def terminal_from_another_reader():
        apply = peer.apply_open_fill if phase == "open" else peer.apply_close_fill
        apply(record_id, 0.01, 100 if phase == "open" else 101, "canceled",
              client_order_id=pending[f"{prefix}_client_order_id"], order_id=pending[f"{prefix}_order_id"], expected_attempt=1)
        # REST returns an older open snapshot; do not overwrite that intentionally
        # stale packet. The next actual exit fills only the proven remaining qty.
        exchange.fill, exchange.status = (1, "closed") if phase == "open" else (2, "closed")
    exchange.before_read = terminal_from_another_reader
    if phase == "open":
        trade.close_partial_open(pending, 101, "known terminal partial entry")
    else:
        trade.poll_orders(times=1, interval=0, adjust_price=True)
    stored = db.get_record(record_id)
    assert cancel_calls == []
    assert stored["current_qty"] == 0 and stored["status"] == "closed"
    assert len(exchange.created) == (2 if phase == "open" else 3)


@pytest.mark.parametrize("phase", ["open", "close"])
@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_closed_status_with_less_than_requested_fill_cannot_authorize_a_retry(databases, tmp_path, phase, venue):
    db, _ = databases
    trade = recovery_engine(db, tmp_path, venue)
    exchange = trade.exchange
    record_id = db.add_signal(make_signal(code=CODE))
    if phase == "close":
        exchange.fill, exchange.status = 3, "closed"
        trade.add_trade(db.get_record(record_id), 100)
    exchange.fill, exchange.status = 1, "closed"
    with pytest.raises(CChanException) as caught:
        if phase == "open":
            trade.add_trade(db.get_record(record_id), 100)
        else:
            trade.cover_trade(db.get_record(record_id), 101, "contradictory closed")
    assert caught.value.errcode == ErrCode.LIST_ORDER_FAIL
    before = db.get_record(record_id)
    assert before["current_qty"] == (0 if phase == "open" else 0.03)
    assert before["status"] == ("submitted" if phase == "open" else "closing")
    trade.restore()
    trade.poll_orders(times=1, interval=0, adjust_price=True)
    assert db.get_record(record_id) == before
    assert len(exchange.created) == (1 if phase == "open" else 2)


@pytest.mark.parametrize("phase", ["open", "close"])
@pytest.mark.parametrize("bad_price", [float("nan"), float("inf"), True])
def test_bound_database_reports_cannot_publish_nonfinite_or_boolean_fill_prices(databases, phase, bad_price):
    db, _ = databases
    record_id = opening(db) if phase == "open" else closing(db)
    apply = db.apply_open_fill if phase == "open" else db.apply_close_fill
    before = db.get_record(record_id)
    with pytest.raises(CChanException):
        apply(record_id, 4, bad_price, "open", client_order_id="open-1" if phase == "open" else "close-1",
              order_id="server-open" if phase == "open" else "server-close", expected_attempt=1)
    assert db.get_record(record_id) == before


@pytest.mark.parametrize("phase", ["open", "close"])
def test_bound_database_contract_rejects_a_partial_fill_claiming_closed(databases, tmp_path, phase):
    db, _ = databases
    trade = recovery_engine(db, tmp_path, "binance")
    record_id = db.add_signal(make_signal(code=CODE))
    if phase == "close":
        trade.exchange.fill, trade.exchange.status = 3, "closed"
        trade.add_trade(db.get_record(record_id), 100)
        trade.exchange.fill, trade.exchange.status = 1, "open"
        trade.cover_trade(db.get_record(record_id), 101, "fixture")
    else:
        trade.add_trade(db.get_record(record_id), 100)
    before = db.get_record(record_id)
    prefix = "open" if phase == "open" else "cover"
    apply = db.apply_open_fill if phase == "open" else db.apply_close_fill
    with pytest.raises(CChanException):
        apply(record_id, 0.02, 100 if phase == "open" else 101, "closed",
              client_order_id=before[f"{prefix}_client_order_id"], order_id=before[f"{prefix}_order_id"], expected_attempt=1)
    assert db.get_record(record_id) == before


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("missing", ["clientOrderId", "timestamp"])
def test_an_unpersisted_server_id_hint_does_not_bypass_discovery_proof(databases, tmp_path, monkeypatch, venue, missing):
    db, _ = databases
    trade = recovery_engine(db, tmp_path, venue)
    record_id = lose_open(trade)
    before = db.get_record(record_id)
    fetch = trade.exchange.fetch_order
    monkeypatch.setattr(trade.exchange, "fetch_order", lambda *args, **kwargs: {**fetch(*args, **kwargs), missing: None})
    with pytest.raises(CChanException) as caught:
        trade.query_order(CODE, "1", client_order_id=before["open_client_order_id"])
    assert caught.value.errcode == ErrCode.LIST_ORDER_FAIL
    assert db.get_record(record_id) == before


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_an_unpersisted_server_id_hint_with_full_proof_can_still_be_recovered(databases, tmp_path, venue):
    db, _ = databases
    trade = recovery_engine(db, tmp_path, venue)
    record_id = lose_open(trade)
    before = db.get_record(record_id)
    report = trade.query_order(CODE, "1", client_order_id=before["open_client_order_id"])
    assert report.filled == 0.01 and report.client_order_id == before["open_client_order_id"]
    assert db.get_record(record_id)["open_order_id"] == "1"
    assert db.get_record(record_id)["current_qty"] == 0
    trade.restore()
    assert db.get_record(record_id)["current_qty"] == 0.01
    assert len(trade.exchange.created) == 1
