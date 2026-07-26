from typing import TYPE_CHECKING, List, Optional

from Common.CEnum import FX_TYPE

from .CustomBSP import CCustomBSP
from .Signal import CSignal
from .Strategy import CStrategy

if TYPE_CHECKING:
    from Chan import CChan
    from KLine.KLine_List import CKLine_List


class CCustomStrategy(CStrategy):
    """demo 策略1:形态学 bsp 分型确认 + 突破分型极值后开仓

    开仓逻辑(以买点为例):
    1. 最新 bsp 是买点,且其所在合并K线是倒数第二根、底分型已形成
    2. 当前K线突破分型K线高点(judge_on_close=True 用收盘价判断,否则盘中触发即可)
    3. strict_open=True 时,若 bsp 之后已完成新的一笔(错过时机)则放弃
    4. 多级别下 use_qjt=True 时,优先尝试区间套买卖点
    平仓逻辑:出现反向 cbsp 开仓信号,或跌破止损价(分型K线低点)
    """

    use_seg_bsp = False  # 子类 CSegBspStrategy 置 True,改用线段买卖点

    def __init__(self, conf):
        super(CCustomStrategy, self).__init__(conf=conf)
        self.opened_bsp_klu_idx = set()  # 已对哪些 bsp(按其klu.idx)开过仓,防重复

    def get_bsp_lst(self, data: 'CKLine_List'):
        return data.seg_bs_point_lst if self.use_seg_bsp else data.bs_point_lst

    def try_open(self, chan: 'CChan', lv: int) -> Optional[CCustomBSP]:
        data = chan[lv]
        if len(data) < 3 or len(data.bi_list) == 0:
            return None
        # 区间套:当前级别不是最低级别时优先尝试
        if self.get_para("use_qjt") and lv != len(chan.lv_list) - 1:
            if qjt_bsp := self.cal_qjt_bsp(data, chan[lv + 1]):
                return qjt_bsp
        last_bsp_lst = self.get_bsp_lst(data).getLastestBspList()
        if len(last_bsp_lst) == 0:
            return None
        last_bsp = last_bsp_lst[0]
        if last_bsp.klu.idx in self.opened_bsp_klu_idx:  # 同一 bsp 只开一次
            return None
        if not last_bsp.is_buy and not self.get_para("short_shelling", last_bsp.is_buy, self.use_seg_bsp):
            return None  # 不做空时卖点不开仓(仅用于 try_close 平多)
        # 分型确认:bsp 所在合并K线是倒数第二根,且分型方向正确
        fx_klc = data[-2]
        if last_bsp.klu.klc.idx != fx_klc.idx:
            if self.get_para("strict_open", last_bsp.is_buy, self.use_seg_bsp):
                return None
            # 非严格开仓:允许在分型确认后的下一笔内追开
            if last_bsp.klu.klc.idx != data[-3].idx or data.bi_list[-1].idx > last_bsp.bi.idx + 1:
                return None
            fx_klc = data[-3]
        if last_bsp.is_buy and fx_klc.fx != FX_TYPE.BOTTOM:
            return None
        if not last_bsp.is_buy and fx_klc.fx != FX_TYPE.TOP:
            return None
        if not self.check_active(data):
            return None
        # 突破判断
        cur_klu = data[-1][-1]
        judge_on_close = self.get_para("judge_on_close", last_bsp.is_buy, self.use_seg_bsp)
        if last_bsp.is_buy:
            if judge_on_close:
                if cur_klu.close <= fx_klc.high:
                    return None
                open_price = cur_klu.close
            else:
                if cur_klu.high <= fx_klc.high:
                    return None
                open_price = fx_klc.high  # 盘中突破,以突破价成交
            sl_price = fx_klc.low
        else:
            if judge_on_close:
                if cur_klu.close >= fx_klc.low:
                    return None
                open_price = cur_klu.close
            else:
                if cur_klu.low >= fx_klc.low:
                    return None
                open_price = fx_klc.low
            sl_price = fx_klc.high
        sl_price = self.truncate_sl_price(open_price, sl_price, last_bsp.is_buy)
        self.opened_bsp_klu_idx.add(last_bsp.klu.idx)
        return CCustomBSP(
            bsp=last_bsp,
            klu=cur_klu,
            bs_type=last_bsp.type2str(),
            is_buy=last_bsp.is_buy,
            target_klc=fx_klc,
            price=open_price,
            sl_price=sl_price,
            is_segbsp=self.use_seg_bsp or last_bsp.is_segbsp,
        )

    def truncate_sl_price(self, open_price: float, sl_price: float, is_buy: bool) -> float:
        # 止损价超过 max_sl_rate 时截断
        max_sl_rate = self.get_para("max_sl_rate", is_buy, self.use_seg_bsp)
        if max_sl_rate is None:
            return sl_price
        if is_buy:
            return max(sl_price, open_price * (1 - abs(max_sl_rate)))
        return min(sl_price, open_price * (1 + abs(max_sl_rate)))

    def try_close(self, chan: 'CChan', lv: int) -> None:
        data = chan[lv]
        if len(data) < 2:
            return
        cur_klu = data[-1][-1]
        for cbsp in self.holding_cbsp():
            if cbsp.klu.idx >= cur_klu.idx:  # 开仓当根不平仓
                continue
            judge_on_close = self.get_para("judge_on_close", cbsp.is_buy, cbsp.is_segbsp)
            # 1. 止损
            if cbsp.sl_price is not None:
                if cbsp.is_buy:
                    hit = cur_klu.close < cbsp.sl_price if judge_on_close else cur_klu.low < cbsp.sl_price
                    price = cur_klu.close if judge_on_close else cbsp.sl_price
                else:
                    hit = cur_klu.close > cbsp.sl_price if judge_on_close else cur_klu.high > cbsp.sl_price
                    price = cur_klu.close if judge_on_close else cbsp.sl_price
                if hit:
                    cbsp.do_close(price, cur_klu, reason="stop_loss")
                    continue
            # 2. 反向分型确认平仓:最新 bsp 方向与持仓相反,且分型已确认
            last_bsp_lst = self.get_bsp_lst(data).getLastestBspList()
            if len(last_bsp_lst) == 0:
                continue
            last_bsp = last_bsp_lst[0]
            if last_bsp.is_buy == cbsp.is_buy:
                continue
            fx_klc = data[-2]
            if last_bsp.klu.klc.idx != fx_klc.idx:
                continue
            target_fx = FX_TYPE.TOP if cbsp.is_buy else FX_TYPE.BOTTOM
            if fx_klc.fx == target_fx:
                cbsp.do_close(cur_klu.close, cur_klu, reason="reverse_bsp")

    def bsp_signal(self, chan: 'CChan', lv: int) -> List[CSignal]:
        """实盘信号:最新 bsp 分型已确认但尚未突破 → 下一根突破分型极值即开仓"""
        data = chan[lv]
        self.signals = []
        if len(data) < 2 or len(data.bi_list) == 0:
            return self.signals
        last_bsp_lst = self.get_bsp_lst(data).getLastestBspList()
        if len(last_bsp_lst) == 0:
            return self.signals
        last_bsp = last_bsp_lst[0]
        if last_bsp.klu.idx in self.opened_bsp_klu_idx:
            return self.signals
        if not last_bsp.is_buy and not self.get_para("short_shelling", last_bsp.is_buy, self.use_seg_bsp):
            return self.signals
        fx_klc = data[-2]
        if last_bsp.klu.klc.idx != fx_klc.idx:
            return self.signals
        target_fx = FX_TYPE.BOTTOM if last_bsp.is_buy else FX_TYPE.TOP
        if fx_klc.fx != target_fx:
            return self.signals
        if not self.check_active(data):
            return self.signals
        cur_klu = data[-1][-1]
        self.signals.append(CSignal(
            code=chan.code,
            lv=chan.lv_list[lv],
            is_buy=last_bsp.is_buy,
            bs_type=last_bsp.type2str(),
            sig_klu=cur_klu,
            open_thred=fx_klc.high if last_bsp.is_buy else fx_klc.low,
            sl_thred=fx_klc.low if last_bsp.is_buy else fx_klc.high,
            target_klu_time=cur_klu.time,
            is_segbsp=self.use_seg_bsp,
        ))
        return self.signals

    def cal_qjt_bsp(self, data: 'CKLine_List', sub_lv_data: 'CKLine_List') -> Optional[CCustomBSP]:
        """区间套(README「区间套策略示例」):父级别买卖点K线下,次级别出现1类 cbsp"""
        last_klu = data[-1][-1]
        last_bsp_lst = self.get_bsp_lst(data).getLastestBspList()
        if len(last_bsp_lst) == 0:
            return None
        last_bsp = last_bsp_lst[0]
        if last_bsp.klu.idx != last_klu.idx:  # 当前K线是父级别的买卖点
            return None
        if last_bsp.klu.idx in self.opened_bsp_klu_idx:
            return None
        if not last_bsp.is_buy and not self.get_para("short_shelling", last_bsp.is_buy, self.use_seg_bsp):
            return None
        if sub_lv_data.cbsp_strategy is None:
            return None
        for sub_bsp in sub_lv_data.cbsp_strategy:  # 对于次级别的买卖点
            if sub_bsp.klu.sup_kl is None or sub_bsp.klu.sup_kl.idx != last_klu.idx:
                continue  # 必须是父级别当前K线下的次级别K线
            if sub_bsp.type2str().find("1") < 0:  # 且是一类买卖点
                continue
            if sub_bsp.is_buy != last_bsp.is_buy:
                continue
            target_klc = None
            if sub_bsp.target_klc is not None and sub_bsp.target_klc[-1].sup_kl is not None:
                target_klc = sub_bsp.target_klc[-1].sup_kl.klc
            self.opened_bsp_klu_idx.add(last_bsp.klu.idx)
            return CCustomBSP(
                bsp=last_bsp,
                klu=last_klu,
                bs_type=last_bsp.qjt_type(),  # 区间套买卖点类型
                is_buy=last_bsp.is_buy,
                target_klc=target_klc,
                price=sub_bsp.open_price,
                sl_price=sub_bsp.sl_price,
                is_segbsp=self.use_seg_bsp,
            )
        return None
