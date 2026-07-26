from typing import Optional

from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit


class CSignal:
    """实盘信号:bsp_signal 接口的返回值,描述"下一根K线若满足突破条件即成为 cbsp"

    字段与交易库信号表对齐(SignalMonitor 落库用):
    - code/lv/bstype/is_buy/open_thred(突破价)/sl_thred(止损价)/target_klu_time
    """

    def __init__(
        self,
        code: str,
        lv,
        is_buy: bool,
        bs_type: str,
        sig_klu: CKLine_Unit,
        open_thred: float,
        sl_thred: Optional[float] = None,
        target_klu_time: Optional[CTime] = None,
        score: Optional[float] = None,
        is_segbsp: bool = False,
        reason: str = "",
    ):
        self.code = code
        self.lv = lv
        self.is_buy = is_buy
        self.bs_type = bs_type
        self.sig_klu = sig_klu
        self.open_thred = open_thred  # 突破该价格即开仓
        self.sl_thred = sl_thred  # 止损价
        self.target_klu_time = target_klu_time  # 突破目标K线时间
        self.score = score  # 模型分(若有)
        self.is_segbsp = is_segbsp
        self.reason = reason

    def __str__(self):
        bs = "buy" if self.is_buy else "sell"
        return f"CSignal[{self.code}] {bs}({self.bs_type}) @{self.sig_klu.time} thred={self.open_thred} sl={self.sl_thred} score={self.score}"
