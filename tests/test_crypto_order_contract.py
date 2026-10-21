"""真实 CCXT precision + fake 交易 I/O + SQLite；无网络请求。"""
import copy
import json
import sqlite3
from decimal import localcontext

import ccxt
import pytest

from Common.ChanException import CChanException
from Common.KLineTime import utc_now_ms
from Trade.CCXTTradeEngine import CCCXTTradeEngine
from Trade.OpenQuotaGen import CBenchPriceQuotaGen
from Trade.db_util import CChanDB
from .test_m6_trade import make_signal
from .test_trade_safety import enabled_trade_conf, write_candidate_receipt

CODE = "TEST/USDT:USDT"


def open_pre_journal_copy(tmp_path, record):
    """Only a temp legacy main table, with no synthetic past audit records."""
    from Trade.SqliteDB import CREATE_TABLE_SQL
    path = str(tmp_path/"pre-journal-orders.db")
    with sqlite3.connect(path) as conn:
        conn.execute(CREATE_TABLE_SQL.format(table_name="chan_trade"))
        conn.execute(f"INSERT INTO chan_trade({','.join(record)}) VALUES({','.join('?' for _ in record)})", tuple(record.values()))
    return CChanDB(db_conf={"type": "sqlite", "sqlite_path": path})


def market(*, spot=False):
    return {"id": "TESTUSDT", "symbol": "TEST/USDT" if spot else CODE, "base": "TEST", "quote": "USDT",
            "settle": None if spot else "USDT", "type": "spot" if spot else "swap", "spot": spot,
            "swap": not spot, "future": False, "option": False, "contract": not spot,
            "linear": None if spot else True, "inverse": None if spot else False, "active": True,
            "contractSize": None if spot else 0.01, "precision": {"amount": 0.001 if spot else 1, "price": 0.1},
            "limits": {"amount": {"min": 0.001 if spot else 1, "max": 10000},
                       "price": {"min": 1, "max": 100000}, "cost": {"min": 1, "max": 100000}}, "info": {}}


class COfflineExchange(ccxt.Exchange):
    id = "binance"

    def __init__(self, definition=None):
        super().__init__({"enableRateLimit": False})
        self.id = "binance"
        self.precisionMode = ccxt.TICK_SIZE
        self.set_markets([copy.deepcopy(definition or market())])
        self.created, self.leverage_calls, self.orders = [], [], {}
        self.fill = 1
        self.status = "open"
        self.positions = []

    def set_leverage(self, leverage, code, params=None):
        self.leverage_calls.append((leverage, code, params))

    def fetch_position_mode(self, symbol=None, params=None):
        return {"hedged": False, "info": {}}

    def fetch_leverage(self, symbol, params=None):
        return {"symbol": symbol, "marginMode": "cross", "longLeverage": 1, "shortLeverage": 1, "info": {}}

    def create_order(self, code, order_type, side, amount, price=None, params=None):
        self.created.append((code, order_type, side, amount, price, copy.deepcopy(params)))
        info = ({"tdMode": params.get("tdMode"), "posSide": params.get("posSide"),
                 "ordType": "post_only" if params.get("postOnly") else order_type}
                if self.id == "okx" else {"positionSide": params.get("positionSide", "BOTH"),
                    "timeInForce": "GTX" if params.get("postOnly") else "GTC", "type": order_type.upper()})
        info["reduceOnly"] = params.get("reduceOnly", False)
        row = {"id": str(len(self.created)), "symbol": code, "clientOrderId": params["clientOrderId"],
               "amount": amount, "filled": self.fill, "average": price or 100, "status": self.status,
               "price": price, "remaining": amount-self.fill, "side": side, "type": order_type,
               "timestamp": utc_now_ms(), "fee": None, "info": info}
        self.orders[row["id"]] = copy.deepcopy(row)
        return row

    def fetch_order(self, order_id, code, params=None):
        if order_id is not None:
            return copy.deepcopy(self.orders[order_id])
        client = (params or {}).get("origClientOrderId") or (params or {}).get("clOrdId")
        rows = [row for row in self.orders.values() if row["clientOrderId"] == client]
        if len(rows) != 1:
            raise ccxt.OrderNotFound("no unique client match")
        return copy.deepcopy(rows[0])

    def fetch_orders(self, code, since=None, limit=None, params=None):
        return list(copy.deepcopy(self.orders).values())

    def fetch_ticker(self, code, params=None):
        return {"symbol": code, "last": 100, "bid": 99.9, "ask": 100.1}

    def fetch_positions(self, symbols, params=None):
        return copy.deepcopy(self.positions)

    def cancel_order(self, order_id, code, params=None):
        self.orders[order_id]["status"] = "canceled"
        return copy.deepcopy(self.orders[order_id])


