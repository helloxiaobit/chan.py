"""Exact facts around the original CAS, never a funding or send permission.

Only the original intent/claim writer publishes these append-only references.
They do not replace the order state machine, allocate money or release unknown
orders. Old contracts/events are unchanged; default native sending stays locked.
"""
import copy
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from . import NativeOrderBoundary as Boundary
from .AccountRiskStore import _ledger, _sha, _trade_tables, read_check, risk_state
from .NativeAccountCheck import _journal_prefix
from .NativeCurrentComponents import _sources_snapshot
from .OrderAudit import ATTEMPTS, EVENTS, _identity, _key, _load, _read_attempt, _state, read_history, validate_schema


TABLE = "chanpy_native_order_transitions"
DOCUMENT_SCHEMA = "chan-native-order-transition-v1"
PREPARED_DOCUMENT_SCHEMA = "chan-native-order-transition-v2"
# Deliberately not an executable CCXT schema. Old strict readers reject it too.
CONTRACT_SCHEMA = "chan-native-cas-order-v1"
_LOCAL_SOURCES = ("Trade/NativeOrderTransition.py", "Trade/CCXTTradeEngine.py")
_INTENT_UPDATES = {"status", "open_client_order_id", "open_requested_qty", "open_filled_qty", "current_qty",
                   "open_order_status", "order_last_update", "position_side", "strategy_version", "risk_multiplier",
                   "model_score_before", "snapshot_before", "open_order_contract", "open_intent_ms"}
_CLAIM_UPDATES = {"open_order_status", "order_last_update"}
SCHEMA = {TABLE: f"""CREATE TABLE {TABLE}(
    trade_table TEXT NOT NULL, record_id INTEGER NOT NULL, phase TEXT NOT NULL CHECK(phase='open'),
    attempt INTEGER NOT NULL CHECK(attempt>0), stage TEXT NOT NULL CHECK(stage IN ('intent','claim')),
    binding_sha256 TEXT NOT NULL, event_id INTEGER NOT NULL UNIQUE,
    payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
    PRIMARY KEY(trade_table,record_id,phase,attempt,stage),
    FOREIGN KEY(trade_table,record_id,phase,attempt)
        REFERENCES {ATTEMPTS}(trade_table,record_id,phase,attempt),
    FOREIGN KEY(event_id) REFERENCES {EVENTS}(event_id))"""}
for _verb in ("UPDATE", "DELETE"):
    _name = f"{TABLE}_no_{_verb.lower()}"
    SCHEMA[_name] = f"CREATE TRIGGER {_name} BEFORE {_verb} ON {TABLE} BEGIN SELECT RAISE(ABORT,'native order boundaries are append-only'); END"


def _fail():
    raise CChanException("原生逐单 L1/L2/原 CAS 增量不一致；不是资金或发送许可", ErrCode.TRADE_UNLOCK_FAIL) from None


def initialize_schema(conn):
    if conn.execute("SELECT name FROM sqlite_master WHERE name=?", (TABLE,)).fetchone() is None:
        for sql in SCHEMA.values():
            conn.execute(sql)
    validate_schema(conn, SCHEMA)


def _implementation():
    return {**Boundary._implementation(), **{name: hashlib.sha256(Path(__file__).with_name(name.split("/")[-1]).read_bytes()).hexdigest()
                                             for name in _LOCAL_SOURCES}}


def _owned(chan):
    database = Boundary._database(chan)
    Boundary._same_database(chan, database, database.conn, chan.table, owned=True)
    validate_schema(database.conn, SCHEMA)
    if any(database.query_one(f"PRAGMA {name}")[name] != 1 for name in ("foreign_keys", "recursive_triggers")):
        _fail()
    return database


def _records(chan):
    return [{"trade_table": table, "record": row} for table in _trade_tables(chan)
            for row in chan.db.query(f"SELECT * FROM {table} ORDER BY id")]


def _prefix(database):
    prefix = _journal_prefix(database)
    if any(database.query_one(f"SELECT count(*) AS n FROM {table}")["n"] != prefix[key]
           for table, key in ((ATTEMPTS, "attempt_count"), (EVENTS, "event_count"))):
        _fail()
    return prefix


