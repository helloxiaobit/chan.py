"""ccxt 下单引擎:显式订单意图、撮合、持仓查询和离线演练。

dry_run 模式绝不创建交易所会话。旧兼容路径保留立即/累计计划成交；显式
paper_account 使用共享 C4 费用/mark/funding/cross 账本和原订单恢复路径。
"""
import itertools
import copy
import hashlib
import json
import math
import re
from contextlib import nullcontext
from dataclasses import dataclass, field
from decimal import Context, Decimal, DecimalException, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, localcontext
from fractions import Fraction
from typing import Dict, List, Optional

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes

from .db_util import CChanDB
from .AccountIdentity import observe_account_context, verify_account_context
from .OpenQuotaGen import COpenQuotaGen
from .SafetyPolicy import build_trading_safety_policy
from .TradeEngine import COrderResult, CTradeEngine
from .PaperState import paper_state_operation


_CONTRACT_TYPES = {"swap", "future"}
_POSITION_SIDES = {"BOTH", "LONG", "SHORT"}
_PAPER_CONTEXT = Context(prec=50, Emax=100, Emin=-100)
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
    price: Optional[float]
    reduce_only: bool
    result: COrderResult
    fill_plan: List[float]
    next_fill: int = 0
    paper_contract: Optional[dict] = None
    paper_position_id: Optional[str] = None
    paper_role: str = "taker"
    paper_reason: Optional[str] = None


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
    paper_account: object = None  # 显式完整 paper；None 保留旧兼容撮合，不能冒称完整账户。
    paper_store: object = None  # 仅显式持久软件服务器；不得用于真实交易。


