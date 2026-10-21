"""Native account namespace plus the effective CCXT private environment.

Only digests of typed native identifiers are published. This is an observed
client context, not a server signature, historical ownership or certification.
No CCXT import is required to read an existing context.
"""
import hashlib
import re
from urllib.parse import urlsplit

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes


SCHEMA = "chan-account-context-v1"
_ROUTES = {"binance": ("fapiPrivate", "fapiPrivateV2", "fapiPrivateV3"), "okx": ("rest",)}
_KINDS = {"binance": "futures_account_alias", "okx": "uid"}


def _fail():
    raise CChanException("原生账户/交易环境身份缺失或漂移，禁止跨账户操作", ErrCode.TRADE_UNLOCK_FAIL) from None


def _digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _https(value):
    if not isinstance(value, str):
        _fail()
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
        _fail()
    return value


def verify_account_context(context):
    """Fresh byte/shape validation; a resealed local object is not native proof."""
    try:
        if (not isinstance(context, dict) or set(context) != {"schema", "venue", "mode", "identifier_kind",
                "identifier_sha256", "environment", "context_id"} or context["schema"] != SCHEMA
                or context["venue"] not in _ROUTES or context["mode"] not in {"testnet", "live"}
                or context["identifier_kind"] != _KINDS[context["venue"]]
                or not isinstance(context["identifier_sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", context["identifier_sha256"]) is None):
            _fail()
        env = context["environment"]
        if (set(env) != {"sandbox", "private_routes", "hostname", "simulated_trading"}
                or env["sandbox"] is not (context["mode"] == "testnet")
                or set(env["private_routes"]) != set(_ROUTES[context["venue"]])):
            _fail()
        for value in env["private_routes"].values():
            _https(value)
        if context["venue"] == "binance":
            if env["hostname"] is not None or env["simulated_trading"] is not None:
                _fail()
        elif (not isinstance(env["hostname"], str) or not env["hostname"]
                or env["simulated_trading"] not in (("1",) if env["sandbox"] else (None, "0"))):
            _fail()
        if context["context_id"] != _digest({k: v for k, v in context.items() if k != "context_id"}):
            _fail()
    except (TypeError, ValueError, KeyError, AttributeError):
        _fail()


def _environment(exchange, reference, venue, mode):
    sandbox = mode == "testnet"
    if getattr(exchange, "isSandboxModeEnabled", None) is not sandbox or getattr(exchange, "verify", None) is not True:
        _fail()
    headers = getattr(exchange, "headers", None) or {}
    if not isinstance(headers, dict):
        _fail()
    simulated = [v for k, v in headers.items() if isinstance(k, str) and k.lower() == "x-simulated-trading"]
    if len(simulated) > 1:
        _fail()
    header = simulated[0] if simulated else None
    if ((venue == "binance" and header is not None)
            or (venue == "okx" and header not in (("1",) if sandbox else (None, "0")))):
        _fail()
    hostname = getattr(exchange, "hostname", None) if venue == "okx" else None
    if venue == "okx" and hostname != reference.hostname:
        _fail()
    actual, expected = exchange.urls["api"], reference.urls["api"]
    routes = {}
    for key in _ROUTES[venue]:
        if actual[key] != expected[key]:
            _fail()
        routes[key] = _https(actual[key].replace("{hostname}", hostname) if hostname else actual[key])
    return {"sandbox": sandbox, "private_routes": routes, "hostname": hostname, "simulated_trading": header}


def observe_account_context(exchange, mode):
    """Check routing before private I/O and again before publishing the digest.

    Binance Futures uses its unique accountAlias, not a Spot/demo account uid.
    OKX uses the requesting account uid from /account/config. Never persist raw
    balances, configuration blobs, keys, identifiers or exception bodies.
    """
    import ccxt  # optional boundary, deliberately outside the redacted I/O try
    try:
        exchange_id = exchange.id
        venue = "binance" if exchange_id in {"binance", "binanceusdm"} else exchange_id
        if venue not in _ROUTES or mode not in {"testnet", "live"}:
            _fail()
        reference = getattr(ccxt, exchange_id)()
        if mode == "testnet":
            reference.set_sandbox_mode(True)
        environment = _environment(exchange, reference, venue, mode)
        if venue == "binance":
            rows = exchange.fapiPrivateV3GetBalance({})
            if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
                _fail()
            values = [row.get("accountAlias") for row in rows]
            if any(not isinstance(v, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", v) is None for v in values):
                _fail()
            if len(set(values)) != 1:
                _fail()
            identifier = values[0]
        else:
            response = exchange.privateGetAccountConfig({})
            if (not isinstance(response, dict) or response.get("code") != "0"
                    or not isinstance(response.get("data"), list) or len(response["data"]) != 1):
                _fail()
            identifier = response["data"][0].get("uid")
            if not isinstance(identifier, str) or re.fullmatch(r"[0-9]{1,64}", identifier) is None:
                _fail()
        if environment != _environment(exchange, reference, venue, mode):
            _fail()
        result = {"schema": SCHEMA, "venue": venue, "mode": mode, "identifier_kind": _KINDS[venue],
            "identifier_sha256": _digest({"venue": venue, "kind": _KINDS[venue], "value": identifier}),
            "environment": environment}
        result["context_id"] = _digest(result)
        verify_account_context(result)
        return result
    except Exception:
        _fail()
