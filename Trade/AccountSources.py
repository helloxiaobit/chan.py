"""Native account-wide observations, not account-reconciliation certificates.

Wallet deltas already include their reported components. Never add trade fees
or PnL again, convert currencies, allocate funding legs or infer missing cash.
"""
import hashlib
import json
import re
from decimal import DecimalException, localcontext

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountIdentity import observe_account_context, verify_account_context
# Share the existing native-wire decimal/identity boundary, not a second money
# conversion policy. No optional CCXT import is needed to validate stored data.
from .ExecutionFacts import MAX_AGE_MS, MAX_REQUESTS, WINDOW_MS, _MONEY, _currency, _id, _market, _number, _string, _time


WALLET_SCHEMA = "chan-wallet-scan-v1"
SNAPSHOT_SCHEMA = "chan-native-account-snapshot-v1"
_DOMAIN = {"binance": "binance_usdt_m_futures", "okx": "okx_trading_account"}
_WALLET_RAW = {
    "binance": ("symbol", "incomeType", "income", "asset", "time", "tranId", "tradeId"),
    "okx": ("billId", "ts", "type", "subType", "ccy", "balChg", "posBalChg", "bal", "posBal", "instId",
        "instType", "mgnMode", "ordId", "clOrdId", "tradeId", "fee", "pnl", "interest", "from", "to", "fillTime"),
}


def _fail():
    raise CChanException("账户原生来源/单位/时间/身份不完整，不能猜测账户对账通过", ErrCode.LIST_ORDER_FAIL) from None


