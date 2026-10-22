"""Independent native mark/BBO observations, never an account admission.

Local windows and exchange clocks are different facts. Readers rederive the
allowlisted content, not server authenticity; a caller-resealed hash is not a
capability. No CCXT import, network or configuration read occurs at import.
"""
import hashlib
import inspect
import json
import re
from decimal import localcontext
from pathlib import Path

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountIdentity import _environment, _https
from .AccountSources import _raw
from .ExecutionFacts import MAX_REQUESTS, _MONEY, _id, _market, _number, _string, _time


SCHEMA = "chan-native-market-evidence-v1"
_ROUTE = {"binance": "fapiPublic", "okx": "rest"}
_MARKET_KEYS = {"exchange", "id", "symbol", "type", "base", "quote", "settle", "contractSize",
                "precision_mode", "precision", "limits"}
_SOURCES = ("Trade/NativeMarketEvidence.py", "Trade/AccountIdentity.py", "Trade/AccountSources.py",
            "Trade/ExecutionFacts.py", "CustomBuySellPoint/Decision.py", "Common/KLineTime.py")
_ROOT = Path(__file__).resolve().parents[1]


def _fail():
    raise CChanException("原生 mark/book 来源、环境或时间证据不完整；不构成账户准入", ErrCode.TRADE_UNLOCK_FAIL) from None


def _digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _implementation():
    return {name: hashlib.sha256((_ROOT/name).read_bytes()).hexdigest() for name in _SOURCES}


def _sdk(exchange, ccxt):
    # Include inherited native endpoint builders, not just binanceusdm's tiny
    # subclass. Persist module names/digests, never local paths or credentials.
    sources = {cls.__module__: hashlib.sha256(Path(inspect.getfile(cls)).read_bytes()).hexdigest()
               for cls in type(exchange).__mro__ if cls.__module__.startswith("ccxt.")}
    return {"name": "ccxt", "version": ccxt.__version__,
            "exchange_class": type(exchange).__module__+"."+type(exchange).__name__, "source_sha256": sources}


def _public_environment(exchange, reference, venue, mode):
    if exchange.id != reference.id or type(exchange) is not type(reference):
        _fail()
    env = _environment(exchange, reference, venue, mode)
    key = _ROUTE[venue]
    actual, expected = exchange.urls["api"][key], reference.urls["api"][key]
    if actual != expected:
        _fail()
    route = _https(actual.replace("{hostname}", env["hostname"]) if env["hostname"] else actual)
    return {"sandbox": env["sandbox"], "public_routes": {key: route},
            "hostname": env["hostname"], "simulated_trading": env["simulated_trading"]}


def _markets(values, exchange_id):
    if not isinstance(values, list) or not values or len(values)*2 > MAX_REQUESTS:
        _fail()
    values = json.loads(canonical_bytes(values))
    ids, symbols = set(), set()
    for value in values:
        if not isinstance(value, dict) or set(value) != _MARKET_KEYS:
            _fail()
        _market(value)  # Original strict USDT-swap unit/Decimal boundary.
        if (value["exchange"] != exchange_id or value["id"] in ids or value["symbol"] in symbols
                or type(value["precision_mode"]) is not int or value["precision_mode"] not in {2, 3, 4}):
            _fail()
        precision, limits = value["precision"], value["limits"]
        if (not isinstance(precision, dict) or not {"amount", "price"} <= set(precision)
                or not set(precision) <= {"amount", "price", "cost", "base", "quote"}
                or any(precision[k] is None for k in ("amount", "price"))
                or not isinstance(limits, dict) or set(limits) != {"amount", "price", "cost"}):
            _fail()
        numbers = list(precision.values())
        for bounds in limits.values():
            if not isinstance(bounds, dict) or not set(bounds) <= {"min", "max"}:
                _fail()
            numbers.extend(bounds.values())
        for number in numbers:
            if number is not None:
                if type(number) not in (str, int, float):
                    _fail()
                _number(str(number))
        for key in ("amount", "price"):
            number = _number(str(precision[key]))
            # CCXT permits negative integer digit counts; they are not ticks.
            if (value["precision_mode"] == 4 and number <= 0) or (value["precision_mode"] != 4 and type(precision[key]) is not int):
                _fail()
        for bounds in limits.values():
            if any(number is not None and _number(str(number)) < 0 for number in bounds.values()):
                _fail()
            if bounds.get("min") is not None and bounds.get("max") is not None and _number(str(bounds["min"])) > _number(str(bounds["max"])):
                _fail()
        ids.add(value["id"])
        symbols.add(value["symbol"])
    return sorted(values, key=lambda value: (value["id"], value["symbol"]))


