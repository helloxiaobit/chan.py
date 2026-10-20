"""显式成交/mark/funding 的 USDT 账户，不从逐笔百分比还原资金。

quantity 为币数量，不是合约张数。swap 仅指 USDT 线性永续；保证金为本软件
cross 风险口径，不冒称交易所强平规则。每个 position_id 是独立成交 lot，允许
部分退出；追加成交应使用新 lot 身份。未平仓保持 mark 估值，不伪造期末成交。
"""
import copy
import hashlib
import json
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, DecimalException, localcontext
from pathlib import Path

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes

ZERO = Decimal(0)
YEAR_MS = 365*24*3600*1000
EVENT_ORDER = {"mark": 0, "funding": 1, "close": 2, "open": 3}


def account_evaluator_identity():
    return {"schema": "chan-crypto-account-v1", "decimal_precision": 50, "currency": "USDT", "quantity_unit": "base_coin",
            "ordering": "mark-funding-old_exit-open-new_lot_exit", "margin_model": "software_cross_not_exchange_liquidation",
            "code_sha256": hashlib.sha256(Path(__file__).read_text(encoding="utf-8").replace("\r\n", "\n").encode()).hexdigest()}


def _error(message):
    return CChanException(message, ErrCode.PARA_ERROR)


def _number(value, *, positive=False, nonnegative=False):
    if type(value) not in (int, float, str, Decimal):
        raise _error("账户数值必须为有限数字，不能是 bool/对象")
    try:
        result = Decimal(str(value))
    except DecimalException as error:
        raise _error("账户数值格式无效") from error
    if not result.is_finite() or (positive and result <= 0) or (nonnegative and result < 0):
        raise _error("账户数值必须有限且满足正/非负约束")
    return result


def _text(value):
    return str(value) if value else "0"


def _clock(value):
    if type(value) is not int or value < 0:
        raise _error("账户时钟必须是非负 UTC 整数毫秒")
    return value


@dataclass(frozen=True)
class CCryptoAccountConfig:
    market_type: str = "swap"
    settle: str = "USDT"
    initial_equity: object = "1000"
    leverage: object = "1"
    taker_fee: object = "0.0005"
    maker_fee: object = "0.0002"
    taker_slippage: object = "0.0002"
    maintenance_rate: object = "0.005"

    def __post_init__(self):
        if self.market_type not in {"spot", "swap"} or self.settle != "USDT":
            raise _error("账户仅适配 USDT spot/线性 perpetual，反向/期权不支持")
        for name in ("initial_equity", "leverage", "taker_fee", "maker_fee", "taker_slippage", "maintenance_rate"):
            value = _number(getattr(self, name), positive=name in {"initial_equity", "leverage"}, nonnegative=True)
            if name not in {"initial_equity", "leverage"} and value >= 1:
                raise _error("费率/滑点/维持保证金比率必须小于 1")
            object.__setattr__(self, name, value)
        if self.leverage < 1 or (self.market_type == "spot" and self.leverage != 1):
            raise _error("spot 不支持借贷，swap 杠杆至少为 1")

    def to_dict(self):
        return {k: _text(v) if isinstance(v, Decimal) else v for k, v in asdict(self).items()}


@dataclass(frozen=True)
class _Position:
    symbol: str
    is_buy: bool
    quantity: Decimal
    price: Decimal
    opened_ms: int

    @property
    def direction(self):
        return 1 if self.is_buy else -1


