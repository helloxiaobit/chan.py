"""交易引擎通用层:CTradeEngine(market, chan_db)

- 频控:两次交易接口调用之间的最小间隔
- 交易时段:wait4MarketOpen(crypto 直通)
- 现场恢复 restore():重启后同步已提交订单状态,不重复开仓
- add_trade(trade_info, price):仓位计算→下单→落库
- 平仓单、订单微调、轮询、推送
具体撮合接口(下单/撤单/查单/余额/持仓)由子类实现(CCXTTradeEngine/FutuTradeEngine)。
"""
import abc
import time
from typing import Dict, List, Optional

from Common.ChanException import CChanException, ErrCode
from Common.send_msg_cmd import send_msg
from Common.TradeUtil import is_market_open

from .db_util import CChanDB
from .OpenQuotaGen import CBenchPriceQuotaGen, COpenQuotaGen


class COrderResult:
    def __init__(self, order_id: str, filled: float, avg_price: Optional[float], status: str):
        self.order_id = order_id
        self.filled = filled          # 已成交数量
        self.avg_price = avg_price    # 成交均价
        self.status = status          # open / closed / canceled


class CTradeEngine(metaclass=abc.ABCMeta):
    def __init__(
        self,
        market: str,
        chan_db: CChanDB,
        quota_gen: Optional[COpenQuotaGen] = None,
        api_interval: float = 0.2,
        push_msg: bool = True,
    ):
        self.market = market  # crypto / cn / hk / us
        self.chan_db = chan_db
        self.quota_gen = quota_gen or CBenchPriceQuotaGen()
        self.api_interval = api_interval
        self.push_msg = push_msg
        self._last_api_ts = 0.0

    # ===== 撮合接口(子类实现)=====
    @abc.abstractmethod
    def place_order(self, code: str, is_buy: bool, amount: float,
                    price: Optional[float] = None) -> COrderResult:
        # price=None 为市价单
        ...

    @abc.abstractmethod
    def cancel_order(self, code: str, order_id: str) -> bool:
        ...

    @abc.abstractmethod
    def query_order(self, code: str, order_id: str) -> COrderResult:
        ...

    @abc.abstractmethod
    def get_balance(self) -> Dict[str, float]:
        ...

    @abc.abstractmethod
    def get_position(self, code: str) -> float:
        ...

    # ===== 通用逻辑 =====
    def rate_limit(self):
        wait = self.api_interval - (time.time() - self._last_api_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_api_ts = time.time()

    def wait4MarketOpen(self, check_interval: float = 60.0, max_wait: Optional[float] = None):
        # crypto 7×24 直通;其他市场等待开盘
        waited = 0.0
        while not is_market_open(self.market):
            if max_wait is not None and waited >= max_wait:
                raise CChanException(f"等待{self.market}开盘超时", ErrCode.TRADE_UNLOCK_FAIL)
            time.sleep(check_interval)
            waited += check_interval

    def add_trade(self, trade_info: dict, price: float) -> COrderResult:
        """开仓:trade_info 为信号记录(db_util 查询行),price 为开仓参考价"""
        record_id = trade_info["id"]
        code = trade_info["stock_code"]
        quota = self.quota_gen.get_quota(code, price)
        if quota <= 0:
            raise CChanException(f"仓位计算为0: {code} price={price}", ErrCode.QUOTA_NOT_ENOUGH)
        self.rate_limit()
        order = self.place_order(code, bool(trade_info["is_buy"]), quota, price)
        self.chan_db.mark_open(
            record_id,
            open_price=order.avg_price or price,
            quota=order.filled or quota,
            order_id=order.order_id,
            score_before=trade_info.get("model_score_before"),
            snapshot={"price": price},
        )
        if self.push_msg:
            bs = "买开" if trade_info["is_buy"] else "卖开"
            send_msg("开仓", f"{code} {bs} {order.filled or quota}@{order.avg_price or price}"
                             f" bstype={trade_info['bstype']} id={record_id}")
        return order

    def cover_trade(self, record: dict, price: Optional[float], reason: str) -> COrderResult:
        """平仓:对已开仓记录反向下单"""
        record_id = record["id"]
        code = record["stock_code"]
        quota = record["quota"]
        self.rate_limit()
        order = self.place_order(code, not bool(record["is_buy"]), quota, price)
        self.chan_db.mark_cover_order(record_id, order.order_id, quota, reason)
        if order.status == "closed" and order.avg_price is not None:
            self.chan_db.mark_cover_done(record_id, order.avg_price)
        if self.push_msg:
            bs = "卖平" if record["is_buy"] else "买平"
            profit = None
            if order.avg_price and record["open_price"]:
                rate = (order.avg_price - record["open_price"]) / record["open_price"]
                profit = rate * 100 if record["is_buy"] else -rate * 100
            send_msg("平仓", f"{code} {bs} {quota}@{order.avg_price or price} reason={reason}"
                             f" profit={f'{profit:.2f}%' if profit is not None else 'NA'} id={record_id}")
        return order

    def poll_orders(self, times: int = 3, interval: float = 5.0, adjust_price: bool = True):
        """轮询未成交平仓单:times 次后仍未成交则撤单重下(订单微调)"""
        for _ in range(times):
            pending = self.chan_db.get_uncovered_orders()
            if not pending:
                return
            for rec in pending:
                self.rate_limit()
                order = self.query_order(rec["stock_code"], rec["cover_order_id"])
                if order.status == "closed":
                    self.chan_db.mark_cover_done(rec["id"], order.avg_price or rec["open_price"])
                elif adjust_price and order.status == "open":
                    # 未成交:撤单后市价重下
                    self.cancel_order(rec["stock_code"], rec["cover_order_id"])
                    new_order = self.place_order(rec["stock_code"], not bool(rec["is_buy"]), rec["quota"], None)
                    self.chan_db.mark_cover_order(rec["id"], new_order.order_id, rec["quota"], rec["cover_reason"] or "retrade")
                    if new_order.status == "closed":
                        self.chan_db.mark_cover_done(rec["id"], new_order.avg_price)
            time.sleep(interval)

    def restore(self) -> List[dict]:
        """现场恢复:重启后核对开仓在途/平仓在途订单状态,防止重复开仓"""
        restored = []
        for rec in self.chan_db.get_open_records():
            if rec["cover_order_id"]:  # 平仓单在途
                order = self.query_order(rec["stock_code"], rec["cover_order_id"])
                if order.status == "closed":
                    self.chan_db.mark_cover_done(rec["id"], order.avg_price or rec["open_price"])
                restored.append(rec)
        return restored
