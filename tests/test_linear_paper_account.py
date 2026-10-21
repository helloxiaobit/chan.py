"""Real C4 accounting in an explicit no-I/O paper adapter, not a venue proof."""
import copy
import hashlib
from decimal import Decimal, Subnormal, localcontext

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from ModelStrategy.parameterEvaluate.crypto_account import CCryptoAccountConfig
from Trade.LinearPaperAccount import CLinearPaperAccount, verify_linear_paper_report
from .test_execution_facts import definition


CODE = "TEST/USDT:USDT"


def paper_market(venue="binance"):
    return {**definition(venue), "amount_step": "1", "price_tick": "0.1", "min_notional": "1"}


def paper_account(*, mode="hedged", initial="1000", leverage="3", venue="binance"):
    return CLinearPaperAccount(CCryptoAccountConfig(initial_equity=initial, leverage=leverage,
        taker_fee="0.001", maker_fee="0.0002", taker_slippage="0.001"),
        markets=[paper_market(venue)], position_mode=mode, start_ms=1000, identity_seed="fixed-paper-account")


def quote(account, at, *, bid="99.9", ask="100.1", mark="100"):
    return account.set_quote(CODE, at_ms=at, bid=bid, ask=ask, mark_price=mark)


def filled(account, key, position_id, at, *, buy=True, quantity="1", price="100", leg="LONG", reduce=False, role="taker"):
    return account.execute_fill(execution_id=key, position_id=position_id, code=CODE,
        is_buy=buy, quantity=quantity, execution_price=price, position_side=leg,
        reduce_only=reduce, role=role, at_ms=at)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_actual_fill_cash_fee_mark_funding_and_partial_exit_use_c4_ledger_once(venue):
    account = paper_account(venue=venue)
    quote(account, 1001)
    result = filled(account, "open:1", "strategy:1", 1001, quantity="2", price="100.2")
    assert Decimal(result["cashflow"]["fee_delta"]) == Decimal("0.2004")
    assert Decimal(account.snapshot()["cash"]) == Decimal("999.7996")
    quote(account, 1002, mark="110")
    account.apply_funding(CODE, at_ms=1002, rate="0.01", mark_price="110", event_id="fund:1")
    assert Decimal(account.snapshot()["funding_pnl"]) == Decimal("-2.2")
    quote(account, 1003, bid="109.9", ask="110.1", mark="110")
    result = filled(account, "close:1", "strategy:1", 1003, buy=False, quantity="0.5", price="109.8", reduce=True)
    assert Decimal(result["cashflow"]["price_pnl_delta"]) == Decimal("4.8")
    assert Decimal(account.snapshot()["cash"]) == Decimal("1002.3447")
    assert account.position_quantity("strategy:1") == Decimal("1.5")
    assert account.snapshot()["status"] == "ready"
    report = account.to_dict()
    assert report["account"]["config"]["taker_slippage"] == "0"
    assert report["identity"]["accounting"] == "c4_per_fill_lot_record_fifo"
    assert report["identity"]["exchange_certified"] is False
    assert len(report["account"]["events"]) == 6  # three quotes, two fills, one funding


def test_hedged_inventory_gross_margin_and_funding_are_not_netted_away():
    account = paper_account()
    quote(account, 1001)
    filled(account, "long:1", "long-record", 1001)
    quote(account, 1002)
    filled(account, "short:1", "short-record", 1002, buy=False, leg="SHORT")
    account.apply_funding(CODE, at_ms=1002, rate="0.01", mark_price="100", event_id="fund:1")
    snapshot = account.snapshot()
    assert Decimal(snapshot["gross_notional"]) == 200 and Decimal(snapshot["net_notional"]) == 0
    assert Decimal(snapshot["funding_pnl"]) == -1  # The new short does not own same-ms funding.
    assert Decimal(snapshot["margin_used"]) > 0
    assert account.leg_quantity(CODE, "LONG") == account.leg_quantity(CODE, "SHORT") == 1


def test_record_fifo_partial_exit_does_not_consume_another_strategy_or_leg():
    account = paper_account()
    quote(account, 1001)
    filled(account, "first", "one", 1001, price="100")
    quote(account, 1002, mark="110")
    filled(account, "second", "one", 1002, price="110")
    filled(account, "other", "two", 1002, price="110")
    quote(account, 1003, mark="120")
    result = filled(account, "exit", "one", 1003, quantity="1.5", price="120", buy=False, reduce=True)
    assert Decimal(result["cashflow"]["price_pnl_delta"]) == 25
    assert account.position_quantity("one") == Decimal("0.5")
    assert account.position_quantity("two") == 1
    with pytest.raises(CChanException):
        filled(account, "wrong-leg", "one", 1003, buy=False, quantity="0.5", price="120", leg="SHORT", reduce=True)


