"""Native execution cash sources, not order averages; all transport is fake."""
import copy
import hashlib
import traceback
from decimal import Decimal

import ccxt
import pytest

from Common.ChanException import CChanException
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.ExecutionFacts import collect_execution_scan, verify_execution_scan
from .test_crypto_order_contract import CODE, market


def definition(venue):
    return {"exchange": venue, "id": "TESTUSDT" if venue == "binance" else "TEST-USDT-SWAP",
            "symbol": CODE, "type": "swap", "base": "TEST", "quote": "USDT", "settle": "USDT",
            "contractSize": "0.01"}


def fill(venue, at, *, key=101, price="100", fee="0.003", quantity=None, side="buy", leg="BOTH"):
    quantity = ("0.03" if venue == "binance" else "3") if quantity is None else quantity
    if venue == "binance":
        return {"symbol": "TESTUSDT", "id": key, "orderId": 7, "side": side.upper(), "positionSide": leg,
                "time": at, "price": price, "qty": quantity, "realizedPnl": "0", "commission": fee,
                "commissionAsset": "USDT", "maker": False, "buyer": side == "buy", "private": "do not archive"}
    return {"instId": "TEST-USDT-SWAP", "instType": "SWAP", "tradeId": str(key), "billId": str(key+1000),
            "ordId": "7", "clOrdId": "testclient", "side": side, "posSide": "net" if leg == "BOTH" else leg.lower(),
            "ts": str(at), "fillTime": str(at), "fillPx": price, "fillSz": quantity, "fillPnl": "0",
            "fee": str(-Decimal(fee)), "feeCcy": "USDT", "execType": "T", "private": "do not archive"}


def funding(venue, at, *, key=901, amount="-0.02"):
    if venue == "binance":
        return {"symbol": "TESTUSDT", "incomeType": "FUNDING_FEE", "tranId": key, "time": at,
                "income": amount, "asset": "USDT", "info": "do not archive"}
    return {"instId": "TEST-USDT-SWAP", "instType": "SWAP", "billId": str(key), "type": "8",
            "subType": "173" if Decimal(amount) < 0 else "174", "ts": str(at), "pnl": amount,
            "balChg": amount, "posBalChg": "0", "ccy": "USDT", "mgnMode": "cross", "fee": "0"}


class NativeSources:
    """Raw private GETs only; create/cancel are intentionally absent."""
    def __init__(self, venue, rows=None, cash=None):
        self.id, self.rows, self.cash, self.requests = venue, rows or [], cash or [], []
        self.endpoints = []
        self.override = None

    def request(self, kind, params):
        self.requests.append((kind, copy.deepcopy(params)))
        if self.override:
            return self.override(kind, params)
        rows = self.rows if kind == "trades" else self.cash
        start = int(params.get("startTime", params.get("begin", 0)))
        end = int(params.get("endTime", params.get("end", 2**63-1)))
        key = "time" if self.id == "binance" else "ts"
        rows = [r for r in rows if start <= int(r[key]) <= end]
        if self.id == "okx":
            rows = sorted(rows, key=lambda r: int(r["billId"]), reverse=True)
            if "after" in params:
                rows = [r for r in rows if int(r["billId"]) < int(params["after"])]
        result = copy.deepcopy(rows[:int(params["limit"])])
        return result if self.id == "binance" else {"code": "0", "data": result, "msg": ""}

    def fapiPrivateGetUserTrades(self, params):
        return self.request("trades", params)

    def fapiPrivateGetIncome(self, params):
        return self.request("funding", params)

    def privateGetTradeFillsHistory(self, params):
        self.endpoints.append("fills-history")
        return self.request("trades", params)

    def privateGetTradeFills(self, params):
        self.endpoints.append("fills")
        return self.request("trades", params)

    def privateGetAccountBillsArchive(self, params):
        self.endpoints.append("bills-archive")
        return self.request("funding", params)


def collect(source, start, end):
    return collect_execution_scan(source, definition(source.id), account_scope="offline-account", mode="testnet",
                                  start_ms=start, end_ms=end)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("fee", ["0.003", "0", "-0.0001"])
