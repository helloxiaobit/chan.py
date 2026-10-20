"""复用训练端 estimator/缺失策略的 XGB、LGBM、MLP 在线适配，不重做第二套评分。"""
from pathlib import Path

from Common.ChanException import CChanException, ErrCode
from .CommModel import CCommModel
from .ModelContract import read_model_contract


class CGeneratorModel(CCommModel):
    expected_type = None

    def load(self, path):
        path = Path(path).resolve()
        meta_path = path.with_suffix(".meta")
        contract, _ = read_model_contract(path, meta_path, expected_type=self.expected_type)
        kind = contract["model_type"]
        if kind == "xgb":
            from ModelStrategy.models.Xgboost.XGBTrainModelGenerator import CXGBTrainModelGenerator
            factory = CXGBTrainModelGenerator
        elif kind == "lgbm":
            from ModelStrategy.models.lightGBM.LGBMModelGenerator import CLGBMModelGenerator
            factory = CLGBMModelGenerator
        else:
            from ModelStrategy.models.deepModel.MLPModelGenerator import CMLPModelGenerator
            factory = CMLPModelGenerator
        options = contract["generator_config"]
        self.generator = factory(model_tag=contract["model_tag"], model_dir=str(path.parent),
                                 is_buy=options["is_buy"], market=options["market"], bsp_type=options["bsp_type"])
        if Path(self.generator.GetModelPath()).resolve() != path:
            raise CChanException("模型文件名与 artifact tag 不一致", ErrCode.MODEL_ERROR)
        dim = self.generator.load_model()
        if dim != len(self.generator.feature_meta):
            raise CChanException("模型维度与 artifact meta 不一致", ErrCode.MODEL_ERROR)
        self.artifact_id = self.generator.artifact_id
        self.contract = self.generator.contract
        self.path = str(path)

    def predict(self, cbsp):
        return self.generator.predict_features(dict(cbsp.features.items()))
