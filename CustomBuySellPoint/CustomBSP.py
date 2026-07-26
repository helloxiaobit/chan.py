from typing import List, Optional

from BuySellPoint.BS_Point import CBS_Point
from ChanModel.Features import CFeatures
from Common.ChanException import CChanException, ErrCode
from KLine.KLine import CKLine
from KLine.KLine_Unit import CKLine_Unit


class CCloseAction:
    """一次平仓动作(支持分批平仓,quota 为本次平掉的额度)"""

    def __init__(self, price: float, klu: CKLine_Unit, reason: str, quota: Optional[float] = None):
        self.price = price
        self.klu = klu
        self.reason = reason
        self.quota = quota

    def __str__(self):
        return f"close@{self.klu.time} price={self.price} reason={self.reason}"


class CCustomBSP:
    """自定义(动力学)买卖点:由策略在"当下"判断产生,可能滞后于形态学 bsp,也不一定正确"""

    def __init__(
        self,
        bsp: Optional[CBS_Point],
        klu: CKLine_Unit,
        bs_type: str,
        is_buy: bool,
        target_klc: Optional[CKLine] = None,
        price: Optional[float] = None,
        sl_price: Optional[float] = None,
        is_segbsp: bool = False,
    ):
        self.bsp = bsp  # 关联的形态学买卖点(可能为 None,如纯区间套产生)
        self.klu = klu  # 开仓判断所在K线
        self.bs_type = bs_type  # 类型字符串,如 "1"/"2s"/"q1"(区间套)
        self.is_buy = is_buy
        self.target_klc = target_klc  # 突破目标合并K线(开仓依据)
        self.open_price: float = price if price is not None else klu.close
        self.sl_price = sl_price  # 止损价
        self.is_segbsp = is_segbsp

        self.is_open = True  # 是否已开仓(本框架 cbsp 产生即视为开仓)
        self.is_cover = False  # 是否已平仓
        self.close_actions: List[CCloseAction] = []
        self.score: Optional[float] = None  # 模型分数
        self.peak_price: float = self.open_price  # 开仓后至今最有利价格(动态止损用)

        # 特征:继承关联 bsp 的特征,策略可继续 add_feat
        self.features = CFeatures(None)
        if bsp is not None:
            for k, v in bsp.features.items():
                self.features.add_feat(k, v)

    def type2str(self) -> str:
        return self.bs_type

    def do_close(self, price: float, close_klu: CKLine_Unit, reason: str, quota: Optional[float] = None):
        # 平仓;quota=None 表示全平
        if self.is_cover:
            raise CChanException(f"cbsp@{self.klu.time} 已平仓,不能重复平仓", ErrCode.RECORD_CLOSED)
        self.close_actions.append(CCloseAction(price, close_klu, reason, quota))
        if quota is None:
            self.is_cover = True

    @property
    def cover_price(self) -> Optional[float]:
        return self.close_actions[-1].price if self.close_actions else None

    @property
    def profit(self) -> Optional[float]:
        # 收益率(%):做多为 (平仓价-开仓价)/开仓价;做空取反;未平仓返回 None
        if not self.close_actions:
            return None
        rate = (self.close_actions[-1].price - self.open_price) / self.open_price
        return rate * 100 if self.is_buy else -rate * 100

    def profit_at(self, price: float) -> float:
        # 以给定价格计算浮动收益率(%)
        rate = (price - self.open_price) / self.open_price
        return rate * 100 if self.is_buy else -rate * 100

    def update_peak_price(self, klu: CKLine_Unit):
        # 更新开仓后至今最有利价格
        if self.is_buy:
            self.peak_price = max(self.peak_price, klu.high)
        else:
            self.peak_price = min(self.peak_price, klu.low)

    def add_feat(self, inp1, inp2=None):
        self.features.add_feat(inp1, inp2)

    def is_win(self) -> Optional[bool]:
        p = self.profit
        return None if p is None else p > 0

    def __str__(self):
        bs = "buy" if self.is_buy else "sell"
        state = f"cover@{self.close_actions[-1].klu.time} profit={self.profit:.2f}%" if self.is_cover else "holding"
        return f"CCustomBSP {bs}({self.bs_type}) @{self.klu.time} open={self.open_price} {state}"
