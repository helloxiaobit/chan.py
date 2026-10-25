"""Read original SQLite attempts against native pending observations.

This is a quantity/identity association, not available cash, native frozen
margin, an absence certificate or an admission capability. No orders, ACKs,
reservations or sticky freezes are written or cleared here.
"""
import json
from decimal import localcontext

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountIdentity import verify_account_context
from .AccountRiskStore import _ledger, account_key
from .CCXTTradeEngine import CCCXTTradeEngine
from .ExecutionFacts import _MONEY, _number, _string
from .ExecutionReconcile import _digest, _order_ids, _reason, _requested
from .NativePendingOrders import verify_native_pending_orders
from .NativeMarketEvidence import _markets


SCHEMA = "chan-native-pending-ownership-v1"
CLIENT_SCHEMA = "chan-native-pending-ownership-v2"
_CLIENT_ORDER_SCHEMA = "chan-native-client-order-v1"
_TERMINAL = {"closed", "canceled", "rejected"}


def _fail():
    raise CChanException("未决单归属/原账本证据不完整，不能释放预留或用于账户准入", ErrCode.TRADE_UNLOCK_FAIL) from None


def _reference(attempt):
    identity = attempt["identity"]
    return {key: identity[key] for key in ("trade_table", "record_id", "phase", "attempt", "client_order_id")}


def _native_key(order):
    return (order["channel"], order["instrument_id"], order["native_order_id"])


def _validate_contract(identity):
    contract = identity["order_contract"]
    if set(contract) != {"schema", "market", "quantity_unit", "exchange_amount_unit", "quantity", "exchange_amount",
                         "price", "reference_price", "notional", "reduce_only", "execution", "account_observation",
                         "post_only", "account_context", "contract_id"} | ({"monetary_basis_sha256"}
                            if contract["schema"] == _CLIENT_ORDER_SCHEMA else set()):
        _fail()
    market = contract["market"]
    _markets([market], market["exchange"])
    venue = "binance" if market["exchange"] in {"binance", "binanceusdm"} else market["exchange"]
    quantity, amount, size, reference = (_number(value, positive=True) for value in
        (contract["quantity"], contract["exchange_amount"], market["contractSize"], contract["reference_price"]))
    notional = _number(contract["notional"], positive=True)
    if (contract["quantity_unit"] != "base_currency" or contract["exchange_amount_unit"] != "contracts"
            or quantity != _requested(identity) or quantity != amount*size or notional != quantity*reference
            or contract["reduce_only"] is not (identity["phase"] == "close") or market["symbol"] != identity["instrument"]
            or contract["account_context"]["venue"] != venue):
        _fail()
    if contract["price"] is not None:
        _number(contract["price"], positive=True)
    # Original pure checks; no engine instance, SDK import, account query or
    # second execution/financial state machine is created by this reader.
    CCCXTTradeEngine._check_execution_evidence(contract, identity, identity["phase"])
    CCCXTTradeEngine._check_limits(market, amount, reference, notional)


def _match(attempt, order, market, context, *, client_roots=()):
    fact = {"client_order_id": order["client_order_id"], "side": order["side"].lower(),
            "position_side": "BOTH" if order["position_side"] == "net" else order["position_side"].upper(),
            "timestamp_ms": order["created_ms"]}
    # Reuse original immutable-contract/account/market/leg/intent checks. Here
    # the native event is creation of this order, not a synthetic trade fill.
    reason = _reason(attempt, fact, market, context, client_roots=client_roots)
    if reason:
        return reason
    identity, state = attempt["identity"], attempt["events"][-1]["state"]
    contract = identity["order_contract"]
    if order["client_order_id"] is None:
        return "missing_client_id"
    if state["order_status"] != "open":
        return "local_order_state_unresolved"
    if (_number(order["base_quantity"]) != _requested(identity)
            or _number(order["contracts"]) != _number(contract["exchange_amount"])
            or _number(order["filled_base_quantity"]) != _number(str(state["filled_qty"]))):
        return "pending_quantity_difference"
    execution, raw = contract["execution"], order["raw"]
    close = identity["phase"] == "close"
    if (contract["reduce_only"] is not close
            or order["reduce_only"] is not (close and execution["position_mode"] == "one_way")):
        return "reduce_only_mismatch"
    if order["margin_mode"] is not None and order["margin_mode"] != execution["margin_mode"]:
        return "margin_mode_mismatch"
    if context["venue"] == "binance":
        kind, price, post_only = raw["type"].lower(), raw["price"], raw["timeInForce"] == "GTX"
        if kind == "limit" and raw["timeInForce"] != ("GTX" if contract["post_only"] else "GTC"):
            return "order_terms_mismatch"
    else:
        kind, price, post_only = ("limit" if raw["ordType"] == "post_only" else raw["ordType"]), raw["px"], raw["ordType"] == "post_only"
    if (kind != ("market" if contract["price"] is None else "limit") or post_only is not contract["post_only"]
            or (contract["price"] is not None and _number(price) != _number(contract["price"]))):
        return "order_terms_mismatch"
    return None


