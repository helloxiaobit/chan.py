"""V1 assumed price reaches the original full book without decimal truncation."""
import copy
import hashlib
from fractions import Fraction

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade import NativeMarginEnvelope as Envelope
from .test_native_margin_envelope import book, corners, fraction
from .test_native_order_cost import cost_case


def api():
    assert hasattr(Envelope, "calculate_binance_order_margin_envelope_v1"), "exact V1 price/book bridge is missing"
    return Envelope.calculate_binance_order_margin_envelope_v1


def arguments(book, side, kind, post):
    case = copy.deepcopy(book)
    c = case["candidate"]
    c.pop("valuation_price")
    c.update(side=side, order_type=kind, limit_price=None if kind == "MARKET" else "105", post_only=post, reduce_only=False)
    c["position_side"] = "BOTH" if case["position_mode"] == "one_way" else "LONG" if side == "BUY" else "SHORT"
    case["last_prices"] = {"TESTUSDT": "102", "ALTUSDT": "20"}
    return case


@pytest.mark.parametrize("side,kind,post", [(side, kind, post) for side in ("BUY", "SELL")
                         for kind, post in (("LIMIT", False), ("LIMIT", True), ("MARKET", False))])
def test_raw_v1_order_uses_original_nonempty_full_book_and_independent_vertices(book, side, kind, post):
    case = arguments(book, side, kind, post)
    original = canonical_bytes(case)
    document = api()(**case)
    p = document["payload"]
    assert document["schema"] == "chan-binance-order-margin-envelope-client-v1"
    assert p["model_id"] == "binance-usdt-linear-open-cost-client-v1"
    price = Fraction(105) if kind == "LIMIT" else Fraction(102153, 1000)
    assert fraction(p["assumed_price"]) == price
    envelope = p["margin_envelope"]
    assert envelope["schema"] == "chan-binance-margin-envelope-rational-v1"
    assert envelope["payload"]["candidate"]["valuation_price"] == p["assumed_price"]
    oracle = {**book, "candidate": {key: case["candidate"][key] for key in
              ("instrument_id", "position_side", "side", "base_quantity", "contracts")}}
    oracle["candidate"]["valuation_price"] = str(price)
    for row in envelope["payload"]["books"]:
        for leg in row["legs"]:
            for phase in ("before", "after"):
                margin, exposure = corners(oracle, row["instrument_id"], leg["position_side"], phase == "after")
                assert fraction(leg[phase]["initial_margin"]) == margin
                assert fraction(leg[phase]["exposure_notional"]) == exposure
    assert p["economics_complete"] is p["native_admission_verified"] is False
    assert canonical_bytes(case) == original


def test_full_precision_internal_r_is_never_rounded_to_the_old_input_context(book):
    case = arguments(book, "SELL", "MARKET", False)
    case["last_prices"]["TESTUSDT"] = "123.12345678901234567890123456789012345678901234567"
    price = Fraction(case["last_prices"]["TESTUSDT"])*Fraction(2003, 2000)
    p = api()(**case)["payload"]
    assert fraction(p["assumed_price"]) == price
    row = next(row for row in p["margin_envelope"]["payload"]["books"] if row["instrument_id"] == "TESTUSDT")
    leg = next(row for row in row["legs"] if row["position_side"] == case["candidate"]["position_side"])
    original_value = Fraction(110) if book["position_mode"] == "one_way" else Fraction(49)
    assert fraction(leg["after"]["ask_order_value"]) == original_value+price/2


def test_legacy_entry_keeps_decimal_schema_and_does_not_accept_internal_ratio(book):
    case = copy.deepcopy(book)
    case["candidate"]["valuation_price"] = {"numerator": "105", "denominator": "1"}
    with pytest.raises(CChanException):
        Envelope.calculate_binance_margin_envelope(**case)


@pytest.mark.parametrize("damage", ["missing_last", "extra_last", "negative_unused_last", "float_last", "bool_last", "nan_last",
    "missing_mark", "caller_price", "caller_cost", "caller_alpha", "market_limit", "market_post_only", "conditional",
    "wrong_units", "unknown_leg", "negative_quantity", "duplicate_pending", "incomplete_config", "wrong_mode"])
