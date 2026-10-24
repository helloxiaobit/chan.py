"""Exact opening cost conditional on the approved named client V1 assumptions.

Provided prices/currency/rates/cash are not authenticated inputs, a native
execution bound, reserved funds, or a transferable permission. No SDK, DB,
configuration, market request or order operation occurs here.
"""
import json
from fractions import Fraction

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountReconcile import _ratio, _sha
from .ExecutionFacts import _id, _number
from .NativeCapacityEvidence import _raw_values
from .NativeMarketEvidence import _markets


SCHEMA = "chan-binance-order-cost-client-v1"
MODEL_ID = "binance-usdt-linear-open-cost-client-v1"
_ALPHA = Fraction(3, 2000)
_CANDIDATE = {"instrument_id", "position_side", "side", "base_quantity", "contracts", "order_type",
              "limit_price", "post_only", "reduce_only"}


def _fail():
    raise CChanException("Binance客户端V1单笔成本输入/单位不完整；不构成原生资金或下单准入",
                         ErrCode.TRADE_UNLOCK_FAIL) from None


def calculate_binance_order_cost_v1(*, market, position_mode, candidate, mark_price, last_price, bid_price, ask_price,
                                    leverage, commission, fee_burn, fee_currency, available_balance, margin_balance):
    """IM + opening loss + estimated fee, without old-book reservation debits.

    All LIMIT loss uses the actual limit, including post-only: there is no
    zero-loss exemption. No opposite exposure or rebate releases cash. The
    fee currency is an explicit *provided* condition, not inferred here.
    """
    try:
        provided = {"market": market, "position_mode": position_mode, "candidate": candidate,
            "mark_price": mark_price, "last_price": last_price, "bid_price": bid_price, "ask_price": ask_price,
            "leverage": leverage, "commission": commission, "fee_burn": fee_burn, "fee_currency": fee_currency,
            "available_balance": available_balance, "margin_balance": margin_balance}
        original = canonical_bytes(provided)
        values = json.loads(original)
        unit = values["market"]
        if unit["exchange"] not in {"binance", "binanceusdm"} or position_mode not in {"one_way", "hedged"}:
            _fail()
        _markets([unit], unit["exchange"])
        request = values["candidate"]
        if (type(request) is not dict or set(request) != _CANDIDATE or request["instrument_id"] != unit["id"]
                or request["side"] not in {"BUY", "SELL"} or request["order_type"] not in {"LIMIT", "MARKET"}
                or type(request["post_only"]) is not bool or request["reduce_only"] is not False
                or (position_mode == "one_way" and request["position_side"] != "BOTH")
                or (position_mode == "hedged" and (request["position_side"], request["side"]) not in
                    {("LONG", "BUY"), ("SHORT", "SELL")})):
            _fail()
        quantity, contracts, size = (Fraction(_number(value, positive=True)) for value in
            (request["base_quantity"], request["contracts"], unit["contractSize"]))
        if quantity != contracts*size:
            _fail()
        mark, last, bid, ask = (Fraction(_number(values[key], positive=True)) for key in
                               ("mark_price", "last_price", "bid_price", "ask_price"))
        native_leverage = int(_id(values["leverage"]))
        available, equity = (Fraction(_number(values[key])) for key in ("available_balance", "margin_balance"))
        if native_leverage <= 0 or not bid < ask or not 0 <= available <= equity:
            _fail()
        if fee_burn is not False or fee_currency != "USDT":
            _fail()
        raw = values["commission"]
        if type(raw) is not dict or not set(raw) <= {"symbol", "makerCommissionRate", "takerCommissionRate", "rpiCommissionRate"}:
            _fail()
        rates = _raw_values("commission", unit["id"], raw)
        maker, taker = (Fraction(_number(rates[key])) for key in ("makerCommissionRate", "takerCommissionRate"))
        if request["order_type"] == "LIMIT":
            limit = Fraction(_number(request["limit_price"], positive=True))
            assumed = limit if request["side"] == "BUY" else max(last*(1+_ALPHA), mark, limit)
            loss_price = limit
            fee_price = limit if request["post_only"] else max(assumed, mark, bid, ask, limit)
            fee_rate = max(Fraction(0), maker) if request["post_only"] else max(Fraction(0), maker, taker)
        else:
            if request["limit_price"] is not None or request["post_only"] is not False:
                _fail()
            assumed = loss_price = last*(1+_ALPHA)
            fee_price, fee_rate = max(assumed, mark, bid, ask), max(Fraction(0), taker)
        side = 1 if request["side"] == "BUY" else -1
        initial = quantity*assumed/native_leverage
        loss, fee = quantity*max(Fraction(0), side*(loss_price-mark)), quantity*fee_price*fee_rate
        total = initial+loss+fee
        payload = {"model_id": MODEL_ID, "provided_inputs_sha256": _sha(values), "candidate": request,
            "assumptions": {"price_policy": "faq_assumed_price_client_v1_not_execution_bound",
                "fee_policy": "client_v1_fee_price_and_nonnegative_role_rate_not_execution_bound",
                "loss_policy": "all_limit_including_post_only_uses_limit_market_uses_assumed_price",
                "open_cost_faq_updated": "2026-07-08", "approval_date": "2026-10-24"},
            "alpha": _ratio(_ALPHA), "currency": "USDT", "fee_currency_basis": "provided_currency_only",
            "assumed_price": _ratio(assumed), "loss_price": _ratio(loss_price), "fee_price": _ratio(fee_price),
            "fee_rate": _ratio(fee_rate), "leverage": _ratio(Fraction(native_leverage)),
            "initial_margin": _ratio(initial), "opening_loss": _ratio(loss), "estimated_fee": _ratio(fee),
            "total_cost": _ratio(total), "available_balance": _ratio(available), "margin_balance": _ratio(equity),
            "available_after_cost": _ratio(available-total), "local_model_funds_sufficient": available >= total,
            "coverage": "provided_inputs_under_approved_client_v1_assumptions_only", "input_provenance_verified": False,
            "economics_complete": False, "native_admission_verified": False, "native_execution_bound_verified": False,
            "server_reservation_verified": False}
        document = json.loads(canonical_bytes({"schema": SCHEMA, "payload": payload, "payload_sha256": _sha(payload)}))
        if canonical_bytes(provided) != original or canonical_bytes(values) != original:
            _fail()
        return document
    except Exception:
        _fail()
