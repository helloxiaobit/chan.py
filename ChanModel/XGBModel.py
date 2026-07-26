import json
import os
from typing import TYPE_CHECKING, Dict

from Common.ChanException import CChanException, ErrCode

from .CommModel import CCommModel

if TYPE_CHECKING:
    from CustomBuySellPoint.CustomBSP import CCustomBSP

MISSING = -9999999  # 与 Debug/strategy_demo6.py 的 predict_bsp 逻辑一致


class CXGBModel(CCommModel):
    """XGB 模型 demo:加载 model + feature.meta,对 cbsp 打分

    path 支持两种形式:
    - 目录:内含 model.json + feature.meta(demo5 产物)
    - 模型文件路径:同名 .meta 文件在旁边(ModelGenerator 产物,如 xxx.model + xxx.meta)
    """

    def load(self, path: str):
        import xgboost as xgb  # 懒加载
        if os.path.isdir(path):
            model_path = os.path.join(path, "model.json")
            meta_path = os.path.join(path, "feature.meta")
        else:
            model_path = path
            meta_path = os.path.splitext(path)[0] + ".meta"
        if not os.path.exists(model_path) or not os.path.exists(meta_path):
            raise CChanException(f"模型或meta文件不存在: {model_path} / {meta_path}", ErrCode.MODEL_ERROR)
        self.model = xgb.Booster()
        self.model.load_model(model_path)
        with open(meta_path, encoding="utf-8") as f:
            self.meta: Dict[str, int] = json.load(f)

    def predict(self, cbsp: 'CCustomBSP') -> float:
        import xgboost as xgb
        feature_arr = [MISSING] * len(self.meta)
        for feat_name, feat_value in cbsp.features.items():
            if feat_name in self.meta and feat_value is not None:
                feature_arr[self.meta[feat_name]] = feat_value
        dtest = xgb.DMatrix([feature_arr], missing=MISSING)
        return float(self.model.predict(dtest)[0])