@pytest.fixture()
def order_db(tmp_path):
    db = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"orders.db")})
    yield db
    db.close()


def engine(db, tmp_path, exchange=None, *, spot=False):
    receipt = write_candidate_receipt(tmp_path)
    result = CCCXTTradeEngine(db, quota_gen=CBenchPriceQuotaGen(3.7),
        ccxt_conf={"exchange": "binance", "mode": "testnet", "testnet": True, "api_key": "key", "secret": "secret",
                   "default_type": "spot" if spot else "swap", "position_mode": "one_way", "margin_mode": "cross"},
        trade_conf=enabled_trade_conf(receipt), environ={"CHANPY_ENABLE_TESTNET": "YES"}, push_msg=False)
    result.exchange = exchange or COfflineExchange(market(spot=spot))
    result.api_interval = 0
    return result


def test_contract_size_and_precision_are_frozen_before_the_real_db_intent(order_db, tmp_path):
    trade = engine(order_db, tmp_path)
    record_id = order_db.add_signal(make_signal(code=CODE))
    result = trade.add_trade(order_db.get_record(record_id), 100.07)
    stored = order_db.get_record(record_id)
    assert stored["open_requested_qty"] == pytest.approx(0.03)
    assert stored["open_filled_qty"] == stored["current_qty"] == pytest.approx(0.01)
    assert result.requested == pytest.approx(0.03) and result.filled == pytest.approx(0.01)
    request = trade.exchange.created[0]
    assert request[3:5] == (3, 100.1)
    contract = json.loads(stored["open_order_contract"])
    assert contract["schema"] == "chan-ccxt-order-v2"
    assert contract["quantity_unit"] == "base_currency" and contract["exchange_amount_unit"] == "contracts"
    assert float(contract["quantity"]) == pytest.approx(0.03)
    assert float(contract["exchange_amount"]) == 3
    assert contract["market"]["contractSize"] == "0.01"


def test_restore_converts_partial_reports_once_including_lookup_without_client_id(order_db, tmp_path):
    trade = engine(order_db, tmp_path)
    record_id = order_db.add_signal(make_signal(code=CODE))
    placed = trade.add_trade(order_db.get_record(record_id), 100)
    trade.exchange.orders[placed.order_id].update(filled=2, clientOrderId=None)
    restored = engine(order_db, tmp_path, trade.exchange)
    assert restored.query_order(CODE, placed.order_id).filled == pytest.approx(0.02)
    restored.restore()
    restored.restore()
    assert order_db.get_record(record_id)["current_qty"] == pytest.approx(0.02)
    assert len(trade.exchange.created) == 1
    trade.exchange.orders[placed.order_id].update(filled=3, status="closed")
    restored.restore()
    trade.exchange.fill = 3
    trade.exchange.status = "closed"
    closed = restored.cover_trade(order_db.get_record(record_id), 101, "fixture exit")
    assert closed.filled == pytest.approx(0.03)
    final = order_db.get_record(record_id)
    assert final["current_qty"] == 0 and final["status"] == "closed"
    assert float(json.loads(final["cover_order_contract"])["exchange_amount"]) == 3


@pytest.mark.parametrize("definition,bench", [
    (market(), 0.5),
    ({**market(), "limits": {**market()["limits"], "cost": {"min": 4, "max": 100000}}}, 3.7),
    ({**market(), "limits": {**market()["limits"], "amount": {"min": 4, "max": 10000}}}, 3.7),
    ({**market(), "limits": {**market()["limits"], "price": {"min": 101, "max": 10000}}}, 3.7),
])
def test_zero_or_post_precision_limits_fail_before_cas(order_db, tmp_path, definition, bench):
    trade = engine(order_db, tmp_path, COfflineExchange(definition))
    trade.quota_gen = CBenchPriceQuotaGen(bench)
    record_id = order_db.add_signal(make_signal(code=CODE))
    with pytest.raises(CChanException):
        trade.add_trade(order_db.get_record(record_id), 100.07)
    record = order_db.get_record(record_id)
    assert record["status"] == "signal" and record["open_attempt"] == 0
    assert trade.exchange.created == []


@pytest.mark.parametrize("mutation", [
    {"contractSize": 0}, {"contractSize": None}, {"contractSize": float("nan")},
    {"linear": False, "inverse": True}, {"settle": "BTC"}, {"active": False},
])
def test_unknown_or_unsupported_contract_metadata_cannot_create_an_intent(order_db, tmp_path, mutation):
    definition = {**market(), **mutation}
    trade = engine(order_db, tmp_path, COfflineExchange(definition))
    record_id = order_db.add_signal(make_signal(code=CODE))
    with pytest.raises(CChanException):
        trade.add_trade(order_db.get_record(record_id), 100.07)
    assert order_db.get_record(record_id)["status"] == "signal"
    assert trade.exchange.created == []


