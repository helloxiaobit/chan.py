"""组合级复利核算:把 eval_strategy 的逐笔交易转成真实资金曲线

与 CEvalResult(每笔1单位名义简单加总)的区别:
- R 仓位:每笔风险恒定占比 risk_pct(名义 = 权益×risk_pct/止损距离比),复利滚动
- 费用:按名义双边收取(taker;限价单可给 maker 费率)
- 并发上限与总杠杆上限(超限的交易跳过/削减)
- 产出:CAGR / 最大回撤 / Calmar / 交易统计 —— 年化50%+回撤<25% 目标的唯一合法记分牌
"""
import datetime
from typing import List, Optional

from .eval_strategy import CTradeRecord


class CPortfolioConfig:
    def __init__(
        self,
        risk_pct: float = 0.01,        # 单笔风险占权益比(止损打掉恰好亏 risk_pct)
        taker_fee: float = 0.0005,     # 单边费率
        maker_fee: float = 0.0002,     # 限价单(z前缀)入场费率
        max_concurrent: int = 4,       # 最大并发持仓
        max_leverage: float = 3.0,     # 总名义/权益上限
        max_pos_leverage: float = 1.5,  # 单笔名义/权益上限(止损太近时防爆杠杆)
        initial_equity: float = 1.0,
        throttle_dd: Optional[float] = None,  # 权益自高点回撤超过该比例时节流(None=不启用)
        throttle_mult: float = 0.5,           # 节流期风险乘数
    ):
        self.risk_pct = risk_pct
        self.taker_fee = taker_fee
        self.maker_fee = maker_fee
        self.max_concurrent = max_concurrent
        self.max_leverage = max_leverage
        self.max_pos_leverage = max_pos_leverage
        self.initial_equity = initial_equity
        self.throttle_dd = throttle_dd
        self.throttle_mult = throttle_mult


class CPortfolioResult:
    def __init__(self, curve, executed, skipped, span_days):
        self.curve = curve              # [(ts, equity)]
        self.executed = executed        # [(trade, notional, pnl)]
        self.skipped = skipped
        self.span_days = span_days
        eq0 = curve[0][1]
        eq_end = curve[-1][1]
        self.total_return = eq_end / eq0 - 1
        years = max(span_days / 365.0, 1e-6)
        self.cagr = (eq_end / eq0) ** (1 / years) - 1 if eq_end > 0 else -1.0
        peak, max_dd = eq0, 0.0
        for _, eq in curve:
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak)
        self.max_drawdown = max_dd
        self.calmar = self.cagr / max_dd if max_dd > 0 else float("inf")
        pnls = [p for _, _, p in executed]
        self.trade_cnt = len(pnls)
        self.win_rate = sum(1 for p in pnls if p > 0) / len(pnls) if pnls else 0.0

    def to_dict(self):
        return {
            "total_return": self.total_return, "cagr": self.cagr,
            "max_drawdown": self.max_drawdown, "calmar": self.calmar,
            "trade_cnt": self.trade_cnt, "win_rate": self.win_rate,
            "skipped": self.skipped, "span_days": self.span_days,
        }

    def __str__(self):
        return (f"总收益 {self.total_return*100:+.1f}% | 年化 {self.cagr*100:+.1f}% | "
                f"最大回撤 {self.max_drawdown*100:.1f}% | Calmar {self.calmar:.2f} | "
                f"交易 {self.trade_cnt}(跳过{self.skipped}) 胜率 {self.win_rate*100:.0f}%")


def portfolio_eval(trades: List[CTradeRecord], conf: Optional[CPortfolioConfig] = None) -> CPortfolioResult:
    """事件驱动模拟:开仓按当时权益定名义,平仓时结算并复利"""
    conf = conf or CPortfolioConfig()
    events = []  # (ts, order, kind, trade) order: 平仓先于同时刻开仓
    for t in trades:
        events.append((t.open_ts, 1, "open", t))
        events.append((t.close_ts, 0, "close", t))
    events.sort(key=lambda x: (x[0], x[1]))

    equity = conf.initial_equity
    peak = equity  # 回撤节流用的权益高水位
    open_pos = {}  # trade id → notional
    curve = [(trades[0].open_ts if trades else 0, equity)]
    executed, skipped = [], 0
    for ts, _, kind, t in events:
        if kind == "open":
            risk_rate = getattr(t, "risk_rate", None)
            if not risk_rate or risk_rate <= 0:
                skipped += 1
                continue
            if len(open_pos) >= conf.max_concurrent:
                skipped += 1
                continue
            gross = sum(open_pos.values())
            # conviction 风险预算:交易可带 risk_mult 戳(见 conviction.stamp_conviction),默认 1.0
            risk = conf.risk_pct * getattr(t, "risk_mult", 1.0)
            # 回撤节流:权益自高水位回撤超过阈值 → 降风险,直至收复
            if conf.throttle_dd is not None and (peak - equity) / peak > conf.throttle_dd:
                risk *= conf.throttle_mult
            notional = min(
                equity * risk / risk_rate,
                equity * conf.max_pos_leverage,
                max(0.0, equity * conf.max_leverage - gross),
            )
            if notional <= 0:
                skipped += 1
                continue
            open_pos[id(t)] = notional
        else:
            notional = open_pos.pop(id(t), None)
            if notional is None:
                continue
            entry_fee = conf.maker_fee if str(t.bs_type).startswith("z") else conf.taker_fee
            pnl = notional * (t.profit_rate / 100.0) - notional * (entry_fee + conf.taker_fee)
            equity += pnl
            peak = max(peak, equity)
            executed.append((t, notional, pnl))
            curve.append((ts, equity))
            if equity <= 0:  # 爆仓保护
                break
    span_days = (curve[-1][0] - curve[0][0]) / 86400 if len(curve) > 1 else 0.0
    return CPortfolioResult(curve, executed, skipped, span_days)


def scale_risk_to_target(trades: List[CTradeRecord], target_dd: float = 0.25,
                         conf: Optional[CPortfolioConfig] = None,
                         risk_grid=(0.003, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03)) -> dict:
    """在回撤约束内找最大可行单笔风险,输出各档 CAGR/DD(风险预算标定)"""
    conf = conf or CPortfolioConfig()
    rows = []
    best = None
    for risk in risk_grid:
        c = CPortfolioConfig(risk_pct=risk, taker_fee=conf.taker_fee, maker_fee=conf.maker_fee,
                             max_concurrent=conf.max_concurrent, max_leverage=conf.max_leverage,
                             max_pos_leverage=conf.max_pos_leverage)
        res = portfolio_eval(trades, c)
        rows.append({"risk_pct": risk, **res.to_dict()})
        if res.max_drawdown <= target_dd and (best is None or res.cagr > best["cagr"]):
            best = rows[-1]
    return {"rows": rows, "best_within_dd": best}
