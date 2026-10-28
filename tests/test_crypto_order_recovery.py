"""Real CCXT recovery of legacy fake histories; no native admission or network."""
import copy

import ccxt
import pytest

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from Trade.db_util import CChanDB
from .test_crypto_order_contract import CODE, open_legacy_history, open_pre_journal_copy, order_db
from .test_crypto_venue_parameters import CVenueExchange, venue_engine
from .test_m6_trade import make_signal


class CRecoveryExchange(CVenueExchange):
    def __init__(self, venue):
        super().__init__(venue)
        self.ack_only = self.lost_response = self.direct_not_found = False
        self.lookup_error = None
        self.reads, self.pages = [], []
        self.page_loader = lambda kind, request: []
        self.before_read = lambda: None
        self.created_ms = utc_now_ms()
        if venue == "binance":
            self.builder.fapiPrivateGetOrder = self._native_lookup
            self.builder.fapiPrivateGetAllOrders = lambda request: self._native_page("all", request)
        else:
            self.builder.privateGetTradeOrder = lambda request: {"data": [self._native_lookup(request)]}
            self.builder.privateGetTradeOrdersPending = lambda request: {"data": self._native_page("pending", request)}
            self.builder.privateGetTradeOrdersHistoryArchive = lambda request: {"data": self._native_page(request["state"], request)}
            self.builder.privateGetTradeOrdersHistory = lambda request: pytest.fail("must use archive, including canceled orders")

    def native_row(self, row):
        price = "0" if row["price"] is None else str(row["price"])
        if self.id == "binance":
            return {"symbol": self.market(CODE)["id"], "orderId": row["id"], "clientOrderId": row["clientOrderId"],
                    "origQty": str(row["amount"]), "executedQty": str(row["filled"]), "avgPrice": str(row["average"]),
                    "price": price, "side": row["side"].upper(), "type": row["type"].upper(),
                    "positionSide": row["info"]["positionSide"], "reduceOnly": row["info"]["reduceOnly"],
                    "timeInForce": row["info"]["timeInForce"],
                    "status": {"open": "PARTIALLY_FILLED", "closed": "FILLED", "canceled": "CANCELED"}[row["status"]],
                    "time": row["timestamp"], "updateTime": row["timestamp"]}
        return {"instId": self.market(CODE)["id"], "instType": "SWAP", "ordId": row["id"], "clOrdId": row["clientOrderId"],
                "sz": str(row["amount"]), "accFillSz": str(row["filled"]), "avgPx": str(row["average"]),
                "px": price, "side": row["side"], "ordType": row["type"], "posSide": "net", "tdMode": "cross",
                "reduceOnly": str(row["info"]["reduceOnly"]).lower(),
                "state": {"open": "partially_filled", "closed": "filled", "canceled": "canceled"}[row["status"]],
                "cTime": str(row["timestamp"]), "uTime": str(row["timestamp"])}

    def create_order(self, *args, **kwargs):
        row = super().create_order(*args, **kwargs)
        row["timestamp"] = max(self.created_ms, utc_now_ms())
        self.orders[row["id"]] = copy.deepcopy(row)
        if self.lost_response:
            raise ccxt.RequestTimeout("accepted but response lost")
        if self.ack_only:
            ack = ({"symbol": self.market(CODE)["id"], "orderId": row["id"], "clientOrderId": row["clientOrderId"]}
                   if self.id == "binance" else {"ordId": row["id"], "clOrdId": row["clientOrderId"], "sCode": "0"})
            return self.builder.parse_order(ack, self.builder.market(CODE))
        return self.builder.parse_order(self.native_row(row), self.builder.market(CODE))

    def _native_lookup(self, request):
        self.reads.append(copy.deepcopy(request))
        self.before_read()
        if self.lookup_error:
            raise self.lookup_error
        if self.direct_not_found:
            raise ccxt.OrderNotFound("not in direct endpoint")
        order_id = request.get("orderId") or request.get("ordId")
        client = request.get("origClientOrderId") or request.get("clOrdId")
        rows = [row for row in self.orders.values() if row["id"] == order_id or (client and row["clientOrderId"] == client)]
        if len(rows) != 1:
            raise ccxt.OrderNotFound("no unique match")
        return self.native_row(rows[0])

    def fetch_order(self, order_id, code, params=None):
        return self.builder.fetch_order(order_id, code, params or {})

    def _native_page(self, kind, request):
        self.pages.append((kind, copy.deepcopy(request)))
        return [self.native_row(row) for row in self.page_loader(kind, request)]

    def fetch_orders(self, code, since=None, limit=None, params=None):
        return self.builder.fetch_orders(code, since, limit, params or {})

    def fetch_open_orders(self, code, since=None, limit=None, params=None):
        return self.builder.fetch_open_orders(code, since, limit, params or {})

    def fetch_closed_orders(self, code, since=None, limit=None, params=None):
        return self.builder.fetch_closed_orders(code, since, limit, params or {})


