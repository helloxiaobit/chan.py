"""有界样本与模型/账户训练入口；只用显式合成数据包，无网络/真实配置。"""
import json
from datetime import datetime, timezone

import pytest

from Chan import CChan
from Common.CEnum import AUTYPE, KL_TYPE
from Common.ChanException import CChanException
from CustomBuySellPoint.CustomStrategy import CCustomStrategy
from ModelStrategy.BacktestChanConfig import CBacktestConfig
from ModelStrategy.backtest import run_backtest
from .test_crypto_evaluation_binding import raw_fixture, dataset, configuration
from .test_crypto_account_contract import CODE
from .test_decision_snapshots import START, HOUR


def utc_string(at):
    return datetime.fromtimestamp(at/1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def sample_config(output, *, end=START+600*HOUR):
    return CBacktestConfig([CODE], begin_time=utc_string(START), end_time=utc_string(end),
        data_src="explicit-crypto-evaluation-packet", lv_list=[KL_TYPE.K_60M], lv_idx=0, autype=AUTYPE.NONE,
        chan_config={"cbsp_strategy": CCustomStrategy, "divergence_rate": float("inf"), "min_zs_cnt": 0,
                     "bs_type": "1,2,3a,1p,2s,3b", "kl_data_check": True},
        output_dir=str(output), primary_label="label_ret_N", label_para={"ret_n": 1})


def test_packet_samples_use_actual_raw_prefix_without_default_reader(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("显式数据包路径不得查默认行情环境/API")
    monkeypatch.setattr(CChan, "GetStockAPI", forbidden)
    result = run_backtest(sample_config(tmp_path / "samples"), source_data=dataset(*raw_fixture()))
    assert result.samples
    manifest = json.loads((tmp_path / "samples" / "sample_manifest.json").read_bytes())
    context = manifest["generation_context"]
    assert context["source_identities"][CODE]["K_60M"]["market_type"] == "swap"
    assert context["input_manifests"][CODE]["K_60M"]["count"] == 599
    info = [json.loads(line) for line in (tmp_path / "samples" / "sample_info.jsonl").read_bytes().splitlines()]
    assert all(r["decision_ms"] < START+600*HOUR for r in info)
    assert all(r["label_end_ms"] is None or r["label_end_ms"] < START+600*HOUR for r in info)


def test_training_packet_future_suffix_does_not_change_sample_or_model_inputs(tmp_path):
    rows, marks, funding = raw_fixture()
    first = run_backtest(sample_config(tmp_path / "first"), source_data=dataset(rows, marks, funding))
    end = START+600*HOUR
    changed = [r if r[0]+HOUR < end else (r[0], r[1], r[2]*1.02, r[3]*0.98, r[4], r[5]) for r in rows]
    second = run_backtest(sample_config(tmp_path / "second"), source_data=dataset(changed, marks, funding))
    for name in ("feature.libsvm", "feature.meta", "sample_info.jsonl", "sample_manifest.json"):
        assert (tmp_path/"first"/name).read_bytes() == (tmp_path/"second"/name).read_bytes()
    assert first.feature_meta == second.feature_meta


def test_packet_samples_need_explicit_bounds_and_matching_symbols(tmp_path):
    source = dataset(*raw_fixture())
    conf = sample_config(tmp_path / "samples")
    conf.end_time = None
    with pytest.raises(CChanException):
        run_backtest(conf, source_data=source)
    conf = sample_config(tmp_path / "samples")
    conf.code_list = ["OTHER/USDT:USDT"]
    with pytest.raises(CChanException):
        run_backtest(conf, source_data=source)
    assert list(tmp_path.iterdir()) == []


def pipeline_options(kind="xgb"):
    options = {"folder_thred": 0.6, "num_boost_round": 2}
    if kind == "mlp":
        options = {"folder_thred": 0.6, "mlp_params": {"hidden_layer_sizes": [2], "max_iter": 60, "random_state": 7}}
    return {"training_window": (START, START+600*HOUR), "search_window": (START+600*HOUR, START+800*HOUR),
        "validation_windows": [(START+800*HOUR, START+1000*HOUR)], "primary_label": "label_ret_N",
        "label_parameters": {"ret_n": 1}, "model_type": kind, "model_options": options,
        "thresholds": {"candidate": 0.0, "entry": 0.0, "post": 0.0},
        "space": {"entry_notional": {"type": "choice", "choices": [10.0, 20.0]}},
        "objective": "total_return", "n_trials": 2, "algorithm": "grid", "seed": 7}


@pytest.mark.parametrize("kind", ["xgb", "lgbm", "mlp"])
def test_actual_training_artifact_deployment_and_account_windows_share_one_identity(tmp_path, kind):
    from ModelStrategy.training_pipeline import run_crypto_training_pipeline, verify_crypto_training_pipeline
    from Trade.Script.Deployment import CDeployment
    source, config = dataset(*raw_fixture()), configuration()
    root = tmp_path / "pipeline"
    receipt = run_crypto_training_pipeline(source, config, output_dir=root, **pipeline_options(kind))
    deployed = CDeployment(root / "deployment.json")
    assert receipt["status"] == "offline_training_and_window_checks_passed"
    assert receipt["candidate_authorized"] is False
    assert receipt["model_artifact_id"] == deployed.model.artifact_id
    assert receipt["deployment_id"] == deployed.deployment_id
    assert deployed.model.contract["training_window"]["last_label_end_ms"] < START+600*HOUR
    proposal = json.loads((root / "experiment" / "proposal.json").read_bytes())
    assert proposal["model"]["artifact_id"] == deployed.model.artifact_id
    assert proposal["model"]["feature_meta"] == deployed.model.contract["feature_meta"]
    assert receipt["thresholds"]["entry"] == deployed.thresholds["entry"]
    assert verify_crypto_training_pipeline(root, source) == receipt
    # 独立目录移动后仍能重读和 replay，不能引用已经删除的 staging 绝对路径。
    moved = tmp_path / "moved"
    root.rename(moved)
    assert verify_crypto_training_pipeline(moved, source) == receipt


@pytest.mark.parametrize("bad", ["overlap", "model_dir", "missing_threshold", "existing"])
def test_training_preflight_refuses_bad_spec_or_existing_output_without_mutating_it(tmp_path, bad):
    from ModelStrategy.training_pipeline import run_crypto_training_pipeline
    source, config = dataset(*raw_fixture()), configuration()
    opts = pipeline_options()
    root = tmp_path / "pipeline"
    if bad == "overlap":
        opts["search_window"] = (START+500*HOUR, START+800*HOUR)
    elif bad == "model_dir":
        opts["model_options"]["model_dir"] = str(tmp_path / "outside")
    elif bad == "missing_threshold":
        del opts["thresholds"]["post"]
    else:
        root.mkdir()
        (root/"preserve").write_bytes(b"user bytes")
    with pytest.raises(CChanException):
        run_crypto_training_pipeline(source, config, output_dir=root, **opts)
    assert not (tmp_path/"outside").exists()
    assert list(tmp_path.iterdir()) == ([] if bad != "existing" else [root])
    if bad == "existing":
        assert (root/"preserve").read_bytes() == b"user bytes"


def test_training_failure_cannot_publish_old_model_or_new_deployment(tmp_path, monkeypatch):
    from ModelStrategy.training_pipeline import run_crypto_training_pipeline
    from ModelStrategy.models.Xgboost.XGBTrainModelGenerator import CXGBTrainModelGenerator
    def failure(*args, **kwargs):
        raise CChanException("synthetic training failure", 0)
    monkeypatch.setattr(CXGBTrainModelGenerator, "train", failure)
    with pytest.raises(CChanException):
        run_crypto_training_pipeline(dataset(*raw_fixture()), configuration(), output_dir=tmp_path/"pipeline", **pipeline_options())
    assert list(tmp_path.iterdir()) == []


def test_packet_export_roundtrip_preserves_actual_view_and_rejects_unknown_schema():
    from ModelStrategy.parameterEvaluate.crypto_evaluate import CCryptoEvaluationData
    source = dataset(*raw_fixture())
    packet = source.to_dict()
    restored = CCryptoEvaluationData.from_dict(packet)
    assert restored.view(start_ms=START, end_ms=START+600*HOUR) == source.view(start_ms=START, end_ms=START+600*HOUR)
    packet["schema"] = "unknown"
    with pytest.raises(CChanException):
        CCryptoEvaluationData.from_dict(packet)


def test_cli_drives_the_real_pipeline_and_returns_nonzero_for_a_bad_spec(tmp_path):
    import subprocess
    import sys
    from CustomBuySellPoint.Decision import canonical_bytes
    source = dataset(*raw_fixture())
    (tmp_path/"packet.json").write_bytes(canonical_bytes(source.to_dict()))
    spec = {"schema": "chan-crypto-training-cli-v1", "data_packet": "packet.json", "output_dir": "output",
            "configuration": configuration().to_dict(), "training": pipeline_options()}
    spec_path = tmp_path/"spec.json"
    spec_path.write_bytes(canonical_bytes(spec))
    result = subprocess.run([sys.executable, "-m", "ModelStrategy.training_pipeline", "--spec", str(spec_path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path/"output"/"receipt.json").is_file(), result.stdout
    spec["output_dir"] = "failed-output"
    spec["training"]["search_window"] = [START+500*HOUR, START+800*HOUR]
    spec_path.write_bytes(canonical_bytes(spec))
    failed = subprocess.run([sys.executable, "-m", "ModelStrategy.training_pipeline", "--spec", str(spec_path)],
                            capture_output=True, text=True)
    assert failed.returncode != 0
    assert not (tmp_path/"failed-output").exists()


def test_powershell_training_wrapper_runs_only_one_checked_pipeline_command(tmp_path):
    import os
    import shutil
    import subprocess
    from pathlib import Path
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell unavailable; no wrapper claim")
    fake = tmp_path/"fake"
    fake.mkdir()
    log = tmp_path/"calls.log"
    (fake/"python.cmd").write_text(f'@echo off\r\necho invoked>>"{log}"\r\nexit /b 37\r\n')
    spec = tmp_path/"spec.json"
    spec.write_text("{}")
    command = Path(__file__).resolve().parents[1]/"Trade"/"Script"/"run_train_pipeline.ps1"
    env = {**os.environ, "PATH": str(fake)+os.pathsep+os.environ["PATH"]}
    result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-File", str(command), str(spec)],
                            capture_output=True, text=True, env=env)
    assert result.returncode == 37, result.stderr
    assert len(log.read_text().splitlines()) == 1


def test_bash_training_wrapper_propagates_a_single_failed_python_command(tmp_path):
    import os
    import subprocess
    from pathlib import Path
    bash = Path("C:/Program Files/Git/bin/bash.exe")
    if not bash.is_file():
        pytest.skip("Git Bash unavailable; no shell wrapper claim")
    fake = tmp_path/"fake"
    fake.mkdir()
    log = tmp_path/"calls.log"
    argv_log = tmp_path/"argv.log"
    (fake/"python").write_bytes(f'#!/bin/bash\necho invoked >> "{log.as_posix()}"\nprintf "%s\\n" "$@" > "{argv_log.as_posix()}"\nexit 37\n'.encode())
    (fake/"python").chmod(0o755)
    spec = tmp_path/"spec.json"
    spec.write_text("{}")
    script = Path(__file__).resolve().parents[1]/"Trade"/"Script"/"run_train_pipeline.sh"
    env = {**os.environ, "PATH": str(fake)+os.pathsep+os.environ["PATH"]}
    result = subprocess.run([str(bash), str(script), str(spec)], capture_output=True, text=True, env=env)
    assert result.returncode == 37, result.stderr
    assert len(log.read_text().splitlines()) == 1
    assert argv_log.read_text().splitlines()[-1] == str(spec)


@pytest.fixture(scope="module")
def published_pipeline(tmp_path_factory):
    from ModelStrategy.training_pipeline import run_crypto_training_pipeline
    source, config = dataset(*raw_fixture()), configuration()
    root = tmp_path_factory.mktemp("published-pipeline")/"run"
    receipt = run_crypto_training_pipeline(source, config, output_dir=root, **pipeline_options())
    return root, source, receipt


@pytest.mark.parametrize("field", ["training_window", "model_type", "primary_label", "experiment_window", "thresholds"])
def test_rehashed_pipeline_spec_cannot_relabel_the_actual_training_or_experiment(tmp_path, published_pipeline, field):
    import copy
    import hashlib
    import shutil
    from CustomBuySellPoint.Decision import canonical_bytes
    from ModelStrategy.training_pipeline import verify_crypto_training_pipeline
    original, source, record = published_pipeline
    root = tmp_path/"copy"
    shutil.copytree(original, root)
    receipt = copy.deepcopy(record)
    spec = receipt["spec"]
    if field == "training_window":
        spec["training_window"][1] -= HOUR
    elif field == "experiment_window":
        spec["search_window"][0] += HOUR
    elif field == "model_type":
        spec["model_type"] = "lgbm"
    elif field == "primary_label":
        spec["primary_label"] = "label_next_bsp"
    else:
        spec["thresholds"]["candidate"] = 0.9
    receipt["inputs"] = [source.view(start_ms=a, end_ms=b)["manifest"]
        for a, b in [spec["training_window"], spec["search_window"]]+spec["validation_windows"]]
    receipt["spec_sha256"] = hashlib.sha256(canonical_bytes(spec)).hexdigest()
    receipt["pipeline_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in receipt.items() if k != "pipeline_id"})).hexdigest()
    (root/"receipt.json").write_bytes(canonical_bytes(receipt))
    with pytest.raises(CChanException):
        verify_crypto_training_pipeline(root, source)


@pytest.mark.parametrize("field,value", [("num_boost_round", 0), ("num_boost_round", True), ("folder_thred", 1.0)])
def test_invalid_model_budget_or_split_is_refused_before_sample_generation(tmp_path, monkeypatch, field, value):
    from ModelStrategy import training_pipeline as pipeline
    def no_generation(*args, **kwargs):
        raise AssertionError("invalid model budget must fail before sample generation")
    monkeypatch.setattr(pipeline, "run_backtest", no_generation)
    opts = pipeline_options()
    opts["model_options"][field] = value
    with pytest.raises(CChanException):
        pipeline.run_crypto_training_pipeline(dataset(*raw_fixture()), configuration(), output_dir=tmp_path/"output", **opts)
    assert list(tmp_path.iterdir()) == []


def test_late_validation_failure_leaves_no_training_model_or_deployment_directory(tmp_path):
    from ModelStrategy.training_pipeline import run_crypto_training_pipeline
    opts = pipeline_options()
    opts["validation_windows"] = [(START+1000*HOUR-1, START+1000*HOUR)]
    with pytest.raises(CChanException, match="验证"):
        run_crypto_training_pipeline(dataset(*raw_fixture()), configuration(), output_dir=tmp_path/"failed", **opts)
    assert list(tmp_path.iterdir()) == []


def test_real_three_level_packet_training_keeps_middle_level_model_and_windows(tmp_path):
    from CustomBuySellPoint.MultiLevelStrategy import CMultiLevelStrategy
    from ModelStrategy.parameterEvaluate.crypto_evaluate import CCryptoEvaluationData, CCryptoEvaluationConfig
    from ModelStrategy.training_pipeline import run_crypto_training_pipeline, verify_crypto_training_pipeline
    from .test_multilv import aggregate, gen_15m_bars, LV_LIST
    from .test_crypto_evaluation_binding import SOURCE
    from .test_crypto_account_contract import conf
    bars = gen_15m_bars(250)
    source = CCryptoEvaluationData(contract_source=SOURCE, mark_source={**SOURCE, "price_type": "mark"},
        contract_rows={CODE: {KL_TYPE.K_4H: aggregate(bars, 16), KL_TYPE.K_60M: aggregate(bars, 4), KL_TYPE.K_15M: bars}},
        mark_rows={CODE: bars}, mark_level=KL_TYPE.K_15M, funding_rows={CODE: []}, funding_schedule_ms={CODE: []})
    config = CCryptoEvaluationConfig(lv_list=LV_LIST, trade_lv_idx=1, account=conf(), entry_notional="10",
        chan_config={"cbsp_strategy": CMultiLevelStrategy, "divergence_rate": float("inf"), "min_zs_cnt": 0,
                     "bs_type": "1,2,3a,1p,2s,3b", "kl_data_check": False,
                     "strategy_para": {"require_sub_confirm": False}})
    opts = pipeline_options()
    opts["label_parameters"] = {"ret_n": 1, "ret_thred": 0}
    receipt = run_crypto_training_pipeline(source, config, output_dir=tmp_path/"three-level", **opts)
    assert receipt["spec"]["configuration"]["trade_lv_idx"] == 1
    assert receipt["spec"]["configuration"]["lv_list"] == [lv.name for lv in LV_LIST]
    assert verify_crypto_training_pipeline(tmp_path/"three-level", source) == receipt
