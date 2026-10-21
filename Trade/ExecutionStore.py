"""Append-only native cash-source facts; importing them never books an order."""
import hashlib
import json

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .ExecutionFacts import SCHEMA as RECEIPT_SCHEMA, verify_execution_fact, verify_execution_scan
from .OrderAudit import validate_schema


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
    fact = value["fact"]
    verify_execution_fact(fact, value["market"], value["venue"])
    if (set(value) != {"account_scope", "venue", "mode", "market", "fact"}
            or _context(value) != _row_context(row) or fact["source_id"] != row["source_id"]
            or fact["kind"] != row["kind"] or fact["source_ms"] != row["source_ms"]):
        _fail()
    return value


def store_scan(db, receipt):
    verify_execution_scan(receipt)
    validate_schema(db.conn, SCHEMA)
    payload = receipt["payload"]
    context, observed, manifest = _context(payload), utc_now_ms(), []
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
    raw, digest = _dump(document)
    existing = db.query_one(f"SELECT * FROM {SCANS} WHERE scan_id=?", (receipt["payload_sha256"],))
    if existing:
        _read_scan(db, existing)
        if (existing["payload"], existing["payload_sha256"]) != (raw, digest):
            _fail()
    else:
        db.execute(f"INSERT INTO {SCANS}(scan_id,account_scope,venue,mode,instrument,observed_ms,payload,payload_sha256) VALUES(?,?,?,?,?,?,?,?)",
                   (receipt["payload_sha256"], *context, observed, raw, digest))
    return receipt["payload_sha256"]


def _read_scan(db, row):
    manifest = _load(row)
    context = manifest["context"]
    if (set(manifest) != {"schema", "context", "facts", "receipt_sha256"}
            or manifest["schema"] != "chan-execution-manifest-v1"
            or _context(context) != _row_context(row) or manifest["receipt_sha256"] != row["scan_id"]):
        _fail()
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


def read_scans(db, account_scope, instrument):
    validate_schema(db.conn, SCHEMA)
    return [_read_scan(db, row) for row in db.query(f"SELECT * FROM {SCANS} WHERE account_scope=? AND instrument=? ORDER BY observed_ms,scan_id", (account_scope, instrument))]


def read_facts(db, account_scope, instrument, venue, mode):
    validate_schema(db.conn, SCHEMA)
    return [_read_fact(row)["fact"] for row in db.query(f"SELECT * FROM {FACTS} WHERE account_scope=? AND instrument=? AND venue=? AND mode=? ORDER BY source_ms,kind,source_id", (account_scope, instrument, venue, mode))]