def _replace_record(records, table, expected):
    result = copy.deepcopy(records)
    matching = [row for row in result if row["trade_table"] == table and row["record"]["id"] == expected["id"]]
    if len(matching) != 1:
        _fail()
    matching[0]["record"] = expected
    return result


def _historical_ledger(database, root, attempt, ordinal):
    """Rebuild from the original check and the one verified immutable attempt."""
    boundary = root["boundary"]["payload"]
    check = read_check(database, boundary["check_id"])
    saved = check["payload"]["inputs"]
    if (saved is None or check["payload"]["account_context"] != boundary["account_context"]
            or _sha({k: saved[k] for k in ("histories", "projections")}) != boundary["ledger_sha256"]
            or saved["journal_prefix"] != boundary["journal_prefix"]):
        _fail()
    entries = {(p["trade_table"], p["record_id"]): (h, p) for h, p in zip(saved["histories"], saved["projections"])}
    identity = attempt["identity"]
    key = (identity["trade_table"], identity["record_id"])
    if key in entries or attempt["origin"] != "new_intent" or identity["phase"] != "open" or identity["attempt"] != 1:
        _fail()
    events = attempt["events"][:ordinal]
    history = {"schema": "chan-order-history-v1", "coverage": "intents_and_applied_reports_only", "economics_complete": False,
               "attempts": [{**attempt, "events": events}], "gaps": []}
    projection = {"trade_table": key[0], "record_id": key[1], "instrument": identity["instrument"],
                  "current_qty": events[-1]["state"]["current_qty"], "position_side": identity["position_side"], "is_buy": bool(identity["is_buy"])}
    entries[key] = (history, projection)
    return {"histories": [entries[k][0] for k in sorted(entries)], "projections": [entries[k][1] for k in sorted(entries)]}


def _reference(history, attempt):
    matching = [row for row in history["attempts"] if row["identity"]["phase"] == "open" and row["identity"]["attempt"] == attempt]
    return matching[0]["events"][0].get("native_boundary_sha256") if len(matching) == 1 else None


def _read(chan, record):
    """Historical original rows, not caller-supplied/resealed L1/L2 documents."""
    database = _owned(chan)
    history = read_history(database, chan.table, record)
    reference = _reference(history, record["open_attempt"])
    if reference is None:
        _fail()
    target_key = (chan.table, record["id"], "open", record["open_attempt"])
    attempt = next(a for a in history["attempts"] if _key(a["identity"]) == target_key)
    rows = database.query(f"SELECT * FROM {TABLE} WHERE trade_table=? AND record_id=? AND phase=? AND attempt=? ORDER BY event_id", target_key)
    if not 1 <= len(rows) <= 2:
        _fail()
    previous, first_root = None, None
    for ordinal, row in enumerate(rows, 1):
        document = json.loads(row["payload"])
        p = document["payload"]
        root, stage = p["root"], "intent" if ordinal == 1 else "claim"
        prepared = document["schema"] == PREPARED_DOCUMENT_SCHEMA
        if (set(document) != {"schema", "payload", "payload_sha256"} or document["schema"] not in {DOCUMENT_SCHEMA, PREPARED_DOCUMENT_SCHEMA}
                or canonical_bytes(document).decode() != row["payload"] or _sha(document) != row["payload_sha256"]
                or _sha(p) != document["payload_sha256"]
                or set(p) != {"root", "binding_sha256", "boundary", "stage", "previous_sha256", "after_record_sha256",
                              "ledger_sha256", "records_sha256", "journal_prefix", "event_sha256", "coverage",
                              "economics_complete", "native_admission_verified"}
                or set(root) != {"boundary", "target", "before_record_sha256", "requested_updates_sha256", "implementation_sha256"} | ({"preparation"} if prepared else set())
                or canonical_bytes(root["target"]) != canonical_bytes(dict(zip(("trade_table", "record_id", "phase", "attempt"), target_key)))
                or canonical_bytes(p["boundary"]) != canonical_bytes(root["boundary"]) or p["stage"] != stage or row["stage"] != stage
                or p["binding_sha256"] != reference or row["binding_sha256"] != reference or _sha(root) != reference
                or p["previous_sha256"] != previous or (first_root is not None and canonical_bytes(root) != canonical_bytes(first_root))
                or p["coverage"] != "exact_original_cas_delta_only"
                or p["economics_complete"] is not False or p["native_admission_verified"] is not False):
            _fail()
        if prepared:
            from .NativePreparedIntent import validate_stored_preparation
            validate_stored_preparation(chan, root, attempt)
        event_row = database.query_one(f"SELECT * FROM {EVENTS} WHERE event_id=?", (row["event_id"],))
        event = _load(event_row)
        if (tuple(event_row[k] for k in ("trade_table", "record_id", "phase", "attempt")) != target_key
                or event["kind"] != stage or event["ordinal"] != ordinal
                or event.get("native_boundary_sha256") != reference or event_row["payload_sha256"] != p["event_sha256"]
                or event["native_delta"]["record_sha256"] != p["after_record_sha256"]
                or event["native_delta"]["records_sha256"] != p["records_sha256"]
                or p["ledger_sha256"] != _sha(_historical_ledger(database, root, attempt, ordinal))
                or p["journal_prefix"]["attempt_count"] != root["boundary"]["payload"]["journal_prefix"]["attempt_count"]+1
                or p["journal_prefix"]["event_count"] != root["boundary"]["payload"]["journal_prefix"]["event_count"]+ordinal
                or p["journal_prefix"]["boundaries"]["event_id"] != row["event_id"]
                or p["journal_prefix"] != _journal_prefix(database, p["journal_prefix"]["boundaries"])):
            _fail()
        previous, first_root = document["payload_sha256"], root
    return document