def test_v1_reprices_raw_order_and_rejects_incomplete_or_precomputed_inputs(book, damage):
    case = arguments(book, "BUY", "MARKET", False)
    if damage == "missing_last": del case["last_prices"]["ALTUSDT"]
    elif damage == "extra_last": case["last_prices"]["FOREIGNUSDT"] = "100"
    elif damage == "negative_unused_last": case["last_prices"]["ALTUSDT"] = "-1"
    elif damage == "float_last": case["last_prices"]["TESTUSDT"] = 102.0
    elif damage == "bool_last": case["last_prices"]["TESTUSDT"] = True
    elif damage == "nan_last": case["last_prices"]["TESTUSDT"] = "NaN"
    elif damage == "missing_mark": del case["mark_prices"]["ALTUSDT"]
    elif damage == "caller_price": case["candidate"]["valuation_price"] = "0"
    elif damage == "caller_cost": case["candidate"]["total_cost"] = "0"
    elif damage == "caller_alpha": case["candidate"]["alpha"] = "0"
    elif damage == "market_limit": case["candidate"]["limit_price"] = "100"
    elif damage == "market_post_only": case["candidate"]["post_only"] = True
    elif damage == "conditional": case["candidate"]["order_type"] = "STOP_MARKET"
    elif damage == "wrong_units": case["candidate"]["contracts"] = "49"
    elif damage == "unknown_leg": case["candidate"]["position_side"] = "missing"
    elif damage == "negative_quantity": case["candidate"].update(base_quantity="-0.5", contracts="-50")
    elif damage == "duplicate_pending": case["pending_orders"].append(copy.deepcopy(case["pending_orders"][0]))
    elif damage == "incomplete_config": case["symbol_configs"].pop()
    else: case["position_mode"] = "unknown"
    original = canonical_bytes(case)
    with pytest.raises(CChanException):
        api()(**case)
    assert canonical_bytes(case) == original


@pytest.mark.parametrize("destination", ["original", "clone"])
def test_last_serialization_cannot_hide_source_or_cloned_input_mutation(book, monkeypatch, destination):
    case = arguments(book, "SELL", "MARKET", False)
    sha, captured = Envelope._sha, {}
    def mutate(value):
        result = sha(value)
        if "last_prices" in value: captured["clone"] = value
        if "model_id" in value:
            target = case if destination == "original" else captured["clone"]
            target["candidate"]["contracts"] = "51"
        return result
    monkeypatch.setattr(Envelope, "_sha", mutate)
    with pytest.raises(CChanException):
        api()(**case)


@pytest.mark.parametrize("side,kind,post,expected", [
    ("BUY", "LIMIT", False, "b40475d3b8360339ab4fa4f08c44cc72f2d36d4a69790642271be74901aba601"),
    ("BUY", "LIMIT", True, "b7db6018783bef2112e38c06f4a94987b85e6758c3a503fcce64680bea4214c1"),
    ("BUY", "MARKET", False, "816f6ed45158dea06ad4fce89479e59658f7f374ee5c0878d082748c54354848"),
    ("SELL", "LIMIT", False, "177fe74068581e2d089f2331f98edba5cd04c3943ec89ccb0a7f35bce8d1a1bf"),
    ("SELL", "LIMIT", True, "b96b2b5ce55fc6db614c0e789063db2d3606fac4cdc2d8c90bcd1ab30c7fb05f"),
    ("SELL", "MARKET", False, "dbfdf25a5e70e98d8f6350629e8efd4c99a0de65227cd1f18503be2c7e554bc8"),
])
def test_cost_bytes_equal_frozen_pre_bridge_commit_cb0808b(cost_case, side, kind, post, expected):
    from Trade.NativeOrderCost import calculate_binance_order_cost_v1
    cost_case["candidate"].update(side=side, order_type=kind, post_only=post, limit_price=None if kind == "MARKET" else "105")
    assert hashlib.sha256(canonical_bytes(calculate_binance_order_cost_v1(**cost_case))).hexdigest() == expected


def test_legacy_envelope_bytes_equal_frozen_pre_bridge_commit_cb0808b(book):
    expected = {"one_way": "5cc02191ef965083f8a729835245b851cf526435d7e7b198d2ef1ff3017859ea",
                "hedged": "4dc861048a83c536e92e7d0ef2f5f7edfa730826c462b227e25c7e7e51d0d95b"}
    assert hashlib.sha256(canonical_bytes(Envelope.calculate_binance_margin_envelope(**book))
                          ).hexdigest() == expected[book["position_mode"]]
