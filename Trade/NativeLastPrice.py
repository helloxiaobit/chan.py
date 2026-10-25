"""Owned native Last V2 observations; neither cash nor execution authority.

Transaction clocks remain distinct from local request windows. The selected
SDK/response path is checked, not the entire host or server authenticity.
Importing this module does not initialize an SDK, configuration or network.
"""
import hashlib
import json
from pathlib import Path
from time import monotonic_ns as _monotonic_ns

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountIdentity import _https
from .AccountSources import _raw
from .ExecutionFacts import _number, _string
from .NativeCapacityEvidence import _budget, _exact_response, _sha, _window
from .NativeInstrumentCurrent import _original_method
from .NativeMarketEvidence import _markets, _public_environment, _sdk


SCHEMA = "chan-binance-last-price-evidence-v1"
_METHOD, _ENDPOINT = "fapiPublicV2GetTickerPrice", "/fapi/v2/ticker/price"
_ROOT = Path(__file__).resolve().parents[1]
_SOURCES = ("Trade/NativeLastPrice.py", "Trade/NativeCapacityEvidence.py", "Trade/NativeInstrumentCurrent.py",
            "Trade/NativeMarketEvidence.py", "Trade/AccountIdentity.py", "Trade/AccountSources.py",
            "Trade/ExecutionFacts.py", "CustomBuySellPoint/Decision.py", "Common/KLineTime.py")


def _fail():
    raise CChanException("Binance Last V2原来源/精确正文/显式窗口缺失或漂移；不构成资金或下单准入",
                         ErrCode.TRADE_UNLOCK_FAIL) from None


def _implementation():
    return {name: hashlib.sha256((_ROOT/name).read_bytes()).hexdigest() for name in _SOURCES}


def _environment(exchange, reference, mode):
    environment = _public_environment(exchange, reference, "binance", mode)
    route = exchange.urls["api"]["fapiPublicV2"]
    if route != reference.urls["api"]["fapiPublicV2"]:
        _fail()
    environment["public_routes"]["fapiPublicV2"] = _https(route)
    return environment


def _values(instrument, wire):
    raw = _raw(wire, ("symbol", "price", "time"))
    if (set(raw) != {"symbol", "price", "time"} or raw["symbol"] != instrument
            or type(raw["time"]) is not int or not 0 <= raw["time"] < 2**63):
        _fail()
    return {"raw": raw, "source_ms": raw["time"], "clock_kind": "transaction_time",
            "price": _string(_number(raw["price"], positive=True))}


def _windows(payload, checked, max_age_ms, max_observation_span_ms):
    _window(payload["started_ms"], payload["finished_ms"], checked, max_age_ms, max_observation_span_ms)
    for row in payload["observations"]:
        if not 0 <= row["source_ms"] <= row["finished_ms"] <= checked or checked-row["source_ms"] > max_age_ms:
            _fail()


def _elapsed(started):
    ended = _monotonic_ns()
    if type(started) is not int or type(ended) is not int or not 0 <= started <= ended:
        _fail()
    return (ended-started+999_999)//1_000_000


def verify_binance_last_prices(document, *, max_age_ms, max_observation_span_ms):
    """Recompute source/route/clocks at use; matching JSON is not owned I/O."""
    return _verify_binance_last_prices_at(document, checked_ms=None, max_age_ms=max_age_ms,
                                          max_observation_span_ms=max_observation_span_ms)


def _verify_binance_last_prices_at(document, *, checked_ms, max_age_ms, max_observation_span_ms):
    """Private immutable-intent as-of read; never renew a current source."""
    try:
        tick_start = _monotonic_ns() if checked_ms is None else None
        _budget(max_age_ms, max_observation_span_ms)
        original = canonical_bytes(document)
        values = json.loads(original)
        p = values["payload"]
        implementation = _implementation()
        keys = {"exchange_id", "venue", "mode", "environment", "sdk", "implementation_sha256", "markets", "observations",
                "started_ms", "finished_ms", "requests", "coverage", "economics_complete", "native_admission_verified"}
        if (set(values) != {"schema", "payload", "payload_sha256"} or values["schema"] != SCHEMA
                or values["payload_sha256"] != _sha(p) or set(p) != keys
                or p["exchange_id"] not in {"binance", "binanceusdm"} or p["venue"] != "binance"
                or p["mode"] not in {"live", "testnet"} or p["implementation_sha256"] != implementation
                or p["economics_complete"] is not False or p["native_admission_verified"] is not False
                or p["coverage"] != "observed_native_last_transaction_prices"):
            _fail()
        import ccxt
        reference = getattr(ccxt, p["exchange_id"])()
        if p["mode"] == "testnet":
            reference.set_sandbox_mode(True)
        if p["sdk"] != _sdk(reference, ccxt) or p["environment"] != _environment(reference, reference, p["mode"]):
            _fail()
        units = _markets(p["markets"], p["exchange_id"])
        if (canonical_bytes(units) != canonical_bytes(p["markets"]) or type(p["observations"]) is not list
                or type(p["requests"]) is not int or p["requests"] != len(units) or len(p["observations"]) != len(units)):
            _fail()
        previous = p["started_ms"]
        for unit, row in zip(units, p["observations"]):
            if (set(row) != {"instrument_id", "endpoint", "method", "params", "started_ms", "finished_ms",
                             "raw", "source_ms", "clock_kind", "price"}
                    or (row["instrument_id"], row["endpoint"], row["method"]) != (unit["id"], _ENDPOINT, _METHOD)
                    or row["params"] != {"symbol": unit["id"]}
                    or any(type(row[key]) is not int for key in ("started_ms", "finished_ms", "source_ms"))
                    or not 0 <= previous <= row["started_ms"] <= row["finished_ms"] <= p["finished_ms"]
                    or canonical_bytes({key: row[key] for key in ("raw", "source_ms", "clock_kind", "price")}) !=
                       canonical_bytes(_values(unit["id"], row["raw"]))):
                _fail()
            previous = row["finished_ms"]
        checked = utc_now_ms() if checked_ms is None else checked_ms
        _windows(p, checked, max_age_ms, max_observation_span_ms)
        if implementation != _implementation() or canonical_bytes(document) != original:
            _fail()
        if checked_ms is None:
            _windows(p, checked+_elapsed(tick_start), max_age_ms, max_observation_span_ms)
        return document
    except Exception:
        _fail()


