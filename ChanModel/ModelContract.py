"""训练与在线共用的模型身份；不提供 candidate 或实盘授权。"""
import enum
import hashlib
import importlib.metadata
import json
import math
import platform
from pathlib import Path

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes

MODEL_SCHEMA = "chan-model-v1"
MODEL_LIBRARIES = {"xgb": "xgboost", "lgbm": "lightgbm", "mlp": "scikit-learn"}
MISSING_POLICIES = {"xgb": {"kind": "sentinel", "value": -9999999},
                    "lgbm": {"kind": "native-nan"}, "mlp": {"kind": "constant", "value": 0.0}}
MODEL_KEYS = {"schema", "model_type", "model_tag", "generator_config", "generator_config_sha256", "feature_meta",
              "missing_policy", "required_features", "feature_code", "runtime", "split_boundaries_ms", "split_counts",
              "model_sha256", "meta_sha256", "samples_manifest_sha256", "label_definition", "generation_context",
              "sample_files", "unknown_count", "training_window"}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_feature_meta(meta):
    if (not isinstance(meta, dict) or any(not isinstance(k, str) or not k or type(v) is not int for k, v in meta.items())
            or sorted(meta.values()) != list(range(len(meta)))):
        raise CChanException("feature.meta 必须为唯一连续的特征名→索引映射", ErrCode.MODEL_ERROR)
    return meta


def freeze_config(value):
    """可审查的配置快照，不用含地址的 repr/不透明对象伪装可复现。"""
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else {"nonfinite_config": str(value)}
    if isinstance(value, enum.Enum):
        return {"enum": f"{type(value).__module__}.{type(value).__qualname__}", "name": value.name}
    if isinstance(value, type):
        return {"class": f"{value.__module__}.{value.__qualname__}"}
    if isinstance(value, (list, tuple)):
        return [freeze_config(v) for v in value]
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return {k: freeze_config(v) for k, v in value.items()}
    if hasattr(value, "artifact_id"):
        return {"model_artifact": value.artifact_id}
    raise CChanException("配置含不能绑定身份的对象", ErrCode.MODEL_ERROR)


def feature_code_identity():
    root = Path(__file__).resolve().parents[1]
    paths = [root / "Chan.py", root / "ChanConfig.py"]
    paths.extend(root / p for p in ("ModelStrategy/backtest.py", "ModelStrategy/ModelGenerator.py",
        "ModelStrategy/BacktestChanConfig.py", "ModelStrategy/models/Xgboost/XGBTrainModelGenerator.py",
        "ModelStrategy/models/Xgboost/xgb_util.py", "ModelStrategy/models/lightGBM/LGBMModelGenerator.py",
        "ModelStrategy/models/deepModel/MLPModelGenerator.py"))
    for folder in ("Bi", "BuySellPoint", "ChanModel", "Combiner", "Common", "CustomBuySellPoint",
                   "KLine", "Math", "Seg", "ZS"):
        paths.extend((root / folder).rglob("*.py"))
    files = {p.relative_to(root).as_posix(): hashlib.sha256(
        p.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")).hexdigest() for p in sorted(paths)}
    return {"schema": "chan-feature-code-v1", "sha256": hashlib.sha256(canonical_bytes(files)).hexdigest(), "files": files}


def contract_path(model_path):
    return str(Path(model_path).with_suffix(".contract.json"))


def model_runtime(kind):
    if kind not in MODEL_LIBRARIES:
        raise CChanException("不支持的模型类型", ErrCode.MODEL_ERROR)
    return {"python": platform.python_version(), "implementation": platform.python_implementation(),
            "library": MODEL_LIBRARIES[kind], "library_version": importlib.metadata.version(MODEL_LIBRARIES[kind])}


def read_model_contract(model_path, meta_path, *, expected_type=None):
    """在加载 estimator（尤其 pickle）之前核验版本、文件、列、公式与运行时身份。"""
    try:
        raw = Path(contract_path(model_path)).read_bytes()
        contract = json.loads(raw)
        if not isinstance(contract, dict) or set(contract) != MODEL_KEYS:
            raise CChanException("模型 contract 缺少完整来源/列/时间证据", ErrCode.MODEL_ERROR)
        kind = contract["model_type"]
        if (canonical_bytes(contract) != raw or contract["schema"] != MODEL_SCHEMA
                or kind not in MODEL_LIBRARIES or (expected_type is not None and kind != expected_type)
                or contract["runtime"] != model_runtime(kind)
                or contract["missing_policy"] != MISSING_POLICIES[kind]
                or contract["model_sha256"] != sha256_file(model_path)
                or contract["meta_sha256"] != sha256_file(meta_path)
                or contract["feature_code"] != feature_code_identity()):
            raise CChanException("模型 contract/文件/meta/特征公式/runtime 身份漂移", ErrCode.MODEL_ERROR)
        meta = validate_feature_meta(json.loads(Path(meta_path).read_text(encoding="utf-8")))
        if meta != contract["feature_meta"]:
            raise CChanException("模型 meta 列顺序身份漂移", ErrCode.MODEL_ERROR)
        required, bounds, counts = (contract[k] for k in ("required_features", "split_boundaries_ms", "split_counts"))
        times = [bounds["train_end_ms"], bounds["validation_end_ms"]] + ([] if bounds.get("test_end_ms") is None else [bounds["test_end_ms"]])
        definition, window = contract["label_definition"], contract["training_window"]
        digests = [contract[k] for k in ("generator_config_sha256", "model_sha256", "meta_sha256", "samples_manifest_sha256")]
        digests.extend(contract["sample_files"].values())
        if (not isinstance(required, list) or required != sorted(set(required)) or set(required)-meta.keys()
                or set(bounds)-{"train_end_ms", "validation_end_ms", "test_end_ms"}
                or any(type(t) is not int or t < 0 for t in times) or any(a >= b for a, b in zip(times, times[1:]))
                or set(counts) != {"input", "train", "validation", "holdout", "purged"}
                or any(type(n) is not int or n < 0 for n in counts.values())
                or min(counts["train"], counts["validation"], counts["holdout"]) == 0
                or sum(n for k, n in counts.items() if k != "input") != counts["input"]
                or type(contract["unknown_count"]) is not int or contract["unknown_count"] < 0
                or set(window) != {"first_decision_ms", "last_decision_ms", "last_label_end_ms"}
                or any(type(n) is not int or n < 0 for n in window.values())
                or window["first_decision_ms"] > window["last_decision_ms"]
                or window["last_decision_ms"] > window["last_label_end_ms"]
                or definition["version"] != "observed-labels-v1" or not isinstance(definition["parameters"], dict)
                or not isinstance(definition["primary_label"], str) or not definition["primary_label"]
                or set(contract["sample_files"]) != {"feature.meta", "feature.libsvm", "sample_info.jsonl"}
                or any(not isinstance(d, str) or len(d) != 64 or any(c not in "0123456789abcdef" for c in d) for d in digests)
                or hashlib.sha256(canonical_bytes(contract["generator_config"])).hexdigest() != contract["generator_config_sha256"]):
            raise CChanException("模型 contract 来源/特征/窗口约束无效", ErrCode.MODEL_ERROR)
        return contract, hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, KeyError, TypeError, AttributeError, importlib.metadata.PackageNotFoundError) as exc:
        raise CChanException("模型缺失或不兼容的版本化 contract，须从完整样本重新生成", ErrCode.MODEL_ERROR) from exc
