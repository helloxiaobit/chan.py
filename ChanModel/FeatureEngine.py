"""特征引擎:在 cbsp 生成路径中计算 10 个特征族(目标 500+ 特征)

硬性约束:只允许使用 cbsp.klu 及其之前的数据(防未来函数)。
特征命名规范:{族}_{对象}_{指标},如 bi_pre1_macd_peak、zs_cnt_before_bsp。
所有特征名(含模式)注册到 FeatureDesc.FEATURE_REG,回测后可检查无未注册特征。
"""
import math
from typing import TYPE_CHECKING, Dict, List, Optional

from Common.CEnum import BI_DIR, BSP_TYPE, DATA_FIELD, MACD_ALGO, TRADE_INFO_LST, TREND_TYPE

from .FeatureDesc import FEATURE_REG

if TYPE_CHECKING:
    from Chan import CChan
    from CustomBuySellPoint.CustomBSP import CCustomBSP
    from KLine.KLine_List import CKLine_List

# ===== 组合参数(特征数 = 对象 × 指标 × 回看窗口)=====
BI_LOOKBACK = 16          # 最近N笔
SEG_LOOKBACK = 3          # 最近N段
SEGSEG_LOOKBACK = 2       # 最近N个线段的线段
ZS_LOOKBACK = 6           # 最近N个中枢
KLU_LAGS = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89]      # K线回看间隔
KLU_WINS = [3, 5, 8, 13, 21, 34, 55, 89, 144]       # K线滚动窗口
MACD_LOOKBACK = 15
BOLL_LOOKBACK = 3
RSI_LOOKBACK = 14
KDJ_LOOKBACK = 10
VOL_WINS = [3, 5, 10, 20, 60]                        # 量能窗口
MACD_CROSS_WINS = [20, 60]

BI_MACD_ALGOS = [MACD_ALGO.PEAK, MACD_ALGO.AREA, MACD_ALGO.FULL_AREA, MACD_ALGO.DIFF, MACD_ALGO.SLOPE, MACD_ALGO.AMP]
BSP_TYPES = [t.value for t in BSP_TYPE]  # 1/1p/2/2s/3a/3b
VOL_FIELD_NAME = {
    DATA_FIELD.FIELD_VOLUME: "volume",
    DATA_FIELD.FIELD_TURNOVER: "turnover",
    DATA_FIELD.FIELD_TURNRATE: "turnrate",
}

# ===== 特征模式注册 =====
FEATURE_REG.register_pattern(r"bi_pre\d+_\w+", "bi", "笔族:最近N笔的形态/MACD度量")
FEATURE_REG.register_pattern(r"seg_pre\d+_\w+", "seg", "线段族")
FEATURE_REG.register_pattern(r"segseg_pre\d+_\w+", "seg", "线段的线段族")
FEATURE_REG.register_pattern(r"zs_pre\d+_\w+", "zs", "中枢族:最近N个中枢")
FEATURE_REG.register(r"zs_cnt_before_bsp", "zs", "全部中枢个数")
FEATURE_REG.register(r"zs_cnt_in_seg", "zs", "当前线段内中枢个数")
FEATURE_REG.register(r"zs_multibi_cnt_in_seg", "zs", "当前线段内多笔中枢个数")
FEATURE_REG.register_pattern(r"zs_inout_\w+", "zs", "最近中枢进出笔MACD比")
FEATURE_REG.register_pattern(r"div_\w+", "divergence", "背驰族:各macd_algo背驰率")
FEATURE_REG.register_pattern(r"macd_zero_cross_cnt_win\d+", "divergence", "MACD回抽零轴计数")
FEATURE_REG.register_pattern(r"macd_dif_above0_ratio_win\d+", "divergence", "DIF在零轴上方比例")
FEATURE_REG.register_pattern(r"bsp_type_\w+", "bsp", "买卖点类型onehot")
FEATURE_REG.register(r"bsp_is_segbsp", "bsp", "是否线段买卖点")
FEATURE_REG.register(r"bsp_is_buy", "bsp", "是否买点")
FEATURE_REG.register(r"bsp_relate1_dist_klu", "bsp", "与相关1类买卖点距离(K线数)")
FEATURE_REG.register(r"bsp_relate1_rate", "bsp", "与相关1类买卖点价格差比例")
FEATURE_REG.register_pattern(r"klu_\w+", "klu", "K线族:形态/滚动窗口/回看")
FEATURE_REG.register_pattern(r"ind_macd_\w+", "indicator", "MACD指标族")
FEATURE_REG.register_pattern(r"ind_boll_\w+", "indicator", "BOLL指标族")
FEATURE_REG.register_pattern(r"ind_rsi_lb\d+", "indicator", "RSI指标族")
FEATURE_REG.register_pattern(r"ind_kdj_\w+", "indicator", "KDJ指标族")
FEATURE_REG.register_pattern(r"ind_demark_\w+", "indicator", "Demark指标族")
FEATURE_REG.register_pattern(r"ind_mean_T\d+_\w+", "indicator", "均线偏离族")
FEATURE_REG.register_pattern(r"ind_trend_T\d+_\w+", "indicator", "通道上下轨距离族")
FEATURE_REG.register_pattern(r"vol_\w+", "volume", "量能族")
FEATURE_REG.register_pattern(r"sub_lv_\w+", "multi_lv", "次级别族")
FEATURE_REG.register_pattern(r"sup_lv_\w+", "multi_lv", "父级别族")
FEATURE_REG.register_pattern(r"time_\w+", "time", "时间族")
FEATURE_REG.register_pattern(r"smc_\w+", "smc", "SMC族:FVG/订单块/流动性/PD位置")


