"""ccxt 下单引擎:显式订单意图、撮合、持仓查询和离线演练。

dry_run 模式绝不创建交易所会话。默认立即成交，也可按客户端订单号注入
单调累计成交计划，用于验证零成交、部分成交和重启恢复逻辑。
"""
import itertools
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, localcontext
from typing import Dict, List, Optional

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes

from .db_util import CChanDB
from .OpenQuotaGen import COpenQuotaGen
from .SafetyPolicy import build_trading_safety_policy
from .TradeEngine import COrderResult, CTradeEngine


_CONTRACT_TYPES = {"swap", "future"}
_POSITION_SIDES = {"BOTH", "LONG", "SHORT"}
# Transport bounds, not strategy/search parameters. Exhaustion means unknown,
# never proof that an accepted order did not exist. Native-id queries run first.
_HISTORY_MAX_PAGES = 32
_HISTORY_WINDOW_MS = 6*86_400_000
_HISTORY_MAX_AGE_MS = 90*86_400_000
_CCXT_STATUS_MAP = {
    "open": "open",
    "closed": "closed",
    "canceled": "canceled",
    "cancelled": "canceled",
    "expired": "canceled",
    "rejected": "rejected",
}


def _quantity(value, *, positive=False):
    try:
        if value is None or isinstance(value, bool):
            raise ValueError("missing numeric evidence")
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or (positive and result == 0):
            raise ValueError("invalid numeric evidence")
        return result
    except (ValueError, InvalidOperation) as error:
        raise CChanException("订单单位/价格证据必须为有限有效数值", ErrCode.PARA_ERROR) from error


def _contract_id(value):
    return hashlib.sha256(canonical_bytes({k: v for k, v in value.items() if k != "contract_id"})).hexdigest()