def test_native_fees_and_funding_preserve_sign_currency_and_decimal_units(venue, fee):
    start = utc_now_ms()-10_000
    source = NativeSources(venue, [fill(venue, start+1, fee=fee)], [funding(venue, start+2)])
    receipt = collect(source, start, start+100)
    assert verify_execution_scan(receipt) == receipt
    payload = receipt["payload"]
    assert payload["coverage"] == "observed_execution_facts"
    assert payload["economics_complete"] is False
    assert payload["account_scope_verified"] is False
    trade, cash = payload["facts"]
    assert trade["kind"] == "trade" and trade["quantity"] == "0.03" and trade["contracts"] == "3"
    assert trade["price"] == "100" and trade["notional"] == "3"
    assert trade["native_quantity_unit"] == ("base_currency" if venue == "binance" else "contracts")
    assert trade["pnl_currency"] == "USDT"
    assert Decimal(trade["fee_cash_delta"]) == -Decimal(fee)
    assert trade["fee_currency"] == "USDT" and trade["realized_pnl"] == "0"
    assert cash["cash_delta"] == "-0.02" and cash["position_side"] is None
    assert "do not archive" not in str(receipt)
    params = source.requests[0][1]
    assert "fromId" not in params
    if venue == "okx":
        assert params["instType"] == "SWAP" and params["limit"] == "100"
    else:
        assert params["startTime"] == start and params["endTime"] == start+99


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("leg", ["LONG", "SHORT"])
def test_trade_leg_is_not_netted_and_local_ccxt_parser_agrees(venue, leg):
    start = utc_now_ms()-10_000
    raw = fill(venue, start+1, leg=leg, side="sell" if leg == "SHORT" else "buy")
    fact, = collect(NativeSources(venue, [raw]), start, start+100)["payload"]["facts"]
    assert fact["position_side"] == leg
    parser = getattr(ccxt, venue)()
    native_market = market()
    native_market["id"] = definition(venue)["id"]
    parser.set_markets([native_market])
    parsed = parser.parse_trade(raw, parser.market(CODE))
    assert Decimal(str(parsed["amount"])) == Decimal(fact["quantity"] if venue == "binance" else fact["contracts"])
    assert Decimal(str(parsed["fee"]["cost"])) == -Decimal(fact["fee_cash_delta"])
    assert parsed["order"] == fact["order_id"]


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_missing_fee_is_not_zero_and_a_malformed_source_returns_no_receipt(venue):
    start = utc_now_ms()-10_000
    row = fill(venue, start+1)
    del row["commission" if venue == "binance" else "fee"]
    with pytest.raises(CChanException):
        collect(NativeSources(venue, [row]), start, start+100)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("bad", ["time", "fee_currency", "nan", "symbol", "leg"])
def test_raw_cash_evidence_is_validated_before_a_receipt(venue, bad):
    start = utc_now_ms()-10_000
    row = fill(venue, start+1)
    keys = ({"time": "time", "fee_currency": "commissionAsset", "nan": "price", "symbol": "symbol", "leg": "positionSide"}
            if venue == "binance" else {"time": "fillTime", "fee_currency": "feeCcy", "nan": "fillPx", "symbol": "instId", "leg": "posSide"})
    row[keys[bad]] = {"time": None, "fee_currency": "", "nan": "NaN", "symbol": "FOREIGN", "leg": "unknown"}[bad]
    with pytest.raises(CChanException):
        collect(NativeSources(venue, [row]), start, start+100)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_end_exclusive_and_identical_duplicates_have_one_financial_fact(venue):
    start = utc_now_ms()-10_000
    row = fill(venue, start)
    source = NativeSources(venue, [row, copy.deepcopy(row), fill(venue, start+10, key=102)])
    receipt = collect(source, start, start+10)
    assert len(receipt["payload"]["facts"]) == 1


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_same_native_id_with_a_changed_fee_is_not_a_duplicate(venue):
    start = utc_now_ms()-10_000
    with pytest.raises(CChanException):
        collect(NativeSources(venue, [fill(venue, start+1), fill(venue, start+1, fee="0.004")]), start, start+100)


