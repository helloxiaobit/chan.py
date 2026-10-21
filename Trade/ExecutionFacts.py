"""Read-only native execution facts; never a balance/absence certification.

Native decimal strings, not rounded order averages, are the economic source.
The caller namespace is not proof of a server account UID. No order is submitted.
"""
import hashlib
import re
from decimal import Context, DecimalException, Inexact, localcontext

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes


SCHEMA = "chan-execution-scan-v1"
MAX_REQUESTS = 128
WINDOW_MS = 6*86_400_000
MAX_AGE_MS = 90*86_400_000
_MONEY = Context(prec=50, Emax=100, Emin=-100)
_MONEY.traps[Inexact] = True
_MARKET_KEYS = ("exchange", "id", "symbol", "type", "base", "quote", "settle", "contractSize")
_TRADE_KEYS = {
    "binance": ("symbol", "id", "orderId", "side", "positionSide", "time", "price", "qty",
                "realizedPnl", "commission", "commissionAsset", "marginAsset", "maker", "buyer"),
    "okx": ("instId", "instType", "tradeId", "billId", "ordId", "clOrdId", "side", "posSide", "ts",
            "fillTime", "fillPx", "fillSz", "fillPnl", "fee", "feeCcy", "execType"),
}
_FUNDING_KEYS = {
    "binance": ("symbol", "incomeType", "tranId", "time", "income", "asset"),
    "okx": ("instId", "instType", "billId", "type", "subType", "ts", "pnl", "balChg", "posBalChg",
            "ccy", "mgnMode", "fee"),
}


def _fail():
    raise CChanException("逐笔经济来源缺失/冲突/超出传输边界；不能猜测费用或重新下单", ErrCode.LIST_ORDER_FAIL)


def _id(value, *, signed=False):
    if type(value) not in (str, int) or not re.fullmatch(r"-?[0-9]{1,40}" if signed else r"[0-9]{1,40}", str(value)):
        _fail()
    return str(value)


def _time(value):
    value = int(_id(value))
    if not 0 <= value < 2**63:
        _fail()
    return value


def _number(value, *, positive=False):
    if type(value) not in (str, int) or len(str(value)) > 160 or str(value).strip() != str(value) or value == "":
        _fail()
    number = _MONEY.create_decimal(str(value))
    if not number.is_finite() or (positive and number <= 0):
        _fail()
    return number


def _string(number):
    if not number:
        return "0"
    raw = format(number, "f")
    return raw.rstrip("0").rstrip(".") if "." in raw else raw


def _currency(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9]{1,24}", value):
        _fail()
    return value


def _market(value):
    market = {key: value[key] for key in _MARKET_KEYS}
    if (market["exchange"] not in {"binance", "binanceusdm", "okx"} or market["type"] != "swap"
            or market["quote"] != "USDT" or market["settle"] != "USDT"
            or any(not isinstance(market[k], str) or not market[k] for k in ("id", "symbol", "base"))):
        _fail()
    _number(market["contractSize"], positive=True)
    return market