def collect_binance_last_prices(exchange, markets, *, mode, max_age_ms, max_observation_span_ms):
    """Use only explicit single-symbol V2 native GETs, never a ticker cache."""
    try:
        _budget(max_age_ms, max_observation_span_ms)
        provided = {"markets": markets, "mode": mode, "max_age_ms": max_age_ms, "max_observation_span_ms": max_observation_span_ms}
        original = canonical_bytes(provided)
        started, exchange_id = utc_now_ms(), exchange.id
        _window(started, started, started, max_age_ms, max_observation_span_ms)
        if exchange_id not in {"binance", "binanceusdm"} or mode not in {"live", "testnet"}:
            _fail()
        import ccxt
        units = _markets(json.loads(original)["markets"], exchange_id)
        reference = getattr(ccxt, exchange_id)()
        if mode == "testnet":
            reference.set_sandbox_mode(True)
        environment, sdk, implementation = _environment(exchange, reference, mode), _sdk(exchange, ccxt), _implementation()
        def state():
            if (exchange.id != exchange_id or type(exchange) is not type(reference)
                    or _environment(exchange, reference, mode) != environment or _sdk(exchange, ccxt) != sdk
                    or exchange.validateServerSsl is not True or exchange.enableLastHttpResponse is not True
                    or exchange.returnResponseHeaders is not False or canonical_bytes(provided) != original):
                _fail()
            for name in (_METHOD, "request", "fetch2", "fetch", "sign", "parse_json", "on_rest_response", "set_last_request",
                         "handle_option_integer_and_params"):
                _original_method(exchange, name, getattr(reference, name).__func__)
            if exchange.on_json_response is not reference.on_json_response:
                _fail()
            retries, _ = exchange.handle_option_integer_and_params({}, "ticker/price", "maxRetriesOnFailure", 0)
            if type(retries) is not int or retries != 0:
                _fail()
            return _sha({key: getattr(exchange, key, None) for key in ("apiKey", "secret", "password", "options", "proxies",
                "proxyUrl", "httpProxy", "httpsProxy", "socksProxy", "validateServerSsl", "enableLastHttpResponse")})
        frozen = state()
        def current():
            if state() != frozen or implementation != _implementation():
                _fail()
        observations = []
        for unit in units:
            request_start = utc_now_ms()
            _windows({"started_ms": started, "finished_ms": request_start, "observations": observations}, request_start,
                     max_age_ms, max_observation_span_ms)
            current()
            wire = getattr(exchange, _METHOD)({"symbol": unit["id"]})
            values = _values(unit["id"], _exact_response(exchange, wire))
            current()
            request_end = utc_now_ms()
            observations.append({"instrument_id": unit["id"], "endpoint": _ENDPOINT, "method": _METHOD,
                "params": {"symbol": unit["id"]}, "started_ms": request_start, "finished_ms": request_end, **values})
        current()
        payload = {"exchange_id": exchange_id, "venue": "binance", "mode": mode, "environment": environment, "sdk": sdk,
            "implementation_sha256": implementation, "markets": units, "observations": observations, "started_ms": started,
            "finished_ms": utc_now_ms(), "requests": len(observations), "coverage": "observed_native_last_transaction_prices",
            "economics_complete": False, "native_admission_verified": False}
        encoded = canonical_bytes({"schema": SCHEMA, "payload": payload, "payload_sha256": _sha(payload)})
        document = json.loads(encoded)
        verify_binance_last_prices(document, max_age_ms=max_age_ms, max_observation_span_ms=max_observation_span_ms)
        tail_start, checked = _monotonic_ns(), utc_now_ms()
        _windows(payload, checked, max_age_ms, max_observation_span_ms)
        current()
        if canonical_bytes(document) != encoded:
            _fail()
        _windows(payload, checked+_elapsed(tail_start), max_age_ms, max_observation_span_ms)
        return document
    except Exception:
        _fail()
