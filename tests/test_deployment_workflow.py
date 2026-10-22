"""真实 SQLite、生产策略和小合成模型的统一部署/评分工作流；不连接交易所。"""
import json
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from Chan import CChan
from Common.CEnum import AUTYPE, KL_TYPE
from Common.ChanException import CChanException
from Config.EnvConfig import CEnv
from CustomBuySellPoint.CustomStrategy import CCustomStrategy
from CustomBuySellPoint.Decision import canonical_bytes
from ModelStrategy.BacktestChanConfig import CBacktestConfig
from ModelStrategy.backtest import run_backtest
from ModelStrategy.models.Xgboost.XGBTrainModelGenerator import CXGBTrainModelGenerator
from OfflineData.offline_data_util import CKLineDB
from .conftest import gen_synthetic_bars
from .test_decision_snapshots import HOUR, START

SOURCE = {"exchange": "binance", "market_type": "swap", "settle": "USDT", "price_type": "contract"}
CODE = "TEST/USDT:USDT"


@pytest.fixture(scope="module")
def deployment_model(tmp_path_factory):
    root = tmp_path_factory.mktemp("deployment")
    with deployment_model_data(root, source=SOURCE) as result:
        yield result


@contextmanager
def deployment_model_data(root, *, source, codes=(CODE,)):
    config_path = root / "config.yaml"
    config_path.write_text(json.dumps({
        "offline_data": {"sqlite_path": str(root / "kline.db"), "source_identity": source},
        "db": {"type": "sqlite", "sqlite_path": str(root / "trade.db")},
        "notify": {"backend": "none"},
        "trade": {"code_list": list(codes), "lv_list": ["K_60M"], "strategy": "custom"}}))
    previous = os.environ.get("CHANPY_CONFIG")
    os.environ["CHANPY_CONFIG"] = str(config_path)
    CEnv.reset_instance()
    try:
        rows = [(START+i*HOUR, b["open"], b["high"], b["low"], b["close"], b["volume"])
                for i, b in enumerate(gen_synthetic_bars(1000))]
        rows_by_code = {code: [(row[0], *(value*(index+1) for value in row[1:5]), row[5]) for row in rows]
                        for index, code in enumerate(codes)}
        with CKLineDB(str(root / "kline.db")) as db:
            db.bind_source(source)
            for code in codes:
                db.upsert_klines(code, KL_TYPE.K_60M, rows_by_code[code][:600])
        chan_config = {"cbsp_strategy": CCustomStrategy, "divergence_rate": float("inf"), "min_zs_cnt": 0,
                       "bs_type": "1,2,3a,1p,2s,3b", "kl_data_check": True,
                       "mean_metrics": [5, 20, 60], "trend_metrics": [10, 20],
                       "cal_rsi": True, "cal_kdj": True, "cal_demark": True}
        result = run_backtest(CBacktestConfig(list(codes), lv_list=[KL_TYPE.K_60M], autype=AUTYPE.NONE,
            data_src="custom:OfflineDataAPI.CStockFileReader", chan_config=chan_config,
            primary_label="label_ret_N", label_para={"ret_n": 1}, output_dir=str(root / "samples")))
        assert len(result.samples) >= 6
        gen = CXGBTrainModelGenerator(model_tag="workflow", model_dir=str(root / "models"), folder_thred=0.6,
                                      num_boost_round=2)
        gen.trainProcess(result.output_dir)
        with CKLineDB(str(root / "kline.db")) as db:
            for code in codes:
                db.upsert_klines(code, KL_TYPE.K_60M, rows_by_code[code][600:])
        yield {"root": root, "model": gen, "rows": rows, "rows_by_code": rows_by_code,
               "chan_config": chan_config, "source_identity": source}
    finally:
        if previous is None:
            os.environ.pop("CHANPY_CONFIG", None)
        else:
            os.environ["CHANPY_CONFIG"] = previous
        CEnv.reset_instance()


def publish(path, model):
    from Trade.Script.Deployment import publish_deployment
    return publish_deployment(path, model.GetModelPath(), candidate_score=0.1, entry_score=0.2, post_score=0.3)


def future_candidate(deployment_model):
    return future_candidates(deployment_model)[CODE]


