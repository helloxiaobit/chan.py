"""C3 小型合成样本的时间、unknown 和模型列身份契约；不做经济研究。"""
import json
from pathlib import Path

import pytest

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE
from Common.ChanException import CChanException
from Common.KLineTime import make_crypto_klu
from CustomBuySellPoint.CustomBSP import CCustomBSP
from ModelStrategy import ModelGenerator as models
from ModelStrategy.BacktestChanConfig import CBacktestConfig
from ModelStrategy.backtest import CSample, cal_labels, run_backtest, write_samples
from .test_decision_snapshots import HOUR, START, channel, feed


def fixture_chan():
    chan = channel()
    for n in range(3):
        feed(chan, n)
    return chan


def test_unknown_primary_label_is_not_written_as_a_negative_training_row(tmp_path):
    chan = fixture_chan()
    known = CSample(chan.code, chan[0].cbsp_strategy[0], {"label_ret_N": 1},
                    label_end_times={"label_ret_N": START + 2 * HOUR})
    unknown = CSample(chan.code, chan[0].cbsp_strategy[1], {})
    # 后来的 mutable features 不能进入已接受样本。
    known.cbsp.features.add_feat("known", -999)
    write_samples([unknown, known], str(tmp_path), "label_ret_N")
    lines = (tmp_path / "feature.libsvm").read_text().splitlines()
    assert len(lines) == 1 and lines[0].startswith("1 ")
    meta, loaded = models.load_sample_dir(str(tmp_path))
    assert loaded[0]["features"][meta["known"]] == 100.0
    assert len(loaded) == 1
    info = [json.loads(line) for line in (tmp_path / "sample_info.jsonl").read_text().splitlines()]
    assert [r["training_row"] for r in info] == [0, None]
    assert info[0]["decision_ms"] == info[0]["feature_available_at_ms"] == START + HOUR
    assert info[0]["label_end_ms"] == START + 2 * HOUR
    assert info[1]["label"] is None and info[1]["label_end_ms"] is None
    manifest = json.loads((tmp_path / "sample_manifest.json").read_text())
    assert manifest["known_count"] == manifest["unknown_count"] == 1
    _, all_samples = models.load_sample_dir(str(tmp_path), include_unknown=True)
    assert [r["label"] for r in all_samples] == [1, None]
    assert all_samples[1]["features"][meta["known"]] == 102.0


def test_tail_and_unconfirmed_structure_labels_stay_unknown():
    chan = fixture_chan()
    cbsp = chan[0].cbsp_strategy[-1]
    labels, ends = cal_labels(chan, cbsp, CBacktestConfig([]).label_para, with_end_times=True)
    assert "label_ret_N" not in labels
    assert "label_next_bsp" not in labels
    assert "label_max_drawdown" not in labels
    assert "label_seg_confirm" not in labels
    assert set(labels) == set(ends)


def test_known_return_label_end_is_the_observed_future_close():
    chan = fixture_chan()
    cbsp = chan[0].cbsp_strategy[0]
    para = {**CBacktestConfig([]).label_para, "ret_n": 1}
    labels, ends = cal_labels(chan, cbsp, para, with_end_times=True)
    assert labels["label_ret_N"] == 0
    assert ends["label_ret_N"] == START + 2 * HOUR


def test_label_uses_the_accepted_open_price_not_a_later_mutable_object():
    chan = fixture_chan()
    cbsp = chan[0].cbsp_strategy[0]
    para = {**CBacktestConfig([]).label_para, "ret_n": 1, "ret_thred": 0.005}
    expected = cal_labels(chan, cbsp, para)
    assert expected["label_ret_N"] == 1
    cbsp.open_price = 200
    cbsp.is_buy = False
    assert cal_labels(chan, cbsp, para) == expected


@pytest.mark.parametrize("name", ["feature.meta", "feature.libsvm", "sample_info.jsonl"])
def test_sample_payload_mutation_is_rejected_before_training(tmp_path, name):
    chan = fixture_chan()
    sample = CSample(chan.code, chan[0].cbsp_strategy[0], {"label_ret_N": 1},
                     label_end_times={"label_ret_N": START + 2 * HOUR})
    write_samples([sample], str(tmp_path), "label_ret_N")
    with (tmp_path / name).open("a") as handle:
        handle.write(" ")
    with pytest.raises(CChanException, match="漂移|身份"):
        models.load_sample_dir(str(tmp_path))


def row(code, at, end=None, *, label=1):
    return {"label": label, "features": {0: 1.0}, "info": {
        "code": code, "decision_ms": at, "feature_available_at_ms": at,
        "label_end_ms": at if end is None else end}}


