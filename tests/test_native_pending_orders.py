"""Native pending channels and original units; all transport is fake."""
import copy
import importlib.util
import hashlib
import subprocess
import sys
import traceback
from types import SimpleNamespace

import ccxt
import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from .test_account_identity import native_client


NOW = 1_800_000_000_000
ALGOS = ("conditional", "oco", "chase", "trigger", "move_order_stop", "iceberg", "twap", "smart_iceberg")


def pending_api(source=None):
    assert importlib.util.find_spec("Trade.NativePendingOrders") is not None, "native pending channel observer is not implemented"
    from Trade import NativePendingOrders
    assert callable(getattr(NativePendingOrders, "collect_native_pending_orders", None)), "native pending collector is not implemented"
    assert callable(getattr(NativePendingOrders, "verify_native_pending_orders", None)), "native pending reader is not implemented"
    if source is not None:
        source.monkeypatch.setattr(NativePendingOrders, "utc_now_ms", lambda: source.clock["now"])
    return NativePendingOrders


def test_pending_observer_api_presence_is_explicit():
    api = pending_api()
    assert api.SCHEMA == "chan-native-pending-orders-v1"


def regular_row(venue, instrument, native_id, *, partial=False):
    if venue == "binance":
        return {"avgPrice": "100" if partial else "0", "clientOrderId": "cpOpen"+str(native_id),
                "cumQuote": "2" if partial else "0", "executedQty": "0.02" if partial else "0", "orderId": native_id,
                "origQty": "0.05", "origType": "LIMIT", "price": "100", "reduceOnly": False, "side": "BUY",
                "positionSide": "BOTH", "status": "PARTIALLY_FILLED" if partial else "NEW", "stopPrice": "0",
                "closePosition": False, "symbol": instrument, "time": NOW-9000, "timeInForce": "GTC", "type": "LIMIT",
                "activatePrice": "0", "priceRate": "0", "updateTime": NOW-8000, "workingType": "CONTRACT_PRICE",
                "priceProtect": False, "priceMatch": "NONE", "selfTradePreventionMode": "NONE", "goodTillDate": 0,
                "private_note": "PRIVATE_NOTE_NO_STORE"}
    return {"accFillSz": "2" if partial else "0", "avgPx": "100" if partial else "", "cTime": str(NOW-9000),
            "uTime": str(NOW-8000), "category": "normal", "ccy": "", "clOrdId": "cpOpen"+str(native_id),
            "fee": "-0.001" if partial else "0", "feeCcy": "USDT", "fillPx": "100" if partial else "",
            "fillSz": "2" if partial else "0", "fillTime": str(NOW-8000) if partial else "", "instId": instrument,
            "instType": "SWAP", "lever": "3", "ordId": str(native_id), "ordType": "limit", "pnl": "0",
            "posSide": "net", "px": "100", "rebate": "0", "rebateCcy": "USDT", "side": "buy", "slOrdPx": "",
            "slTriggerPx": "", "state": "partially_filled" if partial else "live", "sz": "5", "tdMode": "cross",
            "tpOrdPx": "", "tpTriggerPx": "", "tradeId": "22" if partial else "", "reduceOnly": "false",
            "algoClOrdId": "", "algoId": "", "attachAlgoOrds": [], "source": "", "tgtCcy": "",
            "private_note": "PRIVATE_NOTE_NO_STORE"}


