"""模型生成抽象框架:CModelGenerator + CDataSet(README「模型类」章节)

外部接口:
- trainProcess():   按 is_buy/market/bsp_type 分桶过滤样本 → 训练 → 评估AUC → 保存模型
- PredictProcess(): 对回测特征文件(过滤后)进行预测
- predictAllProcess(): 用模型对全部样本打分,生成分数文件(对接 automl)
"""
import abc
import hashlib
import json
import math
import os
from typing import Dict, List, Optional, Tuple

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from ChanModel.ModelContract import (MISSING_POLICIES, MODEL_SCHEMA, contract_path, feature_code_identity,
                                     freeze_config, model_runtime, read_model_contract, sha256_file, validate_feature_meta,
                                     validate_feature_presence)

MISSING_VALUE = -9999999  # 与 demo6 的 missing 约定一致


class CDataSet(metaclass=abc.ABCMeta):
    def __init__(self, data, tag='tmp'):
        self.data = data
        self.tag = tag

    @abc.abstractmethod
    def get_count(self) -> int:
        ...

    @abc.abstractmethod
    def get_pos_count(self) -> int:
        ...

    @abc.abstractmethod
    def get_label(self) -> List[float]:
        ...


class CModelInfo:
    def __init__(self):
        self.model = None
        self.feature_dim: int = 0


