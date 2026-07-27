import os
from collections import Counter
from pathlib import Path

import pytest

from ModelStrategy.research.boundary import ResearchBoundaryError, parse_utc
from ModelStrategy.research.candidate import CandidateTrade, load_candidate_dataset
from ModelStrategy.research.candidate_execution import (
    audit_strategy_fill,
    replay_signal_intent,
    replay_zexit,
)
from ModelStrategy.research.execution import ExecutionTrade
from ModelStrategy.research.market import (
    MarketBar,
    MarketDataError,
    MarketSeries,
    load_market_series,
)


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
        high=max(open_price, close) if high is None else high,
        low=min(open_price, close) if low is None else low,
        close=close,
        synthetic=synthetic,
    )


def series(*values):
    return MarketSeries("BTC/USDT", HOUR, values)


def source_trade(**overrides):
    values = {
        "entry_ts": HOUR,
        "close_ts": 5 * HOUR,
        "open_price": 100.0,
        "close_price": 110.0,
        "risk_rate": 0.05,
        "bs_type": "z1",
        "is_buy": True,
        "is_pyramid": False,
        "reason": "trend_flip",
        "is_closed": True,
    }
    values.update(overrides)
    return CandidateTrade(**values)


def execution_trade(**overrides):
    values = {
        "symbol": "BTC/USDT",
        "signal_ts": HOUR,
        "fill_ts": 2 * HOUR,
        "close_ts": 3 * HOUR,
        "is_buy": True,
        "open_price": 100.0,
        "close_price": 105.0,
        "initial_sl_price": 95.0,
        "risk_rate": 0.05,
        "risk_mult": 1.0,
        "bs_type": "1",
        "stack": "S1bz[4H,1H,15M]",
        "entry_role": "maker",
        "entry_timing": "intrabar_limit",
        "exit_role": "taker",
        "is_pyramid": False,
        "reason": "trend_flip",
    }
    values.update(overrides)
    return ExecutionTrade(**values)


def test_strategy_maker_fill_requires_real_bar_price_touch():
    with pytest.raises(MarketDataError, match="maker fill"):
        audit_strategy_fill(
            source_trade(open_price=95),
            series(bar(1, low=99, high=101)),
            stack="S1bz[4H,1H,15M]",
            stop_slippage=0.0005,
        )


def test_strategy_fill_rejects_synthetic_bar():
    with pytest.raises(MarketDataError, match="synthetic"):
        audit_strategy_fill(
            source_trade(),
            series(bar(1, synthetic=True)),
            stack="S1bz[4H,1H,15M]",
            stop_slippage=0.0005,
        )


def test_strategy_taker_chase_must_equal_fill_bar_close():
    with pytest.raises(MarketDataError, match="taker fill"):
        audit_strategy_fill(
            source_trade(bs_type="1", open_price=99),
            series(bar(1, close=100)),
            stack="S1bz[4H,1H,15M]",
            stop_slippage=0.0005,
        )


@pytest.mark.parametrize(
    "is_buy,low,high,expected",
    [
        (True, 94, 101, 95 * (1 - 0.0005)),
        (False, 99, 106, 105 * (1 + 0.0005)),
    ],
)
def test_audited_maker_fill_applies_same_bar_adverse_stop(
    is_buy, low, high, expected
):
    trade = audit_strategy_fill(
        source_trade(is_buy=is_buy),
        series(bar(1, low=low, high=high)),
        stack="S1bz[4H,1H,15M]",
        stop_slippage=0.0005,
    )
    assert trade.close_ts == trade.fill_ts == HOUR
    assert trade.close_price == pytest.approx(expected)
    assert trade.reason == "same_bar_stop"


def test_signal_intent_requires_source_price_to_match_signal_close():
    bars = series(bar(1, close=101), bar(2, low=99, high=102), bar(5))
    with pytest.raises(MarketDataError, match="source signal price"):
        replay_signal_intent(
            source_trade(open_price=100, bs_type="1"),
            bars,
            stack="S2py10[1D,4H]",
            patience=1,
            stop_slippage=0.0005,
        )


def test_zexit_uses_first_real_touch_and_changes_close_timestamp():
    trade = replay_zexit(
        execution_trade(),
        series(
            bar(3, close=100),
            bar(4, low=99, high=104, close=103),
            bar(5, open_price=105, low=104, high=106, close=105),
        ),
        eligible_reasons=("trend_flip",),
        patience=2,
        end_exclusive_ts=10 * HOUR,
    )
    assert trade.close_ts == 5 * HOUR
    assert trade.close_price == 105
    assert trade.exit_role == "maker"


