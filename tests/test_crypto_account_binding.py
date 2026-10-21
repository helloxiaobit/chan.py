"""Account/environment are frozen in the real SQLite intent, not caller labels."""
import copy
import hashlib
import json

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.AccountIdentity import observe_account_context
from Trade.db_util import CChanDB
from .test_crypto_order_contract import CODE, open_pre_journal_copy, order_db
from .test_crypto_order_recovery import recovery_engine
from .test_crypto_venue_parameters import venue_engine
from .test_m6_trade import make_signal


def switch_account(exchange):
    exchange.account_alias, exchange.account_uid = "offline-Futures-B", "98765432"


def prepared_intent(trade):
    db = trade.chan_db
    key = db.add_signal(make_signal(code=CODE))
    record = db.get_record(key)
    quantity, price, contract = trade.prepare_order(CODE, 0.03, 100, record=record)
    client = trade.make_client_order_id(record, "open")
    assert db.acquire_open_intent(key, quantity, client, order_contract=contract)
    return key, client, quantity, price


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_swap_v3_binds_native_account_and_environment_to_append_only_attempt(order_db, tmp_path, venue):
    trade = venue_engine(order_db, tmp_path, venue)
    key = order_db.add_signal(make_signal(code=CODE))
    trade.add_trade(order_db.get_record(key), 100)
    contract = json.loads(order_db.get_record(key)["open_order_contract"])
    assert contract["schema"] == "chan-ccxt-order-v3"
    assert contract["account_context"] == observe_account_context(trade.exchange, "testnet")
    attempt, = order_db.get_order_history(key)["attempts"]
    assert attempt["identity"]["contract_complete"] is True
    assert attempt["identity"]["order_contract"] == contract
    assert "offline-Futures-A" not in canonical_bytes(attempt).decode()
    assert contract["account_context"]["identifier_kind"] == ("futures_account_alias" if venue == "binance" else "uid")


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("when", ["before_prepare", "during_settings"])
def test_environment_or_mid_prepare_account_change_does_not_acquire_an_intent(order_db, tmp_path, monkeypatch, venue, when):
    trade = venue_engine(order_db, tmp_path, venue)
    if when == "before_prepare":
        trade.exchange.isSandboxModeEnabled = False
        monkeypatch.setattr(trade.exchange, "fetch_position_mode", lambda *args: pytest.fail("private settings before route guard"))
    else:
        original = trade.exchange.fetch_position_mode

        def change(*args):
            result = original(*args)
            switch_account(trade.exchange)
            return result

        monkeypatch.setattr(trade.exchange, "fetch_position_mode", change)
    key = order_db.add_signal(make_signal(code=CODE))
    with pytest.raises(CChanException):
        trade.add_trade(order_db.get_record(key), 100)
    assert order_db.get_record(key)["status"] == "signal"
    assert order_db.get_order_history(key)["attempts"] == []
    assert trade.exchange.created == []


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["account", "environment"])
def test_identity_changed_after_intent_cannot_claim_or_submit(order_db, tmp_path, venue, damage):
    trade = venue_engine(order_db, tmp_path, venue)
    key, client, quantity, price = prepared_intent(trade)
    before, history = order_db.get_record(key), order_db.get_order_history(key)
    if damage == "account":
        switch_account(trade.exchange)
    else:
        trade.exchange.isSandboxModeEnabled = False
    with pytest.raises(CChanException):
        trade.place_order(CODE, True, quantity, price, client_order_id=client)
    assert order_db.get_record(key) == before
    assert order_db.get_order_history(key) == history
    assert trade.exchange.created == []


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_account_change_during_submit_keeps_unknown_attempt_without_ack(order_db, tmp_path, monkeypatch, venue):
    trade = venue_engine(order_db, tmp_path, venue)
    key, client, quantity, price = prepared_intent(trade)
    original = trade.exchange.create_order

    def changed(*args):
        response = original(*args)
        switch_account(trade.exchange)
        return response

    monkeypatch.setattr(trade.exchange, "create_order", changed)
    with pytest.raises(CChanException):
        trade.place_order(CODE, True, quantity, price, client_order_id=client)
    record = order_db.get_record(key)
    assert record["open_order_status"] == "submitting" and record["open_order_id"] is None
    assert record["open_filled_qty"] == 0
    assert [e["kind"] for e in order_db.get_order_history(key)["attempts"][0]["events"]] == ["intent", "claim"]
    assert len(trade.exchange.created) == 1


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("when", ["before_read", "during_read"])
def test_query_cannot_ack_or_apply_a_report_across_account_change(order_db, tmp_path, monkeypatch, venue, when):
    trade = recovery_engine(order_db, tmp_path, venue)
    key = order_db.add_signal(make_signal(code=CODE))
    order = trade.add_trade(order_db.get_record(key), 100)
    before, history = order_db.get_record(key), order_db.get_order_history(key)
    if when == "before_read":
        switch_account(trade.exchange)
        monkeypatch.setattr(trade.exchange, "fetch_order", lambda *args: pytest.fail("query sent to another account"))
    else:
        trade.exchange.before_read = lambda: switch_account(trade.exchange)
    with pytest.raises(CChanException):
        trade.query_order(CODE, order.order_id)
    assert order_db.get_record(key) == before
    assert order_db.get_order_history(key) == history


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_cancel_or_reduce_cannot_target_a_different_account(order_db, tmp_path, monkeypatch, venue):
    trade = venue_engine(order_db, tmp_path, venue)
    trade.exchange.fill, trade.exchange.status = 3, "closed"
    key = order_db.add_signal(make_signal(code=CODE))
    order = trade.add_trade(order_db.get_record(key), 100)
    before, history = order_db.get_record(key), order_db.get_order_history(key)
    switch_account(trade.exchange)
    monkeypatch.setattr(trade.exchange, "cancel_order", lambda *args: pytest.fail("cancel sent to another account"))
    with pytest.raises(CChanException):
        trade.cancel_order(CODE, order.order_id)
    with pytest.raises(CChanException):
        trade.cover_trade(order_db.get_record(key), 101, "must keep original account")
    assert order_db.get_record(key) == before
    assert order_db.get_order_history(key) == history
    assert len(trade.exchange.created) == 1


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_cancel_requires_a_unique_persisted_intent(order_db, tmp_path, monkeypatch, venue):
    trade = venue_engine(order_db, tmp_path, venue)
    monkeypatch.setattr(trade.exchange, "cancel_order", lambda *args: pytest.fail("untracked cancellation"))
    with pytest.raises(CChanException):
        trade.cancel_order(CODE, "unknown-server-order")


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_reduce_does_not_freeze_a_new_account_between_original_check_and_prepare(order_db, tmp_path, monkeypatch, venue):
    trade = venue_engine(order_db, tmp_path, venue)
    trade.exchange.fill, trade.exchange.status = 3, "closed"
    key = order_db.add_signal(make_signal(code=CODE))
    trade.add_trade(order_db.get_record(key), 100)
    before, history = order_db.get_record(key), order_db.get_order_history(key)
    original = trade._execution_settings

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        switch_account(trade.exchange)
        return result

    monkeypatch.setattr(trade, "_execution_settings", changed)
    with pytest.raises(CChanException):
        trade.prepare_order(CODE, 0.03, 101, reduce_only=True, record=before)
    assert order_db.get_record(key) == before
    assert order_db.get_order_history(key) == history


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_legacy_v2_can_be_read_but_does_not_gain_native_account_authority(order_db, tmp_path, venue):
    trade = venue_engine(order_db, tmp_path, venue)
    trade.exchange.fill, trade.exchange.status = 3, "closed"
    key = order_db.add_signal(make_signal(code=CODE))
    order = trade.add_trade(order_db.get_record(key), 100)
    record = copy.deepcopy(order_db.get_record(key))
    contract = json.loads(record["open_order_contract"])
    contract.pop("account_context", None)
    contract["schema"] = "chan-ccxt-order-v2"
    contract["contract_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in contract.items() if k != "contract_id"})).hexdigest()
    record["open_order_contract"] = canonical_bytes(contract).decode()
    legacy = open_pre_journal_copy(tmp_path, record)
    try:
        trade.chan_db = legacy
        assert trade.query_order(CODE, order.order_id).filled == pytest.approx(0.03)
        with pytest.raises(CChanException):
            trade.cover_trade(legacy.get_record(key), 101, "v2 has no original account proof")
        with pytest.raises(CChanException):
            trade.cancel_order(CODE, order.order_id)
        assert len(trade.exchange.created) == 1
        assert "account_context" not in json.loads(legacy.get_record(key)["open_order_contract"])
    finally:
        legacy.close()


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_restart_rechecks_original_context_and_still_allows_proven_management(order_db, tmp_path, venue):
    trade = venue_engine(order_db, tmp_path, venue)
    key = order_db.add_signal(make_signal(code=CODE))
    order = trade.add_trade(order_db.get_record(key), 100)
    history = order_db.get_order_history(key)
    reopened = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"orders.db")})
    try:
        restarted = venue_engine(reopened, tmp_path, venue)
        restarted.exchange = trade.exchange
        restarted.exchange.orders[order.order_id]["filled"] = 2
        restarted.restore()
        assert reopened.get_record(key)["current_qty"] == pytest.approx(0.02)
        assert reopened.get_order_history(key)["attempts"][0]["identity"] == history["attempts"][0]["identity"]
        assert restarted.cancel_order(CODE, order.order_id) is True
        restarted.restore()
        assert reopened.get_record(key)["open_order_status"] == "canceled"
        assert len(trade.exchange.created) == 1
    finally:
        reopened.close()
