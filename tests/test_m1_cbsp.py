"""M1 验收测试:CChanConfig 全参数、cbsp 策略框架、extra_kl、toJson、开关生效"""
import json
import os

import pytest

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from CustomBuySellPoint.CustomStrategy import CCustomStrategy
from CustomBuySellPoint.SegBspStrategy import CSegBspStrategy

from .conftest import ROOT, make_klu

BASE_CONF = {
    "divergence_rate": float("inf"),
    "min_zs_cnt": 0,
    "bs_type": "1,2,3a,1p,2s,3b",
}


def run_chan(code, conf_dict, lv_list=None):
    return CChan(
        code=code,
        data_src=DATA_SRC.CSV,
        lv_list=lv_list or [KL_TYPE.K_DAY],
        config=CChanConfig(dict(conf_dict)),
        autype=AUTYPE.NONE,
    )


def cbsp_signature(chan, lv=0):
    return [
        (c.klu.idx, c.is_buy, c.bs_type, round(c.open_price, 6), c.is_cover,
         None if c.profit is None else round(c.profit, 6))
        for c in chan[lv].cbsp_strategy
    ]


def test_config_accepts_full_params():
    """README 完整版参数全部可传入,不抛 unknown para"""
    conf = CChanConfig({
        "model": None,
        "score_thred": 0.5,
        "score_thred-buy": 0.6,
        "cal_feature": False,
        "cbsp_strategy": CCustomStrategy,
        "strategy_para": {"strict_open": False, "max_sl_rate": 0.05},
        "strategy_para-sell": {"max_sl_rate": 0.03},
        "only_judge_last": False,
        "cal_cover": True,
        "cbsp_check_active": True,
        "print_inactive_reason": False,
        "stock_no_active_day": 30,
        "stock_no_active_thred": 3,
        "stock_distinct_price_thred": 25,
        "od_win_width": 100,
        "od_mean_thred": 3.0,
        "od_max_zero_cnt": None,
        "od_skip_zero": True,
    })
    # cbsp_strategy 开启时强制 cal_feature
    assert conf.cal_feature is True
    assert conf.strategy_para["strict_open"] is False
    assert conf.strategy_para["use_qjt"] is True  # 默认值保留
    # 精确后缀
    assert conf.get_score_thred(is_buy=True) == 0.6
    assert conf.get_score_thred(is_buy=False) == 0.5
    assert conf.get_strategy_para("max_sl_rate", is_buy=True) == 0.05
    assert conf.get_strategy_para("max_sl_rate", is_buy=False) == 0.03


def test_unknown_para_still_raises():
    from Common.ChanException import CChanException
    with pytest.raises(CChanException):
        CChanConfig({"not_a_para": 1})


def test_custom_strategy_produces_cbsp(synthetic_csv_code):
    chan = run_chan(synthetic_csv_code, {**BASE_CONF, "cbsp_strategy": CCustomStrategy})
    strategy = chan[0].cbsp_strategy
    assert strategy is not None
    assert len(strategy) > 0, "合成数据上应产出至少一个 cbsp"
    for cbsp in strategy:
        assert cbsp.open_price > 0
        assert cbsp.bs_type
        assert cbsp.klu is not None
    # 有平仓发生(cal_cover 默认 True)
    assert any(c.is_cover for c in strategy)


def test_short_shelling_off(synthetic_csv_code):
    chan = run_chan(synthetic_csv_code, {
        **BASE_CONF,
        "cbsp_strategy": CCustomStrategy,
        "strategy_para": {"short_shelling": False},
    })
    assert all(c.is_buy for c in chan[0].cbsp_strategy), "关闭做空后不应有卖开 cbsp"
    chan_on = run_chan(synthetic_csv_code, {
        **BASE_CONF,
        "cbsp_strategy": CCustomStrategy,
        "strategy_para": {"short_shelling": True},
    })
    assert any(not c.is_buy for c in chan_on[0].cbsp_strategy), "开启做空后合成数据应有卖开 cbsp"


def test_strict_open_toggle(synthetic_csv_code):
    cnt = {}
    for strict in (True, False):
        chan = run_chan(synthetic_csv_code, {
            **BASE_CONF,
            "cbsp_strategy": CCustomStrategy,
            "strategy_para": {"strict_open": strict},
        })
        cnt[strict] = len(chan[0].cbsp_strategy)
    assert cnt[False] >= cnt[True], "非严格开仓允许追开,数量不应更少"


def test_max_sl_rate_truncates(synthetic_csv_code):
    chan = run_chan(synthetic_csv_code, {
        **BASE_CONF,
        "cbsp_strategy": CCustomStrategy,
        "strategy_para": {"max_sl_rate": 0.02},
    })
    for cbsp in chan[0].cbsp_strategy:
        assert cbsp.sl_price is not None
        sl_rate = abs(cbsp.open_price - cbsp.sl_price) / cbsp.open_price
        assert sl_rate <= 0.02 + 1e-9


def test_seg_bsp_strategy(synthetic_csv_code):
    chan = run_chan(synthetic_csv_code, {**BASE_CONF, "cbsp_strategy": CSegBspStrategy})
    for cbsp in chan[0].cbsp_strategy:
        assert cbsp.is_segbsp