def test_zexit_chases_at_patience_bar_close_as_taker():
    trade = replay_zexit(
        execution_trade(),
        series(
            bar(3, close=100),
            bar(4, low=99, high=103, close=102),
            bar(5, low=100, high=104, close=103),
        ),
        eligible_reasons=("trend_flip",),
        patience=2,
        end_exclusive_ts=10 * HOUR,
    )
    assert trade.close_ts == 5 * HOUR
    assert trade.close_price == 103
    assert trade.exit_role == "taker"


def test_zexit_window_requires_each_real_bar():
    with pytest.raises(MarketDataError, match="exit market gap"):
        replay_zexit(
            execution_trade(),
            series(bar(3), bar(4, synthetic=True), bar(5)),
            eligible_reasons=("trend_flip",),
            patience=2,
            end_exclusive_ts=10 * HOUR,
        )


def test_zexit_cannot_cross_is_boundary():
    with pytest.raises(ResearchBoundaryError, match="OOS"):
        replay_zexit(
            execution_trade(close_ts=9 * HOUR),
            series(bar(9)),
            eligible_reasons=("trend_flip",),
            patience=2,
            end_exclusive_ts=10 * HOUR,
        )


def test_risk_exit_remains_at_original_taker_close():
    original = execution_trade(reason="stop_loss")
    assert (
        replay_zexit(
            original,
            series(bar(3)),
            eligible_reasons=("trend_flip",),
            patience=2,
            end_exclusive_ts=10 * HOUR,
        )
        == original
    )


def test_real_corrected_btc_candidate_execution_audit():
    research_root_text = os.environ.get("CHANPY_RESEARCH_ROOT")
    if research_root_text is None:
        pytest.skip("set CHANPY_RESEARCH_ROOT to audit real candidate inputs")
    research_root = Path(research_root_text)
    s1_dataset = load_candidate_dataset(
        research_root
        / "normalized"
        / "v5"
        / "BTC_USDT__S1bz__2021-2025.json",
        expected_symbol="BTC/USDT",
        expected_stack="S1bz[4H,1H,15M]",
        expected_entry_kind="strategy_fill",
    )
    hourly = load_market_series(
        research_root / "btc_mlv.db",
        "BTC/USDT",
        "K_60M",
        3600000,
        parse_utc("2021-01-01"),
        parse_utc("2026-01-01"),
    )
    first = s1_dataset.trades[0]
    assert s1_dataset.source.timestamp_offset_seconds == 28800
    assert first.bs_type.startswith("z") and not first.is_pyramid
    audited = audit_strategy_fill(
        first,
        hourly,
        stack=s1_dataset.stack,
        stop_slippage=0.0005,
    )
    assert audited.fill_ts == first.entry_ts
    assert audited.entry_role == "maker"

    end_ts = parse_utc("2026-01-01")
    eligible_reasons = ("reverse_bsp", "trend_flip", "time_stop")
    counts = Counter()
    for source in s1_dataset.trades:
        trade = audit_strategy_fill(
            source,
            hourly,
            stack=s1_dataset.stack,
            stop_slippage=0.0005,
        )
        counts[f"s1_{trade.entry_role}"] += 1
        trade = replay_zexit(
            trade,
            hourly,
            eligible_reasons=eligible_reasons,
            patience=8,
            end_exclusive_ts=end_ts,
        )
        counts[f"s1_exit_{trade.exit_role}"] += 1

    s2_dataset = load_candidate_dataset(
        research_root
        / "normalized"
        / "v5"
        / "BTC_USDT__S2py10__2021-2025.json",
        expected_symbol="BTC/USDT",
        expected_stack="S2py10[1D,4H]",
        expected_entry_kind="signal_intent",
    )
    assert s2_dataset.source.timestamp_offset_seconds == 28800
    four_hour = load_market_series(
        research_root / "btc_mlv.db",
        "BTC/USDT",
        "K_4H",
        14400000,
        parse_utc("2021-01-01"),
        end_ts,
    )
    for source in s2_dataset.trades:
        outcome = replay_signal_intent(
            source,
            four_hour,
            stack=s2_dataset.stack,
            patience=8,
            stop_slippage=0.0005,
        )
        counts[f"s2_{outcome.status}"] += 1
        if outcome.trade is None:
            continue
        counts[f"s2_{outcome.trade.entry_role}"] += 1
        trade = replay_zexit(
            outcome.trade,
            four_hour,
            eligible_reasons=eligible_reasons,
            patience=8,
            end_exclusive_ts=end_ts,
        )
        counts[f"s2_exit_{trade.exit_role}"] += 1

    assert counts == Counter(
        {
            "s1_maker": 271,
            "s1_taker": 59,
            "s1_exit_maker": 180,
            "s1_exit_taker": 150,
            "s2_filled": 95,
            "s2_maker": 64,
            "s2_taker": 31,
            "s2_exit_maker": 70,
            "s2_exit_taker": 25,
        }
    )
