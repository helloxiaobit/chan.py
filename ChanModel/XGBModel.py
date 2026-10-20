"""旧的 CXGBModel 类名保留；新模型必须携带版本化 artifact。"""
from .GeneratorModel import CGeneratorModel


class CXGBModel(CGeneratorModel):
    expected_type = "xgb"