def test_binance_saturated_time_window_splits_without_illegal_cursor_combinations():
    start = utc_now_ms()-10_000
    rows = [fill("binance", start+i, key=1000+i) for i in range(1001)]
    source = NativeSources("binance", rows)
    receipt = collect(source, start, start+2000)
    assert len(receipt["payload"]["facts"]) == 1001
    assert len([r for kind, r in source.requests if kind == "trades"]) > 1
    assert all("fromId" not in r and r["endTime"]-r["startTime"] < 7*86_400_000 for _, r in source.requests)


def test_binance_saturated_single_millisecond_is_unknown_not_complete():
    start = utc_now_ms()-10_000
    source = NativeSources("binance", [fill("binance", start, key=i+1) for i in range(1000)])
    with pytest.raises(CChanException):
        collect(source, start, start+1)


def test_okx_full_page_continues_with_bill_id_not_trade_id():
    start = utc_now_ms()-10_000
    rows = [fill("okx", start+1, key=i+1) for i in range(101)]
    source = NativeSources("okx", rows)
    receipt = collect(source, start, start+100)
    assert len(receipt["payload"]["facts"]) == 101
    requests = [r for kind, r in source.requests if kind == "trades"]
    assert requests[1]["after"] == "1002"


def test_okx_repeated_cursor_page_is_not_an_empty_window_proof():
    start = utc_now_ms()-10_000
    source = NativeSources("okx")
    page = [fill("okx", start+1, key=i+1) for i in range(100)]
    source.override = lambda kind, params: {"code": "0", "data": page if kind == "trades" else []}
    with pytest.raises(CChanException):
        collect(source, start, start+100)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_raw_transport_failure_is_redacted_and_never_retries_an_order(venue):
    start = utc_now_ms()-10_000
    source = NativeSources(venue)
    def fail(kind, params):
        raise ccxt.NetworkError("secret response apiKey=hidden")
    source.override = fail
    with pytest.raises(CChanException) as caught:
        collect(source, start, start+100)
    assert "hidden" not in str(caught.value)
    assert len(source.requests) == 1


def test_okx_recent_fills_do_not_depend_on_the_archive_replication_delay():
    start = utc_now_ms()-10_000
    source = NativeSources("okx", [fill("okx", start+1)])
    receipt = collect(source, start, start+100)
    assert len(receipt["payload"]["facts"]) == 1
    assert "fills" in source.endpoints and "fills-history" not in source.endpoints


def test_reader_rejects_a_rehashed_float_timestamp_in_a_native_fact():
    start = utc_now_ms()-10_000
    receipt = collect(NativeSources("binance", [fill("binance", start+1)]), start, start+100)
    receipt["payload"]["facts"][0]["source_ms"] = float(start+1)
    receipt["payload_sha256"] = hashlib.sha256(canonical_bytes(receipt["payload"])).hexdigest()
    with pytest.raises(CChanException):
        verify_execution_scan(receipt)


def test_redaction_also_applies_to_a_formatted_exception_chain():
    start = utc_now_ms()-10_000
    source = NativeSources("binance")
    def fail(kind, params):
        raise ccxt.NetworkError("sensitive-marker-901")
    source.override = fail
    with pytest.raises(CChanException) as caught:
        collect(source, start, start+100)
    # Do not include this test's own source line when rendering the public error.
    rendered = "".join(traceback.format_exception(type(caught.value), caught.value, None))
    assert "sensitive-marker-901" not in rendered


def test_okx_collection_uses_generation_time_without_rewriting_trade_time():
    start = utc_now_ms()-10_000
    raw = fill("okx", start+2)
    raw["fillTime"] = str(start-100)
    fact, = collect(NativeSources("okx", [raw]), start, start+100)["payload"]["facts"]
    assert fact["source_ms"] == start+2 and fact["timestamp_ms"] == start-100
    assert fact["clock_source"] == "fillTime"


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_explicit_zero_fee_is_distinct_from_an_empty_funding_window(venue):
    start = utc_now_ms()-10_000
    receipt = collect(NativeSources(venue, [fill(venue, start+1, fee="0")]), start, start+100)
    assert receipt["payload"]["facts"][0]["fee_cash_delta"] == "0"
    assert receipt["payload"]["economics_complete"] is False


