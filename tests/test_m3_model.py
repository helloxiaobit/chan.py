"""M3 验收测试:ModelGenerator三件套训练出模型(AUC)、CXGBModel接入、score_thred过滤生效"""
import json
import os

import pytest

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from CustomBuySellPoint.CustomStrategy import CCustomStrategy
from ModelStrategy.BacktestChanConfig import CBacktestConfig
from ModelStrategy.backtest import run_backtest
from ModelStrategy.ModelGenerator import cal_auc, get_market, load_sample_dir

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
def sample_dir(synthetic_csv_code, tmp_path_factory):
    out_dir = str(tmp_path_factory.mktemp("m3_samples"))
    run_backtest(CBacktestConfig(
        code_list=[synthetic_csv_code],
        data_src=DATA_SRC.CSV,
        lv_list=[KL_TYPE.K_DAY],
        autype=AUTYPE.NONE,
        chan_config=FULL_CONF,
        output_dir=out_dir,
        primary_label="label_ret_N",  # 合成数据上该标签正负样本均衡
    ))
    return out_dir


@pytest.fixture(scope="module")
def model_dir(tmp_path_factory):
    return str(tmp_path_factory.mktemp("m3_models"))


def test_cal_auc():
    assert cal_auc([1, 1, 0, 0], [0.9, 0.8, 0.2, 0.1]) == 1.0
    assert cal_auc([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1]) == 0.0
    assert cal_auc([1, 0], [0.5, 0.5]) == 0.5
    assert cal_auc([1, 1], [0.5, 0.6]) is None  # 无负样本


def test_get_market():
    assert get_market("sz.000001") == "cn"
    assert get_market("BTC/USDT") == "crypto"
    assert get_market("HK.00700") == "hk"
    assert get_market("US.AAPL") == "us"


@pytest.fixture(scope="module")
def xgb_result(sample_dir, model_dir):
    pytest.importorskip("xgboost")
    from ModelStrategy.models.Xgboost.XGBTrainModelGenerator import CXGBTrainModelGenerator
    gen = CXGBTrainModelGenerator(model_tag="ut", model_dir=model_dir)
    res = gen.trainProcess(sample_dir)
    return gen, res


def test_xgb_train_process(xgb_result, sample_dir):
    gen, res = xgb_result
    assert os.path.exists(gen.GetModelPath())
    assert os.path.exists(gen.GetMetaPath())
    assert res["train_auc"] is not None and 0 <= res["train_auc"] <= 1
    assert res["train_cnt"] > 0
    # load_model 返回特征维度
    dim = gen.load_model()
    assert dim > 0
    # PredictProcess 分数在 [0,1]
    preds = gen.PredictProcess(sample_dir)
    assert len(preds) > 0
    assert all(0 <= p <= 1 for p in preds)


def test_xgb_bucket_filter(sample_dir, model_dir):
    pytest.importorskip("xgboost")
    from ModelStrategy.models.Xgboost.XGBTrainModelGenerator import CXGBTrainModelGenerator
    _, samples = load_sample_dir(sample_dir)
    buy_cnt = sum(1 for s in samples if s["info"].get("is_buy"))
    gen = CXGBTrainModelGenerator(model_tag="ut", is_buy=True, model_dir=model_dir)
    filtered = [s for s in samples if gen.filter_sample(s)]
    assert len(filtered) == buy_cnt
    assert "buy" in gen.GetTag()


def test_xgb_predict_all_process(xgb_result, sample_dir):
    gen, _ = xgb_result
    out = gen.predictAllProcess(sample_dir)
    assert os.path.exists(out)
    with open(out, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    _, samples = load_sample_dir(sample_dir)
    assert len(rows) == len(samples)
    assert all("score" in r and "label" in r for r in rows)


def test_lgbm_generator(sample_dir, model_dir):
    pytest.importorskip("lightgbm")
    from ModelStrategy.models.lightGBM.LGBMModelGenerator import CLGBMModelGenerator
    gen = CLGBMModelGenerator(model_tag="ut", model_dir=model_dir)
    res = gen.trainProcess(sample_dir)
    assert res["train_auc"] is not None
    gen2 = CLGBMModelGenerator(model_tag="ut", model_dir=model_dir)
    assert gen2.load_model() > 0
    preds = gen2.PredictProcess(sample_dir)
    assert len(preds) > 0 and all(0 <= p <= 1 for p in preds)


def test_mlp_generator(sample_dir, model_dir):
    pytest.importorskip("sklearn")
    from ModelStrategy.models.deepModel.MLPModelGenerator import CMLPModelGenerator
    gen = CMLPModelGenerator(model_tag="ut", model_dir=model_dir)
    res = gen.trainProcess(sample_dir)
    assert res["train_auc"] is not None
    gen2 = CMLPModelGenerator(model_tag="ut", model_dir=model_dir)
    assert gen2.load_model() > 0
    preds = gen2.PredictProcess(sample_dir)
    assert len(preds) > 0 and all(0 <= p <= 1 for p in preds)


def test_xgb_model_in_chan_flow(xgb_result, synthetic_csv_code):
    """CXGBModel + score_thred 生效:cbsp 被打分,低分被过滤"""
    pytest.importorskip("xgboost")
    from ChanModel.XGBModel import CXGBModel
    gen, _ = xgb_result
    model = CXGBModel(gen.GetModelPath())

    def run(score_thred):
        conf = {**FULL_CONF, "model": model}
        if score_thred is not None:
            conf["score_thred"] = score_thred
        chan = CChan(
            code=synthetic_csv_code,
            data_src=DATA_SRC.CSV,
            lv_list=[KL_TYPE.K_DAY],
            config=CChanConfig(conf),
            autype=AUTYPE.NONE,
        )
        return list(chan[0].cbsp_strategy)

    no_filter = run(None)
    assert len(no_filter) > 0
    assert all(c.score is not None for c in no_filter), "配置 model 后所有 cbsp 都应有分数"
    strict = run(1.1)  # 阈值>1,全部过滤
    assert len(strict) == 0
    mid_thred = sorted(c.score for c in no_filter)[len(no_filter) // 2]
    mid = run(mid_thred)
    assert 0 < len(mid) <= len(no_filter)
    assert all(c.score >= mid_thred for c in mid)


def test_demo5_compat_meta_format(sample_dir):
    """meta 格式与 demo5 一致:{feature_name: index}"""
    with open(os.path.join(sample_dir, "feature.meta"), encoding="utf-8") as f:
        meta = json.load(f)
    assert isinstance(meta, dict)
    assert all(isinstance(k, str) and isinstance(v, int) for k, v in meta.items())