def recovery_engine(db, tmp_path, venue):
    trade = venue_engine(db, tmp_path, venue)
    trade.exchange = CRecoveryExchange(venue)
    return trade


def lose_open(trade):
    trade.exchange.lost_response = True
    record_id = trade.chan_db.add_signal(make_signal(code=CODE))
    with pytest.raises(CChanException) as caught:
        open_legacy_history(trade, trade.chan_db.get_record(record_id), 100)
    assert caught.value.errcode == ErrCode.PLACE_ORDER_FAIL
    return record_id


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("phase", ["open", "close"])
def test_ack_id_is_durable_before_followup_and_unknown_fill_never_becomes_zero(order_db, tmp_path, venue, phase):
    trade = recovery_engine(order_db, tmp_path, venue)
    exchange = trade.exchange
    record_id = order_db.add_signal(make_signal(code=CODE))
    if phase == "close":
        exchange.fill, exchange.status = 3, "closed"
        open_legacy_history(trade, order_db.get_record(record_id), 100)
    prefix = "open" if phase == "open" else "cover"
    exchange.ack_only, exchange.lookup_error = True, ccxt.NetworkError("read offline")
    expected_id = str(len(exchange.created)+1)
    def inspect_durable_ack():
        pending = order_db.get_record(record_id)
        assert pending[f"{prefix}_order_id"] == expected_id
        assert pending[f"{prefix}_order_status"] == "submitting"
        assert pending["current_qty"] == (0 if phase == "open" else 0.03)
    exchange.before_read = inspect_durable_ack
    with pytest.raises(CChanException) as caught:
        if phase == "open":
            open_legacy_history(trade, order_db.get_record(record_id), 100)
        else:
            trade.cover_trade(order_db.get_record(record_id), 101, "ack close")
    assert caught.value.errcode == ErrCode.LIST_ORDER_FAIL
    inspect_durable_ack()
    assert len(exchange.reads) == 1 and exchange.pages == []
    exchange.lookup_error, exchange.before_read = None, lambda: None
    fresh_db = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"orders.db")})
    try:
        restored = recovery_engine(fresh_db, tmp_path, venue)
        restored.exchange = exchange
        restored.restore()
        restored.restore()
    finally:
        fresh_db.close()
    stored = order_db.get_record(record_id)
    assert stored["current_qty"] == (0.01 if phase == "open" else 0)
    assert stored["status"] == ("partially_filled" if phase == "open" else "closed")
    assert len(exchange.created) == (1 if phase == "open" else 2)


@pytest.mark.parametrize("venue,client_key", [("binance", "origClientOrderId"), ("okx", "clOrdId")])
def test_accepted_response_loss_recovers_by_native_client_id_without_history_or_resubmit(order_db, tmp_path, venue, client_key):
    trade = recovery_engine(order_db, tmp_path, venue)
    record_id = lose_open(trade)
    pending = order_db.get_record(record_id)
    assert pending["open_order_id"] is None and pending["open_order_status"] == "submitting"
    assert not order_db.claim_order_submission(record_id, "open")
    trade.restore()
    trade.restore()
    stored = order_db.get_record(record_id)
    assert stored["current_qty"] == 0.01 and stored["open_order_id"] == "1"
    assert trade.exchange.reads[0][client_key] == pending["open_client_order_id"]
    assert ("orderId" if venue == "binance" else "ordId") not in trade.exchange.reads[0]
    assert trade.exchange.pages == [] and len(trade.exchange.created) == 1


