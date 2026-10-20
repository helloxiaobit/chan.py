"""小型 USDT 手算账户；无数据下载、搜索、真实订单或正式研究资产。"""
from copy import deepcopy
from decimal import Decimal

import pytest

from Common.ChanException import CChanException
from ModelStrategy.parameterEvaluate.crypto_account import CCryptoAccount, CCryptoAccountConfig, evaluate_crypto_account

CODE = "TEST/USDT:USDT"


def opening(at=0, *, buy=True, quantity="2", price="100", market=CODE, pid="p", event_id="open"):
    return {"id": event_id, "kind": "open", "at_ms": at, "position_id": pid, "symbol": market,
            "is_buy": buy, "quantity": quantity, "price": price, "mark_price": price}


def close(at, *, quantity="2", price="100", pid="p", event_id="close"):
    return {"id": event_id, "kind": "close", "at_ms": at, "position_id": pid, "quantity": quantity, "price": price}


def mark(at, price, symbol=CODE):
    return {"id": f"mark-{at}", "kind": "mark", "at_ms": at, "symbol": symbol, "price": price}


def conf(**overrides):
    return CCryptoAccountConfig(**{"market_type": "swap", "initial_equity": "1000", "leverage": "2",
        "taker_fee": "0", "maker_fee": "0", "taker_slippage": "0", **overrides})


def decimal_fields(snapshot, **expected):
    for name, value in expected.items():
        assert Decimal(snapshot[name]) == Decimal(str(value)), name
    assert Decimal(snapshot["equity"]) == (Decimal(snapshot["initial_equity"])+Decimal(snapshot["price_pnl"])
        +Decimal(snapshot["unrealized_pnl"])+Decimal(snapshot["funding_pnl"])-Decimal(snapshot["fees"]))


def test_linear_long_fees_slippage_funding_partial_exit_and_mark_identity():
    account = CCryptoAccount(conf(taker_fee="0.001", taker_slippage="0.01"))
    decimal_fields(account.apply(opening()), cash="999.798", equity="997.798", fees="0.202", unrealized_pnl="-2")
    decimal_fields(account.apply(mark(1000, "110")), equity="1017.798", gross_notional="220", margin_used="110")
    decimal_fields(account.apply({"id": "fund", "kind": "funding", "at_ms": 1000, "symbol": CODE, "rate": "0.01", "price": "110"}),
                   cash="997.598", equity="1015.598", funding_pnl="-2.2")
    decimal_fields(account.apply(close(2000, quantity="0.5", price="120", event_id="partial")),
                   cash="1006.4386", equity="1019.9386", price_pnl="8.9", fees="0.2614", unrealized_pnl="13.5")
    result = account.apply(close(3000, quantity="1.5", price="90"))
    decimal_fields(result, cash="988.45495", equity="988.45495", price_pnl="-8.95", fees="0.39505", funding_pnl="-2.2")
    assert result["positions"] == {} and result["closed_position_count"] == 1
    assert len(account.to_dict()["events"]) == 5


def test_linear_short_funding_credits_and_unclosed_position_are_not_forced_closed():
    account = CCryptoAccount(conf())
    account.apply(opening(buy=False))
    decimal_fields(account.apply(mark(1000, "110")), equity="980", unrealized_pnl="-20")
    account.apply({"id": "fund", "kind": "funding", "at_ms": 1000, "symbol": CODE, "rate": "0.01", "price": "110"})
    decimal_fields(account.apply(close(2000, quantity="1", price="90", event_id="partial")),
                   cash="1012.2", equity="1002.2", funding_pnl="2.2", price_pnl="10", unrealized_pnl="-10")
    result = account.apply(mark(3000, "80"))
    decimal_fields(result, cash="1012.2", equity="1032.2", unrealized_pnl="20")
    assert result["positions"]["p"]["quantity"] == "1"
    assert result["closed_position_count"] == 0


def test_spot_cash_is_reserved_and_short_or_funding_cannot_be_fabricated():
    symbol = "TEST/USDT"
    account = CCryptoAccount(conf(market_type="spot", leverage="1", taker_fee="0.001", taker_slippage="0.01"))
    decimal_fields(account.apply(opening(market=symbol)), cash="797.798", equity="997.798", fees="0.202")
    account.apply(mark(1000, "110", symbol))
    decimal_fields(account.apply(close(2000, quantity="0.5", price="120", event_id="partial")),
                   cash="857.1386", equity="1022.1386", price_pnl="8.9", fees="0.2614", unrealized_pnl="13.5")
    before = account.to_dict()
    with pytest.raises(CChanException):
        account.apply(opening(3000, market=symbol, pid="short", event_id="short", buy=False))
    with pytest.raises(CChanException):
        account.apply({"id": "fund", "kind": "funding", "at_ms": 3000, "symbol": symbol, "rate": "0.01", "price": "110"})
    assert account.to_dict() == before