def future_candidates(deployment_model, *, codes=(CODE,)):
    from ChanConfig import CChanConfig
    from Common.KLineTime import make_crypto_klu
    chans = {code: CChan(code, lv_list=[KL_TYPE.K_60M],
        config=CChanConfig({**deployment_model["chan_config"], "trigger_step": True})) for code in codes}
    histories = deployment_model.get("rows_by_code", {CODE: deployment_model["rows"]})
    for i, group in enumerate(zip(*(histories[code] for code in codes), strict=True)):
        for code, row in zip(codes, group, strict=True):
            unit = make_crypto_klu(row, KL_TYPE.K_60M)
            unit.source_identity = deployment_model["source_identity"]
            chans[code].trigger_load({KL_TYPE.K_60M: [unit]})
        if i >= 600:
            signals = {code: chan[0].cbsp_strategy.bsp_signal(chan, 0) for code, chan in chans.items()}
            if all(signals.values()):
                return {code: (chans[code], values[0]) for code, values in signals.items()}
    raise AssertionError("夹具须有真实的训练窗口后候选信号")


def test_deployment_binds_real_training_config_source_and_thresholds(deployment_model, tmp_path):
    from Trade.Script.Deployment import CDeployment
    gen = deployment_model["model"]
    path = tmp_path / "deployment.json"
    deployment_id = publish(path, gen)
    deployed = CDeployment(path)
    assert deployed.deployment_id == deployment_id
    assert deployed.model.artifact_id == gen.artifact_id
    assert deployed.code_list == [CODE] and deployed.lv_list == [KL_TYPE.K_60M]
    assert deployed.trade_lv_idx == 0 and deployed.source_identity == SOURCE
    assert deployed.thresholds == {"candidate": 0.1, "entry": 0.2, "post": 0.3}
    assert deployed.chan_config["cbsp_strategy"] is CCustomStrategy
    assert deployed.chan_config["divergence_rate"] == float("inf")
    assert deployed.chan_config["mean_metrics"] == [5, 20, 60]
    assert canonical_bytes(json.loads(path.read_bytes())) == path.read_bytes()


def test_deployment_is_write_once_and_existing_bytes_are_untouched(deployment_model, tmp_path):
    path = tmp_path / "deployment.json"
    publish(path, deployment_model["model"])
    before = path.read_bytes()
    with pytest.raises(CChanException):
        publish(path, deployment_model["model"])
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["deployment.json"]


@pytest.mark.parametrize("value", [None, True, float("nan"), -0.1, 1.1])
def test_bad_deployment_threshold_does_not_create_any_output(deployment_model, tmp_path, value):
    from Trade.Script.Deployment import publish_deployment
    with pytest.raises(CChanException):
        publish_deployment(tmp_path / "deployment.json", deployment_model["model"].GetModelPath(),
                           candidate_score=value, entry_score=0.2, post_score=0.3)
    assert list(tmp_path.iterdir()) == []


def test_deployment_reader_rejects_noncanonical_or_drifted_identity(deployment_model, tmp_path):
    from Trade.Script.Deployment import CDeployment
    path = tmp_path / "deployment.json"
    publish(path, deployment_model["model"])
    original = path.read_bytes()
    path.write_bytes(original + b"\n")
    with pytest.raises(CChanException):
        CDeployment(path)
    record = json.loads(original)
    record["thresholds"]["entry"] = 0.9
    path.write_bytes(canonical_bytes(record))
    with pytest.raises(CChanException):
        CDeployment(path)


def test_deployment_rejects_runtime_config_or_market_override(deployment_model, tmp_path):
    from Trade.Script.Deployment import CDeployment
    path = tmp_path / "deployment.json"
    publish(path, deployment_model["model"])
    deployed = CDeployment(path)
    with pytest.raises(CChanException):
        deployed.check_overrides({"mean_metrics": [1]})
    deployed.check_overrides({"mean_metrics": [5, 20, 60]})
    with pytest.raises(CChanException):
        deployed.check_source({**SOURCE, "exchange": "okx"})


def test_closed_prefix_loader_does_not_publish_after_its_cutoff(deployment_model, tmp_path):
    from Trade.Script.Deployment import CDeployment
    path = tmp_path / "deployment.json"
    publish(path, deployment_model["model"])
    deployed = CDeployment(path)
    at = START + 701 * HOUR + HOUR // 2
    chan = deployed.build_chan(CODE, at)
    assert chan[0][-1][-1].close_ms == START + 701 * HOUR
    assert all(k.close_ms <= at for k in chan[0].klu_iter())
    with pytest.raises(CChanException, match="窗口|训练|可用"):
        deployed.build_chan(CODE, START + 50 * HOUR)