def test_ack_saves_only_identity_and_never_replaces_the_known_server_id(order_db, tmp_path):
    trade = recovery_engine(order_db, tmp_path, "okx")
    record_id = lose_open(trade)
    before = order_db.get_record(record_id)
    order_db.record_order_ack(record_id, "open", "1", client_order_id=before["open_client_order_id"], expected_attempt=before["open_attempt"])
    order_db.record_order_ack(record_id, "open", "1", client_order_id=before["open_client_order_id"], expected_attempt=before["open_attempt"])
    after = order_db.get_record(record_id)
    assert after["open_order_status"] == before["open_order_status"] == "submitting"
    assert after["open_filled_qty"] == before["open_filled_qty"] == 0
    with pytest.raises(CChanException):
        order_db.record_order_ack(record_id, "open", "other", client_order_id=before["open_client_order_id"], expected_attempt=before["open_attempt"])
    assert order_db.get_record(record_id)["open_order_id"] == "1"


def test_intent_utc_ms_is_set_in_the_cas_and_never_backfilled_or_replaced(order_db, tmp_path, monkeypatch):
    import Trade.db_util as db_module
    monkeypatch.setattr(db_module, "utc_now_ms", lambda: 1_800_000_000_123, raising=False)
    record_id = order_db.add_signal(make_signal(code=CODE))
    assert order_db.get_record(record_id)["open_intent_ms"] is None
    assert order_db.acquire_open_intent(record_id, 1, "intent-time")
    monkeypatch.setattr(db_module, "utc_now_ms", lambda: 1_800_000_000_999)
    assert not order_db.acquire_open_intent(record_id, 1, "duplicate-time")
    assert order_db.get_record(record_id)["open_intent_ms"] == 1_800_000_000_123
    order_db.record_open_submission(record_id, "1", "closed")
    order_db.apply_open_fill(record_id, 1, 100, "closed")
    assert order_db.acquire_close_intent(record_id, 1, "close-time", "fixture")
    assert order_db.get_record(record_id)["cover_intent_ms"] == 1_800_000_000_999


@pytest.mark.parametrize("venue,error", [(venue, error) for venue in ["binance", "okx"]
                                       for error in [ccxt.NetworkError, ccxt.AuthenticationError, ccxt.RateLimitExceeded]])
def test_transport_and_auth_failure_never_start_a_history_scan_or_resubmit(order_db, tmp_path, venue, error):
    trade = recovery_engine(order_db, tmp_path, venue)
    record_id = lose_open(trade)
    trade.exchange.lookup_error = error("unavailable")
    trade.restore()
    assert order_db.get_record(record_id)["open_order_status"] == "submitting"
    assert len(trade.exchange.reads) == 1 and trade.exchange.pages == []
    assert len(trade.exchange.created) == 1


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_history_recovers_a_later_page_including_okx_partially_filled_cancel(order_db, tmp_path, venue):
    trade = recovery_engine(order_db, tmp_path, venue)
    record_id = lose_open(trade)
    exchange = trade.exchange
    exchange.direct_not_found = True
    size = 1000 if venue == "binance" else 100
    target = {**exchange.orders["1"], "id": str(size+1), "status": "canceled", "filled": 2}
    fillers = [{**target, "id": str(index), "clientOrderId": f"unrelated{index}"} for index in range(1, size+1)]
    def load(kind, request):
        if venue == "binance":
            return [target] if request.get("orderId") == str(size+1) else fillers
        if kind == "canceled":
            return [target] if request.get("after") == str(2*size) else [
                {**row, "id": str(2*size+index)} for index, row in enumerate(fillers)]
        return []
    exchange.page_loader = load
    trade.restore()
    trade.restore()
    stored = order_db.get_record(record_id)
    assert stored["open_order_id"] == target["id"] and stored["open_filled_qty"] == 0.02
    assert stored["status"] == "open" and stored["open_order_status"] == "canceled"
    assert len(exchange.created) == 1
    assert all(request["limit"] == size for _, request in exchange.pages)
    if venue == "binance":
        assert exchange.pages[1][1]["orderId"] == str(size+1)
        assert all(request["endTime"]-request["startTime"] < 7*86_400_000 for _, request in exchange.pages)
    else:
        assert {kind for kind, _ in exchange.pages} == {"pending", "filled", "canceled"}
        assert exchange.pages[-1][1]["after"] == str(2*size)


