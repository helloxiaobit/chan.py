"""Nonempty native books: hand arithmetic and independent corner enumeration."""
import copy
import importlib.util
import itertools
import subprocess
import sys
from fractions import Fraction
from decimal import Decimal

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from .test_native_pending_orders import regular_row


def envelope_api():
    assert importlib.util.find_spec("Trade.NativeMarginEnvelope") is not None, "native margin envelope calculation is missing"
    from Trade import NativeMarginEnvelope
    return NativeMarginEnvelope


def native_order(symbol, identity, side, leg, quantity, filled, price, *, reduce=False):
    row = regular_row("binance", symbol, identity, partial=Fraction(filled) > 0)
    row.update(side=side, positionSide=leg, origQty=quantity, executedQty=filled, price=price, reduceOnly=reduce)
    row.update(avgPrice=price if Fraction(filled) else "0", cumQuote=str(Decimal(filled)*Decimal(price)))
    return row


@pytest.fixture(params=["one_way", "hedged"])
def book(request):
    mode = request.param
    markets = [{"exchange": "binanceusdm", "id": base+"USDT", "symbol": base+"/USDT:USDT", "type": "swap",
                "base": base, "quote": "USDT", "settle": "USDT", "contractSize": size,
                "precision_mode": 4, "precision": {"amount": 1, "price": 0.1},
                "limits": {"amount": {"min": 1}, "price": {}, "cost": {"min": 5}}}
               for base, size in (("TEST", "0.01"), ("ALT", "0.1"))]
    leg = "BOTH" if mode == "one_way" else "LONG"
    alt_leg = "BOTH" if mode == "one_way" else "SHORT"
    positions = [{"symbol": "TESTUSDT", "positionSide": leg, "positionAmt": "2", "marginAsset": "USDT"},
                 {"symbol": "ALTUSDT", "positionSide": alt_leg, "positionAmt": "-3", "marginAsset": "USDT"}]
    orders = [native_order("TESTUSDT", 11, "BUY", leg, "1", "0.25", "90"),
              native_order("TESTUSDT", 12, "SELL", leg, "1.5", "0.5", "110", reduce=mode == "one_way"),
              native_order("ALTUSDT", 21, "BUY", alt_leg, "1.5", "0.5", "18", reduce=mode == "one_way"),
              native_order("ALTUSDT", 22, "SELL", alt_leg, "1", "0.25", "22")]
    candidate = {"instrument_id": "TESTUSDT", "position_side": "BOTH" if mode == "one_way" else "SHORT",
                 "side": "BUY" if mode == "one_way" else "SELL", "base_quantity": "0.5", "contracts": "50", "valuation_price": "105"}
    if mode == "hedged":
        positions += [{"symbol": "TESTUSDT", "positionSide": "SHORT", "positionAmt": "-1", "marginAsset": "USDT"},
                      {"symbol": "ALTUSDT", "positionSide": "LONG", "positionAmt": "1", "marginAsset": "USDT"}]
        orders += [native_order("TESTUSDT", 13, "BUY", "SHORT", "0.5", "0.25", "101"),
                   native_order("TESTUSDT", 14, "SELL", "SHORT", "1", "0.5", "98"),
                   native_order("ALTUSDT", 23, "BUY", "LONG", "0.75", "0.25", "19"),
                   native_order("ALTUSDT", 24, "SELL", "LONG", "0.5", "0.25", "21")]
    return {"markets": markets, "positions": positions, "pending_orders": orders,
            "mark_prices": {"TESTUSDT": "100", "ALTUSDT": "20"},
            "symbol_configs": [{"symbol": symbol, "marginType": "CROSSED", "isAutoAddMargin": False,
                                "leverage": leverage, "maxNotionalValue": "500000"}
                               for symbol, leverage in (("TESTUSDT", 3), ("ALTUSDT", 7))],
            "position_mode": mode, "candidate": candidate}


def calculate(case):
    return envelope_api().calculate_binance_margin_envelope(**case)


def fraction(value):
    assert set(value) == {"numerator", "denominator"}
    result = Fraction(int(value["numerator"]), int(value["denominator"]))
    assert value == {"numerator": str(result.numerator), "denominator": str(result.denominator)}
    return result