def test_real_candidate_score_has_shared_model_and_complete_feature_evidence(deployment_model, tmp_path):
    from ChanModel.FeatureEngine import CFeatureEngine
    from CustomBuySellPoint.CustomBSP import CCustomBSP
    from Trade.Script.Deployment import CDeployment
    path = tmp_path / "deployment.json"
    publish(path, deployment_model["model"])
    deployed = CDeployment(path)
    # 单一前向喂入寻找真实的未来信号，不遍历/挑收益，也不重用训练后的终局结构。
    chan, chosen = future_candidate(deployment_model)
    at = chosen.sig_klu.close_ms
    snapshot = deployed.prepare_signal(chan, chosen, observed_ms=at)
    assert snapshot["model_artifact_id"] == deployed.model.artifact_id
    assert snapshot["deployment_id"] == deployed.deployment_id
    assert snapshot["phase"] == "candidate" and snapshot["feature_available_at_ms"] <= at
    assert snapshot["features"]
    assert chosen.model_artifact_id == deployed.model.artifact_id
    assert chosen.deployment_id == deployed.deployment_id
    pseudo = CCustomBSP(chosen.bsp, chosen.sig_klu, chosen.bs_type, chosen.is_buy,
                       target_klc=chosen.target_klc, price=chosen.open_thred, sl_price=chosen.sl_thred,
                       is_segbsp=chosen.is_segbsp)
    pseudo.add_feat(CFeatureEngine.cal_features(chan, 0, pseudo))
    assert snapshot["features"] == dict(pseudo.features.items())
    assert chosen.score == deployed.model.predict(pseudo)
    published = chan[0].cbsp_strategy.publish_signals(chan, 0, signals=[chosen])
    assert published == [chosen]
    from CustomBuySellPoint.Decision import read_decision
    body = read_decision(chosen.decision)["payload"]
    assert body["assessment"] == snapshot
    assert body["origin"] is not None


def test_configured_scripts_load_one_bound_model_and_refuse_drift(deployment_model, tmp_path, monkeypatch):
    from Trade.Script.StaticsChanConfig import get_statics_chan_config, get_trade_conf
    path = tmp_path / "deployment.json"
    identity = publish(path, deployment_model["model"])
    monkeypatch.setitem(CEnv.get_instance().conf["trade"], "deployment_manifest", str(path))
    conf = get_statics_chan_config()
    assert conf["model"].artifact_id == deployment_model["model"].artifact_id
    assert get_trade_conf()["deployment_id"] == identity
    with pytest.raises(CChanException):
        get_statics_chan_config({"mean_metrics": [1]})


def test_configured_missing_deployment_never_falls_back_to_unscored_defaults(deployment_model, monkeypatch):
    from Trade.Script.StaticsChanConfig import get_statics_chan_config
    monkeypatch.setitem(CEnv.get_instance().conf["trade"], "deployment_manifest", "missing-deployment.json")
    with pytest.raises(CChanException):
        get_statics_chan_config()


def test_signal_db_and_acquired_intent_preserve_the_same_artifact(deployment_model, tmp_path):
    from Trade.Script.Deployment import CDeployment
    from Trade.db_util import CChanDB
    from Trade.CCXTTradeEngine import CCCXTTradeEngine
    from Trade.OpenQuotaGen import CBenchPriceQuotaGen
    path = tmp_path / "deployment.json"
    publish(path, deployment_model["model"])
    deployed = CDeployment(path)
    chan, signal = future_candidate(deployment_model)
    deployed.prepare_signal(chan, signal, observed_ms=signal.sig_klu.close_ms)
    chan[0].cbsp_strategy.publish_signals(chan, 0, signals=[signal])
    db = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path / "trade.db")})
    try:
        sid = db.add_signal(signal)
        rec = db.get_record(sid)
        assert rec["model_version"] == deployed.model.artifact_id
        assert rec["deployment_id"] == deployed.deployment_id
        assert rec["signal_decision"] == signal.decision.decode("utf-8")
        # 绑定模型的信号不能绕过 entry 评分直接发给引擎。
        engine = CCCXTTradeEngine(db, quota_gen=CBenchPriceQuotaGen(100.0), push_msg=False)
        with pytest.raises(CChanException, match="评分|部署|entry"):
            engine.add_trade(rec, signal.open_thred * (1.001 if signal.is_buy else 0.999))
        assert db.get_record(sid)["status"] == "signal"
    finally:
        db.close()


