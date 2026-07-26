"""组合级复利核算器测试"""
import pytest

from ModelStrategy.parameterEvaluate.conviction import stamp_conviction
from ModelStrategy.parameterEvaluate.portfolio_eval import (CPortfolioConfig, portfolio_eval,
                                                            scale_risk_to_target)

DAY = 86400.0


class FakeTrade:
    def __init__(self, open_ts, close_ts, profit_rate, risk_rate=0.02, bs_type="1", open_price=100.0,
                 is_buy=True):
        self.open_ts = open_ts
        self.close_ts = close_ts
        self.profit_rate = profit_rate
        self.risk_rate = risk_rate
        self.bs_type = bs_type
        self.open_price = open_price
        self.is_buy = is_buy


def test_r_sizing_and_compounding():
    # 单笔风险1%,止损距离2% → 名义=权益×0.5;亏到止损恰亏1%权益(费前)
    conf = CPortfolioConfig(risk_pct=0.01, taker_fee=0.0, maker_fee=0.0, max_leverage=10)
    trades = [FakeTrade(0, DAY, -2.0, risk_rate=0.02)]
    res = portfolio_eval(trades, conf)
    assert res.total_return == pytest.approx(-0.01)
    # 复利:两笔各+2%(名义0.5×权益)→ 权益×(1.01)^2
    trades = [FakeTrade(0, DAY, 2.0), FakeTrade(2 * DAY, 3 * DAY, 2.0)]
    res = portfolio_eval(trades, conf)
    assert res.total_return == pytest.approx(1.01 ** 2 - 1)


def test_fees_and_maker():
    conf = CPortfolioConfig(risk_pct=0.01, taker_fee=0.001, maker_fee=0.0002, max_leverage=10)
    # 收益0,taker进出 → 亏 0.5×(0.001+0.001)=0.1%
    res = portfolio_eval([FakeTrade(0, DAY, 0.0)], conf)
    assert res.total_return == pytest.approx(-0.5 * 0.002)
    # z前缀限价入场用maker
    res = portfolio_eval([FakeTrade(0, DAY, 0.0, bs_type="z1")], conf)
    assert res.total_return == pytest.approx(-0.5 * 0.0012)


def test_concurrency_and_leverage_caps():
    conf = CPortfolioConfig(risk_pct=0.01, taker_fee=0, maker_fee=0, max_concurrent=2, max_leverage=10)
    trades = [FakeTrade(0, 10 * DAY, 1.0), FakeTrade(1 * DAY, 10 * DAY, 1.0),
              FakeTrade(2 * DAY, 10 * DAY, 1.0)]  # 第三笔并发超限
    res = portfolio_eval(trades, conf)
    assert res.trade_cnt == 2 and res.skipped == 1
    # 单笔杠杆上限:止损距离0.1% → 理论名义10x,被 max_pos_leverage=1.5 截断
    conf2 = CPortfolioConfig(risk_pct=0.01, taker_fee=0, maker_fee=0, max_pos_leverage=1.5)
    res2 = portfolio_eval([FakeTrade(0, DAY, 1.0, risk_rate=0.001)], conf2)
    assert res2.total_return == pytest.approx(1.5 * 0.01)


def test_drawdown_and_cagr():
    conf = CPortfolioConfig(risk_pct=0.01, taker_fee=0, maker_fee=0)
    # +2% → -2%(名义0.5权益 → ±1%权益)
    trades = [FakeTrade(0, DAY, 2.0), FakeTrade(2 * DAY, 365 * DAY, -2.0)]
    res = portfolio_eval(trades, conf)
    assert res.max_drawdown == pytest.approx(0.01, rel=1e-6)
    assert res.span_days == pytest.approx(365)
    assert res.cagr == pytest.approx(res.total_return, rel=1e-6)  # 恰好一年


def test_scale_risk_to_target():
    trades = [FakeTrade(i * 2 * DAY, (i * 2 + 1) * DAY, 4.0 if i % 3 else -2.0)
              for i in range(60)]
    out = scale_risk_to_target(trades, target_dd=0.25)
    assert len(out["rows"]) >= 5
    assert out["best_within_dd"] is not None
    assert out["best_within_dd"]["max_drawdown"] <= 0.25


