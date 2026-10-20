"""解析有限搜索产物到显式的未验证参数建议；不更新当前活动配置。"""
import os
from typing import Optional

from Common.ChanException import CChanException, ErrCode
from .artifact import write_once
from .para_automl import read_search_result


def parse_automl_result(result_path: str, output_path: Optional[str] = None) -> str:
    """必须指定新文件路径；该建议仍需独立窗口验证和人工部署选择。"""
    if output_path is None:
        raise CChanException("必须指定独立建议文件，不允许默认写活动 OpenConfig", ErrCode.CONFIG_ERROR)
    result, search_sha = read_search_result(result_path)
    best = result.best.to_dict()

    try:
        import yaml  # 懒加载
        dump = yaml.safe_dump
    except ImportError as e:
        raise CChanException("生成 OpenConfig.yaml 需要 pyyaml", ErrCode.CONFIG_ERROR) from e

    open_conf = {
        "schema": "chan-parameter-proposal-v1", "status": "unvalidated_parameter_proposal",
        "search_sha256": search_sha, "run": result.metadata,
        "open_para": best["para"],           # 最优开仓参数(score_thred/止损止盈/bsp类型过滤等)
        "automl_score": best["score"],
        "eval_summary": {
            k: best["eval"].get(k)
            for k in ("trade_cnt", "win_rate", "profit_loss_ratio", "total_profit_rate", "max_drawdown")
        },
        "source": os.path.abspath(result_path),
    }
    raw = dump(open_conf, allow_unicode=True, sort_keys=True).encode("utf-8")
    # 发布前按原 reader 格式重读，不能导出与冻结参数不同的内容。
    if yaml.safe_load(raw) != open_conf:
        raise CChanException("参数建议导出/重读漂移", ErrCode.CONFIG_ERROR)
    write_once(output_path, raw)
    print(f"[parse_automl_result] 未验证参数建议已写入 {output_path}(score={best['score']:.4f})")
    return output_path


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".."))
    if len(sys.argv) < 2:
        print("usage: python parse_automl_result.py <automl_result.jsonl> [output.yaml]")
        sys.exit(1)
    parse_automl_result(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