@pytest.mark.parametrize("long,short,expected", [(5, 2, 0.03), (0, 3, -0.03), (2, 2, 0)])
def test_contract_positions_are_base_quantities_not_contract_counts(order_db, tmp_path, long, short, expected):
    trade = engine(order_db, tmp_path)
    trade.exchange.positions = [{"symbol": CODE, "contracts": long, "side": "long", "contractSize": 0.01},
                                {"symbol": CODE, "contracts": short, "side": "short", "contractSize": 0.01}]
    assert trade.get_position(CODE) == pytest.approx(expected)


def test_spot_precision_keeps_base_units_and_does_not_apply_contract_size(order_db, tmp_path):
    trade = engine(order_db, tmp_path, spot=True)
    trade.exchange.fill = 0.01
    record_id = order_db.add_signal(make_signal(code="TEST/USDT"))
    result = trade.add_trade(order_db.get_record(record_id), 100.07)
    assert result.requested == pytest.approx(0.036)
    assert result.filled == pytest.approx(0.01)
    assert order_db.get_record(record_id)["open_requested_qty"] == pytest.approx(0.036)
    assert trade.exchange.created[0][3:5] == (0.036, 100.1)


def test_legacy_contract_intent_without_units_is_not_claimed_or_resubmitted(order_db, tmp_path):
    trade = engine(order_db, tmp_path)
    record_id = order_db.add_signal(make_signal(code=CODE))
    assert order_db.acquire_open_intent(record_id, 0.03, "legacy-without-unit")
    with pytest.raises(CChanException, match="单位契约"):
        trade.place_order(CODE, True, 0.03, 100, client_order_id="legacy-without-unit")
    assert order_db.get_record(record_id)["open_order_status"] == "created"
    assert trade.exchange.created == []


@pytest.mark.parametrize("changed", [{"contractSize": 0.02}, {"active": False}])
def test_metadata_change_between_cas_and_submission_does_not_send_a_new_unit(order_db, tmp_path, monkeypatch, changed):
    trade = engine(order_db, tmp_path)
    acquire = order_db.acquire_open_intent
    def change_after_intent(*args, **kwargs):
        result = acquire(*args, **kwargs)
        trade.exchange.market(CODE).update(changed)
        return result
    monkeypatch.setattr(order_db, "acquire_open_intent", change_after_intent)
    record_id = order_db.add_signal(make_signal(code=CODE))
    with pytest.raises(CChanException, match="漂移"):
        trade.add_trade(order_db.get_record(record_id), 100)
    assert trade.exchange.created == []
    assert order_db.get_record(record_id)["open_order_status"] == "created"


def test_market_close_uses_frozen_reference_but_does_not_turn_it_into_a_limit_price(order_db, tmp_path):
    trade = engine(order_db, tmp_path)
    record_id = order_db.add_signal(make_signal(code=CODE))
    trade.exchange.fill, trade.exchange.status = 3, "closed"
    trade.add_trade(order_db.get_record(record_id), 100)
    order = trade.cover_trade(order_db.get_record(record_id), None, "market close")
    assert order.filled == pytest.approx(0.03)
    assert trade.exchange.created[-1][1] == "market" and trade.exchange.created[-1][4] is None
    contract = json.loads(order_db.get_record(record_id)["cover_order_contract"])
    assert contract["price"] is None and contract["reference_price"] == "100"


def test_order_fill_conversion_is_independent_of_callers_decimal_context(order_db, tmp_path):
    definition = {**market(), "contractSize": 0.001234}
    trade = engine(order_db, tmp_path, COfflineExchange(definition))
    record_id = order_db.add_signal(make_signal(code=CODE))
    with localcontext() as context:
        context.prec = 2
        order = trade.add_trade(order_db.get_record(record_id), 100)
    assert order.filled == pytest.approx(0.001234)
    assert order_db.get_record(record_id)["current_qty"] == pytest.approx(0.001234)


def test_position_conversion_is_independent_of_callers_decimal_context(order_db, tmp_path):
    trade = engine(order_db, tmp_path, COfflineExchange({**market(), "contractSize": 0.001234}))
    trade.exchange.positions = [{"symbol": CODE, "contracts": 5, "side": "long"},
                                {"symbol": CODE, "contracts": 2, "side": "short"}]
    with localcontext() as context:
        context.prec = 2
        position = trade.get_position(CODE)
    assert position == pytest.approx(0.003702)


