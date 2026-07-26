"""仓位控制:COpenQuotaGen 抽象 + 内置 bench_price 实现

- A股/港股:凑最小手数使开仓金额 ≥ bench_price
- 加密货币:按名义金额 bench_price 折算数量(支持小数)
"""
import abc


class COpenQuotaGen(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def get_quota(self, code: str, price: float, lot_size: float = 1) -> float:
        # 返回开仓数量(股票为股数=手数*每手股数;crypto 为币数量)
        ...


class CBenchPriceQuotaGen(COpenQuotaGen):
    def __init__(self, bench_price: float = 1000.0):
        self.bench_price = bench_price  # 单笔目标名义金额

    def get_quota(self, code: str, price: float, lot_size: float = 1) -> float:
        if price <= 0:
            return 0
        from ModelStrategy.ModelGenerator import get_market
        if get_market(code) == "crypto":  # 按名义金额,数量可为小数(精度由引擎对齐)
            return self.bench_price / price
        # 股票:凑最小手数使金额 >= bench_price
        lots = 1
        while lots * lot_size * price < self.bench_price:
            lots += 1
        return lots * lot_size