def test_signal_monitor_uses_bound_candidate_scoring_and_persists_frozen_bytes(deployment_model, tmp_path, monkeypatch):
    from Trade.Script import SignalMonitor as monitor
    from Trade.Script.Deployment import CDeployment
    from Trade.db_util import CChanDB
    path = tmp_path / "deployment.json"
    publish(path, deployment_model["model"])
    deployed = CDeployment(path)
    chan, signal = future_candidate(deployment_model)
    monkeypatch.setattr(deployed, "build_chan", lambda code, at: chan)
    db = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path / "trade.db")})
    try:
        result = monitor.run_signal_monitor(db, deployment=deployed, now_ms=lambda: signal.sig_klu.close_ms, push=False)
        assert result["added"] > 0 and result["failed"] == 0
        row = db.get_watching_signals(CODE)[0]
        assert row["model_version"] == deployed.model.artifact_id
        assert row["deployment_id"] == deployed.deployment_id
        body = json.loads(row["signal_decision"])["payload"]
        assert body["assessment"]["phase"] == "candidate"
        assert body["assessment"]["score"] == row["model_score_before"]
    finally:
        db.close()


@pytest.mark.parametrize("entry_threshold,should_open", [(0.0, True), (1.0, False)])
def test_actual_breakout_reassesses_before_intent_and_binds_snapshot(deployment_model, tmp_path, entry_threshold, should_open):
    from Trade.Script.Deployment import CDeployment, publish_deployment
    from Trade.Script.MakeOpenTrade import make_open_trade
    from Trade.db_util import CChanDB
    from Trade.CCXTTradeEngine import CCCXTTradeEngine
    from Trade.OpenQuotaGen import CBenchPriceQuotaGen
    path = tmp_path / "deployment.json"
    # 固定 0/1 覆盖准入两侧，只测软件行为，不按收益挑阈值。
    publish_deployment(path, deployment_model["model"].GetModelPath(), candidate_score=0.0,
                       entry_score=entry_threshold, post_score=0.0)
    deployed = CDeployment(path)
    chan, signal = future_candidate(deployment_model)
    at = signal.sig_klu.close_ms
    deployed.prepare_signal(chan, signal, observed_ms=at)
    chan[0].cbsp_strategy.publish_signals(chan, 0, signals=[signal])
    database = tmp_path / "trade.db"
    db = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(database)})
    try:
        sid = db.add_signal(signal)
        engine = CCCXTTradeEngine(db, quota_gen=CBenchPriceQuotaGen(100.0), push_msg=False,
            ccxt_conf={"mode": "dry_run", "exchange": "binance", "default_type": "swap"})
        price = signal.open_thred * (1.001 if signal.is_buy else 0.999)
        opened = make_open_trade(db, engine, price_map={CODE: price}, deployment=deployed, now_ms=lambda: at+HOUR//4)
        rec = db.get_record(sid)
        if should_open:
            assert opened == [sid]
            snapshot = json.loads(rec["snapshot_before"])
            assert snapshot["entry_assessment"]["phase"] == "entry"
            assert snapshot["entry_assessment"]["decision_ms"] == at+HOUR//4
            assert snapshot["entry_assessment"]["model_artifact_id"] == rec["model_version"] == deployed.model.artifact_id
            assert snapshot["entry_assessment"]["deployment_id"] == rec["deployment_id"] == deployed.deployment_id
            assert snapshot["entry_assessment"]["features_sha256"]
            assert json.loads(rec["signal_decision"])["payload"]["assessment"]["phase"] == "candidate"
            assert make_open_trade(db, engine, price_map={CODE: price}, deployment=deployed, now_ms=lambda: at+HOUR//4) == []
        else:
            assert opened == [] and rec["open_client_order_id"] is None
            assert not rec["watching"] and "score" in rec["unwatch_reason"]
    finally:
        db.close()
    if should_open:
        reopened = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(database)})
        try:
            assert reopened.get_record(sid)["snapshot_before"] == rec["snapshot_before"]
        finally:
            reopened.close()


