"""三级联立策略:高周期定方向 + 中周期定交易 + 低周期区间套入场

lv_list 约定(从大到小):[趋势级别, 交易级别, 入场级别],如 [K_4H, K_60M, K_15M];
也兼容两级别 [趋势, 交易](入场确认退化为交易级别自身,即 require_sub_confirm 自动失效)。

角色分工(框架为每个级别实例化一个策略,按 update 传入的 lv 区分角色):
- 趋势级别(lv=0):不开仓。方向 = 窗口内最新形态学 bsp 方向,否则最新确认线段方向
- 交易级别(lv=1):形态学 bsp 同向 + 分型确认 + 突破 → 开仓;结合区间套确认
- 入场级别(lv=2):标记 1类买卖点(分型确认即记,动力学 cbsp),供交易级别区间套引用,
  同时其分型止损价作为更精细的入场止损参考

strategy_para(在 CStrategy 通用参数之外):
- trend_valid_bars:  趋势级别 bsp 的有效窗口(根),默认 60
- qjt_window:        交易级别 bsp 出现后,多少根交易级别K线内接受入场级别确认,默认 8
- require_sub_confirm: 必须入场级别区间套确认才开仓,默认 True(两级别时自动失效)
- trade_bs_types:    交易级别允许触发的 bsp 类型,默认 "1,1p,2,2s,3a,3b"
- cover_on_trend_flip: 趋势级别方向翻转即平仓,默认 True
其余沿用:strict_open/short_shelling/judge_on_close/max_sl_rate/max_profit_rate
"""
from typing import TYPE_CHECKING, List, Optional, Tuple

from Common.CEnum import BI_DIR, FX_TYPE

from .CustomBSP import CCustomBSP
from .Signal import CSignal
from .Strategy import CStrategy

if TYPE_CHECKING:
    from Chan import CChan
    from KLine.KLine_List import CKLine_List