def test_duplicate_exact_event_is_idempotent_and_conflict_or_rollback_is_atomic():
    account = CCryptoAccount(conf())
    event = opening()
    account.apply(event)
    before = account.to_dict()
    assert account.apply(deepcopy(event)) == before["snapshot"]
    assert account.to_dict() == before
    changed = {**event, "quantity": "3"}
    with pytest.raises(CChanException):
        account.apply(changed)
    account.apply(mark(1000, "110"))
    before = account.to_dict()
    with pytest.raises(CChanException):
        account.apply(close(500))
    with pytest.raises(CChanException):
        account.apply(close(2000, quantity="3"))
    assert account.to_dict() == before


def test_fee_adjusted_margin_rejects_new_risk_but_insolvency_allows_reduction():
    account = CCryptoAccount(conf(taker_fee="0.001"))
    before = account.to_dict()
    with pytest.raises(CChanException):
        account.apply(opening(quantity="20"))
    assert account.to_dict() == before
    account.apply(opening(quantity="10"))
    stressed = account.apply(mark(1000, "0.01"))
    assert stressed["status"] == "liquidation_required"
    with pytest.raises(CChanException):
        account.apply(opening(2000, pid="other", event_id="other", quantity="1", price="0.01"))
    reduced = account.apply(close(2000, quantity="10", price="0.01"))
    assert reduced["positions"] == {}  # 不虚构强平价或抹掉亏损，实际减仓成交仍可记账。


def test_same_timestamp_funding_owns_only_old_positions_and_exits_precede_entries():
    events = [opening(1000, pid="new", event_id="new"),
        {"id": "fund", "kind": "funding", "at_ms": 1000, "symbol": CODE, "rate": "0.01", "price": "100"},
        close(1000), opening()]
    result = evaluate_crypto_account(events, conf(), start_ms=0, end_ms=2000)
    assert [r["event"]["id"] for r in result["events"]] == ["open", "fund", "close", "new"]
    decimal_fields(result["snapshot"], funding_pnl="-2", equity="998")
    assert result["snapshot"]["positions"]["new"]["quantity"] == "2"


@pytest.mark.parametrize("value", [True, "NaN", "Infinity", "-1", "0"])
def test_bad_quantities_have_no_partial_ledger_or_cash_update(value):
    account = CCryptoAccount(conf())
    before = account.to_dict()
    with pytest.raises(CChanException):
        account.apply(opening(quantity=value))
    assert account.to_dict() == before