def _current(chan, document):
    database = _owned(chan)
    connection, table = database.conn, chan.table
    p, root = document["payload"], document["payload"]["root"]
    boundary = root["boundary"]["payload"]
    implementation = _implementation()
    Boundary._same_database(chan, database, connection, table, owned=True)
    if (root["implementation_sha256"] != implementation
            or boundary["implementation_sha256"] != {k: v for k, v in implementation.items() if k not in _LOCAL_SOURCES}
            or p["journal_prefix"] != _prefix(database)
            or p["ledger_sha256"] != _sha(_ledger(chan)) or p["records_sha256"] != _sha(_records(chan))
            or p["after_record_sha256"] != _sha(chan.get_record(root["target"]["record_id"]))):
        _fail()
    inputs = Boundary._inputs({key: boundary[key] for key in Boundary._INPUTS})
    snapshot = _sources_snapshot(chan, inputs["account_context"], inputs["check_id"], inputs["market_evidence"])
    state = risk_state(database, inputs["account_context"])
    implementation = _implementation()
    Boundary._same_database(chan, database, connection, table, owned=True)
    location = _sha(database.query("PRAGMA database_list"))
    Boundary._same_database(chan, database, connection, table, owned=True)
    if (state["check_ids"] != boundary["account_check_ids"]
            or location != boundary["database_location_sha256"] or root["implementation_sha256"] != implementation):
        _fail()
    Boundary._windows(inputs, snapshot, boundary["captured_ms"], utc_now_ms())


