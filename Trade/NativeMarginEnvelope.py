"""Exact provided-book margin envelopes, not a per-order funding decision.

The caller's hypothetical valuation is untrusted math input, not an approved
assumed price or a native execution bound. No fee, cash allocation, tier policy,
DB/order state, SDK or currentness proof is constructed here.
"""
import json
from decimal import localcontext
from fractions import Fraction

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountReconcile import _ratio, _sha
from .AccountSources import _raw
from .ExecutionFacts import MAX_REQUESTS, _MONEY, _number
from .NativeCapacityEvidence import _raw_values
from .NativeMarketEvidence import _markets
from .NativePendingOrders import _order
from .NativeOrderCost import MODEL_ID, _priced_candidate


SCHEMA = "chan-binance-margin-envelope-v1"
_CANDIDATE = {"instrument_id", "position_side", "side", "base_quantity", "contracts", "valuation_price"}


def _fail():
    raise CChanException("Binance持仓/挂单包络输入或单位不完整；计算不是资金充分或下单准入", ErrCode.TRADE_UNLOCK_FAIL) from None


def _n(value, *, positive=False):
    return Fraction(_number(value, positive=positive))


def _frame(leg, mark, leverage):
    q = leg["position"]
    bid, ask = q*mark+leg["bid_value"], q*mark-leg["ask_value"]
    order_envelope = max(abs(bid), abs(ask))
    marked_envelope = max(abs(q+leg["bid_quantity"]), abs(q-leg["ask_quantity"]))*mark
    return {
        "bid_base_quantity": leg["bid_quantity"], "ask_base_quantity": leg["ask_quantity"],
        "bid_order_value": leg["bid_value"], "ask_order_value": leg["ask_value"],
        "bid_endpoint_value": bid, "ask_endpoint_value": ask,
        "order_value_envelope": order_envelope, "marked_quantity_envelope": marked_envelope,
        "exposure_notional": max(order_envelope, marked_envelope), "initial_margin": order_envelope/leverage,
    }


def calculate_binance_margin_envelope(*, markets, positions, pending_orders, mark_prices, symbol_configs,
                                     position_mode, candidate):
    """Pure pre/post projection. Never infer completeness, permission or cash.

    Partial native orders contribute only their residual quantity. RO/closing
    orders are retained without assuming cancellations or released funds. All
    divisions remain reduced Fractions, using the original ratio wire shape.
    """
    return _calculate_binance_margin_envelope(markets=markets, positions=positions, pending_orders=pending_orders,
        mark_prices=mark_prices, symbol_configs=symbol_configs, position_mode=position_mode, candidate=candidate, rational=False)


