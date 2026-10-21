"""ccxt 实时行情快照(加密货币,实盘主场景;fetch_tickers 批量获取)"""
from typing import List, Optional
from datetime import datetime, timezone

from Common.CTime import CTime

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
    def query_quotes(cls, code_list: List[str], *, now_ms=None):
        """Strict opening quotes; never fill missing venue time with local now."""
        from Common.ChanException import CChanException, ErrCode
        from Common.KLineTime import utc_now_ms
        from Common.MarketQuote import make_quote_batch
        from DataAPI.ccxt import exchange_source_identity
        try:
            if (not isinstance(code_list, list) or not code_list or len(set(code_list)) != len(code_list)
                    or any(not isinstance(code, str) or not code for code in code_list)):
                raise ValueError()
            clock = now_ms or utc_now_ms
            started = clock()
            exchange = cls.get_exchange()
            source = exchange_source_identity(exchange, code_list[0])
            if any(exchange_source_identity(exchange, code) != source for code in code_list):
                raise ValueError()
            tickers = exchange.fetch_tickers(code_list)
            quotes = []
            for code in code_list:
                ticker = tickers[code]
                if ticker["symbol"] != code or type(ticker["last"]) not in (str, int, float):
                    raise ValueError()
                quotes.append({"symbol": code, "price": float(ticker["last"]), "timestamp_ms": ticker.get("timestamp")})
            if any(exchange_source_identity(exchange, code) != source for code in code_list):
                raise ValueError()
            return make_quote_batch(quotes, source=source, started_ms=started, finished_ms=clock())
        except Exception:
            raise CChanException("完整同源 ticker 报价不可用，禁止新增风险", ErrCode.SNAPSHOT_ERR) from None

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
            # ticker 是当下快照，不能冒充已确认周期 K 线。
            if return_klu:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts is not None else datetime.now(timezone.utc)
                res[code].time = CTime(dt.year, dt.month, dt.day, dt.hour, dt.minute,
                                       dt.second, auto=False, tzinfo=timezone.utc)
                res[code].is_final = False
            else:
                res[code]["is_final"] = False
        return res
