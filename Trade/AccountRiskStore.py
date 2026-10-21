"""Append-only interval checks and sticky native-account new-risk freezes.

No passed/unlock input or reset API. A matching observation never erases a prior
failure, and absence of checks is explicitly NOT verified trading admission.
Callers own the same SQLite transaction as the order CAS or check publication.
"""
import hashlib
import json
import re
import sqlite3

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountIdentity import verify_account_context
from .AccountReconcile import build_account_reconciliation
from .AccountStore import read_evidence
from .ExecutionStore import read_scan_with_account
from .OrderAudit import ATTEMPTS, read_history, validate_schema, verify_history_prefix


TABLE = "chanpy_account_checks"
SCHEMA = {TABLE: f"""CREATE TABLE {TABLE}(
    check_id TEXT PRIMARY KEY, account_key TEXT NOT NULL, status TEXT NOT NULL
        CHECK(status IN ('matched_observations','mismatch','incomplete')),
    observed_ms INTEGER NOT NULL, payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL)""",
    "chanpy_account_check_key": f"CREATE INDEX chanpy_account_check_key ON {TABLE}(account_key)"}
for _verb in ("UPDATE", "DELETE"):
    _name = f"{TABLE}_no_{_verb.lower()}"
    SCHEMA[_name] = f"CREATE TRIGGER {_name} BEFORE {_verb} ON {TABLE} BEGIN SELECT RAISE(ABORT,'account checks are append-only'); END"


def _fail():
    raise CChanException("账户对账冻结/证据不完整，禁止新增风险且不得自动解冻", ErrCode.TRADE_UNLOCK_FAIL) from None


def _sha(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def account_key(context):
    verify_account_context(context)
    return _sha({k: context[k] for k in ("venue", "mode", "identifier_kind", "identifier_sha256")})


def _validate(conn):
    validate_schema(conn, SCHEMA)
    if any(conn.execute(f"PRAGMA {name}").fetchone()[0] != 1 for name in ("recursive_triggers", "foreign_keys")):
        _fail()


def initialize_schema(conn):
    if conn.execute("SELECT name FROM sqlite_master WHERE name=?", (TABLE,)).fetchone() is None:
        for sql in SCHEMA.values():
            conn.execute(sql)
    _validate(conn)


def _identities(request):
    if set(request) != {"before", "after", "wallets", "executions"} or any(type(request[k]) is not list for k in ("wallets", "executions")):
        _fail()
    ids = [request["before"], request["after"], *request["wallets"], *request["executions"]]
    if any(not isinstance(key, str) or re.fullmatch(r"[0-9a-f]{64}", key) is None for key in ids):
        _fail()


def _sources(db, request):
    _identities(request)
    sources = {"before": read_evidence(db, request["before"]), "after": read_evidence(db, request["after"]),
        "wallets": [read_evidence(db, key) for key in request["wallets"]], "executions": []}
    for key in request["executions"]:
        receipt, linked = read_scan_with_account(db, key)
        if linked is None:
            _fail()
        sources["executions"].append({"receipt": receipt, "account_context": linked["observation"]["account_context"],
            "manifest_sha256": linked["manifest_sha256"], "observed_ms": linked["observation"]["finished_ms"]})
    return sources


def _ledger(chan):
    db = chan.db
    # Discover trade-shaped tables rather than reconciling just the caller's
    # table. A second CChanDB(table_name=...) cannot hide an account's positions.
    required = {"id", "stock_code", "is_buy", "current_qty", "position_side", "open_order_contract", "open_attempt", "cover_attempt"}
    tables = {chan.table} | {r["trade_table"] for r in db.query(f"SELECT DISTINCT trade_table FROM {ATTEMPTS}")}
    for row in db.query("SELECT name FROM sqlite_master WHERE type='table'"):
        columns = {r["name"] for r in db.query("SELECT name FROM pragma_table_info(?)", (row["name"],))}
        if required <= columns:
            tables.add(row["name"])
    histories, projections = [], []
    for table in sorted(tables):
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table) is None:
            _fail()
        for row in db.query(f"SELECT * FROM {table} ORDER BY id"):
            history = read_history(db, table, row)
            if not history["attempts"] and not row["current_qty"] and not history["gaps"]:
                continue
            histories.append(history)
            projections.append({"trade_table": table, "record_id": row["id"], "instrument": row["stock_code"],
                "current_qty": row["current_qty"], "position_side": row["position_side"], "is_buy": bool(row["is_buy"])})
    return {"histories": histories, "projections": projections}