def algo_row(venue, instrument, native_id, kind="conditional"):
    if venue == "binance":
        return {"algoId": native_id, "clientAlgoId": "cpAlgo"+str(native_id), "algoType": "CONDITIONAL",
                "orderType": "STOP_MARKET", "symbol": instrument, "side": "SELL", "positionSide": "BOTH",
                "timeInForce": "GTC", "quantity": "0.05", "algoStatus": "NEW", "triggerPrice": "90", "price": "0",
                "workingType": "MARK_PRICE", "priceMatch": "NONE", "closePosition": False, "priceProtect": False,
                "reduceOnly": True, "activatePrice": "0", "callbackRate": "0", "createTime": NOW-9000,
                "updateTime": NOW-8000, "triggerTime": 0, "goodTillDate": 0, "actualOrderId": "",
                "actualPrice": "0", "actualQty": "0", "actualType": "", "private_note": "PRIVATE_NOTE_NO_STORE"}
    return {"activePx": "", "actualPx": "", "actualSide": "", "actualSz": "0", "algoClOrdId": "cpAlgo"+str(native_id),
            "algoId": str(native_id), "amendPxOnTriggerType": "", "attachAlgoOrds": [], "cTime": str(NOW-9000),
            "callbackRatio": "", "callbackSpread": "", "ccy": "USDT", "clOrdId": "", "closeFraction": "",
            "failCode": "", "instId": instrument, "instType": "SWAP", "last": "100", "lever": "3", "ordId": "",
            "ordIdList": [], "subAlgoIdList": [], "ordPx": "-1", "ordType": kind, "posSide": "net", "pxLimit": "",
            "pxSpread": "", "pxVar": "", "quickMgnType": "", "reduceOnly": "true", "side": "sell", "slOrdPx": "-1",
            "slTriggerPx": "90", "slTriggerPxType": "mark", "state": "live", "sz": "5", "szLimit": "", "tag": "",
            "tdMode": "cross", "tgtCcy": "", "timeInterval": "", "tpOrdPx": "", "tpTriggerPx": "",
            "tpTriggerPxType": "", "triggerPx": "", "triggerPxType": "", "triggerTime": "0",
            "private_note": "PRIVATE_NOTE_NO_STORE"}


@pytest.fixture(params=[("binance", "testnet"), ("binance", "live"), ("binanceusdm", "testnet"),
                       ("binanceusdm", "live"), ("okx", "testnet"), ("okx", "live")])
def pending_source(request, monkeypatch):
    exchange_id, mode = request.param
    venue = "okx" if exchange_id == "okx" else "binance"
    client, profiles, profile = native_client(monkeypatch, exchange_id, mode)
    markets = [{"exchange": exchange_id, "id": base+"-USDT-SWAP" if venue == "okx" else base+"USDT",
                "symbol": base+"/USDT:USDT", "type": "swap", "base": base, "quote": "USDT", "settle": "USDT",
                "contractSize": size, "precision_mode": ccxt.TICK_SIZE, "precision": {"amount": 1.0, "price": 0.1},
                "limits": {"amount": {"min": 1.0}, "price": {}, "cost": {"min": 5.0}}}
               for base, size in (("TEST", "0.01"), ("ALT", "0.1"))]
    clock, calls = {"now": NOW}, []
    rows = {"regular": [regular_row(venue, markets[0]["id"], 102, partial=True), regular_row(venue, markets[1]["id"], 101)]}
    for i, kind in enumerate(ALGOS if venue == "okx" else ("conditional",)):
        rows[kind] = [algo_row(venue, markets[i % 2]["id"], 201+i, kind)]
    def get(kind, params):
        calls.append((kind, copy.deepcopy(params)))
        clock["now"] += 5
        data = rows[kind]
        if venue == "okx":
            id_key = "ordId" if kind == "regular" else "algoId"
            data = sorted(data, key=lambda row: int(row[id_key]), reverse=True)
            if "after" in params:
                data = [row for row in data if int(row[id_key]) < int(params["after"])]
            data = data[:int(params["limit"])]
        data = copy.deepcopy(data)
        return data if venue == "binance" else {"code": "0", "data": data, "msg": "PRIVATE_RESPONSE_NO_STORE"}
    monkeypatch.setattr(client, "fapiPrivateGetOpenOrders" if venue == "binance" else "privateGetTradeOrdersPending", lambda params: get("regular", params))
    monkeypatch.setattr(client, "fapiPrivateGetOpenAlgoOrders" if venue == "binance" else "privateGetTradeOrdersAlgoPending",
                        lambda params: get("conditional" if venue == "binance" else params["ordType"], params))
    return SimpleNamespace(client=client, mode=mode, venue=venue, markets=markets, rows=rows, calls=calls,
                           clock=clock, profiles=profiles, profile=profile, monkeypatch=monkeypatch)


