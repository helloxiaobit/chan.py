"""Append-only account-wide source documents, separate from per-order facts.

These documents do not authorize trading. Wallet source identities are checked
against prior documents in the same native context; no delta is booked twice.
"""
import hashlib
import json
import re

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountSources import SNAPSHOT_SCHEMA, WALLET_SCHEMA, verify_account_snapshot, verify_wallet_scan
from .OrderAudit import validate_schema


TABLE = "chanpy_account_evidence"
SCHEMA = {TABLE: f"""CREATE TABLE {TABLE}(
    evidence_id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('wallet','snapshot')),
    context_id TEXT NOT NULL, venue TEXT NOT NULL, mode TEXT NOT NULL,
    observed_ms INTEGER NOT NULL, payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL)""",
    "chanpy_account_context": f"CREATE INDEX chanpy_account_context ON {TABLE}(context_id,kind)"}
for _verb in ("UPDATE", "DELETE"):
    _name = f"{TABLE}_no_{_verb.lower()}"
    SCHEMA[_name] = f"CREATE TRIGGER {_name} BEFORE {_verb} ON {TABLE} BEGIN SELECT RAISE(ABORT,'account evidence is append-only'); END"


def _fail():
    raise CChanException("账户证据/原生流水身份冲突或损坏，禁止推断账户对账通过", ErrCode.LIST_ORDER_FAIL) from None


def initialize_schema(conn):
    if conn.execute("SELECT name FROM sqlite_master WHERE name=?", (TABLE,)).fetchone() is None:
        for sql in SCHEMA.values():
            conn.execute(sql)
    validate_schema(conn, SCHEMA)


def _verify(document):
    if not isinstance(document, dict):
        _fail()
    if document.get("schema") == WALLET_SCHEMA:
        verify_wallet_scan(document)
        return "wallet"
    if document.get("schema") == SNAPSHOT_SCHEMA:
        verify_account_snapshot(document)
        return "snapshot"
    _fail()


def _encode(value):
    raw = canonical_bytes(value).decode("utf-8")
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_row(row):
    try:
        document = json.loads(row["payload"])
        raw, digest = _encode(document)
        kind = _verify(document)
        account = document["payload"]["account_context"]
        if (raw != row["payload"] or digest != row["payload_sha256"] or digest != row["evidence_id"]
                or kind != row["kind"] or account["context_id"] != row["context_id"]
                or account["venue"] != row["venue"] or account["mode"] != row["mode"]
                or type(row["observed_ms"]) is not int or row["observed_ms"] < document["payload"]["finished_ms"]):
            _fail()
        return document
    except (TypeError, ValueError, KeyError, AttributeError):
        _fail()


def store_evidence(db, document):
    validate_schema(db.conn, SCHEMA)
    kind = _verify(document)
    raw, digest = _encode(document)
    existing = db.query_one(f"SELECT * FROM {TABLE} WHERE evidence_id=?", (digest,))
    if existing:
        if canonical_bytes(_read_row(existing)) != canonical_bytes(document):
            _fail()
        return digest
    account = document["payload"]["account_context"]
    if kind == "wallet":
        current = {fact["source_id"]: canonical_bytes(fact) for fact in document["payload"]["facts"]}
        # No retrofit of instrument-scoped execution facts. These are native
        # account-wide identities and amounts, not a second source of trade PnL.
        for row in db.query(f"SELECT * FROM {TABLE} WHERE context_id=? AND kind='wallet'", (account["context_id"],)):
            previous = _read_row(row)
            for fact in previous["payload"]["facts"]:
                if fact["source_id"] in current and current[fact["source_id"]] != canonical_bytes(fact):
                    _fail()
    observed = utc_now_ms()
    if observed < document["payload"]["finished_ms"]:
        _fail()
    db.execute(f"INSERT INTO {TABLE}(evidence_id,kind,context_id,venue,mode,observed_ms,payload,payload_sha256) VALUES(?,?,?,?,?,?,?,?)",
        (digest, kind, account["context_id"], account["venue"], account["mode"], observed, raw, digest))
    return digest


def read_evidence(db, evidence_id):
    validate_schema(db.conn, SCHEMA)
    if not isinstance(evidence_id, str) or re.fullmatch(r"[0-9a-f]{64}", evidence_id) is None:
        _fail()
    row = db.query_one(f"SELECT * FROM {TABLE} WHERE evidence_id=?", (evidence_id,))
    if row is None:
        _fail()
    return _read_row(row)