@pytest.mark.parametrize("changed", [
    {"symbol": "OTHER/USDT:USDT"}, {"amount": 4}, {"filled": -1}, {"average": float("nan")},
    {"clientOrderId": "foreign-client"}, {"side": "sell"}, {"type": "market"},
])
def test_inconsistent_exchange_reports_are_not_booked_as_fills(order_db, tmp_path, monkeypatch, changed):
    trade = engine(order_db, tmp_path)
    submit = trade.exchange.create_order
    def bad_response(*args, **kwargs):
        result = submit(*args, **kwargs)
        result.update(changed)
        return result
    monkeypatch.setattr(trade.exchange, "create_order", bad_response)
    record_id = order_db.add_signal(make_signal(code=CODE))
    with pytest.raises(CChanException):
        trade.add_trade(order_db.get_record(record_id), 100)
    stored = order_db.get_record(record_id)
    assert stored["open_order_status"] == "submitting" and stored["current_qty"] == 0
    # Server acceptance is deliberately still present: recover by the original
    # client id and raw valid server report, never submit a replacement.
    trade.restore()
    assert order_db.get_record(record_id)["current_qty"] == pytest.approx(0.01)
    assert len(trade.exchange.created) == 1


def test_known_exchange_id_cannot_be_replaced_by_another_order_with_the_same_client_id(order_db, tmp_path):
    trade = engine(order_db, tmp_path)
    record_id = order_db.add_signal(make_signal(code=CODE))
    placed = trade.add_trade(order_db.get_record(record_id), 100)
    trade.exchange.orders[placed.order_id]["id"] = "unexpected-id"
    client_id = order_db.get_record(record_id)["open_client_order_id"]
    with pytest.raises(CChanException):
        trade.query_order(CODE, client_order_id=client_id)


def test_order_tracking_uses_frozen_units_after_only_limits_or_ticks_change(order_db, tmp_path):
    trade = engine(order_db, tmp_path)
    record_id = order_db.add_signal(make_signal(code=CODE))
    order = trade.add_trade(order_db.get_record(record_id), 100)
    trade.exchange.market(CODE)["limits"]["cost"]["min"] = 1000
    trade.exchange.market(CODE)["precision"]["amount"] = 5
    trade.exchange.market(CODE)["active"] = False
    trade.exchange.orders[order.order_id]["filled"] = 2
    trade.restore()
    assert order_db.get_record(record_id)["current_qty"] == pytest.approx(0.02)
    assert len(trade.exchange.created) == 1


@pytest.mark.parametrize("definition", [
    {**market(), "contractSize": "0.001234567890123456789"},
    {**market(), "contractSize": "0.000000000000000001",
        "limits": {**market()["limits"], "amount": {"min": 1, "max": None}}},
])
def test_units_that_cannot_roundtrip_through_db_and_ccxt_numeric_boundary_fail_before_cas(order_db, tmp_path, definition):
    trade = engine(order_db, tmp_path, COfflineExchange(definition))
    record_id = order_db.add_signal(make_signal(code=CODE))
    with pytest.raises(CChanException):
        trade.add_trade(order_db.get_record(record_id), 100)
    assert order_db.get_record(record_id)["status"] == "signal"
    assert trade.exchange.created == []


def test_legacy_open_position_with_unknown_units_cannot_automatically_be_covered(order_db, tmp_path):
    trade = engine(order_db, tmp_path)
    record_id = order_db.add_signal(make_signal(code=CODE))
    assert order_db.acquire_open_intent(record_id, 2, "legacy-open")
    order_db.record_open_submission(record_id, "legacy-exchange-id", "closed")
    order_db.apply_open_fill(record_id, 2, 100, "closed")
    with pytest.raises(CChanException, match="单位契约"):
        trade.cover_trade(order_db.get_record(record_id), 100, "cannot infer legacy units")
    assert order_db.get_record(record_id)["status"] == "open"
    assert trade.exchange.created == []


def test_unit_contract_survives_sqlite_reopen_without_changing_any_quantity(tmp_path):
    config = {"type": "sqlite", "sqlite_path": str(tmp_path/"reopen.db")}
    db = CChanDB(db_conf=config)
    try:
        trade = engine(db, tmp_path)
        record_id = db.add_signal(make_signal(code=CODE))
        trade.add_trade(db.get_record(record_id), 100)
        before = db.get_record(record_id)
    finally:
        db.close()
    reopened = CChanDB(db_conf=config)
    try:
        assert reopened.get_record(record_id) == before
    finally:
        reopened.close()


def test_mysql_unit_contract_path_is_disabled_before_any_intent(order_db, tmp_path, monkeypatch):
    trade = engine(order_db, tmp_path)
    monkeypatch.setattr(order_db, "db_type", "mysql")
    record_id = order_db.add_signal(make_signal(code=CODE))
    with pytest.raises(CChanException, match="MySQL"):
        trade.add_trade(order_db.get_record(record_id), 100)
    assert order_db.get_record(record_id)["status"] == "signal"
    assert trade.exchange.created == []
