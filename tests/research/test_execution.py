import os
from collections import Counter
from pathlib import Path

import pytest

from ModelStrategy.research.boundary import parse_utc
from ModelStrategy.research.execution import build_intent, replay_trade
from ModelStrategy.research.market import (
    MarketBar,
    MarketDataError,
    MarketSeries,
    load_market_series,
)
from ModelStrategy.research.schema import ResearchTrade, load_trades


HOUR = 3600


def bar(
    hour,
    *,
    open_price=100.0,
    high=None,
    low=None,
    close=100.0,
    synthetic=False,
):
    return MarketBar(
        ts=hour * HOUR,
        open=open_price,
        high=max(open_price, close) + 1 if high is None else high,
        low=min(open_price, close) - 1 if low is None else low,
        close=close,
        synthetic=synthetic,
    )


def series(*bars):
    return MarketSeries("BTC/USDT", HOUR, bars)


def trade(**overrides):
    value = {
        "open_ts": HOUR,
        "close_ts": 5 * HOUR,
        "profit_rate": 10.0,
        "risk_rate": 0.05,
        "bs_type": "1",
        "is_buy": True,
        "is_pyramid": False,
    }
    value.update(overrides)
    return ResearchTrade.from_mapping(value)


def intent_for(value, bars):
    return build_intent(value, bars, stack="S1", symbol="BTC/USDT")


def test_build_intent_reconstructs_prices_for_long_and_short():
    bars = series(bar(1, close=100))
    long_intent = intent_for(trade(is_buy=True, profit_rate=10), bars)
    short_intent = intent_for(trade(is_buy=False, profit_rate=10), bars)
    assert long_intent.limit_price == 100
    assert long_intent.close_price == pytest.approx(110)
    assert long_intent.initial_sl_price == pytest.approx(95)
    assert short_intent.close_price == pytest.approx(90)
    assert short_intent.initial_sl_price == pytest.approx(105)


def test_maker_fill_occurs_on_first_touch_not_signal_bar():
    bars = series(
        bar(1, close=100),
        bar(2, open_price=102, close=102, low=101),
        bar(3, open_price=102, close=101, low=99),
        bar(4, open_price=105, close=105),
        bar(5, open_price=109, close=110),
    )
    outcome = replay_trade(
        intent_for(trade(), bars),
        bars,
        patience=8,
        stop_slippage=0.0005,
    )
    replayed = outcome.trade
    assert replayed is not None
    assert replayed.fill_ts == 3 * HOUR
    assert replayed.open_price == 100
    assert replayed.entry_role == "maker"
    assert replayed.entry_timing == "intrabar_limit"


def test_unfilled_limit_chases_at_patience_close_as_taker():
    bars = series(
        bar(1, close=100),
        bar(2, open_price=102, close=102, low=101),
        bar(3, open_price=103, close=103, low=102),
        bar(5, open_price=109, close=110),
    )
    outcome = replay_trade(
        intent_for(trade(), bars),
        bars,
        patience=2,
        stop_slippage=0.0005,
    )
    replayed = outcome.trade
    assert replayed is not None
    assert replayed.fill_ts == 3 * HOUR
    assert replayed.open_price == 103
    assert replayed.risk_rate == pytest.approx((103 - 95) / 103)
    assert replayed.entry_role == "taker"
    assert replayed.entry_timing == "bar_close"


@pytest.mark.parametrize(
    "is_buy,bar_values,expected",
    [
        (True, {"high": 101, "low": 94, "close": 96}, 95 * (1 - 0.0005)),
        (False, {"high": 106, "low": 99, "close": 104}, 105 * (1 + 0.0005)),
    ],
)
def test_same_bar_entry_and_stop_uses_adverse_slippage(
    is_buy, bar_values, expected
):
    bars = series(
        bar(1, close=100),
        bar(2, **bar_values),
        bar(3),
        bar(4),
        bar(5),
    )
    outcome = replay_trade(
        intent_for(trade(is_buy=is_buy), bars),
        bars,
        patience=8,
        stop_slippage=0.0005,
    )
    replayed = outcome.trade
    assert replayed is not None
    assert replayed.close_ts == replayed.fill_ts == 2 * HOUR
    assert replayed.close_price == pytest.approx(expected)
    assert replayed.reason == "same_bar_stop"
    assert replayed.exit_role == "taker"


def test_better_than_limit_fill_is_never_assumed():
    bars = series(
        bar(1, close=100),
        bar(2, open_price=98, high=101, low=97, close=99),
        bar(3),
        bar(4),
        bar(5),
    )
    outcome = replay_trade(
        intent_for(trade(), bars),
        bars,
        patience=8,
        stop_slippage=0.0005,
    )
    assert outcome.trade is not None
    assert outcome.trade.open_price == 100


def test_synthetic_mark_cannot_hide_real_execution_gap():
    bars = series(
        bar(1, close=100),
        bar(2, close=100, synthetic=True),
        bar(3, open_price=102, close=102, low=101),
    )
    with pytest.raises(MarketDataError, match="execution market gap"):
        replay_trade(
            intent_for(trade(), bars),
            bars,
            patience=1,
            stop_slippage=0.0005,
        )


def test_touch_at_original_close_without_same_bar_stop_is_unfilled():
    bars = series(bar(1, close=100), bar(2, high=101, low=99, close=100))
    outcome = replay_trade(
        intent_for(trade(close_ts=2 * HOUR), bars),
        bars,
        patience=8,
        stop_slippage=0.0005,
    )
    assert outcome.status == "unfilled"
    assert outcome.trade is None


def test_pyramid_leg_fills_signal_close_as_taker():
    bars = series(bar(1, close=100), bar(5, open_price=109, close=110))
    outcome = replay_trade(
        intent_for(trade(is_pyramid=True), bars),
        bars,
        patience=8,
        stop_slippage=0.0005,
    )
    assert outcome.trade is not None
    assert outcome.trade.fill_ts == HOUR
    assert outcome.trade.entry_role == "taker"


@pytest.mark.skipif(
    "CHANPY_RESEARCH_ROOT" not in os.environ,
    reason="set CHANPY_RESEARCH_ROOT to verify external IS replay",
)
def test_real_freeze_v4_execution_replay_is_deterministic():
    root = Path(os.environ["CHANPY_RESEARCH_ROOT"])
    begin = parse_utc("2021-01-01")
    end = parse_utc("2026-01-01")
    inputs = (
        (
            "S1",
            root / "from_session_b" / "cache_2125_S1.json",
            "K_60M",
            3600000,
        ),
        (
            "S2",
            root / "cache_2125_S2py10_ispyr.json",
            "K_4H",
            14400000,
        ),
    )
    counts = Counter()
    for stack, path, level, interval_ms in inputs:
        bars = load_market_series(
            root / "btc_mlv.db",
            "BTC/USDT",
            level,
            interval_ms,
            begin,
            end,
        )
        for source_trade in load_trades(path):
            outcome = replay_trade(
                build_intent(
                    source_trade,
                    bars,
                    stack=stack,
                    symbol="BTC/USDT",
                ),
                bars,
                patience=8,
                stop_slippage=0.0005,
            )
            counts[outcome.status] += 1
            if outcome.trade is not None:
                counts[outcome.trade.entry_role] += 1
                counts[outcome.trade.reason] += 1
                assert outcome.trade.close_ts < end
    assert counts == Counter(
        {
            "filled": 424,
            "maker": 393,
            "strategy_exit": 391,
            "same_bar_stop": 33,
            "taker": 31,
            "unfilled": 3,
        }
    )