class CCryptoAccount:
    def __init__(self, config=None, *, start_ms=0):
        self.config = config or CCryptoAccountConfig()
        self.start_ms = self.last_ms = _clock(start_ms)
        self.cash = self.config.initial_equity
        self.price_pnl = self.funding_pnl = self.fees = ZERO
        self.positions, self.marks = {}, {}
        self._seen, self._closed, self._events, self._funding_slots = {}, set(), [], set()
        self._exit_slots = set()

    def snapshot(self):
        with localcontext() as context:
            context.prec = 50
            return self._snapshot()

    def _snapshot(self):
        gross = net = unrealized = asset_value = ZERO
        positions = {}
        for identity, pos in sorted(self.positions.items()):
            mark = self.marks[pos.symbol]
            notional = pos.quantity*mark
            gross += notional
            net += pos.direction*notional
            asset_value += notional
            unrealized += pos.direction*pos.quantity*(mark-pos.price)
            positions[identity] = {"symbol": pos.symbol, "is_buy": pos.is_buy, "quantity": _text(pos.quantity),
                "average_price": _text(pos.price), "mark_price": _text(mark), "opened_ms": pos.opened_ms}
        equity = self.cash+(asset_value if self.config.market_type == "spot" else unrealized)
        margin = gross/self.config.leverage if self.config.market_type == "swap" else ZERO
        maintenance = gross*self.config.maintenance_rate if self.config.market_type == "swap" else ZERO
        status = "ready"
        if equity <= 0:
            status = "liquidation_required" if positions else "insolvent"
        elif positions and self.config.market_type == "swap" and equity <= maintenance:
            status = "liquidation_required"
        values = {"initial_equity": self.config.initial_equity, "cash": self.cash, "equity": equity,
            "price_pnl": self.price_pnl, "unrealized_pnl": unrealized, "funding_pnl": self.funding_pnl, "fees": self.fees,
            "gross_notional": gross, "net_notional": net, "margin_used": margin, "maintenance_margin": maintenance,
            "free_collateral": self.cash if self.config.market_type == "spot" else equity-margin}
        return {**{k: _text(v) for k, v in values.items()}, "status": status, "positions": positions,
                "closed_position_count": len(self._closed)}

    def apply(self, event):
        if not isinstance(event, dict) or not isinstance(event.get("id"), str) or not event["id"]:
            raise _error("账户事件需要唯一非空 id")
        raw = canonical_bytes(event)
        if event["id"] in self._seen:
            if self._seen[event["id"]] != raw:
                raise _error("相同事件 id 内容漂移")
            return self.snapshot()
        at = _clock(event.get("at_ms"))
        if at < self.last_ms:
            raise _error("账户事件回绕，不能用未来账户重算过去")
        candidate = copy.copy(self)
        candidate.positions, candidate.marks, candidate._closed = dict(self.positions), dict(self.marks), set(self._closed)
        candidate._funding_slots = set(self._funding_slots)
        candidate._exit_slots = set(self._exit_slots)
        with localcontext() as context:
            context.prec = 50
            execution_price = candidate._apply(event)
            snapshot = candidate.snapshot()
            cashflow = {"cash_delta": _text(candidate.cash-self.cash), "fee_delta": _text(candidate.fees-self.fees),
                        "price_pnl_delta": _text(candidate.price_pnl-self.price_pnl),
                        "funding_delta": _text(candidate.funding_pnl-self.funding_pnl),
                        "execution_price": None if execution_price is None else _text(execution_price)}
        record = canonical_bytes({"event": event, "cashflow": cashflow, "snapshot": snapshot})
        # 在全部校验和序列化成功前，不改现金、持仓、幂等状态或事件账本。
        self.cash, self.price_pnl, self.funding_pnl, self.fees = candidate.cash, candidate.price_pnl, candidate.funding_pnl, candidate.fees
        self.positions, self.marks, self._closed = candidate.positions, candidate.marks, candidate._closed
        self._funding_slots = candidate._funding_slots
        self._exit_slots = candidate._exit_slots
        self.last_ms = at
        self._seen[event["id"]] = raw
        self._events.append(record)
        return snapshot

    def _apply(self, event):
        kind = event.get("kind")
        base = {"id", "kind", "at_ms"}
        required = {"open": {"position_id", "symbol", "is_buy", "quantity", "price", "mark_price"},
                    "close": {"position_id", "quantity", "price"}, "mark": {"symbol", "price"},
                    "funding": {"symbol", "price", "rate"}}
        allowed = {"role"} if kind in {"open", "close"} else set()
        if kind == "close":
            allowed.add("sequence")
        if kind not in required or not (base|required[kind]) <= event.keys() or set(event)-(base|required[kind]|allowed):
            raise _error("账户事件字段/类型不完整")
        if kind in {"mark", "funding", "open"}:
            symbol = event["symbol"]
            suffix = "/USDT:USDT" if self.config.market_type == "swap" else "/USDT"
            if not isinstance(symbol, str) or not symbol.endswith(suffix) or not symbol[:-len(suffix)] or "/" in symbol[:-len(suffix)] or ":" in symbol[:-len(suffix)]:
                raise _error("symbol 与 USDT 账户市场不匹配")
        price = _number(event["price"], positive=True)
        if kind == "mark":
            self.marks[symbol] = price
            return
        if kind == "funding":
            if self.config.market_type != "swap":
                raise _error("spot 账户不允许伪造 perpetual funding")
            rate = _number(event["rate"])
            if abs(rate) >= 1:
                raise _error("资金费率绝对值必须小于 1")
            slot = (symbol, event["at_ms"])
            if slot in self._funding_slots:
                raise _error("同一 symbol/时刻的资金费只能结算一次，不能换 id 重复收费")
            self._funding_slots.add(slot)
            self.marks[symbol] = price
            delta = sum((-p.direction*p.quantity*price*rate for p in self.positions.values()
                         if p.symbol == symbol and p.opened_ms < event["at_ms"]), ZERO)
            self.cash += delta
            self.funding_pnl += delta
            return None
        role = event.get("role", "taker")
        if role not in {"maker", "taker"}:
            raise _error("成交费用角色必须明确")
        fee_rate = self.config.maker_fee if role == "maker" else self.config.taker_fee
        slippage = self.config.taker_slippage if role == "taker" else ZERO
        quantity = _number(event["quantity"], positive=True)
        identity = event["position_id"]
        if not isinstance(identity, str) or not identity:
            raise _error("position_id 必须是非空成交 lot 身份")
        if kind == "open":
            if self.snapshot()["status"] != "ready" or identity in self.positions or identity in self._closed:
                raise _error("账户不允许新风险或同 lot 重复开仓")
            if type(event["is_buy"]) is not bool or (self.config.market_type == "spot" and not event["is_buy"]):
                raise _error("方向无效或 spot 无借贷不能做空")
            direction = 1 if event["is_buy"] else -1
            executed = price*(1+direction*slippage)
            fee = quantity*executed*fee_rate
            self.marks[symbol] = _number(event["mark_price"], positive=True)
            self.positions[identity] = _Position(symbol, event["is_buy"], quantity, executed, event["at_ms"])
            self.cash -= fee+(quantity*executed if self.config.market_type == "spot" else ZERO)
            self.fees += fee
            after = self.snapshot()
            if _number(after["free_collateral"]) < 0 or after["status"] != "ready":
                raise _error("费后权益/保证金或 spot 可用现金不足")
            return executed
        position = self.positions.get(identity)
        if position is None or quantity > position.quantity:
            raise _error("减仓缺少实际 lot 或超过剩余数量")
        sequence = event.get("sequence", 0)
        if (type(sequence) is not int or sequence < 0
                or any(pid == identity and at == event["at_ms"] and old_sequence >= sequence
                       for pid, at, old_sequence in self._exit_slots)):
            raise _error("同刻退出必须有唯一递增 sequence，不能用新 id 重复记账")
        self._exit_slots.add((identity, event["at_ms"], sequence))
        executed = price*(1-position.direction*slippage)
        fee = quantity*executed*fee_rate
        pnl = position.direction*quantity*(executed-position.price)
        self.cash += (quantity*executed if self.config.market_type == "spot" else pnl)-fee
        self.price_pnl += pnl
        self.fees += fee
        remaining = position.quantity-quantity
        if remaining:
            self.positions[identity] = replace(position, quantity=remaining)
        else:
            del self.positions[identity]
            self._closed.add(identity)
        return executed

    def to_dict(self):
        events = [json.loads(raw) for raw in self._events]
        with localcontext() as context:
            context.prec = 50
            snapshot = self.snapshot()
        return {"schema": "chan-crypto-account-v1", "config": self.config.to_dict(), "start_ms": self.start_ms,
                "last_event_ms": self.last_ms, "snapshot": snapshot, "events": events, "evaluator": account_evaluator_identity(),
                "events_sha256": hashlib.sha256(b"\n".join(self._events)).hexdigest()}

    def report(self, *, end_ms):
        end_ms = _clock(end_ms)
        if end_ms <= self.start_ms or self.last_ms >= end_ms:
            raise _error("账户报告必须有明确 end-exclusive 窗口，事件不能越界")
        report = self.to_dict()
        with localcontext() as context:
            context.prec = 50
            peak = self.config.initial_equity
            drawdown = ZERO
            for record in report["events"]:
                equity = _number(record["snapshot"]["equity"])
                peak = max(peak, equity)
                drawdown = max(drawdown, (peak-equity)/peak)
            ratio = _number(report["snapshot"]["equity"])/self.config.initial_equity
            cagr = None
            if ratio > 0:
                try:
                    value = ratio**(Decimal(YEAR_MS)/(end_ms-self.start_ms))-1
                    if value.is_finite() and value.adjusted() <= 308:
                        cagr = value
                except DecimalException:
                    pass  # 极短窗口无法表示的年化明确 null，不能写 Infinity。
            calmar = cagr/drawdown if cagr is not None and drawdown else None
            report.update(window={"start_ms": self.start_ms, "end_ms": end_ms},
                metrics={"units": "fractions_of_USDT_equity", "total_return": _text(ratio-1),
                    "max_drawdown": _text(drawdown), "cagr": None if cagr is None else _text(cagr),
                    "calmar": None if calmar is None else _text(calmar),
                    "calmar_infinite": cagr is not None and cagr > 0 and not drawdown,
                    "annualization_reportable": cagr is not None, "closed_position_count": len(self._closed)})
        report["report_sha256"] = hashlib.sha256(canonical_bytes(report)).hexdigest()
        return report


