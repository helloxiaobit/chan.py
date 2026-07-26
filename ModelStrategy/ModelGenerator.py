"""模型生成抽象框架:CModelGenerator + CDataSet(README「模型类」章节)

外部接口:
- trainProcess():   按 is_buy/market/bsp_type 分桶过滤样本 → 训练 → 评估AUC → 保存模型
- PredictProcess(): 对回测特征文件(过滤后)进行预测
- predictAllProcess(): 用模型对全部样本打分,生成分数文件(对接 automl)
"""
import abc
import json
import os
from typing import Dict, List, Optional, Tuple

from Common.ChanException import CChanException, ErrCode

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


def load_sample_dir(sample_dir: str) -> Tuple[Dict[str, int], List[dict]]:
    """读取 backtest.py 落地的样本目录(feature.libsvm + feature.meta + sample_info.jsonl)"""
    meta_path = os.path.join(sample_dir, "feature.meta")
    libsvm_path = os.path.join(sample_dir, "feature.libsvm")
    info_path = os.path.join(sample_dir, "sample_info.jsonl")
    if not os.path.exists(meta_path) or not os.path.exists(libsvm_path):
        raise CChanException(f"样本目录缺少 feature.meta/feature.libsvm: {sample_dir}", ErrCode.MODEL_ERROR)
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    infos = []
    if os.path.exists(info_path):
        with open(info_path, encoding="utf-8") as f:
            infos = [json.loads(line) for line in f if line.strip()]
    samples = []
    with open(libsvm_path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            parts = line.strip().split(" ")
            if not parts or parts[0] == "":
                continue
            features = {}
            for kv in parts[1:]:
                idx, val = kv.split(":")
                features[int(idx)] = float(val)
            samples.append({
                "label": int(float(parts[0])),
                "features": features,
                "info": infos[i] if i < len(infos) else {},
            })
    return meta, samples


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

    def save_meta(self):
        os.makedirs(self.model_dir, exist_ok=True)
        with open(self.GetMetaPath(), "w", encoding="utf-8") as f:
            f.write(json.dumps(self.feature_meta or {}))

    def load_meta(self) -> Dict[str, int]:
        with open(self.GetMetaPath(), encoding="utf-8") as f:
            self.feature_meta = json.load(f)
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
        # 时序划分(样本按回测顺序落地),防止随机划分导致的时间泄漏
        split = int(len(samples) * self.folder_thred)
        return samples[:split], samples[split:]

    # ===== 外部接口 =====
    def trainProcess(self, sample_dir: str) -> dict:
        meta, samples = load_sample_dir(sample_dir)
        self.feature_meta = meta
        filtered = [s for s in samples if self.filter_sample(s)]
        if len(filtered) < 4:
            raise CChanException(f"[{self.GetTag()}] 样本过少({len(filtered)}),无法训练", ErrCode.MODEL_ERROR)
        train_set, test_set = self.create_train_test_set(iter(filtered))
        self.train(train_set, test_set)
        self.save_model()
        self.save_meta()
        res = {
            "tag": self.GetTag(),
            "train_cnt": train_set.get_count(),
            "train_pos_cnt": train_set.get_pos_count(),
            "test_cnt": test_set.get_count(),
            "test_pos_cnt": test_set.get_pos_count(),
            "train_auc": cal_auc(list(train_set.get_label()), list(self.predict(train_set))),
            "test_auc": cal_auc(list(test_set.get_label()), list(self.predict(test_set))) if test_set.get_count() > 0 else None,
        }
        print(f"[trainProcess] {res['tag']}: train={res['train_cnt']}(pos={res['train_pos_cnt']}) "
              f"test={res['test_cnt']}(pos={res['test_pos_cnt']}) "
              f"train_auc={res['train_auc']} test_auc={res['test_auc']}")
        return res

    def PredictProcess(self, sample_dir: str) -> List[float]:
        meta, samples = load_sample_dir(sample_dir)
        self.feature_meta = meta
        self.load_model()
        filtered = [s for s in samples if self.filter_sample(s)]
        if not filtered:
            return []
        return list(self.predict(self.create_data_set(self.samples_to_feature_arr(filtered))))

    def predictAllProcess(self, sample_dir: str, output_path: Optional[str] = None) -> str:
        # 对全部样本打分(不过滤),分数+样本信息落地,直接对接 automl
        meta, samples = load_sample_dir(sample_dir)
        self.feature_meta = meta
        self.load_model()
        preds = self.predict(self.create_data_set(self.samples_to_feature_arr(samples)))
        output_path = output_path or os.path.join(sample_dir, f"score_{self.GetTag()}.jsonl")
        with open(output_path, "w", encoding="utf-8") as f:
            for s, p in zip(samples, preds):
                row = dict(s["info"])
                row["score"] = float(p)
                row["label"] = s["label"]
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[predictAllProcess] {self.GetTag()}: {len(samples)} 样本打分 → {output_path}")
        return output_path
