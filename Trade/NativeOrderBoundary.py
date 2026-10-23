"""Original native-check L0 for later per-order intent/claim verification.

This is DB-only consistency, not collector ownership, funding or permission.
The original CAS still needs exact L1/L2 consumption and versioned references;
no caller-resealed baseline, matching check or returned None authorizes orders.
"""
import json
from pathlib import Path
import hashlib

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountRiskStore import _sha, risk_state
from .NativeAccountCheck import _journal_prefix
from .NativeAdmission import _assert_current_windows
from .NativeComponentCollector import _implementation as _component_implementation
from .NativeCurrentComponents import _snapshot, read_native_component_policy
from .NativeMarketEvidence import verify_native_market_evidence
from .OrderAudit import ATTEMPTS, EVENTS


SCHEMA = "chan-native-order-boundary-v1"
_INPUTS = {"account_context", "check_id", "market_evidence", "policy"}
_STATE = {"ledger_sha256", "journal_prefix", "account_check_ids", "database_location_sha256"}


def _fail():
    raise CChanException("原生订单 L0/原事务账本边界不一致；不是逐单资金或发送许可", ErrCode.TRADE_UNLOCK_FAIL) from None


def _implementation():
    return {**_component_implementation(), "Trade/NativeOrderBoundary.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def _database(chan):
    from .db_util import CChanDB
    if type(chan) is not CChanDB or chan.db_type != "sqlite":
        _fail()
    return chan.db


def _same_database(chan, database, connection, table, *, owned):
    if (chan.db_type != "sqlite" or chan.db is not database or database.conn is not connection or chan.table != table
            or connection.in_transaction is not owned or (database._transaction_depth > 0) is not owned):
        _fail()


def _view(chan, inputs):
    snapshot = _snapshot(chan, inputs["account_context"], inputs["check_id"], inputs["market_evidence"])
    saved = snapshot["check"]["payload"]["inputs"]
    prefix = _journal_prefix(chan.db)
    if (canonical_bytes(prefix) != canonical_bytes(saved["journal_prefix"])
            or prefix["attempt_count"] != chan.db.query_one(f"SELECT count(*) AS n FROM {ATTEMPTS}")["n"]
            or prefix["event_count"] != chan.db.query_one(f"SELECT count(*) AS n FROM {EVENTS}")["n"]):
        _fail()  # A dangling attempt without any event cannot vanish in a prefix.
    return {"ledger_sha256": _sha({key: saved[key] for key in ("histories", "projections")}),
            "journal_prefix": prefix, "account_check_ids": risk_state(chan.db, inputs["account_context"])["check_ids"],
            "database_location_sha256": _sha(chan.db.query("PRAGMA database_list"))}, snapshot


def _windows(inputs, snapshot, start, finished):
    saved = snapshot["check"]["payload"]["inputs"]
    _assert_current_windows(inputs["policy"], start, finished, account=saved["after"]["payload"],
        market=inputs["market_evidence"]["payload"], wallets=[row["payload"] for row in saved["wallets"]],
        executions=snapshot["execution_observations"],
        additional=[("open_orders", saved["pending"]["payload"]), ("balance", saved["balance"]["payload"])])


def _inputs(document):
    values = json.loads(canonical_bytes(document))
    values["policy"] = read_native_component_policy(values["policy"])
    verify_native_market_evidence(values["market_evidence"])
    return values


def capture_native_order_boundary(chan, *, account_context, check_id, market_evidence, policy):
    """Read committed original L0; captured_ms is a start, not a source clock."""
    try:
        database = _database(chan)
        connection, table = database.conn, chan.table
        if connection.in_transaction:
            _fail()
        provided = {"account_context": account_context, "check_id": check_id, "market_evidence": market_evidence, "policy": policy}
        original = canonical_bytes(provided)
        start, implementation = utc_now_ms(), _implementation()
        inputs = _inputs(provided)
        with database.transaction():
            state, snapshot = _view(chan, inputs)
        payload = {**inputs, **state, "captured_ms": start, "implementation_sha256": implementation,
                   "coverage": "exact_native_component_l0_only", "economics_complete": False, "native_admission_verified": False}
        result = json.loads(canonical_bytes({"schema": SCHEMA, "payload": payload, "payload_sha256": _sha(payload)}))
        if canonical_bytes(provided) != original or implementation != _implementation():
            _fail()
        _same_database(chan, database, connection, table, owned=False)
        location = _sha(database.query("PRAGMA database_list"))
        _same_database(chan, database, connection, table, owned=False)
        if location != state["database_location_sha256"]:
            _fail()
        _windows(inputs, snapshot, start, utc_now_ms())
        return result
    except Exception:
        _fail()


def assert_native_order_boundary(chan, boundary):
    """Caller owns the original SQLite transaction; no GET or row write."""
    try:
        database = _database(chan)
        connection, table = database.conn, chan.table
        if not connection.in_transaction or database._transaction_depth <= 0:
            _fail()
        original = canonical_bytes(boundary)
        value = json.loads(original)
        payload = value["payload"]
        if (set(value) != {"schema", "payload", "payload_sha256"} or value["schema"] != SCHEMA
                or set(payload) != _INPUTS | _STATE | {"captured_ms", "implementation_sha256", "coverage", "economics_complete", "native_admission_verified"}
                or value["payload_sha256"] != _sha(payload) or payload["coverage"] != "exact_native_component_l0_only"
                or payload["economics_complete"] is not False or payload["native_admission_verified"] is not False
                or payload["implementation_sha256"] != _implementation() or type(payload["captured_ms"]) is not int):
            _fail()
        inputs = _inputs({key: payload[key] for key in _INPUTS})
        state, snapshot = _view(chan, inputs)
        if (canonical_bytes(state) != canonical_bytes({key: payload[key] for key in _STATE})
                or canonical_bytes(boundary) != original or payload["implementation_sha256"] != _implementation()):
            _fail()
        _same_database(chan, database, connection, table, owned=True)
        _windows(inputs, snapshot, payload["captured_ms"], utc_now_ms())
    except Exception:
        _fail()