def test_native_lists_preserve_partial_regular_and_every_declared_algo_channel_without_becoming_admission(pending_source):
    s = pending_source
    api = pending_api(s)
    client, mode, venue, markets, calls, clock, profiles = s.client, s.mode, s.venue, s.markets, s.calls, s.clock, s.profiles
    document = api.collect_native_pending_orders(client, markets, mode=mode)
    assert api.verify_native_pending_orders(document) == document
    payload = document["payload"]
    assert document["schema"] == "chan-native-pending-orders-v1"
    assert payload["economics_complete"] is payload["native_admission_verified"] is False
    assert payload["coverage"] == "observed_regular_and_algo_order_channels"
    assert [row["channel"] for row in payload["channels"]] == ["regular", *(ALGOS if venue == "okx" else ("conditional",))]
    assert payload["source_requests"] == len(calls) == (9 if venue == "okx" else 2)
    assert payload["identity_requests"] == len(profiles) == 2*len(calls)
    assert payload["requests"] == len(calls)+len(profiles)
    assert (payload["started_ms"], payload["finished_ms"]) == (NOW, clock["now"])
    assert len(payload["orders"]) == len(calls)+1 and len(payload["unsupported_orders"]) == len(calls)-1
    regular = {row["instrument_id"]: row for row in payload["orders"] if row["channel"] == "regular"}
    first, second = regular[markets[0]["id"]], regular[markets[1]["id"]]
    assert (first["contracts"], first["filled_contracts"], first["remaining_contracts"]) == ("5", "2", "3")
    assert (first["base_quantity"], first["filled_base_quantity"], first["remaining_base_quantity"]) == ("0.05", "0.02", "0.03")
    assert second["base_quantity"] == ("0.5" if venue == "okx" else "0.05")
    assert second["contracts"] == ("5" if venue == "okx" else "0.5")
    assert all(row["update_ms"] == NOW-8000 for row in payload["orders"] if row["channel"] == "regular")
    assert "PRIVATE_" not in canonical_bytes(document).decode()
    assert all(not ({"symbol", "instId", "instType", "state", "instFamily", "algoId"} & set(params)) for _, params in calls)
    assert "bot_and_copy_channels_unobserved" in payload["disclosures"]


def test_all_declared_channels_are_observed_even_when_every_list_is_empty(pending_source):
    s = pending_source
    api = pending_api(s)
    for rows in s.rows.values():
        rows.clear()
    document = api.collect_native_pending_orders(s.client, s.markets, mode=s.mode)
    assert document["payload"]["orders"] == document["payload"]["unsupported_orders"] == []
    assert len(s.calls) == (9 if s.venue == "okx" else 2)
    assert document["payload"]["native_admission_verified"] is False


@pytest.mark.parametrize("pending_source", [("okx", "testnet"), ("okx", "live")], indirect=True)
@pytest.mark.parametrize("channel", ["regular", "trigger"])
def test_okx_uses_exact_native_id_cursor_until_a_short_page_not_a_unified_or_time_cutoff(pending_source, channel):
    s = pending_source
    api = pending_api(s)
    make = regular_row if channel == "regular" else lambda venue, instrument, key: algo_row(venue, instrument, key, channel)
    s.rows[channel] = [make(s.venue, s.markets[i % 2]["id"], i+1) for i in range(101)]
    document = api.collect_native_pending_orders(s.client, s.markets, mode=s.mode)
    assert len([row for row in document["payload"]["orders"] if row["channel"] == channel]) == 101
    calls = [params for kind, params in s.calls if kind == channel]
    assert len(calls) == 2 and calls[0]["limit"] == 100 and calls[1]["after"] == "2"
    assert not any({"before", "begin", "end", "since", "instType", "instId", "state"} & set(p) for p in calls)
    assert api.verify_native_pending_orders(document) == document


def test_out_of_pool_native_orders_are_retained_and_unmapped_not_dropped(pending_source):
    s = pending_source
    api = pending_api(s)
    foreign = "OTHER-USDT-SWAP" if s.venue == "okx" else "OTHERUSDT"
    s.rows["regular"].append(regular_row(s.venue, foreign, 999))
    document = api.collect_native_pending_orders(s.client, s.markets, mode=s.mode)
    found = [row for row in document["payload"]["orders"] if row["instrument_id"] == foreign]
    assert len(found) == 1 and found[0]["contracts"] is found[0]["base_quantity"] is None
    assert any(row["native_order_id"] == "999" and row["reason"] == "unmapped_native_market" for row in document["payload"]["unsupported_orders"])