def prepare_transition(chan, before, kind, updates, boundary, *, history, prepared_context=None):
    """Internal original writer hook, not a stand-alone approval API."""
    try:
        if kind == "intent" and boundary is None:
            if prepared_context is not None:
                _fail()
            return None
        reference = _reference(history, before["open_attempt"])
        if kind == "claim" and (reference is None or before["open_order_status"] != "created"):
            if reference is None and before.get("open_order_contract") is not None and json.loads(before["open_order_contract"]).get("schema") == CONTRACT_SCHEMA:
                _fail()  # Missing metadata cannot downgrade this new schema.
            return None  # The original CAS still decides duplicates/recovery.
        database = _owned(chan)
        connection, table = database.conn, chan.table
        if canonical_bytes(history) != canonical_bytes(read_history(database, chan.table, before)):
            _fail()  # The writer's internal routing input is not proof authority.
        if type(updates) is not dict or set(updates) != (_INTENT_UPDATES if kind == "intent" else _CLAIM_UPDATES):
            _fail()
        start = utc_now_ms()
        if kind == "intent":
            Boundary.assert_native_order_boundary(chan, boundary)
            if history["attempts"] or history["gaps"] or before["status"] != "signal" or before["open_attempt"] != 0:
                _fail()
            expected = {**before, **updates, "open_attempt": 1}
            if updates["model_score_before"] is None:
                expected["model_score_before"] = before["model_score_before"]
            contract = json.loads(expected["open_order_contract"])
            identity = _identity(chan.table, expected, "open")
            declared = [row["market"] for row in boundary["payload"]["market_evidence"]["payload"]["observations"]
                        if row["market"]["symbol"] == before["stock_code"]]
            if (identity["contract_complete"] is not True or contract.get("schema") != CONTRACT_SCHEMA
                    or len(declared) != 1 or canonical_bytes(contract["market"]) != canonical_bytes(declared[0])
                    or contract["account_context"] != boundary["payload"]["account_context"]
                    or contract["contract_id"] != _sha({k: v for k, v in contract.items() if k != "contract_id"})
                    or contract["reduce_only"] is not False or contract["market"]["symbol"] != before["stock_code"]
                    or contract["execution"]["position_side"] != expected["position_side"]
                    or Decimal(contract["quantity"]) != Decimal(str(expected["open_requested_qty"]))
                    or not boundary["payload"]["captured_ms"] <= expected["open_intent_ms"] <= start):
                _fail()
            from .CCXTTradeEngine import CCCXTTradeEngine
            CCCXTTradeEngine._check_execution_evidence(contract, expected, "open")
            root = {"boundary": json.loads(canonical_bytes(boundary)), "target": dict(zip(("trade_table", "record_id", "phase", "attempt"), _key(identity))),
                    "before_record_sha256": _sha(before), "requested_updates_sha256": _sha(updates), "implementation_sha256": _implementation()}
            if prepared_context is not None:
                from .NativePreparedIntent import consume_prepared_context
                root["preparation"] = consume_prepared_context(chan, before, updates, boundary, prepared_context)
            reference, previous = _sha(root), None
        else:
            previous_document = _read(chan, before)
            if previous_document["schema"] == PREPARED_DOCUMENT_SCHEMA:
                _fail()  # Post-intent local reconstitution/funding is not implemented.
            if previous_document["payload"]["stage"] != "intent":
                _fail()
            _current(chan, previous_document)
            root, previous = previous_document["payload"]["root"], previous_document["payload_sha256"]
            expected = {**before, **updates}
        Boundary._same_database(chan, database, connection, table, owned=True)
        records = _records(chan)
        expected_records = _replace_record(records, chan.table, expected)
        return {"root": root, "binding_sha256": reference, "previous_sha256": previous, "stage": kind,
                "expected": expected, "expected_records": expected_records, "prefix": _prefix(database),
                "native_delta": {"schema": "chan-native-cas-delta-v1", "record_sha256": _sha(expected), "records_sha256": _sha(expected_records)},
                "prepared_context": prepared_context,
                "database": database, "connection": database.conn, "table": chan.table, "started_ms": start}
    except Exception:
        _fail()


