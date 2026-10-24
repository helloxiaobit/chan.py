"""Approved F source fields: actual SDK and fake transport, not fee authority."""
import copy
import json
import re
import traceback

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade import NativeCapacityEvidence as Capacity
from .test_native_capacity_evidence import native_capacity, collect as collect_legacy, verify as verify_legacy, reseal


@pytest.fixture
def standard_capacity(native_capacity):
    case = native_capacity
    for key, body in case.bodies.items():
        if key[0] != "balance":
            case.bodies[key] = re.sub(r',\s*"private_unused"\s*:\s*"DO_NOT_PUBLISH"', '', body)
    return case


def collect(case, **changes):
    entry = getattr(Capacity, "collect_binance_standard_capacity_evidence", None)
    assert callable(entry), "closed-field F inputs must be collected before native fields are projected away"
    return entry(case.client, case.markets, mode=case.mode,
                 **({"max_age_ms": 1000, "max_observation_span_ms": 1000} | changes))


def verify(document, **changes):
    entry = getattr(Capacity, "verify_binance_standard_capacity_evidence", None)
    assert callable(entry), "closed-field F input reader is missing"
    return entry(document, **({"max_age_ms": 1000, "max_observation_span_ms": 1000} | changes))


def test_closed_fields_are_same_sdk_observations_without_fee_currency_or_funding_inference(standard_capacity):
    case = standard_capacity
    document = collect(case)
    assert document["schema"] == "chan-binance-capacity-evidence-v2"
    payload = document["payload"]
    assert payload["field_policy"] == "closed_native_capacity_fields_v1"
    assert payload["requests"] == 21 and len(case.calls) == 21
    assert all(row["uninterpreted_paths"] == [] for row in payload["observations"])
    assert payload["fee_currency"] is None
    assert payload["economics_complete"] is payload["native_admission_verified"] is False
    assert verify(document) == document


@pytest.mark.parametrize("role", ["fee_burn", "commission", "configuration", "brackets", "tier"])
@pytest.mark.parametrize("field,value", [("extraTaxRate", "0.0001"), ("extraTaxRate", "0"),
                                         ("commissionAsset", "USDT"), ("private_unknown", {"secret": "PRIVATE_FEE_DO_NOT_PUBLISH"})])
def test_raw_unknown_fields_are_rejected_before_projection_not_hidden_as_empty_coverage(standard_capacity, role, field, value):
    case = standard_capacity
    key = ("brackets" if role == "tier" else role, None if role == "fee_burn" else "ALTUSDT")
    body = json.loads(case.bodies[key], parse_float=str)
    target = body["brackets"][0] if role == "tier" else body[0] if role == "configuration" else body
    target[field] = value
    case.bodies[key] = json.dumps(body)
    with pytest.raises(CChanException) as error:
        collect(case)
    trace = "".join(traceback.format_exception(error.value))
    assert field not in trace and "PRIVATE_FEE_DO_NOT_PUBLISH" not in trace
    assert all(method == "GET" for method in case.attempts)


@pytest.mark.parametrize("standard", [False, True])
def test_terminal_reader_cannot_mutate_a_valid_source_into_a_permission_document(standard_capacity, monkeypatch, standard):
    case = standard_capacity
    name = "verify_binance_standard_capacity_evidence" if standard else "verify_binance_capacity_evidence"
    original = getattr(Capacity, name)
    def changed(document, **kwargs):
        result = original(document, **kwargs)
        document["payload"]["native_admission_verified"] = True
        reseal(document)
        return result
    monkeypatch.setattr(Capacity, name, changed)
    with pytest.raises(CChanException):
        (collect if standard else collect_legacy)(case)


@pytest.mark.parametrize("field", ["max_age_ms", "max_observation_span_ms"])
@pytest.mark.parametrize("bad", [None, True, -1, 1.0, "1000", 2**63])
def test_standard_budgets_are_explicit_before_any_get(standard_capacity, field, bad):
    case = standard_capacity
    with pytest.raises(CChanException): collect(case, **{field: bad})
    assert not case.calls


