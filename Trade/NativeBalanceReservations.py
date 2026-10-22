"""Native balance/configuration components, not per-order cash or admission.

No currency conversion, margin formula, balance inference or order state is
implemented here. Missing/inapplicable native amounts remain unknown.
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
from .AccountSources import _ACCOUNT_POSITION, _ACCOUNT_RAW, _ASSET_RAW, _raw, _text
from .ExecutionFacts import MAX_REQUESTS, _MONEY, _currency, _number, _string, _time
from .NativeMarketEvidence import _sdk


SCHEMA = "chan-native-balance-reservations-v1"
_ROOT = Path(__file__).resolve().parents[1]
_SOURCES = ("Trade/NativeBalanceReservations.py", "Trade/AccountSources.py", "Trade/AccountIdentity.py",
            "Trade/ExecutionFacts.py", "Trade/NativeMarketEvidence.py", "CustomBuySellPoint/Decision.py", "Common/KLineTime.py")
_CONFIG = {"binance": ("canTrade", "dualSidePosition", "multiAssetsMargin", "updateTime"),
           "okx": ("acctLv", "posMode", "autoLoan", "enableSpotBorrow", "ctIsoMode", "roleType", "spotRoleType", "stgyType", "settleCcy")}
_TOTALS = {"binance": (*_ACCOUNT_RAW["binance"], "totalPositionInitialMargin", "totalOpenOrderInitialMargin",
                       "totalCrossWalletBalance", "totalCrossUnPnl", "maxWithdrawAmount"),
           "okx": (*_ACCOUNT_RAW["okx"], "ordFroz", "adjEq", "availEq", "borrowFroz", "notionalUsd")}
_ASSETS = {"binance": (*_ASSET_RAW["binance"], "positionInitialMargin", "openOrderInitialMargin", "maxWithdrawAmount"),
           "okx": (*_ASSET_RAW["okx"], "frozenBal", "ordFrozen", "isoUpl", "isoLiab", "crossLiab", "uplLiab",
                   "stgyEq", "smtSyncEq", "spotCopyTradingEq", "fixedBal", "spotIsoBal", "borrowFroz", "eqUsd")}
_POSITIONS = (*_ACCOUNT_POSITION, "positionInitialMargin", "openOrderInitialMargin")
_ROLES = ("configuration_before", "balance", "configuration_after")
_DISCLOSURES = ["balance_and_configuration_observations_not_atomic", "aggregate_order_margin_not_per_order",
                "positions_and_pending_require_separate_sources", "missing_or_inapplicable_amounts_remain_unknown",
                "usd_totals_not_converted_to_settlement_cash", "sdk_internal_retries_unverified"]


def _fail():
    raise CChanException("原生余额/预占/账户模式来源不完整，不构成资金准入", ErrCode.TRADE_UNLOCK_FAIL) from None


def _sha(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _implementation():
    return {name: hashlib.sha256((_ROOT/name).read_bytes()).hexdigest() for name in _SOURCES}


def _request(venue, role):
    if venue == "binance":
        return (("/fapi/v3/account", "fapiPrivateV3GetAccount") if role == "balance"
                else ("/fapi/v1/accountConfig", "fapiPrivateGetAccountConfig"))
    return (("/api/v5/account/balance", "privateGetAccountBalance") if role == "balance"
            else ("/api/v5/account/config", "privateGetAccountConfig"))


def _configuration(value, venue):
    result = _raw(value, _CONFIG[venue])
    if venue == "binance":
        if any(type(result[key]) is not bool for key in ("canTrade", "dualSidePosition", "multiAssetsMargin")):
            _fail()
        if "updateTime" in result:
            _time(result["updateTime"])  # Reserved field, NOT an observation/generation clock.
    else:
        _text(result["acctLv"])
        if result["posMode"] not in {"net_mode", "long_short_mode"}:
            _fail()
        for key in ("autoLoan", "enableSpotBorrow"):
            if key in result and type(result[key]) is not bool:
                _fail()
        for key in set(result)-{"autoLoan", "enableSpotBorrow"}:
            _text(result[key], empty=key == "settleCcy")
        if "settleCcyList" in value:
            values = value["settleCcyList"]
            if type(values) is not list or len(set(values)) != len(values):
                _fail()
            result["settleCcyList"] = [_currency(item) for item in values]
    return result


def _balance_raw(value, venue):
    result = _raw(value, _TOTALS[venue])
    key = "assets" if venue == "binance" else "details"
    if type(value[key]) is not list:
        _fail()
    result[key] = [_raw(row, _ASSETS[venue]) for row in value[key]]
    if venue == "binance":
        if type(value["positions"]) is not list:
            _fail()
        result["positions"] = [_raw(row, _POSITIONS) for row in value["positions"]]
    return result


def _amounts(row, fields):
    return {key: None if key not in row or row[key] == "" else _string(_number(row[key])) for key in fields}


def _balance_values(raw, venue, configuration, request_end):
    assets, positions, seen = [], [], set()
    label, clock = ("asset", "updateTime") if venue == "binance" else ("ccy", "uTime")
    for row in raw["assets" if venue == "binance" else "details"]:
        currency, updated = _currency(row[label]), _time(row[clock])
        if currency in seen or updated > request_end:
            _fail()
        seen.add(currency)
        assets.append({"currency": currency, "update_ms": updated,
                       "native_fields": _amounts(row, set(_ASSETS[venue])-{label, clock})})
    totals = {"currency": ("USD" if configuration["multiAssetsMargin"] else "USDT") if venue == "binance" else "USD",
              "update_ms": None if venue == "binance" else _time(raw["uTime"]),
              "native_fields": _amounts(raw, set(_TOTALS[venue])-{"uTime"})}
    if totals["update_ms"] is not None and totals["update_ms"] > request_end:
        _fail()
    seen.clear()
    for row in raw.get("positions", []):
        instrument, side, updated = _text(row["symbol"]), row["positionSide"], _time(row["updateTime"])
        if side not in {"BOTH", "LONG", "SHORT"} or (instrument, side) in seen or updated > request_end:
            _fail()
        seen.add((instrument, side))
        positions.append({"instrument_id": instrument, "position_side": side, "update_ms": updated, "quantity_unit": "base_currency",
                          "native_fields": _amounts(row, set(_POSITIONS)-{"symbol", "positionSide", "updateTime"})})
    return {"assets": sorted(assets, key=lambda row: row["currency"]), "reported_totals": totals,
            "native_account_positions": sorted(positions, key=lambda row: (row["instrument_id"], row["position_side"]))}


def _derive(observations, venue, context, started, finished):
    if type(observations) is not list or [row["role"] for row in observations] != list(_ROLES):
        _fail()
    previous = started
    for row in observations:
        if (set(row) != {"role", "method", "endpoint", "params", "started_ms", "request_started_ms", "request_finished_ms", "finished_ms", "raw", "response_identifier_sha256"}
                or (row["endpoint"], row["method"]) != _request(venue, row["role"]) or row["params"] != {}
                or row["response_identifier_sha256"] != (context["identifier_sha256"] if venue == "okx" and row["role"] != "balance" else None)
                or any(type(row[key]) is not int for key in ("started_ms", "request_started_ms", "request_finished_ms", "finished_ms"))
                or not previous <= row["started_ms"] <= row["request_started_ms"] <= row["request_finished_ms"] <= row["finished_ms"] <= finished):
            _fail()
        clean = _balance_raw(row["raw"], venue) if row["role"] == "balance" else _configuration(row["raw"], venue)
        if canonical_bytes(clean) != canonical_bytes(row["raw"]):
            _fail()
        previous = row["finished_ms"]
    configuration = observations[0]["raw"]
    if canonical_bytes(configuration) != canonical_bytes(observations[-1]["raw"]):
        _fail()
    with localcontext(_MONEY):
        return {"configuration": configuration,
                **_balance_values(observations[1]["raw"], venue, configuration, observations[1]["request_finished_ms"])}


def verify_native_balance_reservations(document):
    """Recompute saved native fields; this does not authenticate their transport."""
    try:
        p = document["payload"]
        venue, exchange_id = p["venue"], p["exchange_id"]
        verify_account_context(p["account_context"])
        if (set(document) != {"schema", "payload", "payload_sha256"} or document["schema"] != SCHEMA
                or document["payload_sha256"] != _sha(p)
                or set(p) != {"exchange_id", "venue", "mode", "account_context", "sdk", "implementation_sha256", "observations",
                              "started_ms", "finished_ms", "requests", "source_requests", "identity_requests", "coverage",
                              "economics_complete", "native_admission_verified", "disclosures", "configuration", "assets", "reported_totals", "native_account_positions"}
                or exchange_id not in {"binance", "binanceusdm", "okx"} or venue != ("okx" if exchange_id == "okx" else "binance")
                or p["account_context"]["venue"] != venue or p["account_context"]["mode"] != p["mode"]
                or p["coverage"] != "reported_balance_and_configuration_components"
                or p["economics_complete"] is not False or p["native_admission_verified"] is not False
                or p["disclosures"] != _DISCLOSURES or p["implementation_sha256"] != _implementation()
                or any(type(p[key]) is not int for key in ("started_ms", "finished_ms", "requests", "source_requests", "identity_requests"))
                or not 0 <= p["started_ms"] <= p["finished_ms"] <= utc_now_ms()
                or (p["requests"], p["source_requests"], p["identity_requests"]) != (9, 3, 6) or p["requests"] > MAX_REQUESTS):
            _fail()
        sdk = p["sdk"]
        if (set(sdk) != {"name", "version", "exchange_class", "source_sha256"} or sdk["name"] != "ccxt"
                or type(sdk["version"]) is not str or re.fullmatch(r"[0-9][A-Za-z0-9.+_-]{0,63}", sdk["version"]) is None
                or sdk["exchange_class"] != "ccxt."+exchange_id+"."+exchange_id
                or type(sdk["source_sha256"]) is not dict or not sdk["source_sha256"]
                or any(type(key) is not str or re.fullmatch(r"ccxt\.[A-Za-z0-9_.]+", key) is None
                       or type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None for key, value in sdk["source_sha256"].items())):
            _fail()
        values = _derive(p["observations"], venue, p["account_context"], p["started_ms"], p["finished_ms"])
        if any(canonical_bytes(p[key]) != canonical_bytes(value) for key, value in values.items()):
            _fail()
        return document
    except Exception:
        _fail()


def collect_native_balance_reservations(exchange, *, mode):
    """Collect only GETs outside DB locks; current consumers must own this call."""
    try:
        import ccxt
        started, exchange_id = utc_now_ms(), exchange.id
        if exchange_id not in {"binance", "binanceusdm", "okx"} or mode not in {"testnet", "live"}:
            _fail()
        venue = "okx" if exchange_id == "okx" else "binance"
        reference = getattr(ccxt, exchange_id)()
        if mode == "testnet":
            reference.set_sandbox_mode(True)
        environment, sdk, implementation = _environment(exchange, reference, venue, mode), _sdk(exchange, ccxt), _implementation()
        context, observations = None, []
        def current():
            if (exchange.id != exchange_id or type(exchange) is not type(reference)
                    or _environment(exchange, reference, venue, mode) != environment or _sdk(exchange, ccxt) != sdk):
                _fail()
        for role in _ROLES:
            begin = utc_now_ms()
            current()
            before = observe_account_context(exchange, mode)
            current()
            if context is None:
                context = before
            if canonical_bytes(before) != canonical_bytes(context) or (len(observations)+1)*3 > MAX_REQUESTS:
                _fail()
            endpoint, method = _request(venue, role)
            request_start = utc_now_ms()
            wire = getattr(exchange, method)({})
            current()
            request_end = utc_now_ms()
            if venue == "okx":
                if type(wire) is not dict or wire.get("code") != "0" or type(wire["data"]) is not list or len(wire["data"]) != 1:
                    _fail()
                wire = wire["data"][0]
            response_identifier = None
            if venue == "okx" and role != "balance":
                uid = wire["uid"]
                if type(uid) is not str or re.fullmatch(r"[0-9]{1,64}", uid) is None:
                    _fail()
                response_identifier = _sha({"venue": venue, "kind": "uid", "value": uid})
                if response_identifier != context["identifier_sha256"]:
                    _fail()
            raw = _balance_raw(wire, venue) if role == "balance" else _configuration(wire, venue)
            if role == "balance":
                with localcontext(_MONEY):
                    _balance_values(raw, venue, observations[0]["raw"], request_end)
            if canonical_bytes(observe_account_context(exchange, mode)) != canonical_bytes(context):
                _fail()
            current()
            observations.append({"role": role, "method": method, "endpoint": endpoint, "params": {}, "raw": raw,
                                 "response_identifier_sha256": response_identifier,
                                 "started_ms": begin, "request_started_ms": request_start, "request_finished_ms": request_end, "finished_ms": utc_now_ms()})
        current()
        if implementation != _implementation():
            _fail()
        finished = utc_now_ms()
        values = _derive(observations, venue, context, started, finished)
        payload = {"exchange_id": exchange_id, "venue": venue, "mode": mode, "account_context": context,
                   "sdk": sdk, "implementation_sha256": implementation, "observations": observations,
                   "started_ms": started, "finished_ms": finished, "requests": 9, "source_requests": 3, "identity_requests": 6,
                   "coverage": "reported_balance_and_configuration_components", "economics_complete": False,
                   "native_admission_verified": False, "disclosures": list(_DISCLOSURES), **values}
        return verify_native_balance_reservations(json.loads(canonical_bytes({"schema": SCHEMA, "payload": payload, "payload_sha256": _sha(payload)})))
    except Exception:
        _fail()
