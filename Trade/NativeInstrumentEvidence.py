"""Allowlisted native instruments, not cached metadata or order permission.

Only the explicit collector performs one public GET. The reader uses the
credential-free installed SDK's pure parser, never its market/currency loader.
SDK/file hashes are local interpretation evidence, not server signatures or
proof that every platform trading rule or a new order's funding is satisfied.
"""
import hashlib
import json
import re
from pathlib import Path

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountSources import _raw, _text
from .ExecutionFacts import MAX_REQUESTS, _MONEY, _number, _time
from .NativeMarketEvidence import _markets, _public_environment, _sdk


SCHEMA = "chan-native-instrument-evidence-v1"
_ROOT = Path(__file__).resolve().parents[1]
_SOURCES = ("Trade/NativeInstrumentEvidence.py", "Trade/NativeMarketEvidence.py", "Trade/AccountIdentity.py",
            "Trade/AccountSources.py", "Trade/ExecutionFacts.py", "CustomBuySellPoint/Decision.py", "Common/KLineTime.py")
_FIELDS = {
    "binance": ("symbol", "pair", "baseAsset", "quoteAsset", "marginAsset", "contractType", "status", "contractStatus",
                "contractSize", "deliveryDate", "onboardDate", "pricePrecision", "quantityPrecision", "baseAssetPrecision",
                "quotePrecision", "triggerProtect", "liquidationFee", "marketTakeBound", "maintMarginPercent", "requiredMarginPercent"),
    "okx": ("instId", "instType", "instIdCode", "baseCcy", "quoteCcy", "settleCcy", "uly", "instFamily", "ctType", "ctVal",
            "ctMult", "ctValCcy", "state", "lotSz", "minSz", "maxLmtSz", "maxMktSz", "maxLmtAmt", "maxMktAmt", "tickSz",
            "lever", "listTime", "contTdSwTime", "expTime", "ruleType", "posLmtAmt", "posLmtPct", "maxPlatOILmt"),
}
_FILTER = ("filterType", "minPrice", "maxPrice", "tickSize", "minQty", "maxQty", "stepSize", "notional", "minNotional",
           "maxNotional", "multiplierUp", "multiplierDown", "multiplierDecimal", "bidMultiplierUp", "bidMultiplierDown",
           "askMultiplierUp", "askMultiplierDown", "avgPriceMins", "limit", "maxNumOrders", "maxNumAlgoOrders",
           "applyToMarket", "applyMinToMarket", "applyMaxToMarket")
_NUMERIC = {
    "binance": ("contractSize", "deliveryDate", "onboardDate", "pricePrecision", "quantityPrecision", "baseAssetPrecision",
                "quotePrecision", "triggerProtect", "liquidationFee", "marketTakeBound", "maintMarginPercent", "requiredMarginPercent"),
    "okx": ("instIdCode", "ctVal", "ctMult", "lotSz", "minSz", "maxLmtSz", "maxMktSz", "maxLmtAmt", "maxMktAmt", "tickSz",
            "lever", "listTime", "contTdSwTime", "expTime", "posLmtAmt", "posLmtPct", "maxPlatOILmt"),
}


def _fail():
    raise CChanException("原生 instrument 来源/解析身份/观测窗口不完整；不构成逐单资金或下单准入", ErrCode.TRADE_UNLOCK_FAIL) from None