def _normalize(row, market, venue, kind):
    keys = _TRADE_KEYS[venue] if kind == "trade" else _FUNDING_KEYS[venue]
    raw = {key: row[key] for key in keys if key in row}
    if any(type(value) not in (str, int, bool) for value in raw.values()):
        _fail()
    if raw["symbol" if venue == "binance" else "instId"] != market["id"]:
        _fail()
    if venue == "okx" and raw["instType"] != "SWAP":
        _fail()
    source_ms = _time(raw["time" if venue == "binance" else "ts"])
    source_id = _id(raw[("id" if kind == "trade" else "tranId") if venue == "binance" else "billId"])
    result = {"kind": kind, "source_id": source_id, "source_ms": source_ms, "raw": raw}
    if kind == "funding":
        fee, wallet, position = None, None, None
        if venue == "binance":
            if raw["incomeType"] != "FUNDING_FEE":
                _fail()
            amount, currency = _number(raw["income"]), _currency(raw["asset"])
        else:
            amount, currency = _number(raw["pnl"]), _currency(raw["ccy"])
            if (raw["type"] != "8" or raw["subType"] not in {"173", "174"}
                    or (amount < 0 and raw["subType"] != "173") or (amount > 0 and raw["subType"] != "174")):
                _fail()
            # Preserve both wallets without assuming they can be summed or that
            # a missing isolated-position leg can be allocated by net quantity.
            wallet, position = _number(raw["balChg"]), _number(raw["posBalChg"])
            fee = _number(raw["fee"])
        return {**result, "timestamp_ms": source_ms, "position_side": None,
                "cash_delta": _string(amount), "currency": currency,
                "fee_cash_delta": None if fee is None else _string(fee),
                "wallet_cash_delta": None if wallet is None else _string(wallet),
                "position_cash_delta": None if position is None else _string(position)}
    if venue == "binance":
        timestamp, side, leg = source_ms, raw["side"].lower(), raw["positionSide"]
        if (any(key in raw and type(raw[key]) is not bool for key in ("maker", "buyer"))
                or ("buyer" in raw and raw["buyer"] is not (side == "buy"))
                or ("marginAsset" in raw and raw["marginAsset"] != market["settle"])):
            _fail()
        contracts, price = _number(raw["qty"], positive=True), _number(raw["price"], positive=True)
        fee, pnl, currency = -_number(raw["commission"]), _number(raw["realizedPnl"]), _currency(raw["commissionAsset"])
        order = _id(raw["orderId"])
        trade_id = _id(raw["id"])
        client = None  # userTrades does not echo the client id; never invent it.
        clock = "time"
    else:
        clock = "fillTime" if "fillTime" in raw else "missing_fill_time"
        timestamp, side = _time(raw[clock]) if clock == "fillTime" else None, raw["side"]
        leg = {"net": "BOTH", "long": "LONG", "short": "SHORT"}.get(raw["posSide"])
        contracts, price = _number(raw["fillSz"], positive=True), _number(raw["fillPx"], positive=True)
        fee, pnl, currency = _number(raw["fee"]), _number(raw["fillPnl"]), _currency(raw["feeCcy"])
        order = _id(raw["ordId"]) if raw["ordId"] else None  # block trades can be unowned.
        trade_id = _id(raw["tradeId"], signed=True)  # liquidation/ADL can have negative tradeId.
        client = raw.get("clOrdId") or None
        if ((client is not None and not re.fullmatch(r"[A-Za-z0-9]{1,32}", client))
                or ("execType" in raw and raw["execType"] not in {"", "M", "T"})):
            _fail()
    if side not in {"buy", "sell"} or leg not in {"BOTH", "LONG", "SHORT"}:
        _fail()
    size = _number(market["contractSize"], positive=True)
    if venue == "binance":
        quantity, native_unit = contracts, "base_currency"  # Native USDⓈ-M userTrades.qty.
        contracts = quantity/size
    else:
        quantity, native_unit = contracts*size, "contracts"
    return {**result, "timestamp_ms": timestamp, "clock_source": clock, "order_id": order, "trade_id": trade_id,
            "client_order_id": client, "side": side, "position_side": leg, "contracts": _string(contracts),
            "quantity": _string(quantity), "price": _string(price), "notional": _string(quantity*price),
            "native_quantity_unit": native_unit, "fee_cash_delta": _string(fee), "fee_currency": currency,
            "realized_pnl": _string(pnl), "pnl_currency": market["settle"]}