@pytest.mark.parametrize("field", ["source", "passed", "fee_currency", "field_policy", "checked_ms"])
def test_standard_source_has_no_caller_authority_override(standard_capacity, field):
    case = standard_capacity
    with pytest.raises(TypeError): collect(case, **{field: "USDT"})
    assert not case.calls


@pytest.mark.parametrize("damage", ["policy", "missing_marker", "nonempty_marker", "typed_marker", "fee_currency",
                                   "flag", "extra_fee", "tier_fee", "legacy_schema"])
def test_standard_reader_checks_closed_fields_and_disclosures_even_after_reseal(standard_capacity, damage):
    document = collect(standard_capacity)
    p = document["payload"]
    if damage == "policy": p["field_policy"] = "caller-approved"
    elif damage == "missing_marker": p["observations"][0].pop("uninterpreted_paths")
    elif damage == "nonempty_marker": p["observations"][0]["uninterpreted_paths"] = ["tax"]
    elif damage == "typed_marker": p["observations"][0]["uninterpreted_paths"] = False
    elif damage == "fee_currency": p["fee_currency"] = "USDT"
    elif damage == "flag": p["economics_complete"] = True
    elif damage == "extra_fee": p["observations"][1]["raw"]["additionalTax"] = "0"
    elif damage == "tier_fee": p["observations"][3]["raw"]["brackets"][0]["fee"] = "0"
    else: document["schema"] = Capacity.SCHEMA
    reseal(document)
    with pytest.raises(CChanException): verify(document)


def test_legacy_projection_does_not_upgrade_to_closed_field_inputs(native_capacity):
    case = native_capacity
    legacy = collect_legacy(case)
    assert verify_legacy(case, legacy) == legacy
    original = canonical_bytes(legacy)
    with pytest.raises(CChanException): verify(legacy)
    renamed = copy.deepcopy(legacy)
    renamed["schema"] = "chan-binance-capacity-evidence-v2"
    reseal(renamed)
    with pytest.raises(CChanException): verify(renamed)
    assert canonical_bytes(legacy) == original


@pytest.mark.parametrize("change", ["no_rpi", "no_coef", "array_brackets", "burn_on", "isolated"])
def test_supported_source_shapes_are_not_silently_fee_or_risk_qualification(standard_capacity, change):
    case = standard_capacity
    key = ("commission" if change == "no_rpi" else "fee_burn" if change == "burn_on" else
           "configuration" if change == "isolated" else "brackets", None if change == "burn_on" else "ALTUSDT")
    body = json.loads(case.bodies[key], parse_float=str)
    if change == "no_rpi": body.pop("rpiCommissionRate")
    elif change == "no_coef": body.pop("notionalCoef")
    elif change == "array_brackets": body = [body]
    elif change == "burn_on": body["feeBurn"] = True
    else: body[0]["marginType"] = "ISOLATED"
    case.bodies[key] = json.dumps(body)
    document = collect(case)
    assert verify(document) == document
    assert document["payload"]["fee_currency"] is None
    assert document["payload"]["native_admission_verified"] is False


@pytest.mark.parametrize("standard", [False, True])
@pytest.mark.parametrize("damage", ["flag", "raw_extension"])
def test_reader_final_clock_cannot_mutate_a_document_after_its_field_checks(standard_capacity, monkeypatch, standard, damage):
    case = standard_capacity
    document = (collect if standard else collect_legacy)(case)
    def clock():
        if damage == "flag": document["payload"]["native_admission_verified"] = True
        else: document["payload"]["observations"][1]["raw"]["newFeeChannel"] = "0"
        reseal(document)
        return case.clock["now"]
    monkeypatch.setattr(Capacity, "utc_now_ms", clock)
    with pytest.raises(CChanException):
        verify(document) if standard else verify_legacy(case, document)