def _request(venue, market, kind):
    instrument = market["id"]
    if venue == "binance":
        return (("/fapi/v1/premiumIndex", "fapiPublicGetPremiumIndex") if kind == "mark" else
                ("/fapi/v1/ticker/bookTicker", "fapiPublicGetTickerBookTicker")) + ({"symbol": instrument},)
    return (("/api/v5/public/mark-price", "publicGetPublicMarkPrice", {"instType": "SWAP", "instId": instrument})
            if kind == "mark" else ("/api/v5/market/books", "publicGetMarketBooks", {"instId": instrument, "sz": "1"}))


def _values(venue, market, kind, wire):
    if kind == "mark":
        keys = ("symbol", "markPrice", "time") if venue == "binance" else ("instId", "instType", "markPx", "ts")
        raw = _raw(wire, keys)
        if set(raw) != set(keys) or raw[keys[0]] != market["id"] or (venue == "okx" and raw["instType"] != "SWAP"):
            _fail()
        return {"raw": raw, "source_ms": _time(raw["time" if venue == "binance" else "ts"]),
                "clock_kind": "native_time" if venue == "binance" else "data_return_time",
                "price": _string(_number(raw["markPrice" if venue == "binance" else "markPx"], positive=True))}
    if venue == "binance":
        keys = ("symbol", "bidPrice", "bidQty", "askPrice", "askQty", "time")
        raw = _raw(wire, keys)
        if set(raw) != set(keys) or raw["symbol"] != market["id"]:
            _fail()
        bid, ask = _number(raw["bidPrice"]), _number(raw["askPrice"])
        bid_q, ask_q = _number(raw["bidQty"]), _number(raw["askQty"])
        if min(bid, ask, bid_q, ask_q) < 0:
            _fail()
        size = _number(market["contractSize"], positive=True)
        bid_c, ask_c = bid_q/size, ask_q/size
        clock, source_ms, binding, unit = "transaction_time", _time(raw["time"]), "response_symbol", "base_currency"
    else:
        if not isinstance(wire, dict) or not {"bids", "asks", "ts", "seqId"} <= set(wire):
            _fail()
        raw = json.loads(canonical_bytes({key: wire[key] for key in ("bids", "asks", "ts", "seqId")}))
        _id(raw["seqId"], signed=True)  # Snapshot sequence is not a stream continuity proof.
        levels = []
        for side in ("bids", "asks"):
            rows = raw[side]
            if not isinstance(rows, list) or len(rows) > 1:
                _fail()
            if not rows:
                levels.append((None, None, None))
                continue
            row = rows[0]
            if not isinstance(row, list) or len(row) != 4 or any(type(v) is not str for v in row):
                _fail()
            price, contracts = _number(row[0], positive=True), _number(row[1])
            _id(row[2])
            _id(row[3])
            if contracts < 0:
                _fail()
            levels.append((price, contracts*_number(market["contractSize"], positive=True), contracts))
        (bid, bid_q, bid_c), (ask, ask_q, ask_c) = levels
        clock, source_ms, binding, unit = "book_generation_time", _time(raw["ts"]), "request_only", "contracts"
    tradeable = all(value is not None and value > 0 for value in (bid, ask, bid_q, ask_q)) and bid < ask
    return {"raw": raw, "source_ms": source_ms, "clock_kind": clock, "instrument_binding": binding,
            "native_quantity_unit": unit, "tradeable": tradeable,
            **{key: None if value is None else _string(value) for key, value in
               (("bid_price", bid), ("ask_price", ask), ("bid_quantity", bid_q), ("ask_quantity", ask_q),
                ("bid_contracts", bid_c), ("ask_contracts", ask_c))}}


def _source(venue, market, kind, wire, started_ms, finished_ms):
    endpoint, _, params = _request(venue, market, kind)
    values = _values(venue, market, kind, wire)
    if (type(started_ms) is not int or type(finished_ms) is not int or not 0 <= started_ms <= finished_ms
            or values["source_ms"] > finished_ms):
        _fail()
    return {"endpoint": endpoint, "params": params, "started_ms": started_ms, "finished_ms": finished_ms, **values}


