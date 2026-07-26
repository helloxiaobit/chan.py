"""实时快照抽象父类:query 类方法规范见 README「实时数据接入」

返回值约定:Dict[code, CKLine_Unit|Dict|None]
- return_klu=True → CKLine_Unit
- return_klu=False → {"name","price","low","high","open","yesterdayClose"}(price/low/high 必有)
- 获取失败 → 对应 code 的值为 None
"""
import abc
from datetime import datetime
from typing import Dict, List, Optional, Union

from Common.CEnum import DATA_FIELD
from Common.CTime import CTime
from KLine.KLine_Unit import CKLine_Unit

T_SNAPSHOT_RES = Dict[str, Optional[Union[CKLine_Unit, Dict[str, float]]]]


class CCommSnapshot(metaclass=abc.ABCMeta):
    @classmethod
    @abc.abstractmethod
    def query(cls, code_list: List[str], return_klu: bool = False) -> T_SNAPSHOT_RES:
        ...

    @staticmethod
    def make_result(price_dict: Optional[Dict[str, float]], return_klu: bool, ts: Optional[float] = None):
        # price_dict → 统一出口;return_klu=True 时以快照构造当下的"未完成K线"
        if price_dict is None:
            return None
        if not return_klu:
            return price_dict
        dt = datetime.fromtimestamp(ts) if ts is not None else datetime.now()
        open_price = price_dict.get("open", price_dict["price"])
        return CKLine_Unit({
            DATA_FIELD.FIELD_TIME: CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, auto=False),
            DATA_FIELD.FIELD_OPEN: open_price,
            DATA_FIELD.FIELD_HIGH: price_dict["high"],
            DATA_FIELD.FIELD_LOW: price_dict["low"],
            DATA_FIELD.FIELD_CLOSE: price_dict["price"],
        }, autofix=True)
