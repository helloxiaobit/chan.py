"""Approved client assumptions, not authenticated inputs or order permission."""
import copy
import hashlib
import importlib.util
import itertools
import subprocess
import sys
from fractions import Fraction

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes


def cost_api():
    assert importlib.util.find_spec("Trade.NativeOrderCost") is not None, "approved V1 order cost calculation is missing"
    from Trade import NativeOrderCost
    return NativeOrderCost


@pytest.fixture
def cost_case():
    return {"market": {"exchange": "binanceusdm", "id": "TESTUSDT", "symbol": "TEST/USDT:USDT", "type": "swap",
                "base": "TEST", "quote": "USDT", "settle": "USDT", "contractSize": "0.01",
                "precision_mode": 4, "precision": {"amount": 1, "price": "0.1"},
                "limits": {"amount": {"min": 1}, "price": {}, "cost": {"min": 5}}},
            "position_mode": "one_way", "candidate": {"instrument_id": "TESTUSDT", "position_side": "BOTH",
                "side": "BUY", "base_quantity": "0.5", "contracts": "50", "order_type": "LIMIT",
                "limit_price": "105", "post_only": False, "reduce_only": False},
            "mark_price": "100", "last_price": "102", "bid_price": "99", "ask_price": "106", "leverage": 3,
            "commission": {"symbol": "TESTUSDT", "makerCommissionRate": "0.0002", "takerCommissionRate": "0.0004"},
            "fee_burn": False, "fee_currency": "USDT", "available_balance": "100", "margin_balance": "150"}


def calculate(case):
    return cost_api().calculate_binance_order_cost_v1(**case)


def fraction(value):
    result = Fraction(int(value["numerator"]), int(value["denominator"]))
    assert value == {"numerator": str(result.numerator), "denominator": str(result.denominator)}
    return result


@pytest.mark.parametrize("side,kind,post_only,expected", [
    ("BUY", "LIMIT", False, (Fraction(105), Fraction(5, 2), Fraction(53, 2500), Fraction(50053, 2500))),
    ("BUY", "LIMIT", True, (Fraction(105), Fraction(5, 2), Fraction(21, 2000), Fraction(40021, 2000))),
    ("SELL", "LIMIT", False, (Fraction(105), Fraction(0), Fraction(53, 2500), Fraction(43803, 2500))),
    ("SELL", "LIMIT", True, (Fraction(105), Fraction(0), Fraction(21, 2000), Fraction(35021, 2000))),
    ("BUY", "MARKET", False, (Fraction(102153, 1000), Fraction(2153, 2000), Fraction(53, 2500), Fraction(11327, 625))),
    ("SELL", "MARKET", False, (Fraction(102153, 1000), Fraction(0), Fraction(53, 2500), Fraction(170467, 10000))),
])
def test_all_six_order_paths_have_exact_complete_cost_and_no_authority(cost_case, side, kind, post_only, expected):
    case = cost_case
    case["candidate"].update(side=side, order_type=kind, post_only=post_only, limit_price=None if kind == "MARKET" else "105")
    before = canonical_bytes(case)
    document = calculate(case)
    p = document["payload"]
    price, loss, fee, total = expected
    assert document["schema"] == "chan-binance-order-cost-client-v1"
    assert p["model_id"] == "binance-usdt-linear-open-cost-client-v1"
    assert fraction(p["alpha"]) == Fraction(3, 2000)
    assert fraction(p["assumed_price"]) == price
    assert fraction(p["initial_margin"]) == price/6
    assert fraction(p["opening_loss"]) == loss
    assert fraction(p["estimated_fee"]) == fee
    assert fraction(p["total_cost"]) == total == price/6+loss+fee
    assert fraction(p["available_after_cost"]) == 100-total
    assert p["local_model_funds_sufficient"] is True
    assert p["currency"] == "USDT" and p["fee_currency_basis"] == "provided_currency_only"
    assert p["coverage"] == "provided_inputs_under_approved_client_v1_assumptions_only"
    assert all(p[key] is False for key in ("input_provenance_verified", "economics_complete", "native_admission_verified",
                                           "native_execution_bound_verified", "server_reservation_verified"))
    assert canonical_bytes(case) == before


