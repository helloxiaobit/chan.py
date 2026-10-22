"""Append-only native pending/balance observations, not financial checks.

Keep the accepted AccountStore table/schema unchanged. These raw source
documents neither publish a PASS nor acknowledge orders or clear freezes.
"""
import json
import re

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountRiskStore import account_key
from .AccountStore import _encode
from .NativeBalanceReservations import SCHEMA as BALANCE_SCHEMA, verify_native_balance_reservations
from .NativePendingOrders import SCHEMA as PENDING_SCHEMA, verify_native_pending_orders
from .OrderAudit import validate_schema


TABLE = "chanpy_native_account_observations"
SCHEMA = {TABLE: f"""CREATE TABLE {TABLE}(
    evidence_id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('pending','balance')),
    account_key TEXT NOT NULL, context_id TEXT NOT NULL, venue TEXT NOT NULL, mode TEXT NOT NULL,
    observed_ms INTEGER NOT NULL, payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL)""",
    "chanpy_native_observation_key": f"CREATE INDEX chanpy_native_observation_key ON {TABLE}(account_key,kind)"}
for _verb in ("UPDATE", "DELETE"):
    _name = f"{TABLE}_no_{_verb.lower()}"
    SCHEMA[_name] = f"CREATE TRIGGER {_name} BEFORE {_verb} ON {TABLE} BEGIN SELECT RAISE(ABORT,'native observations are append-only'); END"


def _fail():
    raise CChanException("原生账户来源缺失/漂移，禁止推断账户准入或解冻", ErrCode.LIST_ORDER_FAIL) from None


def _validate(conn):
    validate_schema(conn, SCHEMA)
    if any(conn.execute(f"PRAGMA {name}").fetchone()[0] != 1 for name in ("recursive_triggers", "foreign_keys")):
        _fail()


def initialize_schema(conn):
    if conn.execute("SELECT name FROM sqlite_master WHERE name=?", (TABLE,)).fetchone() is None:
        for sql in SCHEMA.values():
            conn.execute(sql)
    _validate(conn)


def _verify(document):
    if type(document) is not dict:
        _fail()
    if document.get("schema") == PENDING_SCHEMA:
        verify_native_pending_orders(document)
        return "pending"
    if document.get("schema") == BALANCE_SCHEMA:
        verify_native_balance_reservations(document)
        return "balance"
    _fail()


def _read_row(row):
    try:
        document = json.loads(row["payload"])
        raw, digest = _encode(document)
        kind = _verify(document)
        payload = document["payload"]
        account = payload["account_context"]
        if (raw != row["payload"] or digest != row["evidence_id"] or digest != row["payload_sha256"]
                or kind != row["kind"] or account_key(account) != row["account_key"]
                or account["context_id"] != row["context_id"] or account["venue"] != row["venue"] or account["mode"] != row["mode"]
                or type(row["observed_ms"]) is not int or not payload["finished_ms"] <= row["observed_ms"] <= utc_now_ms()):
            _fail()
        return document
    except (ValueError, TypeError, KeyError, AttributeError, CChanException):
        _fail()


def store_observation(db, document):
    _validate(db.conn)
    kind = _verify(document)
    raw, digest = _encode(document)
    existing = db.query_one(f"SELECT * FROM {TABLE} WHERE evidence_id=?", (digest,))
    if existing:
        if canonical_bytes(_read_row(existing)) != canonical_bytes(document):
            _fail()
        return digest
    account = document["payload"]["account_context"]
    observed = utc_now_ms()
    if observed < document["payload"]["finished_ms"]:
        _fail()
    db.execute(f"INSERT INTO {TABLE}(evidence_id,kind,account_key,context_id,venue,mode,observed_ms,payload,payload_sha256) VALUES(?,?,?,?,?,?,?,?,?)",
        (digest, kind, account_key(account), account["context_id"], account["venue"], account["mode"], observed, raw, digest))
    return digest


def read_observation(db, evidence_id):
    _validate(db.conn)
    if not isinstance(evidence_id, str) or re.fullmatch(r"[0-9a-f]{64}", evidence_id) is None:
        _fail()
    row = db.query_one(f"SELECT * FROM {TABLE} WHERE evidence_id=?", (evidence_id,))
    if row is None:
        _fail()
    return _read_row(row)


def read_account_observations(db, context):
    _validate(db.conn)
    key = account_key(context)
    # Validate metadata before filtering, so a damaged account column cannot
    # hide a newer observation. Same stable native account, not caller routes.
    documents = [_read_row(row) for row in db.query(f"SELECT * FROM {TABLE} ORDER BY evidence_id")]
    return [document for document in documents if account_key(document["payload"]["account_context"]) == key]
