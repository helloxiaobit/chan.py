"""一致性测试(quick_guide「一致性」章节):
同一批K线,一次性 load 与 trigger_load 逐根投喂,最终笔/段/中枢/买卖点必须完全一致。
"""
import pytest

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE

from .conftest import make_klu

# 两组配置:默认配置 + main.py 同款配置
CONFIGS = {
    "default": {},
    "main_py": {
        "bi_strict": True,
        "divergence_rate": float("inf"),
        "bsp2_follow_1": False,
        "bsp3_follow_1": False,
        "min_zs_cnt": 0,
        "bs1_peak": False,
        "macd_algo": "peak",
        "bs_type": '1,2,3a,1p,2s,3b',
        "print_warning": True,
        "zs_algo": "normal",
    },
}


def chan_signature(chan: CChan, lv_idx=0):
    """提取一个级别的缠论元素签名,用于两种计算模式的比对"""
    lv = chan[lv_idx]
    bis = [
        (bi.idx, bi.dir, bi.get_begin_klu().idx, bi.get_end_klu().idx, bi.is_sure)
        for bi in lv.bi_list
    ]
    segs = [
        (seg.idx, seg.dir, seg.start_bi.idx, seg.end_bi.idx, seg.is_sure)
        for seg in lv.seg_list
    ]
    zss = [
        (zs.begin_bi.idx, zs.end_bi.idx, round(zs.low, 6), round(zs.high, 6), zs.is_sure)
        for zs in lv.zs_list
    ]
    bsps = sorted(
        (bsp.klu.idx, bsp.is_buy, bsp.type2str())
        for bsp in lv.bs_point_lst.getSortedBspList()
    )
    seg_bsps = sorted(
        (bsp.klu.idx, bsp.is_buy, bsp.type2str())
        for bsp in lv.seg_bs_point_lst.getSortedBspList()
    )
    return {"bi": bis, "seg": segs, "zs": zss, "bsp": bsps, "seg_bsp": seg_bsps}


def load_once(code, conf_dict):
    chan = CChan(
        code=code,
        data_src=DATA_SRC.CSV,
        lv_list=[KL_TYPE.K_DAY],
        config=CChanConfig(dict(conf_dict)),
        autype=AUTYPE.NONE,
    )
    return chan_signature(chan)


def load_by_trigger(bars, conf_dict, batch=1):
    chan = CChan(
        code="trigger_dummy",
        data_src=DATA_SRC.CSV,
        lv_list=[KL_TYPE.K_DAY],
        config=CChanConfig({**conf_dict, "trigger_step": True}),
        autype=AUTYPE.NONE,
    )
    for i in range(0, len(bars), batch):
        chan.trigger_load({KL_TYPE.K_DAY: [make_klu(b) for b in bars[i:i + batch]]})
    return chan_signature(chan)


@pytest.mark.parametrize("conf_name", list(CONFIGS.keys()))
def test_load_vs_trigger_one_by_one(synthetic_bars, synthetic_csv_code, conf_name):
    """一次性 load vs trigger_load 每次一根"""
    sig_a = load_once(synthetic_csv_code, CONFIGS[conf_name])
    sig_b = load_by_trigger(synthetic_bars, CONFIGS[conf_name], batch=1)
    for key in sig_a:
        assert sig_a[key] == sig_b[key], f"[{conf_name}] {key} 不一致"


def test_load_vs_trigger_all_at_once(synthetic_bars, synthetic_csv_code):
    """一次性 load vs trigger_load 一次全量投喂(非回放模式)"""
    sig_a = load_once(synthetic_csv_code, CONFIGS["main_py"])
    # trigger_step=True 只是为了绕过构造时自动 load;随后关掉,让 trigger_load 走"最后统一计算"路径
    chan = CChan(
        code="trigger_dummy",
        data_src=DATA_SRC.CSV,
        lv_list=[KL_TYPE.K_DAY],
        config=CChanConfig({**CONFIGS["main_py"], "trigger_step": True}),
        autype=AUTYPE.NONE,
    )
    chan.conf.trigger_step = False
    for lv in chan.lv_list:
        chan.kl_datas[lv].step_calculation = False
    chan.trigger_load({KL_TYPE.K_DAY: [make_klu(b) for b in synthetic_bars]})
    sig_b = chan_signature(chan)
    for key in sig_a:
        assert sig_a[key] == sig_b[key], f"{key} 不一致"


def test_synthetic_data_has_enough_elements(synthetic_csv_code):
    """合成数据要足够复杂:能产生笔/段/中枢/买卖点,fixture 才有意义"""
    chan = CChan(
        code=synthetic_csv_code,
        data_src=DATA_SRC.CSV,
        lv_list=[KL_TYPE.K_DAY],
        config=CChanConfig(dict(CONFIGS["main_py"])),
        autype=AUTYPE.NONE,
    )
    lv = chan[0]
    assert len(lv.bi_list) >= 20
    assert len(lv.seg_list) >= 5
    assert len(lv.zs_list) >= 3
    assert len(lv.bs_point_lst.getSortedBspList()) >= 5