def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _valid(v) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return True
    return isinstance(v, (int, float)) and math.isfinite(v)


class CFeatureEngine:
    """所有方法均为静态计算:cbsp 创建时调用一次,只读取当下及历史状态"""

    @classmethod
    def cal_features(cls, chan: 'CChan', lv: int, cbsp: 'CCustomBSP') -> Dict[str, float]:
        lv_data = chan[lv]
        klu = cbsp.klu
        recent_klus = cls._recent_klus(lv_data, max(max(KLU_WINS), max(KLU_LAGS) + 1, 200))
        feat: Dict[str, Optional[float]] = {}
        feat.update(cls.cal_bi_family(lv_data))
        feat.update(cls.cal_seg_family(lv_data, klu))
        feat.update(cls.cal_zs_family(lv_data, klu))
        feat.update(cls.cal_divergence_family(lv_data, recent_klus))
        feat.update(cls.cal_bsp_family(cbsp))
        feat.update(cls.cal_klu_family(recent_klus))
        feat.update(cls.cal_indicator_family(chan, recent_klus))
        feat.update(cls.cal_volume_family(recent_klus))
        feat.update(cls.cal_multi_lv_family(chan, lv, cbsp))
        feat.update(cls.cal_time_family(lv_data, cbsp))
        feat.update(cls.cal_smc_family(lv_data, recent_klus, cbsp))
        return {k: float(v) for k, v in feat.items() if _valid(v)}

    @staticmethod
    def _recent_klus(lv_data: 'CKLine_List', cnt: int) -> List:
        # 从最新往回取 cnt 根K线,res[0] 为当前K线
        res: List = []
        for klc in lv_data[::-1]:
            for klu in klc[::-1]:
                res.append(klu)
                if len(res) >= cnt:
                    return res
        return res

    # ===== 1. 笔族 =====
    @classmethod
    def cal_bi_family(cls, lv_data) -> dict:
        feat = {}
        bi_lst = lv_data.bi_list
        for i in range(BI_LOOKBACK):
            if i >= len(bi_lst):
                break
            bi = bi_lst[len(bi_lst) - 1 - i]
            pfx = f"bi_pre{i}"
            begin_val, end_val = bi.get_begin_val(), bi.get_end_val()
            feat[f"{pfx}_amp_rate"] = _safe_div(end_val - begin_val, begin_val)
            feat[f"{pfx}_amp"] = bi.amp()
            feat[f"{pfx}_klu_cnt"] = bi.get_klu_cnt()
            feat[f"{pfx}_klc_cnt"] = bi.get_klc_cnt()
            feat[f"{pfx}_slope"] = _safe_div(_safe_div(end_val - begin_val, begin_val), bi.get_klu_cnt())
            feat[f"{pfx}_is_up"] = bi.is_up()
            for algo in BI_MACD_ALGOS:
                try:
                    feat[f"{pfx}_macd_{algo.name.lower()}"] = bi.cal_macd_metric(algo, is_reverse=False)
                except Exception:
                    pass
        return feat

    # ===== 2. 线段族 =====
    @classmethod
    def cal_seg_family(cls, lv_data, klu) -> dict:
        feat = {}
        for prefix, seg_lst, lookback in (
            ("seg", lv_data.seg_list, SEG_LOOKBACK),
            ("segseg", lv_data.segseg_list, SEGSEG_LOOKBACK),
        ):
            for i in range(lookback):
                if i >= len(seg_lst):
                    break
                seg = seg_lst[len(seg_lst) - 1 - i]
                pfx = f"{prefix}_pre{i}"
                begin_val = seg.start_bi.get_begin_val()
                end_val = seg.end_bi.get_end_val()
                kl_cnt = seg.end_bi.get_end_klu().idx - seg.start_bi.get_begin_klu().idx + 1
                feat[f"{pfx}_is_up"] = seg.dir == BI_DIR.UP
                feat[f"{pfx}_bi_cnt"] = seg.end_bi.idx - seg.start_bi.idx + 1
                feat[f"{pfx}_amp_rate"] = _safe_div(end_val - begin_val, begin_val)
                feat[f"{pfx}_slope"] = _safe_div(_safe_div(end_val - begin_val, begin_val), kl_cnt)
                feat[f"{pfx}_is_sure"] = seg.is_sure
                feat[f"{pfx}_kl_cnt"] = kl_cnt
                feat[f"{pfx}_zs_cnt"] = len(seg.zs_lst)
                feat[f"{pfx}_pos_ratio"] = _safe_div(klu.idx - seg.start_bi.get_begin_klu().idx, kl_cnt)
        return feat

    # ===== 3. 中枢族 =====
    @classmethod
    def cal_zs_family(cls, lv_data, klu) -> dict:
        feat = {}
        zs_lst = lv_data.zs_list
        close = klu.close
        for i in range(ZS_LOOKBACK):
            if i >= len(zs_lst):
                break
            zs = zs_lst[len(zs_lst) - 1 - i]
            pfx = f"zs_pre{i}"
            feat[f"{pfx}_high_rate"] = _safe_div(zs.high - close, close)
            feat[f"{pfx}_low_rate"] = _safe_div(zs.low - close, close)
            feat[f"{pfx}_width_rate"] = _safe_div(zs.high - zs.low, zs.low)
            feat[f"{pfx}_bi_cnt"] = zs.end_bi.idx - zs.begin_bi.idx + 1
            feat[f"{pfx}_dist_rate"] = _safe_div(close - (zs.high + zs.low) / 2, close)
            feat[f"{pfx}_peak_width_rate"] = _safe_div(zs.peak_high - zs.peak_low, zs.low)
            feat[f"{pfx}_is_sure"] = zs.is_sure
        feat["zs_cnt_before_bsp"] = len(zs_lst)
        if len(lv_data.seg_list) > 0:
            cur_seg = lv_data.seg_list[-1]
            feat["zs_cnt_in_seg"] = len(cur_seg.zs_lst)
            feat["zs_multibi_cnt_in_seg"] = sum(1 for zs in cur_seg.zs_lst if not zs.is_one_bi_zs())
        # 最近一个中枢的进出笔 MACD 比(背驰率本值)
        if len(zs_lst) > 0:
            zs = zs_lst[-1]
            bi_in, bi_out = zs.bi_in, zs.bi_out
            if bi_in is not None and bi_out is not None:
                for algo in BI_MACD_ALGOS:
                    try:
                        feat[f"zs_inout_{algo.name.lower()}"] = _safe_div(
                            bi_out.cal_macd_metric(algo, is_reverse=False),
                            bi_in.cal_macd_metric(algo, is_reverse=False),
                        )
                    except Exception:
                        pass
        return feat

    # ===== 4. 背驰族 =====
    @classmethod
    def cal_divergence_family(cls, lv_data, recent_klus) -> dict:
        feat = {}
        seg_lst = lv_data.seg_list
        if len(seg_lst) > 0 and len(seg_lst[-1].zs_lst) > 0:
            zs = seg_lst[-1].zs_lst[-1]
            bi_in, bi_out = zs.bi_in, zs.bi_out
            if bi_in is not None and bi_out is not None:
                for algo in BI_MACD_ALGOS:
                    try:
                        rate = _safe_div(
                            bi_out.cal_macd_metric(algo, is_reverse=False),
                            bi_in.cal_macd_metric(algo, is_reverse=False),
                        )
                        feat[f"div_{algo.name.lower()}_rate"] = rate
                        if rate is not None and rate > 0:
                            feat[f"div_{algo.name.lower()}_log"] = math.log(rate)
                    except Exception:
                        pass
        # MACD 回抽零轴计数 / DIF 零轴上方比例
        for win in MACD_CROSS_WINS:
            if len(recent_klus) < 2:
                break
            klus = recent_klus[:win]
            cross = sum(
                1 for a, b in zip(klus[1:], klus[:-1])
                if a.macd is not None and b.macd is not None and a.macd.macd * b.macd.macd < 0
            )
            feat[f"macd_zero_cross_cnt_win{win}"] = cross
            above = [1 for k in klus if k.macd is not None and k.macd.DIF > 0]
            feat[f"macd_dif_above0_ratio_win{win}"] = len(above) / len(klus)
        return feat

    # ===== 5. 买卖点族 =====
    @classmethod
    def cal_bsp_family(cls, cbsp) -> dict:
        feat = {}
        types = {t.lstrip("q") for t in cbsp.bs_type.split(",")}
        for t in BSP_TYPES:
            feat[f"bsp_type_{t}"] = t in types
        feat["bsp_is_segbsp"] = cbsp.is_segbsp
        feat["bsp_is_buy"] = cbsp.is_buy
        if cbsp.bsp is not None and cbsp.bsp.relate_bsp1 is not None:
            relate = cbsp.bsp.relate_bsp1
            feat["bsp_relate1_dist_klu"] = cbsp.klu.idx - relate.klu.idx
            feat["bsp_relate1_rate"] = _safe_div(cbsp.klu.close - relate.klu.close, relate.klu.close)
        return feat

    # ===== 6. K线族 =====
    @classmethod
    def cal_klu_family(cls, recent_klus) -> dict:
        feat = {}
        if not recent_klus:
            return feat
        klu = recent_klus[0]
        o, h, l, c = klu.open, klu.high, klu.low, klu.close
        feat["klu_open_rate"] = _safe_div(c - o, o)
        feat["klu_upper_shadow_rate"] = _safe_div(h - max(o, c), o)
        feat["klu_lower_shadow_rate"] = _safe_div(min(o, c) - l, o)
        feat["klu_hl_rate"] = _safe_div(h - l, o)
        feat["klu_limit_flag"] = klu.limit_flag
        if klu.pre is not None:
            feat["klu_gap_rate"] = _safe_div(o - klu.pre.close, klu.pre.close)
        # 回看间隔涨跌幅
        for lag in KLU_LAGS:
            if lag < len(recent_klus):
                feat[f"klu_close_rate_lag{lag}"] = _safe_div(c - recent_klus[lag].close, recent_klus[lag].close)
        # 滚动窗口统计
        closes = [k.close for k in recent_klus]
        for win in KLU_WINS:
            if len(closes) < win:
                break
            w = closes[:win]
            w_max, w_min = max(w), min(w)
            mean = sum(w) / win
            std = math.sqrt(sum((x - mean) ** 2 for x in w) / win)
            feat[f"klu_ret_win{win}"] = _safe_div(c - w[-1], w[-1])
            feat[f"klu_amp_win{win}"] = _safe_div(w_max - w_min, w_min)
            feat[f"klu_std_rate_win{win}"] = _safe_div(std, mean)
            feat[f"klu_pos_win{win}"] = _safe_div(c - w_min, w_max - w_min)
            up_cnt = sum(1 for a, b in zip(w[:-1], w[1:]) if a > b)  # w按时间倒序,a晚于b
            feat[f"klu_up_ratio_win{win}"] = up_cnt / (win - 1)
            # 最大回撤(按时间正序遍历)
            peak, max_dd = float("-inf"), 0.0
            for x in reversed(w):
                peak = max(peak, x)
                if peak > 0:
                    max_dd = max(max_dd, (peak - x) / peak)
            feat[f"klu_max_dd_win{win}"] = max_dd
        return feat

    # ===== 7. 指标族 =====
    @classmethod
    def cal_indicator_family(cls, chan, recent_klus) -> dict:
        feat = {}
        if not recent_klus:
            return feat
        close = recent_klus[0].close
        # MACD
        for lb in range(MACD_LOOKBACK):
            if lb >= len(recent_klus):
                break
            k = recent_klus[lb]
            if k.macd is None:
                continue
            feat[f"ind_macd_dif_lb{lb}"] = _safe_div(k.macd.DIF, close)
            feat[f"ind_macd_dea_lb{lb}"] = _safe_div(k.macd.DEA, close)
            feat[f"ind_macd_bar_lb{lb}"] = _safe_div(k.macd.macd, close)
        if recent_klus[0].macd is not None:
            feat["ind_macd_dif_above0"] = recent_klus[0].macd.DIF > 0
        # BOLL
        for lb in range(BOLL_LOOKBACK):
            if lb >= len(recent_klus):
                break
            k = recent_klus[lb]
            boll = getattr(k, "boll", None)
            if boll is None:
                continue
            feat[f"ind_boll_pos_lb{lb}"] = _safe_div(k.close - boll.DOWN, boll.UP - boll.DOWN)
            feat[f"ind_boll_width_lb{lb}"] = _safe_div(boll.UP - boll.DOWN, boll.MID)
        # RSI
        for lb in range(RSI_LOOKBACK):
            if lb >= len(recent_klus):
                break
            rsi = getattr(recent_klus[lb], "rsi", None)
            if rsi is not None:
                feat[f"ind_rsi_lb{lb}"] = rsi
        # KDJ
        for lb in range(KDJ_LOOKBACK):
            if lb >= len(recent_klus):
                break
            kdj = getattr(recent_klus[lb], "kdj", None)
            if kdj is not None:
                feat[f"ind_kdj_k_lb{lb}"] = kdj.k
                feat[f"ind_kdj_d_lb{lb}"] = kdj.d
                feat[f"ind_kdj_j_lb{lb}"] = kdj.j
        # Demark
        demark = getattr(recent_klus[0], "demark", None)
        if demark is not None:
            for info in demark.get_setup():
                key = "ind_demark_buy_setup" if info["dir"] == BI_DIR.DOWN else "ind_demark_sell_setup"
                feat[key] = max(feat.get(key, 0), info["idx"])
            for info in demark.get_countdown():
                key = "ind_demark_buy_countdown" if info["dir"] == BI_DIR.DOWN else "ind_demark_sell_countdown"
                feat[key] = max(feat.get(key, 0), info["idx"])
        # 均线偏离
        for T in chan.conf.mean_metrics:
            mean_dict = recent_klus[0].trend.get(TREND_TYPE.MEAN, {})
            if T in mean_dict:
                feat[f"ind_mean_T{T}_dev"] = _safe_div(close - mean_dict[T], mean_dict[T])
                if len(recent_klus) > 1 and T in recent_klus[1].trend.get(TREND_TYPE.MEAN, {}):
                    feat[f"ind_mean_T{T}_slope"] = _safe_div(
                        mean_dict[T] - recent_klus[1].trend[TREND_TYPE.MEAN][T], mean_dict[T])
        # 通道上下轨距离
        for T in chan.conf.trend_metrics:
            trend_max = recent_klus[0].trend.get(TREND_TYPE.MAX, {})
            trend_min = recent_klus[0].trend.get(TREND_TYPE.MIN, {})
            if T in trend_max:
                feat[f"ind_trend_T{T}_up_dist"] = _safe_div(trend_max[T] - close, close)
            if T in trend_min:
                feat[f"ind_trend_T{T}_down_dist"] = _safe_div(close - trend_min[T], close)
        return feat

    # ===== 8. 量能族 =====
    @classmethod
    def cal_volume_family(cls, recent_klus) -> dict:
        feat = {}
        if not recent_klus:
            return feat
        for field, fname in VOL_FIELD_NAME.items():
            cur = recent_klus[0].trade_info.metric.get(field)
            if cur is None:
                continue
            vals = [k.trade_info.metric.get(field) for k in recent_klus]
            vals = [v for v in vals if v is not None]
            for win in VOL_WINS:
                if len(vals) < win:
                    break
                w = vals[:win]
                mean = sum(w) / win
                std = math.sqrt(sum((x - mean) ** 2 for x in w) / win)
                feat[f"vol_{fname}_mean_rate_win{win}"] = _safe_div(cur, mean)
                feat[f"vol_{fname}_std_rate_win{win}"] = _safe_div(std, mean)
            if len(vals) > 1:
                feat[f"vol_{fname}_pre_rate"] = _safe_div(cur, vals[1])
            od_score = getattr(recent_klus[0], "od_scores", {}).get(field)
            if od_score is not None:
                feat[f"vol_{fname}_od_score"] = od_score
        return feat

    # ===== 9. 多级别族 =====
    @classmethod
    def cal_multi_lv_family(cls, chan, lv, cbsp) -> dict:
        feat = {}
        # 次级别
        if lv + 1 < len(chan.lv_list):
            sub_data = chan[lv + 1]
            sub_bsp_lst = sub_data.bs_point_lst.getLastestBspList()
            if sub_bsp_lst:
                sub_bsp = sub_bsp_lst[0]
                sub_types = {t.value for t in sub_bsp.type}
                for t in BSP_TYPES:
                    feat[f"sub_lv_bsp_type_{t}"] = t in sub_types
                feat["sub_lv_bsp_is_buy"] = sub_bsp.is_buy
                feat["sub_lv_bsp_dist_klu"] = len(sub_data.bi_list)
            feat["sub_lv_zs_cnt"] = len(sub_data.zs_list)
            feat["sub_lv_bi_cnt"] = len(sub_data.bi_list)
            if len(sub_data.bi_list) > 0:
                feat["sub_lv_last_bi_is_up"] = sub_data.bi_list[-1].is_up()
            if len(sub_data.seg_list) > 0 and len(sub_data.seg_list[-1].zs_lst) > 0:
                zs = sub_data.seg_list[-1].zs_lst[-1]
                if zs.bi_in is not None and zs.bi_out is not None:
                    try:
                        feat["sub_lv_div_peak_rate"] = _safe_div(
                            zs.bi_out.cal_macd_metric(MACD_ALGO.PEAK, is_reverse=False),
                            zs.bi_in.cal_macd_metric(MACD_ALGO.PEAK, is_reverse=False),
                        )
                    except Exception:
                        pass
        # 父级别
        sup_kl = cbsp.klu.sup_kl
        if sup_kl is not None:
            feat["sup_lv_klu_is_up"] = sup_kl.close > sup_kl.open
            if lv > 0:
                sup_data = chan[lv - 1]
                if len(sup_data.bi_list) > 0:
                    feat["sup_lv_last_bi_is_up"] = sup_data.bi_list[-1].is_up()
                if len(sup_data.seg_list) > 0:
                    feat["sup_lv_last_seg_is_up"] = sup_data.seg_list[-1].dir == BI_DIR.UP
        return feat

    # ===== 11. SMC族(FVG/订单块/流动性/PD位置)=====
    SMC_WINDOW = 240       # 检测窗口(根)
    SMC_LOOKBACK_BI = 12   # OB 回看笔数
    SMC_POOL_BI = 16       # 流动性池回看笔数
    SMC_SWEEP_LOOKBACK = 8  # sweep 回看K线数

    @classmethod
    def cal_smc_family(cls, lv_data, recent_klus, cbsp) -> dict:
        from Math.SmartMoney import (detect_sweeps, find_fvgs, find_liquidity_pools,
                                     find_order_blocks, premium_discount_pos)
        feat = {}
        if len(recent_klus) < 5:
            return feat
        klus = recent_klus[:cls.SMC_WINDOW][::-1]  # 转为时间正序
        cur = klus[-1]
        close = cur.close

        # --- FVG:最近的未回补多/空缺口 ---
        fvgs = find_fvgs(klus)
        unfilled_bull = [f for f in fvgs if f.is_bull and not f.is_filled]
        unfilled_bear = [f for f in fvgs if not f.is_bull and not f.is_filled]
        feat["smc_fvg_bull_cnt"] = len(unfilled_bull)
        feat["smc_fvg_bear_cnt"] = len(unfilled_bear)
        for side, lst in (("bull", unfilled_bull), ("bear", unfilled_bear)):
            if not lst:
                continue
            fvg = lst[-1]  # 最新的
            feat[f"smc_fvg_{side}_dist"] = _safe_div(close - fvg.mid, close)
            feat[f"smc_fvg_{side}_size"] = _safe_div(fvg.top - fvg.bottom, close)
            feat[f"smc_fvg_{side}_age"] = cur.idx - fvg.klu_idx
            feat[f"smc_fvg_{side}_fill"] = fvg.fill_ratio
            feat[f"smc_in_fvg_{side}"] = fvg.bottom <= close <= fvg.top

        # --- 订单块:最近的未失效多/空OB ---
        obs = find_order_blocks(lv_data.bi_list, klus, lookback_bi=cls.SMC_LOOKBACK_BI)
        valid_bull = [o for o in obs if o.is_bull and not o.is_broken]
        valid_bear = [o for o in obs if not o.is_bull and not o.is_broken]
        feat["smc_ob_bull_cnt"] = len(valid_bull)
        feat["smc_ob_bear_cnt"] = len(valid_bear)
        for side, lst in (("bull", valid_bull), ("bear", valid_bear)):
            if not lst:
                continue
            ob = lst[-1]
            feat[f"smc_ob_{side}_dist"] = _safe_div(close - ob.mid, close)
            feat[f"smc_ob_{side}_size"] = _safe_div(ob.top - ob.bottom, close)
            feat[f"smc_ob_{side}_age"] = cur.idx - ob.klu_idx
            feat[f"smc_ob_{side}_test_cnt"] = ob.test_cnt
            feat[f"smc_in_ob_{side}"] = ob.bottom <= close <= ob.top

        # --- 流动性池与 sweep ---
        high_pools, low_pools = find_liquidity_pools(lv_data.bi_list, lookback_bi=cls.SMC_POOL_BI)
        above = [p for p in high_pools if p.price > close]
        below = [p for p in low_pools if p.price < close]
        if above:
            nearest = above[0]
            feat["smc_liq_above_dist"] = _safe_div(nearest.price - close, close)
            feat["smc_liq_above_cnt"] = nearest.cnt
        if below:
            nearest = below[-1]
            feat["smc_liq_below_dist"] = _safe_div(close - nearest.price, close)
            feat["smc_liq_below_cnt"] = nearest.cnt
        if high_pools:
            feat["smc_eq_high_max_cnt"] = max(p.cnt for p in high_pools)
        if low_pools:
            feat["smc_eq_low_max_cnt"] = max(p.cnt for p in low_pools)
        sweeps = detect_sweeps(klus, high_pools, low_pools, lookback=cls.SMC_SWEEP_LOOKBACK)
        bull_sweeps = [s for s in sweeps if s.is_bull]
        bear_sweeps = [s for s in sweeps if not s.is_bull]
        if bull_sweeps:
            feat["smc_sweep_bull_dist"] = cur.idx - bull_sweeps[-1].klu_idx
            feat["smc_sweep_bull_pool_cnt"] = bull_sweeps[-1].pool_cnt
        if bear_sweeps:
            feat["smc_sweep_bear_dist"] = cur.idx - bear_sweeps[-1].klu_idx
            feat["smc_sweep_bear_pool_cnt"] = bear_sweeps[-1].pool_cnt
        # 开仓分型是否为同向 sweep 分型(sweep后3根内且方向一致)
        same_side = bull_sweeps if cbsp.is_buy else bear_sweeps
        feat["smc_bsp_after_sweep"] = bool(same_side) and cur.idx - same_side[-1].klu_idx <= 3

        # --- Premium/Discount 位置 ---
        pd_pos = premium_discount_pos(lv_data, close)
        if "pos_in_zs" in pd_pos:
            feat["smc_pos_in_zs"] = pd_pos["pos_in_zs"]
        if "pos_in_seg" in pd_pos:
            feat["smc_pos_in_seg"] = pd_pos["pos_in_seg"]
        return feat

    # ===== 10. 时间族 =====
    @classmethod
    def cal_time_family(cls, lv_data, cbsp) -> dict:
        feat = {}
        klu_idx = cbsp.klu.idx
        same_dist = opp_dist = None
        for bsp in lv_data.bs_point_lst.getLastestBspList():
            if bsp.klu.idx >= klu_idx:
                continue
            if bsp.is_buy == cbsp.is_buy and same_dist is None:
                same_dist = klu_idx - bsp.klu.idx
            if bsp.is_buy != cbsp.is_buy and opp_dist is None:
                opp_dist = klu_idx - bsp.klu.idx
            if same_dist is not None and opp_dist is not None:
                break
        feat["time_dist_same_dir_bsp"] = same_dist
        feat["time_dist_opp_dir_bsp"] = opp_dist
        if len(lv_data.bi_list) > 0:
            feat["time_last_bi_klu_cnt"] = lv_data.bi_list[-1].get_klu_cnt()
        if cbsp.bsp is not None:
            feat["time_fx_dist"] = klu_idx - cbsp.bsp.klu.idx
        return feat