@pytest.mark.parametrize("pending_source", [("binance", "testnet"), ("binanceusdm", "live")], indirect=True)
@pytest.mark.parametrize("channel", ["regular", "conditional"])
def test_binance_ids_are_scoped_to_symbol_for_both_regular_and_algo_orders(pending_source, channel):
    s = pending_source
    api = pending_api(s)
    first = copy.deepcopy(s.rows[channel][0])
    second = copy.deepcopy(first)
    second["symbol"] = s.markets[1]["id"]
    second["clientOrderId" if channel == "regular" else "clientAlgoId"] = "cpOtherSymbol"
    s.rows[channel] = [first, second]
    document = api.collect_native_pending_orders(s.client, s.markets, mode=s.mode)
    found = [row for row in document["payload"]["orders"] if row["channel"] == channel]
    assert len(found) == 2 and len({row["instrument_id"] for row in found}) == 2
    assert len({row["native_order_id"] for row in found}) == 1


@pytest.mark.parametrize("damage", ["nan_quantity", "negative_quantity", "filled_exceeds", "missing_quantity", "future_clock", "duplicate", "bad_reduce_only"])
def test_invalid_native_regular_rows_never_publish_a_pending_observation(pending_source, damage):
    s = pending_source
    api = pending_api(s)
    row = s.rows["regular"][0]
    qty, filled, clock = ("origQty", "executedQty", "updateTime") if s.venue == "binance" else ("sz", "accFillSz", "uTime")
    if damage == "nan_quantity":
        row[qty] = "NaN"
    elif damage == "negative_quantity":
        row[qty] = "-1"
    elif damage == "filled_exceeds":
        row[filled] = "100"
    elif damage == "missing_quantity":
        del row[qty]
    elif damage == "future_clock":
        row[clock] = NOW+10000 if s.venue == "binance" else str(NOW+10000)
    elif damage == "duplicate":
        s.rows["regular"].append(copy.deepcopy(row))
    else:
        row["reduceOnly"] = "false" if s.venue == "binance" else False
    with pytest.raises(CChanException):
        api.collect_native_pending_orders(s.client, s.markets, mode=s.mode)


def test_a_boolean_empty_client_id_is_not_silently_relabelled_as_no_owner(pending_source):
    s = pending_source
    api = pending_api(s)
    s.rows["regular"][0]["clientOrderId" if s.venue == "binance" else "clOrdId"] = False
    with pytest.raises(CChanException):
        api.collect_native_pending_orders(s.client, s.markets, mode=s.mode)


@pytest.mark.parametrize("damage", ["attached_trigger", "native_parent", "price_selection"])
def test_regular_rows_with_complex_native_terms_are_disclosed_not_silently_treated_as_plain(pending_source, damage):
    s = pending_source
    api = pending_api(s)
    row = s.rows["regular"][0]
    if s.venue == "binance":
        if damage == "attached_trigger":
            row["closePosition"] = True
        elif damage == "native_parent":
            row["origType"] = "STOP"
        else:
            row["priceMatch"] = "QUEUE_5"
    else:
        if damage == "attached_trigger":
            row["slTriggerPx"] = "90"
        elif damage == "native_parent":
            row["algoId"] = "4000"
        else:
            row["category"] = "twap"  # Native forced-repayment category, not a strategy tag.
    document = api.collect_native_pending_orders(s.client, s.markets, mode=s.mode)
    assert any(issue["native_order_id"] == "102" and issue["reason"] == "complex_native_order_terms"
               for issue in document["payload"]["unsupported_orders"])


def test_algo_response_must_match_the_declared_native_family(pending_source):
    s = pending_source
    api = pending_api(s)
    s.rows["conditional"][0]["algoType" if s.venue == "binance" else "ordType"] = "OTHER"
    with pytest.raises(CChanException):
        api.collect_native_pending_orders(s.client, s.markets, mode=s.mode)