@pytest.mark.parametrize("venue,mutation", [
    ("binance", {"positionSide": "SHORT"}), ("binance", {"reduceOnly": True}),
    ("binance", {"timeInForce": "GTX"}), ("okx", {"posSide": "short"}),
    ("okx", {"tdMode": "isolated"}), ("okx", {"ordType": "post_only"}),
])
def test_server_fill_on_wrong_leg_margin_or_post_only_is_not_applied(order_db, tmp_path, venue, mutation):
    trade = recovery_engine(order_db, tmp_path, venue)
    record_id = lose_open(trade)
    native_row = trade.exchange.native_row
    trade.exchange.native_row = lambda row: {**native_row(row), **mutation}
    with pytest.raises(CChanException) as caught:
        trade.query_order(CODE, client_order_id=order_db.get_record(record_id)["open_client_order_id"])
    assert caught.value.errcode == ErrCode.LIST_ORDER_FAIL
    assert order_db.get_record(record_id)["current_qty"] == 0
    assert order_db.get_record(record_id)["open_order_id"] is None


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mutation", [{"id": None}, {"clientOrderId": "wrong-client"},
                                      {"symbol": "OTHER/USDT:USDT"}, {"side": "sell"}, {"amount": 999}])
def test_wrong_ack_identity_never_gets_saved_or_used_for_followup(order_db, tmp_path, venue, mutation):
    trade = recovery_engine(order_db, tmp_path, venue)
    trade.exchange.ack_only = True
    create = trade.exchange.create_order
    trade.exchange.create_order = lambda *args, **kwargs: {**create(*args, **kwargs), **mutation}
    record_id = order_db.add_signal(make_signal(code=CODE))
    with pytest.raises(CChanException):
        open_legacy_history(trade, order_db.get_record(record_id), 100)
    stored = order_db.get_record(record_id)
    assert stored["open_order_id"] is None and stored["current_qty"] == 0
    assert stored["open_order_status"] == "submitting"
    assert trade.exchange.reads == [] and len(trade.exchange.created) == 1


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("failure", ["empty", "repeated_page", "budget", "two_orders"])
def test_incomplete_or_ambiguous_history_never_means_no_order_or_permission_to_retry(order_db, tmp_path, venue, failure):
    import Trade.CCXTTradeEngine as engine_module
    trade = recovery_engine(order_db, tmp_path, venue)
    record_id = lose_open(trade)
    exchange = trade.exchange
    exchange.direct_not_found = True
    target = exchange.orders["1"]
    size = 1000 if venue == "binance" else 100
    def load(kind, request):
        if failure == "empty":
            return []
        if failure == "two_orders":
            return [{**target, "id": "1"}, {**target, "id": "2"}]
        offset = 0
        if failure == "budget":
            offset = int(request.get("orderId", "1"))-1 if venue == "binance" else int(request.get("after", "100000"))-size-1
        return [{**target, "id": str(offset+index+1), "clientOrderId": f"unrelated{offset+index+1}"} for index in range(size)]
    exchange.page_loader = load
    with pytest.raises(CChanException) as caught:
        trade.query_order(CODE, client_order_id=order_db.get_record(record_id)["open_client_order_id"])
    assert caught.value.errcode == ErrCode.LIST_ORDER_FAIL
    assert len(exchange.pages) <= engine_module._HISTORY_MAX_PAGES == 32
    if failure == "budget":
        assert len(exchange.pages) == 32
    if failure == "repeated_page":
        assert len(exchange.pages) == 2
    stored = order_db.get_record(record_id)
    assert stored["open_order_id"] is None and stored["status"] == "submitted"
    assert not order_db.claim_order_submission(record_id, "open")
    assert len(exchange.created) == 1


