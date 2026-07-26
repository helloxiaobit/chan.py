"""开仓参数(阈值/止损/bsp类型过滤等,automl 产物)

优先读 Trade/Script/OpenConfig.yaml(parse_automl_result 生成,已gitignore),
不存在则读 OpenConfig_demo.yaml。
"""
import os
from typing import Optional


class COpenConfig:
    def __init__(self, path: Optional[str] = None):
        conf = self._load(path)
        para = conf.get("open_para", conf)  # 兼容 automl 产物与手写两种格式
        self.score_thred: Optional[float] = para.get("score_thred")
        self.max_sl_rate: Optional[float] = para.get("max_sl_rate")
        self.max_profit_rate: Optional[float] = para.get("max_profit_rate")
        self.bsp_type_filter: Optional[str] = para.get("bsp_type_filter")
        self.raw = conf

    @staticmethod
    def _load(path: Optional[str]) -> dict:
        import yaml  # 懒加载
        cur_dir = os.path.dirname(os.path.realpath(__file__))
        candidates = [path] if path else [
            os.path.join(cur_dir, "OpenConfig.yaml"),
            os.path.join(cur_dir, "OpenConfig_demo.yaml"),
        ]
        for p in candidates:
            if p and os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        return {}

    def pass_bsp_type(self, bstype: str) -> bool:
        if not self.bsp_type_filter:
            return True
        return bool(set(str(bstype).replace("q", "").split(",")) & set(self.bsp_type_filter.split(",")))

    def pass_score(self, score: Optional[float]) -> bool:
        if self.score_thred is None:
            return True
        return score is not None and score >= self.score_thred