def _receipt(schema, payload):
    return {"schema": schema, "payload": payload, "payload_sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest()}


def _raw(row, keys):
    if not isinstance(row, dict):
        _fail()
    value = {k: row[k] for k in keys if k in row}
    if any(type(v) not in (str, int, bool) for v in value.values()):
        _fail()
    return value


def _text(value, *, empty=False):
    if not isinstance(value, str) or len(value) > 128 or (not empty and not value) or value.strip() != value:
        _fail()
    return value


def _numeric_optional(raw, key):
    return None if key not in raw or raw[key] == "" else _string(_number(raw[key]))


def _id_optional(raw, key, *, signed=False):
    return None if key not in raw or raw[key] == "" else _id(raw[key], signed=signed)


def _wallet_fact(row, venue):
    raw = _raw(row, _WALLET_RAW[venue])
    if venue == "binance":
        kind = _text(raw["incomeType"])
        if not re.fullmatch(r"[A-Z0-9_]{1,64}", kind):
            _fail()
        native_id = _id(raw["tranId"])
        source_id, timestamp = f"{kind}:{native_id}", _time(raw["time"])
        currency, amount = _currency(raw["asset"]), _string(_number(raw["income"]))
        instrument = _text(raw["symbol"], empty=True)
        subtype, balance, position_delta, position_balance = None, None, None, None
        fee = pnl = interest = order = None
        client, trade = None, _id_optional(raw, "tradeId", signed=True)
    else:
        kind, native_id = _id(raw["type"]), _id(raw["billId"])
        source_id, timestamp = native_id, _time(raw["ts"])
        subtype = _id_optional(raw, "subType")
        currency, amount = _currency(raw["ccy"]), _string(_number(raw["balChg"]))
        instrument = _text(raw.get("instId", ""), empty=True)
        balance, position_delta, position_balance = (_numeric_optional(raw, k) for k in ("bal", "posBalChg", "posBal"))
        fee, pnl, interest = (_numeric_optional(raw, k) for k in ("fee", "pnl", "interest"))
        order, trade = _id_optional(raw, "ordId"), _id_optional(raw, "tradeId", signed=True)
        client = raw.get("clOrdId") or None
        if client is not None and (not isinstance(client, str) or re.fullmatch(r"[A-Za-z0-9]{1,32}", client) is None):
            _fail()
        for field in ("instType", "mgnMode", "from", "to"):
            if field in raw:
                _text(raw[field], empty=True)
        if "fillTime" in raw and raw["fillTime"] != "":
            _time(raw["fillTime"])
    return {"source_id": source_id, "native_id": native_id, "timestamp_ms": timestamp, "native_type": kind,
        "native_subtype": subtype, "instrument_id": instrument or None, "currency": currency,
        "account_cash_delta": amount, "position_cash_delta": position_delta, "balance_after": balance,
        "position_balance_after": position_balance, "fee_cash_delta": fee, "reported_pnl": pnl, "reported_interest": interest,
        "order_id": order, "trade_id": trade, "client_order_id": client, "raw": raw}


def _verify_envelope(receipt, schema, coverage, keys):
    payload = receipt["payload"]
    if (set(receipt) != {"schema", "payload", "payload_sha256"} or receipt != _receipt(schema, payload)
            or set(payload) != keys or payload["coverage"] != coverage or payload["economics_complete"] is not False):
        _fail()
    verify_account_context(payload["account_context"])
    if (payload["account_domain"] != _DOMAIN[payload["account_context"]["venue"]]
            or any(type(payload[k]) is not int for k in ("started_ms", "finished_ms", "requests"))
            or not 0 <= payload["started_ms"] <= payload["finished_ms"] <= utc_now_ms()
            or not 1 <= payload["requests"] <= MAX_REQUESTS):
        _fail()
    return payload


def verify_wallet_scan(receipt):
    try:
        payload = _verify_envelope(receipt, WALLET_SCHEMA, "observed_account_cashflows", {"account_context", "account_domain",
            "started_ms", "finished_ms", "start_ms", "end_ms", "requests", "coverage", "economics_complete", "facts"})
        if (any(type(payload[k]) is not int for k in ("start_ms", "end_ms"))
                or not 0 <= payload["start_ms"] < payload["end_ms"] <= payload["finished_ms"]
                or payload["end_ms"]-payload["start_ms"] > MAX_AGE_MS):
            _fail()
        venue, seen = payload["account_context"]["venue"], set()
        facts = payload["facts"]
        if not isinstance(facts, list) or facts != sorted(facts, key=lambda f: (f["timestamp_ms"], f["native_type"], f["source_id"])):
            _fail()
        with localcontext(_MONEY):
            for fact in facts:
                if (canonical_bytes(fact) != canonical_bytes(_wallet_fact(fact["raw"], venue))
                        or fact["source_id"] in seen or not payload["start_ms"] <= fact["timestamp_ms"] < payload["end_ms"]):
                    _fail()
                seen.add(fact["source_id"])
        return receipt
    except (KeyError, TypeError, ValueError, AttributeError, DecimalException):
        _fail()


def collect_wallet_scan(exchange, *, mode, start_ms, end_ms):
    """Request all native cashflow types/currencies, with no instrument filter.

    Request budget excludes the two surrounding native identity GETs. Unknown
    cashflow types remain literal native types; they never become trading PnL.
    """
    import ccxt
    try:
        now, started = utc_now_ms(), utc_now_ms()
        if (type(start_ms) is not int or type(end_ms) is not int
                or not now-MAX_AGE_MS <= start_ms < end_ms <= now):
            _fail()
        before = observe_account_context(exchange, mode)
        venue, requests, facts, wire = before["venue"], 0, {}, {}

        def request(params):
            nonlocal requests
            requests += 1
            if requests > MAX_REQUESTS:
                _fail()
            if venue == "binance":
                rows = exchange.fapiPrivateGetIncome(params)
            else:
                response = exchange.privateGetAccountBillsArchive(params)
                if response.get("code") != "0":
                    _fail()
                rows = response["data"]
            if not isinstance(rows, list) or len(rows) > (1000 if venue == "binance" else 100):
                _fail()
            return rows

        def add(rows, begin, end):
            ids = []
            for row in rows:
                fact = _wallet_fact(row, venue)
                if not begin <= fact["timestamp_ms"] < end:
                    _fail()
                key = fact["source_id"]
                if key in wire and canonical_bytes(wire[key]) != canonical_bytes(fact):
                    _fail()
                wire[key] = fact
                if start_ms <= fact["timestamp_ms"] < end_ms:
                    facts[key] = fact
                ids.append(int(fact["native_id"]))
            return ids

        def binance_window(begin, end):
            rows = request({"startTime": begin, "endTime": end-1, "limit": 1000})
            add(rows, begin, end)
            if len(rows) == 1000:
                if end-begin <= 1:
                    _fail()
                middle = (begin+end)//2
                binance_window(begin, middle)
                binance_window(middle, end)

        with localcontext(_MONEY):
            if venue == "binance":
                for begin in range(start_ms, end_ms, WINDOW_MS):
                    binance_window(begin, min(begin+WINDOW_MS, end_ms))
            else:
                # The provider's filter wording does not promise endpoint
                # inclusion. Read one surrounding integer millisecond, then
                # enforce our own end-exclusive target; do not silently miss
                # start/end-1 under a strict timestamp filter.
                params = {"begin": str(max(0, start_ms-1)), "end": str(end_ms), "limit": "100"}
                previous = None
                while True:
                    rows = request(params)
                    ids = add(rows, max(0, start_ms-1), end_ms+1)
                    if previous is not None and any(value >= previous for value in ids):
                        _fail()
                    if len(rows) < 100:
                        break
                    previous = min(ids)
                    params["after"] = str(previous)
        if canonical_bytes(before) != canonical_bytes(observe_account_context(exchange, mode)):
            _fail()
        payload = {"account_context": before, "account_domain": _DOMAIN[venue], "started_ms": started, "finished_ms": utc_now_ms(),
            "start_ms": start_ms, "end_ms": end_ms, "requests": requests, "coverage": "observed_account_cashflows", "economics_complete": False,
            "facts": sorted(facts.values(), key=lambda f: (f["timestamp_ms"], f["native_type"], f["source_id"]))}
        return verify_wallet_scan(_receipt(WALLET_SCHEMA, payload))
    except (ccxt.BaseError, KeyError, TypeError, ValueError, AttributeError, DecimalException):
        _fail()


_ASSET_RAW = {
    "binance": ("asset", "walletBalance", "unrealizedProfit", "marginBalance", "initialMargin", "maintMargin",
        "availableBalance", "crossWalletBalance", "crossUnPnl", "updateTime"),
    "okx": ("ccy", "cashBal", "eq", "upl", "availBal", "availEq", "imr", "mmr", "isoEq", "liab", "interest", "uTime"),
}
_ACCOUNT_RAW = {
    "binance": ("totalWalletBalance", "totalUnrealizedProfit", "totalMarginBalance", "totalInitialMargin", "totalMaintMargin", "availableBalance"),
    "okx": ("uTime", "totalEq", "isoEq", "imr", "mmr", "upl"),
}
_POSITION_RAW = {
    "binance": ("symbol", "positionSide", "positionAmt", "entryPrice", "markPrice", "unRealizedProfit", "notional",
        "marginAsset", "isolatedWallet", "isolatedMargin", "initialMargin", "maintMargin", "liquidationPrice", "updateTime"),
    "okx": ("instId", "instType", "posId", "posSide", "pos", "avgPx", "markPx", "upl", "ccy", "mgnMode",
        "margin", "lever", "imr", "mmr", "notionalUsd", "liqPx", "uTime", "realizedPnl", "pnl", "fee", "fundingFee", "liqPenalty"),
}
_ACCOUNT_POSITION = ("symbol", "positionSide", "positionAmt", "unrealizedProfit", "isolatedMargin", "notional",
    "isolatedWallet", "initialMargin", "maintMargin", "updateTime")
_SETTINGS = ("symbol", "marginType", "leverage", "isAutoAddMargin")


def _rows(value):
    if not isinstance(value, list):
        _fail()
    return value


def _okx(response):
    if not isinstance(response, dict) or response.get("code") != "0":
        _fail()
    return _rows(response["data"])


def _account_raw(value, venue):
    result = _raw(value, _ACCOUNT_RAW[venue])
    asset_key = "assets" if venue == "binance" else "details"
    result[asset_key] = [_raw(row, _ASSET_RAW[venue]) for row in _rows(value[asset_key])]
    if venue == "binance":
        result["positions"] = [_raw(row, _ACCOUNT_POSITION) for row in _rows(value["positions"])]
    return result


def _asset(row, venue):
    for key in set(_ASSET_RAW[venue]) - {"asset", "ccy", "updateTime", "uTime"}:
        _numeric_optional(row, key)
    if venue == "binance":
        currency, cash, clock = _currency(row["asset"]), _string(_number(row["walletBalance"])), _time(row["updateTime"])
        keys = ("marginBalance", "unrealizedProfit", "availableBalance", "initialMargin", "maintMargin", None, None, None)
    else:
        currency, cash, clock = _currency(row["ccy"]), _string(_number(row["cashBal"])), _time(row["uTime"])
        keys = ("eq", "upl", "availBal", "imr", "mmr", "isoEq", "liab", "interest")
    names = ("equity", "unrealized_pnl", "available_balance", "initial_margin", "maintenance_margin", "isolated_equity", "liability", "reported_interest")
    return {"currency": currency, "cash_balance": cash, "update_ms": clock,
        **{name: None if key is None else _numeric_optional(row, key) for name, key in zip(names, keys)}}


def _position(row, venue, markets, settings):
    instrument = _text(row["symbol" if venue == "binance" else "instId"])
    leg = row["positionSide"] if venue == "binance" else {"net": "BOTH", "long": "LONG", "short": "SHORT"}.get(row["posSide"])
    native = _number(row["positionAmt" if venue == "binance" else "pos"])
    updated = _time(row["updateTime" if venue == "binance" else "uTime"])
    monetary = ("entryPrice", "markPrice", "unRealizedProfit", "notional", "isolatedWallet", "isolatedMargin", "initialMargin", "maintMargin", "liquidationPrice") if venue == "binance" else (
        "avgPx", "markPx", "upl", "margin", "lever", "imr", "mmr", "notionalUsd", "liqPx", "realizedPnl", "pnl", "fee", "fundingFee", "liqPenalty")
    for key in monetary:
        _numeric_optional(row, key)  # Unsupported does not mean malformed money is trusted.
    if leg not in {"BOTH", "LONG", "SHORT"} or (leg == "LONG" and native < 0) or (venue == "binance" and leg == "SHORT" and native > 0):
        _fail()
    if instrument not in markets or (venue == "okx" and row["instType"] != "SWAP"):
        return None, {"instrument_id": instrument, "reason": "market_metadata_missing" if instrument not in markets else "unsupported_market_type", "raw": row}
    market = markets[instrument]
    size = _number(market["contractSize"], positive=True)
    quantity, contracts = (abs(native), abs(native)/size) if venue == "binance" else (abs(native)*size, abs(native))
    direction = "flat" if not quantity else "short" if leg == "SHORT" or (leg == "BOTH" and native < 0) else "long"
    currency = _currency(row["marginAsset" if venue == "binance" else "ccy"])
    if currency != market["settle"]:
        _fail()
    if venue == "binance":
        setting = settings[instrument]
        margin = {"CROSSED": "cross", "ISOLATED": "isolated"}.get(setting["marginType"])
        leverage = _string(_number(setting["leverage"], positive=True))
        keys = ("entryPrice", "markPrice", "unRealizedProfit", "initialMargin", "maintMargin", "isolatedWallet", "liquidationPrice", "notional", None)
        position_id = None
    else:
        margin, leverage = row["mgnMode"], _string(_number(row["lever"], positive=True))
        keys = ("avgPx", "markPx", "upl", "imr", "mmr", "margin", "liqPx", "notionalUsd", "realizedPnl")
        position_id = _id(row["posId"])
    if margin not in {"cross", "isolated"}:
        _fail()
    names = ("entry_price", "mark_price", "unrealized_pnl", "initial_margin", "maintenance_margin", "isolated_balance", "liquidation_price", "reported_notional", "reported_realized_pnl")
    values = {name: None if key is None else _numeric_optional(row, key) for name, key in zip(names, keys)}
    if values["unrealized_pnl"] is None or (quantity and any(values[key] is None or _number(values[key]) <= 0 for key in ("entry_price", "mark_price"))):
        _fail()
    return {"instrument": market["symbol"], "instrument_id": instrument, "position_id": position_id, "position_side": leg,
        "quantity": _string(quantity), "contracts": _string(contracts), "quantity_unit": "base_currency", "contracts_unit": "contracts",
        "native_quantity_unit": "base_currency" if venue == "binance" else "contracts", "direction": direction, "currency": currency,
        "margin_mode": margin, "leverage": leverage, "update_ms": updated, "mark_ms": None,
        "notional_currency": market["settle"] if venue == "binance" else "USD", **values}, None


def _snapshot_values(raw, market_list, venue):
    if set(raw) != {"account", "positions", "symbol_configs", "multi_assets_margin"}:
        _fail()
    account = raw["account"]
    cleaned = {"account": _account_raw(account, venue), "positions": [_raw(row, _POSITION_RAW[venue]) for row in _rows(raw["positions"])],
        "symbol_configs": [_raw(row, _SETTINGS) for row in _rows(raw["symbol_configs"])], "multi_assets_margin": raw["multi_assets_margin"]}
    if canonical_bytes(raw) != canonical_bytes(cleaned):
        _fail()
    for key in set(_ACCOUNT_RAW[venue]) - {"uTime"}:
        _numeric_optional(account, key)
    markets = {}
    for definition in _rows(market_list):
        market = _market(definition)
        if (canonical_bytes(market) != canonical_bytes(definition) or market["id"] in markets
                or ("binance" if market["exchange"] == "binanceusdm" else market["exchange"]) != venue):
            _fail()
        markets[market["id"]] = market
    assets = [_asset(row, venue) for row in account["assets" if venue == "binance" else "details"]]
    if len({a["currency"] for a in assets}) != len(assets):
        _fail()
    settings, account_positions = {}, []
    for setting in raw["symbol_configs"]:
        if (setting["symbol"] in settings or setting["marginType"] not in {"CROSSED", "ISOLATED"}
                or type(setting["isAutoAddMargin"]) is not bool):
            _fail()
        _number(setting["leverage"], positive=True)
        settings[_text(setting["symbol"])] = setting
    if venue == "binance":
        if type(raw["multi_assets_margin"]) is not bool:
            _fail()
        seen_accounts = set()
        for position in account["positions"]:
            key = (position["symbol"], position["positionSide"])
            if position["positionSide"] not in {"BOTH", "LONG", "SHORT"} or key in seen_accounts:
                _fail()
            seen_accounts.add(key)
            for field in set(_ACCOUNT_POSITION)-{"symbol", "positionSide", "updateTime"}:
                _numeric_optional(position, field)
            account_positions.append({"instrument_id": _text(position["symbol"]), "position_side": position["positionSide"],
                "signed_quantity": _string(_number(position["positionAmt"])), "unrealized_pnl": _string(_number(position["unrealizedProfit"])),
                "update_ms": _time(position["updateTime"]), "quantity_unit": "base_currency"})
        totals = {"currency": "USD" if raw["multi_assets_margin"] else "USDT", "wallet_balance": _numeric_optional(account, "totalWalletBalance"),
            "unrealized_pnl": _numeric_optional(account, "totalUnrealizedProfit"), "equity": _numeric_optional(account, "totalMarginBalance"),
            "initial_margin": _numeric_optional(account, "totalInitialMargin"), "maintenance_margin": _numeric_optional(account, "totalMaintMargin"), "update_ms": None}
    else:
        if raw["symbol_configs"] or raw["multi_assets_margin"] is not None:
            _fail()
        totals = {"currency": "USD", "wallet_balance": None, "unrealized_pnl": _numeric_optional(account, "upl"), "equity": _numeric_optional(account, "totalEq"),
            "initial_margin": _numeric_optional(account, "imr"), "maintenance_margin": _numeric_optional(account, "mmr"), "update_ms": _time(account["uTime"])}
    positions, unsupported, seen = [], [], set()
    for row in raw["positions"]:
        position, unknown = _position(row, venue, markets, settings)
        key = ((position["instrument_id"], position["position_side"], position["margin_mode"], position["position_id"]) if position else
            (unknown["instrument_id"], row.get("positionSide", row.get("posSide")), row.get("mgnMode"), row.get("posId")))
        if key in seen:
            _fail()
        seen.add(key)
        (positions if position else unsupported).append(position if position else unknown)
    return {"assets": sorted(assets, key=lambda a: a["currency"]),
        "positions": sorted(positions, key=lambda p: (p["instrument_id"], p["position_side"], p["margin_mode"], p["position_id"] or "")),
        "unsupported_positions": sorted(unsupported, key=canonical_bytes), "reported_totals": totals,
        "native_account_positions": sorted(account_positions, key=lambda p: (p["instrument_id"], p["position_side"]))}


def verify_account_snapshot(receipt):
    try:
        payload = _verify_envelope(receipt, SNAPSHOT_SCHEMA, "observed_native_account", {"account_context", "account_domain", "started_ms", "finished_ms", "requests",
            "coverage", "economics_complete", "markets", "raw", "assets", "positions", "unsupported_positions", "reported_totals", "native_account_positions"})
        with localcontext(_MONEY):
            expected = _snapshot_values(payload["raw"], payload["markets"], payload["account_context"]["venue"])
        if canonical_bytes(expected) != canonical_bytes({k: payload[k] for k in expected}):
            _fail()
        clocks = [a["update_ms"] for a in payload["assets"]]+[p["update_ms"] for p in payload["positions"]+payload["native_account_positions"]]
        clocks += [_time(p["raw"]["updateTime" if payload["account_context"]["venue"] == "binance" else "uTime"]) for p in payload["unsupported_positions"]]
        if any(at > payload["finished_ms"] for at in clocks) or (payload["reported_totals"]["update_ms"] is not None and payload["reported_totals"]["update_ms"] > payload["finished_ms"]):
            _fail()
        return receipt
    except (KeyError, TypeError, ValueError, AttributeError, DecimalException):
        _fail()


def collect_account_snapshot(exchange, markets, *, mode):
    """Preserve native legs and currencies; updateTime is not a mark timestamp."""
    import ccxt
    try:
        started = utc_now_ms()
        with localcontext(_MONEY):
            markets = [_market(m) for m in json.loads(canonical_bytes(markets))]
        before = observe_account_context(exchange, mode)
        venue = before["venue"]
        if venue == "binance":
            account = _account_raw(exchange.fapiPrivateV3GetAccount({}), venue)
            positions = [_raw(row, _POSITION_RAW[venue]) for row in _rows(exchange.fapiPrivateV3GetPositionRisk({}))]
            settings = [_raw(row, _SETTINGS) for row in _rows(exchange.fapiPrivateGetSymbolConfig({}))]
            multi = exchange.fapiPrivateGetMultiAssetsMargin({})["multiAssetsMargin"]
        else:
            rows = _okx(exchange.privateGetAccountBalance({}))
            if len(rows) != 1:
                _fail()
            account = _account_raw(rows[0], venue)
            positions = [_raw(row, _POSITION_RAW[venue]) for row in _okx(exchange.privateGetAccountPositions({}))]
            settings, multi = [], None
        raw = {"account": account, "positions": positions, "symbol_configs": settings, "multi_assets_margin": multi}
        with localcontext(_MONEY):
            values = _snapshot_values(raw, markets, venue)
        if canonical_bytes(before) != canonical_bytes(observe_account_context(exchange, mode)):
            _fail()
        payload = {"account_context": before, "account_domain": _DOMAIN[venue], "started_ms": started, "finished_ms": utc_now_ms(),
            "requests": 4 if venue == "binance" else 2, "markets": markets, "raw": raw,
            "coverage": "observed_native_account", "economics_complete": False, **values}
        return verify_account_snapshot(_receipt(SNAPSHOT_SCHEMA, payload))
    except (ccxt.BaseError, KeyError, TypeError, ValueError, AttributeError, DecimalException):
        _fail()