def _sha(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _implementation():
    return {name: hashlib.sha256((_ROOT/name).read_bytes()).hexdigest() for name in _SOURCES}


def _codes(values):
    if (type(values) is not list or not 1 <= len(values) <= MAX_REQUESTS//2
            or any(type(code) is not str or re.fullmatch(r"[A-Za-z0-9._-]+/USDT:USDT", code) is None for code in values)
            or len(set(values)) != len(values)):
        _fail()
    return sorted(values)


def _request(venue):
    return (("/fapi/v1/exchangeInfo", "fapiPublicGetExchangeInfo", {}) if venue == "binance" else
            ("/api/v5/public/instruments", "publicGetPublicInstruments", {"instType": "SWAP"}))


def _reference(exchange_id, mode):
    import ccxt  # Explicit interpretation/collection boundary only.
    if exchange_id not in {"binance", "binanceusdm", "okx"} or mode not in {"testnet", "live"}:
        _fail()
    reference = getattr(ccxt, exchange_id)()
    if mode == "testnet":
        reference.set_sandbox_mode(True)
    return reference, ccxt


def _raw_rows(rows, venue):
    if type(rows) is not list or not rows:
        _fail()
    result, ids = [], set()
    for row in rows:
        raw = _raw(row, _FIELDS[venue])
        for key in _NUMERIC[venue]:
            if key in raw and raw[key] != "":
                _number(raw[key])
        for key in (("deliveryDate", "onboardDate") if venue == "binance" else ("listTime", "contTdSwTime", "expTime")):
            if key in raw and raw[key] != "":
                _time(raw[key])
        identity = _text(raw["symbol" if venue == "binance" else "instId"])
        if identity in ids:
            _fail()
        ids.add(identity)
        if venue == "binance":
            # SDK parse_precision builds a string before native filters can
            # override it. Bound that allocation to the existing wire-number
            # exponent range, not an unbounded server-supplied digit count.
            for key in ("pricePrecision", "quantityPrecision", "baseAssetPrecision", "quotePrecision"):
                if key in raw and (re.fullmatch(r"[0-9]{1,3}", str(raw[key])) is None or int(raw[key]) > _MONEY.Emax):
                    _fail()
            filters = row["filters"]
            if type(filters) is not list:
                _fail()
            raw["filters"] = [_raw(value, _FILTER) for value in filters]
            for value in raw["filters"]:
                required = {"PRICE_FILTER": {"minPrice", "maxPrice", "tickSize"}, "LOT_SIZE": {"minQty", "maxQty", "stepSize"}}
                if not required.get(value.get("filterType"), set()) <= set(value):
                    _fail()
                for key, number in value.items():
                    if key.startswith("apply"):
                        if type(number) is not bool:
                            _fail()
                    elif key != "filterType":
                        _number(number)
            kinds = [_text(value["filterType"]) for value in raw["filters"]]
            if len(set(kinds)) != len(kinds):
                _fail()
            for key in ("orderTypes", "timeInForce"):
                values = row[key]
                if type(values) is not list or not values or any(type(value) is not str or not value for value in values) or len(set(values)) != len(values):
                    _fail()
                raw[key] = list(values)
        elif "upcChg" in row:
            if type(row["upcChg"]) is not list:
                _fail()
            raw["upcChg"] = [_raw(value, ("param", "newValue", "effTime")) for value in row["upcChg"]]
            for value in raw["upcChg"]:
                if set(value) != {"param", "newValue", "effTime"}:
                    _fail()
                _text(value["param"])
                _text(value["newValue"])
                _time(value["effTime"])
                if value["param"] in {"tickSz", "minSz", "maxMktSz"}:
                    _number(value["newValue"])
        result.append(raw)
    return result


def _observations(reference, rows, codes):
    found = {}
    for index, raw in enumerate(rows):
        parsed = reference.parse_market(raw)
        if parsed is None or parsed["symbol"] not in codes:
            continue
        code = parsed["symbol"]
        if (code in found or parsed["type"] != "swap" or parsed["swap"] is not True or parsed["contract"] is not True
                or parsed["linear"] is not True or parsed["inverse"] is not False or parsed["quote"] != "USDT"
                or parsed["settle"] != "USDT" or type(parsed["active"]) is not bool):
            _fail()
        if reference.id == "okx":
            if (raw.get("instType") != "SWAP" or raw.get("ctType") != "linear"
                    or _text(raw["ctValCcy"]) != parsed["baseId"]
                    or raw.get("baseCcy", "") not in {"", parsed["baseId"]}
                    or raw.get("quoteCcy", "") not in {"", parsed["quoteId"]}):
                _fail()
        elif (raw.get("contractType") != "PERPETUAL"
                or not {"PRICE_FILTER", "LOT_SIZE"} <= {value["filterType"] for value in raw["filters"]}):
            _fail()
        market = {key: parsed[key] for key in ("id", "symbol", "type", "base", "quote", "settle")}
        market.update(exchange=reference.id, contractSize=str(_number(str(parsed["contractSize"]), positive=True)),
                      precision_mode=reference.precisionMode, precision=parsed["precision"],
                      limits={key: parsed["limits"][key] for key in ("amount", "price", "cost")})
        market = json.loads(canonical_bytes(market))
        _markets([market], reference.id)
        found[code] = {"market": market, "active": parsed["active"], "raw_index": index,
                       "native_state": _text(raw["state"] if reference.id == "okx" else raw["status"]),
                       "unit_basis": "installed_sdk_native_contract_interpretation"}
    if set(found) != set(codes):
        _fail()
    return [found[code] for code in codes]


def verify_native_instrument_evidence(document):
    """Rebuild interpretation, not authenticity, current client or admission."""
    try:
        p = document["payload"]
        keys = {"exchange_id", "venue", "mode", "codes", "environment", "sdk", "implementation_sha256", "endpoint", "params",
                "started_ms", "request_started_ms", "request_finished_ms", "finished_ms", "requests", "raw_rows", "observations",
                "clock_kind", "source_ms", "coverage", "economics_complete", "native_admission_verified"}
        if (set(document) != {"schema", "payload", "payload_sha256"} or document["schema"] != SCHEMA or set(p) != keys
                or document["payload_sha256"] != _sha(p) or p["coverage"] != "allowlisted_native_instrument_metadata"
                or p["clock_kind"] != "local_request_window_only" or p["source_ms"] is not None
                or p["economics_complete"] is not False or p["native_admission_verified"] is not False
                or p["venue"] != ("okx" if p["exchange_id"] == "okx" else "binance")
                or type(p["requests"]) is not int or p["requests"] != 1):
            _fail()
        reference, ccxt = _reference(p["exchange_id"], p["mode"])
        endpoint, _, params = _request(p["venue"])
        if (p["codes"] != _codes(p["codes"]) or p["endpoint"] != endpoint or canonical_bytes(p["params"]) != canonical_bytes(params)
                or canonical_bytes(p["environment"]) != canonical_bytes(_public_environment(reference, reference, p["venue"], p["mode"]))
                or p["sdk"] != _sdk(reference, ccxt) or p["implementation_sha256"] != _implementation()):
            _fail()
        times = [p[key] for key in ("started_ms", "request_started_ms", "request_finished_ms", "finished_ms")]
        if any(type(at) is not int or not 0 <= at < 2**63 for at in times) or times != sorted(times) or times[-1] > utc_now_ms():
            _fail()
        rows = _raw_rows(p["raw_rows"], p["venue"])
        if canonical_bytes(rows) != canonical_bytes(p["raw_rows"]) or canonical_bytes(_observations(reference, rows, p["codes"])) != canonical_bytes(p["observations"]):
            _fail()
        return document
    except Exception:
        _fail()


def collect_native_instrument_evidence(exchange, codes, *, mode):
    """One fixed public endpoint. Never reload or change the client's cache."""
    try:
        started, exchange_id = utc_now_ms(), exchange.id
        provided = {"codes": codes, "mode": mode}
        original = canonical_bytes(provided)
        values = json.loads(original)
        codes = _codes(values["codes"])
        reference, ccxt = _reference(exchange_id, mode)
        venue = "okx" if exchange_id == "okx" else "binance"
        environment, sdk, implementation = _public_environment(exchange, reference, venue, mode), _sdk(exchange, ccxt), _implementation()
        endpoint, method, params = _request(venue)
        begin = utc_now_ms()
        if _public_environment(exchange, reference, venue, mode) != environment:
            _fail()
        wire = getattr(exchange, method)(dict(params))
        finish = utc_now_ms()
        if _public_environment(exchange, reference, venue, mode) != environment:
            _fail()
        if type(wire) is not dict or (wire.get("code") != "0" if venue == "okx" else "code" in wire):
            _fail()
        rows = _raw_rows(wire["data" if venue == "okx" else "symbols"], venue)
        observations = _observations(reference, rows, codes)
        if (sdk != _sdk(exchange, ccxt) or implementation != _implementation()
                or canonical_bytes(provided) != original):
            _fail()
        payload = {"exchange_id": exchange_id, "venue": venue, "mode": mode, "codes": codes, "environment": environment,
            "sdk": sdk, "implementation_sha256": implementation, "endpoint": endpoint, "params": params,
            "started_ms": started, "request_started_ms": begin, "request_finished_ms": finish, "finished_ms": utc_now_ms(),
            "requests": 1, "raw_rows": rows, "observations": observations, "clock_kind": "local_request_window_only", "source_ms": None,
            "coverage": "allowlisted_native_instrument_metadata", "economics_complete": False, "native_admission_verified": False}
        return verify_native_instrument_evidence(json.loads(canonical_bytes({"schema": SCHEMA, "payload": payload, "payload_sha256": _sha(payload)})))
    except Exception:
        _fail()