def verify_paper_order_state(state, paper):
    """Share the actual fill/average check between server reads and checkpoint restore."""
    with localcontext(_PAPER_CONTEXT):
        contract = state.paper_contract
        fills = [effect["request"] for effect in paper.to_dict()["effects"]
            if effect["request"]["kind"] == "fill" and effect["request"]["id"].startswith(f"fill:{state.result.order_id}:")]
        filled = sum((Decimal(f["quantity"]) for f in fills), Decimal(0))
        notional = sum((Decimal(f["quantity"])*Decimal(f["execution_price"]) for f in fills), Decimal(0))
        expected_average = float(notional/filled) if filled else None
        if (contract["contract_id"] != _contract_id(contract) or contract["paper_account"] != paper.identity_reference
                or _quantity(state.result.requested) != _quantity(contract["quantity"])
                or filled != _quantity(state.result.filled) or state.result.avg_price != expected_average
                or state.result.status not in COrderResult.VALID_STATUSES
                or (filled == _quantity(contract["quantity"])) != (state.result.status == "closed")
                or state.reduce_only is not contract["reduce_only"] or state.paper_role not in {"maker", "taker"}
                or state.fill_plan[-1] > state.result.requested
                or (state.next_fill == 0 and filled != 0)
                or (state.next_fill > 0 and state.fill_plan[state.next_fill-1] != state.result.filled)
                or any(f["position_id"] != state.paper_position_id or f["code"] != state.code
                    or f["is_buy"] is not state.is_buy or f["reduce_only"] is not state.reduce_only
                    or f["role"] != state.paper_role for f in fills)):
            raise CChanException("paper 累计回报与实际 fill 账本不一致", ErrCode.LIST_ORDER_FAIL)


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
        opening_inputs=None,
        paper_inputs=None,
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
        if self.sim_state.paper_account is not None:
            from .LinearPaperAccount import CLinearPaperAccount
            if not isinstance(self.sim_state.paper_account, CLinearPaperAccount) or self.market_type != "swap" or chan_db.db_type != "sqlite":
                raise CChanException("完整 paper 仅用于显式 SQLite USDT 线性永续", ErrCode.PARA_ERROR)
            if (any(order.paper_contract is None for order in self.sim_state.order_state.values())
                    or any(self.sim_state.positions.values())
                    or set(self.sim_state.orders) != set(self.sim_state.order_state)
                    or set(self.sim_state.orders) != set(self.sim_state.client_order_ids.values())
                    or any(key != order.result.order_id or self.sim_state.orders[key] is not order.result
                        for key, order in self.sim_state.order_state.items())):
                raise CChanException("旧简化模拟不能补造完整 paper 账户来源", ErrCode.PARA_ERROR)
        self._order_id_gen = self.sim_state.order_id_gen
        self._sim_orders = self.sim_state.orders
        self._sim_order_state = self.sim_state.order_state
        self._sim_client_order_ids = self.sim_state.client_order_ids
        self._sim_fill_plans = self.sim_state.fill_plans
        self._sim_positions = self.sim_state.positions
        self._sim_balance = self.sim_state.balance
        self._sim_last_price = self.sim_state.last_price
        if self.sim_state.paper_store is not None:
            from .PaperState import CPersistentPaperState
            if type(self.sim_state.paper_store) is not CPersistentPaperState:
                raise CChanException("paper store 必须由原有限字节 reader 打开", ErrCode.PARA_ERROR)
            self.sim_state.paper_store.bind_database(chan_db)
        self.opening_inputs = opening_inputs
        if opening_inputs is not None:
            from .Script.OpeningInputs import COpeningInputs
            if type(opening_inputs) is not COpeningInputs:
                raise CChanException("开仓输入必须由实际配置/来源 reader 构造，不能传 passed 标志", ErrCode.PARA_ERROR)
        self.paper_inputs = paper_inputs
        if paper_inputs is not None:
            from .PaperInputs import CSoftwarePaperInputs
            if type(paper_inputs) is not CSoftwarePaperInputs or self.sim_state.paper_store is None:
                raise CChanException("软件行情策略需要原持久 paper server/reader，不能传 ready 标志", ErrCode.PARA_ERROR)

    def check_open_inputs(self, record, *, price=None):
        if self.opening_inputs is not None:
            return self.opening_inputs.check(record, engine=self, price=price)
        return None

    def _native_entry_profile(self):
        """Read only the original guard's frozen config, never trade_info proof."""
        from .NativeCurrentComponents import read_native_component_policy
        from . import NativePreparedIntent as Prepared
        from . import NativeOrderBoundary as Boundary
        from .AccountSources import SNAPSHOT_SCHEMA
        from .AccountStore import read_evidence
        from .Script.OpeningInputs import COpeningInputs
        try:
            guard = self.opening_inputs
            if type(guard) is not COpeningInputs:
                raise ValueError
            chan = self.chan_db
            database = Boundary._database(chan)
            connection, table = database.conn, chan.table
            guard.assert_current()
            Boundary._same_database(chan, database, connection, table, owned=False)
            if self.chan_db is not chan or self.opening_inputs is not guard:
                raise ValueError
            profile = guard.env.get_section("trade").get("native_admission")
            budgets = {name+suffix for name in ("instrument", "capacity", "last")
                       for suffix in ("_max_age_ms", "_max_observation_span_ms")}
            if (type(profile) is not dict or set(profile) != budgets | {"schema", "before_id", "account_scope", "policy"}
                    or profile["schema"] != "chan-native-entry-profile-v1"
                    or type(profile["before_id"]) is not str or re.fullmatch(r"[0-9a-f]{64}", profile["before_id"]) is None
                    or type(profile["account_scope"]) is not str or re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", profile["account_scope"]) is None
                    or self.ccxt_conf.get("exchange") not in {"binance", "binanceusdm"}):
                raise ValueError
            for name in budgets:
                Prepared._budget(profile[name])
            read_native_component_policy(profile["policy"])
            with database.transaction():
                Boundary._same_database(chan, database, connection, table, owned=True)
                before = read_evidence(database, profile["before_id"])
                if (before["schema"] != SNAPSHOT_SCHEMA or before["payload"]["account_context"]["mode"] != self.mode
                        or before["payload"]["account_context"]["venue"] != "binance"):
                    raise ValueError
                chan.assert_account_new_risk_allowed(before["payload"]["account_context"])
                Boundary._same_database(chan, database, connection, table, owned=True)
                if self.chan_db is not chan or self.opening_inputs is not guard:
                    raise ValueError
            Boundary._same_database(chan, database, connection, table, owned=False)
            return json.loads(canonical_bytes(profile))
        except Exception:
            raise CChanException("原生新风险profile须来自原配置，完整声明before/政策/预算且不得降级", ErrCode.CONFIG_ERROR) from None

    def _acquire_open_intent(self, record, price, *, snapshot, score_before):
        # Native new risk cannot downgrade to old v3 when its guard is absent.
        # Existing-order readers and reduce-only preparation remain separate.
        if self.dry_run or self.market_type != "swap":
            return super()._acquire_open_intent(record, price, snapshot=snapshot, score_before=score_before)
        from . import NativePreparation as Prepare
        from . import NativePreparedIntent as Prepared
        from . import NativeOrderBoundary as Boundary
        from . import NativeOrderTransition as Transition
        profile = self._native_entry_profile()
        Prepare._selected_runtime(self, self.opening_inputs, self.safety_policy)
        if self.exchange is None:
            from .NativePreparedClient import initialize_native_prepared_client
            initialize_native_prepared_client(self, record["id"],
                instrument_max_age_ms=profile["instrument_max_age_ms"],
                instrument_max_observation_span_ms=profile["instrument_max_observation_span_ms"])
        chan, guard, client = self.chan_db, self.opening_inputs, self.exchange
        database = Boundary._database(chan)
        connection, table = database.conn, chan.table
        def owners(*, owned=False):
            Boundary._same_database(chan, database, connection, table, owned=owned)
            if self.chan_db is not chan or self.opening_inputs is not guard or self.exchange is not client:
                Prepared._fail()
        owners()
        amount = self.quota_gen.get_quota(record["stock_code"], price)
        owners()
        if not math.isfinite(amount) or amount <= 0:
            raise CChanException("仓位计算必须为正有限币数量", ErrCode.QUOTA_NOT_ENOUGH)
        client_id = self.make_client_order_id(record, "open")
        owners()
        if not Prepared.acquire_binance_standard_prepared_intent(self, record["id"], amount, price,
                **{name: value for name, value in profile.items() if name != "schema"},
                client_order_id=client_id, entry_assessment=snapshot.get("entry_assessment")):
            raise CChanException("原金额意图已被其他进程获取", ErrCode.SIGNAL_TRADED)
        owners()
        with database.transaction():
            owners(owned=True)
            current = chan.get_record(record["id"])
            owners(owned=True)
            document = Transition._read(chan, current)
            owners(owned=True)
            binding = document["payload"]["root"]["preparation"]
            contract = Prepared._contract(binding)
            if (self.chan_db is not chan or self.opening_inputs is not guard or self.exchange is not client
                    or document["payload"]["stage"] != "intent" or binding["schema"] != Prepared.MONETARY_BINDING_SCHEMA
                    or current["open_client_order_id"] != client_id
                    or current["open_order_contract"] != canonical_bytes(contract).decode()):
                Prepared._fail()
            owners(owned=True)
        owners()
        return (_float_exact(_quantity(contract["quantity"], positive=True)),
                None if contract["price"] is None else _float_exact(_quantity(contract["price"], positive=True)), client_id)

    def _software_quote_bound(self, record):
        from Common.MarketQuote import SOFTWARE_SCHEMA
        try:
            record = record or {}
            bounds = []
            for name in ("open_order_contract", "cover_order_contract"):
                contract = json.loads(record[name]) if record.get(name) else {}
                if contract.get("schema") == "chan-paper-order-v3":
                    bounds.append(contract["software_quote_max_age_ms"])
            snapshot = json.loads(record.get("snapshot_before") or "{}")
            batch = snapshot.get("opening_inputs", {}).get("quote", {}).get("batch", {})
            if batch.get("schema") == SOFTWARE_SCHEMA:
                bounds.append(batch["payload"]["software_max_age_ms"])
            if any(type(value) is not int or not 0 < value < 2**63 for value in bounds):
                raise ValueError("invalid stored policy")
            return min(bounds) if bounds else None
        except (ValueError, KeyError, TypeError, AttributeError):
            raise CChanException("原软件行情策略证据无效，禁止降级或猜测成交", ErrCode.LIST_ORDER_FAIL) from None

    def _check_paper_inputs(self, code, record):
        bound = self._software_quote_bound(record)
        if self.paper_inputs is not None:
            self.paper_inputs.check(self, code, max_age_ms=bound)
        elif bound is not None:
            raise CChanException("原软件来源单需要行情 reader，不能降级到旧模拟", ErrCode.SNAPSHOT_ERR)

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
        if self.sim_state.paper_account is not None:
            raise CChanException("完整 paper 必须 set_sim_quote 显式提供 UTC/bid/ask/mark", ErrCode.PARA_ERROR)
        self._sim_last_price[code] = price

    def _paper(self):
        account = self.sim_state.paper_account
        if not self.dry_run or account is None:
            raise CChanException("需要显式完整 paper，不能建立真实会话或用旧撮合补证", ErrCode.PARA_ERROR)
        if self.sim_state.paper_store is not None:
            self.sim_state.paper_store.assert_current(self.sim_state)
        account.assert_identity()
        return account

    @paper_state_operation
    def set_sim_quote(self, code, *, at_ms, bid, ask, mark_price):
        return self._paper().set_quote(code, at_ms=at_ms, bid=bid, ask=ask, mark_price=mark_price)

    @paper_state_operation
    def apply_sim_funding(self, code, *, at_ms, rate, mark_price, event_id):
        return self._paper().apply_funding(code, at_ms=at_ms, rate=rate, mark_price=mark_price, event_id=event_id)

    def get_sim_account_report(self):
        return self._paper().to_dict()

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
            if opened["schema"] in {"chan-ccxt-order-v3", "chan-native-client-order-v1"} or (self.market_type == "spot" and opened["schema"] == "chan-ccxt-order-v2"):
                return dict(opened["execution"])
            raise CChanException("旧契约只读恢复：自动操作前须显式补足原账户/执行设置证据", ErrCode.TRADE_UNLOCK_FAIL)
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
            if self.sim_state.paper_account is not None:
                paper = self._paper()
                if record.get("status") == "signal":
                    return "BOTH" if paper.position_mode == "one_way" else "LONG" if record["is_buy"] else "SHORT"
            return super()._position_side(record)
        return self._execution_settings(record["stock_code"], record,
            reduce_only=record.get("status") != "signal")["position_side"]

    def _observe_account(self, code, execution, *, reduce_only, _assert_current=None):
        if self.market_type == "spot":
            return None
        import ccxt
        exchange = self.get_exchange()
        args = {"marginMode": execution["margin_mode"]} if execution["venue"] == "okx" else {}
        try:
            mode = exchange.fetch_position_mode(code)
            if _assert_current is not None:
                _assert_current()
            leverage = exchange.fetch_leverage(code, args)
            if _assert_current is not None:
                _assert_current()
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

    @paper_state_operation
    def set_sim_fill_plan(
        self, client_order_id: str, cumulative_fills: List[float]
    ) -> None:
        """为下一张指定客户端订单设置累计成交序列。"""
        if not client_order_id or not cumulative_fills:
            raise CChanException("dry_run 成交计划不能为空", ErrCode.PARA_ERROR)
        if self.sim_state.paper_account is not None and any(type(v) is bool for v in cumulative_fills):
            raise CChanException("paper 累计量不能使用 bool", ErrCode.PARA_ERROR)
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
        chan = self.chan_db
        database = None
        if getattr(chan, "db_type", None) == "sqlite":
            from . import NativeOrderBoundary as Boundary
            database = Boundary._database(chan)
            connection, table, owned = database.conn, chan.table, database.conn.in_transaction
            Boundary._same_database(chan, database, connection, table, owned=owned)
        intent = chan.get_order_intent(client_order_id)
        if self.chan_db is not chan:
            raise CChanException("订单意图读取的原数据库owner已变", ErrCode.TRADE_UNLOCK_FAIL)
        if database is not None:
            Boundary._same_database(chan, database, connection, table, owned=owned)
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
        if phase == "open" and getattr(self.chan_db, "db_type", None) == "sqlite":
            history = self.chan_db.get_order_history(record["id"])
            native = any(a["identity"]["phase"] == "open" and a["identity"]["attempt"] == record["open_attempt"]
                         and a["events"][0].get("native_boundary_sha256") is not None for a in history["attempts"])
            if native:
                from .NativeOrderTransition import PREPARED_DOCUMENT_SCHEMA, read_native_order_transition
                from .NativePreparedIntent import MONETARY_BINDING_SCHEMA
                document = read_native_order_transition(self.chan_db, record["id"])
                if (document["schema"] == PREPARED_DOCUMENT_SCHEMA
                        and document["payload"]["stage"] == "intent"
                        and document["payload"]["root"]["preparation"]["schema"] == MONETARY_BINDING_SCHEMA):
                    from .NativePreparedIntent import assert_native_prepared_intent_current
                    with self.chan_db.db.transaction():
                        assert_native_prepared_intent_current(self, record["id"])
                else:
                    raise CChanException("原生逐单引用仅证明一致性，资金能力及完整发送消费者尚未验收", ErrCode.TRADE_UNLOCK_FAIL)
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
            if self.sim_state.paper_account is not None:
                return self._prepare_paper_order(code, amount, price, reduce_only=reduce_only, record=record, post_only=post_only)
            return super().prepare_order(code, amount, price, reduce_only=reduce_only, record=record, post_only=post_only)
        if type(post_only) is not bool or (post_only and price is None):
            raise CChanException("post-only 必须为明确 bool 且有价格", ErrCode.PARA_ERROR)
        self.safety_policy.assert_order_allowed()
        if self.chan_db.db_type != "sqlite":
            raise CChanException("MySQL 单位契约迁移/事务尚未验收", ErrCode.TRADE_UNLOCK_FAIL)
        opened = None
        if reduce_only and record is not None:
            # 自动平仓的数量来自 DB；旧数量没有单位证据时不能推断成币数。
            opened = self._read_order_contract(code, {"phase": "open", "record": record})
        import ccxt
        try:
            definition, market = self._market_contract(code)
            execution = self._execution_settings(code, record, reduce_only=reduce_only)
            account = None if self.market_type == "spot" else observe_account_context(self.get_exchange(), self.mode)
            if account is not None and not reduce_only:
                self.chan_db.assert_account_new_risk_allowed(account)
            if opened is not None and opened.get("account_context") != account:
                raise CChanException("降风险意图不得切换原账户/环境", ErrCode.TRADE_UNLOCK_FAIL)
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
                if account is not None:
                    contract.update(schema="chan-ccxt-order-v3", account_context=account)
                    self._assert_account_context(contract)
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
            version = contract.get("schema")
            owner = self._monetary_consumer_owner(contract)
            monetary = version == "chan-native-client-order-v1"
            execution_version = version in {"chan-ccxt-order-v2", "chan-ccxt-order-v3", "chan-native-client-order-v1"}
            if execution_version:
                expected_keys |= {"execution", "account_observation", "post_only"}
            if version in {"chan-ccxt-order-v3", "chan-native-client-order-v1"}:
                expected_keys.add("account_context")
            if monetary:
                expected_keys.add("monetary_basis_sha256")
                self._assert_persisted_monetary_contract(intent, contract, submitting=submitting)
                owner()
                if not submitting and self.exchange is None:
                    from .NativePreparedClient import initialize_native_order_recovery_client
                    initialize_native_order_recovery_client(self, record["id"])
                    owner = self._monetary_consumer_owner(contract)
            elif getattr(self.chan_db, "db_type", None) == "sqlite":
                # The projection label cannot erase an original native CAS.
                # Reuse the existing history reader, including its immutable
                # identity-vs-current-projection check, before any native I/O.
                history = self.chan_db.get_order_history(record["id"])
                if any(attempt["identity"]["phase"] == phase
                       and attempt["events"][0].get("native_boundary_sha256") is not None
                       for attempt in history["attempts"]):
                    raise ValueError("native order lineage cannot be downgraded")
            definition, market = self._market_contract(code)
            owner()
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
                        or version not in {"chan-ccxt-order-v1", "chan-ccxt-order-v2", "chan-ccxt-order-v3", "chan-native-client-order-v1"}
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
                if execution_version:
                    self._check_execution_evidence(contract, record, phase)
                self._assert_account_context(contract)
                owner()
                if submitting:
                    # Monetary L1 was fully reconstructed above, not accepted
                    # from the schema label alone. Old diagnostic v2/v3 cannot
                    # enter this branch.
                    if (not execution_version or (self.market_type == "swap" and version != "chan-ccxt-order-v3" and not monetary)
                            or contract["execution"] != self._execution_settings(code, record, reduce_only=phase == "close")):
                        raise ValueError("execution settings drift")
                    self._observe_account(code, contract["execution"], reduce_only=phase == "close",
                        **({"_assert_current": owner} if monetary else {}))
                    self._assert_account_context(contract)
                return contract
        except (TypeError, ValueError, KeyError, AttributeError) as error:
            raise CChanException("缺少完整订单单位契约或 market 漂移，禁止猜测重下/记账", ErrCode.TRADE_UNLOCK_FAIL) from error

    def _monetary_consumer_owner(self, contract):
        """Pin the actual reader/SDK owner across lock-free native callbacks."""
        if contract.get("schema") != "chan-native-client-order-v1":
            return lambda: None  # Keep original legacy recovery contracts.
        from . import NativeOrderBoundary as Boundary
        from . import NativePreparation as Prepare
        chan = self.chan_db
        database = Boundary._database(chan)
        connection, table, exchange, mode = database.conn, chan.table, self.exchange, self.mode
        client_binding = None if exchange is None else Prepare._client_binding(exchange)
        def check(*, owned=False):
            Boundary._same_database(chan, database, connection, table, owned=owned)
            if self.chan_db is not chan or self.exchange is not exchange or self.mode != mode:
                raise CChanException("原生订单消费者的实际账户/DB/SDK owner已变", ErrCode.TRADE_UNLOCK_FAIL)
            if exchange is not None and Prepare._client_binding(exchange) != client_binding:
                raise CChanException("原生订单消费者的SDK/cache/凭据已变", ErrCode.TRADE_UNLOCK_FAIL)
            if exchange is not None:
                Prepare._assert_execution_sdk(exchange, mode)
            from . import OrderAudit as audit
            modules = {}
            for name in ("_native_terminal_observation", "_sdk_submission_report", "_assert_sdk_submission",
                         "_append", "_read_attempt", "read_history", "_history_header"):
                Prepare._function_identity("Trade.OrderAudit", name, getattr(audit, name), modules)
        check()
        return check

    def _assert_persisted_monetary_contract(self, intent, contract, *, submitting=False):
        """Read original historical monetary facts, never trust a caller DTO.

        Existing-risk recovery does not renew source windows or acquire send
        permission. The original immutable L2 is required for that recovery.
        """
        from . import NativeOrderBoundary as Boundary
        from . import NativeOrderTransition as Transition
        from . import NativePreparedIntent as Prepared
        chan = self.chan_db
        database = Boundary._database(chan)
        connection, table = database.conn, chan.table
        with database.transaction():
            Boundary._same_database(chan, database, connection, table, owned=True)
            record = chan.get_record(intent["record"]["id"])
            if (self.chan_db is not chan or intent["phase"] != "open"
                    or canonical_bytes(record) != canonical_bytes(intent["record"])):
                raise CChanException("金额契约缺少原始持久化订单身份", ErrCode.TRADE_UNLOCK_FAIL)
            document = Transition._read(chan, record)
            Boundary._same_database(chan, database, connection, table, owned=True)
            binding = document["payload"]["root"]["preparation"]
            if (self.chan_db is not chan or document["schema"] != Transition.PREPARED_DOCUMENT_SCHEMA
                    or document["payload"]["stage"] != ("intent" if submitting else "claim")
                    or binding["schema"] != Prepared.MONETARY_BINDING_SCHEMA
                    or canonical_bytes(contract) != canonical_bytes(Prepared._contract(binding))):
                raise CChanException("金额契约与原始同次准备/L1/L2不一致", ErrCode.TRADE_UNLOCK_FAIL)

    def _assert_account_context(self, contract):
        if contract["schema"] not in {"chan-ccxt-order-v3", "chan-native-client-order-v1"}:
            return  # No fictional native identity is added to legacy contracts.
        frozen = contract["account_context"]
        verify_account_context(frozen)
        venue = contract["market"]["exchange"]
        venue = "binance" if venue in {"binance", "binanceusdm"} else venue
        if (contract["market"]["type"] != "swap" or frozen["venue"] != venue or frozen["mode"] != self.mode
                or frozen != observe_account_context(self.get_exchange(), self.mode)):
            raise CChanException("订单冻结账户/环境与当前原生身份不一致", ErrCode.TRADE_UNLOCK_FAIL)

    # ===== 撮合接口 =====
    @paper_state_operation
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
            if self.sim_state.paper_account is not None:
                return self._place_paper_order(code, is_buy, amount, price, client_order_id, reduce_only, post_only, side)
            return self._sim_place_order(
                code,
                is_buy,
                amount,
                price,
                client_order_id=client_order_id,
                reduce_only=reduce_only,
                position_side=side,
                post_only=post_only,
            )
        self.safety_policy.assert_order_allowed()
        if not reduce_only and self.market_type == "swap" and getattr(self.chan_db, "db_type", None) != "sqlite":
            raise CChanException("原生swap新风险仅允许原SQLite金额意图，未验证后端不能降级", ErrCode.TRADE_UNLOCK_FAIL)
        intent = self._validated_persisted_intent(
            code,
            is_buy,
            amount,
            client_order_id,
            reduce_only,
            side,
        )
        if not reduce_only and self.market_type == "swap":
            # This is the native branch, not the shared paper validator. A
            # later dry_run change cannot turn a started native call into paper.
            record = intent["record"]
            history = self.chan_db.get_order_history(record["id"])
            if not any(a["identity"]["phase"] == "open" and a["identity"]["attempt"] == record["open_attempt"]
                       and a["events"][0].get("native_boundary_sha256") is not None for a in history["attempts"]):
                raise CChanException("原生swap新风险必须有同次金额CAS，旧契约仅可恢复管理", ErrCode.TRADE_UNLOCK_FAIL)
        import ccxt  # 懒加载
        exchange = self.get_exchange()
        contract = self._read_order_contract(code, intent, amount=amount, price=price, submitting=True)
        owner = self._monetary_consumer_owner(contract)
        params = self._venue_params(contract, client_order_id, is_buy=is_buy, reduce_only=reduce_only, post_only=post_only, side=side)
        owner()
        self.safety_policy.assert_order_allowed()
        if not reduce_only:
            self.check_open_inputs(intent["record"])
        owner()
        if contract.get("schema") == "chan-native-client-order-v1":
            from .NativePreparedIntent import _capture_native_claim_context
            chan = self.chan_db
            with chan.db.transaction():
                owner(owned=True)
                context = _capture_native_claim_context(self, intent["record"]["id"])
                owner(owned=True)
                claimed = chan.claim_order_submission(intent["record"]["id"], intent["phase"], native_claim=context)
                owner(owned=True)
            owner()
        else:
            claimed = self.chan_db.claim_order_submission(intent["record"]["id"], intent["phase"])
        if not claimed:
            raise CChanException("持久化意图已提交或被其他进程获取", ErrCode.TRADE_UNLOCK_FAIL)
        try:
            exchange_amount = _float_exact(_quantity(contract["exchange_amount"], positive=True))
            order_type = "market" if price is None else "limit"
            self.safety_policy.assert_order_allowed()
            if not reduce_only and contract.get("schema") == "chan-ccxt-order-v3":
                self.chan_db.assert_account_new_risk_allowed(contract["account_context"])
            if not reduce_only:
                self.check_open_inputs(intent["record"])
            http_scope = nullcontext()
            if contract.get("schema") == "chan-native-client-order-v1":
                from .NativePreparation import _selected_runtime
                from .NativePreparedIntent import _native_prepared_claim_http_use
                _selected_runtime(self, self.opening_inputs, self.safety_policy)
                http_scope = _native_prepared_claim_http_use(self, intent["record"]["id"])
            with http_scope:
                order = exchange.create_order(
                    code,
                    order_type,
                    "buy" if is_buy else "sell",
                    exchange_amount,
                    price,
                    params,
                )
        except ccxt.BaseError as e:
            if contract.get("schema") == "chan-native-client-order-v1":
                raise CChanException("原生订单提交结果未知，保留原意图且禁止据此重下", ErrCode.PLACE_ORDER_FAIL) from None
            order_side = "buy" if is_buy else "sell"
            raise CChanException(
                f"下单失败 {code} {order_side} {amount}: {e}",
                ErrCode.PLACE_ORDER_FAIL,
            ) from e
        owner()
        self._assert_account_context(contract)
        owner()
        self._check_order_identity(order, code, intent, contract, partial=True)
        owner()
        self.chan_db.record_order_ack(intent["record"]["id"], intent["phase"], str(order["id"]), client_order_id=client_order_id,
            expected_attempt=intent["record"]["open_attempt" if intent["phase"] == "open" else "cover_attempt"])
        owner()
        if any(order.get(key) is None for key in ("symbol", "side", "type", "filled", "status")):
            return self.query_order(code, str(order["id"]), client_order_id=client_order_id)
        result = self._result_from_ccxt(
            order, code=code, intent=intent, contract=contract
        )
        if contract.get("schema") == "chan-native-client-order-v1":
            from . import OrderAudit as audit
            import sqlite3
            owner()
            report = audit._sdk_submission_report({key: getattr(result, key) for key in
                ("order_id", "client_order_id", "requested", "filled", "avg_price", "status")})
            owner()
            chan, database = self.chan_db, self.chan_db.db
            prefix = "open" if intent["phase"] == "open" else "cover"
            try:
                with database.transaction():
                    owner(owned=True)
                    fresh = chan.get_record(intent["record"]["id"])
                    owner(owned=True)
                    audit.read_history(database, chan.table, fresh)
                    owner(owned=True)
                    row = audit._ensure(database, chan.table, fresh, prefix)
                    owner(owned=True)
                    audit._append(database, row, "sdk_submission_report", audit._state(fresh, prefix),
                        submission_report=report, _assert_current=lambda: owner(owned=True))
                    owner(owned=True)
                    audit.read_history(database, chan.table, chan.get_record(fresh["id"]))
                    owner(owned=True)
            except sqlite3.DatabaseError:
                raise CChanException("提交累计事实发布失败，保留原ACK及未知意图", ErrCode.LIST_ORDER_FAIL) from None
            owner()
            if result.status in {"closed", "canceled", "rejected"}:
                return self.query_order(code, result.order_id, client_order_id=client_order_id)
        return result

    @paper_state_operation
    def cancel_order(self, code: str, order_id: str) -> bool:
        if self.dry_run:
            if self.sim_state.paper_account is not None:
                state = self._paper_state(code, order_id, None)
                if state.result.status == "open":
                    state.result.status = "canceled"
                return True
            if order_id in self._sim_orders:
                self._sim_orders[order_id].status = "canceled"
            return True
        import ccxt
        intent = self.chan_db.get_order_intent_by_order_id(code, str(order_id))
        if intent is None:
            raise CChanException("撤单缺少唯一持久化意图", ErrCode.CANDEL_ORDER_FAIL)
        contract = self._read_order_contract(code, intent)
        owner = self._monetary_consumer_owner(contract)
        owner()
        if self.market_type == "swap" and contract["schema"] not in {"chan-ccxt-order-v3", "chan-native-client-order-v1"}:
            raise CChanException("旧永续契约撤单需先证明原账户归属", ErrCode.CANDEL_ORDER_FAIL)
        try:
            response = self.get_exchange().cancel_order(order_id, code)
            owner()
            self._assert_account_context(contract)
            owner()
            if contract["schema"] == "chan-native-client-order-v1":
                # Cancel responses need not carry a fill average. Validate
                # identity/terms, but leave cumulative application to query.
                self._check_order_identity(response, code, intent, contract, partial=True)
                self._check_execution_report(response, contract)
                owner()
            return True
        except ccxt.BaseError as e:
            if contract.get("schema") == "chan-native-client-order-v1":
                raise CChanException("原生撤单结果未知，保留原意图并按原订单查询核实", ErrCode.CANDEL_ORDER_FAIL) from None
            raise CChanException(f"撤单失败 {code} {order_id}: {e}", ErrCode.CANDEL_ORDER_FAIL) from e

    @paper_state_operation
    def query_order(
        self,
        code: str,
        order_id: Optional[str] = None,
        *,
        client_order_id: Optional[str] = None,
    ) -> COrderResult:
        if self.dry_run:
            if self.sim_state.paper_account is not None:
                state = self._paper_state(code, order_id, client_order_id)
                intent = self.chan_db.get_order_intent(state.result.client_order_id)
                bound = self._software_quote_bound(intent["record"])
                available = (self.paper_inputs.available(self, code, max_age_ms=bound) if self.paper_inputs is not None else bound is None)
                if state.result.status == "open" and available:
                    self._advance_paper_order(state)
                return copy.copy(state.result)
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
        identity_was_persisted = known_id is not None
        if order_id is not None and known_id is not None and str(order_id) != str(known_id):
            raise CChanException("查单不能替换已知交易所订单号", ErrCode.LIST_ORDER_FAIL)
        known_id = known_id if known_id is not None else order_id
        client_order_id = record[f"{prefix}_client_order_id"]
        contract = self._read_order_contract(code, intent)
        owner = self._monetary_consumer_owner(contract)
        owner()
        native_terminal = contract.get("schema") == "chan-native-client-order-v1"
        query_started = utc_now_ms() if native_terminal else None
        try:
            order = self._fetch_persisted_order(code, known_id, client_order_id, record.get(f"{prefix}_intent_ms"))
            owner()
        except ccxt.BaseError as e:
            if native_terminal:
                raise CChanException("原生查单来源不可用，保留原未知意图且禁止据此重下", ErrCode.LIST_ORDER_FAIL) from None
            identity = known_id or client_order_id
            raise CChanException(f"查单失败 {code} {identity}: {e}", ErrCode.LIST_ORDER_FAIL) from e
        self._assert_account_context(contract)
        owner()
        try:
            result = self._result_from_ccxt(order, code=code, intent=intent, contract=contract)
            owner()
        except CChanException as error:
            raise CChanException("查单回报尚不能安全记账", ErrCode.LIST_ORDER_FAIL) from error
        if known_id is not None and result.order_id != str(known_id):
            raise CChanException("交易所订单与持久化意图不匹配", ErrCode.LIST_ORDER_FAIL)
        if not identity_was_persisted:
            # Client ids may be reused by a venue after completion. A client-only
            # match must carry a creation clock from this UTC intent, not a local
            # timezone string or an older same-client order.
            at_ms, since = order.get("timestamp"), record.get(f"{prefix}_intent_ms")
            if (type(since) is not int or type(at_ms) is not int or at_ms < since
                    or at_ms > utc_now_ms() or self._order_client_id(order) != client_order_id):
                raise CChanException("客户端匹配缺少本意图 UTC/身份依据", ErrCode.LIST_ORDER_FAIL)
        owner()
        if native_terminal:
            from . import OrderAudit as audit
            history = audit.read_history(self.chan_db.db, self.chan_db.table, record)
            owner()
            attempts = [attempt for attempt in history["attempts"] if attempt["identity"]["phase"] == intent["phase"]
                        and attempt["identity"]["attempt"] == record.get(f"{prefix}_attempt")]
            if len(attempts) != 1:
                raise CChanException("查单缺少唯一原尝试历史", ErrCode.LIST_ORDER_FAIL)
            audit._assert_sdk_submission(attempts[0], {key: getattr(result, key) for key in
                ("order_id", "client_order_id", "requested", "filled", "avg_price", "status")})
            owner()
        if native_terminal and result.status in {"closed", "canceled", "rejected"}:
            from . import OrderAudit as audit
            from .NativePendingOrders import _raw_order
            chan, database = self.chan_db, self.chan_db.db
            observation = audit._native_terminal_observation(audit._identity(chan.table, record, prefix),
                _raw_order(order["info"], contract["account_context"]["venue"]), query_started, utc_now_ms())
            observed = observation["payload"]
            if (observed["native_order_id"] != result.order_id or observed["client_order_id"] != result.client_order_id
                    or observed["status"] != result.status or _quantity(observed["requested_base_quantity"]) != _quantity(result.requested)
                    or _quantity(observed["filled_base_quantity"]) != _quantity(result.filled)
                    or (None if observed["average_price"] is None else _quantity(observed["average_price"])) !=
                       (None if result.avg_price is None else _quantity(result.avg_price))):
                raise CChanException("原生终态累计量与原SDK回报不一致", ErrCode.LIST_ORDER_FAIL)
            owner()
            import sqlite3
            try:
                with database.transaction():
                    owner(owned=True)
                    chan.record_order_ack(record["id"], intent["phase"], result.order_id, client_order_id=client_order_id,
                        expected_attempt=record.get(f"{prefix}_attempt"))
                    owner(owned=True)
                    fresh = chan.get_record(record["id"])
                    audit.read_history(database, chan.table, fresh)
                    owner(owned=True)
                    row = audit._ensure(database, chan.table, fresh, prefix)
                    owner(owned=True)
                    audit._append(database, row, "native_terminal_observation", audit._state(fresh, prefix),
                                  native_order_observation=observation, _assert_current=lambda: owner(owned=True))
                    owner(owned=True)
                    audit.read_history(database, chan.table, chan.get_record(record["id"]))
                    owner(owned=True)
            except sqlite3.DatabaseError:
                raise CChanException("原生终态来源发布失败，原ACK及来源写入整组回滚", ErrCode.LIST_ORDER_FAIL) from None
            owner()
        else:
            self.chan_db.record_order_ack(record["id"], intent["phase"], result.order_id, client_order_id=client_order_id,
                expected_attempt=record.get(f"{prefix}_attempt"))
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
            if self.sim_state.paper_account is not None:
                return {"USDT": float(self._paper().snapshot()["cash"])}
            return dict(self._sim_balance)
        import ccxt
        try:
            balance = self.get_exchange().fetch_balance()
        except ccxt.BaseError as e:
            raise CChanException(f"查余额失败: {e}", ErrCode.GET_HOLDING_QTY_FAIL) from e
        return {k: v for k, v in balance.get("total", {}).items() if v}

    def sync_execution_facts(self, code, *, account_scope, start_ms, end_ms):
        """Explicit read/import only; does not reconcile, release risk or book orders."""
        self._assert_native_source_session()
        from .ExecutionFacts import collect_execution_scan
        definition, _ = self._market_contract(code)
        started = utc_now_ms()
        before = observe_account_context(self.get_exchange(), self.mode)
        receipt = collect_execution_scan(self.get_exchange(), definition, account_scope=account_scope,
                                         mode=self.mode, start_ms=start_ms, end_ms=end_ms)
        after = observe_account_context(self.get_exchange(), self.mode)
        self.chan_db.store_execution_scan(receipt, account_observation={"before": before, "after": after,
            "started_ms": started, "finished_ms": utc_now_ms()})
        return receipt

    def _assert_native_source_session(self):
        if self.dry_run or self.market_type != "swap" or self.chan_db.db_type != "sqlite":
            raise CChanException("真实来源导入仅用于显式 SQLite 线性永续会话；模拟不可创建真实会话", ErrCode.LIST_ORDER_FAIL)

    def sync_wallet_cashflows(self, *, start_ms, end_ms):
        """Explicit account-wide source import only, without ordering/release."""
        self._assert_native_source_session()
        from .AccountSources import collect_wallet_scan
        document = collect_wallet_scan(self.get_exchange(), mode=self.mode, start_ms=start_ms, end_ms=end_ms)
        self.chan_db.store_account_evidence(document)
        return document

    def sync_account_snapshot(self, codes):
        """Observe all returned legs, preserving unsupported external positions."""
        self._assert_native_source_session()
        if not isinstance(codes, (list, tuple)) or any(not isinstance(code, str) or not code for code in codes) or len(set(codes)) != len(codes):
            raise CChanException("账户观察需要显式无重复的 market 标的列表", ErrCode.PARA_ERROR)
        from .AccountSources import collect_account_snapshot
        document = collect_account_snapshot(self.get_exchange(), [self._market_contract(code)[0] for code in codes], mode=self.mode)
        self.chan_db.store_account_evidence(document)
        return document

    def reconcile_account_interval(self, *, before_id, after_id, wallet_ids, execution_scan_ids):
        """Explicit observed-interval check; failures freeze, success cannot thaw.

        The caller supplies persisted source IDs, never a passed flag or account
        label. Native identity GETs stay outside the SQLite writer transaction.
        """
        self._assert_native_source_session()
        account = observe_account_context(self.get_exchange(), self.mode)
        document = self.chan_db.reconcile_account(account_context=account, before_id=before_id, after_id=after_id,
            wallet_ids=wallet_ids, execution_scan_ids=execution_scan_ids)
        if observe_account_context(self.get_exchange(), self.mode) != account:
            raise CChanException("对账期间原生账户/环境变化，不得用于放行", ErrCode.TRADE_UNLOCK_FAIL)
        return document

    def get_position(self, code: str) -> float:
        if self.dry_run:
            if self.sim_state.paper_account is not None:
                with localcontext(_PAPER_CONTEXT):
                    paper = self._paper()
                    value = sum((paper.position_quantity(key)*(1 if r["is_buy"] else -1)
                        for key, r in paper.records.items() if r["code"] == code), Decimal(0))
                    return _float_exact(value) if value >= 0 else -_float_exact(-value)
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
    def _paper_market_definition(self, code):
        market = self._paper().markets[code]
        definition = {k: market[k] for k in ("exchange", "id", "symbol", "type", "base", "quote", "settle", "contractSize")}
        definition.update(precision_mode="paper_tick_size_v1", precision={"amount": market["amount_step"], "price": market["price_tick"]},
            limits={"amount": {"min": market["amount_step"]}, "price": {"min": market["price_tick"]}, "cost": {"min": market["min_notional"]}})
        return definition

    def _paper_execution_price(self, code, limit, buy, role):
        paper = self._paper()
        best = Decimal(paper.quotes[code]["ask" if buy else "bid"])
        if role == "maker":
            return limit
        executed = best*(1+paper.config.taker_slippage*(1 if buy else -1))
        tick = Decimal(paper.markets[code]["price_tick"])
        executed = (executed/tick).to_integral_value(rounding=ROUND_CEILING if buy else ROUND_FLOOR)*tick
        executed = max(tick, executed)  # 软件价格梯最小正 tick；不虚构零价强平/退出。
        return executed if limit is None else min(executed, limit) if buy else max(executed, limit)

    def _prepare_paper_order(self, code, amount, price, *, reduce_only, record, post_only):
        self._check_paper_inputs(code, record)
        from .ExecutionFacts import _number
        self.safety_policy.assert_order_allowed()
        paper = self._paper()
        if record is None or type(post_only) is not bool or (post_only and price is None) or code not in paper.markets or code not in paper.quotes:
            raise CChanException("paper 需要真实信号记录、显式行情/单位与有效订单类型", ErrCode.PARA_ERROR)
        if not reduce_only:
            self._assert_paper_db_state()
        with localcontext(_PAPER_CONTEXT):
            market, quote = paper.markets[code], paper.quotes[code]
            size, step = (_number(market[k], positive=True) for k in ("contractSize", "amount_step"))
            desired = _number(str(_quantity(amount, positive=True)), positive=True)
            contracts = Decimal((Fraction(desired)/Fraction(size*step)).__floor__())*step
            quantity = contracts*size
            tick = _number(market["price_tick"], positive=True)
            limit = None if price is None else _number(str(_quantity(price, positive=True)), positive=True)
            if quantity <= 0 or (limit is not None and Fraction(limit)/Fraction(tick) % 1):
                raise CChanException("paper 数量舍入为零或限价不符合显式 tick", ErrCode.PARA_ERROR)
            buy = bool(record["is_buy"]) != bool(reduce_only)
            reference = _number(quote["ask" if buy else "bid"], positive=True) if limit is None else limit
            if not reduce_only and quantity*reference < _number(market["min_notional"], positive=True):
                raise CChanException("paper 精度化后低于最小名义金额", ErrCode.QUOTA_NOT_ENOUGH)
            side = self._position_side(record)
            if reduce_only:
                self._read_paper_contract({"phase": "open", "record": record})
                if quantity > paper.position_quantity(f"{self.chan_db.table}:{record['id']}"):
                    raise CChanException("paper 降风险超过原记录实际 fill lots", ErrCode.PARA_ERROR)
            elif paper.snapshot()["status"] != "ready":
                raise CChanException("paper 账户不可增加风险", ErrCode.TRADE_UNLOCK_FAIL)
            if not reduce_only:
                crossing = limit is None or (limit >= Decimal(quote["ask"]) if buy else limit <= Decimal(quote["bid"]))
                role = "taker" if crossing else "maker"
                preview = copy.deepcopy(paper)
                preview.execute_fill(execution_id=f"preview:{self.chan_db.table}:{record['id']}", position_id=f"{self.chan_db.table}:{record['id']}",
                    code=code, is_buy=buy, quantity=str(quantity), execution_price=str(self._paper_execution_price(code, limit, buy, role)),
                    position_side=side, reduce_only=False, role=role, at_ms=quote["at_ms"])
            definition = self._paper_market_definition(code)
            contract = {"schema": "chan-paper-order-v1", "market": definition, "quantity_unit": "base_currency",
                "exchange_amount_unit": "contracts", "quantity": str(quantity), "exchange_amount": str(contracts),
                "price": None if limit is None else str(limit), "reference_price": str(reference), "notional": str(quantity*reference),
                "reduce_only": bool(reduce_only), "post_only": post_only,
                "execution": {"venue": "paper", "position_mode": paper.position_mode, "position_side": side,
                    "margin_mode": "software_cross", "leverage": str(paper.config.leverage)},
                "account_observation": None, "paper_account": paper.identity_reference}
            if self.sim_state.paper_store is not None:
                contract.update(schema="chan-paper-order-v2", paper_store=self.sim_state.paper_store.reference)
                if self.paper_inputs is not None:
                    original = self._software_quote_bound(record)
                    cap = self.paper_inputs.max_age_ms if original is None else min(original, self.paper_inputs.max_age_ms)
                    contract.update(schema="chan-paper-order-v3", software_quote_max_age_ms=cap)
            contract["contract_id"] = _contract_id(contract)
            return _float_exact(quantity), None if limit is None else _float_exact(limit), contract

    def _read_paper_contract(self, intent):
        try:
            phase, record = intent["phase"], intent["record"]
            raw = record["open_order_contract" if phase == "open" else "cover_order_contract"]
            contract = json.loads(raw)
            requested = record["open_requested_qty" if phase == "open" else "cover_requested_qty"]
            with localcontext(_PAPER_CONTEXT):
                paper = self._paper()
                expected = {"schema", "market", "quantity_unit", "exchange_amount_unit", "quantity", "exchange_amount",
                    "price", "reference_price", "notional", "reduce_only", "post_only", "execution", "account_observation", "paper_account", "contract_id"}
                store = self.sim_state.paper_store
                if store is not None:
                    expected.add("paper_store")
                if contract.get("schema") == "chan-paper-order-v3":
                    expected.add("software_quote_max_age_ms")
                    cap = contract["software_quote_max_age_ms"]
                    if type(cap) is not int or not 0 < cap < 2**63:
                        raise ValueError("invalid stored quote policy")
                definition = self._paper_market_definition(record["stock_code"])
                q, amount, ref = (_quantity(contract[k], positive=True) for k in ("quantity", "exchange_amount", "reference_price"))
                limit = None if contract["price"] is None else _quantity(contract["price"], positive=True)
                side = record["position_side"]
                execution = {"venue": "paper", "position_mode": paper.position_mode, "position_side": side,
                    "margin_mode": "software_cross", "leverage": str(paper.config.leverage)}
                allowed = {"chan-paper-order-v2", "chan-paper-order-v3"} if store is not None else {"chan-paper-order-v1"}
                if (set(contract) != expected or contract["schema"] not in allowed
                        or (store is not None and contract.get("paper_store") != store.reference)
                        or contract["contract_id"] != _contract_id(contract)
                        or contract["paper_account"] != paper.identity_reference or contract["market"] != definition
                        or q != _quantity(requested, positive=True) or q != amount*Decimal(definition["contractSize"])
                        or Fraction(amount)/Fraction(Decimal(definition["precision"]["amount"])) % 1
                        or (limit is not None and Fraction(limit)/Fraction(Decimal(definition["precision"]["price"])) % 1)
                        or _quantity(contract["notional"]) != q*ref or contract["execution"] != execution
                        or (limit is not None and ref != limit)
                        or (phase == "open" and q*ref < Decimal(definition["limits"]["cost"]["min"]))
                        or side != ("BOTH" if paper.position_mode == "one_way" else "LONG" if record["is_buy"] else "SHORT")
                        or contract["quantity_unit"] != "base_currency" or contract["exchange_amount_unit"] != "contracts"
                        or contract["account_observation"] is not None or type(contract["post_only"]) is not bool
                        or (contract["post_only"] and limit is None) or contract["reduce_only"] is not (phase == "close")
                        or canonical_bytes(contract).decode() != raw):
                    raise ValueError("paper contract drift")
            history = self.chan_db.get_order_history(record["id"])
            if history["gaps"] or any(a["origin"] != "new_intent" or a["identity"]["contract_complete"] is not True for a in history["attempts"]):
                raise ValueError("paper history is incomplete")
            return contract
        except (ValueError, KeyError, TypeError, DecimalException):
            raise CChanException("原 paper 账户/意图/单位不匹配，禁止重新提交", ErrCode.TRADE_UNLOCK_FAIL) from None

    def _assert_paper_db_state(self):
        """同一 paper 身份不是恢复证明；已知记录必须与原服务器账本一致。"""
        paper, seen = self._paper(), set()
        try:
            for row in self.chan_db.db.query(f"SELECT * FROM {self.chan_db.table} WHERE open_order_contract IS NOT NULL ORDER BY id"):
                contract = json.loads(row["open_order_contract"])
                if contract.get("schema") not in {"chan-paper-order-v1", "chan-paper-order-v2", "chan-paper-order-v3"} or contract.get("paper_account") != paper.identity_reference:
                    continue
                self._read_paper_contract({"phase": "open", "record": row})
                key = f"{self.chan_db.table}:{row['id']}"
                seen.add(key)
                if Decimal(str(row["current_qty"] or 0)) != paper.position_quantity(key):
                    raise ValueError("paper DB/fill lots differ")
                for prefix in ("open", "cover"):
                    if row.get(f"{prefix}_order_status") in {"submitting", "open"}:
                        self._paper_state(row["stock_code"], row.get(f"{prefix}_order_id"), row.get(f"{prefix}_client_order_id"))
            if any(key.startswith(self.chan_db.table+":") and key not in seen and paper.position_quantity(key) for key in paper.records):
                raise ValueError("paper record missing from DB")
        except (ValueError, KeyError, TypeError, AttributeError):
            raise CChanException("paper 原 DB/订单/fill 账本不一致，先恢复核验再增风险", ErrCode.TRADE_UNLOCK_FAIL) from None

    def _paper_state(self, code, order_id, client_id):
        if order_id is None:
            order_id = self._sim_client_order_ids.get(client_id)
        state = self._sim_order_state.get(order_id)
        if state is None or state.paper_contract is None or state.code != code or (client_id is not None and state.result.client_order_id != client_id):
            raise CChanException("paper 交易所没有可证明的原订单；未知不能重下", ErrCode.LIST_ORDER_FAIL)
        intent = self.chan_db.get_order_intent(state.result.client_order_id)
        if intent is None or self._read_paper_contract(intent) != state.paper_contract:
            raise CChanException("paper 查询不属于原持久意图", ErrCode.LIST_ORDER_FAIL)
        verify_paper_order_state(state, self._paper())
        return state

    def _place_paper_order(self, code, is_buy, amount, price, client_id, reduce_only, post_only, side):
        self.safety_policy.assert_order_allowed()
        if client_id in self._sim_client_order_ids:
            state = self._paper_state(code, None, client_id)
            if (state.is_buy != is_buy or state.reduce_only != reduce_only or state.result.requested != amount or state.price != price
                    or state.paper_contract["post_only"] is not post_only or state.paper_contract["execution"]["position_side"] != side):
                raise CChanException("paper 客户端号不能用于另一请求", ErrCode.PARA_ERROR)
            return copy.copy(state.result)
        intent = self._validated_persisted_intent(code, is_buy, amount, client_id, reduce_only, side)
        contract = self._read_paper_contract(intent)
        if (_quantity(amount) != _quantity(contract["quantity"]) or contract["post_only"] is not post_only
                or (None if price is None else _quantity(price)) != (None if contract["price"] is None else _quantity(contract["price"]))):
            raise CChanException("paper 提交必须使用冻结数量/限价/类型", ErrCode.PARA_ERROR)
        plan = self._sim_fill_plans.get(client_id, [amount])
        if plan[-1] > amount:
            raise CChanException("paper 累计计划超过请求量", ErrCode.PARA_ERROR)
        with localcontext(_PAPER_CONTEXT):
            base_step = Decimal(contract["market"]["contractSize"])*Decimal(contract["market"]["precision"]["amount"])
            if any(Fraction(Decimal(str(value)))/Fraction(base_step) % 1 for value in plan):
                raise CChanException("paper 累计计划不符合冻结合约步长", ErrCode.PARA_ERROR)
        if not reduce_only:
            self.check_open_inputs(intent["record"])
        self._check_paper_inputs(code, intent["record"])
        if not self.chan_db.claim_order_submission(intent["record"]["id"], intent["phase"]):
            raise CChanException("paper 意图已由其他进程提交", ErrCode.TRADE_UNLOCK_FAIL)
        if not reduce_only:
            self.check_open_inputs(intent["record"])
        self._check_paper_inputs(code, intent["record"])
        sequence = next(self._order_id_gen)
        result = COrderResult(order_id=f"sim_{sequence}", requested=amount, filled=0, avg_price=None, status="open", client_order_id=client_id)
        quote = self._paper().quotes[code]
        crossing = price is None or (Decimal(str(price)) >= Decimal(quote["ask"]) if is_buy else Decimal(str(price)) <= Decimal(quote["bid"]))
        state = _SimOrder(code, is_buy, price, reduce_only, result, list(plan), paper_contract=contract,
            paper_position_id=f"{self.chan_db.table}:{intent['record']['id']}", paper_role="taker" if crossing else "maker")
        if post_only and crossing:
            state.result.status, state.paper_reason = "rejected", "post_only_would_cross"
        self._sim_orders[result.order_id] = result
        self._sim_order_state[result.order_id] = state
        self._sim_client_order_ids[client_id] = result.order_id
        self._sim_fill_plans.pop(client_id, None)
        if result.status == "open":
            self._advance_paper_order(state)
        if self.sim_state.paper_store is not None:
            self.sim_state.paper_store.checkpoint()  # durable server acceptance precedes the local ACK
        self.chan_db.record_order_ack(intent["record"]["id"], intent["phase"], result.order_id, client_order_id=client_id,
            expected_attempt=intent["record"]["open_attempt" if intent["phase"] == "open" else "cover_attempt"])
        return copy.copy(state.result)

    def _advance_paper_order(self, state):
        if state.result.status != "open" or state.next_fill >= len(state.fill_plan):
            return
        intent = self.chan_db.get_order_intent(state.result.client_order_id)
        self._check_paper_inputs(state.code, intent["record"])
        with localcontext(_PAPER_CONTEXT):
            paper, contract = self._paper(), state.paper_contract
            quote = paper.quotes[state.code]
            cumulative = Decimal(str(state.fill_plan[state.next_fill]))
            delta = cumulative-Decimal(str(state.result.filled))
            if delta < 0:
                raise CChanException("paper 累计成交不能回绕", ErrCode.LIST_ORDER_FAIL)
            if not delta:
                state.next_fill += 1
                return
            limit = None if state.price is None else Decimal(str(state.price))
            best = Decimal(quote["ask" if state.is_buy else "bid"])
            if limit is not None and (best > limit if state.is_buy else best < limit):
                return
            if state.paper_role == "maker":
                executed = limit
            else:
                executed = self._paper_execution_price(state.code, limit, state.is_buy, state.paper_role)
            candidate = copy.deepcopy(paper)
            event_id = f"{state.result.order_id}:{state.next_fill}"
            self._check_paper_inputs(state.code, intent["record"])
            try:
                candidate.execute_fill(execution_id=event_id, position_id=state.paper_position_id, code=state.code,
                    is_buy=state.is_buy, quantity=str(delta), execution_price=str(executed),
                    position_side=contract["execution"]["position_side"], reduce_only=state.reduce_only,
                    role=state.paper_role, at_ms=quote["at_ms"])
            except CChanException:
                state.result.status, state.paper_reason = "rejected", "paper_account_constraints"
                return
            old_notional = sum((Decimal(effect["request"]["quantity"])*Decimal(effect["request"]["execution_price"])
                for effect in paper.to_dict()["effects"] if effect["request"]["kind"] == "fill"
                and effect["request"]["id"].startswith(f"fill:{state.result.order_id}:")), Decimal(0))
            average = float((old_notional+delta*executed)/cumulative)  # API binary64; source fills retain exact Decimal prices.
            if not math.isfinite(average) or average <= 0:
                raise CChanException("paper 均价无法经过旧 API 数值边界", ErrCode.PARA_ERROR)
            filled = _float_exact(cumulative)
            paper.__dict__ = candidate.__dict__  # 保留共享服务器账户句柄，原子采用已完整校验的候选账本。
            state.result.filled, state.result.avg_price = filled, average
            state.result.status = "closed" if filled == state.result.requested else "open"
            state.next_fill += 1

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
        status = _normalize_order_status(order.get("status"))
        if status == "closed" and filled != _quantity(contract["exchange_amount"], positive=True):
            raise CChanException("交易所 closed 与累计成交量矛盾，禁止据此重下", ErrCode.LIST_ORDER_FAIL)
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
            status=status,
            client_order_id=(str(client_value) if client_value else None),
        )

    @staticmethod
    def _check_execution_report(order, contract):
        if contract["schema"] not in {"chan-ccxt-order-v2", "chan-ccxt-order-v3", "chan-native-client-order-v1"}:
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
        if swap and (execution["position_mode"] == "one_way" or contract["schema"] == "chan-native-client-order-v1"):
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
        position_side: Optional[str] = None,
        post_only: bool = False,
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
        if self.opening_inputs is not None and not reduce_only:
            intent = self._validated_persisted_intent(code, is_buy, amount, client_order_id, reduce_only, position_side)
            record = intent["record"]
            snapshot = json.loads(record.get("snapshot_before") or "{}")
            if amount != record["open_requested_qty"] or price != snapshot.get("price") or post_only:
                raise CChanException("配置模拟必须使用原意图的精确数量/方向/价格/类型", ErrCode.TRADE_UNLOCK_FAIL)
            self.check_open_inputs(intent["record"])
            if not self.chan_db.claim_order_submission(intent["record"]["id"], intent["phase"]):
                raise CChanException("配置运行意图已由其他进程提交", ErrCode.TRADE_UNLOCK_FAIL)
            self.check_open_inputs(intent["record"])
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
