"""Original local management identities, not current sources or permission.

The eventual action consumer must own current collection, quantity checks,
account-wide CAS and the original SDK use point. JSON copies cannot send.
"""
import json
from decimal import Decimal, localcontext

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountRiskStore import account_key, _sha
from .ExecutionFacts import _MONEY, _number, _string
from . import NativeOrderBoundary as Boundary
from . import NativeOrderTransition as Transition
from . import NativePendingOwnership as Ownership
from . import OrderAudit as Audit


IDENTITY_SCHEMA = "chan-native-management-identity-v1"


def _fail():
    raise CChanException("原有风险管理的原单身份/历史不完整或漂移；不是操作许可", ErrCode.LIST_ORDER_FAIL) from None


def read_native_management_order_identity(chan, record_id, *, phase):
    """Rebuild one original attempt and local remainder without GET or writes."""
    try:
        if type(record_id) is not int or record_id <= 0 or type(phase) is not str or phase not in {"open", "close"}:
            _fail()
        database = Boundary._database(chan)
        connection, table, owned = database.conn, chan.table, database.conn.in_transaction
        Boundary._same_database(chan, database, connection, table, owned=owned)
        with database.transaction():
            Boundary._same_database(chan, database, connection, table, owned=True)
            record = chan.get_record(record_id)
            Boundary._same_database(chan, database, connection, table, owned=True)
            history = Audit.read_history(database, table, record)
            Boundary._same_database(chan, database, connection, table, owned=True)
            if history["gaps"] or not history["attempts"]:
                _fail()
            frozen = canonical_bytes({"record": record, "history": history})
            prefix = "open" if phase == "open" else "cover"
            selected = [a for a in history["attempts"] if a["identity"]["phase"] == phase
                        and a["identity"]["attempt"] == record.get(prefix+"_attempt")]
            if len(selected) != 1:
                _fail()
            identity = selected[0]["identity"]
            account = identity["order_contract"]["account_context"]
            stable_account = account_key(account)
            with localcontext(_MONEY):
                totals = {"open": Decimal(0), "close": Decimal(0)}
                for attempt in history["attempts"]:
                    original = attempt["identity"]
                    if (attempt["origin"] != "new_intent" or original["contract_complete"] is not True
                            or original["order_contract"]["schema"] not in {"chan-ccxt-order-v3", "chan-native-client-order-v1"}):
                        _fail()
                    Ownership._validate_contract(original)
                    if (account_key(original["order_contract"]["account_context"]) != stable_account
                            or canonical_bytes(original["order_contract"]["account_context"]) != canonical_bytes(account)):
                        _fail()
                    quantity = _number(str(attempt["events"][-1]["state"]["filled_qty"]))
                    if quantity < 0:
                        _fail()
                    totals[original["phase"]] += quantity
                remaining = totals["open"]-totals["close"]
                if (totals["open"] != _number(str(record["open_filled_qty"]))
                        or totals["close"] != _number(str(record["cover_filled_qty"]))
                        or remaining < 0 or remaining != _number(str(record["current_qty"]))):
                    _fail()
                remaining = _string(remaining)
            roots = Transition._client_order_roots(chan, [history])
            references = [Transition._client_reference(a, roots) for a in history["attempts"]
                          if a["identity"]["order_contract"]["schema"] == "chan-native-client-order-v1"]
            if any(reference["stage"] != "claim" for reference in references):
                _fail()  # An unsubmitted monetary L1 is not an existing server order.
            Boundary._same_database(chan, database, connection, table, owned=True)
            current = chan.get_record(record_id)
            Boundary._same_database(chan, database, connection, table, owned=True)
            if canonical_bytes({"record": current, "history": Audit.read_history(database, table, current)}) != frozen:
                _fail()
            Boundary._same_database(chan, database, connection, table, owned=True)
            payload = {"target": {key: identity[key] for key in ("trade_table", "record_id", "phase", "attempt", "client_order_id")},
                "account_context": account, "account_key": stable_account, "identity": identity,
                "record_sha256": _sha(record), "history_sha256": _sha(history), "native_roots": references,
                "local_remaining_quantity": remaining, "native_quantity_verified": False, "operation_authorized": False}
            payload["target"]["native_order_id"] = record.get(prefix+"_order_id")
            result = json.loads(canonical_bytes({"schema": IDENTITY_SCHEMA, "payload": payload, "payload_sha256": _sha(payload)}))
        Boundary._same_database(chan, database, connection, table, owned=owned)
        return result
    except Exception:
        _fail()
