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

SMC 限价入场模式(entry_mode,默认 "breakout" 为原突破逻辑):
- "zone":   1H 信号确认即挂回撤限价(v1;2026回测证实存在逆向选择,不推荐,保留做对照)
- "bos_zone": 教科书顺序 v2——先突破确认(BOS),再在位移留下的回撤区挂限价
  (15M FVG中线/OB边沿/突破位回踩,取离现价最近);chase_bars 根内未成交且
  收盘仍站稳突破位则市价追入(防错过强势单);限价成交带 z 前缀,追入为原类型
- entry_valid_bars:  限价单有效期(交易级别K线数),默认 8
- entry_zone_source: 回撤区来源 both/fvg/ob,默认 both
- entry_sl_mode:     止损口径 fx(1H分型)/zone(区间下沿),默认 fx
- entry_fallback:    找不到回撤区时 skip(放弃)/breakout(退回突破逻辑),默认 skip
- chase_bars:        bos_zone 防错过追入等待根数,默认 6(None 关闭追入)

出场引擎(E1,全部默认关闭,开启后开仓即带出场蓝图):
- exit_target_mode:  "liq" 用交易级别对侧流动性池作结构化止盈目标(触及全平)
- partial_tp_r:      浮盈达 R 倍初始风险时平一半并把止损移到保本,如 1.0
- trail_after_r:     浮盈达 R 倍后启动入场级别笔端点结构追踪止损,如 1.5
- time_stop_bars:    持仓 N 根交易级别K线仍未盈利则离场,如 12
- min_target_r:      目标距离不足 R 倍初始风险的信号直接放弃(质量地板),如 1.0
(2026回测教训:趋势剧本下利润集中在少数大赢家尾部,最近池止盈/保本会截断尾部,
 默认保持关闭;结构化止盈只应用于震荡剧本)

止损执行(迭代6,R系列数据驱动:收盘判断止损导致40%交易亏损>1R,肥左尾摧毁复利Calmar):
- sl_intrabar: True 时止损盘中触价即出,成交价=止损价±滑点(入场仍按收盘确认,互不影响)
- sl_slippage: 盘中止损滑点比例,默认 0.0005(万5)

