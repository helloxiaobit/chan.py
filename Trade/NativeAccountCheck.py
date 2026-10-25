"""Native component checks in the original table; failures stay sticky.

The report is historical observation, never an authorization or a reset. Its
component calculation is shared with the DB observer and the old cash engine.
"""
import re
import sqlite3

from Common.ChanException import CChanException
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountRiskStore import _fail, _failure, _identities, _ledger, _publish, _sha, _sources, _validate, _client_roots, account_key
from .NativeAccountReconcile import _components
from .NativeAccountStore import read_observation
from .OrderAudit import ATTEMPTS, EVENTS, validate_schema, verify_history_prefix


SCHEMA = "chan-native-account-check-v1"
CLIENT_SCHEMA = "chan-native-account-check-v2"
_BASE = ("before", "after", "wallets", "executions")


def _publish_unavailable(db, context, request):
    """Caller owns publication transaction; failures only, never a PASS input."""
    _validate(db.conn)
    account_key(context)
    _base_request(request)
    payload = {"account_context": context, "source_ids": request, "inputs": None, "report": _failure(context)}
    return _publish(db, {"schema": SCHEMA, "payload": payload, "payload_sha256": _sha(payload)})


def _base_request(request):
    if type(request) is not dict or set(request) != {*_BASE, "pending", "balance"}:
        _fail()
    base = {key: request[key] for key in _BASE}
    _identities(base)
    if any(type(request[key]) is not str or re.fullmatch(r"[0-9a-f]{64}", request[key]) is None for key in ("pending", "balance")):
        _fail()
    return base


def _load(db, request):
    return {**_sources(db, _base_request(request)), "pending": read_observation(db, request["pending"]),
            "balance": read_observation(db, request["balance"])}


def _journal_prefix(db, boundaries=None):
    validate_schema(db.conn)
    if boundaries is None:
        boundaries = {"event_id": db.query_one(f"SELECT COALESCE(max(event_id),0) AS n FROM {EVENTS}")["n"]}
    if set(boundaries) != {"event_id"} or any(type(value) is not int or value < 0 for value in boundaries.values()):
        _fail()
    # event_id is an explicit INTEGER PRIMARY KEY. The attempts table has a
    # composite key, so its implicit rowid must not become a durable identity
    # (SQLite may renumber such rowids during ordinary compaction).
    attempts = db.query(f"""SELECT a.* FROM {ATTEMPTS} a WHERE EXISTS(
        SELECT 1 FROM {EVENTS} e WHERE e.trade_table=a.trade_table AND e.record_id=a.record_id
        AND e.phase=a.phase AND e.attempt=a.attempt AND e.event_id<=?)
        ORDER BY a.trade_table,a.record_id,a.phase,a.attempt""", (boundaries["event_id"],))
    events = db.query(f"SELECT * FROM {EVENTS} WHERE event_id<=? ORDER BY event_id", (boundaries["event_id"],))
    return {"boundaries": boundaries, "attempts_sha256": _sha(attempts), "events_sha256": _sha(events),
            "attempt_count": len(attempts), "event_count": len(events)}


def _verify_complete_histories(db, histories, prefix):
    if canonical_bytes(_journal_prefix(db, prefix["boundaries"])) != canonical_bytes(prefix):
        _fail()
    verify_history_prefix(db, histories)
    keys = lambda row: tuple(row[key] for key in ("trade_table", "record_id", "phase", "attempt"))
    attempts = [attempt for history in histories for attempt in history["attempts"]]
    saved = {keys(attempt["identity"]): len(attempt["events"]) for attempt in attempts}
    actual = {}
    for row in db.query(f"SELECT * FROM {EVENTS} WHERE event_id<=?", (prefix["boundaries"]["event_id"],)):
        actual[keys(row)] = actual.get(keys(row), 0)+1
    if len(saved) != len(attempts) or saved != actual:
        _fail()


def _report(context, request, inputs):
    components = _components(context, _base_request(request), {key: inputs[key] for key in _BASE},
                              {key: inputs[key] for key in ("histories", "projections")}, inputs["pending"], inputs["balance"],
                              client_roots=inputs.get("client_roots", ()))
    p = components["payload"]
    payload = {"account_context": context, "coverage": "historical_native_components_only", "economics_complete": False,
               "native_admission_verified": False, "status": "matched_observations" if p["status"] == "matched_components" else p["status"],
               "issues": p["issues"], "components": components}
    return {"schema": "chan-native-account-component-result-v2" if inputs.get("client_roots") else "chan-native-account-component-result-v1",
            "payload": payload, "payload_sha256": _sha(payload)}


def reconcile_native_account(chan, context, request):
    db = chan.db
    _validate(db.conn)
    account_key(context)
    _base_request(request)
    inputs = None
    try:
        loaded = {**_load(db, request), **_ledger(chan), "journal_prefix": _journal_prefix(db)}
        _verify_complete_histories(db, loaded["histories"], loaded["journal_prefix"])
        roots = _client_roots(chan, loaded["histories"])
        if roots:
            loaded["client_roots"] = roots
        report = _report(context, request, loaded)
        inputs = loaded
    except (CChanException, sqlite3.DatabaseError, ValueError, TypeError, KeyError, AttributeError):
        report = _failure(context)
    payload = {"account_context": context, "source_ids": request, "inputs": inputs, "report": report}
    return _publish(db, {"schema": CLIENT_SCHEMA if inputs is not None and inputs.get("client_roots") else SCHEMA,
                         "payload": payload, "payload_sha256": _sha(payload)})


def read_native_check(db, row, document):
    try:
        payload = document["payload"]
        context, inputs, report = payload["account_context"], payload["inputs"], payload["report"]
        client = document["schema"] == CLIENT_SCHEMA
        if (set(document) != {"schema", "payload", "payload_sha256"} or document["schema"] not in {SCHEMA, CLIENT_SCHEMA}
                or set(payload) != {"account_context", "source_ids", "inputs", "report"}
                or canonical_bytes(document).decode() != row["payload"] or _sha(document) != row["check_id"]
                or _sha(document) != row["payload_sha256"] or _sha(payload) != document["payload_sha256"]
                or account_key(context) != row["account_key"] or report["payload"]["status"] != row["status"]
                or type(row["observed_ms"]) is not int or not 0 <= row["observed_ms"] <= utc_now_ms()):
            _fail()
        _base_request(payload["source_ids"])
        if inputs is None:
            if client or canonical_bytes(report) != canonical_bytes(_failure(context)):
                _fail()
        else:
            if set(inputs) != {*_BASE, "pending", "balance", "histories", "projections", "journal_prefix"} | ({"client_roots"} if client else set()):
                _fail()
            sources = _load(db, payload["source_ids"])
            if any(canonical_bytes(sources[key]) != canonical_bytes(inputs[key]) for key in sources):
                _fail()
            _verify_complete_histories(db, inputs["histories"], inputs["journal_prefix"])
            if client:
                from .NativeOrderTransition import _stored_client_order_roots
                roots = _stored_client_order_roots(db, inputs["histories"])
                if not roots or canonical_bytes(roots) != canonical_bytes(inputs["client_roots"]):
                    _fail()
            if canonical_bytes(_report(context, payload["source_ids"], inputs)) != canonical_bytes(report):
                _fail()
        return document
    except (ValueError, TypeError, KeyError, AttributeError):
        _fail()
