import os
import sys
from typing import List, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", ".."))

from ModelStrategy.ModelGenerator import CDataSet, CModelGenerator

DEFAULT_LGBM_PARAMS = {
    "objective": "binary",
    "metric": "auc",
    "learning_rate": 0.1,
    "num_leaves": 15,
    "max_depth": 4,
    "min_data_in_leaf": 2,
    "verbose": -1,
}
NAN = float("nan")  # LGBM 原生支持 nan 缺失值


class CLGBM_DataSet(CDataSet):
    """data = (X: List[List[float]], y: List[int])"""

    def get_count(self):
        return len(self.data[1])

    def get_pos_count(self):
        return int(sum(self.data[1]))

    def get_label(self):
        return self.data[1]


class CLGBMModelGenerator(CModelGenerator):
    def __init__(self, model_tag="demo", is_buy=None, market=None, bsp_type=None,
                 folder_thred=None, lgbm_params=None, num_boost_round=50, model_dir=None):
        super(CLGBMModelGenerator, self).__init__(
            model_type='lgbm', model_tag=model_tag, is_buy=is_buy, market=market,
            bsp_type=bsp_type, folder_thred=folder_thred, model_dir=model_dir,
        )
        self.lgbm_params = lgbm_params or dict(DEFAULT_LGBM_PARAMS)
        self.num_boost_round = num_boost_round

    def train(self, train_set: CDataSet, test_set: CDataSet) -> None:
        import lightgbm as lgb  # 懒加载
        import numpy as np
        dtrain = lgb.Dataset(np.array(train_set.data[0], dtype=float), label=train_set.data[1])
        valid_sets = [dtrain]
        if test_set.get_count() > 0:
            valid_sets.append(lgb.Dataset(np.array(test_set.data[0], dtype=float), label=test_set.data[1], reference=dtrain))
        self.model_info.model = lgb.train(
            self.lgbm_params, dtrain, num_boost_round=self.num_boost_round, valid_sets=valid_sets,
        )

    def create_train_test_set(self, sample_iter) -> Tuple[CDataSet, CDataSet]:
        samples = list(sample_iter)
        train, test = self.split_samples(samples)
        res = []
        for part, tag in ((train, "train"), (test, "test")):
            arr = self.samples_to_feature_arr(part, missing=NAN)
            labels = [s["label"] for s in part]
            res.append(CLGBM_DataSet((arr, labels), tag=tag))
        return res[0], res[1]

    def save_model(self):
        os.makedirs(self.model_dir, exist_ok=True)
        self.model_info.model.save_model(self.GetModelPath())

    def load_model(self) -> int:
        import lightgbm as lgb
        booster = lgb.Booster(model_file=self.GetModelPath())
        self.model_info.model = booster
        self.model_info.feature_dim = booster.num_feature()
        return self.model_info.feature_dim

    def predict(self, dataSet: CDataSet) -> List[float]:
        import numpy as np
        return list(self.model_info.model.predict(np.array(dataSet.data[0], dtype=float)))

    def create_data_set(self, feature_arr: List[List[float]]) -> CDataSet:
        # 预测用,label 占位;把 xgb 缺失约定值转成 nan
        arr = [[NAN if v == -9999999 else v for v in row] for row in feature_arr]
        return CLGBM_DataSet((arr, [0] * len(arr)))

    def samples_to_feature_arr(self, samples, missing=NAN):
        return super().samples_to_feature_arr(samples, missing=missing)


if __name__ == "__main__":
    sample_dir = sys.argv[1] if len(sys.argv) > 1 else "./backtest_output"
    for is_buy in (True, False, None):
        try:
            CLGBMModelGenerator(model_tag="all", is_buy=is_buy).trainProcess(sample_dir)
        except Exception as e:
            print(f"[WARN] is_buy={is_buy} 训练失败: {e}")
