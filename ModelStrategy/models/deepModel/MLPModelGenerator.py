import os
import pickle
import sys
from typing import List, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", ".."))

from ModelStrategy.ModelGenerator import CDataSet, CModelGenerator

DEFAULT_MLP_PARAMS = {
    "hidden_layer_sizes": (64, 16),
    "max_iter": 500,
    "random_state": 42,
    "early_stopping": False,
}


class CMLP_DataSet(CDataSet):
    """data = (X: List[List[float]], y: List[int]);缺失值已填0"""

    def get_count(self):
        return len(self.data[1])

    def get_pos_count(self):
        return int(sum(self.data[1]))

    def get_label(self):
        return self.data[1]


class CMLPModelGenerator(CModelGenerator):
    """MLP 用 sklearn.MLPClassifier 实现(torch 可选,自行替换 train/predict 即可)"""

    def __init__(self, model_tag="demo", is_buy=None, market=None, bsp_type=None,
                 folder_thred=None, mlp_params=None, model_dir=None):
        super(CMLPModelGenerator, self).__init__(
            model_type='mlp', model_tag=model_tag, is_buy=is_buy, market=market,
            bsp_type=bsp_type, folder_thred=folder_thred, model_dir=model_dir,
        )
        self.mlp_params = mlp_params or dict(DEFAULT_MLP_PARAMS)

    def train(self, train_set: CDataSet, test_set: CDataSet) -> None:
        from sklearn.neural_network import MLPClassifier  # 懒加载
        from sklearn.preprocessing import StandardScaler
        scaler = StandardScaler()
        x = scaler.fit_transform(train_set.data[0])
        clf = MLPClassifier(**self.mlp_params)
        clf.fit(x, train_set.data[1])
        self.model_info.model = {"scaler": scaler, "clf": clf}

    def create_train_test_set(self, sample_iter) -> Tuple[CDataSet, CDataSet]:
        samples = list(sample_iter)
        train, test = self.split_samples(samples)
        res = []
        for part, tag in ((train, "train"), (test, "test")):
            arr = self.samples_to_feature_arr(part, missing=0.0)  # MLP 缺失填0
            labels = [s["label"] for s in part]
            res.append(CMLP_DataSet((arr, labels), tag=tag))
        return res[0], res[1]

    def save_model(self):
        os.makedirs(self.model_dir, exist_ok=True)
        with open(self.GetModelPath(), "wb") as f:
            pickle.dump(self.model_info.model, f)

    def load_model(self) -> int:
        with open(self.GetModelPath(), "rb") as f:
            self.model_info.model = pickle.load(f)
        self.model_info.feature_dim = self.model_info.model["scaler"].n_features_in_
        return self.model_info.feature_dim

    def predict(self, dataSet: CDataSet) -> List[float]:
        x = self.model_info.model["scaler"].transform(dataSet.data[0])
        return list(self.model_info.model["clf"].predict_proba(x)[:, 1])

    def create_data_set(self, feature_arr: List[List[float]]) -> CDataSet:
        arr = [[0.0 if v == -9999999 else v for v in row] for row in feature_arr]
        return CMLP_DataSet((arr, [0] * len(arr)))

    def samples_to_feature_arr(self, samples, missing=0.0):
        return super().samples_to_feature_arr(samples, missing=missing)


if __name__ == "__main__":
    sample_dir = sys.argv[1] if len(sys.argv) > 1 else "./backtest_output"
    for is_buy in (True, False, None):
        try:
            CMLPModelGenerator(model_tag="all", is_buy=is_buy).trainProcess(sample_dir)
        except Exception as e:
            print(f"[WARN] is_buy={is_buy} 训练失败: {e}")