def test_explicit_window_metrics_are_finite_and_open_marks_contribute_to_drawdown():
    year = 365*24*3600*1000
    result = evaluate_crypto_account([opening(), mark(year//2, "90"), mark(year-1, "110")], conf(), start_ms=0, end_ms=year)
    decimal_fields(result["snapshot"], equity="1020", price_pnl="0", unrealized_pnl="20")
    assert Decimal(result["metrics"]["total_return"]) == Decimal("0.02")
    assert Decimal(result["metrics"]["max_drawdown"]) == Decimal("0.02")
    assert Decimal(result["metrics"]["cagr"]) == Decimal("0.02")
    from CustomBuySellPoint.Decision import canonical_bytes
    canonical_bytes(result)
    with pytest.raises(CChanException):
        evaluate_crypto_account([opening(year)], conf(), start_ms=0, end_ms=year)


def test_caller_decimal_context_cannot_change_snapshots_or_duplicate_results():
    from decimal import localcontext
    account = CCryptoAccount(conf(taker_fee="0.001"))
    event = opening(quantity="1.234567890123456789", price="100.123456789123456789")
    expected = account.apply(event)
    with localcontext() as context:
        context.prec = 8
        assert account.snapshot() == expected
        assert account.apply(deepcopy(event)) == expected
        assert account.to_dict()["snapshot"] == expected


def test_maker_fee_has_no_adverse_market_slippage_and_hedged_exposure_stays_gross():
    account = CCryptoAccount(conf(taker_fee="0.001", maker_fee="0.0002", taker_slippage="0.01"))
    account.apply({**opening(), "role": "maker"})
    account.apply({**opening(1, buy=False, quantity="1", pid="short", event_id="short"), "role": "maker"})
    result = account.apply({"id": "fund", "kind": "funding", "at_ms": 1000, "symbol": CODE, "rate": "0.01", "price": "100"})
    decimal_fields(result, fees="0.06", funding_pnl="-1", gross_notional="300", net_notional="100", equity="998.94")
    assert result["positions"]["p"]["average_price"] == "100"


def test_decoded_account_history_cannot_rewrite_already_recorded_events():
    account = CCryptoAccount(conf())
    event = opening()
    account.apply(event)
    before = account.to_dict()
    event["quantity"] = "200"
    decoded = account.to_dict()
    decoded["events"][0]["snapshot"]["equity"] = "2000"
    assert account.to_dict() == before
    account.apply(close(1000))
    assert account.to_dict()["events"][0] == before["events"][0]


def test_a_new_lot_can_exit_at_its_fill_timestamp_after_older_lots_exit():
    events = [close(1000, pid="new", event_id="new-exit", quantity="1", price="101"),
              opening(1000, pid="new", event_id="new", quantity="1"), close(1000), opening()]
    result = evaluate_crypto_account(events, conf(), start_ms=0, end_ms=2000)
    assert [r["event"]["id"] for r in result["events"]] == ["open", "close", "new", "new-exit"]
    decimal_fields(result["snapshot"], equity="1001", price_pnl="1")
    assert result["snapshot"]["closed_position_count"] == 2


def test_funding_is_unique_per_symbol_and_timestamp_even_if_another_id_is_used():
    account = CCryptoAccount(conf())
    account.apply(opening())
    event = {"id": "fund", "kind": "funding", "at_ms": 1000, "symbol": CODE, "rate": "0.01", "price": "100"}
    account.apply(event)
    before = account.to_dict()
    with pytest.raises(CChanException):
        account.apply({**event, "id": "same-economic-funding"})
    assert account.to_dict() == before


def test_remaining_quantity_owns_future_funding_and_event_cashflows_are_explicit():
    account = CCryptoAccount(conf())
    account.apply(opening())
    account.apply(close(1000, quantity="0.5", price="110", event_id="partial"))
    account.apply({"id": "fund", "kind": "funding", "at_ms": 2000, "symbol": CODE, "rate": "0.01", "price": "110"})
    report = account.to_dict()
    partial, funding = report["events"][1:]
    assert Decimal(partial["cashflow"]["cash_delta"]) == Decimal("5")
    assert Decimal(partial["cashflow"]["execution_price"]) == Decimal("110")
    assert Decimal(funding["cashflow"]["funding_delta"]) == Decimal("-1.65")
    decimal_fields(report["snapshot"], funding_pnl="-1.65", price_pnl="5", equity="1018.35")


@pytest.mark.parametrize("event", [
    {"id": "bad", "kind": "mark", "at_ms": 1, "symbol": CODE, "price": "100", "role": "maker"},
    {"id": "bad", "kind": "open", "at_ms": 1, "position_id": "bad", "symbol": "/USDT:USDT", "is_buy": True,
     "quantity": "1", "price": "100", "mark_price": "100"},
])
def test_unknown_mark_fields_or_empty_base_symbol_fail_without_an_event(event):
    account = CCryptoAccount(conf())
    before = account.to_dict()
    with pytest.raises(CChanException):
        account.apply(event)
    assert account.to_dict() == before


@pytest.mark.parametrize("field", ["cash", "fee", "event", "metric", "window", "code"])
def test_report_replay_checks_every_record_and_bound_evaluator_identity(field):
    from ModelStrategy.parameterEvaluate.crypto_account import verify_crypto_account_report
    report = evaluate_crypto_account([opening(), close(1000, price="110")], conf(), start_ms=0, end_ms=2000)
    assert verify_crypto_account_report(report) == report
    changed = deepcopy(report)
    if field == "cash":
        changed["events"][0]["snapshot"]["cash"] = "2000"
    elif field == "fee":
        changed["events"][1]["cashflow"]["fee_delta"] = "0.01"
    elif field == "event":
        changed["events"][0]["event"]["quantity"] = "1"
    elif field == "metric":
        changed["metrics"]["total_return"] = "0.9"
    elif field == "window":
        changed["window"]["end_ms"] = 3000
    else:
        changed["evaluator"]["code_sha256"] = "0"*64
    with pytest.raises(CChanException):
        verify_crypto_account_report(changed)


def test_same_millisecond_partial_exits_use_explicit_sequence_not_lexical_id():
    events = [opening(), {**close(1000, quantity="1", price="90", event_id="a-last"), "sequence": 1},
              {**close(1000, quantity="1", price="110", event_id="z-first"), "sequence": 0}]
    result = evaluate_crypto_account(events, conf(), start_ms=0, end_ms=2000)
    assert [r["event"]["id"] for r in result["events"]] == ["open", "z-first", "a-last"]
    decimal_fields(result["snapshot"], equity="1000", price_pnl="0")


def test_ambiguous_duplicate_exit_slot_is_not_another_fill():
    account = CCryptoAccount(conf())
    account.apply(opening())
    account.apply(close(1000, quantity="0.5", event_id="first"))
    before = account.to_dict()
    with pytest.raises(CChanException):
        account.apply(close(1000, quantity="0.5", event_id="another-id-same-slot"))
    assert account.to_dict() == before