@pytest.mark.parametrize("holds", [True, False])
def test_post_check_waits_for_the_entry_period_not_the_latest_database_row(deployment_model, tmp_path, monkeypatch, holds):
    from Trade.Script.Deployment import CDeployment, publish_deployment
    from Trade.Script.MakeOpenTrade import make_open_trade
    from Trade.Script.CheckOpenScore import check_open_score
    from Trade.db_util import CChanDB
    from Trade.CCXTTradeEngine import CCCXTTradeEngine
    path = tmp_path / "deployment.json"
    publish_deployment(path, deployment_model["model"].GetModelPath(), candidate_score=0.0, entry_score=0.0, post_score=0.0)
    deployed = CDeployment(path)
    chan, signal = future_candidate(deployment_model)
    at = signal.sig_klu.close_ms
    deployed.prepare_signal(chan, signal, observed_ms=at)
    chan[0].cbsp_strategy.publish_signals(chan, 0, signals=[signal])
    db = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path / "trade.db")})
    original_row = None
    try:
        sid = db.add_signal(signal)
        engine = CCCXTTradeEngine(db, push_msg=False,
            ccxt_conf={"mode": "dry_run", "exchange": "binance", "default_type": "swap"})
        quote = signal.open_thred * (1.001 if signal.is_buy else 0.999)
        assert make_open_trade(db, engine, deployment=deployed, price_map={CODE: quote}, now_ms=lambda: at+HOUR//4) == [sid]
        # 即使全库有许多更晚行，也不能在该交易 1h 周期尚未结束时后验。
        with CKLineDB(str(deployment_model["root"] / "kline.db")) as market:
            original_row = market.query_klines(CODE, KL_TYPE.K_60M, at, at+1)[0]
            market.conn.execute("DELETE FROM kline WHERE symbol=? AND lv=? AND ts=?", (CODE, "K_60M", at))
            market.conn.commit()
        assert check_open_score(db, now_ms=lambda: at+HOUR-1) == []
        assert db.get_record(sid)["snapshot_after"] is None
        with CKLineDB(str(deployment_model["root"] / "kline.db")) as market:
            direction = 1 if signal.is_buy == holds else -1
            close = signal.open_thred * (1 + direction*0.01)
            o = original_row[1]
            modified = (at, o, max(original_row[2], close), min(original_row[3], close), close, original_row[5])
            market.upsert_klines(CODE, KL_TYPE.K_60M, [modified])
        # 全局配置故意列 4h 在前，记录中的实际 1h 级别仍必须优先。
        monkeypatch.setitem(CEnv.get_instance().conf["trade"], "lv_list", ["K_4H", "K_60M", "K_15M"])
        errors = check_open_score(db, now_ms=lambda: at+2*HOUR)
        rec = db.get_record(sid)
        after = json.loads(rec["snapshot_after"])
        assert after["bar"]["open_ms"] == at and after["bar"]["close_ms"] == at+HOUR
        assert after["model_artifact_id"] == rec["model_version"] == deployed.model.artifact_id
        assert after["deployment_id"] == rec["deployment_id"] == deployed.deployment_id
        assert after["timing_basis"] == "entry_observation"
        if holds:
            assert errors == [] and after["status"] == "passed"
            assert after["assessment"]["phase"] == "post"
            assert rec["model_score_after"] == after["assessment"]["score"]
        else:
            assert errors == [sid] and rec["open_err"]
        before = rec["snapshot_after"]
        check_open_score(db, now_ms=lambda: at+500*HOUR)
        assert db.get_record(sid)["snapshot_after"] == before
    finally:
        if original_row is not None:
            with CKLineDB(str(deployment_model["root"] / "kline.db")) as market:
                market.upsert_klines(CODE, KL_TYPE.K_60M, [original_row])
        db.close()


@pytest.mark.parametrize("field,value", [("is_buy", True), ("bs_type", "changed"), ("open_thred", 1.0)])
def test_mutating_frozen_signal_fields_is_rejected_before_insert(deployment_model, tmp_path, field, value):
    from Trade.Script.Deployment import CDeployment
    from Trade.db_util import CChanDB
    path = tmp_path / "deployment.json"
    publish(path, deployment_model["model"])
    deployed = CDeployment(path)
    chan, signal = future_candidate(deployment_model)
    deployed.prepare_signal(chan, signal, observed_ms=signal.sig_klu.close_ms)
    chan[0].cbsp_strategy.publish_signals(chan, 0, signals=[signal])
    setattr(signal, field, not signal.is_buy if field == "is_buy" else value)
    db = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path / "trade.db")})
    try:
        with pytest.raises(CChanException):
            db.add_signal(signal)
        assert db.get_watching_signals() == []
    finally:
        db.close()


def test_mysql_legacy_insert_does_not_require_unverified_new_columns():
    from Trade.db_util import CChanDB
    from .test_m6_trade import make_signal
    calls = []
    class CLegacySQL:
        def query_one(self, *args):
            return None

        def execute(self, sql, args):
            calls.append(sql)
            return 1
    db = CChanDB.__new__(CChanDB)
    db.db_type, db.table, db.db = "mysql", "chan_trade", CLegacySQL()
    assert db.add_signal(make_signal()) == 1
    assert "deployment_id" not in calls[0] and "signal_decision" not in calls[0]


