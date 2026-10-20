"""冻结目标与窗口的账户参数实验，不写活动模型/配置，不授予 candidate 身份。"""
import copy
import hashlib
import json
import math
from pathlib import Path

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes

from .artifact import write_json_once
from .crypto_account import _clock, _number, verify_crypto_account_report
from .crypto_evaluate import CCryptoEvaluationConfig, evaluation_code_identity, evaluate_crypto_strategy
from .para_automl import CParaAutoML, read_search_result

PARAMETERS = {"entry_notional", "score_thred", "max_sl_rate", "max_profit_rate"}
OBJECTIVES = {"total_return", "cagr", "calmar"}


def _error(message):
    return CChanException(message, ErrCode.PARA_ERROR)


def _digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _window(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise _error("每个窗口必须有显式 start/end 毫秒")
    start, end = (_clock(t) for t in value)
    if start >= end:
        raise _error("窗口必须是正的 UTC 半开区间")
    return [start, end]


def _context(data, config, *, search_window, validation_windows, space, objective, min_closed_positions):
    search = _window(search_window)
    if (objective not in OBJECTIVES or not isinstance(validation_windows, (list, tuple)) or not validation_windows
            or not isinstance(space, dict) or not space or set(space)-PARAMETERS
            or type(min_closed_positions) is not int or min_closed_positions < 1):
        raise _error("目标/允许参数/验证窗口或最小已完成持仓约束无效")
    windows = [_window(window) for window in validation_windows]
    previous_end = search[1]
    for start, end in windows:
        if start < previous_end:
            raise _error("搜索与验证必须按预先声明顺序不重叠；禁止验证后重新选参")
        previous_end = end
    if config.chan_config.get("model") is None and "score_thred" in space:
        raise _error("没有模型时 score_thred 不会生效，不能搜索无效参数")
    if config.chan_config.get("model") is not None and set(space)&{"max_sl_rate", "max_profit_rate"}:
        raise _error("改变策略上下文后须重训模型，不能用旧模型给搜索结果贴版本")
    views = [data.view(start_ms=a, end_ms=b)["manifest"] for a, b in [search]+windows]
    body = {"schema": "chan-account-experiment-context-v1", "search_window": search, "validation_windows": windows,
            "objective": objective, "objective_contract": "maximize_finite_float_from_Decimal_account_metric",
            "risk_admission": "no_liquidation_required_or_insolvent_event", "allowed_space": copy.deepcopy(space),
            "min_closed_positions": min_closed_positions, "configuration": config.to_dict(), "data_manifests": views,
            "evaluator": evaluation_code_identity(), "candidate_authorized": False,
            "workflow_sha256": hashlib.sha256(Path(__file__).read_text(encoding="utf-8").replace("\r\n", "\n").encode()).hexdigest()}
    body["context_id"] = _digest(body)
    return body


def _configured(config, parameters):
    chan = copy.deepcopy(config.chan_config)
    notional = config.entry_notional
    for key, value in parameters.items():
        if key not in PARAMETERS:
            raise _error("未知评估参数")
        if key == "entry_notional":
            notional = _number(value, positive=True)
        elif key == "score_thred":
            score = _number(value, nonnegative=True)
            if score > 1:
                raise _error("score_thred 必须是概率")
            chan[key] = float(score)
        else:
            if value is not None and not 0 < _number(value, positive=True) < 1:
                raise _error("止损/止盈参数必须为正的小于 1 的比例或 None")
            chan.setdefault("strategy_para", {})[key] = value
    return CCryptoEvaluationConfig(lv_list=config.lv_list, trade_lv_idx=config.trade_lv_idx, chan_config=chan,
                                   account=config.account, entry_notional=notional)


def _score(report, context):
    account = report["account"]
    if (account["metrics"]["closed_position_count"] < context["min_closed_positions"]
            or account["snapshot"]["status"] != "ready"
            or any(row["snapshot"]["status"] != "ready" for row in account["events"])):
        return float("nan")
    value = account["metrics"][context["objective"]]
    if value is None:
        return float("nan")
    result = float(_number(value))
    return result if math.isfinite(result) else float("nan")


def _evaluate(data, config, parameters, window):
    current = _configured(config, parameters)
    result = evaluate_crypto_strategy(data, current, start_ms=window[0], end_ms=window[1])
    verify_crypto_account_report(result.to_dict()["account"])
    return result


def _documents(data, config, search):
    context, best = search.metadata["context"], search.best
    selected = None
    for trial in search.trials:
        actual = _evaluate(data, config, trial.para, context["search_window"]).to_dict()
        score = _score(actual, context)
        if (canonical_bytes(actual) != canonical_bytes(trial.eval_summary)
                or (trial.score is None and math.isfinite(score))
                or (trial.score is not None and score != trial.score)):
            raise _error("搜索 trial 不能逐事件重放，非最优 trial 也不能放宽")
        if trial is best:
            selected = actual
    if selected is None:
        raise _error("搜索缺少明确可重放的最优 trial")
    evaluations = []
    for window in context["validation_windows"]:
        report = _evaluate(data, config, best.para, window).to_dict()
        if not math.isfinite(_score(report, context)):
            raise _error("验证窗口缺少有效完整持仓或有限目标；不得发布建议")
        evaluations.append(report)
    validation = {"schema": "chan-account-validation-v1", "context_id": context["context_id"],
                  "selection_uses": "search_only", "selected_parameters": best.para, "evaluations": evaluations}
    model = config.chan_config.get("model")
    model_evidence = None if model is None else {"artifact_id": model.artifact_id, "file_name": Path(model.path).name,
        "feature_meta": model.contract["feature_meta"], "samples_manifest_sha256": model.contract["samples_manifest_sha256"],
        "label_definition": model.contract["label_definition"]}
    proposal = {"schema": "chan-account-parameter-proposal-v1", "status": "offline_windows_evaluated_not_candidate",
                "context_id": context["context_id"], "parameters": best.para,
                "configuration": _configured(config, best.para).to_dict(), "model": model_evidence,
                "search_evaluation_id": selected["evaluation_id"],
                "validation_evaluation_ids": [r["evaluation_id"] for r in evaluations], "candidate_authorized": False}
    # 配置导出重读后必须完整一致，不能只核验某个参数或最终净值。
    if json.loads(canonical_bytes(proposal))["configuration"] != selected["configuration"]:
        raise _error("配置导出/重读身份漂移")
    return validation, proposal


def run_account_experiment(data, config, *, search_window, validation_windows, space, objective, n_trials, algorithm, seed,
                           output_dir, min_closed_positions=1, algorithm_parameters=None):
    destination = Path(output_dir).resolve()
    if destination.exists() or not destination.parent.is_dir():
        raise _error("实验目录必须是明确新路径，禁止覆盖已有运行")
    context = _context(data, config, search_window=search_window, validation_windows=validation_windows,
                       space=space, objective=objective, min_closed_positions=min_closed_positions)
    search = CParaAutoML(lambda parameters: _evaluate(data, config, parameters, context["search_window"]), space,
                        cal_score=lambda result: _score(result.to_dict(), context), algo=algorithm, seed=seed).run(
                            n_trials=n_trials, **(algorithm_parameters or {}))
    search.metadata["context"] = context
    validation, proposal = _documents(data, config, search)
    # 先完成所有窗口和读取/重放，再创建目录。任何阶段失败都不能留下部署建议。
    destination.mkdir(exist_ok=False)
    paths = [destination/name for name in ("search.jsonl", "validation.json", "proposal.json", "receipt.json")]
    try:
        search.save(str(paths[0]))
        write_json_once(paths[1], validation)
        write_json_once(paths[2], proposal)
        files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths[:3]}
        receipt = {"schema": "chan-account-experiment-v1", "status": "offline_window_checks_passed",
                   "context_id": context["context_id"], "files_sha256": files, "candidate_authorized": False}
        receipt["experiment_id"] = _digest(receipt)
        write_json_once(paths[3], receipt)
        return receipt
    except Exception:
        for path in paths:  # 本运行新建的显式目录；不扫描或删除用户既有文件。
            path.unlink(missing_ok=True)
        destination.rmdir()
        raise