Regime 状态机(迭代5):
- 判定:4H最近中枢仍新鲜(距今≤regime_zs_valid_bars根)且现价在[ZD,ZG]内 → "range",否则 "trend"
- 每笔交易开仓时打戳 exit_state["regime"](当下判定,无后见偏差),供分状态切片分析
- regime_mode: None(仅打戳)/"silent"(range期不开新仓,在途限价单照常管理)
- regime_zs_valid_bars: 中枢新鲜度窗口,默认 30
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
        self.opened_bsp_klu_idx = set()  # 交易级别:已开仓/已挂单过的 bsp(按klu.idx)
        self.marked_bsp_klu_idx = set()  # 入场级别:已标记过的 1类 bsp
        self.pending_entries = []        # zone 模式在途限价单

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

    def cal_regime(self, chan: 'CChan') -> str:
        """4H 状态:最近中枢仍新鲜且现价在其[ZD,ZG]内 → range(震荡),否则 trend"""
        if len(chan.lv_list) < 2:
            return "trend"
        trend_data = chan[0]
        if len(trend_data) == 0 or len(trend_data.zs_list) == 0:
            return "trend"
        zs = trend_data.zs_list[-1]
        cur = trend_data[-1][-1]
        fresh = cur.idx - zs.end.idx <= self.get_p("regime_zs_valid_bars", 30)
        if fresh and zs.low <= cur.close <= zs.high:
            return "range"
        return "trend"

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
        # zone/bos_zone 模式:先处理在途限价单(成交/追入/撤销),成交则本根直接返回
        if self.get_p("entry_mode", "breakout") in ("zone", "bos_zone"):
            if filled := self.process_pending_entries(chan, lv, direction):
                return self.attach_exit_plan(chan, lv, filled)
        if lv > 0 and direction == 0:
            return None
        # 1.5) Regime 门控:silent 模式下震荡期不开新仓
        if self.get_p("regime_mode") == "silent" and self.cal_regime(chan) == "range":
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
        cur_klu = data[-1][-1]
        # zone v1 模式:不做突破确认直接挂回撤限价(对照组,已证实存在逆向选择)
        if self.get_p("entry_mode", "breakout") == "zone":
            armed = self.arm_pending_entry(chan, lv, last_bsp, is_buy, fx_klc, cur_klu)
            if armed or self.get_p("entry_fallback", "skip") == "skip":
                return None
            # entry_fallback=breakout 且找不到回撤区 → 退回突破逻辑
        # 4) 突破判断(与 CCustomStrategy 同口径)
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
        # bos_zone v2:突破已确认(BOS),不市价追,在位移回撤区挂限价 + chase 防错过
        if self.get_p("entry_mode", "breakout") == "bos_zone":
            if self.arm_bos_pending(chan, lv, last_bsp, is_buy, fx_klc, cur_klu, sl_price):
                return None
            # 找不到回撤区:按 entry_fallback 决定放弃还是直接开(突破条件本就已满足)
            if self.get_p("entry_fallback", "skip") == "skip":
                self.opened_bsp_klu_idx.add(last_bsp.klu.idx)
                return None
        self.opened_bsp_klu_idx.add(last_bsp.klu.idx)
        cbsp = CCustomBSP(
            bsp=last_bsp,
            klu=cur_klu,
            bs_type=last_bsp.qjt_type() if sub_ref is not None else last_bsp.type2str(),
            is_buy=is_buy,
            target_klc=fx_klc,
            price=open_price,
            sl_price=sl_price,
        )
        return self.attach_exit_plan(chan, lv, cbsp)

    # ---- SMC 限价入场(entry_mode="zone")----
    @staticmethod
    def _recent_entry_klus(entry_data: 'CKLine_List', cnt: int = 240) -> List:
        res: List = []
        for klc in entry_data[::-1]:
            for klu in klc[::-1]:
                res.append(klu)
                if len(res) >= cnt:
                    return res[::-1]
        return res[::-1]

    def find_entry_zone(self, chan: 'CChan', lv: int, is_buy: bool, close: float):
        """从入场级别找回撤区:(挂单价, 区间下沿, 区间上沿, 来源) 或 None;取离现价最近者"""
        if lv + 1 >= len(chan.lv_list):
            return None
        from Math.SmartMoney import find_fvgs, find_order_blocks
        entry_data = chan[lv + 1]
        klus = self._recent_entry_klus(entry_data)
        if len(klus) < 5:
            return None
        source = self.get_p("entry_zone_source", "both")
        candidates = []
        if source in ("both", "fvg"):
            for fvg in find_fvgs(klus)[::-1]:  # 最新优先
                if fvg.is_bull != is_buy or fvg.is_filled:
                    continue
                if (is_buy and fvg.mid < close) or (not is_buy and fvg.mid > close):
                    candidates.append((fvg.mid, fvg.bottom, fvg.top, "fvg"))
                    break
        if source in ("both", "ob"):
            for ob in find_order_blocks(entry_data.bi_list, klus)[::-1]:
                if ob.is_bull != is_buy or ob.is_broken:
                    continue
                edge = ob.top if is_buy else ob.bottom  # 买:回落到OB上沿即接;卖反之
                if (is_buy and edge < close) or (not is_buy and edge > close):
                    candidates.append((edge, ob.bottom, ob.top, "ob"))
                    break
        if not candidates:
            return None
        return max(candidates) if is_buy else min(candidates)

    def arm_pending_entry(self, chan: 'CChan', lv: int, trade_bsp, is_buy: bool, fx_klc, cur_klu) -> bool:
        zone = self.find_entry_zone(chan, lv, is_buy, cur_klu.close)
        if zone is None:
            return False
        entry_price, zone_bottom, zone_top, source = zone
        if self.get_p("entry_sl_mode", "fx") == "zone":
            sl = zone_bottom if is_buy else zone_top
        else:
            sl = fx_klc.low if is_buy else fx_klc.high
        sl = self.truncate_sl(entry_price, sl, is_buy)
        # 挂单价必须优于现价且在止损位的正确一侧
        if is_buy and (entry_price >= cur_klu.close or entry_price <= sl):
            return False
        if not is_buy and (entry_price <= cur_klu.close or entry_price >= sl):
            return False
        self.opened_bsp_klu_idx.add(trade_bsp.klu.idx)
        self.pending_entries.append({
            "bsp": trade_bsp, "is_buy": is_buy, "price": entry_price, "sl": sl,
            "expire_idx": cur_klu.idx + self.get_p("entry_valid_bars", 8),
            "fx_klc": fx_klc, "source": source,
        })
        return True

    def arm_bos_pending(self, chan: 'CChan', lv: int, trade_bsp, is_buy: bool,
                        fx_klc, cur_klu, sl_price: float) -> bool:
        """bos_zone:突破确认后挂回撤限价;候选区含突破位回踩(fx极值)与15M FVG/OB"""
        trigger = fx_klc.high if is_buy else fx_klc.low  # 突破位
        candidates = [(trigger, fx_klc.low, fx_klc.high, "retest")]
        if zone := self.find_entry_zone(chan, lv, is_buy, cur_klu.close):
            candidates.append(zone[:4])
        best = None
        for entry_price, zb, zt, src in candidates:
            if is_buy and (entry_price >= cur_klu.close or entry_price <= sl_price):
                continue
            if not is_buy and (entry_price <= cur_klu.close or entry_price >= sl_price):
                continue
            if best is None or (is_buy and entry_price > best[0]) or (not is_buy and entry_price < best[0]):
                best = (entry_price, zb, zt, src)
        if best is None:
            return False
        self.opened_bsp_klu_idx.add(trade_bsp.klu.idx)
        self.pending_entries.append({
            "bsp": trade_bsp, "is_buy": is_buy, "price": best[0], "sl": sl_price,
            "expire_idx": cur_klu.idx + self.get_p("entry_valid_bars", 8),
            "fx_klc": fx_klc, "source": best[3],
            "trigger": trigger, "armed_idx": cur_klu.idx,  # chase 用
        })
        return True

    def process_pending_entries(self, chan: 'CChan', lv: int, direction: int) -> Optional[CCustomBSP]:
        """限价单撮合与撤销:触价成交(每根至多一单,z前缀);
        bos_zone 的 chase:等待 chase_bars 根未成交且收盘仍站稳突破位 → 市价追入(原类型);
        过期/趋势翻转/收盘破止损撤单"""
        if not self.pending_entries:
            return None
        cur = chan[lv][-1][-1]
        chase_bars = self.get_p("chase_bars", 6)
        fill: Optional[CCustomBSP] = None
        remain = []
        for p in self.pending_entries:
            touched = (cur.low <= p["price"]) if p["is_buy"] else (cur.high >= p["price"])
            chase = False
            if not touched and fill is None and chase_bars is not None and "trigger" in p:
                waited = cur.idx - p["armed_idx"]
                still_valid = (cur.close > p["trigger"]) if p["is_buy"] else (cur.close < p["trigger"])
                chase = waited >= chase_bars and still_valid
            if fill is None and (touched or chase):
                cbsp = CCustomBSP(
                    bsp=p["bsp"],
                    klu=cur,
                    bs_type=",".join(f"z{t}" for t in p["bsp"].type2str().split(","))
                    if touched else p["bsp"].type2str(),
                    is_buy=p["is_buy"],
                    target_klc=p["fx_klc"],
                    price=p["price"] if touched else cur.close,
                    sl_price=p["sl"],
                )
                # 成交当根收盘已破止损 → 立即止损离场(不留隔根乐观)
                if (p["is_buy"] and cur.close < p["sl"]) or (not p["is_buy"] and cur.close > p["sl"]):
                    cbsp.do_close(cur.close, cur, reason="stop_loss")
                fill = cbsp
                continue
            expired = cur.idx >= p["expire_idx"]
            flipped = direction != 0 and (direction > 0) != p["is_buy"]
            sl_broken = (cur.close < p["sl"]) if p["is_buy"] else (cur.close > p["sl"])
            if not (expired or flipped or sl_broken):
                remain.append(p)
        self.pending_entries = remain
        return fill

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

    # ---- 出场引擎(E1,默认全关)----
    def attach_exit_plan(self, chan: 'CChan', lv: int, cbsp: Optional[CCustomBSP]) -> Optional[CCustomBSP]:
        """开仓即带出场蓝图:结构化目标(对侧流动性池)+ 初始风险记录;
        min_target_r 质量地板:目标距离不足 R 倍初始风险直接放弃该交易"""
        if cbsp is None or cbsp.sl_price is None:
            return cbsp
        risk = abs(cbsp.open_price - cbsp.sl_price)
        cbsp.exit_state = {"risk": risk, "partial_done": False, "trailing": False,
                           "regime": self.cal_regime(chan)}  # 开仓时打戳,无后见偏差
        if self.get_p("exit_target_mode") == "liq" and risk > 0:
            from Math.SmartMoney import find_liquidity_pools
            highs, lows = find_liquidity_pools(chan[lv].bi_list, lookback_bi=16)
            if cbsp.is_buy:
                above = [p.price for p in highs if p.price > cbsp.open_price]
                cbsp.target_price = min(above) if above else None
            else:
                below = [p.price for p in lows if p.price < cbsp.open_price]
                cbsp.target_price = max(below) if below else None
            min_target_r = self.get_p("min_target_r")
            if min_target_r is not None and cbsp.target_price is not None \
               and abs(cbsp.target_price - cbsp.open_price) < min_target_r * risk:
                return None  # 盈亏空间不够,放弃
        return cbsp

    def entry_lv_trail_price(self, chan: 'CChan', lv: int, is_buy: bool) -> Optional[float]:
        # 入场级别最近一笔反向笔端点(多头取最近下笔低点)作为结构追踪位
        if lv + 1 >= len(chan.lv_list):
            return None
        for bi in chan[lv + 1].bi_list[::-1]:
            if is_buy and bi.is_down():
                return bi.get_end_val()
            if not is_buy and bi.is_up():
                return bi.get_end_val()
        return None

    def manage_exits(self, chan: 'CChan', lv: int, cur_klu) -> None:
        """结构化止盈/分批/保本/追踪/时间止损(在常规止损与反向信号检查之前执行)"""
        partial_tp_r = self.get_p("partial_tp_r")
        trail_after_r = self.get_p("trail_after_r")
        time_stop_bars = self.get_p("time_stop_bars")
        use_target = self.get_p("exit_target_mode") == "liq"
        if partial_tp_r is None and trail_after_r is None and time_stop_bars is None and not use_target:
            return
        for cbsp in self.holding_cbsp():
            if cbsp.klu.idx >= cur_klu.idx or not cbsp.exit_state:
                continue
            risk = cbsp.exit_state.get("risk", 0)
            close = cur_klu.close
            gain = (close - cbsp.open_price) if cbsp.is_buy else (cbsp.open_price - close)
            # 1) 结构化目标:触及全平
            if use_target and cbsp.target_price is not None:
                hit = close >= cbsp.target_price if cbsp.is_buy else close <= cbsp.target_price
                if hit:
                    cbsp.do_close(close, cur_klu, reason="take_profit")
                    continue
            if risk <= 0:
                continue
            # 2) 分批止盈 + 保本
            if partial_tp_r is not None and not cbsp.exit_state["partial_done"] and gain >= partial_tp_r * risk:
                cbsp.do_close(close, cur_klu, reason="partial_tp", quota=0.5)
                cbsp.exit_state["partial_done"] = True
                cbsp.sl_price = max(cbsp.sl_price, cbsp.open_price) if cbsp.is_buy \
                    else min(cbsp.sl_price, cbsp.open_price)  # 移到保本
            # 3) 结构追踪止损(入场级别笔端点)
            if trail_after_r is not None:
                if not cbsp.exit_state["trailing"] and gain >= trail_after_r * risk:
                    cbsp.exit_state["trailing"] = True
                if cbsp.exit_state["trailing"]:
                    trail = self.entry_lv_trail_price(chan, lv, cbsp.is_buy)
                    if trail is not None:
                        cbsp.sl_price = max(cbsp.sl_price, trail) if cbsp.is_buy \
                            else min(cbsp.sl_price, trail)
            # 4) 时间止损:持仓 N 根仍未盈利
            if time_stop_bars is not None and cur_klu.idx - cbsp.klu.idx >= time_stop_bars and gain <= 0:
                cbsp.do_close(close, cur_klu, reason="time_stop")

    # ---- 平仓 ----
    def try_close(self, chan: 'CChan', lv: int) -> None:
        if self.get_role(chan, lv) != "trade":
            return
        data = chan[lv]
        if len(data) < 2:
            return
        cur_klu = data[-1][-1]
        self.manage_exits(chan, lv, cur_klu)
        trend_dir = self.cal_trend_direction(chan) if lv > 0 else 0
        judge_on_close = self.get_p("judge_on_close", True)
        sl_intrabar = self.get_p("sl_intrabar", False)
        slip = self.get_p("sl_slippage", 0.0005)
        for cbsp in self.holding_cbsp():
            if cbsp.klu.idx >= cur_klu.idx:
                continue
            # 1) 止损(入场级别分型收紧过的 sl_price)
            if cbsp.sl_price is not None:
                if sl_intrabar:  # 盘中触价即出:把单笔亏损钉在≈1R(+滑点),消灭肥左尾
                    if cbsp.is_buy:
                        hit = cur_klu.low < cbsp.sl_price
                        price = cbsp.sl_price * (1 - slip)
                    else:
                        hit = cur_klu.high > cbsp.sl_price
                        price = cbsp.sl_price * (1 + slip)
                elif cbsp.is_buy:
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
