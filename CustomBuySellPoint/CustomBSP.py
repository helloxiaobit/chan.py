import json
from typing import List, Optional

from BuySellPoint.BS_Point import CBS_Point
from ChanModel.Features import CFeatures
from Common.ChanException import CChanException, ErrCode
from KLine.KLine import CKLine
from KLine.KLine_Unit import CKLine_Unit
from .Decision import bar_snapshot, canonical_bytes, decision_identity, make_decision, read_decision


class CCloseAction:
    """一次平仓动作(支持分批平仓,quota 为本次平掉的额度)"""

    def __init__(self, price: float, klu: CKLine_Unit, reason: str, quota: Optional[float] = None):
        self._payload = canonical_bytes({"price": price, "bar": bar_snapshot(klu), "reason": reason, "quota": quota})
        self._decision = None
        self.price = price
        self.klu = klu
        self.reason = reason
        self.quota = quota

    @property
    def decision(self):
        return self._decision

    def make_decision(self, opening, sequence):
        payload = json.loads(self._payload)
        at_ms = payload["bar"]["time_ms"]
        if at_ms < opening["identity"]["decision_ms"]:
            raise CChanException("退出不能先于开仓决策", ErrCode.FEATURE_ERROR)
        if payload["bar"].get("market") != opening["identity"]["market"]:
            raise CChanException("退出的 market 来源与开仓不一致", ErrCode.FEATURE_ERROR)
        identity = {**opening["identity"], "kind": "exit", "decision_ms": at_ms,
                    "parent_event_id": opening["event_id"], "sequence": sequence}
        return make_decision(identity, payload)

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
        self.target_price: Optional[float] = None  # 结构化止盈目标(出场引擎用)
        self.exit_state: dict = {}  # 出场引擎状态(初始风险/是否已分批/是否已启动追踪等)
        self.mae: float = 0.0  # 最大不利偏移(%)
        self.mfe: float = 0.0  # 最大有利偏移(%)
        self._open_decision = None
        self._decision_sink = None

        # 特征:继承关联 bsp 的特征,策略可继续 add_feat
        self.features = CFeatures(None)
        if bsp is not None:
            for k, v in bsp.features.items():
                self.features.add_feat(k, v)

    def type2str(self) -> str:
        return self.bs_type

    @property
    def open_decision(self):
        return self._open_decision

    def freeze_open_decision(self, code, level, decision_klu, *, dedupe=None, sink=None):
        bar = bar_snapshot(decision_klu)
        identity = decision_identity("open", code, level, bar["time_ms"], self.is_buy, self.bs_type,
                                     is_segbsp=self.is_segbsp, anchor_ms=int(self.klu.time.ts * 1000), market=bar.get("market"))
        target = None if self.target_klc is None else {
            "first_ms": int(self.target_klc[0].time.ts * 1000),
            "last_ms": int(self.target_klc[-1].time.ts * 1000),
            "high": self.target_klc.high, "low": self.target_klc.low}
        if target is not None and target["last_ms"] > bar["time_ms"]:
            raise CChanException("目标结构超出开仓决策时刻", ErrCode.FEATURE_ERROR)
        origin = None
        if self.bsp is not None:
            line = self.bsp.bi
            origin = {"anchor_ms": int(self.bsp.klu.time.ts * 1000),
                      "types": [t.value for t in self.bsp.type], "is_buy": self.bsp.is_buy,
                      "is_segbsp": self.bsp.is_segbsp,
                      "line": {"idx": line.idx, "is_sure": line.is_sure,
                               "used_to_be_sure": line.used_to_be_sure, "direction": line.dir.name,
                               "begin_ms": int(line.get_begin_klu().time.ts * 1000),
                               "end_ms": int(line.get_end_klu().time.ts * 1000),
                               "begin_price": line.get_begin_val(), "end_price": line.get_end_val()}}
            if max(origin["anchor_ms"], origin["line"]["end_ms"]) > bar["time_ms"]:
                raise CChanException("来源笔/段结构超出开仓决策时刻", ErrCode.FEATURE_ERROR)
        raw = make_decision(identity, {"bar": bar, "features": dict(self.features.items()), "score": self.score,
                                       "open_price": self.open_price, "sl_price": self.sl_price,
                                       "target_price": self.target_price, "target": target, "origin": origin,
                                       "dedupe": dedupe or {}})
        if self._open_decision is not None:
            if raw != self._open_decision:
                raise CChanException("开仓身份已发布，不能改写 payload", ErrCode.FEATURE_ERROR)
            return self._open_decision
        opening = read_decision(raw)
        exits = [ca.make_decision(opening, n) for n, ca in enumerate(self.close_actions)]
        self._open_decision, self._decision_sink = raw, sink
        if sink is not None:
            sink(raw)
        for ca, exit_raw in zip(self.close_actions, exits):
            ca._decision = exit_raw
            if sink is not None:
                sink(exit_raw)
        return raw

    def do_close(self, price: float, close_klu: CKLine_Unit, reason: str, quota: Optional[float] = None):
        # 平仓;quota=None 表示全平
        if self.is_cover:
            raise CChanException(f"cbsp@{self.klu.time} 已平仓,不能重复平仓", ErrCode.RECORD_CLOSED)
        action = CCloseAction(price, close_klu, reason, quota)
        if self._open_decision is not None:
            action._decision = action.make_decision(read_decision(self._open_decision), len(self.close_actions))
            if self._decision_sink is not None:
                self._decision_sink(action._decision)
        self.close_actions.append(action)
        if quota is None:
            self.is_cover = True

    @property
    def cover_price(self) -> Optional[float]:
        return self.close_actions[-1].price if self.close_actions else None

    @property
    def profit(self) -> Optional[float]:
        # 收益率(%):按分批平仓数量加权;未平仓返回 None
        if not self.close_actions:
            return None
        return self.profit_with_final(self.close_actions[-1].price)

    def profit_with_final(self, final_price: float) -> float:
        """加权收益率(%):按 close_actions 的 quota(仓位比例,None=剩余全部)加权,
        未平部分按 final_price 结算——分批止盈后评估口径必须用它"""
        remaining = 1.0
        total = 0.0
        for ca in self.close_actions:
            if remaining <= 0:
                break
            q = remaining if ca.quota is None else min(ca.quota, remaining)
            total += q * self.profit_at(ca.price)
            remaining -= q
        if remaining > 0:
            total += remaining * self.profit_at(final_price)
        return total

    def profit_at(self, price: float) -> float:
        # 以给定价格计算浮动收益率(%)
        rate = (price - self.open_price) / self.open_price
        return rate * 100 if self.is_buy else -rate * 100

    def update_peak_price(self, klu: CKLine_Unit):
        # 更新开仓后至今最有利价格与 MAE/MFE(最大不利/有利偏移,出场参数校准用)
        if self.is_buy:
            self.peak_price = max(self.peak_price, klu.high)
            self.mfe = max(self.mfe, self.profit_at(klu.high))
            self.mae = min(self.mae, self.profit_at(klu.low))
        else:
            self.peak_price = min(self.peak_price, klu.low)
            self.mfe = max(self.mfe, self.profit_at(klu.low))
            self.mae = min(self.mae, self.profit_at(klu.high))

    def add_feat(self, inp1, inp2=None):
        self.features.add_feat(inp1, inp2)

    def is_win(self) -> Optional[bool]:
        p = self.profit
        return None if p is None else p > 0

    def __str__(self):
        bs = "buy" if self.is_buy else "sell"
        state = f"cover@{self.close_actions[-1].klu.time} profit={self.profit:.2f}%" if self.is_cover else "holding"
        return f"CCustomBSP {bs}({self.bs_type}) @{self.klu.time} open={self.open_price} {state}"