@pytest.mark.parametrize("at,level,start", [
    ("2024-02-29T23:59:59+00:00", KL_TYPE.K_MON, "2024-02-01T00:00:00+00:00"),
    ("2024-03-01T00:00:00+00:00", KL_TYPE.K_MON, "2024-03-01T00:00:00+00:00"),
    ("2024-01-07T23:59:59+00:00", KL_TYPE.K_WEEK, "2024-01-01T00:00:00+00:00"),
    ("2024-01-08T00:00:00+00:00", KL_TYPE.K_WEEK, "2024-01-08T00:00:00+00:00"),
    ("2024-02-29T03:59:59+00:00", KL_TYPE.K_4H, "2024-02-29T00:00:00+00:00"),
    ("2024-02-29T04:00:00+00:00", KL_TYPE.K_4H, "2024-02-29T04:00:00+00:00"),
])
def test_entry_observation_period_is_utc_calendar_aligned(at, level, start):
    from datetime import datetime
    from Common.KLineTime import containing_bar_open_ms
    assert containing_bar_open_ms(int(datetime.fromisoformat(at).timestamp()*1000), level) == int(datetime.fromisoformat(start).timestamp()*1000)


@pytest.mark.parametrize("field,value", [("feature_available_at_ms", -1), ("observed_price", 0), ("bar", {})])
def test_malformed_score_context_cannot_be_accepted(deployment_model, tmp_path, field, value):
    from copy import deepcopy
    from Trade.Script.Deployment import CDeployment, validate_assessment
    path = tmp_path / "deployment.json"
    publish(path, deployment_model["model"])
    deployed = CDeployment(path)
    chan, signal = future_candidate(deployment_model)
    snapshot = deepcopy(deployed.prepare_signal(chan, signal, observed_ms=signal.sig_klu.close_ms))
    snapshot[field] = value
    with pytest.raises(CChanException):
        validate_assessment(snapshot, phase="candidate", deployment_id=deployed.deployment_id,
                            model_artifact_id=deployed.model.artifact_id)


def test_three_level_deployment_uses_middle_period_and_same_closed_features(tmp_path, monkeypatch):
    from ChanConfig import CChanConfig
    from Common.KLineTime import make_crypto_klu
    from CustomBuySellPoint.MultiLevelStrategy import CMultiLevelStrategy
    from Trade.Script.Deployment import CDeployment, publish_deployment
    from .test_multilv import aggregate, gen_15m_bars, LV_LIST
    root = tmp_path
    config = root / "config.json"
    config.write_text(json.dumps({"offline_data": {"sqlite_path": str(root / "market.db"), "source_identity": SOURCE},
                                  "notify": {"backend": "none"}}))
    monkeypatch.setenv("CHANPY_CONFIG", str(config))
    CEnv.reset_instance()
    try:
        bars = gen_15m_bars(250)
        rows = {KL_TYPE.K_15M: bars, KL_TYPE.K_60M: aggregate(bars, 4), KL_TYPE.K_4H: aggregate(bars, 16)}
        cutoff = START+160*4*HOUR
        with CKLineDB(str(root / "market.db")) as market:
            market.bind_source(SOURCE)
            for level, data in rows.items():
                market.upsert_klines(CODE, level, [r for r in data if r[0] < cutoff])
        conf = {"cbsp_strategy": CMultiLevelStrategy, "divergence_rate": float("inf"), "min_zs_cnt": 0,
                "bs_type": "1,2,3a,1p,2s,3b", "kl_data_check": False,
                "strategy_para": {"require_sub_confirm": False}}
        result = run_backtest(CBacktestConfig([CODE], lv_list=LV_LIST, lv_idx=1, autype=AUTYPE.NONE,
            data_src="custom:OfflineDataAPI.CStockFileReader", chan_config=conf,
            primary_label="label_ret_N", label_para={"ret_n": 1, "ret_thred": 0}, output_dir=str(root / "samples")))
        model = CXGBTrainModelGenerator(model_tag="three-level", model_dir=str(root / "models"),
                                       folder_thred=0.6, num_boost_round=2)
        model.trainProcess(result.output_dir)
        with CKLineDB(str(root / "market.db")) as market:
            for level, data in rows.items():
                market.upsert_klines(CODE, level, [r for r in data if r[0] >= cutoff])
        path = root / "deployment.json"
        publish_deployment(path, model.GetModelPath(), candidate_score=0, entry_score=0, post_score=0)
        deployed = CDeployment(path)
        assert deployed.trade_lv_idx == 1 and deployed.lv_list == LV_LIST
        online = CChan(CODE, lv_list=LV_LIST, config=CChanConfig({**conf, "trigger_step": True}))
        chosen = None
        for i, row in enumerate(rows[KL_TYPE.K_4H]):
            batch = {KL_TYPE.K_4H: [row], KL_TYPE.K_60M: rows[KL_TYPE.K_60M][i*4:(i+1)*4],
                     KL_TYPE.K_15M: rows[KL_TYPE.K_15M][i*16:(i+1)*16]}
            units = {}
            for level, data in batch.items():
                units[level] = [make_crypto_klu(r, level) for r in data]
                for unit in units[level]:
                    unit.source_identity = SOURCE
            online.trigger_load(units)
            if i >= 160:
                candidates = online[1].cbsp_strategy.bsp_signal(online, 1)
                if candidates:
                    chosen = candidates[0]
                    break
        assert chosen is not None, "固定 fixture 需要训练窗口后的真实三级候选"
        at = chosen.sig_klu.close_ms
        scored = deployed.prepare_signal(online, chosen, observed_ms=at)
        offline = deployed.build_chan(CODE, at)
        counterpart = offline[1].cbsp_strategy.bsp_signal(offline, 1)[0]
        rebuilt = deployed.prepare_signal(offline, counterpart, observed_ms=at)
        assert canonical_bytes(scored) == canonical_bytes(rebuilt)
        assert scored["feature_available_at_ms"] <= at
        assert scored["bar"]["close_ms"] == at
    finally:
        CEnv.reset_instance()


