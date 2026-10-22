"""开仓参数(阈值/止损/bsp类型过滤等,automl 产物)

优先读 Trade/Script/OpenConfig.yaml(parse_automl_result 生成,已gitignore),
不存在则读 OpenConfig_demo.yaml。
"""
import os
import copy
import math
from typing import Optional
from Common.ChanException import CChanException, ErrCode


class COpenConfig:
    def __init__(self, path: Optional[str] = None, *, parameters=None):
        if parameters is not None:
            if (path is not None or not isinstance(parameters, dict)
                    or set(parameters)-{"score_thred", "max_sl_rate", "max_profit_rate", "bsp_type_filter"}):
                raise CChanException("显式开仓/退出参数形状无效", ErrCode.CONFIG_ERROR)
            for key in ("score_thred", "max_sl_rate", "max_profit_rate"):
                value = parameters.get(key)
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0
                        or (key == "score_thred" and value > 1) or (key == "max_sl_rate" and value >= 1)):
                    raise CChanException("显式开仓/退出阈值必须有限且单位有效", ErrCode.CONFIG_ERROR)
            if parameters.get("bsp_type_filter") is not None and not isinstance(parameters["bsp_type_filter"], str):
                raise CChanException("显式买卖点过滤参数必须是字符串", ErrCode.CONFIG_ERROR)
            conf = copy.deepcopy(parameters)
        else:
            conf = self._load(path)
        para = conf.get("open_para", conf)  # 兼容 automl 产物与手写两种格式
        self.score_thred: Optional[float] = para.get("score_thred")
        self.max_sl_rate: Optional[float] = para.get("max_sl_rate")
        self.max_profit_rate: Optional[float] = para.get("max_profit_rate")
        self.bsp_type_filter: Optional[str] = para.get("bsp_type_filter")
        self.raw = conf

    @classmethod
    def configured(cls, env=None):
        from Config.EnvConfig import CEnv
        trade = (env or CEnv.get_instance()).get_section("trade")
        if "open_para" in trade or "paper" in trade:
            parameters = trade.get("open_para", {})
            if not isinstance(parameters, dict):
                raise CChanException("显式 open_para 不能回退到私有文件", ErrCode.CONFIG_ERROR)
            return cls(parameters=parameters)
        return cls()  # unchanged legacy file-based configuration

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
        return bool(set(str(bstype).replace("q", "").replace("z", "").split(",")) & set(self.bsp_type_filter.split(",")))

    def pass_score(self, score: Optional[float]) -> bool:
        if self.score_thred is None:
            return True
        return score is not None and score >= self.score_thred