def evaluate_crypto_account(events, config=None, *, start_ms, end_ms):
    """同刻 mark→旧仓 funding→旧仓退出→入场→该新 lot 即时退出。

    不静默过滤窗口外事件；未来价格和成交不能混入当前报告。
    """
    start_ms, end_ms = _clock(start_ms), _clock(end_ms)
    events = list(events)
    if end_ms <= start_ms:
        raise _error("账户窗口必须为正的半开区间")
    for event in events:
        if not isinstance(event, dict) or event.get("kind") not in EVENT_ORDER or not start_ms <= _clock(event.get("at_ms")) < end_ms:
            raise _error("账户事件不在明确窗口内或类型无效")
    account = CCryptoAccount(config, start_ms=start_ms)
    opened_at = {str(e.get("position_id")): e["at_ms"] for e in events if e["kind"] == "open"}
    def order(event):
        priority = EVENT_ORDER[event["kind"]]
        if event["kind"] == "close" and opened_at.get(str(event.get("position_id"))) == event["at_ms"]:
            priority = 4
        sequence = event.get("sequence", 0)
        if type(sequence) is not int or sequence < 0:
            raise _error("退出 sequence 必须为非负整数")
        return event["at_ms"], priority, str(event.get("symbol", "")), str(event.get("position_id", "")), sequence, str(event.get("id", ""))
    for event in sorted(events, key=order):
        account.apply(event)
    return account.report(end_ms=end_ms)


def verify_crypto_account_report(report):
    """从事件重放核对完整报告，不是第二套独立经济公式或外部审计。"""
    try:
        if not isinstance(report, dict) or report.get("evaluator") != account_evaluator_identity():
            raise _error("账户 evaluator 身份不一致")
        config = CCryptoAccountConfig(**report["config"])
        reconstructed = evaluate_crypto_account([row["event"] for row in report["events"]], config,
                                                start_ms=report["window"]["start_ms"], end_ms=report["window"]["end_ms"])
        if canonical_bytes(report) != canonical_bytes(reconstructed):
            raise _error("账户事件、现金流、曲线、窗口或指标无法逐项重放")
        return reconstructed
    except (KeyError, TypeError, ValueError, AttributeError, DecimalException) as error:
        raise _error("账户报告缺少完整可重放证据") from error
