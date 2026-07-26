from typing import TYPE_CHECKING, List, Optional

from Common.CEnum import FX_TYPE

from .CustomBSP import CCustomBSP
from .Signal import CSignal
from .Strategy import CStrategy

if TYPE_CHECKING:
    from Chan import CChan


class CExamStrategy(CStrategy):
    """试题策略(ExamGenerator 用):最新 bsp 分型完成即输出 cbsp,不做突破判断、不平仓"""

    def __init__(self, conf):
        super(CExamStrategy, self).__init__(conf=conf)
        self.opened_bsp_klu_idx = set()

    def try_open(self, chan: 'CChan', lv: int) -> Optional[CCustomBSP]:
        data = chan[lv]
        if len(data) < 2 or len(data.bi_list) == 0:
            return None
        last_bsp_lst = data.bs_point_lst.getLastestBspList()
        if len(last_bsp_lst) == 0:
            return None
        last_bsp = last_bsp_lst[0]
        if last_bsp.klu.idx in self.opened_bsp_klu_idx:
            return None
        fx_klc = data[-2]
        if last_bsp.klu.klc.idx != fx_klc.idx:
            return None
        target_fx = FX_TYPE.BOTTOM if last_bsp.is_buy else FX_TYPE.TOP
        if fx_klc.fx != target_fx:
            return None
        cur_klu = data[-1][-1]
        self.opened_bsp_klu_idx.add(last_bsp.klu.idx)
        return CCustomBSP(
            bsp=last_bsp,
            klu=cur_klu,
            bs_type=last_bsp.type2str(),
            is_buy=last_bsp.is_buy,
            target_klc=fx_klc,
            price=cur_klu.close,
        )

    def try_close(self, chan: 'CChan', lv: int) -> None:
        pass

    def bsp_signal(self, chan: 'CChan', lv: int) -> List[CSignal]:
        return []
