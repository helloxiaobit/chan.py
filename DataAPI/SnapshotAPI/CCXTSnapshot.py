"""ccxt 实时行情快照(加密货币,实盘主场景;fetch_tickers 批量获取)"""
from typing import List, Optional

from .CommSnapshot import CCommSnapshot, T_SNAPSHOT_RES


class CCCXTSnapshot(CCommSnapshot):
    exchange = None  # 可注入(测试/复用连接),否则按 config.yaml 创建

    @classmethod
    def get_exchange(cls):
        if cls.exchange is None:
            from DataAPI.ccxt import create_exchange
            cls.exchange = create_exchange(for_data=True)  # 行情走生产环境,testnet 只影响交易
        return cls.exchange

    @classmethod
    def query(cls, code_list: List[str], return_klu: bool = False) -> T_SNAPSHOT_RES:
        res: T_SNAPSHOT_RES = {code: None for code in code_list}
        try:
            exchange = cls.get_exchange()
            tickers = exchange.fetch_tickers(code_list)  # 批量
        except Exception as e:
            print(f"[CCCXTSnapshot] 行情获取失败(检查网络/代理配置): {e}")
            return res
        for code in code_list:
            ticker = tickers.get(code)
            if ticker is None or ticker.get("last") is None:
                continue
            last = float(ticker["last"])
            ts: Optional[float] = ticker["timestamp"] / 1000 if ticker.get("timestamp") else None
            res[code] = cls.make_result({
                "name": code,
                "open": float(ticker["open"]) if ticker.get("open") is not None else last,
                "yesterdayClose": float(ticker["previousClose"]) if ticker.get("previousClose") is not None else last,
                "price": last,
                "high": float(ticker["high"]) if ticker.get("high") is not None else last,
                "low": float(ticker["low"]) if ticker.get("low") is not None else last,
            }, return_klu, ts=ts)
        return res
