"""SMC(Smart Money Concepts)检测器:FVG / 订单块 / 流动性池与sweep / Premium-Discount

设计原则:
- 全部为"当前及之前K线"的确定性纯函数,不持有跨调用状态 → 天然满足 load/trigger 一致性
- 订单块用缠论笔结构定位(笔起点前最后一根反向K线),以缠论的确定性修 SMC 定义的模糊性
- 输入 klus 一律为时间正序(旧→新)的 CKLine_Unit 列表
"""
from typing import List, Optional, Tuple


class CFVG:
    """公允价值缺口(三根K线失衡):bull 为 k[i-2].high < k[i].low 留下的未回补区间"""

    def __init__(self, klu_idx: int, is_bull: bool, top: float, bottom: float):
        self.klu_idx = klu_idx  # 中间那根K线(位移K线)的idx
        self.is_bull = is_bull
        self.top = top
        self.bottom = bottom
        self.fill_ratio = 0.0  # 0=未回补,1=完全回补

    @property
    def is_filled(self) -> bool:
        return self.fill_ratio >= 1.0

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2

    def update_fill(self, klu) -> None:
        # bull 缺口被后续K线向下侵入回补;bear 反之
        height = self.top - self.bottom
        if height <= 0:
            self.fill_ratio = 1.0
            return
        if self.is_bull:
            penetrate = self.top - klu.low
        else:
            penetrate = klu.high - self.bottom
        if penetrate > 0:
            self.fill_ratio = max(self.fill_ratio, min(1.0, penetrate / height))


def find_fvgs(klus: List, min_size_rate: float = 0.0) -> List[CFVG]:
    """扫描全部三K组合,返回按时间正序的 FVG 列表(含回补状态)"""
    fvgs: List[CFVG] = []
    for i in range(2, len(klus)):
        k0, k2 = klus[i - 2], klus[i]
        mid_klu = klus[i - 1]
        if k2.low > k0.high:  # bullish 失衡
            fvg = CFVG(mid_klu.idx, True, k2.low, k0.high)
        elif k2.high < k0.low:  # bearish 失衡
            fvg = CFVG(mid_klu.idx, False, k0.low, k2.high)
        else:
            continue
        if min_size_rate > 0 and (fvg.top - fvg.bottom) / mid_klu.close < min_size_rate:
            continue
        fvgs.append(fvg)
    # 回补状态:每个 FVG 只被其之后的K线回补
    j = 0
    for fvg in fvgs:
        while j < len(klus) and klus[j].idx <= fvg.klu_idx + 1:
            j += 1
        for klu in klus[j:]:
            fvg.update_fill(klu)
            if fvg.is_filled:
                break
    return fvgs


class COrderBlock:
    """订单块:笔起点前最后一根反向K线(机构建仓区)"""

    def __init__(self, bi_idx: int, is_bull: bool, top: float, bottom: float, klu_idx: int):
        self.bi_idx = bi_idx      # 由哪笔定位(向上笔→bull OB)
        self.is_bull = is_bull
        self.top = top
        self.bottom = bottom
        self.klu_idx = klu_idx    # OB K线 idx
        self.test_cnt = 0         # 后续价格回踩进入区间次数
        self.is_broken = False    # 收盘价穿越区间另一侧 → 失效

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2


def find_order_blocks(bi_list, klus: List, lookback_bi: int = 12) -> List[COrderBlock]:
    """对最近 lookback_bi 笔,每笔定位一个 OB;klus 为覆盖这些笔的正序K线窗口"""
    if len(klus) == 0:
        return []
    idx2pos = {klu.idx: pos for pos, klu in enumerate(klus)}
    obs: List[COrderBlock] = []
    for bi in bi_list[-lookback_bi:]:
        begin_klu = bi.get_begin_klu()
        if begin_klu.idx not in idx2pos:
            continue  # 窗口外
        pos = idx2pos[begin_klu.idx]
        ob_klu = None
        for p in range(pos, -1, -1):  # 从笔起点向前找最后一根反向K线
            k = klus[p]
            if bi.is_up() and k.close < k.open:
                ob_klu = k
                break
            if bi.is_down() and k.close > k.open:
                ob_klu = k
                break
        if ob_klu is None:
            continue
        ob = COrderBlock(bi.idx, bi.is_up(), ob_klu.high, ob_klu.low, ob_klu.idx)
        # 回踩测试与失效:OB K线之后;初始为 in_zone,价格首次离开区间后再返回才算一次测试
        in_zone = True
        for k in klus[idx2pos[ob_klu.idx] + 1:]:
            if ob.is_bull:
                if k.close < ob.bottom:
                    ob.is_broken = True
                    break
                touching = k.low <= ob.top
            else:
                if k.close > ob.top:
                    ob.is_broken = True
                    break
                touching = k.high >= ob.bottom
            if touching and not in_zone:
                ob.test_cnt += 1
            in_zone = touching
        obs.append(ob)
    return obs