def test_multicoin_utc_partitions_are_order_invariant_and_purge_label_overlap():
    rows = [row("BTC", 1, 4), row("BTC", 4, 5), row("BTC", 7, 8), row("BTC", 10, 11),
            row("ETH", 2, 5), row("ETH", 4, 5), row("ETH", 7, 10), row("ETH", 10, 12),
            row("ETH", 3, label=None)]
    parts = models.split_temporal_samples(rows, train_end_ms=6, validation_end_ms=9, test_end_ms=12)
    reversed_parts = models.split_temporal_samples(list(reversed(rows)), train_end_ms=6,
                                                   validation_end_ms=9, test_end_ms=12)
    assert parts == reversed_parts
    assert [(s["info"]["code"], s["info"]["decision_ms"]) for s in parts[0]] == [
        ("BTC", 1), ("ETH", 2), ("BTC", 4), ("ETH", 4)]
    assert [s["info"]["code"] for s in parts[1]] == ["BTC"]
    assert [s["info"]["code"] for s in parts[2]] == ["BTC"]
    assert all(s["info"]["label_end_ms"] < 6 for s in parts[0])


@pytest.mark.parametrize("bad", [
    {"code": "BTC"},
    {"code": "BTC", "decision_ms": 4, "feature_available_at_ms": 5, "label_end_ms": 6},
    {"code": "BTC", "decision_ms": 4, "feature_available_at_ms": 4, "label_end_ms": 3},
])
def test_missing_or_noncausal_sample_timing_cannot_enter_a_split(bad):
    with pytest.raises(CChanException):
        models.split_temporal_samples([{"label": 1, "features": {}, "info": bad}],
                                       train_end_ms=6, validation_end_ms=9)


def test_matching_but_reordered_model_columns_must_map_by_name_before_predict(tmp_path):
    # 复用真正的预测编排，用最小确定性模型隔离列映射，不靠最终维度检查。
    class CColumnModel(models.CModelGenerator):
        def __init__(self):
            super().__init__("fixture", "columns", model_dir=str(tmp_path))

        def load_model(self):
            return 2

        def load_meta(self):
            self.feature_meta = {"alpha": 0, "beta": 1}
            return self.feature_meta

        def create_data_set(self, arr):
            return arr

        def predict(self, arr):
            return [r[0] * 10 + r[1] for r in arr]

        def train(self, *args):
            raise AssertionError("not a training test")

        def create_train_test_set(self, *args):
            raise AssertionError("not a training test")

        def save_model(self):
            raise AssertionError("not a training test")
    (tmp_path / "feature.meta").write_text(json.dumps({"beta": 0, "alpha": 1}))
    (tmp_path / "feature.libsvm").write_text("1 0:2 1:3\n")
    assert CColumnModel().PredictProcess(str(tmp_path)) == [32]


def test_actual_generator_split_is_global_causal_and_three_way(tmp_path):
    from ModelStrategy.models.Xgboost.XGBTrainModelGenerator import CXGBTrainModelGenerator
    gen = CXGBTrainModelGenerator(model_dir=str(tmp_path), folder_thred=0.5)
    rows = [row("BTC", at, at+1) for at in range(1, 21)] + [row("ETH", at, at+1) for at in range(1, 21)]
    train, validation = gen.split_samples(rows)
    boundary = gen.training_boundaries
    assert all(r["info"]["label_end_ms"] < boundary["train_end_ms"] for r in train)
    assert all(boundary["train_end_ms"] <= r["info"]["decision_ms"] < boundary["validation_end_ms"]
               and r["info"]["label_end_ms"] < boundary["validation_end_ms"] for r in validation)
    assert gen.holdout_samples
    assert all(r["info"]["decision_ms"] >= boundary["validation_end_ms"] for r in gen.holdout_samples)
    assert gen.split_samples(list(reversed(rows))) == (train, validation)


def test_purged_empty_training_set_cannot_be_filled_with_validation_rows(tmp_path):
    from ModelStrategy.models.Xgboost.XGBTrainModelGenerator import CXGBTrainModelGenerator
    gen = CXGBTrainModelGenerator(model_dir=str(tmp_path))
    # 所有标签都依赖终局窗口：不能把 validation 信息偷回 train。
    with pytest.raises(CChanException, match="purge|训练|观察"):
        gen.split_samples([row("BTC", i, 100) for i in range(1, 21)])


