"""ETF 数据源(A股研究用,低优先):baostock 同接口,ETF 代码如 sh.510300"""
from .BaoStockAPI import CBaoStock


class CETF_API(CBaoStock):
    # ETF 走 baostock 同一 K线查询接口,仅基础信息可能查不到(不影响K线)
    def SetBasciInfo(self):
        try:
            super(CETF_API, self).SetBasciInfo()
        except Exception:
            self.name = self.code
            self.is_stock = False