def verify_account_experiment(path, data, config):
    """使用显式原数据和配置重放已选搜索与每个验证窗口，不只是检查哈希。"""
    root = Path(path).resolve()
    try:
        raw = (root/"receipt.json").read_bytes()
        receipt = json.loads(raw)
        expected_files = {"search.jsonl", "validation.json", "proposal.json"}
        body = {k: v for k, v in receipt.items() if k != "experiment_id"}
        if (canonical_bytes(receipt) != raw or receipt.get("schema") != "chan-account-experiment-v1"
                or receipt.get("status") != "offline_window_checks_passed" or receipt.get("candidate_authorized") is not False
                or set(receipt["files_sha256"]) != expected_files or receipt["experiment_id"] != _digest(body)
                or any(hashlib.sha256((root/name).read_bytes()).hexdigest() != digest for name, digest in receipt["files_sha256"].items())):
            raise _error("实验收据/产物缺失或漂移")
        search, _ = read_search_result(root/"search.jsonl")
        context = search.metadata["context"]
        rebuilt = _context(data, config, search_window=context["search_window"], validation_windows=context["validation_windows"],
            space=search.metadata["allowed_space"], objective=context["objective"], min_closed_positions=context["min_closed_positions"])
        if canonical_bytes(context) != canonical_bytes(rebuilt) or context["context_id"] != receipt["context_id"]:
            raise _error("实际数据、窗口、配置或评估器与实验上下文不一致")
        validation, proposal = _documents(data, config, search)
        if (canonical_bytes(validation) != (root/"validation.json").read_bytes()
                or canonical_bytes(proposal) != (root/"proposal.json").read_bytes()):
            raise _error("验证或导出配置不能逐事件重放")
        return receipt
    except (OSError, KeyError, ValueError, TypeError, AttributeError) as error:
        raise _error("实验目录缺少完整可复验证据") from error