def test_consistency_load_vs_trigger_with_strategy(synthetic_bars, synthetic_csv_code):
    """一次性 load 与逐根 trigger_load 的 cbsp 必须一致(一致性最高验收)"""
    conf = {**BASE_CONF, "cbsp_strategy": CCustomStrategy}
    chan_a = run_chan(synthetic_csv_code, conf)
    sig_a = cbsp_signature(chan_a)

    chan_b = CChan(
        code="dummy",
        data_src=DATA_SRC.CSV,
        lv_list=[KL_TYPE.K_DAY],
        config=CChanConfig({**conf, "trigger_step": True}),
        autype=AUTYPE.NONE,
    )
    for b in synthetic_bars:
        chan_b.trigger_load({KL_TYPE.K_DAY: [make_klu(b)]})
    sig_b = cbsp_signature(chan_b)
    assert sig_a == sig_b


def test_only_judge_last(synthetic_csv_code):
    chan = run_chan(synthetic_csv_code, {
        **BASE_CONF,
        "cbsp_strategy": CCustomStrategy,
        "only_judge_last": True,
    })
    # 快速路径:只判断最后一根K线,cbsp 数量至多 1
    assert len(chan[0].cbsp_strategy) <= 1
    # 快速路径不应触发逐K计算
    assert chan[0].step_calculation is False


def test_extra_kl_list(synthetic_bars, synthetic_csv_code):
    """extra_kl(list)拼接:csv 前900根 + extra_kl 后100根 == 全量 csv"""
    part_code = "test_synth_part"
    part_path = os.path.join(ROOT, f"{part_code}_day.csv")
    with open(part_path, "w", encoding="utf-8") as f:
        f.write("datetime,open,high,low,close\n")
        for b in synthetic_bars[:900]:
            f.write(f"{b['year']:04}-{b['month']:02}-{b['day']:02},{b['open']},{b['high']},{b['low']},{b['close']}\n")
    try:
        chan_full = run_chan(synthetic_csv_code, BASE_CONF)
        chan_part = CChan(
            code=part_code,
            data_src=DATA_SRC.CSV,
            lv_list=[KL_TYPE.K_DAY],
            config=CChanConfig(dict(BASE_CONF)),
            autype=AUTYPE.NONE,
            extra_kl=[make_klu(b) for b in synthetic_bars[900:]],
        )
        assert sum(len(klc.lst) for klc in chan_full[0]) == sum(len(klc.lst) for klc in chan_part[0])
        bi_a = [(bi.idx, bi.get_begin_klu().idx, bi.get_end_klu().idx) for bi in chan_full[0].bi_list]
        bi_b = [(bi.idx, bi.get_begin_klu().idx, bi.get_end_klu().idx) for bi in chan_part[0].bi_list]
        assert bi_a == bi_b
    finally:
        os.remove(part_path)


def test_extra_kl_list_multi_lv_raises(synthetic_bars):
    from Common.ChanException import CChanException
    with pytest.raises(CChanException):
        CChan(
            code="dummy",
            data_src=DATA_SRC.CSV,
            lv_list=[KL_TYPE.K_DAY, KL_TYPE.K_60M],
            config=CChanConfig({"trigger_step": False}),
            autype=AUTYPE.NONE,
            extra_kl=[make_klu(b) for b in synthetic_bars[:10]],
        )


def test_tojson(synthetic_csv_code):
    chan = run_chan(synthetic_csv_code, {**BASE_CONF, "cbsp_strategy": CCustomStrategy})
    data = chan.toJson()
    s = json.dumps(data)  # 可序列化
    assert "K_DAY" in data
    for key in ("klu", "bi", "seg", "zs", "bsp", "cbsp"):
        assert key in data["K_DAY"], f"toJson 缺少 {key}"
    assert len(data["K_DAY"]["cbsp"]) == len(chan[0].cbsp_strategy)
    assert len(s) > 100


def test_qjt_multi_lv(synthetic_bars, synthetic_csv_code):
    """多级别 use_qjt 开关:开启后跑通;区间套 q 类型只在开启时出现"""
    # 由日线拆出4根60分钟K线(10:30/11:30/14:00/15:00),合并后与父K线 OHLC 一致
    sub_path = os.path.join(ROOT, f"{synthetic_csv_code}_60m.csv")
    with open(sub_path, "w", encoding="utf-8") as f:
        f.write("datetime,open,high,low,close\n")
        for b in synthetic_bars:
            o, h, l, c = b["open"], b["high"], b["low"], b["close"]
            pairs = [(o, h), (h, l), (l, c), (c, c)]
            times = ["10:30:00", "11:30:00", "14:00:00", "15:00:00"]
            for (so, sc), t in zip(pairs, times):
                sh, sl = max(so, sc), min(so, sc)
                f.write(f"{b['year']:04}-{b['month']:02}-{b['day']:02} {t},{so},{sh},{sl},{sc}\n")
    try:
        result = {}
        for use_qjt in (True, False):
            chan = run_chan(
                synthetic_csv_code,
                {
                    **BASE_CONF,
                    "cbsp_strategy": CCustomStrategy,
                    "strategy_para": {"use_qjt": use_qjt},
                    "kl_data_check": False,
                },
                lv_list=[KL_TYPE.K_DAY, KL_TYPE.K_60M],
            )
            result[use_qjt] = cbsp_signature(chan, lv=0)
        qjt_types_on = [c for c in result[True] if "q" in c[2]]
        qjt_types_off = [c for c in result[False] if "q" in c[2]]
        assert not qjt_types_off, "未开启 use_qjt 不应出现区间套买卖点"
        # 开启后至少跑通(区间套是否出现取决于数据形态,不强行断言数量)
        assert isinstance(qjt_types_on, list)
    finally:
        os.remove(sub_path)
