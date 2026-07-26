"""M2 验收测试:特征引擎(≥500特征)、FeatureDesc 注册检查、OutlinerDetection、backtest 样本落地"""
import json
import os

import pytest

from Chan import CChan
from ChanConfig import CChanConfig
from ChanModel.FeatureDesc import FEATURE_REG
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from CustomBuySellPoint.CustomStrategy import CCustomStrategy
from Math.OutlinerDetection import COutlinerDetection
from ModelStrategy.BacktestChanConfig import CBacktestConfig
from ModelStrategy.backtest import run_backtest

from .conftest import make_klu

# 特征全开配置
FULL_CONF = {
    "divergence_rate": float("inf"),
    "min_zs_cnt": 0,
    "bs_type": "1,2,3a,1p,2s,3b",
    "cbsp_strategy": CCustomStrategy,
    "mean_metrics": [5, 20, 60],
    "trend_metrics": [10, 20],
    "cal_rsi": True,
    "cal_kdj": True,
    "cal_demark": True,
}


@pytest.fixture(scope="module")
def bt_result(synthetic_csv_code, tmp_path_factory):
    out_dir = str(tmp_path_factory.mktemp("bt_out"))
    bt_conf = CBacktestConfig(
        code_list=[synthetic_csv_code],
        data_src=DATA_SRC.CSV,
        lv_list=[KL_TYPE.K_DAY],
        autype=AUTYPE.NONE,
        chan_config=FULL_CONF,
        output_dir=out_dir,
    )
    return run_backtest(bt_conf)


def test_feature_count_over_500(bt_result):
    assert bt_result.feature_cnt >= 500, f"特征数 {bt_result.feature_cnt} < 500"


def test_no_unregistered_features(bt_result):
    assert bt_result.unregistered_features == [], f"未注册特征: {bt_result.unregistered_features[:20]}"


def test_libsvm_and_meta_files(bt_result):
    assert os.path.exists(bt_result.libsvm_path)
    assert os.path.exists(bt_result.meta_path)
    assert os.path.exists(bt_result.sample_info_path)
    with open(bt_result.meta_path) as f:
        meta = json.load(f)
    assert len(meta) == bt_result.feature_cnt
    assert sorted(meta.values()) == list(range(len(meta)))  # 索引连续
    with open(bt_result.libsvm_path) as f:
        lines = f.read().strip().split("\n")
    assert len(lines) == len(bt_result.samples) > 0
    for line in lines:
        parts = line.split(" ")
        assert parts[0] in ("0", "1")  # 主标签
        for kv in parts[1:]:
            idx, val = kv.split(":")
            assert 0 <= int(idx) < len(meta)
            float(val)


def test_five_labels(bt_result):
    label_names = {"label_bsp_hold", "label_ret_N", "label_next_bsp", "label_max_drawdown", "label_seg_confirm"}
    seen = set()
    for sample in bt_result.samples:
        assert set(sample.labels.keys()) <= label_names
        for v in sample.labels.values():
            assert v in (0, 1)
        seen.update(sample.labels.keys())
    assert seen == label_names, f"五种标签应全部出现,实际: {seen}"


def test_xgb_can_load_libsvm(bt_result):
    xgb = pytest.importorskip("xgboost")
    dtrain = xgb.DMatrix(f"{bt_result.libsvm_path}?format=libsvm")
    assert dtrain.num_row() == len(bt_result.samples)


def test_feature_consistency_load_vs_trigger(synthetic_bars, synthetic_csv_code):
    """特征防未来函数的强校验:一次性 load 与逐根 trigger 投喂的特征值必须完全一致
    (若特征用了当前K线之后的数据,两种模式必然不同)"""
    chan_a = CChan(
        code=synthetic_csv_code,
        data_src=DATA_SRC.CSV,
        lv_list=[KL_TYPE.K_DAY],
        config=CChanConfig(dict(FULL_CONF)),
        autype=AUTYPE.NONE,
    )
    chan_b = CChan(
        code="dummy",
        data_src=DATA_SRC.CSV,
        lv_list=[KL_TYPE.K_DAY],
        config=CChanConfig({**FULL_CONF, "trigger_step": True}),
        autype=AUTYPE.NONE,
    )
    for b in synthetic_bars:
        chan_b.trigger_load({KL_TYPE.K_DAY: [make_klu(b, include_volume=True)]})

    cbsp_a, cbsp_b = list(chan_a[0].cbsp_strategy), list(chan_b[0].cbsp_strategy)
    assert len(cbsp_a) == len(cbsp_b) > 0
    for ca, cb in zip(cbsp_a, cbsp_b):
        fa, fb = dict(ca.features.items()), dict(cb.features.items())
        assert fa.keys() == fb.keys(), f"cbsp@{ca.klu.time} 特征名不一致: {set(fa) ^ set(fb)}"
        for k in fa:
            assert fa[k] == pytest.approx(fb[k], rel=1e-9), f"cbsp@{ca.klu.time} 特征 {k}: {fa[k]} != {fb[k]}"


def test_outliner_detection():
    od = COutlinerDetection("volume", win_width=5, mean_thred=3.0)
    assert od.add(100) is None  # 窗口空
    for _ in range(5):
        od.add(100)
    score = od.add(500)
    assert score == pytest.approx(5.0)
    assert od.is_outliner(score)
    assert not od.is_outliner(od.add(100))


def test_outliner_zero_handling():
    from Common.ChanException import CChanException
    od = COutlinerDetection("volume", win_width=5, max_zero_cnt=2, skip_zero=True)
    od.add(100)
    od.add(0)
    od.add(0)
    with pytest.raises(CChanException):
        od.add(0)


def test_od_score_on_klu(synthetic_csv_code):
    from Common.CEnum import DATA_FIELD
    chan = CChan(
        code=synthetic_csv_code,
        data_src=DATA_SRC.CSV,
        lv_list=[KL_TYPE.K_DAY],
        config=CChanConfig(dict(FULL_CONF)),
        autype=AUTYPE.NONE,
    )
    last_klu = chan[0][-1][-1]
    assert hasattr(last_klu, "od_scores")
    assert DATA_FIELD.FIELD_VOLUME in last_klu.od_scores