def test_binance_history_windows_do_not_skip_the_original_intent_or_the_next_window(order_db, tmp_path, monkeypatch):
    import Trade.db_util as db_module
    start = utc_now_ms()-7*86_400_000
    monkeypatch.setattr(db_module, "utc_now_ms", lambda: start)
    trade = recovery_engine(order_db, tmp_path, "binance")
    record_id = lose_open(trade)
    target = trade.exchange.orders["1"]
    trade.exchange.direct_not_found = True
    trade.exchange.page_loader = lambda kind, request: [target] if request["startTime"] <= target["timestamp"] <= request["endTime"] else []
    trade.restore()
    windows = [request for _, request in trade.exchange.pages]
    assert len(windows) == 2
    assert windows[0]["startTime"] == start
    assert windows[1]["startTime"] == windows[0]["endTime"]+1
    assert order_db.get_record(record_id)["open_filled_qty"] == 0.01


def test_missing_legacy_utc_clock_stays_null_on_reopen_and_cannot_start_a_guessed_history(order_db, tmp_path):
    trade = recovery_engine(order_db, tmp_path, "okx")
    record_id = lose_open(trade)
    # A genuine pre-journal store, not a damaged identity already recorded as new.
    record = order_db.get_record(record_id)
    record["open_intent_ms"] = None
    reopened = open_pre_journal_copy(tmp_path, record)
    try:
        trade.chan_db = reopened
        trade.exchange.direct_not_found = True
        trade.restore()
        assert reopened.get_record(record_id)["open_intent_ms"] is None
        assert trade.exchange.pages == []
        # A known immutable exchange id still works; no timestamp is invented.
        reopened.record_order_ack(record_id, "open", "1", client_order_id=reopened.get_record(record_id)["open_client_order_id"], expected_attempt=1)
        trade.exchange.direct_not_found = False
        trade.restore()
        assert reopened.get_record(record_id)["open_filled_qty"] == 0.01
        assert reopened.get_record(record_id)["open_intent_ms"] is None
        history = reopened.get_order_history(record_id)
        assert history["attempts"][0]["origin"] == "legacy_snapshot"
        assert history["attempts"][0]["identity"]["intent_ms"] is None
        assert history["gaps"]
    finally:
        reopened.close()


@pytest.mark.parametrize("venue,price_key", [("binance", "price"), ("okx", "px")])
def test_server_limit_price_must_match_the_frozen_request(order_db, tmp_path, venue, price_key):
    trade = recovery_engine(order_db, tmp_path, venue)
    record_id = lose_open(trade)
    native_row = trade.exchange.native_row
    trade.exchange.native_row = lambda row: {**native_row(row), price_key: "101"}
    with pytest.raises(CChanException) as caught:
        trade.query_order(CODE, client_order_id=order_db.get_record(record_id)["open_client_order_id"])
    assert caught.value.errcode == ErrCode.LIST_ORDER_FAIL
    assert order_db.get_record(record_id)["current_qty"] == 0