class CMultiLevelStrategy(CStrategy):
    def __init__(self, conf):
        super(CMultiLevelStrategy, self).__init__(conf=conf)
        self.opened_bsp_klu_idx = set()  # 交易级别:已开仓过的 bsp(按klu.idx)
        self.marked_bsp_klu_idx = set()  # 入场级别:已标记过的 1类 bsp

    # ===== 角色 =====
    @staticmethod
    def trade_lv_idx(chan: 'CChan') -> int:
        return 1 if len(chan.lv_list) >= 2 else 0

    def get_role(self, chan: 'CChan', lv: int) -> str:
        trade_lv = self.trade_lv_idx(chan)
        if lv == trade_lv:
            return "trade"
        if lv < trade_lv:
            return "trend"
        return "entry"

    def get_p(self, name: str, default=None):
        v = self.conf.strategy_para.get(name, default)
        return default if v is None else v

    # ===== 趋势级别:方向判定 =====
    def cal_trend_direction(self, chan: 'CChan') -> int:
        """返回 1(多)/-1(空)/0(不明);两级别以上时用 lv0,单级别恒为双向由调用方处理"""
        trend_data = chan[0]
        if len(trend_data) == 0:
            return 0
        cur_idx = trend_data[-1][-1].idx
        # 1) 窗口内最新 bsp 方向优先(转折信号)
        # 注意:回测引擎按整根喂入父级别K线,当前趋势级别K线在其子K线决策时还未走完,
        # 故只认当前K线之前确认的 bsp,消除"看到未来的4H分型"的乐观偏差
        for bsp in trend_data.bs_point_lst.getLastestBspList():
            if bsp.klu.idx >= cur_idx:
                continue
            if cur_idx - bsp.klu.idx <= self.get_p("trend_valid_bars", 60):
                return 1 if bsp.is_buy else -1
            break
        # 2) 否则最新确认线段方向(顺势)
        for seg in trend_data.seg_list[::-1]:
            if seg.is_sure:
                return 1 if seg.dir == BI_DIR.UP else -1
        return 0

    # ===== 框架接口 =====
    def try_open(self, chan: 'CChan', lv: int) -> Optional[CCustomBSP]:
        role = self.get_role(chan, lv)
        if role == "trend":
            return None
        if role == "entry":
            return self.try_mark_entry_bsp(chan, lv)
        return self.try_open_trade(chan, lv)

    # ---- 入场级别:1类买卖点标记(动力学:分型确认即记) ----
    def try_mark_entry_bsp(self, chan: 'CChan', lv: int) -> Optional[CCustomBSP]:
        data = chan[lv]
        if len(data) < 3 or len(data.bi_list) == 0:
            return None
        last_bsp_lst = data.bs_point_lst.getLastestBspList()
        if len(last_bsp_lst) == 0:
            return None
        last_bsp = last_bsp_lst[0]
        if last_bsp.klu.idx in self.marked_bsp_klu_idx:
            return None
        if not {t.value for t in last_bsp.type} & {"1", "1p"}:  # 区间套只认低级别1类
            return None
        fx_klc = data[-2]
        if last_bsp.klu.klc.idx != fx_klc.idx:
            return None
        target_fx = FX_TYPE.BOTTOM if last_bsp.is_buy else FX_TYPE.TOP
        if fx_klc.fx != target_fx:
            return None
        cur_klu = data[-1][-1]
        self.marked_bsp_klu_idx.add(last_bsp.klu.idx)
        return CCustomBSP(
            bsp=last_bsp,
            klu=cur_klu,
            bs_type=last_bsp.type2str(),
            is_buy=last_bsp.is_buy,
            target_klc=fx_klc,
            price=cur_klu.close,
            sl_price=fx_klc.low if last_bsp.is_buy else fx_klc.high,
        )

    # ---- 交易级别:三级联立开仓 ----
    def try_open_trade(self, chan: 'CChan', lv: int) -> Optional[CCustomBSP]:
        data = chan[lv]
        if len(data) < 3 or len(data.bi_list) == 0:
            return None
        # 1) 高周期方向
        direction = self.cal_trend_direction(chan) if lv > 0 else 0
        if lv > 0 and direction == 0:
            return None
        # 2) 交易级别形态学 bsp 触发
        last_bsp_lst = data.bs_point_lst.getLastestBspList()
        if len(last_bsp_lst) == 0:
            return None
        last_bsp = last_bsp_lst[0]
        if last_bsp.klu.idx in self.opened_bsp_klu_idx:
            return None
        is_buy = last_bsp.is_buy
        if lv > 0 and ((direction > 0) != is_buy):  # 与高周期方向一致
            return None
        if not is_buy and not self.get_p("short_shelling", True):
            return None
        allow_types = set(str(self.get_p("trade_bs_types", "1,1p,2,2s,3a,3b")).split(","))
        if not {t.value for t in last_bsp.type} & allow_types:
            return None
        fx_klc = data[-2]
        if last_bsp.klu.klc.idx != fx_klc.idx:
            return None
        target_fx = FX_TYPE.BOTTOM if is_buy else FX_TYPE.TOP
        if fx_klc.fx != target_fx:
            return None
        if not self.check_active(data):
            return None
        # 3) 入场级别区间套确认
        sub_ref = None
        has_entry_lv = lv + 1 < len(chan.lv_list)
        if has_entry_lv:
            sub_ref = self.find_qjt_entry(chan, lv, last_bsp, is_buy)
            if sub_ref is None and self.get_p("require_sub_confirm", True):
                return None
        # 4) 突破判断(与 CCustomStrategy 同口径)
        cur_klu = data[-1][-1]
        judge_on_close = self.get_p("judge_on_close", True)
        if is_buy:
            if judge_on_close and cur_klu.close <= fx_klc.high:
                return None
            if not judge_on_close and cur_klu.high <= fx_klc.high:
                return None
            open_price = cur_klu.close if judge_on_close else fx_klc.high
            sl_price = fx_klc.low
            if sub_ref is not None and sub_ref.sl_price is not None:
                sl_price = max(sl_price, sub_ref.sl_price)  # 用更近的15M分型止损收紧
        else:
            if judge_on_close and cur_klu.close >= fx_klc.low:
                return None
            if not judge_on_close and cur_klu.low >= fx_klc.low:
                return None
            open_price = cur_klu.close if judge_on_close else fx_klc.low
            sl_price = fx_klc.high
            if sub_ref is not None and sub_ref.sl_price is not None:
                sl_price = min(sl_price, sub_ref.sl_price)
        sl_price = self.truncate_sl(open_price, sl_price, is_buy)
        self.opened_bsp_klu_idx.add(last_bsp.klu.idx)
        return CCustomBSP(
            bsp=last_bsp,
            klu=cur_klu,
            bs_type=last_bsp.qjt_type() if sub_ref is not None else last_bsp.type2str(),
            is_buy=is_buy,
            target_klc=fx_klc,
            price=open_price,
            sl_price=sl_price,
        )

    def find_qjt_entry(self, chan: 'CChan', lv: int, trade_bsp, is_buy: bool) -> Optional[CCustomBSP]:
        """区间套:交易级别 bsp 出现后 qjt_window 根内,入场级别出现同向1类标记"""
        entry_strategy = chan[lv + 1].cbsp_strategy
        if entry_strategy is None:
            return None
        cur_idx = chan[lv][-1][-1].idx
        window = self.get_p("qjt_window", 8)
        for sub in entry_strategy.cbsp_lst[::-1]:
            if sub.is_buy != is_buy:
                continue
            sup_kl = sub.klu.sup_kl  # 入场级别K线的交易级别父K线
            if sup_kl is None:
                continue
            if sup_kl.idx < trade_bsp.klu.idx:  # 必须在交易级别 bsp 出现之后(含当根)
                break
            if cur_idx - sup_kl.idx <= window:
                return sub
        return None

    def truncate_sl(self, open_price: float, sl_price: float, is_buy: bool) -> float:
        max_sl_rate = self.get_p("max_sl_rate")
        if max_sl_rate is None:
            return sl_price
        if is_buy:
            return max(sl_price, open_price * (1 - abs(max_sl_rate)))
        return min(sl_price, open_price * (1 + abs(max_sl_rate)))

    # ---- 平仓 ----
    def try_close(self, chan: 'CChan', lv: int) -> None:
        if self.get_role(chan, lv) != "trade":
            return
        data = chan[lv]
        if len(data) < 2:
            return
        cur_klu = data[-1][-1]
        trend_dir = self.cal_trend_direction(chan) if lv > 0 else 0
        judge_on_close = self.get_p("judge_on_close", True)
        for cbsp in self.holding_cbsp():
            if cbsp.klu.idx >= cur_klu.idx:
                continue
            # 1) 止损(入场级别分型收紧过的 sl_price)
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
            # 2) 高周期方向翻转
            if self.get_p("cover_on_trend_flip", True) and trend_dir != 0 \
               and (trend_dir > 0) != cbsp.is_buy:
                cbsp.do_close(cur_klu.close, cur_klu, reason="trend_flip")
                continue
            # 3) 交易级别反向 bsp 分型确认
            last_bsp_lst = data.bs_point_lst.getLastestBspList()
            if not last_bsp_lst:
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

    # ---- 实盘信号 ----
    def bsp_signal(self, chan: 'CChan', lv: int) -> List[CSignal]:
        self.signals = []
        if self.get_role(chan, lv) != "trade":
            return self.signals
        data = chan[lv]
        if len(data) < 2 or len(data.bi_list) == 0:
            return self.signals
        direction = self.cal_trend_direction(chan) if lv > 0 else 0
        if lv > 0 and direction == 0:
            return self.signals
        last_bsp_lst = data.bs_point_lst.getLastestBspList()
        if len(last_bsp_lst) == 0:
            return self.signals
        last_bsp = last_bsp_lst[0]
        is_buy = last_bsp.is_buy
        if last_bsp.klu.idx in self.opened_bsp_klu_idx:
            return self.signals
        if lv > 0 and ((direction > 0) != is_buy):
            return self.signals
        if not is_buy and not self.get_p("short_shelling", True):
            return self.signals
        fx_klc = data[-2]
        if last_bsp.klu.klc.idx != fx_klc.idx:
            return self.signals
        target_fx = FX_TYPE.BOTTOM if is_buy else FX_TYPE.TOP
        if fx_klc.fx != target_fx:
            return self.signals
        # 区间套确认状态进入信号类型标记(已确认→ q 前缀)
        sub_ref = self.find_qjt_entry(chan, lv, last_bsp, is_buy) if lv + 1 < len(chan.lv_list) else None
        if sub_ref is None and lv + 1 < len(chan.lv_list) and self.get_p("require_sub_confirm", True):
            return self.signals
        cur_klu = data[-1][-1]
        self.signals.append(CSignal(
            code=chan.code,
            lv=chan.lv_list[lv],
            is_buy=is_buy,
            bs_type=last_bsp.qjt_type() if sub_ref is not None else last_bsp.type2str(),
            sig_klu=cur_klu,
            open_thred=fx_klc.high if is_buy else fx_klc.low,
            sl_thred=(max(fx_klc.low, sub_ref.sl_price) if is_buy else min(fx_klc.high, sub_ref.sl_price))
            if sub_ref is not None and sub_ref.sl_price is not None
            else (fx_klc.low if is_buy else fx_klc.high),
            target_klu_time=cur_klu.time,
        ))
        return self.signals