@pytest.fixture()
def tiny_sample_dir(tmp_path):
    from .test_decision_snapshots import CDecisionStrategy
    class CEveryBar(CDecisionStrategy):
        def try_open(self, chan, lv):
            cur = chan[lv][-1][-1]
            cbsp = CCustomBSP(None, cur, "fixture", True)
            cbsp.add_feat({"alpha": float(cur.idx % 2), "beta": float(cur.idx % 7)})
            return cbsp
    chan = CChan("TEST/USDT:USDT", lv_list=[KL_TYPE.K_60M], config=CChanConfig({
        "trigger_step": True, "cbsp_strategy": CEveryBar, "strategy_para": {"skip_features": True}}))
    for i in range(51):
        chan.trigger_load({KL_TYPE.K_60M: [make_crypto_klu([START+i*HOUR, 100, 110, 90, 100, 1], KL_TYPE.K_60M)]})
    samples = [CSample(chan.code, cbsp, {"label_ret_N": i % 2},
                       label_end_times={"label_ret_N": START + (i+2)*HOUR})
               for i, cbsp in enumerate(list(chan[0].cbsp_strategy)[:-1])]
    samples.append(CSample(chan.code, chan[0].cbsp_strategy[-1], {}))
    path = tmp_path / "samples"
    write_samples(samples, str(path), "label_ret_N", label_parameters={"fixture": "alternating-bit"})
    return path


def model_factory(kind, path):
    if kind == "xgb":
        from ModelStrategy.models.Xgboost.XGBTrainModelGenerator import CXGBTrainModelGenerator
        return CXGBTrainModelGenerator(model_tag="contract", model_dir=str(path), num_boost_round=2)
    if kind == "lgbm":
        from ModelStrategy.models.lightGBM.LGBMModelGenerator import CLGBMModelGenerator
        return CLGBMModelGenerator(model_tag="contract", model_dir=str(path), num_boost_round=2)
    from ModelStrategy.models.deepModel.MLPModelGenerator import CMLPModelGenerator
    return CMLPModelGenerator(model_tag="contract", model_dir=str(path),
                              mlp_params={"hidden_layer_sizes": (2,), "max_iter": 60, "random_state": 42})


@pytest.mark.parametrize("kind", ["xgb", "lgbm", "mlp"])
def test_real_model_artifact_binds_training_identity_and_rejects_meta_drift(kind, tiny_sample_dir, tmp_path):
    gen = model_factory(kind, tmp_path / "model")
    result = gen.trainProcess(str(tiny_sample_dir))
    contract = json.loads(Path(gen.GetContractPath()).read_bytes())
    assert contract["schema"] == "chan-model-v1"
    assert contract["model_type"] == kind
    assert contract["feature_meta"] == {"alpha": 0, "beta": 1}
    assert contract["split_boundaries_ms"] == result["split_boundaries_ms"]
    assert contract["label_definition"]["parameters"] == {"fixture": "alternating-bit"}
    assert contract["samples_manifest_sha256"] and contract["feature_code"]["sha256"]
    assert contract["generator_config_sha256"]
    restored = model_factory(kind, tmp_path / "model")
    assert restored.PredictProcess(str(tiny_sample_dir)) == pytest.approx(gen.PredictProcess(str(tiny_sample_dir)))
    with open(gen.GetMetaPath(), "w", encoding="utf-8") as handle:
        json.dump({"beta": 0, "alpha": 1}, handle)
    with pytest.raises(CChanException, match="meta|漂移|身份"):
        restored.load_model()


@pytest.mark.parametrize("kind", ["xgb", "lgbm", "mlp"])
def test_online_model_uses_the_exact_persisted_artifact(kind, tiny_sample_dir, tmp_path):
    from ChanModel.GeneratorModel import CGeneratorModel
    gen = model_factory(kind, tmp_path / "model")
    gen.trainProcess(str(tiny_sample_dir))
    online = CGeneratorModel(gen.GetModelPath())
    cbsp = fixture_chan()[0].cbsp_strategy[0]
    from ChanModel.Features import CFeatures
    cbsp.features = CFeatures({"beta": 3.0, "alpha": 1.0})
    expected = gen.predict(gen.create_data_set([[1.0, 3.0]]))[0]
    assert online.predict(cbsp) == pytest.approx(expected)
    assert online.artifact_id
    cbsp.features = CFeatures({"beta": 3.0})
    with pytest.raises(CChanException, match="特征|feature"):
        online.predict(cbsp)


def test_strategy_failure_closes_active_source_generators(monkeypatch):
    from .test_decision_snapshots import CDecisionStrategy
    closed = []
    class CBroken(CDecisionStrategy):
        def try_open(self, chan, lv):
            raise CChanException("fixture model failure", models.ErrCode.MODEL_ERROR)
    class CAPI:
        def __init__(self, **kwargs):
            pass

        @classmethod
        def do_init(cls):
            pass

        @classmethod
        def do_close(cls):
            pass

        def get_kl_data(self):
            try:
                for i in range(3):
                    yield make_crypto_klu([START+i*HOUR, 100, 110, 90, 100, 1], KL_TYPE.K_60M)
            finally:
                closed.append(True)
    monkeypatch.setattr(CChan, "GetStockAPI", lambda self: CAPI)
    with pytest.raises(CChanException, match="fixture model"):
        CChan("TEST/USDT", lv_list=[KL_TYPE.K_60M], config=CChanConfig({"cbsp_strategy": CBroken}))
    assert closed == [True]


