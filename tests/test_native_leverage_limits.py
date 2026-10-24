"""Observed native limits and nonempty provided books, never funding authority."""
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from .test_native_capacity_evidence import collect, native_capacity
from .test_native_margin_envelope import book, corners, fraction


def limits_api():
    assert importlib.util.find_spec("Trade.NativeLeverageLimits") is not None, "native leverage limit evaluation is missing"
    from Trade import NativeLeverageLimits
    return NativeLeverageLimits


@pytest.fixture
def limit_case(native_capacity, book):
    source = native_capacity
    for symbol, leverage, cap in (("TESTUSDT", 3, "10000"), ("ALTUSDT", 7, "5000")):
        source.bodies["configuration", symbol] = json.dumps([{"symbol": symbol, "marginType": "CROSSED",
            "isAutoAddMargin": False, "leverage": leverage, "maxNotionalValue": cap}])
        source.bodies["brackets", symbol] = json.dumps({"symbol": symbol, "brackets": [
            {"bracket": 1, "initialLeverage": 20, "notionalFloor": "0", "notionalCap": "1000", "maintMarginRatio": "0.005", "cum": "0"},
            {"bracket": 2, "initialLeverage": 10, "notionalFloor": "1000", "notionalCap": "5000", "maintMarginRatio": "0.01", "cum": "5"},
            {"bracket": 3, "initialLeverage": 3, "notionalFloor": "5000", "notionalCap": "10000", "maintMarginRatio": "0.025", "cum": "80"}]})
    document = collect(source)
    case = {key: copy.deepcopy(value) for key, value in book.items() if key not in {"markets", "symbol_configs"}}
    case.update(capacity_evidence=document, max_age_ms=1000, max_observation_span_ms=1000)
    return source, case


def evaluate(case):
    return limits_api().evaluate_binance_leverage_limits(**case)


def test_real_native_sources_use_each_symbol_limits_and_recompute_nonempty_book(limit_case):
    source, case = limit_case
    original = canonical_bytes(case)
    source.calls.clear()
    document = evaluate(case)
    assert document["schema"] == "chan-binance-leverage-limits-v1"
    p = document["payload"]
    assert p["status"] == "within_observed_limits"
    assert p["coverage"] == "provided_book_against_observed_limits_only"
    assert all(p[key] is False for key in ("book_origin_verified", "economics_complete", "native_admission_verified"))
    assert p["account_context"] == case["capacity_evidence"]["payload"]["account_context"]
    assert p["capacity_evidence_sha256"] == hashlib.sha256(canonical_bytes(case["capacity_evidence"])).hexdigest()
    assert document["payload_sha256"] == hashlib.sha256(canonical_bytes(p)).hexdigest()
    assert p["issues"] == []
    values = {row["instrument_id"]: row for row in p["limits"]}
    for symbol, leverage, cap in (("TESTUSDT", 3, 10000), ("ALTUSDT", 7, 5000)):
        row = values[symbol]
        assert fraction(row["leverage"]) == leverage
        assert fraction(row["configuration_cap"]) == fraction(row["compatible_bracket_cap"]) == cap
        legs = ("BOTH",) if case["position_mode"] == "one_way" else ("LONG", "SHORT")
        oracle = {**case, "markets": source.markets, "symbol_configs": [
            {"symbol": symbol, "leverage": value} for symbol, value in (("TESTUSDT", 3), ("ALTUSDT", 7))]}
        for label in ("before", "after"):
            expected = sum((corners(oracle, symbol, leg, label == "after")[1] for leg in legs), Fraction())
            assert fraction(row[label+"_exposure_notional"]) == expected
    assert canonical_bytes(case) == original
    assert source.calls == []


def change_native(source, case, role, symbol, mutation):
    raw = json.loads(source.bodies[role, symbol])
    mutation(raw)
    source.bodies[role, symbol] = json.dumps(raw)
    case["capacity_evidence"] = collect(source)


@pytest.mark.parametrize("damage", ["coefficient", "tiny_coefficient", "first_floor", "gap", "overlap",
                                         "missing_middle", "number_gap", "reordered", "rising_leverage"])