def load_sample_dir(sample_dir: str, *, include_unknown=False) -> Tuple[Dict[str, int], List[dict]]:
    """读取 backtest.py 落地的样本目录(feature.libsvm + feature.meta + sample_info.jsonl)"""
    meta_path = os.path.join(sample_dir, "feature.meta")
    libsvm_path = os.path.join(sample_dir, "feature.libsvm")
    info_path = os.path.join(sample_dir, "sample_info.jsonl")
    if not os.path.exists(meta_path) or not os.path.exists(libsvm_path):
        raise CChanException(f"样本目录缺少 feature.meta/feature.libsvm: {sample_dir}", ErrCode.MODEL_ERROR)
    with open(meta_path, encoding="utf-8") as f:
        meta = validate_feature_meta(json.load(f))
    infos = []
    if os.path.exists(info_path):
        with open(info_path, encoding="utf-8") as f:
            infos = [json.loads(line) for line in f if line.strip()]
    manifest_path = os.path.join(sample_dir, "sample_manifest.json")
    versioned = os.path.isfile(manifest_path)
    if versioned:
        with open(manifest_path, "rb") as f:
            raw = f.read()
        manifest = json.loads(raw)
        if manifest.get("schema") != "chan-samples-v1" or canonical_bytes(manifest) != raw:
            raise CChanException("不兼容的样本 manifest 版本/字节", ErrCode.MODEL_ERROR)
        if manifest.get("feature_code") != feature_code_identity():
            raise CChanException("样本 feature 公式/代码身份漂移，须重新生成", ErrCode.MODEL_ERROR)
        for name in ("feature.libsvm", "feature.meta", "sample_info.jsonl"):
            with open(os.path.join(sample_dir, name), "rb") as f:
                if hashlib.sha256(f.read()).hexdigest() != manifest.get("files", {}).get(name):
                    raise CChanException("样本文件与 manifest 身份漂移", ErrCode.MODEL_ERROR)
        known_infos = [i for i in infos if i.get("training_row") is not None]
        if ([i["training_row"] for i in known_infos] != list(range(len(known_infos)))
                or manifest.get("known_count") != len(known_infos)
                or manifest.get("unknown_count") != len(infos)-len(known_infos)):
            raise CChanException("样本训练行或 unknown 统计不一致", ErrCode.MODEL_ERROR)
    else:
        known_infos = infos  # 仅保留旧目录读取兼容；训练时不能缺少时序证据。
    samples = []
    with open(libsvm_path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            parts = line.split()
            if not parts:
                continue
            features = {}
            for kv in parts[1:]:
                idx, val = kv.split(":")
                idx, val = int(idx), float(val)
                if idx in features or idx not in meta.values() or not math.isfinite(val):
                    raise CChanException("样本特征索引/数值无效", ErrCode.MODEL_ERROR)
                features[idx] = val
            label = float(parts[0])
            if label not in (0.0, 1.0):
                raise CChanException("样本训练标签必须为已知二元值", ErrCode.MODEL_ERROR)
            info = known_infos[len(samples)] if len(samples) < len(known_infos) else {}
            if versioned and (info.get("label") != int(label) or info.get("primary_label") != manifest["primary_label"]):
                raise CChanException("libsvm 标签与样本说明不一致", ErrCode.MODEL_ERROR)
            samples.append({
                "label": int(label),
                "features": features,
                "info": info,
            })
    if (versioned or infos) and len(samples) != len(known_infos):
        raise CChanException("libsvm 与样本说明行数不一致", ErrCode.MODEL_ERROR)
    if versioned:
        complete = []
        for info in infos:
            named = info.get("features")
            if (not isinstance(named, dict) or named.keys()-meta.keys()
                    or any(value is not None and (type(value) not in (int, float, bool) or not math.isfinite(value))
                           for value in named.values())
                    or hashlib.sha256(canonical_bytes(named)).hexdigest() != info.get("features_sha256")):
                raise CChanException("样本完整 features 与已发布摘要不一致", ErrCode.MODEL_ERROR)
            sparse = {meta[name]: float(value) for name, value in named.items() if value is not None}
            if info["training_row"] is not None and sparse != samples[info["training_row"]]["features"]:
                raise CChanException("完整样本 features 与训练行不一致", ErrCode.MODEL_ERROR)
            complete.append({"label": info["label"], "features": sparse, "info": info})
        if include_unknown:
            return meta, complete
    return meta, samples


def split_temporal_samples(samples, *, train_end_ms, validation_end_ms, test_end_ms=None):
    """全局 UTC 半开区间；同刻不拆分，标签观察穿越区间末端即清除，unknown 排除。"""
    bounds = [train_end_ms, validation_end_ms] + ([] if test_end_ms is None else [test_end_ms])
    if (any(type(b) is not int or b < 0 for b in bounds)
            or any(a >= b for a, b in zip(bounds, bounds[1:]))):
        raise CChanException("训练/验证/测试边界必须为升序 UTC 毫秒", ErrCode.MODEL_ERROR)
    parts = ([], [], [])
    ordered = []
    for sample in samples:
        info = sample.get("info", {})
        at, available, end = (info.get(k) for k in ("decision_ms", "feature_available_at_ms", "label_end_ms"))
        if (not isinstance(info.get("code"), str) or not info["code"]
                or type(at) is not int or type(available) is not int or not 0 <= available <= at):
            raise CChanException("样本缺少有效的 instrument/decision/available 时序证据", ErrCode.MODEL_ERROR)
        if sample.get("label") is None:
            continue
        if type(sample["label"]) is not int or sample["label"] not in (0, 1) or type(end) is not int or end < at:
            raise CChanException("样本标签未完成或观察时刻无效", ErrCode.MODEL_ERROR)
        ordered.append(sample)
    ordered.sort(key=lambda s: (s["info"]["decision_ms"], s["info"]["code"], s["info"].get("event_id", "")))
    for sample in ordered:
        at, end = sample["info"]["decision_ms"], sample["info"]["label_end_ms"]
        i = 0 if at < train_end_ms else 1 if at < validation_end_ms else 2
        ceiling = (train_end_ms, validation_end_ms, test_end_ms)[i]
        if ceiling is None or end < ceiling:
            parts[i].append(sample)
    return parts


def get_market(code: str) -> str:
    # 按代码格式粗分市场:A股/港股/美股/加密货币
    code = str(code)
    if "/" in code or code.upper().endswith("USDT"):
        return "crypto"
    if code.lower().startswith(("sz.", "sh.", "bj.")):
        return "cn"
    if code.upper().startswith("HK."):
        return "hk"
    if code.upper().startswith("US."):
        return "us"
    return "other"


def cal_auc(labels: List[float], preds: List[float]) -> Optional[float]:
    # 秩和法 AUC,避免依赖 sklearn
    pairs = sorted(zip(preds, labels), key=lambda x: x[0])
    pos_cnt = sum(1 for _, y in pairs if y > 0)
    neg_cnt = len(pairs) - pos_cnt
    if pos_cnt == 0 or neg_cnt == 0:
        return None
    rank_sum = 0.0
    i = 0
    while i < len(pairs):  # 并列取平均秩
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        rank_sum += sum(avg_rank for k in range(i, j + 1) if pairs[k][1] > 0)
        i = j + 1
    return (rank_sum - pos_cnt * (pos_cnt + 1) / 2) / (pos_cnt * neg_cnt)


class CModelGenerator(metaclass=abc.ABCMeta):
    def __init__(
        self,
        model_type: str,
        model_tag: str,
        is_buy: Optional[bool] = None,
        market: Optional[str] = None,
        bsp_type: Optional[str] = None,
        folder_thred: Optional[float] = None,
        model_dir: Optional[str] = None,
        split_boundaries_ms: Optional[Dict] = None,
    ):
        self.model_type = model_type
        self.model_tag = model_tag
        self.is_buy = is_buy          # None 表示不分桶
        self.market = market
        self.bsp_type = bsp_type
        self.folder_thred = folder_thred if folder_thred is not None else 0.8  # 时序划分训练集比例
        self.model_dir = model_dir or self._default_model_dir()
        self.model_info = CModelInfo()
        self.feature_meta: Optional[Dict[str, int]] = None
        self.training_boundaries = dict(split_boundaries_ms) if split_boundaries_ms is not None else None
        self.holdout_samples = []
        self.split_counts = {}
        self.training_context = None
        self.artifact_id = None
        self.contract = None

    @staticmethod
    def _default_model_dir() -> str:
        try:
            from Config.EnvConfig import CEnv
            env = CEnv.get_instance()
            return env.abs_path(env.model_conf.get("dir", "ModelStrategy/models/output"))
        except Exception:
            return "./models_output"

    # ===== 六个抽象方法(README 原文)=====
    @abc.abstractmethod
    def train(self, train_set: CDataSet, test_set: CDataSet) -> None:
        # 训练后将模型赋值给 self.model_info.model
        ...

    @abc.abstractmethod
    def create_train_test_set(self, sample_iter) -> Tuple[CDataSet, CDataSet]:
        ...

    @abc.abstractmethod
    def save_model(self):
        ...

    @abc.abstractmethod
    def load_model(self) -> int:
        # 加载模型,返回所需特征维度
        ...

    @abc.abstractmethod
    def predict(self, dataSet: CDataSet) -> List[float]:
        ...

    @abc.abstractmethod
    def create_data_set(self, feature_arr: List[List[float]]) -> CDataSet:
        ...

    # ===== 路径 =====
    def GetTag(self) -> str:
        parts = [self.model_type, self.model_tag]
        if self.is_buy is not None:
            parts.append("buy" if self.is_buy else "sell")
        if self.market is not None:
            parts.append(self.market)
        if self.bsp_type is not None:
            parts.append(self.bsp_type.replace(",", "_"))
        return "_".join(parts)

    def GetModelPath(self) -> str:
        return os.path.join(self.model_dir, f"{self.GetTag()}.model")

    def GetMetaPath(self) -> str:
        return os.path.join(self.model_dir, f"{self.GetTag()}.meta")

    def GetContractPath(self) -> str:
        return contract_path(self.GetModelPath())

    def save_meta(self):
        if self.training_context is None:
            raise CChanException("保存模型缺少完整样本/时间切分契约", ErrCode.MODEL_ERROR)
        os.makedirs(self.model_dir, exist_ok=True)
        with open(self.GetMetaPath(), "w", encoding="utf-8") as f:
            f.write(canonical_bytes(validate_feature_meta(self.feature_meta)).decode("utf-8"))
        config = freeze_config({"params": getattr(self, "xgb_params", getattr(self, "lgbm_params", getattr(self, "mlp_params", {}))),
                                "num_boost_round": getattr(self, "num_boost_round", None),
                                "is_buy": self.is_buy, "market": self.market, "bsp_type": self.bsp_type})
        self.contract = {"schema": MODEL_SCHEMA, "model_type": self.model_type, "model_tag": self.model_tag,
                         "generator_config": config, "generator_config_sha256": hashlib.sha256(canonical_bytes(config)).hexdigest(),
                         "feature_meta": self.feature_meta, "missing_policy": MISSING_POLICIES[self.model_type],
                         "required_features": self.required_features,
                         "feature_code": feature_code_identity(), "runtime": model_runtime(self.model_type),
                         "split_boundaries_ms": self.training_boundaries, "split_counts": self.split_counts,
                         "model_sha256": sha256_file(self.GetModelPath()), "meta_sha256": sha256_file(self.GetMetaPath()),
                         **self.training_context}
        raw = canonical_bytes(self.contract)
        with open(self.GetContractPath(), "wb") as f:
            f.write(raw)
        self.artifact_id = hashlib.sha256(raw).hexdigest()

    def load_meta(self) -> Dict[str, int]:
        self.contract, self.artifact_id = read_model_contract(self.GetModelPath(), self.GetMetaPath(), expected_type=self.model_type)
        self.feature_meta = self.contract["feature_meta"]
        return self.feature_meta

    # ===== 样本处理 =====
    def filter_sample(self, sample: dict) -> bool:
        info = sample.get("info", {})
        if self.is_buy is not None and info.get("is_buy") != self.is_buy:
            return False
        if self.market is not None and get_market(info.get("code", "")) != self.market:
            return False
        if self.bsp_type is not None:
            sample_types = set(str(info.get("bs_type", "")).replace("q", "").replace("z", "").split(","))
            if not sample_types & set(self.bsp_type.split(",")):
                return False
        return True

    def samples_to_feature_arr(self, samples: List[dict], missing: float = MISSING_VALUE) -> List[List[float]]:
        assert self.feature_meta is not None
        dim = len(self.feature_meta)
        arr = []
        for s in samples:
            row = [missing] * dim
            for idx, val in s["features"].items():
                if idx < dim:
                    row[idx] = val
            arr.append(row)
        return arr

    def split_samples(self, samples: List[dict]) -> Tuple[List[dict], List[dict]]:
        self._freeze_split_boundaries(samples)
        train, validation, self.holdout_samples = split_temporal_samples(samples, **self.training_boundaries)
        self.split_counts = {"input": len(samples), "train": len(train), "validation": len(validation),
                             "holdout": len(self.holdout_samples),
                             "purged": len(samples)-len(train)-len(validation)-len(self.holdout_samples)}
        if not train or not validation or not self.holdout_samples:
            raise CChanException("purge 后训练/验证/测试样本不足，不能回填跨界观察标签", ErrCode.MODEL_ERROR)
        common = set.intersection(*(set(s["features"]) for s in train))
        self.required_features = sorted(name for name, idx in (self.feature_meta or {}).items() if idx in common)
        reverse = {idx: name for name, idx in (self.feature_meta or {}).items()}
        for sample in train + validation + self.holdout_samples:
            if reverse:
                validate_feature_presence({reverse[i]: value for i, value in sample["features"].items()},
                                          self.feature_meta, self.required_features)
        return train, validation

    def _freeze_split_boundaries(self, samples):
        if self.training_boundaries is not None:
            return
        if type(self.folder_thred) not in (int, float) or not 0 < self.folder_thred < 1:
            raise CChanException("folder_thred 必须在 0 与 1 之间", ErrCode.MODEL_ERROR)
        times = [s.get("info", {}).get("decision_ms") for s in samples]
        if not times or any(type(t) is not int or t < 0 for t in times):
            raise CChanException("样本缺少全局 UTC decision_ms，不能按数组猜测时间切分", ErrCode.MODEL_ERROR)
        times = sorted(set(times))
        if len(times) < 3:
            raise CChanException("至少需要三个不同决策时刻分离训练/验证/测试", ErrCode.MODEL_ERROR)
        split = max(1, min(int(len(times)*self.folder_thred), len(times)-2))
        validation_end = min(len(times)-1, max(split+1, (len(times)+split)//2))
        self.training_boundaries = {"train_end_ms": times[split], "validation_end_ms": times[validation_end]}

    # ===== 外部接口 =====
    def trainProcess(self, sample_dir: str) -> dict:
        meta, samples = load_sample_dir(sample_dir)
        self.feature_meta = meta
        manifest_path = os.path.join(sample_dir, "sample_manifest.json")
        if not os.path.isfile(manifest_path) or not samples:
            raise CChanException("缺少版本化样本 manifest 或已知标签，不能冒充完整训练证据", ErrCode.MODEL_ERROR)
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        self.training_context = {"samples_manifest_sha256": sha256_file(manifest_path),
                                 "label_definition": {**manifest["label_definition"], "primary_label": manifest["primary_label"]},
                                 "generation_context": manifest.get("generation_context"),
                                 "sample_files": manifest["files"], "unknown_count": manifest["unknown_count"],
                                 "training_window": {"first_decision_ms": min(s["info"]["decision_ms"] for s in samples),
                                                     "last_decision_ms": max(s["info"]["decision_ms"] for s in samples),
                                                     "last_label_end_ms": max(s["info"]["label_end_ms"] for s in samples)}}
        self._freeze_split_boundaries(samples)  # 先冻结整个样本池的时钟，再按币种/方向等分桶。
        filtered = [s for s in samples if self.filter_sample(s)]
        if len(filtered) < 4:
            raise CChanException(f"[{self.GetTag()}] 样本过少({len(filtered)}),无法训练", ErrCode.MODEL_ERROR)
        train_set, test_set = self.create_train_test_set(iter(filtered))
        if set(train_set.get_label()) != {0, 1}:
            raise CChanException("二元模型训练必须具备两个 class 类别", ErrCode.MODEL_ERROR)
        self.train(train_set, test_set)
        res = {
            "tag": self.GetTag(),
            "train_cnt": train_set.get_count(),
            "train_pos_cnt": train_set.get_pos_count(),
            "test_cnt": test_set.get_count(),
            "test_pos_cnt": test_set.get_pos_count(),
            "train_auc": cal_auc(list(train_set.get_label()), self._checked_predict(train_set)),
            "test_auc": cal_auc(list(test_set.get_label()), self._checked_predict(test_set)) if test_set.get_count() > 0 else None,
            "validation_cnt": test_set.get_count(),  # 旧 test_set 名称实为训练期 validation，保留兼容别名。
            "holdout_cnt": len(self.holdout_samples),
            "holdout_auc": cal_auc([s["label"] for s in self.holdout_samples], self._checked_predict(
                self.create_data_set(self.samples_to_feature_arr(self.holdout_samples)))),
            "split_boundaries_ms": self.training_boundaries, "split_counts": self.split_counts,
        }
        self.save_model()
        self.save_meta()
        print(f"[trainProcess] {res['tag']}: train={res['train_cnt']}(pos={res['train_pos_cnt']}) "
              f"test={res['test_cnt']}(pos={res['test_pos_cnt']}) "
              f"train_auc={res['train_auc']} test_auc={res['test_auc']}")
        return res

    def PredictProcess(self, sample_dir: str) -> List[float]:
        samples = self._load_prediction_samples(sample_dir)
        filtered = [s for s in samples if self.filter_sample(s)]
        if not filtered:
            return []
        return self._checked_predict(self.create_data_set(self.samples_to_feature_arr(filtered)))

    def predictAllProcess(self, sample_dir: str, output_path: Optional[str] = None) -> str:
        # 对全部样本打分(不过滤),分数+样本信息落地,直接对接 automl
        samples = self._load_prediction_samples(sample_dir)
        preds = self._checked_predict(self.create_data_set(self.samples_to_feature_arr(samples))) if samples else []
        output_path = output_path or os.path.join(sample_dir, f"score_{self.GetTag()}.jsonl")
        with open(output_path, "w", encoding="utf-8") as f:
            for s, p in zip(samples, preds):
                row = dict(s["info"])
                row["score"] = float(p)
                row["label"] = s["label"]
                row["model_artifact_id"] = self.artifact_id
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[predictAllProcess] {self.GetTag()}: {len(samples)} 样本打分 → {output_path}")
        return output_path

    def _load_prediction_samples(self, sample_dir):
        input_meta, samples = load_sample_dir(sample_dir, include_unknown=True)
        self.load_meta()  # 模型的列身份为准，不允许样本 meta 覆盖训练 meta。
        dim = self.load_model()
        required = set(self.contract["required_features"]) if self.contract else self.feature_meta.keys()
        if dim != len(self.feature_meta):
            raise CChanException("模型维度或输入特征集合与训练 meta 不兼容", ErrCode.MODEL_ERROR)
        reverse = {idx: name for name, idx in input_meta.items()}
        result = []
        for sample in samples:
            named = {reverse[i]: value for i, value in sample["features"].items()}
            validate_feature_presence(named, self.feature_meta, required)
            result.append({**sample, "features": {self.feature_meta[name]: value for name, value in named.items()
                                                  if name in self.feature_meta}})
        return result

    def _checked_predict(self, dataset):
        count = dataset.get_count() if hasattr(dataset, "get_count") else len(dataset)
        scores = [float(v) for v in self.predict(dataset)]
        if len(scores) != count or any(not math.isfinite(v) or
            (self.model_type in MISSING_POLICIES and not 0 <= v <= 1) for v in scores):
            raise CChanException("模型预测行数、有限值或概率无效", ErrCode.MODEL_ERROR)
        return scores

    def predict_features(self, features):
        if self.contract is None:
            raise CChanException("在线模型缺少 artifact", ErrCode.MODEL_ERROR)
        validate_feature_presence(features, self.feature_meta, self.contract["required_features"])
        values = {}
        for name, idx in self.feature_meta.items():
            value = features.get(name)
            if value is not None:
                if type(value) not in (int, float, bool) or not math.isfinite(value):
                    raise CChanException("在线特征必须有限", ErrCode.MODEL_ERROR)
                values[idx] = value
        arr = self.samples_to_feature_arr([{"features": values}])
        return self._checked_predict(self.create_data_set(arr))[0]
