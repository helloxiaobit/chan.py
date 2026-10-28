"""SQLite facts accompanying the existing projection, not another order engine.

Old events prove local intents/applied reports only. Explicit native terminal
observations retain original query evidence, never fees, funding or admission.
Hashes detect accidental drift, not whole-file forgery.
"""
import hashlib
import json

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes


ATTEMPTS = "chanpy_order_attempts"
EVENTS = "chanpy_order_events"
SCHEMA = {
    ATTEMPTS: f"""CREATE TABLE {ATTEMPTS}(
        trade_table TEXT NOT NULL, record_id INTEGER NOT NULL,
        phase TEXT NOT NULL CHECK(phase IN ('open','close')),
        attempt INTEGER NOT NULL CHECK(attempt>0), client_order_id TEXT NOT NULL UNIQUE,
        origin TEXT NOT NULL CHECK(origin IN ('new_intent','legacy_snapshot')),
        observed_ms INTEGER NOT NULL, payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
        PRIMARY KEY(trade_table,record_id,phase,attempt))""",
    EVENTS: f"""CREATE TABLE {EVENTS}(
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_table TEXT NOT NULL, record_id INTEGER NOT NULL, phase TEXT NOT NULL,
        attempt INTEGER NOT NULL, ordinal INTEGER NOT NULL CHECK(ordinal>0),
        kind TEXT NOT NULL, observed_ms INTEGER NOT NULL,
        data_sha256 TEXT NOT NULL, previous_sha256 TEXT,
        payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
        UNIQUE(trade_table,record_id,phase,attempt,ordinal),
        UNIQUE(trade_table,record_id,phase,attempt,kind,data_sha256),
        FOREIGN KEY(trade_table,record_id,phase,attempt)
            REFERENCES {ATTEMPTS}(trade_table,record_id,phase,attempt))""",
}
for _table in (ATTEMPTS, EVENTS):
    for _verb in ("UPDATE", "DELETE"):
        _name = f"{_table}_no_{_verb.lower()}"
        SCHEMA[_name] = (f"CREATE TRIGGER {_name} BEFORE {_verb} ON {_table} "
                         "BEGIN SELECT RAISE(ABORT, 'order audit is append-only'); END")


def _fail():
    raise CChanException("订单历史身份/字节/链不一致，禁止猜测对账", ErrCode.LIST_ORDER_FAIL)


