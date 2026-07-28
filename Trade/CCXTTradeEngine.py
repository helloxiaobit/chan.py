"""ccxt 下单引擎:显式订单意图、撮合、持仓查询和离线演练。

dry_run 模式绝不创建交易所会话。默认立即成交，也可按客户端订单号注入
单调累计成交计划，用于验证零成交、部分成交和重启恢复逻辑。
"""
import itertools
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from Common.ChanException import CChanException, ErrCode

from .db_util import CChanDB
from .OpenQuotaGen import COpenQuotaGen
from .SafetyPolicy import build_trading_safety_policy
from .TradeEngine import COrderResult, CTradeEngine


_CONTRACT_TYPES = {"swap", "future"}
_POSITION_SIDES = {"BOTH", "LONG", "SHORT"}
_CCXT_STATUS_MAP = {
    "open": "open",
    "closed": "closed",
    "canceled": "canceled",
    "cancelled": "canceled",
    "expired": "canceled",
    "rejected": "rejected",
}


@dataclass
class _SimOrder:
    code: str
    is_buy: bool
    price: float
    reduce_only: bool
    result: COrderResult
    fill_plan: List[float]
    next_fill: int = 0


@dataclass
class CSimExchangeState:
    """可在引擎重建后复用的离线交易所状态。"""

    order_id_gen: object = field(default_factory=lambda: itertools.count(1))
    orders: Dict[str, COrderResult] = field(default_factory=dict)
    order_state: Dict[str, _SimOrder] = field(default_factory=dict)
    client_order_ids: Dict[str, str] = field(default_factory=dict)
    fill_plans: Dict[str, List[float]] = field(default_factory=dict)
    positions: Dict[str, float] = field(default_factory=dict)
    balance: Dict[str, float] = field(
        default_factory=lambda: {"USDT": 100000.0}
    )
    last_price: Dict[str, float] = field(default_factory=dict)


def _normalize_order_status(value) -> str:
    status = str(value or "").lower()
    if status not in _CCXT_STATUS_MAP:
        raise CChanException(f"未知订单状态: {value}", ErrCode.LIST_ORDER_FAIL)
    return _CCXT_STATUS_MAP[status]


