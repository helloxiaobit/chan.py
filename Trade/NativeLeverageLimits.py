"""Provided-book/native-limit comparisons, never per-order funding authority.

The capacity source supplies its own markets and configurations. Raw book and
hypothetical price origin remain unverified; no DB, order or configuration is
read or written, and no source is refreshed here.
"""
import json
from fractions import Fraction
from time import monotonic_ns as _monotonic_ns

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from . import NativeCapacityEvidence as Capacity
from .AccountReconcile import _ratio, _sha
from .NativeCapacityEvidence import verify_binance_capacity_evidence
from .NativeMarginEnvelope import _n, calculate_binance_margin_envelope


SCHEMA = "chan-binance-leverage-limits-v1"


def _fail():
    raise CChanException("Binance杠杆/名义限额来源、完整档位或输入不明确；不构成逐单资金或下单准入",
                         ErrCode.TRADE_UNLOCK_FAIL) from None


def _compatible_cap(raw, leverage):
    if "notionalCoef" in raw and _n(raw["notionalCoef"], positive=True) != 1:
        _fail()  # The API does not establish whether its returned ranges are already adjusted.
    previous_cap, previous_leverage, compatible_cap = Fraction(0), None, None
    for number, tier in enumerate(raw["brackets"], 1):
        floor, cap = _n(tier["notionalFloor"]), _n(tier["notionalCap"], positive=True)
        maximum_leverage = _n(tier["initialLeverage"], positive=True)
        if (int(tier["bracket"]) != number or floor != previous_cap or cap <= previous_cap
                or (previous_leverage is not None and maximum_leverage > previous_leverage)):
            _fail()
        if leverage <= maximum_leverage:
            compatible_cap = cap
        previous_cap, previous_leverage = cap, maximum_leverage
    return compatible_cap


def evaluate_binance_leverage_limits(capacity_evidence, *, positions, pending_orders, mark_prices,
                                     position_mode, candidate, max_age_ms, max_observation_span_ms):
    """Recompute, never consume a caller's pre-approved or resealed book result."""
    try:
        tick_start, checked = _monotonic_ns(), Capacity.utc_now_ms()
        provided = {"capacity_evidence": capacity_evidence, "positions": positions, "pending_orders": pending_orders,
            "mark_prices": mark_prices, "position_mode": position_mode, "candidate": candidate,
            "max_age_ms": max_age_ms, "max_observation_span_ms": max_observation_span_ms}
        original = canonical_bytes(provided)
        inputs = json.loads(original)
        source = inputs["capacity_evidence"]
        verify_binance_capacity_evidence(source, max_age_ms=max_age_ms, max_observation_span_ms=max_observation_span_ms)
        p = source["payload"]
        Capacity._window(p["started_ms"], p["finished_ms"], checked, max_age_ms, max_observation_span_ms)
        configs = {row["instrument_id"]: row["raw"] for row in p["observations"] if row["role"] == "configuration"}
        brackets = {row["instrument_id"]: row["raw"] for row in p["observations"] if row["role"] == "brackets"}
        book = calculate_binance_margin_envelope(markets=p["markets"], positions=inputs["positions"],
            pending_orders=inputs["pending_orders"], mark_prices=inputs["mark_prices"], symbol_configs=list(configs.values()),
            position_mode=inputs["position_mode"], candidate=inputs["candidate"])
        limits, issues = [], []
        for row in book["payload"]["books"]:
            instrument = row["instrument_id"]
            config = configs[instrument]
            leverage, configuration_cap = _n(config["leverage"], positive=True), _n(config["maxNotionalValue"], positive=True)
            cap = _compatible_cap(brackets[instrument], leverage)
            if cap is None:
                issues.append({"instrument_id": instrument, "reason": "leverage_unsupported"})
            values = {}
            for label in ("before", "after"):
                raw = row[label+"_exposure_notional"]
                value = Fraction(int(raw["numerator"]), int(raw["denominator"]))
                values[label+"_exposure_notional"] = raw
                for reason, bound in (("configuration_cap", configuration_cap), ("compatible_bracket_cap", cap)):
                    if bound is not None and value > bound:
                        issues.append({"instrument_id": instrument, "phase": label, "reason": reason+"_exceeded"})
            limits.append({"instrument_id": instrument, "leverage": _ratio(leverage), "configuration_cap": _ratio(configuration_cap),
                "compatible_bracket_cap": _ratio(cap) if cap is not None else None, **values})
        payload = {"capacity_evidence_sha256": _sha(source), "provided_inputs_sha256": _sha(inputs),
            "account_context": p["account_context"], "margin_envelope": book, "limits": limits, "issues": issues,
            "status": "exceeds_observed_limits" if issues else "within_observed_limits",
            "coverage": "provided_book_against_observed_limits_only", "book_origin_verified": False,
            "economics_complete": False, "native_admission_verified": False}
        document = json.loads(canonical_bytes({"schema": SCHEMA, "payload": payload, "payload_sha256": _sha(payload)}))
        verify_binance_capacity_evidence(source, max_age_ms=max_age_ms, max_observation_span_ms=max_observation_span_ms)
        if canonical_bytes(provided) != original:
            _fail()
        tick_end = _monotonic_ns()
        if type(tick_start) is not int or type(tick_end) is not int or not 0 <= tick_start <= tick_end:
            _fail()
        # Conservative whole-evaluation bound, not another source timestamp.
        Capacity._window(p["started_ms"], p["finished_ms"], checked+(tick_end-tick_start+999_999)//1_000_000,
                         max_age_ms, max_observation_span_ms)
        return document
    except Exception:
        _fail()