def test_fee_after_margin_failure_is_atomic_and_stressed_positions_may_still_reduce():
    account = paper_account(initial="100", leverage="1")
    quote(account, 1001)
    before = account.to_dict()
    with pytest.raises(CChanException):
        filled(account, "too-large", "one", 1001, quantity="1", price="100")
    assert account.to_dict() == before
    filled(account, "valid", "one", 1001, quantity="0.9", price="100")
    quote(account, 1002)
    # Deliberately large funding loss; no fake liquidation price is invented.
    account.apply_funding(CODE, at_ms=1002, rate="0.9", mark_price="100", event_id="stress")
    quote(account, 1003, bid="0.9", ask="1.1", mark="1")
    assert account.snapshot()["status"] == "liquidation_required"
    with pytest.raises(CChanException):
        filled(account, "new-risk", "two", 1003, quantity="0.1", price="100")
    result = filled(account, "real-reduction", "one", 1003, buy=False, quantity="0.9", price="1", reduce=True)
    assert account.position_quantity("one") == 0
    assert Decimal(result["snapshot"]["equity"]) < 0


def test_fill_and_funding_retry_are_idempotent_but_changed_id_payload_is_rejected():
    account = paper_account()
    quote(account, 1001)
    first = filled(account, "open:1", "one", 1001)
    assert filled(account, "open:1", "one", 1001) == first
    with pytest.raises(CChanException):
        filled(account, "open:1", "one", 1001, quantity="2")
    quote(account, 1002)
    event = dict(at_ms=1002, rate="0.01", mark_price="100", event_id="fund:1")
    first_funding = account.apply_funding(CODE, **event)
    assert account.apply_funding(CODE, **event) == first_funding
    with pytest.raises(CChanException):
        account.apply_funding(CODE, **{**event, "event_id": "fund:other-id"})
    first["snapshot"]["cash"] = "wrong"
    assert account.snapshot()["cash"] != "wrong"


def test_quotes_are_owned_and_cannot_be_rewound_or_implicitly_used_at_another_clock():
    account = paper_account()
    quote(account, 1002)
    with pytest.raises(CChanException):
        quote(account, 1001)
    with pytest.raises(CChanException):
        filled(account, "stale", "one", 1003)
    before = account.to_dict()
    with pytest.raises(CChanException):
        quote(account, 1003, bid="110", ask="100")
    assert account.to_dict() == before


def test_paper_economics_are_independent_of_callers_decimal_context():
    expected = paper_account()
    quote(expected, 1001)
    filled(expected, "open:1", "one", 1001, quantity="0.03", price="100.2")
    with localcontext() as context:
        context.prec, context.Emax, context.Emin, context.traps[Subnormal] = 2, 1, -1, True
        actual = paper_account()
        quote(actual, 1001)
        filled(actual, "open:1", "one", 1001, quantity="0.03", price="100.2")
        assert actual.to_dict() == expected.to_dict()


@pytest.mark.parametrize("damage", ["metadata", "config", "position_mode"])
def test_paper_identity_is_frozen_instead_of_following_mutable_objects(damage):
    account = paper_account()
    if damage == "metadata":
        account.markets[CODE]["contractSize"] = "1"
    elif damage == "config":
        account.config = CCryptoAccountConfig(initial_equity="9999", leverage="1")
    else:
        account.position_mode = "one_way"
    with pytest.raises(CChanException):
        quote(account, 1001)


def test_python_numeric_inputs_are_normalized_at_paper_boundary_not_as_native_wire():
    account = paper_account()
    account.set_quote(CODE, at_ms=1001, bid=99.9, ask=100, mark_price=Decimal("100"))
    account.execute_fill(execution_id="numeric", position_id="one", code=CODE, is_buy=True,
        quantity=0.03, execution_price=Decimal("100.1"), position_side="LONG", reduce_only=False, role="taker", at_ms=1001)
    account.set_quote(CODE, at_ms=1002, bid=99.9, ask=100, mark_price=100)
    account.apply_funding(CODE, at_ms=1002, rate=-0.01, mark_price=100, event_id="credit")
    assert Decimal(account.snapshot()["funding_pnl"]) == Decimal("0.03")