class CCCXTTradeEngine(CTradeEngine):
    def __init__(
        self,
        chan_db: CChanDB,
        quota_gen: Optional[COpenQuotaGen] = None,
        dry_run: Optional[bool] = None,
        ccxt_conf: Optional[dict] = None,
        trade_conf: Optional[dict] = None,
        environ=None,
        sim_state: Optional[CSimExchangeState] = None,
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
        if trade_conf is None:
            try:
                from Config.EnvConfig import CEnv
                trade_conf = CEnv.get_instance().get_section("trade")
            except Exception:
                trade_conf = {}
        if dry_run is True:
            ccxt_conf = {**ccxt_conf, "mode": "dry_run"}
        elif dry_run is False and ccxt_conf.get("mode", "dry_run") == "dry_run":
            raise CChanException(
                "dry_run=False 不能绕过显式 ccxt.mode",
                ErrCode.TRADE_UNLOCK_FAIL,
            )
        self.ccxt_conf = ccxt_conf
        self.safety_policy = build_trading_safety_policy(
            ccxt_conf, trade_conf, environ
        )
        self.mode = self.safety_policy.mode
        self.dry_run = self.safety_policy.dry_run
        self.market_type = str(ccxt_conf.get("default_type", "spot")).lower()
        if self.market_type not in {"spot", *_CONTRACT_TYPES}:
            raise CChanException(
                "ccxt.default_type 必须是 spot、swap 或 future",
                ErrCode.PARA_ERROR,
            )
        self.leverage = int(ccxt_conf.get("leverage", 1))
        if self.leverage <= 0:
            raise CChanException("ccxt.leverage 必须大于 0", ErrCode.PARA_ERROR)
        default_side = str(ccxt_conf.get("position_side", "BOTH")).upper()
        if default_side not in _POSITION_SIDES:
            raise CChanException(
                "ccxt.position_side 必须是 BOTH、LONG 或 SHORT",
                ErrCode.PARA_ERROR,
            )
        self.position_side = default_side
        self.exchange = None
        # dry_run 状态
        if sim_state is not None and not self.dry_run:
            raise CChanException(
                "sim_state 只能用于 dry_run", ErrCode.PARA_ERROR
            )
        self.sim_state = sim_state or CSimExchangeState()
        self._order_id_gen = self.sim_state.order_id_gen
        self._sim_orders = self.sim_state.orders
        self._sim_order_state = self.sim_state.order_state
        self._sim_client_order_ids = self.sim_state.client_order_ids
        self._sim_fill_plans = self.sim_state.fill_plans
        self._sim_positions = self.sim_state.positions
        self._sim_balance = self.sim_state.balance
        self._sim_last_price = self.sim_state.last_price

    def get_exchange(self):
        if self.dry_run:
            raise CChanException(
                "dry_run 禁止创建交易所会话", ErrCode.TRADE_UNLOCK_FAIL
            )
        if self.exchange is None:
            from DataAPI.ccxt import create_exchange
            self.exchange = create_exchange(self.ccxt_conf)  # 交易接口尊重 testnet 配置
        return self.exchange

    def set_sim_price(self, code: str, price: float):
        # dry_run:注入市价单参考价(测试/演练用)
        self._sim_last_price[code] = price

    def set_sim_fill_plan(
        self, client_order_id: str, cumulative_fills: List[float]
    ) -> None:
        """为下一张指定客户端订单设置累计成交序列。"""
        if not client_order_id or not cumulative_fills:
            raise CChanException("dry_run 成交计划不能为空", ErrCode.PARA_ERROR)
        fills = [float(value) for value in cumulative_fills]
        if any(not math.isfinite(value) or value < 0 for value in fills):
            raise CChanException("dry_run 成交计划包含无效数量", ErrCode.PARA_ERROR)
        if any(current < previous for previous, current in zip(fills, fills[1:])):
            raise CChanException("dry_run 成交计划必须单调递增", ErrCode.PARA_ERROR)
        self._sim_fill_plans[client_order_id] = fills

    def _claim_persisted_intent(
        self,
        code: str,
        is_buy: bool,
        amount: float,
        client_order_id: Optional[str],
        reduce_only: bool,
        position_side: str,
    ) -> None:
        if not client_order_id:
            raise CChanException(
                "非 dry-run 下单必须提供客户端订单号",
                ErrCode.TRADE_UNLOCK_FAIL,
            )
        intent = self.chan_db.get_order_intent(client_order_id)
        if intent is None:
            raise CChanException(
                "客户端订单号没有唯一的持久化意图",
                ErrCode.TRADE_UNLOCK_FAIL,
            )
        phase = intent["phase"]
        record = intent["record"]
        if phase == "open":
            requested = float(record.get("open_requested_qty") or 0)
            valid = (
                record.get("status") in {"submitted", "partially_filled"}
                and record.get("open_order_status") == "created"
                and not record.get("open_order_id")
                and is_buy == bool(record.get("is_buy"))
                and not reduce_only
            )
        else:
            requested = float(record.get("cover_requested_qty") or 0)
            valid = (
                record.get("status") == "closing"
                and record.get("cover_order_status") == "created"
                and not record.get("cover_order_id")
                and is_buy != bool(record.get("is_buy"))
                and reduce_only
            )
        valid = (
            valid
            and record.get("stock_code") == code
            and math.isclose(requested, amount, rel_tol=1e-12, abs_tol=1e-12)
        )
        if self.market_type in _CONTRACT_TYPES:
            valid = valid and record.get("position_side") == position_side
        if not valid:
            raise CChanException(
                "下单参数与持久化意图不一致",
                ErrCode.TRADE_UNLOCK_FAIL,
            )
        if not self.chan_db.claim_order_submission(record["id"], phase):
            raise CChanException(
                "持久化意图已提交或被其他进程获取",
                ErrCode.TRADE_UNLOCK_FAIL,
            )

    # ===== 撮合接口 =====
    def place_order(
        self,
        code: str,
        is_buy: bool,
        amount: float,
        price: Optional[float] = None,
        *,
        client_order_id: Optional[str] = None,
        reduce_only: bool = False,
        post_only: bool = False,
        position_side: Optional[str] = None,
    ) -> COrderResult:
        amount = float(amount)
        if not math.isfinite(amount) or amount <= 0:
            raise CChanException("下单数量必须大于 0", ErrCode.PARA_ERROR)
        if post_only and price is None:
            raise CChanException(
                "post-only 订单必须指定限价", ErrCode.PLACE_ORDER_FAIL
            )
        side = self._resolve_position_side(position_side)
        if self.dry_run:
            return self._sim_place_order(
                code,
                is_buy,
                amount,
                price,
                client_order_id=client_order_id,
                reduce_only=reduce_only,
            )
        self.safety_policy.assert_order_allowed()
        self._claim_persisted_intent(
            code,
            is_buy,
            amount,
            client_order_id,
            reduce_only,
            side,
        )
        import ccxt  # 懒加载
        exchange = self.get_exchange()
        try:
            amount = float(exchange.amount_to_precision(code, amount))  # 精度对齐
            order_type = "market" if price is None else "limit"
            if price is not None:
                price = float(exchange.price_to_precision(code, price))
            params = {}
            if client_order_id:
                params["clientOrderId"] = client_order_id
            if self.market_type in _CONTRACT_TYPES:
                params.update(
                    {
                        "reduceOnly": bool(reduce_only),
                        "postOnly": bool(post_only),
                        "positionSide": side,
                    }
                )
                exchange.set_leverage(
                    self.leverage, code, {"positionSide": side}
                )
            elif post_only:
                params["postOnly"] = True
            order = exchange.create_order(
                code,
                order_type,
                "buy" if is_buy else "sell",
                amount,
                price,
                params,
            )
        except ccxt.BaseError as e:
            order_side = "buy" if is_buy else "sell"
            raise CChanException(
                f"下单失败 {code} {order_side} {amount}: {e}",
                ErrCode.PLACE_ORDER_FAIL,
            ) from e
        return self._result_from_ccxt(
            order, requested=amount, client_order_id=client_order_id
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

    def query_order(
        self,
        code: str,
        order_id: Optional[str] = None,
        *,
        client_order_id: Optional[str] = None,
    ) -> COrderResult:
        if self.dry_run:
            if order_id is None and client_order_id:
                order_id = self._sim_client_order_ids.get(client_order_id)
            if order_id not in self._sim_orders:
                identity = order_id or client_order_id
                raise CChanException(f"订单不存在 {identity}", ErrCode.LIST_ORDER_FAIL)
            state = self._sim_order_state[order_id]
            if state.result.status == "open":
                self._advance_sim_order(state)
            return state.result
        import ccxt
        try:
            exchange = self.get_exchange()
            if order_id is not None:
                order = exchange.fetch_order(order_id, code)
            elif client_order_id:
                matches = [
                    item for item in exchange.fetch_orders(code)
                    if (
                        item.get("clientOrderId")
                        or item.get("client_order_id")
                    ) == client_order_id
                ]
                if len(matches) != 1:
                    raise CChanException(
                        f"客户端订单号匹配数量不是 1: {client_order_id}",
                        ErrCode.LIST_ORDER_FAIL,
                    )
                order = matches[0]
            else:
                raise CChanException(
                    "查单需要交易所订单号或客户端订单号",
                    ErrCode.LIST_ORDER_FAIL,
                )
        except ccxt.BaseError as e:
            identity = order_id or client_order_id
            raise CChanException(f"查单失败 {code} {identity}: {e}", ErrCode.LIST_ORDER_FAIL) from e
        return self._result_from_ccxt(order)

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
        if self.market_type in _CONTRACT_TYPES:
            import ccxt
            try:
                positions = self.get_exchange().fetch_positions([code])
            except ccxt.BaseError as e:
                raise CChanException(
                    f"查合约持仓失败 {code}: {e}",
                    ErrCode.GET_HOLDING_QTY_FAIL,
                ) from e
            total = 0.0
            for position in positions:
                if position.get("symbol") not in {None, code}:
                    continue
                amount = float(
                    position.get("contracts")
                    or position.get("amount")
                    or 0
                )
                side = str(position.get("side") or "").lower()
                total += -abs(amount) if side == "short" else abs(amount)
            return total
        base = code.split("/")[0]  # 现货持仓即基础币余额
        return self.get_balance().get(base, 0.0)

    # ===== dry_run 模拟撮合 =====
    def _resolve_position_side(self, value: Optional[str]) -> str:
        side = self.position_side if value is None else str(value).upper()
        if side not in _POSITION_SIDES:
            raise CChanException(
                "position_side 必须是 BOTH、LONG 或 SHORT",
                ErrCode.PARA_ERROR,
            )
        return side

    def _result_from_ccxt(
        self,
        order: dict,
        requested: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> COrderResult:
        requested_value = order.get("amount")
        if requested_value is None:
            requested_value = requested
        if requested_value is None:
            requested_value = order.get("filled") or 0
        client_value = (
            order.get("clientOrderId")
            or order.get("client_order_id")
            or client_order_id
        )
        return COrderResult(
            order_id=str(order["id"]),
            requested=float(requested_value),
            filled=float(order.get("filled") or 0),
            avg_price=(
                float(order["average"]) if order.get("average") else None
            ),
            status=_normalize_order_status(order.get("status")),
            client_order_id=(str(client_value) if client_value else None),
        )

    @staticmethod
    def _quote_asset(code: str) -> str:
        if "/" not in code:
            return "USDT"
        return code.split("/", 1)[1].split(":", 1)[0]

    def _validate_sim_bounds(
        self,
        code: str,
        is_buy: bool,
        amount: float,
        price: float,
        reduce_only: bool,
    ) -> None:
        position = self._sim_positions.get(code, 0.0)
        if self.market_type == "spot":
            if not is_buy and amount > position:
                raise CChanException(
                    f"dry_run 现货超卖: 持仓{position}, 请求{amount}",
                    ErrCode.QUOTA_NOT_ENOUGH,
                )
            if is_buy:
                quote = self._quote_asset(code)
                cost = amount * price
                if self._sim_balance.get(quote, 0.0) < cost:
                    raise CChanException(
                        f"dry_run 余额不足: 需要{cost:.2f} {quote}",
                        ErrCode.QUOTA_NOT_ENOUGH,
                    )
            return
        if not reduce_only:
            return
        reduces_long = position > 0 and not is_buy
        reduces_short = position < 0 and is_buy
        if not (reduces_long or reduces_short):
            raise CChanException(
                "dry_run reduce-only 方向不会降低现有仓位",
                ErrCode.PLACE_ORDER_FAIL,
            )
        if amount > abs(position):
            raise CChanException(
                "dry_run reduce-only 请求会穿仓或翻转方向",
                ErrCode.PLACE_ORDER_FAIL,
            )

    def _sim_place_order(
        self,
        code: str,
        is_buy: bool,
        amount: float,
        price: Optional[float],
        *,
        client_order_id: Optional[str],
        reduce_only: bool,
    ) -> COrderResult:
        if price is None:
            price = self._sim_last_price.get(code)
            if price is None:
                raise CChanException(f"dry_run 市价单需要先 set_sim_price({code})", ErrCode.PLACE_ORDER_FAIL)
        price = float(price)
        self._validate_sim_bounds(code, is_buy, amount, price, reduce_only)
        if client_order_id in self._sim_client_order_ids:
            existing_id = self._sim_client_order_ids[client_order_id]
            existing = self._sim_order_state[existing_id]
            if (
                existing.code != code
                or existing.is_buy != is_buy
                or existing.result.requested != amount
                or existing.reduce_only != reduce_only
            ):
                raise CChanException(
                    "客户端订单号已被不同意图使用", ErrCode.PLACE_ORDER_FAIL
                )
            return existing.result
        sequence = next(self._order_id_gen)
        client_id = client_order_id or f"sim_client_{sequence}"
        fill_plan = self._sim_fill_plans.pop(client_id, [amount])
        if fill_plan[-1] > amount:
            raise CChanException(
                "dry_run 成交计划超过请求数量", ErrCode.PARA_ERROR
            )
        order = COrderResult(
            order_id=f"sim_{sequence}",
            requested=amount,
            filled=0.0,
            avg_price=None,
            status="open",
            client_order_id=client_id,
        )
        state = _SimOrder(
            code=code,
            is_buy=is_buy,
            price=price,
            reduce_only=reduce_only,
            result=order,
            fill_plan=fill_plan,
        )
        self._sim_orders[order.order_id] = order
        self._sim_order_state[order.order_id] = state
        self._sim_client_order_ids[client_id] = order.order_id
        self._sim_last_price[code] = price
        self._advance_sim_order(state)
        return order

    def _advance_sim_order(self, state: _SimOrder) -> None:
        if state.next_fill >= len(state.fill_plan):
            return
        cumulative = state.fill_plan[state.next_fill]
        state.next_fill += 1
        delta = cumulative - state.result.filled
        if delta < 0:
            raise CChanException(
                "dry_run 累计成交量发生回退", ErrCode.PARA_ERROR
            )
        if delta:
            position = self._sim_positions.get(state.code, 0.0)
            signed_delta = delta if state.is_buy else -delta
            new_position = position + signed_delta
            if self.market_type in _CONTRACT_TYPES:
                if state.reduce_only and (
                    position == 0
                    or abs(new_position) > abs(position)
                    or position * new_position < 0
                ):
                    raise CChanException(
                        "dry_run reduce-only 成交会增加或翻转仓位",
                        ErrCode.PLACE_ORDER_FAIL,
                    )
            else:
                quote = self._quote_asset(state.code)
                cost = delta * state.price
                if state.is_buy:
                    self._sim_balance[quote] -= cost
                else:
                    self._sim_balance[quote] = (
                        self._sim_balance.get(quote, 0.0) + cost
                    )
            self._sim_positions[state.code] = new_position
        state.result.filled = cumulative
        state.result.avg_price = state.price if cumulative else None
        if cumulative == state.result.requested:
            state.result.status = "closed"