def test_model_does_not_reuse_a_caller_result_or_mutate_its_candidate(cost_case):
    cost_case["candidate"]["total_cost"] = "0"
    original = copy.deepcopy(cost_case)
    with pytest.raises(CChanException):
        calculate(cost_case)
    assert cost_case == original


def test_pinned_client_model_discloses_price_fee_and_post_only_loss_assumptions(cost_case):
    p = calculate(cost_case)["payload"]
    assert p["assumptions"] == {"price_policy": "faq_assumed_price_client_v1_not_execution_bound",
        "fee_policy": "client_v1_fee_price_and_nonnegative_role_rate_not_execution_bound",
        "loss_policy": "all_limit_including_post_only_uses_limit_market_uses_assumed_price",
        "open_cost_faq_updated": "2026-07-08", "approval_date": "2026-10-24"}


def reference_cost(case):
    """Separate branch table and signed loss equations, never production fields."""
    c = case["candidate"]
    mark, ticker, leverage = (Fraction(case[key]) for key in ("mark_price", "last_price", "leverage"))
    quantity = Fraction(c["contracts"])*Fraction(case["market"]["contractSize"])
    padded = ticker*Fraction(2003, 2000)
    limit = None if c["limit_price"] is None else Fraction(c["limit_price"])
    refs = {("BUY", "LIMIT"): lambda: limit, ("SELL", "LIMIT"): lambda: sorted((padded, mark, limit))[-1],
            ("BUY", "MARKET"): lambda: padded, ("SELL", "MARKET"): lambda: padded}
    price = refs[c["side"], c["order_type"]]()
    basis = price if c["order_type"] == "MARKET" else limit
    loss = quantity*((abs(basis-mark)+basis-mark)/2 if c["side"] == "BUY" else (abs(mark-basis)+mark-basis)/2)
    maker, taker = (Fraction(case["commission"][key]) for key in ("makerCommissionRate", "takerCommissionRate"))
    if c["post_only"]:
        fee = quantity*limit*(maker+abs(maker))/2
    else:
        prices = [price, mark, Fraction(case["bid_price"]), Fraction(case["ask_price"])]
        if limit is not None:
            prices.append(limit)
        rates = [Fraction(0), taker]+([maker] if c["order_type"] == "LIMIT" else [])
        fee = quantity*sorted(prices)[-1]*sorted(rates)[-1]
    return price, loss, fee, quantity*price/leverage+loss+fee


@pytest.mark.parametrize("side,kind,post_only", [(side, kind, post) for side in ("BUY", "SELL")
                         for kind, post in (("LIMIT", False), ("LIMIT", True), ("MARKET", False))])
@pytest.mark.parametrize("mark,last,limit", [("100", "102", "105"), ("110", "90", "95"), ("100", "120", "90")])
def test_independent_reference_covers_each_assumed_price_branch_and_negative_rates(cost_case, side, kind, post_only,
                                                                                mark, last, limit):
    cost_case.update(mark_price=mark, last_price=last, leverage=7)
    cost_case["candidate"].update(side=side, order_type=kind, post_only=post_only, limit_price=None if kind == "MARKET" else limit)
    for maker, taker in itertools.product(("-0.0002", "0", "0.0006"), ("-0.0004", "0", "0.0004")):
        cost_case["commission"].update(makerCommissionRate=maker, takerCommissionRate=taker)
        price, loss, fee, total = reference_cost(cost_case)
        p = calculate(cost_case)["payload"]
        assert tuple(fraction(p[key]) for key in ("assumed_price", "opening_loss", "estimated_fee", "total_cost")) == (
            price, loss, fee, total)
        assert fee >= 0 and fraction(p["initial_margin"]) > 0