def corners(case, symbol, leg, after):
    """Enumerate all none/full residual fills, not the production endpoint rule."""
    position = sum((Fraction(row["positionAmt"]) for row in case["positions"]
                    if (row["symbol"], row["positionSide"]) == (symbol, leg)), Fraction(0))
    remaining = [(Fraction(row["origQty"])-Fraction(row["executedQty"]), Fraction(row["price"]), row["side"])
                 for row in case["pending_orders"] if (row["symbol"], row["positionSide"]) == (symbol, leg)]
    candidate = case["candidate"]
    if after and (candidate["instrument_id"], candidate["position_side"]) == (symbol, leg):
        remaining.append((Fraction(candidate["base_quantity"]), Fraction(candidate["valuation_price"]), candidate["side"]))
    mark = Fraction(case["mark_prices"][symbol])
    values, quantities = [], []
    for picks in itertools.product((0, 1), repeat=len(remaining)):
        values.append(abs(position*mark+sum((pick*q*price*(1 if side == "BUY" else -1)
                                            for pick, (q, price, side) in zip(picks, remaining)), Fraction(0))))
        quantities.append(abs(position+sum((pick*q*(1 if side == "BUY" else -1)
                                            for pick, (q, _, side) in zip(picks, remaining)), Fraction(0)))*mark)
    leverage = next(row["leverage"] for row in case["symbol_configs"] if row["symbol"] == symbol)
    return max(values)/leverage, max(max(values), max(quantities))


def test_two_symbol_partial_book_matches_hand_and_independent_vertices(book):
    original = canonical_bytes(book)
    document = calculate(book)
    assert canonical_bytes(book) == original
    assert document["schema"] == "chan-binance-margin-envelope-v1"
    p = document["payload"]
    assert p["economics_complete"] is p["native_admission_verified"] is False
    assert p["coverage"] == "provided_book_margin_envelopes_only"
    assert p["candidate_valuation_basis"] == "provided_untrusted_reference"
    before, after = (Fraction(2102, 21), Fraction(4939, 42)) if book["position_mode"] == "one_way" else (
                     Fraction(6467, 42), Fraction(3601, 21))
    assert fraction(p["before_initial_margin"]) == before
    assert fraction(p["after_initial_margin"]) == after
    assert fraction(p["incremental_initial_margin"]) == Fraction(35, 2)
    for market in p["books"]:
        for leg in market["legs"]:
            for frame, active in (("before", False), ("after", True)):
                margin, exposure = corners(book, market["instrument_id"], leg["position_side"], active)
                assert fraction(leg[frame]["initial_margin"]) == margin
                assert fraction(leg[frame]["exposure_notional"]) == exposure
    test_market = next(row for row in p["books"] if row["instrument_id"] == "TESTUSDT")
    long = next(row for row in test_market["legs"] if row["position_side"] in {"BOTH", "LONG"})
    assert fraction(long["before"]["bid_order_value"]) == Fraction(135, 2)  # .75 remaining, not original 1
    assert fraction(long["before"]["ask_order_value"]) == 110  # Closing/RO is not silently removed.


@pytest.mark.parametrize("side,quantity,price,expected", [("SELL", "5", "99", Fraction(2043, 14)),
                                                        ("BUY", "0.5", "105", Fraction(4939, 42))])
@pytest.mark.parametrize("book", ["one_way"], indirect=True)
def test_one_way_opposite_orders_use_signed_position_and_full_pending_not_full_new_notional(book, side, quantity, price, expected):
    book["candidate"].update(side=side, base_quantity=quantity, contracts=str(Fraction(quantity)*100), valuation_price=price)
    p = calculate(book)["payload"]
    assert fraction(p["after_initial_margin"]) == expected


@pytest.mark.parametrize("book", ["hedged"], indirect=True)
def test_hedged_long_and_short_are_never_netted_before_margin(book):
    p = calculate(book)["payload"]
    test = next(row for row in p["books"] if row["instrument_id"] == "TESTUSDT")
    assert fraction(test["before_initial_margin"]) == Fraction(833, 6)
    assert len(test["legs"]) == 2
    assert {row["position_side"]: fraction(row["position_base_quantity"]) for row in test["legs"]} == {"LONG": 2, "SHORT": -1}


