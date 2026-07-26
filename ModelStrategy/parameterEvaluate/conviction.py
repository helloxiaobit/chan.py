"""conviction 自适应风险预算:按结构性信念给逐笔交易盖 risk_mult 戳

原理:多路信号流(不同级别栈)在同一标的上的共振/冲突是免费的置信度信息——
同向在场 = 多级别结构共振(加码),对向在场 = 级别间打架(减码)。
bs_type 分层:纯1类(趋势反转确认)与1p(盘整背驰)历史均R不同,可分层预算。

用法(标定只允许在 2021-25 窗口):
    trades = stamp_conviction(merged_trades, co_dir_mult=1.5, opp_dir_mult=0.5)
    pf = portfolio_eval(trades, CPortfolioConfig(risk_pct=0.01))

戳完后 portfolio_eval 按 risk_pct × risk_mult 定单笔风险(仍受杠杆帽约束)。
"""
from typing import Dict, List, Optional

from .eval_strategy import CTradeRecord


def stamp_conviction(
    trades: List[CTradeRecord],
    co_dir_mult: float = 1.0,    # 开仓时已有同向持仓 → 风险乘数(>1 加码)
    opp_dir_mult: float = 1.0,   # 开仓时已有对向持仓 → 风险乘数(<1 减码)
    bs_mults: Optional[Dict[str, float]] = None,  # bs_type→乘数,如 {"1":1.2,"1p":0.8}
    stack_mults: Optional[Dict[str, float]] = None,  # 信号栈→乘数(交易需带 .stack 戳)
    mult_cap: float = 2.0,       # 单笔乘数上限(防叠乘爆仓)
) -> List[CTradeRecord]:
    """按时间回放交易流,在每笔开仓时刻依据在场持仓方向盖 risk_mult 戳(原地修改并返回)

    注意:同一时刻先平后开(与 portfolio_eval 的事件排序一致),避免刚平的仓算作在场。
    """
    events = []  # (ts, order, kind, trade)
    for t in trades:
        events.append((t.open_ts, 1, "open", t))
        events.append((t.close_ts, 0, "close", t))
    events.sort(key=lambda x: (x[0], x[1]))

    open_dir: Dict[int, bool] = {}  # trade id → is_buy
    for _, _, kind, t in events:
        if kind == "close":
            open_dir.pop(id(t), None)
            continue
        mult = 1.0
        same = sum(1 for d in open_dir.values() if d == t.is_buy)
        opp = len(open_dir) - same
        if same > 0:
            mult *= co_dir_mult
        if opp > 0:
            mult *= opp_dir_mult
        if bs_mults:
            mult *= bs_mults.get(str(t.bs_type), 1.0)
        if stack_mults:
            mult *= stack_mults.get(getattr(t, "stack", ""), 1.0)
        t.risk_mult = min(mult, mult_cap)
        open_dir[id(t)] = t.is_buy
    return trades