@pytest.mark.parametrize("value", [True, None, {}, "NaN", "Infinity"])
def test_invalid_funding_is_redacted_and_cannot_mutate_account(value):
    account = paper_account()
    quote(account, 1001)
    before = account.to_dict()
    with pytest.raises(CChanException):
        account.apply_funding(CODE, at_ms=1001, rate=value, mark_price="100", event_id="bad")
    assert account.to_dict() == before


def test_whole_paper_report_replays_actual_effect_order_without_performance_or_network():
    account = paper_account()
    quote(account, 1001)
    filled(account, "fill", "one", 1001)
    quote(account, 1002, mark="110")
    account.apply_funding(CODE, at_ms=1002, rate="0.01", mark_price="110", event_id="fund")
    report = account.to_dict()
    assert verify_linear_paper_report(report) == report
    for damage in ("cash", "effect", "metadata", "certified"):
        broken = copy.deepcopy(report)
        if damage == "cash":
            broken["account"]["snapshot"]["cash"] = "9999"
        elif damage == "effect":
            broken["effects"][1]["request"]["execution_price"] = "99"
        elif damage == "metadata":
            broken["identity"]["markets"][0]["contractSize"] = "1"
        else:
            broken["identity"]["exchange_certified"] = True
        with pytest.raises(CChanException):
            verify_linear_paper_report(broken)


def test_quote_book_prices_must_be_on_explicit_tick_but_mark_is_independent():
    account = paper_account()
    with pytest.raises(CChanException):
        quote(account, 1001, bid="99.95", ask="100", mark="100")
    quote(account, 1001, bid="99.9", ask="100", mark="99.999999")
    assert account.quotes[CODE]["mark_price"] == "99.999999"


@pytest.mark.parametrize("damage", ["same_native_id", "mixed_venue", "unbounded_config"])
def test_one_paper_wallet_cannot_silently_alias_instruments_or_cross_native_venues(damage):
    first, second = paper_market(), paper_market()
    second.update(symbol="ALT/USDT:USDT", base="ALT")
    config = CCryptoAccountConfig()
    if damage == "mixed_venue":
        second.update(exchange="okx", id="ALT-USDT-SWAP")
    elif damage == "unbounded_config":
        second["id"] = "ALTUSDT"
        config = CCryptoAccountConfig(initial_equity="1e200")
    with pytest.raises(CChanException):
        CLinearPaperAccount(config, markets=[first, second], position_mode="one_way", start_ms=1000)


def test_multiple_symbols_keep_independent_prices_funding_and_gross_cross_margin():
    first, second = paper_market(), paper_market()
    second.update(id="ALTUSDT", symbol="ALT/USDT:USDT", base="ALT", contractSize="0.1")
    account = CLinearPaperAccount(paper_account().config, markets=[first, second], position_mode="hedged", start_ms=1000)
    quote(account, 1001)
    account.set_quote(second["symbol"], at_ms=1001, bid="9.9", ask="10", mark_price="10")
    filled(account, "first", "one", 1001, quantity="0.03")
    account.execute_fill(execution_id="second", position_id="two", code=second["symbol"], is_buy=False,
        quantity="1", execution_price="10", position_side="SHORT", reduce_only=False, role="taker", at_ms=1001)
    assert Decimal(account.snapshot()["gross_notional"]) == 13
    assert Decimal(account.snapshot()["net_notional"]) == -7
    quote(account, 1002, mark="110")
    account.apply_funding(CODE, at_ms=1002, rate="0.01", mark_price="110", event_id="first-fund")
    account.set_quote(second["symbol"], at_ms=1002, bid="9.9", ask="10", mark_price="10")
    account.apply_funding(second["symbol"], at_ms=1002, rate="-0.01", mark_price="10", event_id="second-fund")
    assert Decimal(account.snapshot()["funding_pnl"]) == Decimal("-0.133")
    assert Decimal(account.snapshot()["cash"]) == Decimal("999.854")
    assert verify_linear_paper_report(account.to_dict()) == account.to_dict()


@pytest.mark.parametrize("field", ["code_sha256", "execution_code_sha256"])
def test_resealed_paper_identity_cannot_claim_different_account_or_matching_code(field):
    account = paper_account()
    account._identity[field] = "0"*64
    account._identity["account_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in account._identity.items() if k != "account_id"})).hexdigest()
    with pytest.raises(CChanException):
        quote(account, 1001)