@pytest.mark.parametrize("phase", ["open", "close"])
def test_submission_report_cannot_overwrite_an_ack_id_from_another_process(order_db, phase):
    record_id = order_db.add_signal(make_signal(code=CODE))
    assert order_db.acquire_open_intent(record_id, 1, "open-ack")
    if phase == "close":
        order_db.record_open_submission(record_id, "original-open", "closed")
        order_db.apply_open_fill(record_id, 1, 100, "closed")
        assert order_db.acquire_close_intent(record_id, 1, "close-ack", "fixture")
    assert order_db.claim_order_submission(record_id, phase)
    order_db.record_order_ack(record_id, phase, "ack-original")
    submit = order_db.record_open_submission if phase == "open" else order_db.record_close_submission
    with pytest.raises(CChanException):
        submit(record_id, "wrong-server-id", "open")
    prefix = "open" if phase == "open" else "cover"
    assert order_db.get_record(record_id)[f"{prefix}_order_id"] == "ack-original"


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mutation", [{"timestamp": None}, {"timestamp": 1}, {"clientOrderId": None}])
def test_client_only_result_requires_its_own_utc_creation_and_client_echo(order_db, tmp_path, venue, mutation):
    trade = recovery_engine(order_db, tmp_path, venue)
    record_id = lose_open(trade)
    original_fetch = trade.exchange.fetch_order
    trade.exchange.fetch_order = lambda *args, **kwargs: {**original_fetch(*args, **kwargs), **mutation}
    trade.restore()
    stored = order_db.get_record(record_id)
    assert stored["open_order_id"] is None and stored["current_qty"] == 0
    assert len(trade.exchange.created) == 1


def test_binance_history_explicitly_starts_before_the_latest_page(order_db, tmp_path):
    trade = recovery_engine(order_db, tmp_path, "binance")
    record_id = lose_open(trade)
    target = trade.exchange.orders["1"]
    others = [{**target, "id": str(index), "clientOrderId": f"other{index}"} for index in range(2, 1002)]
    trade.exchange.direct_not_found = True
    def load(kind, request):
        # Binance defaults to MOST RECENT when orderId is absent, not the
        # earliest page after startTime. Do not let our fixture hide that gap.
        if "orderId" not in request:
            return others
        cursor = int(request["orderId"])
        return [row for row in [target, *others] if int(row["id"]) >= cursor][:1000]
    trade.exchange.page_loader = load
    trade.restore()
    assert order_db.get_record(record_id)["open_order_id"] == "1"
    assert trade.exchange.pages[0][1]["orderId"] == "1"
    assert len(trade.exchange.pages) == 2


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_ack_without_a_read_failure_applies_only_the_followup_fill(order_db, tmp_path, venue):
    trade = recovery_engine(order_db, tmp_path, venue)
    trade.exchange.ack_only = True
    record_id = order_db.add_signal(make_signal(code=CODE))
    def before_read():
        pending = order_db.get_record(record_id)
        assert pending["open_order_id"] == "1" and pending["open_order_status"] == "submitting"
        assert pending["open_filled_qty"] == 0 and pending["current_qty"] == 0
    trade.exchange.before_read = before_read
    result = open_legacy_history(trade, order_db.get_record(record_id), 100)
    assert result.filled == 0.01 and order_db.get_record(record_id)["current_qty"] == 0.01
    assert len(trade.exchange.reads) == 1 and len(trade.exchange.created) == 1


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_partial_close_cancel_race_uses_terminal_get_and_a_new_remaining_intent(order_db, tmp_path, venue):
    trade = recovery_engine(order_db, tmp_path, venue)
    exchange = trade.exchange
    exchange.fill, exchange.status = 3, "closed"
    record_id = order_db.add_signal(make_signal(code=CODE))
    open_legacy_history(trade, order_db.get_record(record_id), 100)
    exchange.ack_only = True
    def race():
        exchange.orders["2"].update(filled=2, status="canceled")
    exchange.before_read = race
    first = trade.cover_trade(order_db.get_record(record_id), 101, "partial cancel race")
    remaining = order_db.get_record(record_id)
    assert first.filled == 0.02 and first.status == "canceled"
    assert remaining["current_qty"] == pytest.approx(0.01) and remaining["status"] == "open"
    first_client = remaining["cover_client_order_id"]
    trade.restore()
    assert len(exchange.created) == 2
    exchange.before_read = lambda: None
    exchange.fill = 1
    final = trade.cover_trade(remaining, 102, "remaining after terminal confirmation")
    closed = order_db.get_record(record_id)
    assert final.filled == 0.01 and final.requested == 0.01
    assert closed["current_qty"] == 0 and closed["status"] == "closed"
    assert closed["cover_client_order_id"] != first_client and closed["cover_attempt"] == 2
    assert closed["cover_filled_qty"] == pytest.approx(0.03)
    assert exchange.created[-1][3] == 1  # one contract, not one coin


