"""Binance raw fee/settings/bracket inputs, never a money model or admission.

Numeric JSON tokens are read from the same SDK call's retained response body,
not reconstructed from float or a leverage cache. The allowlisted projection
is local interpretation evidence, not an authenticated server receipt. No SDK,
configuration or network activity occurs at import; no orders or DB writes.
"""
import hashlib
import json
from decimal import localcontext
from pathlib import Path
from time import monotonic_ns as _monotonic_ns

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountIdentity import _environment, observe_account_context, verify_account_context
from .AccountSources import _raw
from .ExecutionFacts import MAX_REQUESTS, _MONEY, _id, _number
from .NativeMarketEvidence import _markets, _sdk


SCHEMA = "chan-binance-capacity-evidence-v1"
_ROOT = Path(__file__).resolve().parents[1]
_SOURCES = ("Trade/NativeCapacityEvidence.py", "Trade/AccountIdentity.py", "Trade/AccountSources.py",
            "Trade/ExecutionFacts.py", "Trade/NativeMarketEvidence.py", "CustomBuySellPoint/Decision.py", "Common/KLineTime.py")
_REQUESTS = {"fee_burn": ("/fapi/v1/feeBurn", "fapiPrivateGetFeeBurn"),
             "commission": ("/fapi/v1/commissionRate", "fapiPrivateGetCommissionRate"),
             "configuration": ("/fapi/v1/symbolConfig", "fapiPrivateGetSymbolConfig"),
             "brackets": ("/fapi/v1/leverageBracket", "fapiPrivateGetLeverageBracket")}
_FIELDS = {"fee_burn": ("feeBurn",),
           "commission": ("symbol", "makerCommissionRate", "takerCommissionRate", "rpiCommissionRate"),
           "configuration": ("symbol", "marginType", "isAutoAddMargin", "leverage", "maxNotionalValue"),
           "brackets": ("symbol", "notionalCoef")}
_TIER_FIELDS = ("bracket", "initialLeverage", "notionalFloor", "notionalCap", "maintMarginRatio", "cum")
_DISCLOSURES = ["observations_not_atomic", "local_request_window_not_native_generation_time",
                "raw_notional_coefficient_not_applied", "fee_currency_and_order_capacity_not_inferred",
                "negative_rates_not_available_cash", "selected_sdk_path_not_whole_host_attestation"]


def _fail():
    raise CChanException("Binance原生资金参数/精确正文/显式窗口缺失或漂移；不构成逐单资金或下单准入",
                         ErrCode.TRADE_UNLOCK_FAIL) from None


