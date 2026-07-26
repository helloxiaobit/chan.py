"""多周期稳定性测试:同一组参数在多个时间段滚动评估,检查表现是否稳定"""
from typing import Callable, Dict, List, Tuple

from .eval_strategy import CEvalResult


def multi_cycle_test(
    para: Dict,
    eval_func_builder: Callable[[str, str], Callable[[Dict], CEvalResult]],
    cycles: List[Tuple[str, str]],
) -> List[dict]:
    """cycles: [(begin_time, end_time), ...];eval_func_builder(begin, end) 返回该时段的评估函数"""
    reports = []
    print("===== 多周期稳定性测试 =====")
    for begin, end in cycles:
        res = eval_func_builder(begin, end)(dict(para))
        reports.append({"cycle": (begin, end), "eval": res.to_dict()})
        print(f"[{begin} ~ {end}] 交易{res.trade_cnt}次 胜率{res.win_rate*100:.1f}% "
              f"收益{res.total_profit_rate:.2f}% 回撤{res.max_drawdown:.2f}%")
    return reports