def test_ambiguous_adjustments_or_incomplete_topology_never_become_available_capacity(limit_case, damage):
    source, case = limit_case
    def damage_table(raw):
        tiers = raw["brackets"]
        if damage in {"coefficient", "tiny_coefficient"}:
            raw["notionalCoef"] = "1.25" if damage == "coefficient" else "1.000000000000000000000000000001"
        elif damage == "first_floor":
            tiers[0]["notionalFloor"] = "1"
        elif damage in {"gap", "overlap"}:
            tiers[1]["notionalFloor"] = "1001" if damage == "gap" else "999"
        elif damage == "missing_middle":
            del tiers[1]
        elif damage == "number_gap":
            tiers[-1]["bracket"] = 4
        elif damage == "reordered":
            tiers.reverse()
        else:
            tiers[1]["initialLeverage"] = 21
    change_native(source, case, "brackets", "ALTUSDT", damage_table)
    original = canonical_bytes(case)
    source.calls.clear()
    with pytest.raises(CChanException, match="杠杆/名义限额"):
        evaluate(case)
    assert canonical_bytes(case) == original and not source.calls


def test_a_native_leverage_with_no_compatible_bracket_has_no_numeric_cap(limit_case):
    source, case = limit_case
    change_native(source, case, "configuration", "TESTUSDT", lambda raw: raw[0].update(leverage=21))
    p = evaluate(case)["payload"]
    assert p["status"] == "exceeds_observed_limits"
    row = next(row for row in p["limits"] if row["instrument_id"] == "TESTUSDT")
    assert row["compatible_bracket_cap"] is None
    assert p["issues"] == [{"instrument_id": "TESTUSDT", "reason": "leverage_unsupported"}]


@pytest.mark.parametrize("constraint", ["configuration_cap", "compatible_bracket_cap"])
@pytest.mark.parametrize("offset", ["0", "-0.000000000000000000000000000001", "0.000000000000000000000000000001"])
def test_each_independent_cap_accepts_exact_equality_but_not_a_tiny_excess(limit_case, constraint, offset):
    source, case = limit_case
    # Hand totals, not the evaluator's book output: BOTH 325; LONG 275 + SHORT 201.5.
    exact = "325" if case["position_mode"] == "one_way" else "476.5"
    with localcontext() as money:
        money.prec = 60
        bound = str(Decimal(exact)+Decimal(offset))
    if constraint == "configuration_cap":
        change_native(source, case, "configuration", "TESTUSDT", lambda raw: raw[0].update(maxNotionalValue=bound))
    else:
        def table(raw):
            raw["brackets"][0]["notionalCap"] = "100"
            raw["brackets"][1].update(notionalFloor="100", notionalCap="300")
            raw["brackets"][2].update(notionalFloor="300", notionalCap=bound)
        change_native(source, case, "brackets", "TESTUSDT", table)
    p = evaluate(case)["payload"]
    assert p["status"] == ("exceeds_observed_limits" if offset.startswith("-") else "within_observed_limits")
    assert p["issues"] == ([{"instrument_id": "TESTUSDT", "phase": "after", "reason": constraint+"_exceeded"}]
                            if offset.startswith("-") else [])
    assert p["economics_complete"] is p["native_admission_verified"] is False


@pytest.mark.parametrize("leverage,cap", [(3, 10000), (4, 5000), (10, 5000), (11, 1000), (20, 1000)])
def test_current_native_leverage_not_software_leverage_selects_max_compatible_cap(limit_case, leverage, cap):
    source, case = limit_case
    change_native(source, case, "configuration", "TESTUSDT", lambda raw: raw[0].update(leverage=leverage))
    p = evaluate(case)["payload"]
    row = next(row for row in p["limits"] if row["instrument_id"] == "TESTUSDT")
    assert fraction(row["leverage"]) == leverage and fraction(row["compatible_bracket_cap"]) == cap
    assert p["status"] == "within_observed_limits"


def test_non_candidate_symbol_and_existing_book_are_not_ignored(limit_case):
    source, case = limit_case
    change_native(source, case, "configuration", "ALTUSDT", lambda raw: raw[0].update(maxNotionalValue="1"))
    p = evaluate(case)["payload"]
    assert case["candidate"]["instrument_id"] == "TESTUSDT" and p["status"] == "exceeds_observed_limits"
    assert p["issues"] == [{"instrument_id": "ALTUSDT", "phase": phase, "reason": "configuration_cap_exceeded"}
                            for phase in ("before", "after")]


@pytest.mark.parametrize("neutral", [1, "1.000000000000000000000000000000"])
def test_explicitly_neutral_coefficient_does_not_transform_reported_ranges(limit_case, neutral):
    source, case = limit_case
    change_native(source, case, "brackets", "ALTUSDT", lambda raw: raw.update(notionalCoef=neutral))
    document = evaluate(case)
    assert document["payload"]["status"] == "within_observed_limits"
    assert next(row for row in document["payload"]["limits"] if row["instrument_id"] == "ALTUSDT")["compatible_bracket_cap"] == {
        "numerator": "5000", "denominator": "1"}
    assert case["capacity_evidence"]["payload"]["notional_coefficient_applied"] is False


