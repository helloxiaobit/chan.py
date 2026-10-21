"""Append-only native cash-source facts; importing them never books an order."""
import hashlib
import json

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .ExecutionFacts import SCHEMA as RECEIPT_SCHEMA, verify_execution_fact, verify_execution_scan
from .OrderAudit import validate_schema
from .AccountIdentity import verify_account_context


FACTS = "chanpy_execution_facts"
SCANS = "chanpy_execution_scans"
SCHEMA = {
    FACTS: f"""CREATE TABLE {FACTS}(
        account_scope TEXT NOT NULL, venue TEXT NOT NULL, mode TEXT NOT NULL, instrument TEXT NOT NULL,
        kind TEXT NOT NULL, source_id TEXT NOT NULL, source_ms INTEGER NOT NULL,
        observed_ms INTEGER NOT NULL, payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
        PRIMARY KEY(account_scope,venue,mode,instrument,kind,source_id))""",
    SCANS: f"""CREATE TABLE {SCANS}(
        scan_id TEXT PRIMARY KEY, account_scope TEXT NOT NULL, venue TEXT NOT NULL,
        mode TEXT NOT NULL, instrument TEXT NOT NULL, observed_ms INTEGER NOT NULL,
        payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL)""",
    "chanpy_execution_global_source": f"""CREATE UNIQUE INDEX chanpy_execution_global_source ON {FACTS}
        (account_scope,venue,mode,kind,source_id) WHERE kind='funding'""",
    "chanpy_execution_okx_bill": f"""CREATE UNIQUE INDEX chanpy_execution_okx_bill ON {FACTS}
        (account_scope,venue,mode,source_id) WHERE venue='okx'""",
}
for _table in (FACTS, SCANS):
    for _verb in ("UPDATE", "DELETE"):
        _name = f"{_table}_no_{_verb.lower()}"
        SCHEMA[_name] = (f"CREATE TRIGGER {_name} BEFORE {_verb} ON {_table} "
                         "BEGIN SELECT RAISE(ABORT, 'execution evidence is append-only'); END")


def _fail():
    raise CChanException("逐笔经济事实/账户命名空间/导入清单不一致", ErrCode.LIST_ORDER_FAIL)


def initialize_schema(conn):
    if not conn.execute("SELECT name FROM sqlite_master WHERE name IN (?,?)", (FACTS, SCANS)).fetchall():
        for sql in SCHEMA.values():
            conn.execute(sql)
    validate_schema(conn, SCHEMA)


def _dump(value):
    raw = canonical_bytes(value).decode("utf-8")
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load(row):
    try:
        value = json.loads(row["payload"])
        if _dump(value) != (row["payload"], row["payload_sha256"]):
            _fail()
        return value
    except (KeyError, TypeError, ValueError):
        raise CChanException("逐笔经济事实不是完整有限 canonical JSON", ErrCode.LIST_ORDER_FAIL) from None


def _context(payload):
    return (payload["account_scope"], payload["venue"], payload["mode"], payload["market"]["symbol"])


def _row_context(row):
    return tuple(row[key] for key in ("account_scope", "venue", "mode", "instrument"))


def _read_fact(row):
    value = _load(row)
    if not isinstance(value, dict) or set(value) != {"account_scope", "venue", "mode", "market", "fact"}:
        _fail()
    fact = value["fact"]
    verify_execution_fact(fact, value["market"], value["venue"])
    if (_context(value) != _row_context(row) or fact["source_id"] != row["source_id"]
            or fact["kind"] != row["kind"] or fact["source_ms"] != row["source_ms"]):
        _fail()
    return value


def _verify_observation(observation, payload):
    try:
        if (set(observation) != {"schema", "account_context", "started_ms", "finished_ms", "coverage"}
                or observation["schema"] != "chan-execution-account-observation-v1"
                or observation["coverage"] != "native_context_observed_around_scan"
                or any(type(observation[k]) is not int for k in ("started_ms", "finished_ms"))
                or not 0 <= observation["started_ms"] <= observation["finished_ms"] <= utc_now_ms()
                or payload["end_ms"] > observation["finished_ms"]):
            _fail()
        account = observation["account_context"]
        verify_account_context(account)
        if account["venue"] != payload["venue"] or account["mode"] != payload["mode"]:
            _fail()
        return observation
    except (TypeError, ValueError, KeyError, AttributeError):
        _fail()


def _prepare_observation(observed, payload):
    if observed is None:
        return None
    try:
        if set(observed) != {"before", "after", "started_ms", "finished_ms"}:
            _fail()
        verify_account_context(observed["before"])
        verify_account_context(observed["after"])
        if canonical_bytes(observed["before"]) != canonical_bytes(observed["after"]):
            _fail()
        return _verify_observation({"schema": "chan-execution-account-observation-v1",
            "account_context": observed["before"], "started_ms": observed["started_ms"],
            "finished_ms": observed["finished_ms"], "coverage": "native_context_observed_around_scan"}, payload)
    except (TypeError, ValueError, KeyError, AttributeError):
        _fail()


def _read_manifest(row):
    manifest = _load(row)
    expected = {"schema", "context", "facts", "receipt_sha256"}
    if not isinstance(manifest, dict) or not expected <= set(manifest):
        _fail()
    context = manifest["context"]
    try:
        stored_context = _context(context)
    except (KeyError, TypeError, AttributeError):
        _fail()
    if (not isinstance(manifest["facts"], list)
            or any(not isinstance(ref, dict) or set(ref) != {"kind", "source_id", "payload_sha256"} for ref in manifest["facts"])):
        _fail()
    if manifest["schema"] == "chan-execution-manifest-v2":
        expected.add("native_account")
        _verify_observation(manifest.get("native_account"), context)
    elif manifest["schema"] != "chan-execution-manifest-v1":
        _fail()
    if (set(manifest) != expected or stored_context != _row_context(row)
            or manifest["receipt_sha256"] != row["scan_id"]):
        _fail()
    return manifest