@pytest.mark.parametrize("excess_ns", [0, 1])
def test_standard_reader_terminal_work_is_in_its_exact_age_budget(standard_capacity, monkeypatch, excess_ns):
    case = standard_capacity
    document = collect(case)
    remaining = 1000-(case.clock["now"]-document["payload"]["started_ms"])
    values = iter([0, remaining*1_000_000+excess_ns])
    monkeypatch.setattr(Capacity, "_monotonic_ns", lambda: next(values))
    if excess_ns:
        with pytest.raises(CChanException): verify(document)
    else: assert verify(document) == document


def test_standard_reader_final_canonicalization_cost_precedes_the_last_elapsed_sample(standard_capacity, monkeypatch):
    case = standard_capacity
    document = collect(case)
    original, elapsed, calls = Capacity.canonical_bytes, [0], []
    def delayed(value):
        result = original(value)
        if value is document:
            calls.append(1)
            if len(calls) == 2: elapsed[0] += 1_001_000_000
        return result
    monkeypatch.setattr(Capacity, "canonical_bytes", delayed)
    monkeypatch.setattr(Capacity, "_monotonic_ns", lambda: elapsed[0])
    with pytest.raises(CChanException): verify(document)
    assert len(calls) == 2


@pytest.mark.parametrize("samples", [(True, 1), (0, True), (1, 0), (-1, 0), (0, 0.5)])
def test_standard_reader_terminal_core_clock_is_typed_and_non_decreasing(standard_capacity, monkeypatch, samples):
    document = collect(standard_capacity)
    values = iter(samples)
    monkeypatch.setattr(Capacity, "_monotonic_ns", lambda: next(values))
    with pytest.raises(CChanException): verify(document)


@pytest.mark.parametrize("standard", [False, True])
@pytest.mark.parametrize("damage", ["observations_tuple", "observations_subclass", "tiers_tuple", "clock_subclass",
                                   "requests_subclass", "leverage_subclass", "commission_subclass"])
def test_reader_snapshot_cannot_normalize_types_which_original_native_fields_reject(standard_capacity, standard, damage):
    class WireInt(int): pass
    class WireText(str): pass
    class WireList(list): pass
    case = standard_capacity
    document = (collect if standard else collect_legacy)(case)
    original = canonical_bytes(document)
    p = document["payload"]
    if damage == "observations_tuple": p["observations"] = tuple(p["observations"])
    elif damage == "observations_subclass": p["observations"] = WireList(p["observations"])
    elif damage == "tiers_tuple":
        raw = next(row["raw"] for row in p["observations"] if row["role"] == "brackets")
        raw["brackets"] = tuple(raw["brackets"])
    elif damage == "clock_subclass": p["started_ms"] = WireInt(p["started_ms"])
    elif damage == "requests_subclass": p["requests"] = WireInt(p["requests"])
    elif damage == "leverage_subclass":
        raw = next(row["raw"] for row in p["observations"] if row["role"] == "configuration")
        raw["leverage"] = WireInt(raw["leverage"])
    else:
        raw = next(row["raw"] for row in p["observations"] if row["role"] == "commission")
        raw["takerCommissionRate"] = WireText(raw["takerCommissionRate"])
    assert canonical_bytes(document) == original
    with pytest.raises(CChanException):
        verify(document) if standard else verify_legacy(case, document)


@pytest.mark.parametrize("subclass", [False, True])
def test_standard_marker_cannot_be_normalized_into_a_native_empty_list(standard_capacity, subclass):
    class WireList(list): pass
    document = collect(standard_capacity)
    original = canonical_bytes(document)
    document["payload"]["observations"][0]["uninterpreted_paths"] = WireList() if subclass else ()
    assert canonical_bytes(document) == original
    with pytest.raises(CChanException): verify(document)
