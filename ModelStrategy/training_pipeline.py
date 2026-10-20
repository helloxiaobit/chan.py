"""有界来源样本→现有模型→不重叠账户窗口→只读部署清单；非实盘授权。"""
import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from ChanModel.GeneratorModel import CGeneratorModel
from ChanModel.ModelContract import freeze_config, feature_code_identity, sha256_file
from Common.CEnum import AUTYPE, KL_TYPE
from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.Script.Deployment import CDeployment, _restore, _thresholds, publish_deployment

from .BacktestChanConfig import CBacktestConfig
from .backtest import LABEL_SEMANTICS, run_backtest
from .ModelGenerator import load_sample_dir
from .parameterEvaluate.artifact import write_json_once
from .parameterEvaluate.account_experiment import _window, run_account_experiment, verify_account_experiment
from .parameterEvaluate.crypto_account import CCryptoAccountConfig
from .parameterEvaluate.crypto_evaluate import CCryptoEvaluationConfig, CCryptoEvaluationData
from .parameterEvaluate.para_automl import CParaAutoML, read_search_result


def _error(message):
    return CChanException(message, ErrCode.MODEL_ERROR)


def _sha(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _identity():
    return {"feature_code": feature_code_identity(),
            "pipeline_sha256": hashlib.sha256(Path(__file__).read_text(encoding="utf-8").replace("\r\n", "\n").encode()).hexdigest()}


def _model_factory(kind):
    if kind == "xgb":
        from .models.Xgboost.XGBTrainModelGenerator import CXGBTrainModelGenerator
        return CXGBTrainModelGenerator, {"xgb_params", "num_boost_round"}
    if kind == "lgbm":
        from .models.lightGBM.LGBMModelGenerator import CLGBMModelGenerator
        return CLGBMModelGenerator, {"lgbm_params", "num_boost_round"}
    if kind == "mlp":
        from .models.deepModel.MLPModelGenerator import CMLPModelGenerator
        return CMLPModelGenerator, {"mlp_params"}
    raise _error("必须显式选择已适配的 xgb/lgbm/mlp，不自动根据验证收益挑模型")


def _utc(value):
    if value % 1000:
        raise _error("训练 reader 起止需整数 UTC 秒，不能截断毫秒")
    return datetime.fromtimestamp(value/1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _configured(record):
    if set(record) != {"lv_list", "trade_lv_idx", "chan_config", "account", "entry_notional", "sizing_contract"}:
        raise _error("评估配置不完整")
    result = CCryptoEvaluationConfig(lv_list=[KL_TYPE[name] for name in record["lv_list"]],
        trade_lv_idx=record["trade_lv_idx"], chan_config=_restore(record["chan_config"]),
        account=CCryptoAccountConfig(**record["account"]), entry_notional=record["entry_notional"])
    if canonical_bytes(result.to_dict()) != canonical_bytes(record):
        raise _error("配置重读不一致")
    return result


def _inventory(root):
    return {p.relative_to(root).as_posix(): sha256_file(p) for p in sorted(root.rglob("*"))
            if p.is_file() and p != root/"receipt.json"}


def run_crypto_training_pipeline(data, config, *, training_window, search_window, validation_windows, primary_label,
        label_parameters, model_type, model_options, thresholds, space, objective, n_trials, algorithm, seed,
        output_dir, min_closed_positions=1, algorithm_parameters=None):
    destination = Path(output_dir).resolve()
    if destination.exists() or not destination.parent.is_dir() or config.chan_config.get("model") is not None:
        raise _error("训练必须从明确新目录和无旧模型配置开始，禁止旧产物续用或覆盖")
    factory, options = _model_factory(model_type)
    if (not isinstance(model_options, dict) or set(model_options)-(options|{"folder_thred", "split_boundaries_ms"})
            or not isinstance(label_parameters, dict) or not isinstance(primary_label, str) or not primary_label
            or not isinstance(validation_windows, (list, tuple)) or not validation_windows
            or not isinstance(space, dict) or set(space)-{"entry_notional", "score_thred"}
            or type(n_trials) is not int or n_trials <= 0):
        raise _error("模型/标签/搜索参数无效；模型后搜索仅允许实际准入阈值和名义额度")
    if ("num_boost_round" in model_options and (type(model_options["num_boost_round"]) is not int or model_options["num_boost_round"] <= 0)):
        raise _error("模型轮数必须是正整数，不能发布零轮或 bool 预算的模型")
    proportion = model_options.get("folder_thred")
    if proportion is not None and (type(proportion) not in (int, float) or not math.isfinite(proportion) or not 0 < proportion < 1):
        raise _error("模型训练切分比例必须严格在 0 和 1 之间")
    thresholds = _thresholds(thresholds)
    training, search = _window(training_window), _window(search_window)
    windows = [_window(w) for w in validation_windows]
    previous = training[1]
    for start, end in [search]+windows:
        if start < previous:
            raise _error("训练、搜索和验证窗口必须按顺序不重叠")
        previous = end
    _utc(training[0]), _utc(training[1])
    CParaAutoML(None, space, algo=algorithm, seed=seed)._validate_space()
    inputs = [data.view(start_ms=a, end_ms=b)["manifest"] for a, b in [training, search]+windows]
    spec = {"schema": "chan-crypto-training-spec-v1", "configuration": config.to_dict(), "training_window": training,
        "search_window": search, "validation_windows": windows, "primary_label": primary_label,
        "label_parameters": label_parameters, "model_type": model_type, "model_options": freeze_config(model_options),
        "thresholds": thresholds, "space": space, "objective": objective, "n_trials": n_trials,
        "algorithm": algorithm, "seed": seed, "min_closed_positions": min_closed_positions,
        "algorithm_parameters": algorithm_parameters or {}}
    canonical_bytes(spec)
    with tempfile.TemporaryDirectory(prefix=f".{destination.name}.building-", dir=destination.parent) as temporary:
        root = Path(temporary)/"run"
        root.mkdir()
        bt_config = CBacktestConfig(sorted(data.view(start_ms=training[0], end_ms=training[1])["contract"]),
            begin_time=_utc(training[0]), end_time=_utc(training[1]), data_src="explicit-crypto-evaluation-packet",
            lv_list=config.lv_list, lv_idx=config.trade_lv_idx, autype=AUTYPE.NONE, chan_config=config.chan_config,
            output_dir=str(root/"samples"), primary_label=primary_label, label_para=label_parameters)
        run_backtest(bt_config, source_data=data)
        generator = factory(model_tag="pipeline", model_dir=str(root/"model"), **copy.deepcopy(model_options))
        generator.trainProcess(str(root/"samples"))
        model = CGeneratorModel(generator.GetModelPath())
        if model.contract["training_window"]["last_label_end_ms"] >= training[1]:
            raise _error("训练标签越过固定训练窗口")
        trained = CCryptoEvaluationConfig(lv_list=config.lv_list, trade_lv_idx=config.trade_lv_idx,
            chan_config={**config.chan_config, "model": model, "score_thred": thresholds["entry"]},
            account=config.account, entry_notional=config.entry_notional)
        experiment = run_account_experiment(data, trained, search_window=search, validation_windows=windows,
            space=space, objective=objective, n_trials=n_trials, algorithm=algorithm, seed=seed,
            min_closed_positions=min_closed_positions, algorithm_parameters=algorithm_parameters,
            output_dir=root/"experiment")
        verify_account_experiment(root/"experiment", data, trained)
        proposal = json.loads((root/"experiment"/"proposal.json").read_bytes())
        selected_entry = proposal["configuration"]["chan_config"]["score_thred"]
        selected_thresholds = {**thresholds, "entry": selected_entry}
        deployed_id = publish_deployment(root/"deployment.json", model.path,
            candidate_score=selected_thresholds["candidate"], entry_score=selected_entry, post_score=selected_thresholds["post"])
        deployed = CDeployment(root/"deployment.json")
        if deployed.model.artifact_id != model.artifact_id or deployed.deployment_id != deployed_id:
            raise _error("部署清单重读身份漂移")
        receipt = {"schema": "chan-crypto-training-pipeline-v1", "status": "offline_training_and_window_checks_passed",
            "candidate_authorized": False, "spec": spec, "spec_sha256": _sha(spec), "inputs": inputs,
            "model_artifact_id": model.artifact_id, "deployment_id": deployed_id, "thresholds": selected_thresholds,
            "model_relative_path": Path(model.path).relative_to(root).as_posix(),
            "experiment_id": experiment["experiment_id"], "code": _identity(), "files_sha256": _inventory(root)}
        receipt["pipeline_id"] = _sha(receipt)
        write_json_once(root/"receipt.json", receipt)
        verify_crypto_training_pipeline(root, data)
        # Windows rename 不覆盖既有目录；新目标已显式核对，无 replace 或旧目录清理。
        root.rename(destination)
        return receipt


def verify_crypto_training_pipeline(path, data):
    """核对样本/模型/部署/所有实验账户及实际数据，不信任目录的成功名称。"""
    root = Path(path).resolve()
    try:
        raw = (root/"receipt.json").read_bytes()
        receipt = json.loads(raw)
        body = {k: v for k, v in receipt.items() if k != "pipeline_id"}
        if (canonical_bytes(receipt) != raw or receipt.get("schema") != "chan-crypto-training-pipeline-v1"
                or receipt.get("status") != "offline_training_and_window_checks_passed" or receipt.get("candidate_authorized") is not False
                or receipt["pipeline_id"] != _sha(body) or receipt["code"] != _identity()
                or receipt["files_sha256"] != _inventory(root) or receipt["spec_sha256"] != _sha(receipt["spec"])):
            raise _error("训练流水线收据、代码或制品库存漂移")
        spec = receipt["spec"]
        config = _configured(spec["configuration"])
        model_path = (root/receipt["model_relative_path"]).resolve()
        if not model_path.is_relative_to(root):
            raise _error("模型路径不能逃出该运行目录")
        model = CGeneratorModel(model_path)
        deployed = CDeployment(root/"deployment.json")
        if (model.artifact_id != receipt["model_artifact_id"] or deployed.model.path != model.path
                or deployed.deployment_id != receipt["deployment_id"] or deployed.thresholds != receipt["thresholds"]
                or model.contract["samples_manifest_sha256"] != sha256_file(root/"samples"/"sample_manifest.json")):
            raise _error("实际样本/模型/部署身份不一致")
        contract, generation = model.contract, model.contract["generation_context"]
        label_config = CBacktestConfig([], primary_label=spec["primary_label"], label_para=spec["label_parameters"])
        definition = {**LABEL_SEMANTICS, "primary_label": spec["primary_label"], "parameters": label_config.label_para}
        if (contract["model_type"] != spec["model_type"] or contract["label_definition"] != definition
                or generation["begin_time"] != _utc(spec["training_window"][0])
                or generation["end_time"] != _utc(spec["training_window"][1])
                or generation["chan_config"] != freeze_config(config.chan_config)
                or contract["training_window"]["last_label_end_ms"] >= spec["training_window"][1]):
            raise _error("声明的窗口/模型/标签/策略不等于实际训练 contract")
        meta, samples = load_sample_dir(str(root/"samples"))
        manifest = _read_json(root/"samples"/"sample_manifest.json")
        if (meta != contract["feature_meta"] or manifest["generation_context"] != generation
                or manifest["files"] != contract["sample_files"]):
            raise _error("实际样本/meta 与模型训练输入不一致")
        factory, _ = _model_factory(spec["model_type"])
        generator = factory(model_tag="pipeline", model_dir=str(root/"model"), **_restore(spec["model_options"]))
        actual_options = freeze_config({"params": getattr(generator, "xgb_params", getattr(generator, "lgbm_params", getattr(generator, "mlp_params", {}))),
            "num_boost_round": getattr(generator, "num_boost_round", None),
            "is_buy": generator.is_buy, "market": generator.market, "bsp_type": generator.bsp_type})
        generator.feature_meta = meta
        generator._freeze_split_boundaries(samples)
        generator.split_samples([s for s in samples if generator.filter_sample(s)])
        if (actual_options != contract["generator_config"] or generator.training_boundaries != contract["split_boundaries_ms"]
                or generator.split_counts != contract["split_counts"] or generator.required_features != contract["required_features"]):
            raise _error("声明超参/分段不等于实际模型训练配置")
        inputs = [data.view(start_ms=a, end_ms=b)["manifest"] for a, b in [spec["training_window"], spec["search_window"]]+spec["validation_windows"]]
        if inputs != receipt["inputs"]:
            raise _error("实际原始输入与训练/实验窗口不一致")
        trained = CCryptoEvaluationConfig(lv_list=config.lv_list, trade_lv_idx=config.trade_lv_idx,
            chan_config={**config.chan_config, "model": model, "score_thred": spec["thresholds"]["entry"]},
            account=config.account, entry_notional=config.entry_notional)
        experiment = verify_account_experiment(root/"experiment", data, trained)
        if experiment["experiment_id"] != receipt["experiment_id"]:
            raise _error("训练运行与账户实验版本不一致")
        search, _ = read_search_result(root/"experiment"/"search.jsonl")
        context = search.metadata["context"]
        expected_algorithm = "population-perturbation" if spec["algorithm"] == "pbt" else spec["algorithm"]
        if (context["search_window"] != spec["search_window"] or context["validation_windows"] != spec["validation_windows"]
                or context["objective"] != spec["objective"] or context["min_closed_positions"] != spec["min_closed_positions"]
                or search.metadata["allowed_space"] != spec["space"] or search.metadata["trial_budget"] != spec["n_trials"]
                or search.metadata["seed"] != spec["seed"] or search.metadata["algorithm"] != expected_algorithm
                or search.metadata["algorithm_parameters"] != spec["algorithm_parameters"]):
            raise _error("声明的搜索/验证窗口与实际实验不一致")
        proposal = _read_json(root/"experiment"/"proposal.json")
        expected_thresholds = {**_thresholds(spec["thresholds"]), "entry": proposal["configuration"]["chan_config"]["score_thred"]}
        if receipt["thresholds"] != expected_thresholds:
            raise _error("部署阈值不等于预先声明阈值与搜索实际选定 entry 阈值")
        return receipt
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as error:
        raise _error("训练流水线缺少完整可重读证据") from error


def _read_json(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise _error("训练输入 JSON 不允许重复字段")
            result[key] = value
        return result
    value = json.loads(path.read_bytes(), object_pairs_hook=unique_pairs)
    canonical_bytes(value)  # 接受可读 JSON 排版，但不接受 Infinity/NaN。
    return value


def main(argv=None):
    import argparse
    import sys
    parser = argparse.ArgumentParser(description="显式有界 crypto 训练；不下载数据、不复用旧模型或授权下单")
    parser.add_argument("--spec", required=True, help="chan-crypto-training-cli-v1 JSON；路径相对该文件解析")
    arguments = parser.parse_args(argv)
    try:
        path = Path(arguments.spec).resolve()
        spec = _read_json(path)
        if (not isinstance(spec, dict) or set(spec) != {"schema", "data_packet", "output_dir", "configuration", "training"}
                or spec["schema"] != "chan-crypto-training-cli-v1"
                or any(not isinstance(spec[k], str) or not spec[k] for k in ("data_packet", "output_dir"))
                or not isinstance(spec["training"], dict) or "output_dir" in spec["training"]):
            raise _error("训练 spec 缺少固定 schema/数据包/新输出目录/实际配置")
        data = CCryptoEvaluationData.from_dict(_read_json((path.parent/spec["data_packet"]).resolve()))
        result = run_crypto_training_pipeline(data, _configured(spec["configuration"]),
            output_dir=(path.parent/spec["output_dir"]).resolve(), **spec["training"])
        print(json.dumps({"status": result["status"], "pipeline_id": result["pipeline_id"], "candidate_authorized": False}))
        return 0
    except (CChanException, OSError, KeyError, ValueError, TypeError) as error:
        print(f"training_pipeline failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