def verify_native_market_evidence(document):
    """Recompute all derived fields; this does not authenticate caller bytes.

    No freshness defaults: old source clocks remain old and must be checked by
    the later explicit policy consumer. SDK digests describe collection, not a
    certificate or permission; current-client binding belongs at each use.
    """
    try:
        payload = document["payload"]
        keys = {"exchange_id", "venue", "mode", "environment", "sdk", "implementation_sha256", "started_ms", "finished_ms",
                "requests", "coverage", "native_admission_verified", "observations"}
        if (set(document) != {"schema", "payload", "payload_sha256"} or document["schema"] != SCHEMA
                or document["payload_sha256"] != _digest(payload) or set(payload) != keys
                or payload["exchange_id"] not in {"binance", "binanceusdm", "okx"}
                or payload["venue"] != ("okx" if payload["exchange_id"] == "okx" else "binance")
                or payload["mode"] not in {"live", "testnet"} or payload["native_admission_verified"] is not False
                or payload["coverage"] != "observed_native_mark_and_best_book"
                or payload["implementation_sha256"] != _implementation()):
            _fail()
        env, venue = payload["environment"], payload["venue"]
        if (set(env) != {"sandbox", "public_routes", "hostname", "simulated_trading"}
                or env["sandbox"] is not (payload["mode"] == "testnet") or set(env["public_routes"]) != {_ROUTE[venue]}):
            _fail()
        _https(env["public_routes"][_ROUTE[venue]])
        if venue == "binance":
            if env["hostname"] is not None or env["simulated_trading"] is not None:
                _fail()
        elif (not isinstance(env["hostname"], str) or not env["hostname"]
                or env["simulated_trading"] not in (("1",) if env["sandbox"] else (None, "0"))):
            _fail()
        sdk = payload["sdk"]
        if (set(sdk) != {"name", "version", "exchange_class", "source_sha256"} or sdk["name"] != "ccxt"
                or not isinstance(sdk["version"], str) or re.fullmatch(r"[0-9][A-Za-z0-9.+_-]{0,63}", sdk["version"]) is None
                or sdk["exchange_class"] != "ccxt."+payload["exchange_id"]+"."+payload["exchange_id"]
                or not isinstance(sdk["source_sha256"], dict) or not sdk["source_sha256"]
                or any(not isinstance(k, str) or re.fullmatch(r"ccxt\.[A-Za-z0-9_.]+", k) is None
                       or not isinstance(v, str) or re.fullmatch(r"[0-9a-f]{64}", v) is None for k, v in sdk["source_sha256"].items())):
            _fail()
        observations = payload["observations"]
        if not isinstance(observations, list) or any(set(row) != {"market", "mark", "book"} for row in observations):
            _fail()
        with localcontext(_MONEY):
            markets = _markets([row["market"] for row in observations], payload["exchange_id"])
            if canonical_bytes(markets) != canonical_bytes([row["market"] for row in observations]):
                _fail()
            if (any(type(payload[k]) is not int for k in ("started_ms", "finished_ms", "requests"))
                    or not 0 <= payload["started_ms"] <= payload["finished_ms"] <= utc_now_ms()
                    or payload["requests"] != len(markets)*2):
                _fail()
            previous = payload["started_ms"]
            for row in observations:
                for kind in ("mark", "book"):
                    source = row[kind]
                    start, finish = source["started_ms"], source["finished_ms"]
                    expected = _source(venue, row["market"], kind, source["raw"], start, finish)
                    if (canonical_bytes(source) != canonical_bytes(expected) or type(start) is not int or type(finish) is not int
                            or not previous <= start <= finish <= payload["finished_ms"] or source["source_ms"] > finish):
                        _fail()
                    previous = finish
        return document
    except Exception:
        _fail()


def collect_native_market_evidence(exchange, markets, *, mode):
    """Explicit raw read-only SDK calls. No retry, private GET or admission."""
    try:
        import ccxt  # optional, and only at the explicit collection boundary
        started = utc_now_ms()
        exchange_id = exchange.id
        venue = "okx" if exchange_id == "okx" else "binance"
        if exchange_id not in {"binance", "binanceusdm", "okx"} or mode not in {"live", "testnet"}:
            _fail()
        with localcontext(_MONEY):
            markets = _markets(markets, exchange_id)
        reference = getattr(ccxt, exchange_id)()
        if mode == "testnet":
            reference.set_sandbox_mode(True)
        environment = _public_environment(exchange, reference, venue, mode)
        sdk, implementation = _sdk(exchange, ccxt), _implementation()
        observations = []
        for market in markets:
            observation = {"market": market}
            for kind in ("mark", "book"):
                request_start = utc_now_ms()
                if _public_environment(exchange, reference, venue, mode) != environment:
                    _fail()
                _, method, params = _request(venue, market, kind)
                wire = getattr(exchange, method)(dict(params))
                if _public_environment(exchange, reference, venue, mode) != environment:
                    _fail()
                request_end = utc_now_ms()
                if venue == "okx":
                    if not isinstance(wire, dict) or wire.get("code") != "0" or not isinstance(wire.get("data"), list) or len(wire["data"]) != 1:
                        _fail()
                    wire = wire["data"][0]
                with localcontext(_MONEY):
                    observation[kind] = _source(venue, market, kind, wire, request_start, request_end)
            observations.append(observation)
        if sdk != _sdk(exchange, ccxt) or implementation != _implementation():
            _fail()
        payload = {"exchange_id": exchange_id, "venue": venue, "mode": mode, "environment": environment,
                   "sdk": sdk, "implementation_sha256": implementation, "started_ms": started, "finished_ms": utc_now_ms(),
                   "requests": len(markets)*2, "coverage": "observed_native_mark_and_best_book",
                   "native_admission_verified": False, "observations": observations}
        document = json.loads(canonical_bytes({"schema": SCHEMA, "payload": payload, "payload_sha256": _digest(payload)}))
        return verify_native_market_evidence(document)
    except Exception:
        _fail()
