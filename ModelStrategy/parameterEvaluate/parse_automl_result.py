"""解析 automl 结果,生成线上交易引擎可直接使用的 OpenConfig.yaml"""
import json
import os
from typing import Optional

from Common.ChanException import CChanException, ErrCode


def parse_automl_result(result_path: str, output_path: Optional[str] = None) -> str:
    """读取 para_automl 保存的 trials(jsonl),取最优参数写成 OpenConfig.yaml

    output_path 默认为 Trade/Script/OpenConfig.yaml(已 gitignore,demo 见 OpenConfig_demo.yaml)
    """
    if not os.path.exists(result_path):
        raise CChanException(f"automl结果文件不存在: {result_path}", ErrCode.CONFIG_ERROR)
    trials = []
    with open(result_path, encoding="utf-8") as f:
        trials.extend(json.loads(line) for line in f if line.strip())
    if not trials:
        raise CChanException(f"automl结果为空: {result_path}", ErrCode.CONFIG_ERROR)
    best = max(trials, key=lambda t: t["score"])

    if output_path is None:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
        output_path = os.path.join(repo_root, "Trade", "Script", "OpenConfig.yaml")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        import yaml  # 懒加载
        dump = yaml.safe_dump
    except ImportError as e:
        raise CChanException("生成 OpenConfig.yaml 需要 pyyaml", ErrCode.CONFIG_ERROR) from e

    open_conf = {
        "open_para": best["para"],           # 最优开仓参数(score_thred/止损止盈/bsp类型过滤等)
        "automl_score": best["score"],
        "eval_summary": {
            k: best["eval"].get(k)
            for k in ("trade_cnt", "win_rate", "profit_loss_ratio", "total_profit_rate", "max_drawdown")
        },
        "source": os.path.abspath(result_path),
    }
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# 由 parse_automl_result.py 自动生成,交易引擎开仓参数\n")
        f.write(dump(open_conf, allow_unicode=True, sort_keys=False))
    print(f"[parse_automl_result] 最优参数已写入 {output_path}(score={best['score']:.4f})")
    return output_path


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".."))
    if len(sys.argv) < 2:
        print("usage: python parse_automl_result.py <automl_result.jsonl> [output.yaml]")
        sys.exit(1)
    parse_automl_result(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
