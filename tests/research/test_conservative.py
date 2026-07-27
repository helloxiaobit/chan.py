import math

import pytest

from ModelStrategy.research.conservative import (
    ConservativeConfig,
    PortfolioError,
    conservative_portfolio_eval,
)
from ModelStrategy.research.execution import ExecutionTrade
from ModelStrategy.research.market import FundingEvent, MarketBar, MarketDataError, MarketSeries


HOUR = 3600
DAY = 86400


def execution_trade(**overrides):
    values = {
        "symbol": "BTC/USDT",
        "signal_ts": 0,
        "fill_ts": 0,
        "close_ts": 3 * HOUR,
        "is_buy": True,
        "open_price": 100.0,
        "close_price": 110.0,
        "initial_sl_price": 90.0,
        "risk_rate": 0.1,
        "risk_mult": 1.0,
        "bs_type": "1",
        "stack": "S1",
        "entry_role": "taker",
        "entry_timing": "bar_close",
        "exit_role": "taker",
        "is_pyramid": False,
        "reason": "strategy_exit",
    }
    values.update(overrides)
    return ExecutionTrade(**values)


def mark_series(closes, *, interval=HOUR, timestamps=None):
    times = (
        [index * interval for index in range(len(closes))]
        if timestamps is None
        else timestamps
    )
    bars = tuple(
        MarketBar(ts=ts, open=close, high=close, low=close, close=close)
        for ts, close in zip(times, closes)
    )
    return MarketSeries("BTC/USDT", interval, bars)


def config(**overrides):
    values = {
        "risk_pct": 0.1,
        "taker_fee": 0.0,
        "maker_fee": 0.0,
        "max_concurrent": 4,
        "max_leverage": 3.0,
        "max_pos_leverage": 1.5,
        "initial_equity": 1.0,
    }
    values.update(overrides)
    return ConservativeConfig(**values)


def evaluate(trades, marks, funding=(), **config_overrides):
    return conservative_portfolio_eval(
        trades,
        {"BTC/USDT": marks},
        funding,
        config(**config_overrides),
    )


def test_unrealized_loss_counts_toward_drawdown_before_close():
    trade = execution_trade(close_ts=3 * DAY)
    marks = mark_series([100, 80, 100, 110], interval=DAY)
    result = evaluate([trade], marks)
    assert result.total_return > 0
    assert result.max_drawdown == pytest.approx(0.2)


@pytest.mark.parametrize(
    "is_buy,expected_sign", [(True, -1), (False, 1)]
)
def test_funding_payment_direction(is_buy, expected_sign):
    trade = execution_trade(
        is_buy=is_buy,
        close_ts=2 * HOUR,
        close_price=100,
        initial_sl_price=90 if is_buy else 110,
    )
    result = evaluate(
        [trade],
        mark_series([100, 100, 100]),
        [FundingEvent(HOUR, "BTC/USDT", 0.001)],
    )
    assert math.copysign(1, result.funding_pnl) == expected_sign


def test_entry_fee_reduces_equity_immediately():
    trade = execution_trade(entry_role="maker", close_price=100)
    result = evaluate(
        [trade],
        mark_series([100, 100, 100, 100]),
        maker_fee=0.01,
    )
    entry_point = next(point for point in result.curve if point.kind == "open")
    assert entry_point.equity < 1.0


def test_fees_use_entry_and_exit_trade_values():
    result = evaluate(
        [execution_trade()],
        mark_series([100, 100, 100, 110]),
        risk_pct=0.1,
        taker_fee=0.01,
        max_leverage=100,
        max_pos_leverage=100,
    )
    assert result.accepted_trades[0].entry_notional == pytest.approx(1.0)
    assert result.fees == pytest.approx(0.01 + 0.011)


def test_missing_mark_inside_holding_window_fails():
    marks = mark_series([100, 110], timestamps=[0, 2 * HOUR])
    trade = execution_trade(close_ts=2 * HOUR)
    with pytest.raises(MarketDataError, match="gap"):
        evaluate([trade], marks)


def test_position_leverage_cap_limits_entry_notional():
    trade = execution_trade(risk_rate=0.01)
    result = evaluate(
        [trade],
        mark_series([100, 100, 100, 110]),
        risk_pct=1.0,
        max_pos_leverage=0.5,
    )
    assert result.accepted_trades[0].entry_notional == pytest.approx(0.5)


def test_new_position_sizes_from_current_marked_equity():
    first = execution_trade(stack="S1")
    second = execution_trade(
        signal_ts=2 * HOUR,
        fill_ts=2 * HOUR,
        stack="S2",
        close_price=100,
    )
    result = evaluate(
        [first, second],
        mark_series([100, 80, 80, 110]),
    )
    second_result = next(
        item for item in result.accepted_trades if item.trade.stack == "S2"
    )
    assert second_result.entry_notional == pytest.approx(0.8)


def test_concurrency_rejection_is_counted_and_never_closed_later():
    first = execution_trade(stack="S1")
    second = execution_trade(stack="S2")
    result = evaluate(
        [second, first],
        mark_series([100, 100, 100, 110]),
        max_concurrent=1,
    )
    assert len(result.accepted_trades) == 1
    assert len(result.skipped_trades) == 1
    assert result.skipped_trades[0].reason == "max_concurrent"


def test_funding_is_applied_before_close_at_same_timestamp():
    trade = execution_trade(close_ts=HOUR, close_price=100)
    result = evaluate(
        [trade],
        mark_series([100, 100]),
        [FundingEvent(HOUR, "BTC/USDT", 0.001)],
    )
    kinds = [point.kind for point in result.curve if point.ts == HOUR]
    assert kinds.index("funding") < kinds.index("close")
    assert result.funding_pnl < 0


def test_same_timestamp_round_trip_is_opened_then_closed_atomically():
    trade = execution_trade(
        signal_ts=HOUR,
        fill_ts=HOUR,
        close_ts=HOUR,
        close_price=95,
        reason="same_bar_stop",
    )
    result = evaluate([trade], mark_series([100], timestamps=[HOUR]))
    assert len(result.accepted_trades) == 1
    assert result.total_return < 0
    kinds = [point.kind for point in result.curve]
    assert kinds == ["initial", "open", "close", "mark"]


def test_duplicate_execution_trade_is_rejected():
    trade = execution_trade()
    with pytest.raises(PortfolioError, match="duplicate"):
        evaluate([trade, trade], mark_series([100, 100, 100, 110]))


def test_non_positive_equity_fails_immediately():
    trade = execution_trade(close_ts=2 * HOUR, close_price=100)
    with pytest.raises(PortfolioError, match="positive"):
        evaluate(
            [trade],
            mark_series([100, 100, 100]),
            [FundingEvent(HOUR, "BTC/USDT", 2.0)],
        )
