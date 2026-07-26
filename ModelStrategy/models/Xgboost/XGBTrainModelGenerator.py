import os
import sys
from typing import List, Tuple

if __package__ in (None, ""):  # 直接以脚本运行时把仓库根目录加进 sys.path
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", ".."))

from ModelStrategy.ModelGenerator import MISSING_VALUE, CDataSet, CModelGenerator
from ModelStrategy.models.Xgboost.xgb_util import DEFAULT_NUM_BOOST_ROUND, DEFAULT_XGB_PARAMS, xgb_train


class CXGB_DataSet(CDataSet):
    def __init__(self, data, tag='tmp'):
        super(CXGB_DataSet, self).__init__(data, tag)

    def get_count(self):
        return self.data.num_row()

    def get_pos_count(self):
        return int(sum(self.get_label()))

    def get_label(self):
        return self.data.get_label()


class CXGBTrainModelGenerator(CModelGenerator):
    def __init__(
        self,
        model_tag="demo",
        is_buy=None,
        market=None,
        bsp_type=None,
        folder_thred=None,
        xgb_params=None,
        num_boost_round=DEFAULT_NUM_BOOST_ROUND,
        model_dir=None,
    ):
        super(CXGBTrainModelGenerator, self).__init__(
            model_type='xgb',
            model_tag=model_tag,
            is_buy=is_buy,
            market=market,
            bsp_type=bsp_type,
            folder_thred=folder_thred,
            model_dir=model_dir,
        )
        self.xgb_params = xgb_params or dict(DEFAULT_XGB_PARAMS)
        self.num_boost_round = num_boost_round

    def GetModelPath(self) -> str:
        # xgb 按扩展名确定保存格式,用 .json 避免 UBJSON 猜测告警
        return os.path.join(self.model_dir, f"{self.GetTag()}.json")

    def train(self, train_set: CDataSet, test_set: CDataSet) -> None:
        self.model_info.model = xgb_train(
            self.xgb_params, train_set.data, test_set.data,
            num_boost_round=self.num_boost_round, verbose_eval=False,
        )

    def create_train_test_set(self, sample_iter) -> Tuple[CDataSet, CDataSet]:
        import xgboost as xgb
        samples = list(sample_iter)
        train, test = self.split_samples(samples)
        res = []
        for part, tag in ((train, "train"), (test, "test")):
            arr = self.samples_to_feature_arr(part)
            labels = [s["label"] for s in part]
            res.append(CXGB_DataSet(xgb.DMatrix(arr, label=labels, missing=MISSING_VALUE), tag=tag))
        return res[0], res[1]

    def save_model(self):
        os.makedirs(self.model_dir, exist_ok=True)
        self.model_info.model.save_model(self.GetModelPath())

    def load_model(self) -> int:
        import xgboost as xgb
        bst = xgb.Booster(model_file=self.GetModelPath())
        self.model_info.model = bst
        self.model_info.feature_dim = bst.num_features()
        return self.model_info.feature_dim

    def predict(self, dataSet: CDataSet) -> List[float]:
        return list(self.model_info.model.predict(dataSet.data))

    def create_data_set(self, feature_arr: List[List[float]]) -> CDataSet:
        import xgboost as xgb
        return CXGB_DataSet(xgb.DMatrix(feature_arr, missing=MISSING_VALUE))


if __name__ == "__main__":
    sample_dir = sys.argv[1] if len(sys.argv) > 1 else "./backtest_output"
    for is_buy in (True, False, None):
        try:
            CXGBTrainModelGenerator(model_tag="all", is_buy=is_buy).trainProcess(sample_dir)
        except Exception as e:
            print(f"[WARN] is_buy={is_buy} 训练失败: {e}")
