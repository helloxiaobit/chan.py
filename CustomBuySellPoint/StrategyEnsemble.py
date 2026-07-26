"""策略集合:一次缠论计算,N 组 strategy_para 变体并行评估

用途:walk-forward 合法调参的提速器——chan 结构计算(慢)只跑一遍,
N 个 CMultiLevelStrategy 变体(快)共享其状态各自决策,互不干扰。

用法:
    config = CChanConfig({
        "cbsp_strategy": CStrategyEnsemble,
        "strategy_para": {
            "skip_features": True,          # 扫描通常关特征提速
            "require_sub_confirm": False,   # 公共基底参数
            "variants": [                   # 变体列表(在基底上覆盖)
                {"name": "base"},
                {"name": "intrabar", "sl_intrabar": True},
                {"name": "bos", "entry_mode": "bos_zone"},
            ],
        },
    })
    chan = CChan(...)
    for name, sub in chan[trade_lv].cbsp_strategy.variants:
        trades = trades_from_strategy(code, sub, chan[trade_lv][-1][-1])
"""
from typing import TYPE_CHECKING, List, Optional

from .CustomBSP import CCustomBSP
from .MultiLevelStrategy import CMultiLevelStrategy
from .Signal import CSignal
from .Strategy import CStrategy

if TYPE_CHECKING:
    from Chan import CChan


class CStrategyEnsemble(CStrategy):
    def __init__(self, conf):
        super(CStrategyEnsemble, self).__init__(conf=conf)
        base = {k: v for k, v in conf.strategy_para.items() if k != "variants"}
        specs = conf.strategy_para.get("variants") or [{"name": "base"}]
        self.variants = []
        for i, spec in enumerate(specs):
            spec = dict(spec)
            name = spec.pop("name", f"v{i}")
            sub = CMultiLevelStrategy(conf)
            sub.para_override = {**base, **spec}
            self.variants.append((name, sub))

    # 框架每根K线调 update:扇出给全部变体(各自带同K线去重,互不影响)
    def update(self, chan: 'CChan', lv: int):
        for _, sub in self.variants:
            sub.update(chan, lv)

    def get_variant(self, name: str) -> CMultiLevelStrategy:
        for n, sub in self.variants:
            if n == name:
                return sub
        raise KeyError(name)

    # 抽象接口与迭代协议:代理到第一个变体(画图/eval默认口径)
    def try_open(self, chan: 'CChan', lv: int) -> Optional[CCustomBSP]:
        return None  # update 已扇出,框架不会再直接调用

    def try_close(self, chan: 'CChan', lv: int) -> None:
        pass

    def bsp_signal(self, chan: 'CChan', lv: int) -> List[CSignal]:
        return self.variants[0][1].bsp_signal(chan, lv)

    @property
    def cbsp_lst(self):  # type: ignore[override]
        return self.variants[0][1].cbsp_lst

    @cbsp_lst.setter
    def cbsp_lst(self, v):  # 基类 __init__ 会赋初值,吸收掉
        pass

    def __iter__(self):
        yield from self.variants[0][1].cbsp_lst

    def __len__(self):
        return len(self.variants[0][1].cbsp_lst)