def finish_transition(chan, before, after, transition):
    """Check the one original event/attempt and complete deterministic delta."""
    try:
        t = transition
        Boundary._same_database(chan, t["database"], t["connection"], t["table"], owned=True)
        database = _owned(chan)
        if canonical_bytes(after) != canonical_bytes(t["expected"]):
            _fail()
        prefix = t["prefix"]
        if _journal_prefix(database, prefix["boundaries"]) != prefix:
            _fail()
        added = database.query(f"SELECT * FROM {EVENTS} WHERE event_id>? ORDER BY event_id", (prefix["boundaries"]["event_id"],))
        if len(added) != 1:
            _fail()
        event_row, stage = added[0], t["stage"]
        identity = _identity(chan.table, after, "open")
        target = _key(identity)
        attempt_row = database.query_one(f"SELECT * FROM {ATTEMPTS} WHERE trade_table=? AND record_id=? AND phase=? AND attempt=?", target)
        attempt = _read_attempt(database, attempt_row)
        previous_event = attempt["events"][-2] if stage == "claim" else None
        expected_event = {"identity_sha256": attempt_row["payload_sha256"], "kind": stage, "ordinal": 1 if stage == "intent" else 2,
                          "previous_sha256": None if previous_event is None else _sha(previous_event),
                          "observed_ms": event_row["observed_ms"], "state": _state(t["expected"], "open"),
                          "native_boundary_sha256": t["binding_sha256"], "native_delta": t["native_delta"]}
        expected_attempt = {"identity": identity, "origin": "new_intent", "observed_ms": attempt_row["observed_ms"]}
        if (tuple(event_row[k] for k in ("trade_table", "record_id", "phase", "attempt")) != target
                or canonical_bytes(_load(event_row)) != canonical_bytes(expected_event)
                or canonical_bytes(_load(attempt_row)) != canonical_bytes(expected_attempt)
                or len(attempt["events"]) != (1 if stage == "intent" else 2)
                or type(event_row["observed_ms"]) is not int or not t["started_ms"] <= event_row["observed_ms"] <= utc_now_ms()):
            _fail()
        expected_ledger = _historical_ledger(database, t["root"], attempt, len(attempt["events"]))
        actual_ledger = _ledger(chan)
        expected_records = t["expected_records"]
        current_prefix = _prefix(database)
        if (canonical_bytes(actual_ledger) != canonical_bytes(expected_ledger)
                or canonical_bytes(_records(chan)) != canonical_bytes(expected_records)
                or current_prefix["event_count"] != prefix["event_count"]+1
                or current_prefix["attempt_count"] != prefix["attempt_count"]+(stage == "intent")):
            _fail()
        payload = {"root": t["root"], "boundary": t["root"]["boundary"], "binding_sha256": t["binding_sha256"], "stage": stage,
                   "previous_sha256": t["previous_sha256"], "after_record_sha256": _sha(after), "ledger_sha256": _sha(actual_ledger),
                   "records_sha256": _sha(expected_records), "journal_prefix": current_prefix, "event_sha256": event_row["payload_sha256"],
                   "coverage": "exact_original_cas_delta_only", "economics_complete": False, "native_admission_verified": False}
        document = {"schema": PREPARED_DOCUMENT_SCHEMA if "preparation" in t["root"] else DOCUMENT_SCHEMA,
                    "payload": payload, "payload_sha256": _sha(payload)}
        database.execute(f"INSERT INTO {TABLE}(trade_table,record_id,phase,attempt,stage,binding_sha256,event_id,payload,payload_sha256) VALUES(?,?,?,?,?,?,?,?,?)",
                         (*target, stage, t["binding_sha256"], event_row["event_id"], canonical_bytes(document).decode(), _sha(document)))
        if _read(chan, after) != document:
            _fail()
        Boundary._same_database(chan, t["database"], t["connection"], t["table"], owned=True)
        if "preparation" in t["root"]:
            from .NativePreparedIntent import finish_prepared_context
            finish_prepared_context(chan, t["prepared_context"], t["expected"], document)
        else:
            _current(chan, document)  # Publication/readback must not escape source budgets.
    except Exception:
        _fail()


def read_native_order_transition(chan, record_id):
    """Historical reference only; no freshness, allocation, release or ready flag."""
    try:
        database = Boundary._database(chan)
        with database.transaction():
            return _read(chan, chan.get_record(record_id))
    except Exception:
        _fail()


def assert_native_order_transition(chan, record_id):
    """Original owned transaction must still be exactly the persisted L2."""
    try:
        _owned(chan)
        document = _read(chan, chan.get_record(record_id))
        if document["payload"]["stage"] != "claim":
            _fail()
        _current(chan, document)
    except Exception:
        _fail()