def test_close_all_algo_quantity_is_preserved_as_unproven_not_zero_remaining_risk(pending_source):
    s = pending_source
    api = pending_api(s)
    raw = s.rows["conditional"][0]
    if s.venue == "binance":
        raw.update(closePosition=True, quantity="0")
    else:
        raw.update(closeFraction="1", sz="")
        raw["ordIdList"] = ["900"]
        raw["subAlgoIdList"] = ["901"]
        raw["attachAlgoOrds"] = [{"attachAlgoClOrdId": "cpAttached", "tpTriggerPx": "120", "tpOrdPx": "-1"}]
    document = api.collect_native_pending_orders(s.client, s.markets, mode=s.mode)
    row = next(row for row in document["payload"]["orders"] if row["channel"] == "conditional")
    assert row["contracts"] is row["remaining_contracts"] is row["base_quantity"] is None
    if s.venue == "okx":
        assert row["raw"]["closeFraction"] == "1" and row["raw"]["ordIdList"] == ["900"]
        assert row["raw"]["subAlgoIdList"] == ["901"] and row["raw"]["attachAlgoOrds"][0]["tpOrdPx"] == "-1"
    assert any(issue["reason"] == "native_algo_ownership_unproven" and issue["native_order_id"] == "201"
               for issue in document["payload"]["unsupported_orders"])


@pytest.mark.parametrize("damage", ["zero_id", "missing_update", "backwards_update", "empty_partial", "filled_new", "ambiguous_terms"])
def test_regular_order_cannot_hide_missing_identity_time_or_contradictory_native_state(pending_source, damage):
    s = pending_source
    api = pending_api(s)
    row = s.rows["regular"][0]
    key, updated, filled, state = (("orderId", "updateTime", "executedQty", "status") if s.venue == "binance"
                                  else ("ordId", "uTime", "accFillSz", "state"))
    if damage == "zero_id":
        row[key] = 0 if s.venue == "binance" else "0"
    elif damage == "missing_update":
        del row[updated]
    elif damage == "backwards_update":
        row[updated] = NOW-10000 if s.venue == "binance" else str(NOW-10000)
    elif damage == "empty_partial":
        row[filled] = "0"
    elif damage == "filled_new":
        row[state] = "NEW" if s.venue == "binance" else "live"
    else:
        if s.venue == "binance":
            row["closePosition"] = "false"
        else:
            row["tdMode"] = ""
    with pytest.raises(CChanException):
        api.collect_native_pending_orders(s.client, s.markets, mode=s.mode)


@pytest.mark.parametrize("damage", ["route", "identity", "sdk", "metadata", "backwards_clock"])
def test_drift_during_a_real_native_read_never_publishes_or_retries(pending_source, damage):
    s = pending_source
    api = pending_api(s)
    name = "fapiPrivateGetOpenOrders" if s.venue == "binance" else "privateGetTradeOrdersPending"
    get = getattr(s.client, name)
    def changed(params):
        value = get(params)
        if damage == "route":
            s.client.urls["api"]["fapiPrivate" if s.venue == "binance" else "rest"] = "https://wrong.example/private"
        elif damage == "identity":
            if s.venue == "binance":
                for row in s.profile:
                    row["accountAlias"] = "OTHER_ACCOUNT"
            else:
                s.profile["data"][0]["uid"] = "88888888"
        elif damage == "sdk":
            s.monkeypatch.setattr(ccxt, "__version__", "0.0.test")
        elif damage == "metadata":
            s.markets[0]["contractSize"] = "9"
        else:
            s.clock["now"] -= 1000
        return value
    s.monkeypatch.setattr(s.client, name, changed)
    with pytest.raises(CChanException):
        api.collect_native_pending_orders(s.client, s.markets, mode=s.mode)
    assert len([call for call in s.calls if call[0] == "regular"]) == 1


@pytest.mark.parametrize("pending_source", [("okx", "testnet")], indirect=True)
def test_128_call_budget_counts_typed_profiles_and_never_returns_partial_coverage(pending_source):
    s = pending_source
    api = pending_api(s)
    s.rows["regular"] = [regular_row("okx", s.markets[i % 2]["id"], i+1) for i in range(4200)]
    with pytest.raises(CChanException):
        api.collect_native_pending_orders(s.client, s.markets, mode=s.mode)
    assert len(s.calls) == 42 and len(s.profiles) == 84
    assert len(s.calls)+len(s.profiles) == 126 < 128
    assert all(kind == "regular" for kind, _ in s.calls)