def _receipt(payload):
    return {"schema": SCHEMA, "payload_sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest(), "payload": payload}


def verify_execution_fact(fact, market, venue):
    try:
        with localcontext(_MONEY):
            market = _market(market)
            if (venue not in {"binance", "okx"} or fact["kind"] not in {"trade", "funding"}
                    or ("binance" if market["exchange"] == "binanceusdm" else market["exchange"]) != venue
                    or canonical_bytes(fact) != canonical_bytes(_normalize(fact["raw"], market, venue, fact["kind"]))):
                _fail()
        return fact
    except (KeyError, TypeError, ValueError, AttributeError, DecimalException):
        raise CChanException("逐笔事实字节/来源字段不一致", ErrCode.LIST_ORDER_FAIL) from None


def verify_execution_scan(receipt):
    """Validate the entire normalized/whitelisted shape, not just a rehash."""
    try:
        payload = receipt["payload"]
        expected = {"account_scope", "account_scope_verified", "venue", "mode", "market", "start_ms", "end_ms",
                    "coverage", "economics_complete", "requests", "facts"}
        with localcontext(_MONEY):
            if (set(payload) != expected or receipt != _receipt(payload)
                    or set(receipt) != {"schema", "payload_sha256", "payload"} or receipt["schema"] != SCHEMA
                    or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", payload["account_scope"])
                    or payload["account_scope_verified"] is not False or payload["economics_complete"] is not False
                    or payload["coverage"] != "observed_execution_facts" or payload["mode"] not in {"testnet", "live"}
                    or payload["venue"] not in {"binance", "okx"}
                    or type(payload["requests"]) is not int or not 2 <= payload["requests"] <= MAX_REQUESTS
                    or any(type(payload[k]) is not int for k in ("start_ms", "end_ms"))
                    or not 0 <= payload["start_ms"] < payload["end_ms"] < 2**63
                    or payload["end_ms"]-payload["start_ms"] > MAX_AGE_MS
                    or payload["market"] != _market(payload["market"])
                    or ("binance" if payload["market"]["exchange"] == "binanceusdm" else payload["market"]["exchange"]) != payload["venue"]):
                _fail()
            facts, seen = payload["facts"], set()
            if facts != sorted(facts, key=lambda f: (f["source_ms"], f["kind"], f["source_id"])):
                _fail()
            for fact in facts:
                key = (fact["kind"], fact["source_id"])
                if (fact["kind"] not in {"trade", "funding"} or key in seen
                        or not payload["start_ms"] <= fact["source_ms"] < payload["end_ms"]):
                    _fail()
                verify_execution_fact(fact, payload["market"], payload["venue"])
                seen.add(key)
        return receipt
    except (KeyError, TypeError, ValueError, AttributeError, DecimalException):
        raise CChanException("逐笔来源收据无效，禁止猜测对账", ErrCode.LIST_ORDER_FAIL) from None


def collect_execution_scan(exchange, market, *, account_scope, mode, start_ms, end_ms):
    import ccxt
    try:
        with localcontext(_MONEY):
            observed_now = utc_now_ms()
            market = _market(market)
            venue = "binance" if exchange.id in {"binance", "binanceusdm"} else exchange.id
            if (venue not in {"binance", "okx"} or venue != ("binance" if market["exchange"] == "binanceusdm" else market["exchange"])
                    or mode not in {"testnet", "live"} or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", account_scope)
                    or type(start_ms) is not int or type(end_ms) is not int
                    or not observed_now-MAX_AGE_MS <= start_ms < end_ms <= observed_now):
                _fail()
            facts, wire, requests = {}, {}, 0
            def request(kind, params, *, recent=False):
                nonlocal requests
                requests += 1
                if requests > MAX_REQUESTS:
                    _fail()
                if venue == "binance":
                    method = exchange.fapiPrivateGetUserTrades if kind == "trade" else exchange.fapiPrivateGetIncome
                    rows = method(params)
                else:
                    method = (exchange.privateGetTradeFills if recent else exchange.privateGetTradeFillsHistory) if kind == "trade" else exchange.privateGetAccountBillsArchive
                    response = method(params)
                    if response.get("code") != "0":
                        _fail()
                    rows = response["data"]
                if not isinstance(rows, list) or len(rows) > (1000 if venue == "binance" else 100):
                    _fail()
                return rows

            def add(rows, kind, begin, end, *, target=None):
                ids = []
                selected_begin, selected_end = (begin, end) if target is None else target
                for row in rows:
                    fact = _normalize(row, market, venue, kind)
                    if not begin <= fact["source_ms"] < end:
                        _fail()
                    key = (kind, fact["source_id"])
                    if key in wire and canonical_bytes(wire[key]) != canonical_bytes(fact):
                        _fail()
                    wire[key] = fact
                    if selected_begin <= fact["source_ms"] < selected_end:
                        facts[key] = fact
                    ids.append(int(fact["source_id"]))
                return ids

            def binance_window(kind, begin, end):
                params = {"symbol": market["id"], "startTime": begin, "endTime": end-1, "limit": 1000}
                if kind == "funding":
                    params["incomeType"] = "FUNDING_FEE"
                rows = request(kind, params)
                add(rows, kind, begin, end)
                if len(rows) == 1000:
                    if end-begin <= 1:
                        _fail()
                    middle = (begin+end)//2
                    binance_window(kind, begin, middle)
                    binance_window(kind, middle, end)

            for kind in ("trade", "funding"):
                if venue == "binance":
                    for begin in range(start_ms, end_ms, WINDOW_MS):
                        binance_window(kind, begin, min(begin+WINDOW_MS, end_ms))
                else:
                    windows = [(start_ms, end_ms, False)]
                    if kind == "trade":
                        cutoff = observed_now-3*86_400_000
                        windows = ([(start_ms, min(end_ms, cutoff), False)] if start_ms < cutoff else [])
                        if end_ms > cutoff:
                            windows.append((max(start_ms, cutoff), end_ms, True))
                    for begin, end, recent in windows:
                        # Read adjacent integer boundaries because provider
                        # wording does not promise timestamp inclusion. The
                        # published lane still uses exactly [begin,end).
                        params = {"instId": market["id"], "instType": "SWAP", "begin": str(max(0, begin-1)), "end": str(end), "limit": "100"}
                        if kind == "funding":
                            params.update(type="8", ctType="linear", ccy="USDT")
                        previous = None
                        while True:
                            rows = request(kind, params, recent=recent)
                            ids = add(rows, kind, max(0, begin-1), end+1, target=(begin, end))
                            if previous is not None and any(key >= previous for key in ids):
                                _fail()
                            if len(rows) < 100:
                                break
                            previous = min(ids)
                            params["after"] = str(previous)
            payload = {"account_scope": account_scope, "account_scope_verified": False, "venue": venue,
                "mode": mode, "market": market, "start_ms": start_ms, "end_ms": end_ms,
                "coverage": "observed_execution_facts", "economics_complete": False, "requests": requests,
                "facts": sorted(facts.values(), key=lambda f: (f["source_ms"], f["kind"], f["source_id"]))}
            return verify_execution_scan(_receipt(payload))
    except (ccxt.BaseError, KeyError, TypeError, ValueError, AttributeError, DecimalException):
        raise CChanException("逐笔来源读取失败，未提交订单或认定账户完整", ErrCode.LIST_ORDER_FAIL) from None
