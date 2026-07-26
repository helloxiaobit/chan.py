"""实时快照统一入口:StockSnapshotAPI.priceQuery(codelist, engine, return_klu)"""
from typing import List

from Common.ChanException import CChanException, ErrCode

from .AkShareSnapshot import CAKShareSnapshot
from .CCXTSnapshot import CCCXTSnapshot
from .CommSnapshot import T_SNAPSHOT_RES
from .FutuSnapshot import CFutuSnapshot
from .PytdxSnapshot import CPytdxSnapshot
from .SinaAPI import CSinaApi


def priceQuery(codelist: List[str], engine: str, return_klu: bool = False) -> T_SNAPSHOT_RES:
    _class_dict = {
        'sina': CSinaApi,
        'futu': CFutuSnapshot,
        'pytdx': CPytdxSnapshot,
        'ak': CAKShareSnapshot,
        'ccxt': CCCXTSnapshot,
    }
    if engine in _class_dict:
        return _class_dict[engine].query(codelist, return_klu=return_klu)
    raise CChanException(f"engine={engine} not found", ErrCode.SNAPSHOT_ERR)