def test_drawdown_throttle_recovery():
    # 无节流:三笔 -2%、-2%、-2%(风险1%/笔)→ 各亏1%权益
    conf = CPortfolioConfig(risk_pct=0.01, taker_fee=0, maker_fee=0,
                            throttle_dd=0.015, throttle_mult=0.5)
    trades = [FakeTrade(0, DAY, -2.0), FakeTrade(2 * DAY, 3 * DAY, -2.0),
              FakeTrade(4 * DAY, 5 * DAY, -2.0)]
    res = portfolio_eval(trades, conf)
    # 前两笔全额(累计回撤~1.99%>1.5%),第三笔节流半仓
    expect = 1.0 * 0.99 * 0.99
    expect -= expect * 0.005
    assert res.total_return == pytest.approx(expect - 1.0, rel=1e-6)
    # 收复高点后恢复全仓
    trades2 = [FakeTrade(0, DAY, -2.0), FakeTrade(2 * DAY, 3 * DAY, -2.0),
               FakeTrade(4 * DAY, 5 * DAY, 10.0), FakeTrade(6 * DAY, 7 * DAY, -2.0)]
    res2 = portfolio_eval(trades2, conf)
    eq = 1.0 * 0.99 * 0.99
    eq += eq * 0.5 * 0.01 * (10.0 / 2.0)   # 节流半仓的+10%(名义=权益×0.5×0.25)
    eq -= eq * 0.01                        # 已收复 → 全仓
    assert res2.total_return == pytest.approx(eq - 1.0, rel=1e-6)


def test_conviction_risk_mult():
    conf = CPortfolioConfig(risk_pct=0.01, taker_fee=0, maker_fee=0, max_leverage=10)
    # risk_mult 戳直接缩放单笔风险:2.0 → 亏损翻倍
    t = FakeTrade(0, DAY, -2.0)
    t.risk_mult = 2.0
    assert portfolio_eval([t], conf).total_return == pytest.approx(-0.02)

    # 同向共振加码:第二笔开仓时首笔仍在场且同向 → co_dir_mult
    a = FakeTrade(0, 10 * DAY, 2.0, is_buy=True)
    b = FakeTrade(1 * DAY, 10 * DAY, 2.0, is_buy=True)
    stamp_conviction([a, b], co_dir_mult=1.5, opp_dir_mult=0.5)
    assert getattr(a, "risk_mult") == pytest.approx(1.0)
    assert getattr(b, "risk_mult") == pytest.approx(1.5)

    # 对向在场减码;先平后开不算在场
    c = FakeTrade(0, 5 * DAY, 2.0, is_buy=True)
    d = FakeTrade(2 * DAY, 10 * DAY, 2.0, is_buy=False)   # c 在场 → 对向减码
    e = FakeTrade(5 * DAY, 10 * DAY, 2.0, is_buy=False)   # c 恰在同刻平掉 → 只剩 d 同向
    stamp_conviction([c, d, e], co_dir_mult=1.5, opp_dir_mult=0.5)
    assert getattr(d, "risk_mult") == pytest.approx(0.5)
    assert getattr(e, "risk_mult") == pytest.approx(1.5)

    # bs_type 分层与乘数上限
    f = FakeTrade(0, DAY, 2.0, bs_type="1p")
    stamp_conviction([f], bs_mults={"1p": 0.8})
    assert getattr(f, "risk_mult") == pytest.approx(0.8)
    g = FakeTrade(0, 10 * DAY, 2.0)
    h = FakeTrade(1 * DAY, 10 * DAY, 2.0, bs_type="1")
    stamp_conviction([g, h], co_dir_mult=3.0, bs_mults={"1": 1.5}, mult_cap=2.0)
    assert getattr(h, "risk_mult") == pytest.approx(2.0)


def test_exit_maker_fee():
    conf = CPortfolioConfig(risk_pct=0.01, taker_fee=0.001, maker_fee=0.0002, max_leverage=10)
    # 收益0:taker进+maker出 → 亏 0.5×(0.001+0.0002)
    t = FakeTrade(0, DAY, 0.0)
    t.exit_maker = True
    assert portfolio_eval([t], conf).total_return == pytest.approx(-0.5 * 0.0012)
