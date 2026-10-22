"""Native regular/algo pending observations; never absence or admission proof.

All declared channels are read without an instrument filter. Other bot/copy/
account domains and native margin reservations are explicitly not certified.
No optional SDK, configuration, DB or order engine is loaded at import.
"""
import hashlib
import json
import re
from decimal import localcontext
from pathlib import Path

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountIdentity import _environment, observe_account_context, verify_account_context
from .AccountSources import _raw
from .ExecutionFacts import MAX_REQUESTS, _MONEY, _id, _number, _string, _time
from .NativeMarketEvidence import _markets, _sdk


SCHEMA = "chan-native-pending-orders-v1"
_ALGOS = ("conditional", "oco", "chase", "trigger", "move_order_stop", "iceberg", "twap", "smart_iceberg")
_ROOT = Path(__file__).resolve().parents[1]
_SOURCES = ("Trade/NativePendingOrders.py", "Trade/NativeMarketEvidence.py", "Trade/AccountIdentity.py",
            "Trade/AccountSources.py", "Trade/ExecutionFacts.py", "CustomBuySellPoint/Decision.py", "Common/KLineTime.py")
_RAW = {
    "binance": ("avgPrice", "clientOrderId", "cumQuote", "executedQty", "orderId", "origQty", "origType", "price",
                "reduceOnly", "side", "positionSide", "status", "stopPrice", "closePosition", "symbol", "time",
                "timeInForce", "type", "activatePrice", "priceRate", "updateTime", "workingType", "priceProtect",
                "priceMatch", "selfTradePreventionMode", "goodTillDate", "algoId", "clientAlgoId", "algoType",
                "orderType", "quantity", "algoStatus", "triggerPrice", "callbackRate", "createTime", "triggerTime",
                "actualOrderId", "actualPrice", "actualQty", "actualType"),
    "okx": ("accFillSz", "avgPx", "cTime", "uTime", "category", "ccy", "clOrdId", "fee", "feeCcy", "fillPx",
            "fillSz", "fillTime", "instId", "instType", "lever", "ordId", "ordType", "pnl", "posSide", "px", "rebate",
            "rebateCcy", "side", "slOrdPx", "slTriggerPx", "state", "sz", "tdMode", "tpOrdPx", "tpTriggerPx", "tradeId",
            "reduceOnly", "algoClOrdId", "algoId", "source", "tgtCcy", "activePx", "activePxType", "actualPx",
            "actualSide", "actualSz", "amendPxOnTriggerType", "callbackRatio", "callbackSpread", "closeFraction",
            "failCode", "last", "ordPx", "pxLimit", "pxSpread", "pxVar", "quickMgnType", "slTriggerPxType",
            "szLimit", "timeInterval", "tpTriggerPxType", "triggerPx", "triggerPxType", "triggerTime",
            "advanceOrdType", "isTpLimit", "cancelSource", "isTradeBorrowMode"),
}
_ATTACHMENT = ("attachAlgoId", "attachAlgoClOrdId", "tpOrdKind", "tpTriggerPx", "tpTriggerPxType", "tpOrdPx",
               "slTriggerPx", "slTriggerPxType", "slOrdPx", "sz", "amendPxOnTriggerType", "tpOrdId", "slOrdId")
_NUMBERS = {"avgPrice", "cumQuote", "executedQty", "origQty", "price", "stopPrice", "activatePrice", "priceRate",
            "quantity", "triggerPrice", "callbackRate", "actualPrice", "actualQty", "accFillSz", "avgPx", "fee",
            "fillPx", "fillSz", "lever", "pnl", "px", "rebate", "slOrdPx", "slTriggerPx", "sz", "tpOrdPx",
            "tpTriggerPx", "activePx", "actualPx", "actualSz", "callbackRatio", "callbackSpread", "closeFraction",
            "last", "ordPx", "pxLimit", "pxSpread", "pxVar", "szLimit", "timeInterval", "triggerPx"}


def _fail():
    raise CChanException("原生未决单通道/分页/身份/单位不完整；不是预占或账户准入证明", ErrCode.TRADE_UNLOCK_FAIL) from None