@pytest.mark.parametrize("offset", ["-0.000000000000000000000000000001", "0", "0.000000000000000000000000000001"])
def test_available_is_compared_exactly_without_epsilon_or_old_reservation_debit(cost_case, offset):
    # Hand cost 20.0212; native available already excludes the original 50 USDT reservation.
    from decimal import Decimal, localcontext
    with localcontext() as ctx:
        ctx.prec = 60
        cost_case["available_balance"] = str(Decimal("20.0212")+Decimal(offset))
    p = calculate(cost_case)["payload"]
    assert fraction(p["total_cost"]) == Fraction(50053, 2500)
    assert p["local_model_funds_sufficient"] is (not offset.startswith("-"))
    assert fraction(p["available_after_cost"]) == Fraction(offset)


def test_exact_intermediate_price_and_nonterminating_leverage_are_not_rounded(cost_case):
    cost_case.update(last_price="123.12345678901234567890123456789012345678901234567", leverage=7)
    cost_case["candidate"].update(order_type="MARKET", limit_price=None)
    price, loss, fee, total = reference_cost(cost_case)
    p = calculate(cost_case)["payload"]
    assert fraction(p["assumed_price"]) == price == Fraction(cost_case["last_price"])*Fraction(2003, 2000)
    assert fraction(p["initial_margin"]) == price/14
    assert fraction(p["total_cost"]) == total
    assert fraction(p["opening_loss"]) == loss and fraction(p["estimated_fee"]) == fee


@pytest.mark.parametrize("mode,leg,side", [("one_way", "BOTH", "BUY"), ("one_way", "BOTH", "SELL"),
                                         ("hedged", "LONG", "BUY"), ("hedged", "SHORT", "SELL")])
def test_only_actual_new_risk_legs_preserve_base_and_contract_units(cost_case, mode, leg, side):
    cost_case["position_mode"] = mode
    cost_case["candidate"].update(position_side=leg, side=side)
    p = calculate(cost_case)["payload"]
    assert p["candidate"] == cost_case["candidate"]
    assert fraction(p["total_cost"]) == reference_cost(cost_case)[-1]


@pytest.mark.parametrize("field", ["mark_price", "last_price", "bid_price", "ask_price", "leverage",
                                   "available_balance", "margin_balance", "base_quantity", "contracts", "limit_price",
                                   "makerCommissionRate", "takerCommissionRate"])
@pytest.mark.parametrize("bad", [True, 0.1, "NaN", "Infinity", " 1", "", None])
def test_money_never_uses_float_bool_nonfinite_or_missing_defaults(cost_case, field, bad):
    target = (cost_case["candidate"] if field in cost_case["candidate"] else
              cost_case["commission"] if field in cost_case["commission"] else cost_case)
    target[field] = bad
    before = canonical_bytes(cost_case)
    with pytest.raises(CChanException, match="V1单笔成本"):
        calculate(cost_case)
    assert canonical_bytes(cost_case) == before


@pytest.mark.parametrize("damage", ["wrong_instrument", "wrong_commission", "spot", "okx", "inverse", "foreign_settle",
    "wrong_contracts", "zero_quantity", "negative_quantity", "zero_last", "zero_mark", "empty_book", "crossed_book",
    "zero_leverage", "fractional_leverage", "negative_available", "available_over_equity", "missing_maker", "missing_taker",
    "tax_field", "fee_burn", "fee_burn_int", "fee_burn_missing", "unknown_currency", "bnb_currency", "credits_currency",
    "market_limit", "market_post_only", "market_zero_limit", "post_only_int", "reduce_only", "reduce_only_int",
    "conditional", "one_way_long", "hedge_both", "hedge_close", "alpha_override", "caller_fee", "missing_candidate_field"])