def _build(source, ledger, *, client_roots=()):
    context = source["account_context"]
    markets = {market["id"]: market for market in source["markets"]}
    attempts, issues, reservations = [], [], []
    references = []
    for history in ledger["histories"]:
        if history["gaps"] or not history["attempts"]:
            issues.append({"reason": "incomplete_attempt_history"})
        for attempt in history["attempts"]:
            identity, contract = attempt["identity"], attempt["identity"]["order_contract"]
            if (attempt["origin"] != "new_intent" or identity["contract_complete"] is not True
                    or not isinstance(contract, dict) or contract.get("schema") not in {"chan-ccxt-order-v3", _CLIENT_ORDER_SCHEMA}
                    or _digest(contract) != identity["contract_sha256"]
                    or _digest({key: value for key, value in contract.items() if key != "contract_id"}) != contract["contract_id"]):
                issues.append({"reason": "unidentified_attempt", "attempt": _reference(attempt)})
                continue
            if contract["schema"] == _CLIENT_ORDER_SCHEMA:
                from .NativeOrderTransition import _client_reference
                references.append(_client_reference(attempt, client_roots))
            verify_account_context(contract["account_context"])
            if account_key(contract["account_context"]) != account_key(context):
                continue  # Only a verified different native account can be excluded.
            _validate_contract(identity)
            times = [identity["intent_ms"], attempt["observed_ms"], *(event["observed_ms"] for event in attempt["events"])]
            if (any(type(at) is not int or at < 0 or at > source["finished_ms"] for at in times)
                    or times != sorted(times)):
                _fail()
            if canonical_bytes(contract["account_context"]) != canonical_bytes(context):
                issues.append({"reason": "historical_account_environment_drift", "attempt": _reference(attempt)})
            attempts.append(attempt)
    unsupported = {_native_key(row): row["reason"] for row in source["unsupported_orders"]}
    records, owned = [], set()
    for order in source["orders"]:
        candidates = [attempt for attempt in attempts if order["native_order_id"] in _order_ids(attempt)
                      and attempt["identity"]["order_contract"]["market"]["id"] == order["instrument_id"]]
        reason = unsupported.get(_native_key(order))
        if reason is None:
            reason = ("unrecorded_order" if not candidates else "ambiguous_order_id" if len(candidates) != 1
                      else _match(candidates[0], order, markets[order["instrument_id"]], context, client_roots=client_roots))
        reference = _reference(candidates[0]) if reason is None else None
        if reference is not None:
            owned.add(canonical_bytes(reference))
        else:
            issues.append({"reason": reason, "native_order": list(_native_key(order))})
        records.append({"native_order": list(_native_key(order)), "status": "owned" if reason is None else "unowned",
                        "reason": reason, "attempt": reference})
    for attempt in attempts:
        state, identity = attempt["events"][-1]["state"], attempt["identity"]
        terminal = state["order_status"] in _TERMINAL
        client = identity["order_contract"]["schema"] == _CLIENT_ORDER_SCHEMA
        if terminal and not client:
            continue
        reference = _reference(attempt)
        if terminal and client:
            issues.append({"reason": "client_terminal_not_observed", "attempt": reference})
        requested, filled = _requested(identity), _number(str(state["filled_qty"]))
        if not 0 <= filled <= requested:
            _fail()
        remaining = requested-filled
        size = _number(identity["order_contract"]["market"]["contractSize"], positive=True)
        matched = canonical_bytes(reference) in owned
        reservations.append({"attempt": reference, "instrument": identity["instrument"], "position_side": identity["position_side"],
            "local_order_status": state["order_status"], "requested_base_quantity": _string(requested),
            "filled_base_quantity": _string(filled), "remaining_base_quantity": _string(remaining),
            "remaining_contracts": _string(remaining/size), "native_pending_matched": matched, "native_margin_amount": None})
        if not matched:
            issues.append({"reason": "local_pending_not_observed", "attempt": reference})
    payload = {"source_pending_sha256": _digest(source), "account_context_id": context["context_id"],
        "ledger_sha256": _digest(ledger), "coverage": "native_pending_and_local_nonterminal_attempts",
        "economics_complete": False, "native_admission_verified": False, "orders": records,
        "reservations": reservations, "issues": sorted(issues, key=canonical_bytes)}
    if references:
        payload["client_order_references"] = references
    return payload


def observe_native_pending_ownership(chan, *, pending_orders):
    """DB-only consistent read; all transport must finish outside this call.

    No source-authenticity or age claim. The later current-state consumer must
    own collection and recheck the original ledger in its own CAS transaction.
    """
    try:
        original = canonical_bytes(pending_orders)
        document = json.loads(original)
        verify_native_pending_orders(document)
        if chan.db_type != "sqlite":
            _fail()
        with chan.db.transaction(), localcontext(_MONEY):
            from .AccountRiskStore import _client_roots
            ledger = _ledger(chan)
            roots = _client_roots(chan, ledger["histories"])
            payload = _build(document["payload"], ledger, client_roots=roots)
        if canonical_bytes(pending_orders) != original:
            _fail()
        return {"schema": CLIENT_SCHEMA if "client_order_references" in payload else SCHEMA,
                "payload": payload, "payload_sha256": _digest(payload)}
    except Exception:
        _fail()