def test_stale_sample_formula_identity_cannot_be_rebranded_by_new_training(tiny_sample_dir, tmp_path):
    from CustomBuySellPoint.Decision import canonical_bytes
    path = tiny_sample_dir / "sample_manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["feature_code"]["sha256"] = "0" * 64
    path.write_bytes(canonical_bytes(manifest))
    with pytest.raises(CChanException, match="公式|feature|身份"):
        model_factory("xgb", tmp_path / "model").trainProcess(str(tiny_sample_dir))


@pytest.mark.parametrize("remove", ["required_features", "label_definition", "samples_manifest_sha256"])
def test_model_contract_missing_required_provenance_is_rejected(remove, tiny_sample_dir, tmp_path):
    from CustomBuySellPoint.Decision import canonical_bytes
    gen = model_factory("xgb", tmp_path / "model")
    gen.trainProcess(str(tiny_sample_dir))
    path = Path(gen.GetContractPath())
    contract = json.loads(path.read_bytes())
    del contract[remove]
    path.write_bytes(canonical_bytes(contract))
    with pytest.raises(CChanException):
        gen.load_model()


def test_sample_manifest_binds_full_source_inputs_before_strategy_mutation(monkeypatch, tmp_path):
    import hashlib
    from CustomBuySellPoint.Decision import bar_snapshot, canonical_bytes
    from .test_decision_snapshots import CDecisionStrategy
    def bars():
        return [make_crypto_klu([START+i*HOUR, 100, 110, 90, 100, 1], KL_TYPE.K_60M) for i in range(3)]
    class CAPI:
        def __init__(self, **kwargs):
            pass

        @classmethod
        def do_init(cls):
            pass

        @classmethod
        def do_close(cls):
            pass

        def get_kl_data(self):
            yield from bars()
    monkeypatch.setattr(CChan, "GetStockAPI", lambda self: CAPI)
    run_backtest(CBacktestConfig(["TEST/USDT:USDT"], lv_list=[KL_TYPE.K_60M], output_dir=str(tmp_path),
        primary_label="label_ret_N", chan_config={"cbsp_strategy": CDecisionStrategy, "strategy_para": {"skip_features": True}}))
    manifest = json.loads((tmp_path / "sample_manifest.json").read_bytes())
    digest = hashlib.sha256()
    for bar in bars():
        digest.update(canonical_bytes({**bar_snapshot(bar), "trade_info": bar.trade_info.metric}) + b"\n")
    actual = manifest["generation_context"]["input_manifests"]["TEST/USDT:USDT"]["K_60M"]
    assert actual == {"count": 3, "sha256": digest.hexdigest()}


def test_binary_training_with_only_one_class_publishes_no_artifact(tiny_sample_dir, tmp_path):
    gen = model_factory("mlp", tmp_path / "model")
    gen.filter_sample = lambda s: s["label"] == 1
    with pytest.raises(CChanException, match="类别|class"):
        gen.trainProcess(str(tiny_sample_dir))
    assert not Path(gen.GetContractPath()).exists()


def test_invalid_prediction_cannot_publish_a_model_contract(tiny_sample_dir, tmp_path):
    gen = model_factory("xgb", tmp_path / "model")
    gen.predict = lambda data: [float("nan")] * data.get_count()
    with pytest.raises(CChanException, match="有限|概率|预测"):
        gen.trainProcess(str(tiny_sample_dir))
    assert not Path(gen.GetContractPath()).exists()


def test_predict_all_keeps_unlabeled_features_without_training_on_them(tiny_sample_dir, tmp_path):
    gen = model_factory("xgb", tmp_path / "model")
    gen.trainProcess(str(tiny_sample_dir))
    scores = [json.loads(line) for line in Path(gen.predictAllProcess(str(tiny_sample_dir))).read_text().splitlines()]
    assert len(scores) == 51
    assert sum(s["label"] is None for s in scores) == 1
    assert gen.contract["unknown_count"] == 1
    assert gen.contract["split_counts"]["input"] == 50
    assert all(s["model_artifact_id"] == gen.artifact_id for s in scores)


def test_nonnumeric_features_are_rejected_before_creating_any_sample_files(tmp_path):
    chan = channel(fixture_feature="not-a-number")
    feed(chan, 0)
    sample = CSample(chan.code, chan[0].cbsp_strategy[0], {"label_ret_N": 1},
                     label_end_times={"label_ret_N": START + 2 * HOUR})
    with pytest.raises(CChanException, match="数字|特征"):
        write_samples([sample], str(tmp_path), "label_ret_N")
    assert list(tmp_path.iterdir()) == []
