"""SMC 检测器与 smc 特征族测试"""
import pytest

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_FIELD, DATA_SRC, KL_TYPE
from Common.CTime import CTime
from CustomBuySellPoint.CustomStrategy import CCustomStrategy
from KLine.KLine_Unit import CKLine_Unit
from Math.SmartMoney import (CFVG, detect_sweeps, find_fvgs, find_liquidity_pools,
                             find_order_blocks, premium_discount_pos)


class FakeKlu:
    """检测器只依赖 idx/open/high/low/close 的轻量桩"""

    def __init__(self, idx, o, h, l, c):
        self.idx = idx
        self.open, self.high, self.low, self.close = o, h, l, c


def K(idx, o, h, l, c):
    return FakeKlu(idx, o, h, l, c)


def test_fvg_detect_and_fill():
    # k0.high=10 < k2.low=12 → bullish FVG [10,12]
    klus = [K(0, 9, 10, 8, 9.5), K(1, 9.5, 13, 9.4, 12.8), K(2, 12.8, 14, 12, 13.5)]
    fvgs = find_fvgs(klus)
    assert len(fvgs) == 1
    fvg = fvgs[0]
    assert fvg.is_bull and fvg.top == 12 and fvg.bottom == 10 and fvg.fill_ratio == 0.0
    # 半回补:后续K线low=11 → (12-11)/2 = 0.5
    fvgs = find_fvgs(klus + [K(3, 13.5, 13.6, 11, 11.5)])
    assert fvgs[0].fill_ratio == pytest.approx(0.5)
    # 完全回补
    fvgs = find_fvgs(klus + [K(3, 13.5, 13.6, 9.9, 10.5)])
    assert fvgs[0].is_filled
    # bearish FVG
    klus_bear = [K(0, 13, 14, 12, 12.5), K(1, 12.5, 12.4, 9, 9.2), K(2, 9.2, 10, 8, 8.5)]
    fvgs = find_fvgs(klus_bear)
    assert len(fvgs) == 1 and not fvgs[0].is_bull
    assert fvgs[0].top == 12 and fvgs[0].bottom == 10


class FakeBi:
    def __init__(self, idx, is_up, begin_klu, end_klu, end_val):
        self.idx = idx
        self._is_up = is_up
        self._begin_klu, self._end_klu, self._end_val = begin_klu, end_klu, end_val

    def is_up(self):
        return self._is_up

    def is_down(self):
        return not self._is_up

    def get_begin_klu(self):
        return self._begin_klu

    def get_end_klu(self):
        return self._end_klu

    def get_end_val(self):
        return self._end_val


def test_order_block():
    # K线:idx0阴,idx1阴(OB),idx2起向上笔,idx5回踩,idx7收盘跌破→失效
    klus = [
        K(0, 10, 10.5, 9.5, 9.8),   # 阴
        K(1, 9.8, 10, 9.0, 9.2),    # 阴 ← 笔起点前最后一根反向K线(OB)
        K(2, 9.2, 11, 9.1, 10.8),   # 阳,笔起点
        K(3, 10.8, 12, 10.7, 11.8),
        K(4, 11.8, 12.5, 11.5, 12.2),
        K(5, 12.2, 12.3, 9.9, 10.1),  # 回踩进入OB区间[9.0,10]
    ]
    bi = FakeBi(0, True, klus[2], klus[4], 12.5)
    obs = find_order_blocks([bi], klus)
    assert len(obs) == 1
    ob = obs[0]
    assert ob.is_bull and ob.klu_idx == 1 and ob.top == 10 and ob.bottom == 9.0
    assert ob.test_cnt == 1 and not ob.is_broken
    # 收盘跌破区间下沿 → 失效
    obs = find_order_blocks([bi], klus + [K(6, 10.1, 10.2, 8.5, 8.8)])
    assert obs[0].is_broken