def _failure(context):
    payload = {"account_context": context, "coverage": "evidence_unavailable", "economics_complete": False, "status": "incomplete",
        "issues": [{"reason": "evidence_unavailable", "severity": "incomplete"}]}
    return {"schema": "chan-account-reconciliation-failure-v1", "payload": payload, "payload_sha256": _sha(payload)}


def reconcile(chan, context, request):
    """Load original sources + current journal, compute, and publish atomically."""
    db = chan.db
    _validate(db.conn)
    account_key(context)
    _identities(request)
    inputs = None
    try:
        loaded = {**_sources(db, request), **_ledger(chan)}
        if any(canonical_bytes(loaded[key]["payload"]["account_context"]) != canonical_bytes(context) for key in ("before", "after")):
            _fail()
        report = build_account_reconciliation(**loaded)
        inputs = loaded
    except (CChanException, sqlite3.DatabaseError, ValueError, TypeError, KeyError, AttributeError):
        # Do not propagate arbitrary private exception text or roll back the
        # very freeze an unreadable source must create. Publication failures
        # themselves still raise/roll back, and no order is thereby authorized.
        report = _failure(context)
    payload = {"account_context": context, "source_ids": request, "inputs": inputs, "report": report}
    document = {"schema": "chan-account-check-v1", "payload": payload, "payload_sha256": _sha(payload)}
    raw, digest = canonical_bytes(document).decode(), _sha(document)
    row = db.query_one(f"SELECT * FROM {TABLE} WHERE check_id=?", (digest,))
    if row:
        if canonical_bytes(_read(db, row)) != canonical_bytes(document):
            _fail()
        return document
    db.execute(f"INSERT INTO {TABLE}(check_id,account_key,status,observed_ms,payload,payload_sha256) VALUES(?,?,?,?,?,?)",
        (digest, account_key(context), report["payload"]["status"], utc_now_ms(), raw, digest))
    return document


def _read(db, row):
    try:
        document = json.loads(row["payload"])
        payload = document["payload"]
        context, inputs, report = payload["account_context"], payload["inputs"], payload["report"]
        if (set(document) != {"schema", "payload", "payload_sha256"} or document["schema"] != "chan-account-check-v1"
                or set(payload) != {"account_context", "source_ids", "inputs", "report"}
                or canonical_bytes(document).decode() != row["payload"] or _sha(document) != row["check_id"]
                or _sha(document) != row["payload_sha256"] or _sha(payload) != document["payload_sha256"]
                or account_key(context) != row["account_key"] or report["payload"]["status"] != row["status"]
                or type(row["observed_ms"]) is not int or not 0 <= row["observed_ms"] <= utc_now_ms()):
            _fail()
        _identities(payload["source_ids"])
        if inputs is None:
            if canonical_bytes(report) != canonical_bytes(_failure(context)):
                _fail()
        else:
            sources = _sources(db, payload["source_ids"])
            if any(canonical_bytes(sources[key]) != canonical_bytes(inputs[key]) for key in sources):
                _fail()
            verify_history_prefix(db, inputs["histories"])
            if (canonical_bytes(inputs["before"]["payload"]["account_context"]) != canonical_bytes(context)
                    or canonical_bytes(build_account_reconciliation(**inputs)) != canonical_bytes(report)):
                _fail()
        return document
    except (ValueError, TypeError, KeyError, AttributeError):
        _fail()


def read_check(db, check_id):
    _validate(db.conn)
    if not isinstance(check_id, str) or re.fullmatch(r"[0-9a-f]{64}", check_id) is None:
        _fail()
    row = db.query_one(f"SELECT * FROM {TABLE} WHERE check_id=?", (check_id,))
    if row is None:
        _fail()
    return _read(db, row)


def risk_state(db, context):
    _validate(db.conn)
    key = account_key(context)
    # Validate indexed metadata before filtering; a corrupted account_key column
    # must not hide a freeze. No cache can survive another connection's writes.
    checks = [_read(db, row) for row in db.query(f"SELECT * FROM {TABLE} ORDER BY check_id")]
    checks = [c for c in checks if account_key(c["payload"]["account_context"]) == key]
    return {"schema": "chan-account-risk-state-v1", "account_key": key,
        "frozen": any(c["payload"]["report"]["payload"]["status"] != "matched_observations" for c in checks),
        "check_ids": [_sha(c) for c in checks], "coverage": "historical_checks_only", "admission_verified": False}


def assert_new_risk_allowed(db, context):
    if risk_state(db, context)["frozen"]:
        _fail()
