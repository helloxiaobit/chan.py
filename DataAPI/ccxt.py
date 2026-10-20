from typing import Optional

from Common.CEnum import AUTYPE, KL_TYPE
from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import bar_close_ms, make_crypto_klu, utc_now_ms, validate_ohlcv_page

from .CommonStockAPI import CCommonStockApi

# ccxt timeframe 映射(K_10M 等交易所不支持的级别不在列)
KLTYPE2TIMEFRAME = {
    KL_TYPE.K_1M: '1m',
    KL_TYPE.K_3M: '3m',
    KL_TYPE.K_5M: '5m',
    KL_TYPE.K_15M: '15m',
    KL_TYPE.K_30M: '30m',
    KL_TYPE.K_60M: '1h',
    KL_TYPE.K_2H: '2h',
    KL_TYPE.K_4H: '4h',
    KL_TYPE.K_DAY: '1d',
    KL_TYPE.K_WEEK: '1w',
    KL_TYPE.K_MON: '1M',
}

PAGE_LIMIT = 1000  # 单次 fetch_ohlcv 最大根数(binance 上限)


def exchange_source_identity(exchange, symbol):
    from OfflineData.offline_data_util import validate_source_identity
    return validate_source_identity({"exchange": exchange.id,
                                     "market_type": getattr(exchange, "options", {}).get("defaultType"),
                                     "settle": symbol.split(":", 1)[1] if ":" in symbol else "",
                                     "price_type": "contract"})


def create_exchange(conf: Optional[dict] = None, for_data: bool = False):
    """按 config.yaml 的 ccxt 段创建交易所实例(懒加载 ccxt)

    for_data=True 时忽略 testnet 配置(行情/K线是公共数据,始终走生产环境;
    测试网只保留近期K线,会导致历史数据缺失。testnet 只影响交易类接口)。
    """
    import ccxt  # 懒加载,核心缠论计算不依赖
    if conf is None:
        try:
            from Config.EnvConfig import CEnv
            conf = CEnv.get_instance().ccxt_conf
        except Exception:
            conf = {}
    exchange_name = conf.get("exchange", "binance")
    if not hasattr(ccxt, exchange_name):
        raise CChanException(f"ccxt 不支持交易所: {exchange_name}", ErrCode.SRC_DATA_TYPE_ERR)
    params = {
        "enableRateLimit": bool(conf.get("rate_limit", True)),
    }
    if conf.get("api_key"):
        params["apiKey"] = conf["api_key"]
    if conf.get("secret"):
        params["secret"] = conf["secret"]
    if conf.get("password"):
        params["password"] = conf["password"]
    if conf.get("default_type"):
        params["options"] = {"defaultType": conf["default_type"]}
    exchange = getattr(ccxt, exchange_name)(params)
    if conf.get("proxy"):
        exchange.proxies = {"http": conf["proxy"], "https": conf["proxy"]}
    if conf.get("testnet") and not for_data:
        try:
            exchange.set_sandbox_mode(True)
        except Exception as exc:
            # 交易用途绝不能在沙盒启用失败后静默落到生产端点。
            raise CChanException(
                "交易测试网沙盒启用失败，已拒绝创建交易会话",
                ErrCode.TRADE_UNLOCK_FAIL,
            ) from exc
    return exchange


class CCXT(CCommonStockApi):
    """ccxt K线数据源:since 分页拉全量、带成交量、支持 end_date、限频与代理走 config.yaml"""

    exchange = None  # 类级共享,do_init 创建,do_close 释放

    def __init__(self, code, k_type=KL_TYPE.K_DAY, begin_date=None, end_date=None, autype=AUTYPE.QFQ, *, now_ms=None):
        super(CCXT, self).__init__(code, k_type, begin_date, end_date, autype)
        self.now_ms = now_ms or utc_now_ms

    def get_kl_data(self):
        import ccxt  # 懒加载(异常类型判断用)
        if CCXT.exchange is None:
            CCXT.do_init()
        exchange = CCXT.exchange
        source = exchange_source_identity(exchange, self.code)
        timeframe = self.__convert_type()
        since = exchange.parse8601(f"{self.begin_date}T00:00:00Z") if self.begin_date else None
        end_ts = exchange.parse8601(f"{self.end_date}T00:00:00Z") if self.end_date else None
        available_ms = self.now_ms()  # 一次读取固定可用边界，避免分页期间改变输入窗口

        last_ts = None
        while True:
            try:
                data = exchange.fetch_ohlcv(self.code, timeframe, since=since, limit=PAGE_LIMIT)
            except ccxt.NetworkError as e:
                raise CChanException(
                    f"ccxt 网络请求失败({exchange.id} {self.code} {timeframe}),"
                    f"请检查网络/代理配置(config.yaml ccxt.proxy): {e}",
                    ErrCode.SRC_DATA_NOT_FOUND,
                ) from e
            except ccxt.BaseError as e:
                raise CChanException(f"ccxt 获取K线失败({exchange.id} {self.code} {timeframe}): {e}", ErrCode.SRC_DATA_NOT_FOUND) from e
            if not data:
                break
            data = validate_ohlcv_page(data, self.k_type, since=since, previous_open=last_ts)
            for item in data:
                ts = item[0]
                if last_ts is not None and ts <= last_ts:  # 去重防回绕
                    continue
                if end_ts is not None and ts >= end_ts:
                    return
                if bar_close_ms(ts, self.k_type) > available_ms:
                    return
                last_ts = ts
                klu = self.make_klu(item)
                klu.source_identity = dict(source)
                yield klu
            if len(data) < PAGE_LIMIT or since is None:
                break  # 不足一页说明已到最新;未指定begin_date只取最近一页
            since = last_ts + 1  # 下一页从最后一根之后开始

    def make_klu(self, ohlcv) -> "CKLine_Unit":
        return make_crypto_klu(ohlcv, self.k_type, self.now_ms())

    def SetBasciInfo(self):
        pass

    @classmethod
    def do_init(cls):
        cls.exchange = create_exchange(for_data=True)

    @classmethod
    def do_close(cls):
        cls.exchange = None

    def __convert_type(self):
        if self.k_type not in KLTYPE2TIMEFRAME:
            raise CChanException(f"ccxt 不支持K线级别: {self.k_type}", ErrCode.SRC_DATA_TYPE_ERR)
        return KLTYPE2TIMEFRAME[self.k_type]