def _hash(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _encode(value):
    return canonical_bytes(value).decode("utf-8")


def validate_schema(conn, schema=None):
    """Do not adopt similarly named foreign tables or missing guard triggers."""
    for name, sql in (SCHEMA if schema is None else schema).items():
        row = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
        if row is None or " ".join(row[0].split()) != " ".join(sql.split()):
            _fail()


def initialize_schema(conn):
    present = conn.execute("SELECT name FROM sqlite_master WHERE name IN (?,?)", (ATTEMPTS, EVENTS)).fetchall()
    if not present:
        for sql in SCHEMA.values():
            conn.execute(sql)
    validate_schema(conn)


# Copy only supported fields. Unknown contracts remain hashed, not guessed or
# copied as arbitrary nested request/response blobs (which can contain secrets).
_SCALAR = None
_BOUNDS = {"min": _SCALAR, "max": _SCALAR}
_CONTRACT = {key: _SCALAR for key in ("schema", "quantity_unit", "exchange_amount_unit", "quantity",
    "exchange_amount", "price", "reference_price", "notional", "reduce_only", "contract_id", "post_only", "software_quote_max_age_ms",
    "monetary_basis_sha256")}
_CONTRACT.update({
    "paper_account": {"schema": _SCALAR, "account_id": _SCALAR},
    "paper_store": {"schema": _SCALAR, "store_id": _SCALAR},
    "market": {**{key: _SCALAR for key in ("exchange", "id", "symbol", "type", "base", "quote", "settle",
        "contractSize", "precision_mode")}, "precision": {key: _SCALAR for key in ("amount", "price", "base", "quote", "cost")},
        "limits": {"amount": _BOUNDS, "price": _BOUNDS, "cost": _BOUNDS}},
    "execution": {key: _SCALAR for key in ("venue", "position_mode", "position_side", "margin_mode", "leverage")},
    "account_observation": {key: _SCALAR for key in ("hedged", "margin_mode", "long_leverage", "short_leverage")},
    "account_context": {
        **{key: _SCALAR for key in ("schema", "venue", "mode", "identifier_kind", "identifier_sha256", "context_id")},
        "environment": {"sandbox": _SCALAR, "hostname": _SCALAR, "simulated_trading": _SCALAR,
            "private_routes": {key: _SCALAR for key in ("fapiPrivate", "fapiPrivateV2", "fapiPrivateV3", "rest")}},
    },
})


def _whitelist(value, shape):
    if value is None:
        return None
    if shape is None:
        return value if type(value) in (str, int, float, bool) else None
    if not isinstance(value, dict):
        return None
    return {key: _whitelist(value[key], child) for key, child in shape.items() if key in value}


def _identity(table, record, prefix):
    raw = record.get(f"{prefix}_order_contract")
    contract = None if raw is None else _whitelist(json.loads(raw), _CONTRACT)
    identity = {"trade_table": table, "record_id": record["id"], "phase": "open" if prefix == "open" else "close",
        "attempt": record.get(f"{prefix}_attempt"), "client_order_id": record.get(f"{prefix}_client_order_id"),
        "instrument": record["stock_code"], "is_buy": record["is_buy"], "position_side": record.get("position_side"),
        "requested_qty": record.get(f"{prefix}_requested_qty"), "intent_ms": record.get(f"{prefix}_intent_ms"),
        "order_contract": contract, "contract_sha256": None if raw is None else _hash(raw),
        "contract_complete": raw is not None and _encode(contract) == raw,
        "strategy_version": record.get("strategy_version"), "model_version": record.get("model_version"),
        "deployment_id": record.get("deployment_id")}
    if prefix == "open":
        try:
            snapshot = json.loads(record.get("snapshot_before") or "{}")
        except (TypeError, ValueError):
            snapshot = None  # 无新字段的旧不透明快照不补造证明，也不重写原历史。
        if isinstance(snapshot, dict) and "opening_inputs" in snapshot:
            proof = snapshot["opening_inputs"]
            hashes = ("config_sha256", "scope_sha256", "inputs_sha256", "signal_event_id")
            version = proof.get("schema") if isinstance(proof, dict) else None
            extra = {"quote"} if version == "chan-opening-input-check-v2" else set()
            if (not isinstance(proof, dict) or set(proof) != {"schema", "checked_at_ms", "native_admission_verified", *hashes, *extra}
                    or type(version) is not str or version not in {"chan-opening-input-check-v1", "chan-opening-input-check-v2"}
                    or proof["native_admission_verified"] is not False
                    or type(proof["checked_at_ms"]) is not int or not 0 <= proof["checked_at_ms"] < 2**63
                    or any(not isinstance(proof[key], str) or len(proof[key]) != 64
                        or set(proof[key])-set("0123456789abcdef") for key in hashes)):
                _fail()
            if extra:
                from Common.MarketQuote import read_quote_batch, SOFTWARE_SCHEMA
                from CustomBuySellPoint.Decision import read_decision
                quote = proof["quote"]
                if not isinstance(quote, dict) or set(quote) != {"batch", "max_age_ms"}:
                    _fail()
                signal = read_decision(record["signal_decision"].encode())
                batch = read_quote_batch(quote["batch"], source=signal["identity"]["market"],
                    symbols=[row["symbol"] for row in quote["batch"]["payload"]["quotes"]],
                    now_ms=proof["checked_at_ms"], max_age_ms=quote["max_age_ms"])
                if batch["schema"] == SOFTWARE_SCHEMA and (not isinstance(contract, dict)
                        or contract.get("schema") != "chan-paper-order-v3" or not isinstance(contract.get("paper_store"), dict)
                        or contract.get("software_quote_max_age_ms") != batch["payload"]["software_max_age_ms"]
                        or contract["paper_store"].get("schema") != "chan-paper-store-v1"):
                    _fail()
                prices = {row["symbol"]: row["price"] for row in batch["payload"]["quotes"]}
                if (signal["event_id"] != proof["signal_event_id"] or signal["identity"]["kind"] != "signal"
                        or signal["identity"]["code"] != record["stock_code"]
                        or signal["identity"]["level"] != record["lv"] or signal["identity"]["bs_type"] != record["bstype"]
                        or record["stock_code"] not in prices or type(snapshot.get("price")) not in (int, float)
                        or snapshot["price"] != prices[record["stock_code"]]):
                    _fail()
            identity["opening_inputs"] = proof
    return identity


def _key(identity):
    return tuple(identity[key] for key in ("trade_table", "record_id", "phase", "attempt"))


def _identified(record, prefix):
    attempt, client = record.get(f"{prefix}_attempt"), record.get(f"{prefix}_client_order_id")
    return type(attempt) is int and attempt > 0 and isinstance(client, str) and bool(client)


def _state(record, prefix):
    return {"status": record["status"], "is_open": record["is_open"], "current_qty": record["current_qty"],
        "total_close_qty": record["cover_filled_qty"], "total_close_avg": record["cover_avg_price"],
        "order_id": record.get(f"{prefix}_order_id"), "order_status": record.get(f"{prefix}_order_status"),
        "filled_qty": record["open_filled_qty" if prefix == "open" else "cover_order_filled_qty"],
        "avg_price": record["open_price" if prefix == "open" else "cover_order_avg_price"]}


def _load(row):
    try:
        payload = json.loads(row["payload"])
        if _encode(payload) != row["payload"] or _hash(row["payload"]) != row["payload_sha256"]:
            _fail()
        return payload
    except (ValueError, TypeError, KeyError):
        _fail()


def _native_terminal_observation(identity, raw, started_ms, finished_ms):
    """Pure rebuild of a query's raw fields, not a caller permission or fill."""
    try:
        from decimal import localcontext
        from .ExecutionFacts import _MONEY, _id, _number, _string, _time
        from .NativePendingOrders import _raw_order
        from .NativePendingOwnership import _validate_contract
        _validate_contract(identity)
        contract = identity["order_contract"]
        if (identity["phase"] != "open" or contract["schema"] != "chan-native-client-order-v1"
                or contract["account_context"]["venue"] != "binance"
                or any(type(at) is not int or not 0 <= at < 2**63 for at in (started_ms, finished_ms))
                or not identity["intent_ms"] <= started_ms <= finished_ms
                or canonical_bytes(raw) != canonical_bytes(_raw_order(raw, "binance"))):
            _fail()
        created, updated = _time(raw["time"]), _time(raw["updateTime"])
        statuses = {"FILLED": "closed", "CANCELED": "canceled", "REJECTED": "rejected",
                    "EXPIRED": "canceled", "EXPIRED_IN_MATCH": "canceled"}
        status = statuses[raw["status"]]
        if (not identity["intent_ms"] <= created <= updated <= finished_ms
                or raw["symbol"] != contract["market"]["id"]
                or raw["clientOrderId"] != identity["client_order_id"] or int(_id(raw["orderId"])) <= 0
                or raw["side"] != ("BUY" if identity["is_buy"] else "SELL")
                or raw["positionSide"] != identity["position_side"]
                or raw["type"] != ("MARKET" if contract["price"] is None else "LIMIT")
                or raw["origType"] != raw["type"] or raw["reduceOnly"] is not False
                or raw["closePosition"] is not False or raw.get("priceMatch") not in {"NONE", ""}
                or raw["timeInForce"] not in {"GTC", "IOC", "FOK", "GTX"}
                or (raw["timeInForce"] == "GTX") is not contract["post_only"]
                or (raw["type"] == "LIMIT" and raw["timeInForce"] != ("GTX" if contract["post_only"] else "GTC"))):
            _fail()
        with localcontext(_MONEY):
            requested, filled, size = (_number(value, positive=positive) for value, positive in
                ((raw["origQty"], True), (raw["executedQty"], False), (contract["market"]["contractSize"], True)))
            average, quote = _number(raw["avgPrice"]), _number(raw["cumQuote"])
            if (requested != _number(contract["quantity"]) or requested/size != _number(contract["exchange_amount"])
                    or not 0 <= filled <= requested or quote != filled*average
                    or (status == "closed" and filled != requested)
                    or (filled and average <= 0) or (not filled and (average != 0 or quote != 0))
                    or (contract["price"] is not None and _number(raw["price"]) != _number(contract["price"]))):
                _fail()
            payload = {"account_context": contract["account_context"], "contract_id": contract["contract_id"],
                "source": "original_query_native_response", "started_ms": started_ms, "finished_ms": finished_ms,
                "native_order_id": _id(raw["orderId"]), "client_order_id": identity["client_order_id"], "status": status,
                "requested_base_quantity": _string(requested), "requested_contracts": _string(requested/size),
                "filled_base_quantity": _string(filled), "filled_contracts": _string(filled/size),
                "average_price": _string(average) if filled else None, "raw": raw,
                "economics_complete": False, "native_admission_verified": False}
        return {"schema": "chan-native-order-terminal-observation-v1", "payload": payload,
                "payload_sha256": _hash(_encode(payload))}
    except Exception:
        raise CChanException("原生终态来源/原订单身份不完整，不能据此释放预留", ErrCode.LIST_ORDER_FAIL) from None


def _sdk_submission_report(values):
    """Normalize an SDK response's known facts, not a terminal-release proof."""
    try:
        from .ExecutionFacts import _id, _number, _string
        if (type(values) is not dict or set(values) != {"order_id", "client_order_id", "requested", "filled", "avg_price", "status"}
                or type(values["order_id"]) is not str or int(_id(values["order_id"])) <= 0
                or type(values["client_order_id"]) is not str or not values["client_order_id"]
                or values["client_order_id"].strip() != values["client_order_id"]
                or type(values["status"]) is not str or values["status"] not in {"open", "closed", "canceled", "rejected"}):
            _fail()
        def number(value, *, positive=False):
            if type(value) not in (str, int, float):
                _fail()
            return _number(str(value), positive=positive)
        requested, filled = number(values["requested"], positive=True), number(values["filled"])
        average = None if values["avg_price"] is None else number(values["avg_price"], positive=True)
        if (not 0 <= filled <= requested or bool(filled) != (average is not None)
                or (values["status"] == "closed" and filled != requested)):
            _fail()
        return {"order_id": values["order_id"], "client_order_id": values["client_order_id"],
            "requested": _string(requested), "filled": _string(filled),
            "avg_price": None if average is None else _string(average), "status": values["status"]}
    except Exception:
        _fail()


def _assert_sdk_submission(attempt, values):
    """Do not forget known POST facts across a later query or process restart."""
    from .ExecutionFacts import _number
    reports = [event["submission_report"] for event in attempt["events"] if event["kind"] == "sdk_submission_report"]
    if not reports:
        return
    if len(reports) != 1:
        _fail()
    known, actual = _sdk_submission_report(reports[0]), _sdk_submission_report(values)
    if (any(known[key] != actual[key] for key in ("order_id", "client_order_id", "requested"))
            or (known["status"] != "open" and known != actual)
            or _number(actual["filled"]) < _number(known["filled"])
            or (actual["filled"] == known["filled"] and actual["avg_price"] != known["avg_price"])):
        raise CChanException("查单累计回报与原已知提交事实矛盾，保留未知且禁止重下", ErrCode.LIST_ORDER_FAIL)


def _read_attempt(db, row):
    connection = db.conn
    payload = _load(row)
    identity = payload["identity"]
    if (_key(identity) != tuple(row[key] for key in ("trade_table", "record_id", "phase", "attempt"))
            or identity["client_order_id"] != row["client_order_id"] or payload["origin"] != row["origin"]
            or payload["observed_ms"] != row["observed_ms"]):
        _fail()
    rows = db.query(f"SELECT * FROM {EVENTS} WHERE trade_table=? AND record_id=? AND phase=? AND attempt=? ORDER BY ordinal", _key(identity))
    events, previous = [], None
    for ordinal, event_row in enumerate(rows, 1):
        event = _load(event_row)
        extra = {key: event[key] for key in ("native_order_observation", "submission_report") if key in event}
        if (event["identity_sha256"] != row["payload_sha256"] or event["ordinal"] != ordinal
                or event["previous_sha256"] != previous or event_row["previous_sha256"] != previous
                or event["kind"] != event_row["kind"] or event["observed_ms"] != event_row["observed_ms"]
                or event_row["ordinal"] != ordinal
                or _hash(_encode({"state": event["state"], **extra} if extra else event["state"])) != event_row["data_sha256"]):
            _fail()
        events.append(event)
        previous = event_row["payload_sha256"]
    if not events or events[0]["kind"] != ("intent" if row["origin"] == "new_intent" else "legacy_snapshot"):
        _fail()
    reference = events[0].get("native_boundary_sha256")
    if sum(event["kind"] == "sdk_submission_report" for event in events) > 1:
        _fail()
    for event in events:
        if event["kind"] == "native_terminal_observation":
            try:
                observation = event["native_order_observation"]
                value = observation["payload"]
                checked_ms = utc_now_ms()
                if db.conn is not connection:
                    _fail()
                valid = (set(event) == {"identity_sha256", "kind", "ordinal", "previous_sha256", "observed_ms", "state", "native_order_observation"}
                    and payload["origin"] == "new_intent" and reference is not None and len(events) >= 3
                    and events[1]["kind"] == "claim" and events[1].get("native_boundary_sha256") == reference
                    and type(event["observed_ms"]) is int and type(checked_ms) is int
                    and value["finished_ms"] <= event["observed_ms"] <= checked_ms < 2**63
                    and event["state"]["order_id"] == value["native_order_id"]
                    and canonical_bytes(observation) == canonical_bytes(_native_terminal_observation(
                        identity, value["raw"], value["started_ms"], value["finished_ms"])))
            except (ValueError, TypeError, KeyError, AttributeError):
                _fail()
            if not valid:
                _fail()
        elif "native_order_observation" in event:
            _fail()
        if event["kind"] == "sdk_submission_report":
            try:
                from .NativePendingOwnership import _validate_contract
                from .ExecutionFacts import _number
                _validate_contract(identity)
                report, contract = event["submission_report"], identity["order_contract"]
                checked_ms = utc_now_ms()
                if db.conn is not connection:
                    _fail()
                valid = (set(event) == {"identity_sha256", "kind", "ordinal", "previous_sha256", "observed_ms", "state", "submission_report"}
                    and payload["origin"] == "new_intent" and reference is not None and len(events) >= 3
                    and events[1]["kind"] == "claim" and events[1].get("native_boundary_sha256") == reference
                    and identity["phase"] == "open" and contract["schema"] == "chan-native-client-order-v1"
                    and identity["contract_complete"] is True and contract["account_context"]["venue"] == "binance"
                    and type(event["observed_ms"]) is int and type(checked_ms) is int
                    and identity["intent_ms"] <= event["observed_ms"] <= checked_ms < 2**63
                    and event["state"]["order_id"] == report["order_id"]
                    and report["client_order_id"] == identity["client_order_id"]
                    and _number(report["requested"]) == _number(contract["quantity"])
                    and canonical_bytes(report) == canonical_bytes(_sdk_submission_report(report))
                    and any(prior["kind"] == "ack" and prior["ordinal"] < event["ordinal"]
                            and prior["state"]["order_id"] == report["order_id"] for prior in events))
            except (ValueError, TypeError, KeyError, AttributeError):
                _fail()
            if not valid:
                _fail()
        elif "submission_report" in event:
            _fail()
        if "native_boundary_sha256" in event:
            value = event["native_boundary_sha256"]
            delta = event.get("native_delta")
            if (type(value) is not str or len(value) != 64 or set(value)-set("0123456789abcdef")
                    or identity["phase"] != "open" or payload["origin"] != "new_intent"
                    or event["kind"] not in {"intent", "claim"} or value != reference
                    or type(delta) is not dict or set(delta) != {"schema", "record_sha256", "records_sha256"}
                    or delta["schema"] != "chan-native-cas-delta-v1"
                    or any(type(delta[k]) is not str or len(delta[k]) != 64 or set(delta[k])-set("0123456789abcdef")
                           for k in ("record_sha256", "records_sha256"))):
                _fail()
        elif "native_delta" in event:
            _fail()
        if reference is not None and event["kind"] == "claim" and event.get("native_boundary_sha256") != reference:
            _fail()
    return {**payload, "events": events}


def _append(db, row, kind, state, *, native_boundary_sha256=None, native_delta=None, native_order_observation=None,
            submission_report=None, _assert_current=None):
    identity = _load(row)["identity"]
    key = _key(identity)
    if (native_order_observation is not None) != (kind == "native_terminal_observation"):
        _fail()
    if (submission_report is not None) != (kind == "sdk_submission_report"):
        _fail()
    extra = {}
    if native_order_observation is not None:
        extra["native_order_observation"] = native_order_observation
    if submission_report is not None:
        if canonical_bytes(submission_report) != canonical_bytes(_sdk_submission_report(submission_report)):
            _fail()
        extra["submission_report"] = submission_report
    if extra and _assert_current is None:
        _fail()
    digest = _hash(_encode({"state": state, **extra} if extra else state))
    if _assert_current is not None:
        _assert_current()
    duplicate = db.query_one(f"SELECT event_id FROM {EVENTS} WHERE trade_table=? AND record_id=? AND phase=? AND attempt=? AND kind=? AND data_sha256=?", (*key, kind, digest))
    if _assert_current is not None:
        _assert_current()
    if duplicate:
        return
    previous = db.query_one(f"SELECT ordinal,payload_sha256 FROM {EVENTS} WHERE trade_table=? AND record_id=? AND phase=? AND attempt=? ORDER BY ordinal DESC LIMIT 1", key)
    if _assert_current is not None:
        _assert_current()
    ordinal = previous["ordinal"]+1 if previous else 1
    previous_sha = previous["payload_sha256"] if previous else None
    observed = utc_now_ms()
    if _assert_current is not None:
        _assert_current()
    if native_order_observation is not None and (type(observed) is not int
            or not native_order_observation["payload"]["finished_ms"] <= observed < 2**63):
        _fail()
    if submission_report is not None and (type(observed) is not int or not identity["intent_ms"] <= observed < 2**63):
        _fail()
    event = {"identity_sha256": row["payload_sha256"], "kind": kind, "ordinal": ordinal,
             "previous_sha256": previous_sha, "observed_ms": observed, "state": state}
    if native_boundary_sha256 is not None:
        event["native_boundary_sha256"] = native_boundary_sha256
        event["native_delta"] = native_delta
    event.update(extra)
    raw = _encode(event)
    db.execute(f"INSERT INTO {EVENTS}(trade_table,record_id,phase,attempt,ordinal,kind,observed_ms,data_sha256,previous_sha256,payload,payload_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (*key, ordinal, kind, observed, digest, previous_sha, raw, _hash(raw)))
    if _assert_current is not None:
        _assert_current()


def _ensure(db, table, record, prefix, *, new=False, native_boundary_sha256=None, native_delta=None):
    if not _identified(record, prefix):
        if new:
            _fail()
        return None
    identity = _identity(table, record, prefix)
    row = db.query_one(f"SELECT * FROM {ATTEMPTS} WHERE trade_table=? AND record_id=? AND phase=? AND attempt=?", _key(identity))
    if row:
        existing = _read_attempt(db, row)
        if new or existing["identity"] != identity:
            _fail()
        return row
    origin, observed = ("new_intent" if new else "legacy_snapshot"), utc_now_ms()
    raw = _encode({"identity": identity, "origin": origin, "observed_ms": observed})
    db.execute(f"INSERT INTO {ATTEMPTS}(trade_table,record_id,phase,attempt,client_order_id,origin,observed_ms,payload,payload_sha256) VALUES(?,?,?,?,?,?,?,?,?)",
               (*_key(identity), identity["client_order_id"], origin, observed, raw, _hash(raw)))
    row = db.query_one(f"SELECT * FROM {ATTEMPTS} WHERE trade_table=? AND record_id=? AND phase=? AND attempt=?", _key(identity))
    _append(db, row, "intent" if new else "legacy_snapshot", _state(record, prefix),
            native_boundary_sha256=native_boundary_sha256, native_delta=native_delta)
    return row


def record_transition(db, table, before, after, prefix, kind, *, native_boundary_sha256=None, native_delta=None):
    """Caller owns the same transaction as the winning projection CAS."""
    for old_prefix in ("open", "cover"):
        _ensure(db, table, before, old_prefix)
    row = _ensure(db, table, after, prefix, new=kind == "intent",
                  native_boundary_sha256=native_boundary_sha256 if kind == "intent" else None, native_delta=native_delta)
    if row is not None and kind != "intent":
        _append(db, row, kind, _state(after, prefix), native_boundary_sha256=native_boundary_sha256, native_delta=native_delta)


def _history_header(attempts):
    kinds = {event["kind"] for attempt in attempts for event in attempt["events"]}
    native = "native_terminal_observation" in kinds
    if "sdk_submission_report" in kinds:
        return {"schema": "chan-order-history-v3",
            "coverage": ("intents_applied_reports_sdk_submission_reports_and_native_query_observations" if native
                         else "intents_applied_reports_and_sdk_submission_reports"), "economics_complete": False}
    return {"schema": "chan-order-history-v2" if native else "chan-order-history-v1",
            "coverage": "intents_applied_reports_and_native_query_observations" if native else "intents_and_applied_reports_only",
            "economics_complete": False}


def read_history(db, table, record):
    validate_schema(db.conn)
    rows = db.query(f"SELECT * FROM {ATTEMPTS} WHERE trade_table=? AND record_id=? ORDER BY CASE phase WHEN 'open' THEN 0 ELSE 1 END,attempt", (table, record["id"]))
    attempts = [_read_attempt(db, row) for row in rows]
    gaps = []
    for prefix, phase in (("open", "open"), ("cover", "close")):
        observed = [a["identity"]["attempt"] for a in attempts if a["identity"]["phase"] == phase]
        counter = record.get(f"{prefix}_attempt") or 0
        if len(observed) != counter or (observed and (observed[0] != 1 or observed[-1] != counter)):
            gaps.append({"phase": phase, "reason": "missing_attempts", "expected_count": counter, "observed": observed})
        if not _identified(record, prefix) and (record.get(f"{prefix}_order_id") or (record.get("open_filled_qty") if prefix == "open" else record.get("cover_filled_qty"))):
            gaps.append({"phase": phase, "reason": "unidentified_legacy_order"})
        for attempt in attempts:
            if attempt["identity"]["phase"] == phase and attempt["origin"] == "legacy_snapshot":
                gaps.append({"phase": phase, "attempt": attempt["identity"]["attempt"], "reason": "legacy_snapshot"})
            if attempt["identity"]["phase"] == phase and attempt["identity"]["attempt"] == counter:
                if attempt["identity"] != _identity(table, record, prefix):
                    _fail()
                state = _state(record, prefix)
                if any(attempt["events"][-1]["state"][key] != state[key]
                       for key in ("order_id", "order_status", "filled_qty", "avg_price")):
                    _fail()
    last = db.query_one(f"SELECT * FROM {EVENTS} WHERE trade_table=? AND record_id=? ORDER BY event_id DESC LIMIT 1", (table, record["id"]))
    if last:
        state = _load(last)["state"]
        current = _state(record, "open")
        if any(state[key] != current[key] for key in ("status", "is_open", "current_qty", "total_close_qty", "total_close_avg")):
            _fail()
    return {**_history_header(attempts), "attempts": attempts, "gaps": gaps}


def verify_history_prefix(db, histories):
    """Verify an old check's snapshot against immutable attempts/events only.

    The mutable projection may legitimately advance, or be inside a winning CAS
    before its event is appended. It is not the historical snapshot's source.
    """
    validate_schema(db.conn)
    try:
        for history in histories:
            if (set(history) != {"schema", "coverage", "economics_complete", "attempts", "gaps"}
                    or canonical_bytes({key: history[key] for key in ("schema", "coverage", "economics_complete")})
                       != canonical_bytes(_history_header(history["attempts"]))):
                _fail()
            for saved in history["attempts"]:
                row = db.query_one(f"SELECT * FROM {ATTEMPTS} WHERE trade_table=? AND record_id=? AND phase=? AND attempt=?", _key(saved["identity"]))
                if row is None:
                    _fail()
                actual = _read_attempt(db, row)
                head = lambda a: {k: v for k, v in a.items() if k != "events"}
                if (_encode(head(saved)) != _encode(head(actual)) or not saved["events"]
                        or _encode(saved["events"]) != _encode(actual["events"][:len(saved["events"])])):
                    _fail()
    except (ValueError, TypeError, KeyError, AttributeError):
        _fail()