def _namespace_account(db, context):
    # Header/account proof is independent of potentially large fact sets. Full
    # source/fact verification remains mandatory when reading a selected scan.
    account = None
    for row in db.query(f"SELECT * FROM {SCANS} WHERE account_scope=? AND venue=? AND mode=?", context[:3]):
        manifest = _read_manifest(row)
        native = manifest.get("native_account")
        if native is not None:
            candidate = canonical_bytes(native["account_context"])
            if account is not None and account != candidate:
                _fail()
            account = candidate
    return account


def store_scan(db, receipt, account_observation=None):
    verify_execution_scan(receipt)
    validate_schema(db.conn, SCHEMA)
    payload = receipt["payload"]
    context, observed, manifest = _context(payload), utc_now_ms(), []
    observation = _prepare_observation(account_observation, payload)
    bound = _namespace_account(db, context)
    existing = db.query_one(f"SELECT * FROM {SCANS} WHERE scan_id=?", (receipt["payload_sha256"],))
    if bound is not None and ((observation is None and existing is None)
            or (observation is not None and canonical_bytes(observation["account_context"]) != bound)):
        _fail()
    if existing:
        _read_scan(db, existing)
        previous = _read_manifest(existing).get("native_account")
        if ((previous is None) != (observation is None)
                or (previous is not None and canonical_bytes(previous["account_context"]) != canonical_bytes(observation["account_context"]))):
            _fail()  # Never backfill or strip the first import's native context.
        return receipt["payload_sha256"]
    for fact in payload["facts"]:
        document = {key: payload[key] for key in ("account_scope", "venue", "mode", "market")}
        raw, digest = _dump({**document, "fact": fact})
        existing = db.query_one(f"SELECT * FROM {FACTS} WHERE account_scope=? AND venue=? AND mode=? AND instrument=? AND kind=? AND source_id=?", (*context, fact["kind"], fact["source_id"]))
        if existing:
            _read_fact(existing)
            if (existing["payload"], existing["payload_sha256"]) != (raw, digest):
                _fail()
        else:
            db.execute(f"INSERT INTO {FACTS}(account_scope,venue,mode,instrument,kind,source_id,source_ms,observed_ms,payload,payload_sha256) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (*context, fact["kind"], fact["source_id"], fact["source_ms"], observed, raw, digest))
        manifest.append({"kind": fact["kind"], "source_id": fact["source_id"], "payload_sha256": digest})
    document = {"schema": "chan-execution-manifest-v1", "context": {key: value for key, value in payload.items() if key != "facts"},
                "facts": manifest, "receipt_sha256": receipt["payload_sha256"]}
    if observation is not None:
        document.update(schema="chan-execution-manifest-v2", native_account=observation)
    raw, digest = _dump(document)
    db.execute(f"INSERT INTO {SCANS}(scan_id,account_scope,venue,mode,instrument,observed_ms,payload,payload_sha256) VALUES(?,?,?,?,?,?,?,?)",
               (receipt["payload_sha256"], *context, observed, raw, digest))
    return receipt["payload_sha256"]


def _read_scan(db, row):
    manifest = _read_manifest(row)
    context = manifest["context"]
    facts = []
    for reference in manifest["facts"]:
        stored = db.query_one(f"SELECT * FROM {FACTS} WHERE account_scope=? AND venue=? AND mode=? AND instrument=? AND kind=? AND source_id=?",
                              (*_context(context), reference["kind"], reference["source_id"]))
        if stored is None or stored["payload_sha256"] != reference["payload_sha256"]:
            _fail()
        fact = _read_fact(stored)
        if fact["market"] != context["market"]:
            _fail()
        facts.append(fact["fact"])
    return verify_execution_scan({"schema": RECEIPT_SCHEMA, "payload_sha256": row["scan_id"], "payload": {**context, "facts": facts}})


def read_scan_with_account(db, scan_id):
    validate_schema(db.conn, SCHEMA)
    row = db.query_one(f"SELECT * FROM {SCANS} WHERE scan_id=?", (scan_id,))
    if row is None:
        _fail()
    receipt = _read_scan(db, row)
    manifest = _read_manifest(row)
    _namespace_account(db, _context(manifest["context"]))
    native = manifest.get("native_account")
    account = None if native is None else {"scan_id": scan_id, "manifest_sha256": row["payload_sha256"], "observation": native}
    return receipt, account


def read_scan_account(db, scan_id):
    return read_scan_with_account(db, scan_id)[1]


def read_scans(db, account_scope, instrument):
    validate_schema(db.conn, SCHEMA)
    return [_read_scan(db, row) for row in db.query(f"SELECT * FROM {SCANS} WHERE account_scope=? AND instrument=? ORDER BY observed_ms,scan_id", (account_scope, instrument))]


def read_facts(db, account_scope, instrument, venue, mode):
    validate_schema(db.conn, SCHEMA)
    return [_read_fact(row)["fact"] for row in db.query(f"SELECT * FROM {FACTS} WHERE account_scope=? AND instrument=? AND venue=? AND mode=? ORDER BY source_ms,kind,source_id", (account_scope, instrument, venue, mode))]