def test_liquidity_pools_and_sweep():
    k_hi1, k_hi2 = K(10, 0, 0, 0, 0), K(20, 0, 0, 0, 0)
    k_lo = K(15, 0, 0, 0, 0)
    bis = [
        FakeBi(0, True, None, k_hi1, 100.0),   # 顶端点 100
        FakeBi(1, False, None, k_lo, 90.0),    # 底端点 90
        FakeBi(2, True, None, k_hi2, 100.1),   # 等高(0.2%容差内)→ 聚簇
    ]
    highs, lows = find_liquidity_pools(bis, tol=0.002)
    assert len(highs) == 1 and highs[0].cnt == 2 and highs[0].price == pytest.approx(100.1)
    assert len(lows) == 1 and lows[0].cnt == 1
    # sweep:影线破90收回92 → bull sweep;注意池须先于该K线形成
    sweep_klu = K(30, 91, 92.5, 89.5, 92)
    sweeps = detect_sweeps([sweep_klu], highs, lows)
    assert len(sweeps) == 1 and sweeps[0].is_bull and sweeps[0].pool_price == 90.0
    # 收盘也破位 → 不是sweep
    break_klu = K(31, 91, 91.5, 88, 88.5)
    assert detect_sweeps([break_klu], highs, lows) == []


def test_smc_features_in_chan_flow(synthetic_csv_code):
    """smc 特征族接入完整链路:cbsp 特征包含 smc_*,全部已注册"""
    from ChanModel.FeatureDesc import FEATURE_REG
    chan = CChan(
        code=synthetic_csv_code,
        data_src=DATA_SRC.CSV,
        lv_list=[KL_TYPE.K_DAY],
        config=CChanConfig({
            "divergence_rate": float("inf"),
            "min_zs_cnt": 0,
            "bs_type": "1,2,3a,1p,2s,3b",
            "cbsp_strategy": CCustomStrategy,
        }),
        autype=AUTYPE.NONE,
    )
    cbsp_lst = list(chan[0].cbsp_strategy)
    assert len(cbsp_lst) > 0
    all_smc_keys = set()
    for cbsp in cbsp_lst:
        smc_keys = {k for k, _ in cbsp.features.items() if k.startswith("smc_")}
        all_smc_keys |= smc_keys
    assert len(all_smc_keys) >= 15, f"smc特征太少: {sorted(all_smc_keys)}"
    assert FEATURE_REG.check_features(all_smc_keys) == []
    # PD 位置特征应存在且数值合理
    for cbsp in cbsp_lst:
        feats = dict(cbsp.features.items())
        if "smc_pos_in_seg" in feats:
            assert -3 < feats["smc_pos_in_seg"] < 4
            break
    else:
        pytest.fail("没有任何 cbsp 带 smc_pos_in_seg")


def test_smc_feature_consistency(synthetic_bars, synthetic_csv_code):
    """smc 特征的 load vs trigger 一致性(防未来函数)"""
    from .conftest import make_klu
    conf = {
        "divergence_rate": float("inf"),
        "min_zs_cnt": 0,
        "bs_type": "1,2,3a,1p,2s,3b",
        "cbsp_strategy": CCustomStrategy,
    }
    chan_a = CChan(code=synthetic_csv_code, data_src=DATA_SRC.CSV, lv_list=[KL_TYPE.K_DAY],
                   config=CChanConfig(dict(conf)), autype=AUTYPE.NONE)
    chan_b = CChan(code="dummy", data_src=DATA_SRC.CSV, lv_list=[KL_TYPE.K_DAY],
                   config=CChanConfig({**conf, "trigger_step": True}), autype=AUTYPE.NONE)
    for b in synthetic_bars:
        chan_b.trigger_load({KL_TYPE.K_DAY: [make_klu(b, include_volume=True)]})
    cbsp_a, cbsp_b = list(chan_a[0].cbsp_strategy), list(chan_b[0].cbsp_strategy)
    assert len(cbsp_a) == len(cbsp_b) > 0
    for ca, cb in zip(cbsp_a, cbsp_b):
        fa = {k: v for k, v in ca.features.items() if k.startswith("smc_")}
        fb = {k: v for k, v in cb.features.items() if k.startswith("smc_")}
        assert fa.keys() == fb.keys(), f"@{ca.klu.time} smc特征名不一致: {set(fa) ^ set(fb)}"
        for k in fa:
            assert fa[k] == pytest.approx(fb[k], rel=1e-9), f"@{ca.klu.time} {k}: {fa[k]} != {fb[k]}"


def test_premium_discount_needs_structure(synthetic_csv_code):
    chan = CChan(
        code=synthetic_csv_code,
        data_src=DATA_SRC.CSV,
        lv_list=[KL_TYPE.K_DAY],
        config=CChanConfig({"divergence_rate": float("inf"), "min_zs_cnt": 0}),
        autype=AUTYPE.NONE,
    )
    pos = premium_discount_pos(chan[0], chan[0][-1][-1].close)
    assert "pos_in_zs" in pos and "pos_in_seg" in pos