def test_candidate_is_not_turned_into_a_fake_native_order_or_owned_balance(book):
    p = calculate(book)["payload"]
    assert p["candidate"] == book["candidate"]
    assert p["native_pending_count"] == len(book["pending_orders"])
    assert all(key not in canonical_bytes(p).decode() for key in ('"available_balance"', '"affordable"', '"orderId"', '"passed"'))


def test_symbol_exposure_explicitly_sums_hedge_legs_without_cross_symbol_netting(book):
    p = calculate(book)["payload"]
    expected = {"TESTUSDT": (Fraction(275), Fraction(325)), "ALTUSDT": (Fraction(153, 2), Fraction(153, 2))} if (
        book["position_mode"] == "one_way") else {"TESTUSDT": (Fraction(425), Fraction(953, 2)),
                                                    "ALTUSDT": (Fraction(213, 2), Fraction(213, 2))}
    for market in p["books"]:
        assert "before_exposure_notional" in market, "the per-symbol cap input must not depend on netted hedge legs"
        assert fraction(market["before_exposure_notional"]) == expected[market["instrument_id"]][0]
        assert fraction(market["after_exposure_notional"]) == expected[market["instrument_id"]][1]


@pytest.mark.parametrize("book", ["one_way"], indirect=True)
def test_opposite_candidate_can_leave_margin_unchanged_without_claiming_zero_cost(book):
    book["candidate"].update(instrument_id="ALTUSDT", side="BUY", base_quantity="2", contracts="20", valuation_price="19")
    p = calculate(book)["payload"]
    assert fraction(p["incremental_initial_margin"]) == 0
    assert fraction(p["after_initial_margin"]) == Fraction(2102, 21)
    assert p["economics_complete"] is p["native_admission_verified"] is False


@pytest.mark.parametrize("quantity", ["0.01", "0.25", "1", "5", "30"])
def test_sign_crossings_and_large_residuals_match_independent_vertex_oracle(book, quantity):
    book["candidate"].update(base_quantity=quantity, contracts=str(Decimal(quantity)*100))
    p = calculate(book)["payload"]
    before, after = Fraction(0), Fraction(0)
    for market in p["books"]:
        for leg in market["legs"]:
            first, first_exposure = corners(book, market["instrument_id"], leg["position_side"], False)
            last, last_exposure = corners(book, market["instrument_id"], leg["position_side"], True)
            assert fraction(leg["before"]["initial_margin"]) == first
            assert fraction(leg["after"]["initial_margin"]) == last
            assert fraction(leg["before"]["exposure_notional"]) == first_exposure
            assert fraction(leg["after"]["exposure_notional"]) == last_exposure
            before, after = before+first, after+last
    assert fraction(p["incremental_initial_margin"]) == after-before >= 0


def test_native_order_ids_are_scoped_by_symbol_not_globally_deduplicated(book):
    book["pending_orders"][2]["orderId"] = book["pending_orders"][0]["orderId"]
    assert calculate(book)["payload"]["native_pending_count"] == len(book["pending_orders"])


def test_numeric_native_id_alias_cannot_count_the_same_pending_order_twice(book):
    duplicate = copy.deepcopy(book["pending_orders"][0])
    duplicate["orderId"] = "00011"
    book["pending_orders"].append(duplicate)
    with pytest.raises(CChanException):
        calculate(book)


def test_ordering_changes_do_not_change_the_numeric_book_but_do_change_input_identity(book):
    first = calculate(book)["payload"]
    book["positions"].reverse()
    book["pending_orders"].reverse()
    book["markets"].reverse()
    book["symbol_configs"].reverse()
    second = calculate(book)["payload"]
    assert first["books"] == second["books"]
    assert first["provided_inputs_sha256"] != second["provided_inputs_sha256"]


def test_final_check_detects_original_inputs_changed_inside_reused_parser(book, monkeypatch):
    api = envelope_api()
    original = api._order
    def changed(*args):
        value = original(*args)
        book["candidate"]["base_quantity"] = "9"
        return value
    monkeypatch.setattr(api, "_order", changed)
    with pytest.raises(CChanException):
        calculate(book)