def _claim_in_process(path, record_id, gate, result):
    """Only two short SQLite CAS contenders; no exchange/network or agents."""
    db = None
    try:
        db = CChanDB(db_conf={"type": "sqlite", "sqlite_path": path})
        gate.wait(timeout=20)
        result.put(db.claim_order_submission(record_id, "open"))
    except Exception as error:
        result.put(repr(error))
    finally:
        if db is not None:
            db.close()


def test_two_processes_cannot_claim_the_same_submission(order_db, tmp_path):
    import multiprocessing
    record_id = order_db.add_signal(make_signal(code=CODE))
    assert order_db.acquire_open_intent(record_id, 1, "two-process-intent")
    ctx = multiprocessing.get_context("spawn")
    gate, result = ctx.Barrier(3), ctx.Queue()
    processes = [ctx.Process(target=_claim_in_process, args=(str(tmp_path/"orders.db"), record_id, gate, result)) for _ in range(2)]
    try:
        for process in processes:
            process.start()
        gate.wait(timeout=20)
        for process in processes:
            process.join(timeout=20)
            assert process.exitcode == 0
        assert sorted([result.get(timeout=5), result.get(timeout=5)]) == [False, True]
        assert order_db.get_record(record_id)["open_order_status"] == "submitting"
        assert not order_db.claim_order_submission(record_id, "open")
        history = order_db.get_order_history(record_id)
        assert history["gaps"] == []
        assert [event["kind"] for event in history["attempts"][0]["events"]] == ["intent", "claim"]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            if process.pid is not None:
                process.join(timeout=5)
        result.close()
        result.join_thread()


@pytest.mark.parametrize("requested,filled,expected", [(0.03, 0.02, 0.01), (0.3, 0.2, 0.1),
                                                       (1, 0.9999999999999, 0.0000000000001)])
def test_remaining_quantity_is_exact_and_small_positions_are_not_discarded(order_db, requested, filled, expected):
    from decimal import localcontext
    record_id = order_db.add_signal(make_signal(code=CODE))
    assert order_db.acquire_open_intent(record_id, requested, "decimal-open")
    order_db.record_open_submission(record_id, "1", "closed")
    order_db.apply_open_fill(record_id, requested, 100, "closed")
    assert order_db.acquire_close_intent(record_id, requested, "decimal-close", "fixture")
    order_db.record_close_submission(record_id, "2", "canceled")
    with localcontext() as context:
        context.prec = 6
        order_db.apply_close_fill(record_id, filled, 101, "canceled")
    stored = order_db.get_record(record_id)
    assert stored["current_qty"] == expected
    assert stored["cover_filled_qty"] == filled
    assert stored["status"] == "open" and stored["is_open"] == 1


@pytest.mark.parametrize("phase", ["open", "close"])
def test_quantity_beyond_decimal_or_db_precision_fails_without_changing_the_position(order_db, phase):
    record_id = order_db.add_signal(make_signal(code=CODE))
    assert order_db.acquire_open_intent(record_id, 1, "precision-open")
    order_db.record_open_submission(record_id, "1", "open")
    if phase == "open":
        order_db.apply_open_fill(record_id, 1e-100, 100, "open")
        apply, filled = order_db.apply_open_fill, 1
    else:
        order_db.apply_open_fill(record_id, 1, 100, "closed")
        assert order_db.acquire_close_intent(record_id, 1, "precision-close", "fixture")
        apply, filled = order_db.apply_close_fill, 1e-100
    before = order_db.get_record(record_id)
    with pytest.raises(CChanException):
        apply(record_id, filled, 100, "open")
    assert order_db.get_record(record_id) == before
