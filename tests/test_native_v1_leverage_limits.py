"""V1 raw order projection must feed the existing whole-book native limits."""
import copy
from fractions import Fraction

import pytest

from Common.ChanException import CChanException
from Trade import NativeLeverageLimits as Limits
from .test_native_capacity_evidence import native_capacity
from .test_native_margin_envelope import book, fraction
from .test_native_leverage_limits import limit_case, change_native


def evaluate(case):
    assert hasattr(Limits, "evaluate_binance_order_leverage_limits_v1"), "V1 raw order is not connected to native limits"
    return Limits.evaluate_binance_order_leverage_limits_v1(**case)


def v1_case(case):
    values = copy.deepcopy(case)
    values["candidate"].pop("valuation_price")
    values["candidate"].update(order_type="MARKET", limit_price=None, post_only=False, reduce_only=False)
    values["last_prices"] = {"TESTUSDT": "123.12345678901234567890123456789012345678901234567", "ALTUSDT": "20"}
    return values


def test_whole_book_limits_use_v1_exact_r_and_keep_all_non_candidate_symbols(limit_case):
    source, original = limit_case
    case = v1_case(original)
    p = evaluate(case)["payload"]
    assert p["status"] == "within_observed_limits" and p["issues"] == []
    assert p["coverage"] == "provided_book_with_client_v1_against_observed_limits_only"
    assert p["economics_complete"] is p["native_admission_verified"] is False
    assert fraction(p["order_price_projection"]["payload"]["assumed_price"]) == Fraction(case["last_prices"]["TESTUSDT"])*Fraction(2003, 2000)
    assert p["margin_envelope"] == p["order_price_projection"]["payload"]["margin_envelope"]
    assert {row["instrument_id"] for row in p["limits"]} == {"TESTUSDT", "ALTUSDT"}
    change_native(source, case, "configuration", "ALTUSDT", lambda raw: raw[0].update(maxNotionalValue="1"))
    p = evaluate(case)["payload"]
    assert p["status"] == "exceeds_observed_limits"
    assert p["issues"] == [{"instrument_id": "ALTUSDT", "phase": phase, "reason": "configuration_cap_exceeded"}
                            for phase in ("before", "after")]


def test_v1_missing_last_does_not_downgrade_to_a_caller_valuation(limit_case):
    source, original = limit_case
    case = v1_case(original)
    case["last_prices"] = None
    case["candidate"]["valuation_price"] = "1"
    with pytest.raises(CChanException):
        evaluate(case)


@pytest.mark.parametrize("style", ["legacy", "v1"])
def test_terminal_payload_hash_cannot_hide_internal_input_mutation(limit_case, monkeypatch, style):
    source, original = limit_case
    case = original if style == "legacy" else v1_case(original)
    sha, captured = Limits._sha, {}
    def mutate(value):
        result = sha(value)
        if "positions" in value: captured["inputs"] = value
        if "limits" in value: captured["inputs"]["positions"][0]["positionAmt"] = "999"
        return result
    monkeypatch.setattr(Limits, "_sha", mutate)
    with pytest.raises(CChanException):
        Limits.evaluate_binance_leverage_limits(**case) if style == "legacy" else evaluate(case)