def _float_exact(value):
    result = float(value)
    if _quantity(result) != value:
        raise CChanException("订单数值无法经过 DB/CCXT 数值边界原样重读", ErrCode.PARA_ERROR)
    return result


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
        self.leverage = ccxt_conf.get("leverage", 1)
        if type(self.leverage) is not int or not 1 <= self.leverage <= 125:
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

    def make_client_order_id(self, record, phase):
        # 只生成新 id；查询/恢复始终使用已持久化原 id，不裁剪或改写旧号。
        original = super().make_client_order_id(record, phase)
        return "cp" + phase[0] + hashlib.sha256(original.encode()).hexdigest()[:28]

    def _execution_settings(self, code, record=None, *, reduce_only=False):
        exchange_id = self.get_exchange().id
        venue = "binance" if exchange_id in {"binance", "binanceusdm"} else exchange_id
        if venue not in {"binance", "okx"}:
            raise CChanException("当前交易参数仅适配 Binance/OKX", ErrCode.PARA_ERROR)
        if reduce_only and record is not None:
            opened = self._read_order_contract(code, {"phase": "open", "record": record})
            if opened["schema"] == "chan-ccxt-order-v2":
                return dict(opened["execution"])
            raise CChanException("v1 只读恢复：自动提交前须显式补足执行设置证据", ErrCode.TRADE_UNLOCK_FAIL)
        if self.market_type == "spot":
            return {"venue": venue, "position_mode": "one_way", "position_side": "BOTH",
                    "margin_mode": "cash", "leverage": 1}
        mode, margin = (self.ccxt_conf.get(k) for k in ("position_mode", "margin_mode"))
        leverage = self.ccxt_conf.get("leverage", 1)
        if (mode not in {"one_way", "hedged"} or margin not in {"cross", "isolated"}
                or type(leverage) is not int or not 1 <= leverage <= 125):
            raise CChanException("swap 必须显式指定 position_mode/margin_mode 和整数 leverage", ErrCode.PARA_ERROR)
        side = record.get("position_side") if record is not None else self.position_side
        if mode == "one_way":
            if side not in {None, "", "BOTH"} or self.position_side != "BOTH":
                raise CChanException("one_way 不能使用 LONG/SHORT leg", ErrCode.PARA_ERROR)
            side = "BOTH"
        elif record is not None and record.get("status") == "signal":
            derived = "LONG" if record["is_buy"] else "SHORT"
            if side not in {None, "", "BOTH", derived} or self.position_side not in {"BOTH", derived}:
                raise CChanException("hedged 新风险方向与信号 leg 不一致", ErrCode.PARA_ERROR)
            side = derived
        elif side not in {"LONG", "SHORT"}:
            raise CChanException("hedged 缺少明确 LONG/SHORT leg", ErrCode.PARA_ERROR)
        return {"venue": venue, "position_mode": mode, "position_side": side,
                "margin_mode": margin, "leverage": leverage}

    def _position_side(self, record):
        if self.dry_run:
            return super()._position_side(record)
        return self._execution_settings(record["stock_code"], record,
            reduce_only=record.get("status") != "signal")["position_side"]

    def _observe_account(self, code, execution, *, reduce_only):
        if self.market_type == "spot":
            return None
        import ccxt
        exchange = self.get_exchange()
        args = {"marginMode": execution["margin_mode"]} if execution["venue"] == "okx" else {}
        try:
            mode = exchange.fetch_position_mode(code)
            leverage = exchange.fetch_leverage(code, args)
        except ccxt.BaseError as error:
            raise CChanException("账户设置只读核验失败，未取得提交权", ErrCode.TRADE_UNLOCK_FAIL) from error
        if not isinstance(mode, dict) or not isinstance(leverage, dict):
            raise CChanException("账户设置只读核验缺少结构化证据", ErrCode.TRADE_UNLOCK_FAIL)
        hedged = mode.get("hedged")
        keys = ["longLeverage", "shortLeverage"] if execution["position_side"] == "BOTH" else [
            "longLeverage" if execution["position_side"] == "LONG" else "shortLeverage"]
        if (type(hedged) is not bool or hedged != (execution["position_mode"] == "hedged")
                or leverage.get("symbol") != code or leverage.get("marginMode") != execution["margin_mode"]
                or (not reduce_only and any(type(leverage.get(k)) is not int or leverage[k] != execution["leverage"] for k in keys))):
            raise CChanException("实际账户 mode/margin/leverage 与订单设置不一致", ErrCode.TRADE_UNLOCK_FAIL)
        return {"hedged": hedged, "margin_mode": leverage["marginMode"],
                "long_leverage": leverage.get("longLeverage"), "short_leverage": leverage.get("shortLeverage")}

    @staticmethod
    def _venue_params(contract, client_id, *, is_buy, reduce_only, post_only, side):
        execution = contract["execution"]
        venue, mode = execution["venue"], execution["position_mode"]
        if type(post_only) is not bool or post_only != contract["post_only"]:
            raise CChanException("post-only 与持久化订单意图不一致", ErrCode.PARA_ERROR)
        pattern = r"[A-Za-z0-9]{1,32}" if venue == "okx" else r"[.A-Za-z0-9_:/-]{1,36}"
        if not re.fullmatch(pattern, client_id or ""):
            raise CChanException("客户端订单号不符合交易所格式", ErrCode.PARA_ERROR)
        if side != execution["position_side"] or (mode == "hedged" and (side == "LONG") != (is_buy != reduce_only)):
            raise CChanException("订单方向/降风险语义与冻结 leg 不一致", ErrCode.PARA_ERROR)
        params = {"clientOrderId": client_id} if venue == "binance" else {"clOrdId": client_id}
        if execution["margin_mode"] == "cash":
            if venue == "okx":
                params.update(tdMode="cash", tgtCcy="base_ccy")
                if contract["price"] is None:
                    params["banAmend"] = True
        else:
            if venue == "binance":
                params["positionSide"] = side
            else:
                params.update(tdMode=execution["margin_mode"], posSide="net" if mode == "one_way" else side.lower())
            if mode == "one_way" and reduce_only:
                params["reduceOnly"] = True
        if post_only:
            params["postOnly"] = True
        return params

    @staticmethod
    def _check_execution_evidence(contract, record, phase):
        execution, observation = contract["execution"], contract["account_observation"]
        keys = {"venue", "position_mode", "position_side", "margin_mode", "leverage"}
        if type(contract["post_only"]) is not bool or (contract["post_only"] and contract["price"] is None):
            raise ValueError("invalid post-only evidence")
        venue = contract["market"]["exchange"]
        venue = "binance" if venue in {"binance", "binanceusdm"} else venue
        if (set(execution) != keys or execution["venue"] != venue or venue not in {"binance", "okx"}
                or execution["position_mode"] not in {"one_way", "hedged"}
                or execution["position_side"] != record["position_side"]
                or type(execution["leverage"]) is not int or not 1 <= execution["leverage"] <= 125):
            raise ValueError("incomplete execution evidence")
        hedge = execution["position_mode"] == "hedged"
        side = execution["position_side"]
        if ((hedge and (side not in {"LONG", "SHORT"} or (side == "LONG") != bool(record["is_buy"])))
                or (not hedge and side != "BOTH")):
            raise ValueError("execution leg mismatch")
        if contract["market"]["type"] == "spot":
            if hedge or execution["margin_mode"] != "cash" or execution["leverage"] != 1 or observation is not None:
                raise ValueError("unsupported cash execution")
            return
        if (execution["margin_mode"] not in {"cross", "isolated"} or not isinstance(observation, dict)
                or set(observation) != {"hedged", "margin_mode", "long_leverage", "short_leverage"}
                or observation["hedged"] is not hedge or observation["margin_mode"] != execution["margin_mode"]
                or any(value is not None and (type(value) is not int or not 1 <= value <= 125)
                    for value in (observation["long_leverage"], observation["short_leverage"]))):
            raise ValueError("incomplete account observation")
        observed = [observation["long_leverage"], observation["short_leverage"]] if side == "BOTH" else [
            observation["long_leverage"] if side == "LONG" else observation["short_leverage"]]
        if phase == "open" and any(value != execution["leverage"] for value in observed):
            raise ValueError("opening leverage mismatch")

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

    def _validated_persisted_intent(
        self,
        code: str,
        is_buy: bool,
        amount: float,
        client_order_id: Optional[str],
        reduce_only: bool,
        position_side: str,
    ) -> dict:
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
        return intent

    def _market_contract(self, code):
        """当前交易所真实 metadata；不从 symbol 或缺省 contractSize 猜单位。"""
        exchange = self.get_exchange()
        exchange.load_markets()
        market = exchange.market(code)
        spot = self.market_type == "spot"
        if (market.get("symbol") != code or not market.get("id") or not exchange.id
                or not market.get("base") or not market.get("quote")
                or (spot and (market.get("spot") is not True or market.get("contract")))
                or (not spot and (self.market_type != "swap" or market.get("swap") is not True
                    or market.get("contract") is not True or market.get("linear") is not True
                    or market.get("inverse") is not False or market.get("settle") != "USDT"
                    or market.get("quote") != "USDT"))):
            raise CChanException("缺少或不支持的现货/USDT 线性永续 market 身份", ErrCode.PARA_ERROR)
        size = Decimal(1) if spot else _quantity(market.get("contractSize"), positive=True)
        precision = market.get("precision") or {}
        if precision.get("amount") is None or precision.get("price") is None:
            raise CChanException("market 缺少数量/价格精度", ErrCode.PARA_ERROR)
        definition = {"exchange": exchange.id, "id": market["id"], "symbol": code,
            "type": self.market_type, "base": market["base"], "quote": market["quote"],
            "settle": "" if spot else market["settle"], "contractSize": str(size),
            "precision_mode": exchange.precisionMode, "precision": precision,
            "limits": {key: (market.get("limits") or {}).get(key) or {} for key in ("amount", "price", "cost")}}
        # 复制完整有限字节，后续 metadata 原地变动不能回写已发布意图。
        return json.loads(canonical_bytes(definition)), market

    @staticmethod
    def _check_limits(definition, amount, price, cost):
        for key, value in (("amount", amount), ("price", price), ("cost", cost)):
            for bound, test in (("min", lambda x, y: x < y), ("max", lambda x, y: x > y)):
                limit = definition["limits"][key].get(bound)
                if limit is not None and test(value, _quantity(limit)):
                    raise CChanException(f"精度化后订单违反 market {key}.{bound}", ErrCode.QUOTA_NOT_ENOUGH)

    def prepare_order(self, code, amount, price, *, reduce_only=False, record=None, post_only=False):
        if self.dry_run:
            return super().prepare_order(code, amount, price, reduce_only=reduce_only, record=record, post_only=post_only)
        if type(post_only) is not bool or (post_only and price is None):
            raise CChanException("post-only 必须为明确 bool 且有价格", ErrCode.PARA_ERROR)
        self.safety_policy.assert_order_allowed()
        if self.chan_db.db_type != "sqlite":
            raise CChanException("MySQL 单位契约迁移/事务尚未验收", ErrCode.TRADE_UNLOCK_FAIL)
        if reduce_only and record is not None:
            # 自动平仓的数量来自 DB；旧数量没有单位证据时不能推断成币数。
            self._read_order_contract(code, {"phase": "open", "record": record})
        import ccxt
        try:
            definition, market = self._market_contract(code)
            execution = self._execution_settings(code, record, reduce_only=reduce_only)
            observation = self._observe_account(code, execution, reduce_only=reduce_only)
            if not reduce_only and market.get("active") is not True:
                raise CChanException("market 非明确 active，禁止新风险", ErrCode.TRADE_UNLOCK_FAIL)
            with localcontext() as context:
                context.prec = 50
                size = _quantity(definition["contractSize"], positive=True)
                desired = _quantity(amount, positive=True)
                amount = _quantity(self.get_exchange().amount_to_precision(code, str(desired/size)), positive=True)
                quantity = amount*size
                if quantity > desired:
                    raise CChanException("精度化不得向上扩大币数量", ErrCode.PARA_ERROR)
                price = None if price is None else _quantity(self.get_exchange().price_to_precision(code, price), positive=True)
                reference = price if price is not None else _quantity(self.get_exchange().fetch_ticker(code).get("last"), positive=True)
                self._check_limits(definition, amount, reference, quantity*reference)
                contract = {"schema": "chan-ccxt-order-v2", "market": definition, "quantity_unit": "base_currency",
                    "exchange_amount_unit": "base_currency" if self.market_type == "spot" else "contracts",
                    "quantity": str(quantity), "exchange_amount": str(amount),
                    "price": None if price is None else str(price), "reference_price": str(reference),
                    "notional": str(quantity*reference), "reduce_only": bool(reduce_only),
                    "execution": execution, "account_observation": observation, "post_only": post_only}
                contract["contract_id"] = _contract_id(contract)
                _float_exact(amount)  # 下单 API 的张数也不能被 float 静默改写。
                self.safety_policy.assert_order_allowed()
                return _float_exact(quantity), None if price is None else _float_exact(price), contract
        except ccxt.BaseError as error:
            raise CChanException("market metadata/精度校验失败，未取得订单意图", ErrCode.PARA_ERROR) from error

    def _read_order_contract(self, code, intent, *, amount=None, price=None, submitting=False):
        try:
            phase, record = intent["phase"], intent["record"]
            field = "open_order_contract" if phase == "open" else "cover_order_contract"
            raw = record.get(field)
            contract = json.loads(raw)
            expected_keys = {"schema", "market", "quantity_unit", "exchange_amount_unit", "quantity", "exchange_amount",
                             "price", "reference_price", "notional", "reduce_only", "contract_id"}
            v2 = contract.get("schema") == "chan-ccxt-order-v2"
            if v2:
                expected_keys |= {"execution", "account_observation", "post_only"}
            definition, market = self._market_contract(code)
            with localcontext() as context:
                context.prec = 50
                quantity, exchange_amount, reference = (_quantity(contract[k], positive=True)
                    for k in ("quantity", "exchange_amount", "reference_price"))
                frozen = contract["market"]
                size = _quantity(frozen["contractSize"], positive=True)
                unit_keys = set(definition)-{"precision", "precision_mode", "limits"}
                same_units = all(frozen.get(key) == definition[key] for key in unit_keys)
                requested = record["open_requested_qty" if phase == "open" else "cover_requested_qty"]
                if (set(contract) != expected_keys or canonical_bytes(contract).decode() != raw
                        or contract["schema"] not in {"chan-ccxt-order-v1", "chan-ccxt-order-v2"}
                        or contract["contract_id"] != _contract_id(contract)
                        or not same_units or (submitting and (frozen != definition or
                            (phase == "open" and market.get("active") is not True)))
                        or contract["quantity_unit"] != "base_currency"
                        or contract["exchange_amount_unit"] != ("base_currency" if self.market_type == "spot" else "contracts")
                        or contract["reduce_only"] is not (phase == "close") or record["stock_code"] != code
                        or quantity != exchange_amount*size or quantity != _quantity(requested, positive=True)
                        or _quantity(contract["notional"]) != quantity*reference
                        or (submitting and (quantity != _quantity(amount, positive=True)
                            or (None if price is None else _quantity(price, positive=True)) !=
                               (None if contract["price"] is None else _quantity(contract["price"], positive=True))))):
                    raise ValueError("order contract drift")
                self._check_limits(frozen, exchange_amount, reference, quantity*reference)
                if v2:
                    self._check_execution_evidence(contract, record, phase)
                if submitting:
                    if not v2 or contract["execution"] != self._execution_settings(code, record, reduce_only=phase == "close"):
                        raise ValueError("execution settings drift")
                    self._observe_account(code, contract["execution"], reduce_only=phase == "close")
                return contract
        except (TypeError, ValueError, KeyError, AttributeError) as error:
            raise CChanException("缺少完整订单单位契约或 market 漂移，禁止猜测重下/记账", ErrCode.TRADE_UNLOCK_FAIL) from error

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
        intent = self._validated_persisted_intent(
            code,
            is_buy,
            amount,
            client_order_id,
            reduce_only,
            side,
        )
        import ccxt  # 懒加载
        exchange = self.get_exchange()
        contract = self._read_order_contract(code, intent, amount=amount, price=price, submitting=True)
        params = self._venue_params(contract, client_order_id, is_buy=is_buy, reduce_only=reduce_only, post_only=post_only, side=side)
        self.safety_policy.assert_order_allowed()
        if not self.chan_db.claim_order_submission(intent["record"]["id"], intent["phase"]):
            raise CChanException("持久化意图已提交或被其他进程获取", ErrCode.TRADE_UNLOCK_FAIL)
        try:
            exchange_amount = _float_exact(_quantity(contract["exchange_amount"], positive=True))
            order_type = "market" if price is None else "limit"
            self.safety_policy.assert_order_allowed()
            order = exchange.create_order(
                code,
                order_type,
                "buy" if is_buy else "sell",
                exchange_amount,
                price,
                params,
            )
        except ccxt.BaseError as e:
            order_side = "buy" if is_buy else "sell"
            raise CChanException(
                f"下单失败 {code} {order_side} {amount}: {e}",
                ErrCode.PLACE_ORDER_FAIL,
            ) from e
        self._check_order_identity(order, code, intent, contract, partial=True)
        self.chan_db.record_order_ack(intent["record"]["id"], intent["phase"], str(order["id"]))
        if any(order.get(key) is None for key in ("symbol", "side", "type", "filled", "status")):
            return self.query_order(code, str(order["id"]), client_order_id=client_order_id)
        return self._result_from_ccxt(
            order, code=code, intent=intent, contract=contract
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
        intent = (self.chan_db.get_order_intent(client_order_id) if client_order_id else
                  self.chan_db.get_order_intent_by_order_id(code, str(order_id)) if order_id is not None else None)
        if intent is None:
            raise CChanException("查单缺少唯一持久化意图", ErrCode.LIST_ORDER_FAIL)
        prefix = "open" if intent["phase"] == "open" else "cover"
        record = intent["record"]
        known_id = record.get(f"{prefix}_order_id")
        if order_id is not None and known_id is not None and str(order_id) != str(known_id):
            raise CChanException("查单不能替换已知交易所订单号", ErrCode.LIST_ORDER_FAIL)
        known_id = known_id if known_id is not None else order_id
        client_order_id = record[f"{prefix}_client_order_id"]
        contract = self._read_order_contract(code, intent)
        try:
            order = self._fetch_persisted_order(code, known_id, client_order_id, record.get(f"{prefix}_intent_ms"))
        except ccxt.BaseError as e:
            identity = known_id or client_order_id
            raise CChanException(f"查单失败 {code} {identity}: {e}", ErrCode.LIST_ORDER_FAIL) from e
        try:
            result = self._result_from_ccxt(order, code=code, intent=intent, contract=contract)
        except CChanException as error:
            raise CChanException("查单回报尚不能安全记账", ErrCode.LIST_ORDER_FAIL) from error
        if known_id is not None and result.order_id != str(known_id):
            raise CChanException("交易所订单与持久化意图不匹配", ErrCode.LIST_ORDER_FAIL)
        if known_id is None:
            # Client ids may be reused by a venue after completion. A client-only
            # match must carry a creation clock from this UTC intent, not a local
            # timezone string or an older same-client order.
            at_ms, since = order.get("timestamp"), record.get(f"{prefix}_intent_ms")
            if (type(since) is not int or type(at_ms) is not int or at_ms < since
                    or at_ms > utc_now_ms() or self._order_client_id(order) != client_order_id):
                raise CChanException("客户端匹配缺少本意图 UTC/身份依据", ErrCode.LIST_ORDER_FAIL)
        self.chan_db.record_order_ack(record["id"], intent["phase"], result.order_id)
        return result

    def _fetch_persisted_order(self, code, order_id, client_id, since):
        import ccxt
        exchange = self.get_exchange()
        if order_id is not None:
            try:
                return exchange.fetch_order(str(order_id), code)
            except (ccxt.OrderNotFound, ccxt.NotSupported):
                pass
        venue = "binance" if exchange.id in {"binance", "binanceusdm"} else exchange.id
        if venue not in {"binance", "okx"}:
            raise CChanException("未支持该交易所恢复协议", ErrCode.LIST_ORDER_FAIL)
        key = "origClientOrderId" if venue == "binance" else "clOrdId"
        try:
            return exchange.fetch_order(None, code, {key: client_id})
        except (ccxt.OrderNotFound, ccxt.NotSupported):
            return self._find_order_in_history(code, client_id, since, venue)

    @staticmethod
    def _order_client_id(order):
        return order.get("clientOrderId") or order.get("client_order_id")

    def _find_order_in_history(self, code, client_id, since, venue):
        """Explicit bounded pagination; absence/expiry/ambiguity stays unresolved."""
        until = utc_now_ms()
        if type(since) is not int or since < 0 or not since <= until <= since+_HISTORY_MAX_AGE_MS:
            raise CChanException("历史补查缺少有效 UTC 意图边界或超出恢复窗口", ErrCode.LIST_ORDER_FAIL)
        exchange, pages, matches = self.get_exchange(), 0, {}

        def fetch_page(fetch, limit, start, end, params, *, ascending, cursor=None, pending=False):
            nonlocal pages
            if pages >= _HISTORY_MAX_PAGES:
                raise CChanException("历史补查页数预算耗尽，订单仍未知", ErrCode.LIST_ORDER_FAIL)
            pages += 1
            rows = fetch(code, None if pending else start, limit, params)
            if not isinstance(rows, list) or len(rows) > limit:
                raise CChanException("历史补查页结构无效", ErrCode.LIST_ORDER_FAIL)
            ids = set()
            for row in rows:
                identity = row.get("id") if isinstance(row, dict) else None
                at_ms = row.get("timestamp") if isinstance(row, dict) else None
                if (not isinstance(identity, str) or not identity.isascii() or not identity.isdecimal()
                        or str(int(identity)) != identity or type(at_ms) is not int
                        or row.get("symbol") != code or at_ms > end
                        or (not pending and at_ms < start)):
                    raise CChanException("历史补查缺少精确 id/UTC/symbol", ErrCode.LIST_ORDER_FAIL)
                value = int(identity)
                if value in ids or (cursor is not None and (value < cursor if ascending else value >= cursor)):
                    raise CChanException("历史补查游标无进展或重复 id", ErrCode.LIST_ORDER_FAIL)
                ids.add(value)
                if self._order_client_id(row) == client_id:
                    if at_ms < since or (identity in matches and matches[identity] != row):
                        raise CChanException("历史客户端号/回报身份冲突", ErrCode.LIST_ORDER_FAIL)
                    matches[identity] = row
            return len(rows), (max(ids)+1 if ascending else min(ids)) if ids else None

        if venue == "binance":
            start = since
            while start <= until:
                # Without orderId Binance returns the most recent page, even
                # with a startTime. Start explicitly before all positive ids.
                end, cursor = min(until, start+_HISTORY_WINDOW_MS-1), 1
                while True:
                    params = {"endTime": end, "orderId": str(cursor)}
                    size, cursor = fetch_page(exchange.fetch_orders, 1000, start, end, params, ascending=True, cursor=cursor)
                    if size < 1000:
                        break
                start = end+1
        else:
            # fetch_canceled_orders in CCXT 4.5.43 cannot route to Archive.
            # fetch_closed_orders passes the explicit state through to the same
            # native archive endpoint, including partially-filled cancellations.
            for state in ("pending", "filled", "canceled"):
                cursor = None
                while True:
                    params = {} if state == "pending" else {
                        "method": "privateGetTradeOrdersHistoryArchive", "state": state, "until": until}
                    if cursor is not None:
                        params["after"] = str(cursor)
                    fetch = exchange.fetch_open_orders if state == "pending" else exchange.fetch_closed_orders
                    size, cursor = fetch_page(fetch, 100, since, until, params, ascending=False, cursor=cursor, pending=state == "pending")
                    if size < 100:
                        break
        if len(matches) != 1:
            raise CChanException("历史客户端订单号未得到唯一回报，禁止重下", ErrCode.LIST_ORDER_FAIL)
        return next(iter(matches.values()))

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
            definition, _ = self._market_contract(code)
            size = _quantity(definition["contractSize"], positive=True)
            with localcontext() as context:
                context.prec = 50
                total = Decimal(0)
                for position in positions:
                    if position.get("symbol") not in {None, code}:
                        continue
                    amount = _quantity(position.get("contracts"))*size
                    if position.get("contractSize") is not None and _quantity(position["contractSize"], positive=True) != size:
                        raise CChanException("持仓 contractSize 与 market 不一致", ErrCode.GET_HOLDING_QTY_FAIL)
                    side = str(position.get("side") or "").lower()
                    if amount and side not in {"long", "short"}:
                        raise CChanException("持仓缺少明确方向", ErrCode.GET_HOLDING_QTY_FAIL)
                    total += -abs(amount) if side == "short" else abs(amount)
                return _float_exact(total) if total >= 0 else -_float_exact(-total)
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

    def _check_order_identity(self, order, code, intent, contract, *, partial=False):
        if (not isinstance(order, dict) or isinstance(order.get("id"), bool)
                or not isinstance(order.get("id"), (str, int)) or not str(order["id"]).strip()):
            raise CChanException("交易所回报缺少订单 id", ErrCode.LIST_ORDER_FAIL)
        requested_value = _quantity(contract["exchange_amount"], positive=True)
        if ((order.get("symbol") is not None or not partial) and order.get("symbol") != code
                or (order.get("amount") is not None and _quantity(order["amount"]) != requested_value)):
            raise CChanException("交易所订单 symbol/amount 与单位契约不一致", ErrCode.LIST_ORDER_FAIL)
        if (contract["price"] is not None and (order.get("price") is not None or not partial)
                and _quantity(order.get("price"), positive=True) != _quantity(contract["price"], positive=True)):
            raise CChanException("交易所限价与冻结意图不一致", ErrCode.LIST_ORDER_FAIL)
        record, phase = intent["record"], intent["phase"]
        client_order_id = record["open_client_order_id" if phase == "open" else "cover_client_order_id"]
        expected_id = record["open_order_id" if phase == "open" else "cover_order_id"]
        is_buy = bool(record["is_buy"]) if phase == "open" else not bool(record["is_buy"])
        if (((order.get("side") is not None or not partial) and order.get("side") != ("buy" if is_buy else "sell"))
                or ((order.get("type") is not None or not partial) and order.get("type") != ("market" if contract["price"] is None else "limit"))
                or (expected_id is not None and str(order["id"]) != str(expected_id))):
            raise CChanException("交易所订单方向/类型/id 与持久化意图不一致", ErrCode.LIST_ORDER_FAIL)
        client_value = self._order_client_id(order)
        if ((client_value is not None and client_value != client_order_id)
                or (partial and expected_id is None and client_value is None)):
            raise CChanException("交易所客户端订单号与持久化意图不一致", ErrCode.LIST_ORDER_FAIL)

    def _result_from_ccxt(
        self,
        order: dict,
        *, code, intent, contract,
    ) -> COrderResult:
        self._check_order_identity(order, code, intent, contract)
        self._check_execution_report(order, contract)
        filled = _quantity(order.get("filled"))
        average = _quantity(order.get("average"), positive=True) if filled else None
        if filled > _quantity(contract["exchange_amount"], positive=True):
            raise CChanException("交易所累计成交量超过请求量", ErrCode.LIST_ORDER_FAIL)
        record = intent["record"]
        client_value = self._order_client_id(order) or record["open_client_order_id" if intent["phase"] == "open" else "cover_client_order_id"]
        size = _quantity(contract["market"]["contractSize"], positive=True)
        with localcontext() as context:
            context.prec = 50
            filled_base = _float_exact(filled*size)
        return COrderResult(
            order_id=str(order["id"]),
            requested=float(_quantity(contract["quantity"], positive=True)),
            filled=filled_base,
            avg_price=None if average is None else _float_exact(average),
            status=_normalize_order_status(order.get("status")),
            client_order_id=(str(client_value) if client_value else None),
        )

    @staticmethod
    def _check_execution_report(order, contract):
        if contract["schema"] != "chan-ccxt-order-v2":
            return  # v1 remains read-only; it cannot authorize a new submission.
        execution, info = contract["execution"], order.get("info")
        if not isinstance(info, dict):
            raise CChanException("交易所缺少原生执行回报", ErrCode.LIST_ORDER_FAIL)
        swap = contract["market"]["type"] == "swap"
        if execution["venue"] == "binance":
            if (swap and info.get("positionSide") != execution["position_side"]
                    or info.get("timeInForce") not in {"GTC", "IOC", "FOK", "GTX"}):
                raise CChanException("Binance 回报缺少正确 leg/timeInForce", ErrCode.LIST_ORDER_FAIL)
            post_only = info.get("timeInForce") == "GTX" or info.get("type") == "LIMIT_MAKER"
        else:
            side = "net" if execution["position_mode"] == "one_way" else execution["position_side"].lower()
            if (info.get("tdMode") != execution["margin_mode"] or (swap and info.get("posSide") != side)
                    or info.get("ordType") not in {"limit", "market", "post_only"}):
                raise CChanException("OKX 回报缺少正确 leg/tdMode/ordType", ErrCode.LIST_ORDER_FAIL)
            post_only = info["ordType"] == "post_only"
        if post_only is not contract["post_only"]:
            raise CChanException("服务端 post-only 与冻结意图不一致", ErrCode.LIST_ORDER_FAIL)
        if swap and execution["position_mode"] == "one_way":
            reduced = info.get("reduceOnly")
            if isinstance(reduced, str) and reduced in {"true", "false"}:
                reduced = reduced == "true"
            if type(reduced) is not bool or reduced is not contract["reduce_only"]:
                raise CChanException("服务端 reduce-only 与冻结意图不一致", ErrCode.LIST_ORDER_FAIL)

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