def _calculate_binance_margin_envelope(*, markets, positions, pending_orders, mark_prices, symbol_configs,
                                      position_mode, candidate, rational):
    try:
        provided = {"markets": markets, "positions": positions, "pending_orders": pending_orders,
                    "mark_prices": mark_prices, "symbol_configs": symbol_configs,
                    "position_mode": position_mode, "candidate": candidate}
        frozen = canonical_bytes(provided)
        inputs = json.loads(frozen)
        exchange_id = inputs["markets"][0]["exchange"]
        if exchange_id not in {"binance", "binanceusdm"} or position_mode not in {"one_way", "hedged"}:
            _fail()
        with localcontext(_MONEY):
            units = _markets(inputs["markets"], exchange_id)
            by_id = {market["id"]: market for market in units}
            if (type(inputs["mark_prices"]) is not dict or set(inputs["mark_prices"]) != set(by_id)
                    or any(type(inputs[key]) is not list or len(inputs[key]) > MAX_REQUESTS
                           for key in ("positions", "pending_orders", "symbol_configs"))):
                _fail()
            marks = {key: _n(value, positive=True) for key, value in inputs["mark_prices"].items()}
            settings = {}
            for row in inputs["symbol_configs"]:
                instrument = row["symbol"]
                if instrument not in by_id or instrument in settings:
                    _fail()
                raw = _raw_values("configuration", instrument, row)
                if raw["marginType"] != "CROSSED":
                    _fail()
                settings[instrument] = _n(raw["leverage"], positive=True)
            if set(settings) != set(by_id):
                _fail()
            sides = ("BOTH",) if position_mode == "one_way" else ("LONG", "SHORT")
            legs = {(instrument, side): {key: Fraction(0) for key in
                    ("position", "bid_quantity", "ask_quantity", "bid_value", "ask_value")}
                    for instrument in by_id for side in sides}
            seen = set()
            for row in inputs["positions"]:
                raw = _raw(row, ("symbol", "positionSide", "positionAmt", "marginAsset"))
                if set(raw) != {"symbol", "positionSide", "positionAmt", "marginAsset"}:
                    _fail()
                key = raw["symbol"], raw["positionSide"]
                quantity = _n(raw["positionAmt"])
                if (key not in legs or key in seen or raw["marginAsset"] != "USDT"
                        or (key[1] == "LONG" and quantity < 0) or (key[1] == "SHORT" and quantity > 0)):
                    _fail()
                seen.add(key)
                legs[key]["position"] = quantity
            seen.clear()
            for row in inputs["pending_orders"]:
                order, issue = _order(row, "binance", "regular", units)
                key = order["instrument_id"], order["position_side"]
                identity = order["instrument_id"], int(order["native_order_id"])
                if (issue is not None or key not in legs or identity in seen or order["native_type"] != "LIMIT"
                        or (position_mode == "hedged" and order["reduce_only"] is not False)):
                    _fail()
                seen.add(identity)
                quantity, price = _n(order["remaining_base_quantity"], positive=True), _n(order["raw"]["price"], positive=True)
                prefix = "bid" if order["side"] == "BUY" else "ask"
                legs[key][prefix+"_quantity"] += quantity
                legs[key][prefix+"_value"] += quantity*price
            request = inputs["candidate"]
            if type(request) is not dict or set(request) != _CANDIDATE:
                _fail()
            key = request["instrument_id"], request["position_side"]
            if (key not in legs or request["side"] not in {"BUY", "SELL"}
                    or (position_mode == "hedged" and request["side"] != ("BUY" if key[1] == "LONG" else "SELL"))):
                _fail()
            quantity, contracts = (_n(request[field], positive=True) for field in ("base_quantity", "contracts"))
            if rational is True:
                raw_price = request["valuation_price"]
                price = Fraction(int(raw_price["numerator"]), int(raw_price["denominator"]))
                if raw_price != _ratio(price) or price <= 0:
                    _fail()
            elif rational is False:
                price = _n(request["valuation_price"], positive=True)
            else:
                _fail()
            if quantity != contracts*_n(by_id[key[0]]["contractSize"], positive=True):
                _fail()
            after = {identity: dict(leg) for identity, leg in legs.items()}
            prefix = "bid" if request["side"] == "BUY" else "ask"
            after[key][prefix+"_quantity"] += quantity
            after[key][prefix+"_value"] += quantity*price
            books, before_total, after_total = [], Fraction(0), Fraction(0)
            for market in units:
                instrument = market["id"]
                leverage, mark = settings[instrument], marks[instrument]
                projected, totals = [], {"before": Fraction(0), "after": Fraction(0)}
                exposures = {"before": Fraction(0), "after": Fraction(0)}
                for side in sides:
                    identity = instrument, side
                    frames = {"before": _frame(legs[identity], mark, leverage), "after": _frame(after[identity], mark, leverage)}
                    for label, frame in frames.items():
                        totals[label] += frame["initial_margin"]
                        exposures[label] += frame["exposure_notional"]
                    projected.append({"position_side": side, "position_base_quantity": _ratio(legs[identity]["position"]),
                        "position_contracts_signed": _ratio(legs[identity]["position"]/_n(market["contractSize"], positive=True)),
                        **{label: {field: _ratio(value) for field, value in frame.items()} for label, frame in frames.items()}})
                before_total += totals["before"]
                after_total += totals["after"]
                books.append({"instrument_id": instrument, "symbol": market["symbol"], "mark_price": _ratio(mark),
                    "leverage": _ratio(leverage), "legs": projected, "before_initial_margin": _ratio(totals["before"]),
                    "after_initial_margin": _ratio(totals["after"]), "incremental_initial_margin": _ratio(totals["after"]-totals["before"]),
                    "before_exposure_notional": _ratio(exposures["before"]), "after_exposure_notional": _ratio(exposures["after"])})
        if canonical_bytes(provided) != frozen or after_total < before_total:
            _fail()
        payload = {"provided_inputs_sha256": _sha(inputs), "position_mode": position_mode, "currency": "USDT",
            "candidate": request, "candidate_valuation_basis": "provided_untrusted_rational_reference" if rational else "provided_untrusted_reference", "books": books,
            "native_pending_count": len(inputs["pending_orders"]), "native_position_count": len(inputs["positions"]),
            "before_initial_margin": _ratio(before_total), "after_initial_margin": _ratio(after_total),
            "incremental_initial_margin": _ratio(after_total-before_total), "coverage": "provided_book_margin_envelopes_only",
            "economics_complete": False, "native_admission_verified": False}
        return {"schema": "chan-binance-margin-envelope-rational-v1" if rational else SCHEMA, "payload": payload, "payload_sha256": _sha(payload)}
    except Exception:
        _fail()