@pytest.mark.parametrize("damage", ["sdk", "sha", "source_flags", "gap_resealed", "missing_symbol", "stale"])
def test_resealed_or_expired_source_still_uses_original_verifier_and_topology_checks(limit_case, damage):
    source, case = limit_case
    document = case["capacity_evidence"]
    p = document["payload"]
    if damage == "sdk":
        p["sdk"]["version"] = "0.0.0"
    elif damage == "sha":
        document["payload_sha256"] = "0"*64
    elif damage == "source_flags":
        p["economics_complete"] = True
    elif damage == "gap_resealed":
        next(row for row in p["observations"] if row["role"] == "brackets")["raw"]["brackets"][1]["notionalFloor"] = "1001"
    elif damage == "missing_symbol":
        del p["observations"][-1]
    else:
        source.clock["now"] += 1001
    if damage != "sha":
        document["payload_sha256"] = hashlib.sha256(canonical_bytes(p)).hexdigest()
    source.calls.clear()
    with pytest.raises(CChanException):
        evaluate(case)
    assert not source.calls


def test_final_serialization_cost_is_in_source_age_budget(limit_case, monkeypatch):
    source, case = limit_case
    api = limits_api()
    original_sha = api._sha
    def cost(value):
        result = original_sha(value)
        if "limits" in value:
            source.clock["now"] += 2001
        return result
    monkeypatch.setattr(api, "_sha", cost)
    with pytest.raises(CChanException):
        evaluate(case)


def test_a_stalled_business_clock_cannot_hide_positive_one_ns_of_evaluation_cost(limit_case, monkeypatch):
    source, case = limit_case
    api = limits_api()
    case["max_age_ms"] = source.clock["now"]-case["capacity_evidence"]["payload"]["started_ms"]
    ticks, original_sha = {"now": 0}, api._sha
    monkeypatch.setattr(api, "_monotonic_ns", lambda: ticks["now"], raising=False)
    def cost(value):
        result = original_sha(value)
        if "limits" in value:
            ticks["now"] += 1
        return result
    monkeypatch.setattr(api, "_sha", cost)
    with pytest.raises(CChanException):
        evaluate(case)


@pytest.mark.parametrize("ticks", [(False, 1), (1, False), (-1, 0), (2, 1)])
def test_invalid_or_backward_core_clock_never_produces_a_limit_result(limit_case, monkeypatch, ticks):
    api = limits_api()
    readings = iter(ticks)
    monkeypatch.setattr(api, "_monotonic_ns", lambda: next(readings), raising=False)
    with pytest.raises(CChanException):
        evaluate(limit_case[1])


def test_zero_cost_at_exact_age_and_span_boundaries_is_allowed(limit_case, monkeypatch):
    source, case = limit_case
    api = limits_api()
    p = case["capacity_evidence"]["payload"]
    case.update(max_age_ms=source.clock["now"]-p["started_ms"], max_observation_span_ms=p["finished_ms"]-p["started_ms"])
    monkeypatch.setattr(api, "_monotonic_ns", lambda: 0, raising=False)
    assert evaluate(case)["payload"]["status"] == "within_observed_limits"


@pytest.mark.parametrize("target", ["candidate", "positions", "source", "mark"])
def test_last_source_read_cannot_hide_mutation_of_callers_inputs(limit_case, monkeypatch, target):
    source, case = limit_case
    api = limits_api()
    verify, count = api.verify_binance_capacity_evidence, [0]
    def mutate(*args, **kwargs):
        result = verify(*args, **kwargs)
        count[0] += 1
        if count[0] == 2:
            if target == "candidate":
                case["candidate"]["contracts"] = "51"
            elif target == "positions":
                case["positions"][0]["positionAmt"] = "999"
            elif target == "source":
                case["capacity_evidence"]["payload"]["mode"] = "paper"
            else:
                case["mark_prices"]["TESTUSDT"] = "999"
        return result
    monkeypatch.setattr(api, "verify_binance_capacity_evidence", mutate)
    with pytest.raises(CChanException):
        evaluate(case)
    assert not source.attempts.count("POST")


def test_core_import_has_no_sdk_config_or_network_side_effect():
    code = """import sys
from Trade.NativeLeverageLimits import evaluate_binance_leverage_limits
assert callable(evaluate_binance_leverage_limits)
assert not any(name == 'ccxt' or name.startswith('ccxt.') for name in sys.modules)
assert 'Config' not in sys.modules and 'Config.config' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout+result.stderr