class CLiquidityPool:
    """流动性池:笔端点极值;等高/等低分型在容差内聚成簇,簇越大流动性越厚"""

    def __init__(self, price: float, klu_idx: int, is_high: bool):
        self.price = price      # 簇内极值(高点簇取最高,低点簇取最低)
        self.klu_idx = klu_idx  # 簇内最新端点的K线idx
        self.is_high = is_high
        self.cnt = 1            # 簇内端点数(等高/等低次数)


def find_liquidity_pools(bi_list, lookback_bi: int = 16, tol: float = 0.002) -> Tuple[List[CLiquidityPool], List[CLiquidityPool]]:
    """返回 (高点池列表, 低点池列表),各按价格排序;tol 为等高/等低相对容差"""
    highs: List[CLiquidityPool] = []
    lows: List[CLiquidityPool] = []
    for bi in bi_list[-lookback_bi:]:
        end_klu = bi.get_end_klu()
        price = bi.get_end_val()
        pools = highs if bi.is_up() else lows
        merged = False
        for pool in pools:
            if abs(price - pool.price) <= tol * pool.price:
                pool.cnt += 1
                pool.klu_idx = max(pool.klu_idx, end_klu.idx)
                if (pool.is_high and price > pool.price) or (not pool.is_high and price < pool.price):
                    pool.price = price
                merged = True
                break
        if not merged:
            pools.append(CLiquidityPool(price, end_klu.idx, bi.is_up()))
    highs.sort(key=lambda p: p.price)
    lows.sort(key=lambda p: p.price)
    return highs, lows


class CSweep:
    def __init__(self, is_bull: bool, pool_price: float, klu_idx: int, pool_cnt: int):
        self.is_bull = is_bull      # True=下方低点池被扫后收回(看多信号)
        self.pool_price = pool_price
        self.klu_idx = klu_idx      # 发生 sweep 的K线idx
        self.pool_cnt = pool_cnt


def detect_sweeps(klus: List, high_pools: List[CLiquidityPool], low_pools: List[CLiquidityPool],
                  lookback: int = 8) -> List[CSweep]:
    """检测最近 lookback 根K线内的流动性扫荡:影线穿过池但收盘收回;返回时间正序"""
    sweeps: List[CSweep] = []
    for klu in klus[-lookback:]:
        for pool in low_pools:
            if pool.klu_idx >= klu.idx:  # 池必须先于该K线形成
                continue
            if klu.low < pool.price and klu.close > pool.price:
                sweeps.append(CSweep(True, pool.price, klu.idx, pool.cnt))
                break
        for pool in high_pools:
            if pool.klu_idx >= klu.idx:
                continue
            if klu.high > pool.price and klu.close < pool.price:
                sweeps.append(CSweep(False, pool.price, klu.idx, pool.cnt))
                break
    return sweeps


def premium_discount_pos(lv_data, close: float) -> dict:
    """当前价在均衡区间中的位置:0=底部(discount),1=顶部(premium),可越界

    - pos_in_zs:最近中枢 [ZD, ZG] 口径(缠论中枢即 SMC 的均衡区间)
    - pos_in_seg:当前线段高低点口径
    """
    res = {}
    if len(lv_data.zs_list) > 0:
        zs = lv_data.zs_list[-1]
        if zs.high > zs.low:
            res["pos_in_zs"] = (close - zs.low) / (zs.high - zs.low)
    if len(lv_data.seg_list) > 0:
        seg = lv_data.seg_list[-1]
        seg_high = max(seg.start_bi.get_begin_val(), seg.end_bi.get_end_val())
        seg_low = min(seg.start_bi.get_begin_val(), seg.end_bi.get_end_val())
        if seg_high > seg_low:
            res["pos_in_seg"] = (close - seg_low) / (seg_high - seg_low)
    return res
