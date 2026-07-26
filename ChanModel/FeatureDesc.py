import re
from typing import Dict, List


class CFeatureDesc:
    def __init__(self, name: str, group: str, desc: str = ""):
        self.name = name
        self.group = group
        self.desc = desc


class CFeatureReg:
    """特征注册表:名称→分组/描述;支持正则模式注册(特征名含动态部分,如 bi_pre{i}_)

    用途:回测结束后调用 check_features 列出未注册特征,防止特征命名失控/拼写错误。
    """

    def __init__(self):
        self.descs: Dict[str, CFeatureDesc] = {}
        self.patterns: List = []  # (compiled_pattern, group, desc)

    def register(self, name: str, group: str, desc: str = ""):
        self.descs[name] = CFeatureDesc(name, group, desc)

    def register_pattern(self, pattern: str, group: str, desc: str = ""):
        self.patterns.append((re.compile(f"^{pattern}$"), group, desc))

    def is_registered(self, name: str) -> bool:
        if name in self.descs:
            return True
        return any(p.match(name) for p, _, _ in self.patterns)

    def get_group(self, name: str) -> str:
        if name in self.descs:
            return self.descs[name].group
        for p, group, _ in self.patterns:
            if p.match(name):
                return group
        return "unknown"

    def check_features(self, feat_names) -> List[str]:
        # 返回未注册的特征名列表(回测后检查入口)
        return sorted({name for name in feat_names if not self.is_registered(name)})


FEATURE_REG = CFeatureReg()

# 开源版 bsp 计算路径已有的内置特征
for _name in (
    "bsp_bi_amp", "bsp1_bi_amp", "bsp2_bi_amp", "bsp2_break_bi_amp", "bsp2_retrace_rate",
    "bsp2s_bi_amp", "bsp2s_break_bi_amp", "bsp2s_lv", "bsp2s_retrace_rate",
    "bsp3_bi_amp", "bsp3_zs_height", "divergence_rate", "zs_cnt",
):
    FEATURE_REG.register(_name, group="bsp_builtin", desc="bsp计算路径内置特征")
# demo5 的开仓K线特征
FEATURE_REG.register("open_klu_rate", group="klu", desc="开仓K线涨跌幅(demo5)")
