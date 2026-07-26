import abc
from typing import TYPE_CHECKING, List, Optional

from ChanModel.Features import CFeatures
from Common.CEnum import KL_TYPE

from .CustomBSP import CCustomBSP
from .Signal import CSignal

if TYPE_CHECKING:
    from Chan import CChan
    from ChanConfig import CChanConfig


class CStrategy(metaclass=abc.ABCMeta):
    """cbsp 策略抽象父类

    框架侧约定:
    - CChan.do_init 时为每个级别实例化一个策略,挂到 CKLine_List.cbsp_strategy
    - 每根新K线完成后(含次级别递归完成)框架调用 update(chan, lv)
    - update 内部依次调用 try_close(平仓判断)与 try_open(开仓判断)
    - 产出的 cbsp 若配置了模型,则打分并按 score_thred 过滤
    """

    def __init__(self, conf: 'CChanConfig'):
        self.conf = conf
        self.cbsp_lst: List[CCustomBSP] = []
        self.signals: List[CSignal] = []  # 最近一次 update 产生的实盘信号
        self.last_judge_klu_idx = -1  # 防止同一根K线重复判断(load_iterator 与 trigger_load 尾部都会触发)

    # ===== 用户需实现的三个接口 =====
    @abc.abstractmethod
    def try_open(self, chan: 'CChan', lv: int) -> Optional[CCustomBSP]:
        # 判断当下(最后一根K线)是否是买卖时机,是则返回 CCustomBSP
        ...

    @abc.abstractmethod
    def try_close(self, chan: 'CChan', lv: int) -> None:
        # 对已开仓未平仓的 cbsp 决定是否平仓,平仓调 CCustomBSP.do_close(...)
        ...

    @abc.abstractmethod
    def bsp_signal(self, chan: 'CChan', lv: int) -> List[CSignal]:
        # 实盘信号:返回下一根K线若满足突破条件即会成为 cbsp 的信号(供 SignalMonitor 落库)
        ...

    # ===== 框架调度入口 =====
    def update(self, chan: 'CChan', lv: int):
        lv_data = chan[lv]
        if len(lv_data) == 0:
            return
        cur_klu = lv_data[-1][-1]
        if cur_klu.idx <= self.last_judge_klu_idx:  # 同一根K线只判断一次
            return
        self.last_judge_klu_idx = cur_klu.idx

        self.update_holding_state(cur_klu)
        if self.conf.cal_cover:
            self.try_close(chan, lv)
            self.check_force_cover(cur_klu)
        if cbsp := self.try_open(chan, lv):
            if self.conf.cal_feature:
                from ChanModel.FeatureEngine import CFeatureEngine  # 懒加载
                cbsp.add_feat(CFeatureEngine.cal_features(chan, lv, cbsp))
            if self.model_filter(cbsp):
                self.cbsp_lst.append(cbsp)

    def update_holding_state(self, cur_klu):
        # 更新持仓中 cbsp 的峰值价格(动态止损/止盈用)
        for cbsp in self.cbsp_lst:
            if not cbsp.is_cover and cbsp.klu.idx < cur_klu.idx:
                cbsp.update_peak_price(cur_klu)

    def check_force_cover(self, cur_klu):
        # max_sl_rate/max_profit_rate 强制止损/止盈(框架级兜底,对所有策略生效)
        judge_on_close = self.get_para("judge_on_close", True)
        for cbsp in self.holding_cbsp():
            if cbsp.klu.idx >= cur_klu.idx:
                continue
            max_sl_rate = self.get_para("max_sl_rate", cbsp.is_buy, cbsp.is_segbsp)
            max_profit_rate = self.get_para("max_profit_rate", cbsp.is_buy, cbsp.is_segbsp)
            judge_price = cur_klu.close if judge_on_close else (
                cur_klu.low if cbsp.is_buy else cur_klu.high)
            profit = cbsp.profit_at(judge_price)
            if max_sl_rate is not None and profit < -abs(max_sl_rate) * 100:
                cbsp.do_close(judge_price, cur_klu, reason="max_sl_rate")
                continue
            if max_profit_rate is None:
                continue
            best_price = cur_klu.close if judge_on_close else (
                cur_klu.high if cbsp.is_buy else cur_klu.low)
            if cbsp.profit_at(best_price) > abs(max_profit_rate) * 100:
                cbsp.do_close(best_price, cur_klu, reason="max_profit_rate")

    def model_filter(self, cbsp: CCustomBSP) -> bool:
        # 模型打分过滤:低于 score_thred 的 cbsp 丢弃;分数存到 cbsp 上(画图/入库用)
        if self.conf.model is None:
            return True
        cbsp.score = self.conf.model.predict(cbsp)
        thred = self.conf.get_score_thred(cbsp.is_buy, cbsp.is_segbsp)
        return thred is None or cbsp.score >= thred

    # ===== 工具方法 =====
    def get_para(self, para: str, is_buy: bool = True, is_seg: bool = False):
        return self.conf.get_strategy_para(para, is_buy, is_seg)

    def holding_cbsp(self) -> List[CCustomBSP]:
        return [cbsp for cbsp in self.cbsp_lst if not cbsp.is_cover]

    def has_open_at(self, klu_idx: int) -> bool:
        return any(cbsp.klu.idx == klu_idx for cbsp in self.cbsp_lst)

    def check_active(self, lv_data) -> bool:
        """交易活跃度检查(A股用;不活跃股票不开仓)

        - 最近 stock_no_active_day 根K线内一字线(非涨跌停)超过 stock_no_active_thred 根 → 不活跃
        - 价格多样性低于 stock_distinct_price_thred → 不活跃
        """
        if not self.conf.cbsp_check_active:
            return True
        day = self.conf.stock_no_active_day
        klu_lst = []
        for klc in lv_data[::-1]:
            for klu in klc[::-1]:
                klu_lst.append(klu)
                if len(klu_lst) >= day:
                    break
            if len(klu_lst) >= day:
                break
        if len(klu_lst) < day:  # K线不足,不做检查
            return True
        yizi_cnt = sum(1 for klu in klu_lst if klu.high == klu.low and klu.limit_flag == 0)
        if yizi_cnt > self.conf.stock_no_active_thred:
            if self.conf.print_inactive_reason:
                print(f"[inactive] 最近{day}根K线一字线{yizi_cnt}根 > {self.conf.stock_no_active_thred}")
            return False
        distinct_price = len({klu.close for klu in klu_lst})
        if distinct_price < self.conf.stock_distinct_price_thred:
            if self.conf.print_inactive_reason:
                print(f"[inactive] 最近{day}根K线价格多样性{distinct_price} < {self.conf.stock_distinct_price_thred}")
            return False
        return True

    @property
    def features(self) -> CFeatures:
        # 最近一个 cbsp 的特征(README: CChan[lv].cbsp_strategy.features[feat_name])
        return self.cbsp_lst[-1].features if self.cbsp_lst else CFeatures(None)

    def getLastCbsp(self) -> Optional[CCustomBSP]:
        return self.cbsp_lst[-1] if self.cbsp_lst else None

    def __iter__(self):
        yield from self.cbsp_lst

    def __len__(self):
        return len(self.cbsp_lst)

    def __getitem__(self, idx) -> CCustomBSP:
        return self.cbsp_lst[idx]

    @staticmethod
    def is_lowest_lv(chan: 'CChan', lv: int) -> bool:
        return lv == len(chan.lv_list) - 1

    @staticmethod
    def lv_type(chan: 'CChan', lv: int) -> KL_TYPE:
        return chan.lv_list[lv]