def test_unsupported_or_incomplete_inputs_do_not_become_spendable_cash(cost_case, damage):
    c = cost_case["candidate"]
    if damage == "wrong_instrument": c["instrument_id"] = "ALTUSDT"
    elif damage == "wrong_commission": cost_case["commission"]["symbol"] = "ALTUSDT"
    elif damage == "spot": cost_case["market"]["type"] = "spot"
    elif damage == "okx": cost_case["market"]["exchange"] = "okx"
    elif damage == "inverse": cost_case["market"]["settle"] = "TEST"
    elif damage == "foreign_settle": cost_case["market"]["quote"] = cost_case["market"]["settle"] = "USDC"
    elif damage == "wrong_contracts": c["contracts"] = "49"
    elif damage == "zero_quantity": c["base_quantity"] = c["contracts"] = "0"
    elif damage == "negative_quantity": c["base_quantity"], c["contracts"] = "-0.5", "-50"
    elif damage == "zero_last": cost_case["last_price"] = "0"
    elif damage == "zero_mark": cost_case["mark_price"] = "0"
    elif damage == "empty_book": cost_case["bid_price"] = "0"
    elif damage == "crossed_book": cost_case["bid_price"] = cost_case["ask_price"]
    elif damage == "zero_leverage": cost_case["leverage"] = 0
    elif damage == "fractional_leverage": cost_case["leverage"] = "3.5"
    elif damage == "negative_available": cost_case["available_balance"] = "-0.0000000000000000000001"
    elif damage == "available_over_equity": cost_case["available_balance"] = "151"
    elif damage == "missing_maker": del cost_case["commission"]["makerCommissionRate"]
    elif damage == "missing_taker": del cost_case["commission"]["takerCommissionRate"]
    elif damage == "tax_field": cost_case["commission"]["taxCommissionRate"] = "0.01"
    elif damage == "fee_burn": cost_case["fee_burn"] = True
    elif damage == "fee_burn_int": cost_case["fee_burn"] = 0
    elif damage == "fee_burn_missing": cost_case["fee_burn"] = None
    elif damage == "unknown_currency": cost_case["fee_currency"] = None
    elif damage == "bnb_currency": cost_case["fee_currency"] = "BNB"
    elif damage == "credits_currency": cost_case["fee_currency"] = "BNFCR"
    elif damage in {"market_limit", "market_post_only", "market_zero_limit"}:
        c.update(order_type="MARKET", limit_price="0" if damage == "market_zero_limit" else None if damage == "market_post_only" else "105",
                 post_only=damage == "market_post_only")
    elif damage == "post_only_int": c["post_only"] = 0
    elif damage == "reduce_only": c["reduce_only"] = True
    elif damage == "reduce_only_int": c["reduce_only"] = 0
    elif damage == "conditional": c["order_type"] = "STOP_MARKET"
    elif damage == "one_way_long": c["position_side"] = "LONG"
    elif damage == "hedge_both": cost_case["position_mode"] = "hedged"
    elif damage == "hedge_close": cost_case["position_mode"], c["position_side"], c["side"] = "hedged", "SHORT", "BUY"
    elif damage == "alpha_override": c["alpha"] = "0"
    elif damage == "caller_fee": c["fee"] = "0"
    else: del c["post_only"]
    with pytest.raises(CChanException, match="V1单笔成本"):
        calculate(cost_case)


def test_finite_canonical_document_and_original_input_hash_are_reproducible(cost_case):
    document = calculate(cost_case)
    assert document["payload_sha256"] == hashlib.sha256(canonical_bytes(document["payload"])).hexdigest()
    assert document["payload"]["provided_inputs_sha256"] == hashlib.sha256(canonical_bytes(cost_case)).hexdigest()
    assert canonical_bytes(document) == canonical_bytes(calculate(copy.deepcopy(cost_case)))


@pytest.mark.parametrize("target", ["original", "clone"])
def test_even_output_hashing_cannot_hide_late_input_mutation(cost_case, monkeypatch, target):
    api, original_hash = cost_api(), cost_api()._sha
    def mutate(value):
        digest = original_hash(value)
        if "total_cost" in value:
            destination = cost_case if target == "original" else saved["clone"]
            destination["candidate"]["contracts"] = "51"
        elif "market" in value:
            saved["clone"] = value
        return digest
    saved = {}
    monkeypatch.setattr(api, "_sha", mutate)
    with pytest.raises(CChanException, match="V1单笔成本"):
        calculate(cost_case)


def test_import_has_no_sdk_config_db_or_network_side_effect():
    script = """
import sys
import Trade.NativeOrderCost
assert not any(x in sys.modules for x in ('ccxt', 'Config', 'Trade.CCXTTradeEngine', 'db_util'))
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout+result.stderr