def _sha(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _implementation():
    return {name: hashlib.sha256((_ROOT/name).read_bytes()).hexdigest() for name in _SOURCES}


def _budget(max_age_ms, max_observation_span_ms):
    if any(type(value) is not int or not 0 <= value < 2**63 for value in (max_age_ms, max_observation_span_ms)):
        _fail()


def _window(started, finished, checked, max_age_ms, max_observation_span_ms):
    if (any(type(value) is not int for value in (started, finished, checked))
            or not 0 <= started <= finished <= checked < 2**63
            or checked-started > max_age_ms or finished-started > max_observation_span_ms):
        _fail()


def _pool(markets, exchange_id):
    markets = _markets(markets, exchange_id)
    if 3*(1+3*len(markets)) > MAX_REQUESTS:
        _fail()
    return markets


def _roles(markets):
    return [("fee_burn", None)]+[(role, market["id"]) for market in markets
                                for role in ("commission", "configuration", "brackets")]


def _raw_values(role, instrument, wire):
    raw = _raw(wire, _FIELDS[role])
    required = set(_FIELDS[role])-({"rpiCommissionRate"} if role == "commission" else
                                  {"notionalCoef"} if role == "brackets" else set())
    if not required <= set(raw) or (role != "fee_burn" and raw["symbol"] != instrument):
        _fail()
    with localcontext(_MONEY):
        if role == "fee_burn":
            if type(raw["feeBurn"]) is not bool:
                _fail()
        elif role == "commission":
            for key in set(raw)-{"symbol"}:
                _number(raw[key])  # Preserve signed rates; never credit a rebate.
        elif role == "configuration":
            if (raw["marginType"] not in {"CROSSED", "ISOLATED"} or type(raw["isAutoAddMargin"]) is not bool
                    or int(_id(raw["leverage"])) <= 0):
                _fail()
            _number(raw["maxNotionalValue"], positive=True)
        else:
            if "notionalCoef" in raw:
                _number(raw["notionalCoef"], positive=True)  # Do not apply or infer 1.
            tiers = wire["brackets"]
            if type(tiers) is not list or not 1 <= len(tiers) <= MAX_REQUESTS:
                _fail()
            raw["brackets"], seen = [], set()
            for value in tiers:
                tier = _raw(value, _TIER_FIELDS)
                if set(tier) != set(_TIER_FIELDS):
                    _fail()
                identity = int(_id(tier["bracket"]))
                if identity <= 0 or identity in seen or int(_id(tier["initialLeverage"])) <= 0:
                    _fail()
                seen.add(identity)
                floor, cap, ratio, cum = (_number(tier[key]) for key in _TIER_FIELDS[2:])
                if not 0 <= floor < cap or ratio < 0 or cum < 0:
                    _fail()
                raw["brackets"].append(tier)
    return raw


def _exact_response(exchange, wire):
    """Keep raw numeric lexemes; reject duplicate keys and decoded/body mixes."""
    body = exchange.last_http_response
    if type(body) is not str or not 0 < len(body) <= 1_048_576:
        _fail()
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                _fail()
            value[key] = item
        return value
    def invalid(value):
        _fail()
    exact = json.loads(body, parse_float=str, parse_constant=invalid, object_pairs_hook=pairs)
    if canonical_bytes(json.loads(body)) != canonical_bytes(wire):
        _fail()
    return exact


def _shape(role, instrument, wire):
    shape = "single_row_array" if type(wire) is list else "object"
    if type(wire) is list:
        if role not in {"configuration", "brackets"} or len(wire) != 1:
            _fail()
        wire = wire[0]
    elif role == "configuration":
        _fail()
    return shape, _raw_values(role, instrument, wire)


def verify_binance_capacity_evidence(document, *, max_age_ms, max_observation_span_ms):
    """Recompute stored fields and explicit local age, never authenticate I/O."""
    return _verify_binance_capacity_evidence_at(document, checked_ms=None, max_age_ms=max_age_ms,
                                               max_observation_span_ms=max_observation_span_ms)


def _verify_binance_capacity_evidence_at(document, *, checked_ms, max_age_ms, max_observation_span_ms):
    """Internal journal as-of check; None retains the public terminal clock."""
    try:
        _budget(max_age_ms, max_observation_span_ms)
        import ccxt
        p = document["payload"]
        keys = {"exchange_id", "venue", "mode", "account_context", "sdk", "implementation_sha256", "markets", "observations",
                "started_ms", "finished_ms", "requests", "source_requests", "identity_requests", "coverage", "clock_kind",
                "source_ms", "economics_complete", "native_admission_verified", "fee_currency", "notional_coefficient_applied", "disclosures"}
        if (set(document) != {"schema", "payload", "payload_sha256"} or document["schema"] != SCHEMA
                or document["payload_sha256"] != _sha(p) or set(p) != keys
                or p["exchange_id"] not in {"binance", "binanceusdm"} or p["venue"] != "binance"
                or p["mode"] not in {"live", "testnet"} or p["coverage"] != "native_fee_configuration_and_raw_brackets"
                or p["clock_kind"] != "local_request_window_only" or p["source_ms"] is not None
                or p["economics_complete"] is not False or p["native_admission_verified"] is not False
                or p["fee_currency"] is not None or p["notional_coefficient_applied"] is not False
                or p["disclosures"] != _DISCLOSURES or p["implementation_sha256"] != _implementation()):
            _fail()
        reference = getattr(ccxt, p["exchange_id"])()
        if p["mode"] == "testnet":
            reference.set_sandbox_mode(True)
        verify_account_context(p["account_context"])
        if (p["sdk"] != _sdk(reference, ccxt) or p["account_context"]["venue"] != "binance"
                or p["account_context"]["mode"] != p["mode"]
                or p["account_context"]["environment"] != _environment(reference, reference, "binance", p["mode"])):
            _fail()
        markets = _pool(p["markets"], p["exchange_id"])
        roles = _roles(markets)
        if (canonical_bytes(markets) != canonical_bytes(p["markets"]) or type(p["observations"]) is not list
                or len(p["observations"]) != len(roles)
                or any(type(p[key]) is not int for key in ("requests", "source_requests", "identity_requests"))
                or (p["requests"], p["source_requests"], p["identity_requests"]) != (3*len(roles), len(roles), 2*len(roles))):
            _fail()
        previous = p["started_ms"]
        for row, (role, instrument) in zip(p["observations"], roles):
            endpoint, method = _REQUESTS[role]
            times = [row[key] for key in ("started_ms", "request_started_ms", "request_finished_ms", "finished_ms")]
            if (set(row) != {"role", "instrument_id", "method", "endpoint", "params", "response_shape", "raw",
                            "started_ms", "request_started_ms", "request_finished_ms", "finished_ms"}
                    or (row["role"], row["instrument_id"], row["endpoint"], row["method"]) != (role, instrument, endpoint, method)
                    or row["params"] != ({} if instrument is None else {"symbol": instrument})
                    or any(type(at) is not int or not 0 <= at < 2**63 for at in times)
                    or times != sorted(times) or not previous <= times[0] <= times[-1] <= p["finished_ms"]):
                _fail()
            wire = [row["raw"]] if row["response_shape"] == "single_row_array" else row["raw"]
            shape, raw = _shape(role, instrument, wire)
            if row["response_shape"] != shape or canonical_bytes(raw) != canonical_bytes(row["raw"]):
                _fail()
            previous = times[-1]
        _window(p["started_ms"], p["finished_ms"], utc_now_ms() if checked_ms is None else checked_ms,
                max_age_ms, max_observation_span_ms)
        return document
    except Exception:
        _fail()


def collect_binance_capacity_evidence(exchange, markets, *, mode, max_age_ms, max_observation_span_ms):
    """Own fixed GETs and original SDK decoding; never mutate options/cache."""
    try:
        _budget(max_age_ms, max_observation_span_ms)
        provided = {"markets": markets, "mode": mode, "max_age_ms": max_age_ms, "max_observation_span_ms": max_observation_span_ms}
        original = canonical_bytes(provided)
        import ccxt
        started, exchange_id = utc_now_ms(), exchange.id
        _window(started, started, started, max_age_ms, max_observation_span_ms)
        if exchange_id not in {"binance", "binanceusdm"} or mode not in {"live", "testnet"}:
            _fail()
        units = _pool(json.loads(original)["markets"], exchange_id)
        reference = getattr(ccxt, exchange_id)()
        if mode == "testnet":
            reference.set_sandbox_mode(True)
        environment, sdk, implementation = _environment(exchange, reference, "binance", mode), _sdk(exchange, ccxt), _implementation()
        def state():
            if (exchange.id != exchange_id or type(exchange) is not type(reference)
                    or _environment(exchange, reference, "binance", mode) != environment or _sdk(exchange, ccxt) != sdk
                    or exchange.validateServerSsl is not True
                    or exchange.enableLastHttpResponse is not True or exchange.returnResponseHeaders is not False
                    or canonical_bytes(provided) != original):
                _fail()
            names = [method for _, method in _REQUESTS.values()]+["fapiPrivateV3GetBalance", "request", "fetch2", "fetch", "sign",
                    "parse_json", "on_rest_response", "set_last_request", "handle_option_integer_and_params"]
            for name in names:
                actual, expected = getattr(exchange, name), getattr(reference, name)
                if getattr(actual, "__self__", None) is not exchange or getattr(actual, "__func__", None) is not expected.__func__:
                    _fail()
            if exchange.on_json_response is not reference.on_json_response:
                _fail()
            for endpoint in [path.rsplit("/", 1)[-1] for path, _ in _REQUESTS.values()]+["balance"]:
                retries, _ = exchange.handle_option_integer_and_params({}, endpoint, "maxRetriesOnFailure", 0)
                if type(retries) is not int or retries != 0:
                    _fail()
            return _sha({key: getattr(exchange, key, None) for key in ("apiKey", "secret", "password", "options", "proxies",
                "proxyUrl", "httpProxy", "httpsProxy", "socksProxy", "validateServerSsl", "enableLastHttpResponse")})
        frozen = state()
        def current():
            if state() != frozen or implementation != _implementation():
                _fail()
        observations, context = [], None
        for role, instrument in _roles(units):
            begin = utc_now_ms()
            current()
            before = observe_account_context(exchange, mode)
            if context is None:
                context = before
            if canonical_bytes(before) != canonical_bytes(context):
                _fail()
            current()
            endpoint, method = _REQUESTS[role]
            params = {} if instrument is None else {"symbol": instrument}
            request_start = utc_now_ms()
            wire = getattr(exchange, method)(dict(params))
            # Capture before identity GETs overwrite last_http_response.
            shape, raw = _shape(role, instrument, _exact_response(exchange, wire))
            current()
            request_end = utc_now_ms()
            if canonical_bytes(observe_account_context(exchange, mode)) != canonical_bytes(context):
                _fail()
            current()
            observations.append({"role": role, "instrument_id": instrument, "endpoint": endpoint, "method": method,
                "params": params, "response_shape": shape, "raw": raw, "started_ms": begin, "request_started_ms": request_start,
                "request_finished_ms": request_end, "finished_ms": utc_now_ms()})
        current()
        payload = {"exchange_id": exchange_id, "venue": "binance", "mode": mode, "account_context": context, "sdk": sdk,
            "implementation_sha256": implementation, "markets": units, "observations": observations,
            "started_ms": started, "finished_ms": utc_now_ms(), "requests": 3*len(observations), "source_requests": len(observations),
            "identity_requests": 2*len(observations), "coverage": "native_fee_configuration_and_raw_brackets",
            "source_ms": None, "clock_kind": "local_request_window_only", "economics_complete": False,
            "native_admission_verified": False, "fee_currency": None, "notional_coefficient_applied": False, "disclosures": list(_DISCLOSURES)}
        document = json.loads(canonical_bytes({"schema": SCHEMA, "payload": payload, "payload_sha256": _sha(payload)}))
        verify_binance_capacity_evidence(document, max_age_ms=max_age_ms, max_observation_span_ms=max_observation_span_ms)
        tail_start, checked = _monotonic_ns(), utc_now_ms()
        _window(started, payload["finished_ms"], checked, max_age_ms, max_observation_span_ms)
        current()
        tail_end = _monotonic_ns()
        if type(tail_start) is not int or type(tail_end) is not int or not 0 <= tail_start <= tail_end:
            _fail()
        # Same conservative terminal upper bound as the owned cold initializer;
        # this neither invents a native source clock nor extends a budget.
        _window(started, payload["finished_ms"], checked+(tail_end-tail_start+999_999)//1_000_000,
                max_age_ms, max_observation_span_ms)
        return document
    except Exception:
        _fail()
