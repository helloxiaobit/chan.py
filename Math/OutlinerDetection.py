from collections import deque
from typing import Optional

from Common.CEnum import TRADE_INFO_LST
from Common.ChanException import CChanException, ErrCode


class COutlinerDetection:
    """离群点检测(滑窗均值):监控成交量/成交额/换手率等指标的异常放大

    - od_win_width: 滑窗宽度
    - od_mean_thred: 离群阈值(当前值/窗口均值 超过该值视为离群)
    - od_max_zero_cnt: 指标为0的K线最大条数,超过抛异常(None 表示不检测)
    - od_skip_zero: 是否跳过0值(不把0计入窗口)
    增量计算风格,与 Math/ 其他指标一致。
    """

    def __init__(self, field: str, win_width=100, mean_thred=3.0, max_zero_cnt=None, skip_zero=True):
        assert field in TRADE_INFO_LST
        self.field = field
        self.win_width = win_width
        self.mean_thred = mean_thred
        self.max_zero_cnt = max_zero_cnt
        self.skip_zero = skip_zero

        self.window: deque = deque(maxlen=win_width)
        self.win_sum = 0.0
        self.zero_cnt = 0

    def add(self, value: Optional[float]) -> Optional[float]:
        """返回离群分数 = 当前值/窗口均值;窗口为空或无值返回 None"""
        if value is None:
            return None
        if value == 0:
            self.zero_cnt += 1
            if self.max_zero_cnt is not None and self.zero_cnt > self.max_zero_cnt:
                raise CChanException(
                    f"{self.field} 为0的K线数超过 {self.max_zero_cnt}",
                    ErrCode.TRADEINFO_TOO_MUCH_ZERO,
                )
            if self.skip_zero:
                return self.cal_score(0.0)
        score = self.cal_score(value)
        if len(self.window) == self.window.maxlen:
            self.win_sum -= self.window[0]
        self.window.append(value)
        self.win_sum += value
        return score

    def cal_score(self, value: float) -> Optional[float]:
        # 先算分再入窗,避免当前值影响均值
        if len(self.window) == 0:
            return None
        mean = self.win_sum / len(self.window)
        return None if mean == 0 else value / mean

    def is_outliner(self, score: Optional[float]) -> bool:
        return score is not None and score > self.mean_thred