def calculate_binance_order_margin_envelope_v1(*, markets, positions, pending_orders, mark_prices, symbol_configs,
                                             position_mode, candidate, last_prices):
    """Reprice the actual raw order under V1, then reuse the same full book.

    Last/Mark and the full provided book are still unverified inputs. This
    neither selects a fee currency nor computes cash capacity/admission.
    """
    try:
        provided = {"markets": markets, "positions": positions, "pending_orders": pending_orders,
            "mark_prices": mark_prices, "symbol_configs": symbol_configs, "position_mode": position_mode,
            "candidate": candidate, "last_prices": last_prices}
        original = canonical_bytes(provided)
        values = json.loads(original)
        units = _markets(values["markets"], values["markets"][0]["exchange"])
        by_id = {unit["id"]: unit for unit in units}
        if (type(values["last_prices"]) is not dict or set(values["last_prices"]) != set(by_id)
                or type(values["mark_prices"]) is not dict or set(values["mark_prices"]) != set(by_id)):
            _fail()
        for price in values["last_prices"].values():
            _n(price, positive=True)
        request = values["candidate"]
        instrument = request["instrument_id"]
        _, _, price, _ = _priced_candidate(by_id[instrument], position_mode, request,
                                           values["mark_prices"][instrument], values["last_prices"][instrument])
        projection = {key: request[key] for key in _CANDIDATE-{"valuation_price"}}
        projection["valuation_price"] = _ratio(price)
        envelope = _calculate_binance_margin_envelope(**{key: values[key] for key in
            ("markets", "positions", "pending_orders", "mark_prices", "symbol_configs", "position_mode")},
            candidate=projection, rational=True)
        payload = {"model_id": MODEL_ID, "provided_inputs_sha256": _sha(values), "candidate": request,
            "assumed_price": _ratio(price), "margin_envelope": envelope,
            "coverage": "provided_book_with_approved_client_v1_price_only",
            "economics_complete": False, "native_admission_verified": False}
        document = json.loads(canonical_bytes({"schema": "chan-binance-order-margin-envelope-client-v1",
            "payload": payload, "payload_sha256": _sha(payload)}))
        if canonical_bytes(provided) != original or canonical_bytes(values) != original:
            _fail()
        return document
    except Exception:
        _fail()