def test_margin_result_keeps_reduced_nonterminating_fraction_not_a_rounded_decimal(book):
    p = calculate(book)["payload"]
    assert fraction(p["before_initial_margin"]).denominator in {21, 42}
    assert p["before_initial_margin"]["denominator"] in {"21", "42"}
    assert "PRIVATE_NOTE_NO_STORE" not in canonical_bytes(p).decode()


@pytest.mark.parametrize("damage", ["duplicate_leg", "wrong_position_sign", "wrong_mode_leg", "foreign_currency", "missing_qty",
    "duplicate_order", "unknown_market", "pending_market", "pending_algo", "complex_pending", "pending_overfill", "missing_mark",
    "bad_mark", "missing_settings", "duplicate_settings", "isolated", "zero_leverage", "bool_leverage", "candidate_units",
    "candidate_side", "candidate_leg", "candidate_extra", "candidate_float", "candidate_bool"])
def test_incomplete_or_ambiguous_book_is_not_repaired_into_a_margin_result(book, damage):
    if damage == "duplicate_leg":
        book["positions"].append(copy.deepcopy(book["positions"][0]))
    elif damage == "wrong_position_sign":
        if book["position_mode"] == "one_way":
            book["positions"][0]["positionSide"] = "SHORT"
        else:
            book["positions"][0]["positionAmt"] = "-2"
    elif damage == "wrong_mode_leg":
        book["positions"][0]["positionSide"] = "LONG" if book["position_mode"] == "one_way" else "BOTH"
    elif damage == "foreign_currency":
        book["positions"][0]["marginAsset"] = "USDC"
    elif damage == "missing_qty":
        del book["positions"][0]["positionAmt"]
    elif damage == "duplicate_order":
        book["pending_orders"].append(copy.deepcopy(book["pending_orders"][0]))
    elif damage == "unknown_market":
        book["pending_orders"][0]["symbol"] = "OTHERUSDT"
    elif damage in {"pending_market", "pending_algo"}:
        book["pending_orders"][0].update(type="MARKET" if damage == "pending_market" else "STOP_MARKET",
                                        origType="MARKET" if damage == "pending_market" else "STOP_MARKET")
    elif damage == "complex_pending":
        book["pending_orders"][0]["priceMatch"] = "OPPONENT"
    elif damage == "pending_overfill":
        book["pending_orders"][0]["executedQty"] = "9"
    elif damage == "missing_mark":
        del book["mark_prices"]["ALTUSDT"]
    elif damage == "bad_mark":
        book["mark_prices"]["ALTUSDT"] = "NaN"
    elif damage == "missing_settings":
        book["symbol_configs"].pop()
    elif damage == "duplicate_settings":
        book["symbol_configs"].append(copy.deepcopy(book["symbol_configs"][0]))
    elif damage == "isolated":
        book["symbol_configs"][0]["marginType"] = "ISOLATED"
    elif damage == "zero_leverage":
        book["symbol_configs"][0]["leverage"] = 0
    elif damage == "bool_leverage":
        book["symbol_configs"][0]["leverage"] = True
    elif damage == "candidate_units":
        book["candidate"]["contracts"] = "49"
    elif damage == "candidate_side":
        book["candidate"]["side"] = "BUY" if book["position_mode"] == "hedged" else "sell"
    elif damage == "candidate_leg":
        book["candidate"]["position_side"] = "LONG" if book["position_mode"] == "one_way" else "BOTH"
    elif damage == "candidate_extra":
        book["candidate"]["affordable"] = True
    else:
        book["candidate"]["valuation_price"] = 105.0 if damage == "candidate_float" else True
    with pytest.raises(CChanException):
        calculate(book)


def test_margin_arithmetic_core_import_has_no_sdk_or_configuration_side_effects():
    envelope_api()
    result = subprocess.run([sys.executable, "-c", "import sys; import Trade.NativeMarginEnvelope; "
        "assert not any(k == 'ccxt' or k.startswith('ccxt.') or k == 'Config' or k.startswith('Config.') for k in sys.modules)"],
        text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout+result.stderr