def test_transport_budget_cannot_be_bypassed_by_endless_decreasing_bill_ids():
    start = utc_now_ms()-10_000
    source = NativeSources("okx")
    def page(kind, params):
        top = int(params.get("after", "100000"))-1
        return {"code": "0", "data": [fill("okx", start+1, key=key-1000) for key in range(top-99, top+1)]}
    source.override = page
    with pytest.raises(CChanException):
        collect(source, start, start+100)
    assert len(source.requests) <= 128


def test_okx_missing_fill_time_is_not_relabelled_from_bill_generation_time():
    start = utc_now_ms()-10_000
    row = fill("okx", start+1)
    del row["fillTime"]
    fact, = collect(NativeSources("okx", [row]), start, start+100)["payload"]["facts"]
    assert fact["timestamp_ms"] is None and fact["clock_source"] == "missing_fill_time"
    assert fact["source_ms"] == start+1


def test_okx_funding_preserves_wallet_position_and_fee_channels_separately():
    start = utc_now_ms()-10_000
    row = funding("okx", start+1)
    row.update(balChg="0", posBalChg="-0.021", fee="-0.001", mgnMode="isolated")
    fact, = collect(NativeSources("okx", cash=[row]), start, start+100)["payload"]["facts"]
    assert fact["cash_delta"] == "-0.02"
    assert fact["fee_cash_delta"] == "-0.001"
    assert fact["wallet_cash_delta"] == "0" and fact["position_cash_delta"] == "-0.021"
    assert fact["position_side"] is None


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_fee_currency_is_not_silently_converted_into_the_pnl_currency(venue):
    start = utc_now_ms()-10_000
    row = fill(venue, start+1)
    row["commissionAsset" if venue == "binance" else "feeCcy"] = "BNB"
    fact, = collect(NativeSources(venue, [row]), start, start+100)["payload"]["facts"]
    assert fact["fee_currency"] == "BNB" and fact["pnl_currency"] == "USDT"


def test_okx_crosses_recent_and_archive_boundary_without_overwriting_timestamps(monkeypatch):
    now = utc_now_ms()
    monkeypatch.setattr("Trade.ExecutionFacts.utc_now_ms", lambda: now)
    boundary = now-3*86_400_000
    rows = [fill("okx", boundary-1), fill("okx", boundary, key=102)]
    source = NativeSources("okx", rows)
    receipt = collect(source, boundary-100, boundary+100)
    assert len(receipt["payload"]["facts"]) == 2
    assert source.endpoints == ["fills-history", "fills", "bills-archive"]


@pytest.mark.parametrize("bad", ["future", "backdate", "bool", "empty_scope"])
def test_bad_collection_context_makes_no_private_request(bad):
    from Trade.ExecutionFacts import MAX_AGE_MS
    now = utc_now_ms()
    start, end, scope = now-100, now-1, "offline-account"
    if bad == "future":
        end = now+100_000
    elif bad == "backdate":
        start = now-MAX_AGE_MS-10_000
    elif bad == "bool":
        start = True
    else:
        scope = ""
    source = NativeSources("binance")
    with pytest.raises(CChanException):
        collect_execution_scan(source, definition("binance"), account_scope=scope, mode="testnet", start_ms=start, end_ms=end)
    assert source.requests == []


@pytest.mark.parametrize("venue,key,value", [("binance", "maker", "sensitive-response"),
    ("binance", "marginAsset", "BTC"), ("okx", "clOrdId", "sensitive response token"),
    ("okx", "execType", "sensitive-response")])
def test_whitelisted_fields_also_require_their_native_types_and_enums(venue, key, value):
    start = utc_now_ms()-10_000
    row = fill(venue, start+1)
    row[key] = value
    with pytest.raises(CChanException):
        collect(NativeSources(venue, [row]), start, start+100)


def test_missing_optional_ccxt_does_not_mask_the_import_error_or_make_io(monkeypatch):
    import builtins
    original = builtins.__import__
    def without_ccxt(name, *args, **kwargs):
        if name == "ccxt":
            raise ModuleNotFoundError("optional ccxt dependency is absent", name="ccxt")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", without_ccxt)
    start = utc_now_ms()-10_000
    source = NativeSources("binance")
    with pytest.raises(ModuleNotFoundError, match="optional ccxt"):
        collect(source, start, start+100)
    assert source.requests == []
