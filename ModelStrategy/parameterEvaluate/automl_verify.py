"""automl 结果验证:用最优参数在另一时段重新评估,对比搜索时的表现(防过拟合)"""
import json
from typing import Callable, Dict

from .eval_strategy import CEvalResult


def automl_verify(result_path: str, eval_func: Callable[[Dict], CEvalResult]) -> dict:
    """eval_func 应绑定验证时段(与搜索时段不同)的评估配置"""
    trials = []
    with open(result_path, encoding="utf-8") as f:
        trials.extend(json.loads(line) for line in f if line.strip())
    best = max(trials, key=lambda t: t["score"])
    verify_res = eval_func(dict(best["para"]))
    report = {
        "para": best["para"],
        "search_eval": best["eval"],
        "verify_eval": verify_res.to_dict(),
    }
    print("===== automl 验证(搜索期 vs 验证期)=====")
    print(f"参数: {best['para']}")
    print(f"搜索期: 收益{best['eval'].get('total_profit_rate', 0):.2f}% 胜率{best['eval'].get('win_rate', 0)*100:.1f}%")
    print(f"验证期: 收益{verify_res.total_profit_rate:.2f}% 胜率{verify_res.win_rate*100:.1f}%")
    return report