def _sha(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _implementation():
    return {name: hashlib.sha256((_ROOT/name).read_bytes()).hexdigest() for name in _SOURCES}


def _channels(venue):
    return ("regular", *(_ALGOS if venue == "okx" else ("conditional",)))


def _request(venue, channel, cursor=None):
    if venue == "binance":
        return (("/fapi/v1/openOrders", "fapiPrivateGetOpenOrders", {}) if channel == "regular"
                else ("/fapi/v1/openAlgoOrders", "fapiPrivateGetOpenAlgoOrders", {}))
    params = {"limit": 100}
    if channel != "regular":
        params["ordType"] = channel
    if cursor is not None:
        params["after"] = cursor
    return (("/api/v5/trade/orders-pending", "privateGetTradeOrdersPending", params) if channel == "regular"
            else ("/api/v5/trade/orders-algo-pending", "privateGetTradeOrdersAlgoPending", params))


def _disclosures():
    return ["observed_channels_only_not_atomic_absence", "bot_and_copy_channels_unobserved",
            "native_margin_reservations_unobserved", "algo_ownership_and_conditional_quantity_unproven",
            "sdk_internal_retries_unverified"]


def _text(value, *, empty=False):
    if type(value) is not str or len(value) > 128 or value.strip() != value or (not empty and not value):
        _fail()
    return value


def _raw_order(row, venue):
    result = _raw(row, _RAW[venue])
    for key, value in result.items():
        if type(value) is str:
            _text(value, empty=True)
        if key in _NUMBERS and value != "":
            _number(value)
    if "attachAlgoOrds" in row:
        if type(row["attachAlgoOrds"]) is not list:
            _fail()
        result["attachAlgoOrds"] = [_raw(item, _ATTACHMENT) for item in row["attachAlgoOrds"]]
        for item in result["attachAlgoOrds"]:
            for key, value in item.items():
                if type(value) is str:
                    _text(value, empty=True)
                if key in _NUMBERS and value != "":
                    _number(value)
    for field in ("ordIdList", "subAlgoIdList"):
        if field in row:
            if type(row[field]) is not list:
                _fail()
            result[field] = [_id(key) for key in row[field]]
    return result


def _order(row, venue, channel, markets):
    raw = _raw_order(row, venue)
    regular = channel == "regular"
    instrument = _text(raw["symbol" if venue == "binance" else "instId"])
    order_id = _id(raw[("orderId" if regular else "algoId") if venue == "binance" else ("ordId" if regular else "algoId")])
    if int(order_id) <= 0:
        _fail()
    client_key = ("clientOrderId" if regular else "clientAlgoId") if venue == "binance" else ("clOrdId" if regular else "algoClOrdId")
    client = raw.get(client_key)
    if client is not None:
        pattern = r"[.A-Za-z0-9_:/-]{1,36}" if venue == "binance" else r"[A-Za-z0-9]{1,32}"
        if type(client) is not str or (client and re.fullmatch(pattern, client) is None):
            _fail()
        client = client or None
    created = _time(raw[("time" if regular else "createTime") if venue == "binance" else "cTime"])
    updated = None if "updateTime" not in raw and "uTime" not in raw else _time(raw["updateTime" if venue == "binance" else "uTime"])
    if (regular and updated is None) or (updated is not None and updated < created):
        _fail()
    side, leg = raw["side"], raw["positionSide" if venue == "binance" else "posSide"]
    if side not in ({"BUY", "SELL"} if venue == "binance" else {"buy", "sell"}) or leg not in ({"BOTH", "LONG", "SHORT"} if venue == "binance" else {"net", "long", "short"}):
        _fail()
    status = _text(raw[("status" if regular else "algoStatus") if venue == "binance" else "state"])
    native_type = _text(raw[("type" if regular else "orderType") if venue == "binance" else "ordType"])
    if regular and status not in ({"NEW", "PARTIALLY_FILLED"} if venue == "binance" else {"live", "partially_filled"}):
        _fail()
    if not regular and (raw.get("algoType") != "CONDITIONAL" if venue == "binance" else native_type != channel):
        _fail()
    if venue == "binance":
        if type(raw["reduceOnly"]) is not bool or type(raw.get("closePosition")) is not bool:
            _fail()
        reduce_only = raw["reduceOnly"]
    else:
        if (type(raw["reduceOnly"]) is not str or raw["reduceOnly"] not in {"true", "false"}
                or raw.get("tdMode") not in {"cross", "isolated", "cash", "spot_isolated"}
                or (raw.get("instType") == "SWAP" and raw["tdMode"] not in {"cross", "isolated"})):
            _fail()
        reduce_only = raw["reduceOnly"] == "true"
    market = next((market for market in markets if market["id"] == instrument), None)
    if venue == "okx" and raw.get("instType") != "SWAP":
        market = None  # Retain the foreign domain without guessing its units.
    quantities = {key: None for key in ("contracts", "filled_contracts", "remaining_contracts",
                                       "base_quantity", "filled_base_quantity", "remaining_base_quantity")}
    if regular:
        quantity = _number(raw["origQty" if venue == "binance" else "sz"], positive=True)
        filled = _number(raw["executedQty" if venue == "binance" else "accFillSz"])
        if not 0 <= filled < quantity or (filled > 0) != (status in {"PARTIALLY_FILLED", "partially_filled"}):
            _fail()
        if market is not None:
            size = _number(market["contractSize"], positive=True)
            native = (quantity, filled, quantity-filled)
            base = native if venue == "binance" else tuple(value*size for value in native)
            contracts = tuple(value/size for value in native) if venue == "binance" else native
            quantities = dict(zip(quantities, [_string(value) for value in (*contracts, *base)]))
    complex_terms = bool(raw.get("attachAlgoOrds"))
    if regular and venue == "binance":
        complex_terms |= raw.get("closePosition") is True or raw.get("origType") != native_type or raw.get("priceMatch") not in {"NONE", ""}
    elif regular:
        complex_terms |= bool(raw.get("algoId") or raw.get("algoClOrdId") or raw.get("slTriggerPx") or raw.get("tpTriggerPx")) or raw.get("category") != "normal"
    plain_types = {"LIMIT", "MARKET"} if venue == "binance" else {"limit", "market", "post_only", "fok", "ioc", "optimal_limit_ioc"}
    reason = ("unmapped_native_market" if market is None else "native_algo_ownership_unproven" if not regular else
              "complex_native_order_terms" if complex_terms or native_type not in plain_types else None)
    value = {"channel": channel, "instrument_id": instrument, "native_order_id": order_id, "client_order_id": client,
             "native_type": native_type, "native_status": status, "side": side, "position_side": leg,
             "margin_mode": raw.get("tdMode"), "reduce_only": reduce_only, "created_ms": created, "update_ms": updated,
             **quantities, "raw": raw}
    issue = None if reason is None else {"channel": channel, "instrument_id": instrument, "native_order_id": order_id, "reason": reason}
    return value, issue


def _derive(channels, venue, markets, started, finished):
    if type(channels) is not list or [row["channel"] for row in channels] != list(_channels(venue)):
        _fail()
    orders, issues, seen, previous, requests = [], [], set(), started, 0
    for channel in channels:
        if set(channel) != {"channel", "pages"} or type(channel["pages"]) is not list or not channel["pages"]:
            _fail()
        kind, cursor = channel["channel"], None
        for index, page in enumerate(channel["pages"]):
            endpoint, method, params = _request(venue, kind, cursor)
            if (set(page) != {"endpoint", "method", "params", "started_ms", "request_started_ms", "request_finished_ms", "finished_ms", "raw"}
                    or (page["endpoint"], page["method"], page["params"]) != (endpoint, method, params)
                    or any(type(page[key]) is not int for key in ("started_ms", "request_started_ms", "request_finished_ms", "finished_ms"))
                    or not previous <= page["started_ms"] <= page["request_started_ms"] <= page["request_finished_ms"] <= page["finished_ms"] <= finished
                    or type(page["raw"]) is not list or (venue == "okx" and len(page["raw"]) > 100)):
                _fail()
            requests += 3  # Both typed profile reads count as real SDK calls.
            if requests > MAX_REQUESTS:
                _fail()
            previous = page["finished_ms"]
            ids = []
            for raw in page["raw"]:
                order, issue = _order(raw, venue, kind, markets)
                if (canonical_bytes(raw) != canonical_bytes(order["raw"])
                        or any(at is not None and at > page["request_finished_ms"] for at in (order["created_ms"], order["update_ms"]))):
                    _fail()
                # Binance both ID sequences are per symbol, not account-wide.
                key = ("regular" if kind == "regular" else "algo",
                       order["instrument_id"] if venue == "binance" else None, int(order["native_order_id"]))
                if key in seen:
                    _fail()
                seen.add(key)
                ids.append(int(order["native_order_id"]))
                orders.append(order)
                if issue:
                    issues.append(issue)
            if venue == "binance":
                if len(channel["pages"]) != 1:
                    _fail()
            else:
                if (ids != sorted(set(ids), reverse=True) or (cursor is not None and any(key >= int(cursor) for key in ids))
                        or (len(ids) < 100) != (index == len(channel["pages"])-1)):
                    _fail()
                cursor = str(ids[-1]) if ids else None
    return sorted(orders, key=lambda row: (row["channel"], row["instrument_id"], int(row["native_order_id"]))), sorted(issues, key=canonical_bytes), requests


def verify_native_pending_orders(document):
    """Reconstruct stored content without CCXT; no source-authenticity claim."""
    try:
        payload = document["payload"]
        keys = {"exchange_id", "venue", "mode", "account_context", "sdk", "implementation_sha256", "started_ms", "finished_ms",
                "requests", "source_requests", "identity_requests", "markets", "coverage", "economics_complete",
                "native_admission_verified", "channels", "orders", "unsupported_orders", "disclosures"}
        exchange_id = payload["exchange_id"]
        venue = "okx" if exchange_id == "okx" else "binance"
        verify_account_context(payload["account_context"])
        if (set(document) != {"schema", "payload", "payload_sha256"} or document["schema"] != SCHEMA
                or document["payload_sha256"] != _sha(payload) or set(payload) != keys
                or exchange_id not in {"binance", "binanceusdm", "okx"} or payload["venue"] != venue
                or payload["account_context"]["venue"] != venue or payload["account_context"]["mode"] != payload["mode"]
                or payload["coverage"] != "observed_regular_and_algo_order_channels"
                or payload["economics_complete"] is not False or payload["native_admission_verified"] is not False
                or payload["disclosures"] != _disclosures() or payload["implementation_sha256"] != _implementation()
                or any(type(payload[key]) is not int for key in ("started_ms", "finished_ms", "requests", "source_requests", "identity_requests"))
                or not 0 <= payload["started_ms"] <= payload["finished_ms"] <= utc_now_ms()):
            _fail()
        sdk = payload["sdk"]
        if (set(sdk) != {"name", "version", "exchange_class", "source_sha256"} or sdk["name"] != "ccxt"
                or type(sdk["version"]) is not str or re.fullmatch(r"[0-9][A-Za-z0-9.+_-]{0,63}", sdk["version"]) is None
                or sdk["exchange_class"] != "ccxt."+exchange_id+"."+exchange_id
                or type(sdk["source_sha256"]) is not dict or not sdk["source_sha256"]
                or any(type(key) is not str or re.fullmatch(r"ccxt\.[A-Za-z0-9_.]+", key) is None
                       or type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None for key, value in sdk["source_sha256"].items())):
            _fail()
        with localcontext(_MONEY):
            markets = _markets(payload["markets"], exchange_id)
            orders, issues, requests = _derive(payload["channels"], venue, markets, payload["started_ms"], payload["finished_ms"])
        if (canonical_bytes(markets) != canonical_bytes(payload["markets"]) or canonical_bytes(orders) != canonical_bytes(payload["orders"])
                or canonical_bytes(issues) != canonical_bytes(payload["unsupported_orders"])
                or (payload["requests"], payload["source_requests"], payload["identity_requests"]) != (requests, requests//3, requests//3*2)):
            _fail()
        return document
    except Exception:
        _fail()


def collect_native_pending_orders(exchange, markets, *, mode):
    """Read each declared native channel outside DB locks; never submit orders."""
    try:
        import ccxt
        started = utc_now_ms()
        original = canonical_bytes(markets)
        exchange_id = exchange.id
        if exchange_id not in {"binance", "binanceusdm", "okx"} or mode not in {"live", "testnet"}:
            _fail()
        venue = "okx" if exchange_id == "okx" else "binance"
        with localcontext(_MONEY):
            units = _markets(markets, exchange_id)
        reference = getattr(ccxt, exchange_id)()
        if mode == "testnet":
            reference.set_sandbox_mode(True)
        environment = _environment(exchange, reference, venue, mode)
        sdk, implementation, context = _sdk(exchange, ccxt), _implementation(), None
        channels, requests = [], 0
        def current():
            if (exchange.id != exchange_id or type(exchange) is not type(reference)
                    or _environment(exchange, reference, venue, mode) != environment or _sdk(exchange, ccxt) != sdk):
                _fail()
        for kind in _channels(venue):
            pages, cursor = [], None
            while True:
                if requests+3 > MAX_REQUESTS:
                    _fail()
                begin = utc_now_ms()
                current()
                before = observe_account_context(exchange, mode)
                current()
                if context is None:
                    context = before
                if canonical_bytes(before) != canonical_bytes(context):
                    _fail()
                endpoint, method, params = _request(venue, kind, cursor)
                request_start = utc_now_ms()
                wire = getattr(exchange, method)(dict(params))
                current()
                request_end = utc_now_ms()
                if venue == "okx":
                    if type(wire) is not dict or wire.get("code") != "0":
                        _fail()
                    wire = wire["data"]
                if type(wire) is not list:
                    _fail()
                with localcontext(_MONEY):
                    raw = [_raw_order(row, venue) for row in wire]
                    for row in raw:
                        value, _ = _order(row, venue, kind, units)
                        if any(at is not None and at > request_end for at in (value["created_ms"], value["update_ms"])):
                            _fail()
                if canonical_bytes(observe_account_context(exchange, mode)) != canonical_bytes(context):
                    _fail()
                current()
                page = {"endpoint": endpoint, "method": method, "params": params, "started_ms": begin,
                        "request_started_ms": request_start, "request_finished_ms": request_end, "finished_ms": utc_now_ms(), "raw": raw}
                pages.append(page)
                requests += 3
                if venue == "binance" or len(raw) < 100:
                    break
                if len(raw) != 100:
                    _fail()
                field = "ordId" if kind == "regular" else "algoId"
                ids = [int(_id(row[field])) for row in raw]
                if ids != sorted(set(ids), reverse=True) or (cursor is not None and any(key >= int(cursor) for key in ids)):
                    _fail()
                cursor = str(ids[-1])
            channels.append({"channel": kind, "pages": pages})
        if implementation != _implementation() or canonical_bytes(markets) != original:
            _fail()
        current()
        finished = utc_now_ms()
        with localcontext(_MONEY):
            orders, issues, _ = _derive(channels, venue, units, started, finished)
        payload = {"exchange_id": exchange_id, "venue": venue, "mode": mode, "account_context": context, "sdk": sdk,
                   "implementation_sha256": implementation, "started_ms": started, "finished_ms": finished,
                   "requests": requests, "source_requests": requests//3, "identity_requests": requests//3*2, "markets": units,
                   "coverage": "observed_regular_and_algo_order_channels", "economics_complete": False,
                   "native_admission_verified": False, "channels": channels, "orders": orders, "unsupported_orders": issues,
                   "disclosures": _disclosures()}
        return verify_native_pending_orders(json.loads(canonical_bytes({"schema": SCHEMA, "payload": payload, "payload_sha256": _sha(payload)})))
    except Exception:
        _fail()
