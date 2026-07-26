import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from CustomBuySellPoint.CustomBSP import CCustomBSP


class CCommModel(metaclass=abc.ABCMeta):
    """模型接入抽象类:实现后赋值给 CChanConfig.model,即可在计算过程中对 cbsp 实时打分

    load 通常除了模型文件本身还要加载 meta 文件(特征名→index),
    才能把 cbsp.features 字典构造成 predict 所需的输入向量。
    """

    def __init__(self, path: str):
        self.load(path)

    @abc.abstractmethod
    def load(self, path: str):
        ...

    @abc.abstractmethod
    def predict(self, cbsp: 'CCustomBSP') -> float:
        # 取出 cbsp.features,构造成模型所需要的输入,返回预测值即可
        ...