@pytest.mark.parametrize("pending_source", [("okx", "testnet")], indirect=True)
def test_a_repeated_full_page_is_a_pagination_failure_not_a_deduplicated_pass(pending_source):
    s = pending_source
    api = pending_api(s)
    s.rows["regular"] = [regular_row("okx", s.markets[i % 2]["id"], i+1) for i in range(100)]
    get = s.client.privateGetTradeOrdersPending
    s.monkeypatch.setattr(s.client, "privateGetTradeOrdersPending", lambda params: get({k: v for k, v in params.items() if k != "after"}))
    with pytest.raises(CChanException):
        api.collect_native_pending_orders(s.client, s.markets, mode=s.mode)
    assert len(s.calls) == 2


@pytest.mark.parametrize("damage", ["derived_quantity", "market_size", "request_filter", "missing_channel", "missing_disclosure",
                                   "unsupported_hidden", "profile_count", "implementation", "sdk_class", "bool_clock", "mode"])
def test_resealed_inconsistent_pending_documents_are_not_accepted(pending_source, damage):
    s = pending_source
    api = pending_api(s)
    document = api.collect_native_pending_orders(s.client, s.markets, mode=s.mode)
    payload = document["payload"]
    if damage == "derived_quantity":
        payload["orders"][0]["base_quantity"] = "999"
    elif damage == "market_size":
        payload["markets"][0]["contractSize"] = "9"
    elif damage == "request_filter":
        payload["channels"][0]["pages"][0]["params"]["symbol"] = "TESTUSDT"
    elif damage == "missing_channel":
        payload["channels"].pop()
    elif damage == "missing_disclosure":
        payload["disclosures"].remove("bot_and_copy_channels_unobserved")
    elif damage == "unsupported_hidden":
        payload["unsupported_orders"] = []
    elif damage == "profile_count":
        payload["requests"] = payload["source_requests"]
    elif damage == "implementation":
        payload["implementation_sha256"]["Trade/NativePendingOrders.py"] = "0"*64
    elif damage == "sdk_class":
        payload["sdk"]["exchange_class"] = "ccxt.other.other"
    elif damage == "bool_clock":
        payload["channels"][0]["pages"][0]["started_ms"] = True
    else:
        payload["mode"] = "live" if s.mode == "testnet" else "testnet"
    document["payload_sha256"] = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    with pytest.raises(CChanException):
        api.verify_native_pending_orders(document)


def test_source_failure_is_redacted_and_is_not_retried_or_switched_to_unified_orders(pending_source):
    s = pending_source
    api = pending_api(s)
    calls = []
    def bad(params):
        calls.append(params)
        raise ccxt.ExchangeError("PRIVATE_KEY_MUST_NOT_ESCAPE")
    s.monkeypatch.setattr(s.client, "fapiPrivateGetOpenOrders" if s.venue == "binance" else "privateGetTradeOrdersPending", bad)
    with pytest.raises(CChanException) as error:
        api.collect_native_pending_orders(s.client, s.markets, mode=s.mode)
    assert calls == [{} if s.venue == "binance" else {"limit": 100}]
    assert "PRIVATE_KEY_MUST_NOT_ESCAPE" not in "".join(traceback.format_exception(error.value))


def test_stored_pending_reader_needs_no_sdk_models_yaml_gui_or_private_io(pending_source):
    s = pending_source
    api = pending_api(s)
    document = api.collect_native_pending_orders(s.client, s.markets, mode=s.mode)
    code = """
import importlib.abc, json, sys
blocked = {'ccxt','xgboost','lightgbm','sklearn','optuna','yaml','PyQt6','minio','qcloud_cos'}
attempted = []
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            attempted.append(fullname)
            raise ModuleNotFoundError('optional dependency intentionally absent')
sys.meta_path.insert(0, BlockOptional())
import Trade.NativePendingOrders as api
value = json.loads(sys.stdin.buffer.read())
api.utc_now_ms = lambda: value['now']
assert api.verify_native_pending_orders(value['document']) == value['document']
assert not attempted, attempted
assert not any(key.split('.')[0] in blocked for key in sys.modules)
print('stored pending reader without optional dependencies PASS')
"""
    result = subprocess.run([sys.executable, "-c", code], input=canonical_bytes({"document": document, "now": s.clock["now"]}),
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.strip() == b"stored pending reader without optional dependencies PASS" and result.stderr == b""