@pytest.mark.parametrize("kind", ["lgbm", "mlp"])
def test_other_model_types_use_the_same_real_deployment_scores(deployment_model, tmp_path, kind):
    from .test_model_deployment_contract import model_factory
    from Trade.Script.Deployment import CDeployment, publish_deployment
    from Trade.db_util import CChanDB
    gen = model_factory(kind, tmp_path / "models")
    gen.folder_thred = 0.6
    gen.trainProcess(str(deployment_model["root"] / "samples"))
    path = tmp_path / "deployment.json"
    publish_deployment(path, gen.GetModelPath(), candidate_score=0, entry_score=0, post_score=0)
    deployed = CDeployment(path)
    chan, signal = future_candidate(deployment_model)
    at = signal.sig_klu.close_ms
    scored = deployed.prepare_signal(chan, signal, observed_ms=at)
    chan[0].cbsp_strategy.publish_signals(chan, 0, signals=[signal])
    db = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path / "trade.db")})
    try:
        rec = db.get_record(db.add_signal(signal))
        entry = deployed.assess_entry(rec, signal.open_thred, observed_ms=at+HOUR//4)
        assert scored["model_artifact_id"] == entry["model_artifact_id"] == rec["model_version"] == gen.artifact_id
        assert scored["deployment_id"] == entry["deployment_id"] == rec["deployment_id"]
        assert entry["score"] == gen.predict_features(entry["features"])
    finally:
        db.close()


def test_configured_cycle_uses_real_deployment_scope_and_blocks_a_corrupt_model(deployment_model, tmp_path):
    import shutil
    from Trade.Script.Deployment import publish_deployment
    from Trade.Script.RunTradeCycle import run_trade_cycle
    original = Path(deployment_model["model"].GetModelPath())
    copied = tmp_path/"model-copy"
    shutil.copytree(original.parent, copied)
    model = copied/original.name
    manifest = tmp_path/"deployment.json"
    identity = publish_deployment(manifest, model, candidate_score=0, entry_score=0, post_score=0)
    config = {"db": {"type": "sqlite", "sqlite_path": str(tmp_path/"trade.db")},
        "ccxt": {"mode": "dry_run", "exchange": "binance", "default_type": "swap"},
        "trade": {"deployment_manifest": str(manifest)},
        "offline_data": {"sqlite_path": str(deployment_model["root"]/"kline.db"), "source_identity": SOURCE}}
    path = tmp_path/"runtime.json"
    path.write_text(json.dumps(config))
    calls = []
    def command(module, args, **kwargs):
        calls.append((module, args))
        return 0
    now = deployment_model["rows"][-1][0]+HOUR
    result = run_trade_cycle(path, report_path=tmp_path/"good.jsonl", command=command, now_ms=lambda: now)
    assert result["status"] == "completed"
    assert result["scope"]["deployment_id"] == identity
    assert result["scope"]["model_artifact_id"] == deployment_model["model"].artifact_id
    assert result["scope"]["code_list"] == [CODE] and result["scope"]["lv_list"] == ["K_60M"]
    assert ("OfflineData.ccxt_update", [CODE, "K_60M"]) in calls
    model.write_bytes(model.read_bytes()+b"broken")
    calls.clear()
    failed = run_trade_cycle(path, report_path=tmp_path/"bad.jsonl", command=command, now_ms=lambda: now)
    assert failed["reason"] == "scope_or_model_unavailable"
    assert not any(module in {"OfflineData.ccxt_update", "Trade.Script.SignalMonitor", "Trade.Script.MakeOpenTrade"}
                   for module, args in calls)
    assert len(calls) == 5  # restore plus all independent management attempts


@pytest.mark.parametrize("damage_after_intent", [False, True])
def test_real_model_opening_inputs_reach_intent_and_recheck_the_artifact_before_send(deployment_model, tmp_path, monkeypatch, damage_after_intent):
    import shutil
    from Trade.Script.Deployment import CDeployment, publish_deployment
    from Trade.Script.OpeningInputs import COpeningInputs
    from Trade.Script.MakeOpenTrade import make_open_trade
    from Trade.Script.OpenConfig import COpenConfig
    from Trade.CCXTTradeEngine import CCCXTTradeEngine
    from Trade.OpenQuotaGen import CBenchPriceQuotaGen
    from Trade.db_util import CChanDB
    original = Path(deployment_model["model"].GetModelPath())
    target = tmp_path/"models"
    shutil.copytree(original.parent, target)
    model = target/original.name
    manifest = tmp_path/"deployment.json"
    publish_deployment(manifest, model, candidate_score=0, entry_score=0, post_score=0)
    deployed = CDeployment(manifest)
    chan, signal = future_candidate(deployment_model)
    now = signal.sig_klu.close_ms+HOUR//4
    assert deployed.prepare_signal(chan, signal, observed_ms=now)["passed"]
    chan[0].cbsp_strategy.publish_signals(chan, 0, signals=[signal])
    path = tmp_path/"runtime.json"
    conf = {"db": {"type": "sqlite", "sqlite_path": str(tmp_path/"trade.db")},
        "ccxt": {"mode": "dry_run", "exchange": "binance", "default_type": "swap"},
        "trade": {"deployment_manifest": str(manifest)}, "notify": {"backend": "none"},
        "offline_data": {"sqlite_path": str(deployment_model["root"]/"kline.db"), "source_identity": SOURCE}}
    path.write_text(json.dumps(conf))
    monkeypatch.setenv("CHANPY_CONFIG", str(path))
    CEnv.reset_instance()
    guard = COpeningInputs(path, now_ms=lambda: now)
    from Common.MarketQuote import make_quote_batch
    price = signal.open_thred*(1.001 if signal.is_buy else 0.999)
    guard.bind_quotes(make_quote_batch([{"symbol": CODE, "price": price, "timestamp_ms": now}],
        source=SOURCE, started_ms=now, finished_ms=now), max_age_ms=1000)
    open_path = tmp_path/"open.json"
    open_path.write_text("{}")
    db = CChanDB(db_conf=conf["db"])
    try:
        key = db.add_signal(signal)
        engine = CCCXTTradeEngine(db, ccxt_conf=conf["ccxt"], trade_conf=conf["trade"],
            quota_gen=CBenchPriceQuotaGen(10), opening_inputs=guard, push_msg=False)
        engine.api_interval = 0
        if damage_after_intent:
            monkeypatch.setattr(engine, "rate_limit", lambda: model.write_bytes(model.read_bytes()+b"changed"))
        failures = []
        opened = make_open_trade(db, engine, COpenConfig(str(open_path)), deployment=deployed,
            now_ms=lambda: now, price_map={CODE: price}, failures=failures)
        record = db.get_record(key)
        assert record["open_attempt"] == 1
        stamp = json.loads(record["snapshot_before"])["opening_inputs"]
        assert stamp["inputs_sha256"] == guard.snapshot()["inputs_sha256"]
        assert db.get_order_history(key)["attempts"][0]["identity"]["opening_inputs"] == stamp
        if damage_after_intent:
            assert opened == [] and failures and engine.sim_state.orders == {}
            assert record["open_order_status"] == "created" and record["current_qty"] == 0
        else:
            assert opened == [key] and failures == [] and record["current_qty"] > 0
        assert engine.exchange is None
    finally:
        db.close()
        CEnv.reset_instance()
