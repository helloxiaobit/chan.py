"""Observed native trade ownership, not an account or cashflow PASS.

The database caller supplies verified complete attempt histories in one SQLite
snapshot. No current-slot fallback, balance inference, fee conversion, funding
leg allocation or order write is performed here.
"""
import hashlib
from decimal import Context, Decimal, DecimalException, Inexact, localcontext

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountIdentity import verify_account_context
from .ExecutionFacts import verify_execution_scan


_QUANTITIES = Context(prec=50, Emax=100, Emin=-100)
_QUANTITIES.traps[Inexact] = True


def _fail():
    raise CChanException("逐笔归属输入/历史证据不完整，不能宣称账户对账通过", ErrCode.LIST_ORDER_FAIL) from None


def _digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _requested(identity):
    value = identity["requested_qty"]
    if isinstance(value, bool):
        _fail()
    number = Decimal(str(value))
    if not number.is_finite() or number <= 0:
        _fail()
    return number


def _order_ids(attempt):
    return {str(e["state"]["order_id"]) for e in attempt["events"] if e["state"]["order_id"] is not None}


def _reason(attempt, fact, market, account, *, client_roots=()):
    identity = attempt["identity"]
    contract = identity["order_contract"]
    if (attempt["origin"] != "new_intent" or identity["contract_complete"] is not True
            or not isinstance(contract, dict) or contract.get("schema") not in {"chan-ccxt-order-v3", "chan-native-client-order-v1"}):
        return "legacy_attempt"
    if contract["schema"] == "chan-native-client-order-v1":
        from .NativeOrderTransition import _client_reference
        try:
            reference = _client_reference(attempt, client_roots)
        except (CChanException, TypeError, KeyError, ValueError, AttributeError):
            return "unverified_client_order"
        if (reference["stage"] != "claim" or len(attempt["events"]) < 2 or attempt["events"][1]["kind"] != "claim"
                or attempt["events"][1].get("native_boundary_sha256") != reference["binding_sha256"]):
            return "client_claim_not_observed"
    if (contract.get("contract_id") != _digest({k: v for k, v in contract.items() if k != "contract_id"})
            or identity["contract_sha256"] != _digest(contract)):
        return "invalid_contract"
    if canonical_bytes(contract["account_context"]) != canonical_bytes(account):
        return "account_context_mismatch"
    if identity["instrument"] != market["symbol"] or any(contract["market"].get(k) != v for k, v in market.items()):
        return "market_mismatch"
    if len(_order_ids(attempt)) != 1:
        return "conflicting_order_ids"
    if fact["client_order_id"] is not None and fact["client_order_id"] != identity["client_order_id"]:
        return "client_id_mismatch"
    phase, buy = identity["phase"], identity["is_buy"]
    if phase not in {"open", "close"} or type(buy) not in (bool, int) or buy not in (0, 1):
        _fail()
    if fact["side"] != ("buy" if bool(buy) == (phase == "open") else "sell"):
        return "side_mismatch"
    if fact["position_side"] != identity["position_side"] or fact["position_side"] != contract["execution"]["position_side"]:
        return "position_side_mismatch"
    if fact["timestamp_ms"] is None:
        return "missing_fill_time"
    if type(identity["intent_ms"]) is not int:
        return "missing_intent_time"
    if fact["timestamp_ms"] < identity["intent_ms"]:
        return "before_intent"
    if Decimal(contract["quantity"]) != _requested(identity):
        return "requested_quantity_mismatch"
    return None


def build_execution_ownership(receipt, account_context, histories, *, client_roots=()):
    """Bind observed trades to one historical attempt or emit an explicit gap.

    A matched subset or an empty scan never proves all executions were observed.
    AccountContext must come from that scan's original native observation, not
    an unrelated current account or a retrospective caller label.
    """
    try:
        verify_execution_scan(receipt)
        verify_account_context(account_context)
        source = receipt["payload"]
        if account_context["venue"] != source["venue"] or account_context["mode"] != source["mode"]:
            _fail()
        attempts = []
        from .OrderAudit import _history_header
        for history in histories:
            if canonical_bytes({key: history[key] for key in ("schema", "coverage", "economics_complete")}) != canonical_bytes(_history_header(history["attempts"])):
                _fail()
            attempts.extend(history["attempts"])
        references = []
        for attempt in attempts:
            contract = attempt["identity"]["order_contract"]
            if isinstance(contract, dict) and contract.get("schema") == "chan-native-client-order-v1":
                from .NativeOrderTransition import _client_reference
                references.append(_client_reference(attempt, client_roots))
        records, groups = [], {}
        with localcontext(_QUANTITIES):
            for fact in source["facts"]:
                if fact["kind"] != "trade":
                    continue
                candidates = [a for a in attempts if fact["order_id"] in _order_ids(a)] if fact["order_id"] is not None else []
                checked = [(a, _reason(a, fact, source["market"], account_context, client_roots=client_roots)) for a in candidates]
                valid = [a for a, reason in checked if reason is None]
                reasons = {reason for _, reason in checked}
                reason = ("missing_order_id" if fact["order_id"] is None else "unrecorded_order")
                if checked:
                    reason = next(iter(reasons)) if len(reasons) == 1 else "conflicting_attempt_evidence"
                reference = None
                if len(valid) > 1:
                    reason = "ambiguous_order_id"
                elif len(valid) == 1:
                    identity = valid[0]["identity"]
                    reference = {k: identity[k] for k in ("trade_table", "record_id", "phase", "attempt", "client_order_id")}
                    reference.update(order_id=fact["order_id"], contract_id=identity["order_contract"]["contract_id"])
                    key = canonical_bytes(reference)
                    group = groups.setdefault(key, {"quantity": Decimal(0), "requested": _requested(identity), "indices": []})
                    group["quantity"] += Decimal(fact["quantity"])
                    group["indices"].append(len(records))
                    reason = None
                records.append({"source_id": fact["source_id"], "quantity": fact["quantity"], "contracts": fact["contracts"],
                    "status": "owned" if reference is not None else "unowned", "reason": reason, "attempt": reference})
            for group in groups.values():
                if group["quantity"] > group["requested"]:
                    for index in group["indices"]:
                        records[index].update(status="unowned", reason="requested_quantity_exceeded", attempt=None)
        payload = {"source_scan_sha256": receipt["payload_sha256"], "account_context_id": account_context["context_id"],
            "history_sha256": _digest(histories), "coverage": "observed_scan_facts_only", "economics_complete": False,
            "trades": records, "funding": [{"source_id": f["source_id"], "status": "unallocated", "reason": "native_leg_missing"}
                for f in source["facts"] if f["kind"] == "funding"]}
        if references:
            payload["client_order_references"] = references
        return {"schema": "chan-execution-ownership-v2" if references else "chan-execution-ownership-v1",
                "payload": payload, "payload_sha256": _digest(payload)}
    except (TypeError, ValueError, KeyError, AttributeError, DecimalException):
        _fail()
