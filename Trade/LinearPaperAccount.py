"""显式软件 cross/lot paper 核算；复用 C4，不伪装原生交易所账户。

只处理已发生的 fills/quote/funding，不维护第二套订单状态机。输入 price 是
实际模拟成交价，滑点在撮合边界体现，故底层 C4 slippage=0，不能重复扣算。
record 的退出按其真实 fill lots FIFO；不是 Binance/OKX pooled 成本认证。
"""
import copy
import hashlib
import json
import re
import uuid
from dataclasses import replace
from decimal import Context, Decimal, DecimalException, localcontext
from fractions import Fraction
from pathlib import Path

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from ModelStrategy.parameterEvaluate.crypto_account import CCryptoAccount, CCryptoAccountConfig, account_evaluator_identity
from .ExecutionFacts import _market, _number as _native_number


_CONTEXT = Context(prec=50, Emax=100, Emin=-100)


def _fail():
    raise CChanException("paper 账户缺少明确单位/行情/原持仓或经济约束，不能猜测成交", ErrCode.PLACE_ORDER_FAIL) from None


def _text(value):
    return format(value, "f") if value else "0"


def _sha(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _code_sha(name):
    return hashlib.sha256(Path(__file__).with_name(name).read_text(encoding="utf-8").replace("\r\n", "\n").encode()).hexdigest()


def _clock(value):
    if type(value) is not int or not 0 <= value < 2**63:
        _fail()
    return value


def _number(value, *, positive=False):
    # Paper 的 Python 数值边界不是交易所原生 wire 协议；不放宽 native reader。
    if type(value) not in (str, int, float, Decimal):
        _fail()
    try:
        return _native_number(str(value), positive=positive)
    except (ValueError, DecimalException):
        _fail()


class CLinearPaperAccount:
    def __init__(self, config, *, markets, position_mode, start_ms, identity_seed=None):
        if not isinstance(config, CCryptoAccountConfig) or config.market_type != "swap" or position_mode not in {"one_way", "hedged"}:
            _fail()
        seed = uuid.uuid4().hex if identity_seed is None else identity_seed
        if not isinstance(seed, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", seed) is None:
            _fail()
        self.config, self.position_mode = config, position_mode
        self.account = CCryptoAccount(replace(config, taker_slippage="0"), start_ms=_clock(start_ms))
        self.markets, self.quotes, self.records, self._seen, self._effects = {}, {}, {}, {}, []
        try:
            with localcontext(_CONTEXT):
                for name, value in config.to_dict().items():
                    if name not in {"market_type", "settle"}:
                        _number(value, positive=name in {"initial_equity", "leverage"})
                ids, venues = set(), set()
                for item in markets:
                    definition = _market(item)
                    venue = "binance" if definition["exchange"] == "binanceusdm" else definition["exchange"]
                    key = (venue, definition["id"])
                    extra = {k: _text(_number(item[k], positive=True)) for k in ("amount_step", "price_tick", "min_notional")}
                    if definition["symbol"] in self.markets or key in ids or set(item) != set(definition) | set(extra):
                        _fail()
                    ids.add(key)
                    venues.add(venue)
                    self.markets[definition["symbol"]] = {**definition, **extra}
            if not self.markets or len(venues) != 1:
                _fail()
        except (ValueError, TypeError, KeyError, DecimalException):
            _fail()
        self._identity = {"schema": "chan-linear-paper-v1", "seed": seed, "config": config.to_dict(),
            "position_mode": position_mode, "markets": list(self.markets.values()), "start_ms": start_ms,
            "accounting": "c4_per_fill_lot_record_fifo", "exchange_certified": False,
            "order_average_report": "binary64_api_source_fills_remain_decimal50",
            "decimal_context": {"precision": 50, "emax": 100, "emin": -100},
            "evaluator": account_evaluator_identity(),
            "code_sha256": _code_sha("LinearPaperAccount.py"), "execution_code_sha256": _code_sha("CCXTTradeEngine.py")}
        self._identity["account_id"] = _sha(self._identity)
        self._identity = json.loads(canonical_bytes(self._identity))

    def assert_identity(self):
        try:
            if (_sha({k: v for k, v in self._identity.items() if k != "account_id"}) != self._identity["account_id"]
                    or canonical_bytes(list(self.markets.values())) != canonical_bytes(self._identity["markets"])
                    or self.position_mode != self._identity["position_mode"] or self.config.to_dict() != self._identity["config"]
                    or self.account.config != replace(self.config, taker_slippage="0")
                    or self._identity["evaluator"] != account_evaluator_identity()
                    or self._identity["code_sha256"] != _code_sha("LinearPaperAccount.py")
                    or self._identity["execution_code_sha256"] != _code_sha("CCXTTradeEngine.py")):
                _fail()
        except (TypeError, ValueError, AttributeError, KeyError, OSError):
            _fail()

    @property
    def identity_reference(self):
        self.assert_identity()
        return {"schema": self._identity["schema"], "account_id": self._identity["account_id"]}

    def snapshot(self):
        self.assert_identity()
        with localcontext(_CONTEXT):
            return self.account.snapshot()

    def to_dict(self):
        self.assert_identity()
        with localcontext(_CONTEXT):
            payload = {"schema": "chan-linear-paper-account-v1", "identity": self._identity,
                "account": self.account.to_dict(), "quotes": self.quotes, "records": self.records,
                "effects": [json.loads(raw) for raw in self._effects]}
            return json.loads(canonical_bytes(payload))

    def read_effect(self, event_id):
        for raw in self._effects:
            item = json.loads(raw)
            if item["request"]["id"] == event_id:
                return item
        return None

    def _apply(self, request, action):
        self.assert_identity()
        raw = canonical_bytes(request)
        key = request["id"]
        if key in self._seen:
            if self._seen[key] != raw:
                _fail()
            return self.read_effect(key)
        candidate = copy.deepcopy(self)
        with localcontext(_CONTEXT):
            before = self.snapshot()
            events = action(candidate)
            after = candidate.snapshot()
            fields = {"cash_delta": "cash", "fee_delta": "fees", "price_pnl_delta": "price_pnl", "funding_delta": "funding_pnl"}
            record = {"request": request, "events": events,
                "cashflow": {k: _text(Decimal(after[field])-Decimal(before[field])) for k, field in fields.items()}, "snapshot": after}
            encoded = canonical_bytes(record)
        candidate._seen[key] = raw
        candidate._effects.append(encoded)
        self.__dict__ = candidate.__dict__
        return json.loads(encoded)

    def set_quote(self, code, *, at_ms, bid, ask, mark_price):
        with localcontext(_CONTEXT):
            if code not in self.markets:
                _fail()
            bid, ask, mark = (_number(v, positive=True) for v in (bid, ask, mark_price))
            at_ms = _clock(at_ms)
            tick = _number(self.markets[code]["price_tick"], positive=True)
            if bid > ask or any(Fraction(value)/Fraction(tick) % 1 for value in (bid, ask)):
                _fail()
            values = {"code": code, "at_ms": at_ms, "bid": _text(bid), "ask": _text(ask), "mark_price": _text(mark)}
            request = {"id": "quote:"+_sha(values), "kind": "quote", **values}

        def apply(candidate):
            event = {"id": request["id"], "kind": "mark", "at_ms": at_ms, "symbol": code, "price": _text(mark)}
            candidate.account.apply(event)
            candidate.quotes[code] = values
            return [event]
        return self._apply(request, apply)

    def position_quantity(self, position_id):
        with localcontext(_CONTEXT):
            return sum((self.account.positions[key].quantity for key in self.records.get(position_id, {}).get("lots", []) if key in self.account.positions), Decimal(0))

    def leg_quantity(self, code, side):
        with localcontext(_CONTEXT):
            return sum((self.position_quantity(key) for key, record in self.records.items() if record["code"] == code and record["position_side"] == side), Decimal(0))

    def execute_fill(self, *, execution_id, position_id, code, is_buy, quantity, execution_price, position_side, reduce_only, role, at_ms):
        with localcontext(_CONTEXT):
            if (not isinstance(execution_id, str) or not execution_id or not isinstance(position_id, str) or not position_id
                    or type(is_buy) is not bool or type(reduce_only) is not bool or role not in {"maker", "taker"} or code not in self.markets):
                _fail()
            quantity, price = _number(quantity, positive=True), _number(execution_price, positive=True)
            step = _number(self.markets[code]["amount_step"])*_number(self.markets[code]["contractSize"])
            if Fraction(quantity)/Fraction(step) % 1:
                _fail()
            expected_side = "BOTH" if self.position_mode == "one_way" else "LONG" if is_buy != reduce_only else "SHORT"
            if position_side != expected_side:
                _fail()
            request = {"id": "fill:"+execution_id, "kind": "fill", "position_id": position_id, "code": code,
                "is_buy": is_buy, "quantity": _text(quantity), "execution_price": _text(price), "position_side": position_side,
                "reduce_only": reduce_only, "role": role, "at_ms": _clock(at_ms)}

        def apply(candidate):
            quote = candidate.quotes.get(code)
            if quote is None or quote["at_ms"] != at_ms or candidate.account.last_ms > at_ms:
                _fail()
            record = candidate.records.get(position_id)
            events = []
            if not reduce_only:
                if record is not None and (record["code"] != code or record["is_buy"] != is_buy or record["position_side"] != position_side or not candidate.position_quantity(position_id)):
                    _fail()
                if candidate.position_mode == "one_way" and any(r["code"] == code and r["is_buy"] != is_buy and candidate.position_quantity(key) for key, r in candidate.records.items()):
                    _fail()
                lot = request["id"]
                event = {"id": lot, "kind": "open", "at_ms": at_ms, "position_id": lot, "symbol": code,
                    "is_buy": is_buy, "quantity": _text(quantity), "price": _text(price), "mark_price": quote["mark_price"], "role": role}
                candidate.account.apply(event)
                candidate.records.setdefault(position_id, {"code": code, "is_buy": is_buy, "position_side": position_side, "lots": []})["lots"].append(lot)
                events.append(event)
            else:
                if (record is None or record["code"] != code or record["is_buy"] == is_buy
                        or record["position_side"] != position_side or candidate.position_quantity(position_id) < quantity):
                    _fail()
                remaining = quantity
                for index, lot in enumerate(record["lots"]):
                    if lot not in candidate.account.positions or not remaining:
                        continue
                    taken = min(remaining, candidate.account.positions[lot].quantity)
                    event = {"id": request["id"]+":"+str(index), "kind": "close", "at_ms": at_ms,
                        "position_id": lot, "quantity": _text(taken), "price": _text(price), "role": role,
                        "sequence": len(candidate.account.to_dict()["events"])}
                    candidate.account.apply(event)
                    events.append(event)
                    remaining -= taken
            return events
        return self._apply(request, apply)

    def apply_funding(self, code, *, at_ms, rate, mark_price, event_id):
        with localcontext(_CONTEXT):
            if not isinstance(event_id, str) or not event_id or code not in self.markets:
                _fail()
            # Rates may be signed; the shared kernel enforces its bounded rate.
            rate, mark = _number(rate), _number(mark_price, positive=True)
            if not rate.is_finite():
                _fail()
            request = {"id": "funding:"+event_id, "kind": "funding", "code": code, "at_ms": _clock(at_ms),
                "rate": _text(rate), "mark_price": _text(mark)}

        def apply(candidate):
            quote = candidate.quotes.get(code)
            if quote is None or quote["at_ms"] != at_ms or _number(quote["mark_price"]) != mark:
                _fail()
            event = {"id": request["id"], "kind": "funding", "at_ms": at_ms, "symbol": code, "price": _text(mark), "rate": _text(rate)}
            candidate.account.apply(event)
            return [event]
        return self._apply(request, apply)


def verify_linear_paper_report(report):
    """按原输入 effect 顺序复算，不是独立公式/交易所认证，也不读取绩效。"""
    try:
        identity = report["identity"]
        account = CLinearPaperAccount(CCryptoAccountConfig(**identity["config"]), markets=identity["markets"],
            position_mode=identity["position_mode"], start_ms=identity["start_ms"], identity_seed=identity["seed"])
        for effect in report["effects"]:
            request = effect["request"]
            if request["kind"] == "quote":
                account.set_quote(request["code"], at_ms=request["at_ms"], bid=request["bid"], ask=request["ask"], mark_price=request["mark_price"])
            elif request["kind"] == "funding" and request["id"].startswith("funding:"):
                account.apply_funding(request["code"], at_ms=request["at_ms"], rate=request["rate"], mark_price=request["mark_price"], event_id=request["id"][8:])
            elif request["kind"] == "fill" and request["id"].startswith("fill:"):
                account.execute_fill(execution_id=request["id"][5:], **{k: v for k, v in request.items() if k not in {"id", "kind"}})
            else:
                _fail()
        reconstructed = account.to_dict()
        if canonical_bytes(report) != canonical_bytes(reconstructed):
            _fail()
        return reconstructed
    except (ValueError, TypeError, KeyError, AttributeError, DecimalException):
        _fail()
