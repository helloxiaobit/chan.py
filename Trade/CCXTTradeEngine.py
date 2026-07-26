"""ccxt 下单引擎(实盘主场景):market/limit 下单、撤单、查余额持仓、testnet、精度对齐、现场恢复

dry_run 模式(config ccxt.api_key 为空或显式指定)下模拟撮合:
所有订单按给定价格(市价单按最近一次报价)立即成交,持仓/余额在内存维护 ——
用于回归测试与不接交易所的完整流程演练。
"""
import itertools
from typing import Dict, Optional

from Common.ChanException import CChanException, ErrCode

from .db_util import CChanDB
from .OpenQuotaGen import COpenQuotaGen
from .TradeEngine import COrderResult, CTradeEngine


class CCCXTTradeEngine(CTradeEngine):
    def __init__(
        self,
        chan_db: CChanDB,
        quota_gen: Optional[COpenQuotaGen] = None,
        dry_run: Optional[bool] = None,
        ccxt_conf: Optional[dict] = None,
        push_msg: bool = True,
    ):
        super(CCCXTTradeEngine, self).__init__(
            market="crypto", chan_db=chan_db, quota_gen=quota_gen, push_msg=push_msg)
        if ccxt_conf is None:
            try:
                from Config.EnvConfig import CEnv
                ccxt_conf = CEnv.get_instance().ccxt_conf
            except Exception:
                ccxt_conf = {}
        self.ccxt_conf = ccxt_conf
        # 未配置 api_key 时自动进入 dry_run(模拟撮合)
        self.dry_run = dry_run if dry_run is not None else not ccxt_conf.get("api_key")
        self.exchange = None
        # dry_run 状态
        self._order_id_gen = itertools.count(1)
        self._sim_orders: Dict[str, COrderResult] = {}
        self._sim_positions: Dict[str, float] = {}
        self._sim_balance: Dict[str, float] = {"USDT": 100000.0}
        self._sim_last_price: Dict[str, float] = {}

    def get_exchange(self):
        if self.exchange is None:
            from DataAPI.ccxt import create_exchange
            self.exchange = create_exchange(self.ccxt_conf)  # 交易接口尊重 testnet 配置
        return self.exchange

    def set_sim_price(self, code: str, price: float):
        # dry_run:注入市价单参考价(测试/演练用)
        self._sim_last_price[code] = price

    # ===== 撮合接口 =====
    def place_order(self, code: str, is_buy: bool, amount: float, price: Optional[float] = None) -> COrderResult:
        if self.dry_run:
            return self._sim_place_order(code, is_buy, amount, price)
        import ccxt  # 懒加载
        exchange = self.get_exchange()
        try:
            amount = float(exchange.amount_to_precision(code, amount))  # 精度对齐
            side = "buy" if is_buy else "sell"
            if price is None:
                order = exchange.create_order(code, "market", side, amount)
            else:
                price = float(exchange.price_to_precision(code, price))
                order = exchange.create_order(code, "limit", side, amount, price)
        except ccxt.BaseError as e:
            raise CChanException(f"下单失败 {code} {side} {amount}: {e}", ErrCode.PLACE_ORDER_FAIL) from e
        return COrderResult(
            order_id=str(order["id"]),
            filled=float(order.get("filled") or 0),
            avg_price=float(order["average"]) if order.get("average") else None,
            status=order.get("status") or "open",
        )

    def cancel_order(self, code: str, order_id: str) -> bool:
        if self.dry_run:
            if order_id in self._sim_orders:
                self._sim_orders[order_id].status = "canceled"
            return True
        import ccxt
        try:
            self.get_exchange().cancel_order(order_id, code)
            return True
        except ccxt.BaseError as e:
            raise CChanException(f"撤单失败 {code} {order_id}: {e}", ErrCode.CANDEL_ORDER_FAIL) from e

    def query_order(self, code: str, order_id: str) -> COrderResult:
        if self.dry_run:
            if order_id not in self._sim_orders:
                raise CChanException(f"订单不存在 {order_id}", ErrCode.LIST_ORDER_FAIL)
            return self._sim_orders[order_id]
        import ccxt
        try:
            order = self.get_exchange().fetch_order(order_id, code)
        except ccxt.BaseError as e:
            raise CChanException(f"查单失败 {code} {order_id}: {e}", ErrCode.LIST_ORDER_FAIL) from e
        return COrderResult(
            order_id=str(order["id"]),
            filled=float(order.get("filled") or 0),
            avg_price=float(order["average"]) if order.get("average") else None,
            status=order.get("status") or "open",
        )

    def get_balance(self) -> Dict[str, float]:
        if self.dry_run:
            return dict(self._sim_balance)
        import ccxt
        try:
            balance = self.get_exchange().fetch_balance()
        except ccxt.BaseError as e:
            raise CChanException(f"查余额失败: {e}", ErrCode.GET_HOLDING_QTY_FAIL) from e
        return {k: v for k, v in balance.get("total", {}).items() if v}

    def get_position(self, code: str) -> float:
        if self.dry_run:
            return self._sim_positions.get(code, 0.0)
        base = code.split("/")[0]  # 现货持仓即基础币余额
        return self.get_balance().get(base, 0.0)

    # ===== dry_run 模拟撮合 =====
    def _sim_place_order(self, code: str, is_buy: bool, amount: float, price: Optional[float]) -> COrderResult:
        if price is None:
            price = self._sim_last_price.get(code)
            if price is None:
                raise CChanException(f"dry_run 市价单需要先 set_sim_price({code})", ErrCode.PLACE_ORDER_FAIL)
        cost = amount * price
        if is_buy:
            if self._sim_balance.get("USDT", 0) < cost:
                raise CChanException(f"dry_run 余额不足: 需要{cost:.2f} USDT", ErrCode.QUOTA_NOT_ENOUGH)
            self._sim_balance["USDT"] -= cost
            self._sim_positions[code] = self._sim_positions.get(code, 0.0) + amount
        else:
            self._sim_positions[code] = self._sim_positions.get(code, 0.0) - amount
            self._sim_balance["USDT"] = self._sim_balance.get("USDT", 0) + cost
        order = COrderResult(order_id=f"sim_{next(self._order_id_gen)}", filled=amount, avg_price=price, status="closed")
        self._sim_orders[order.order_id] = order
        self._sim_last_price[code] = price
        return order
