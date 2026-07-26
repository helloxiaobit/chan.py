from .CustomStrategy import CCustomStrategy


class CSegBspStrategy(CCustomStrategy):
    """demo 策略2:与 CCustomStrategy 逻辑一致,但基于线段买卖点(seg_bs_point_lst)开平仓"""

    use_seg_bsp = True
