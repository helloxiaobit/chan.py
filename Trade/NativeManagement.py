"""Original local management identities, not current sources or permission.

The eventual action consumer must own current collection, quantity checks,
account-wide CAS and the original SDK use point. JSON copies cannot send.
"""
import json
import hashlib
import types
from decimal import Decimal, localcontext
from pathlib import Path
from time import monotonic_ns as _monotonic_ns

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountRiskStore import account_key, _sha
from .ExecutionFacts import _MONEY, _market, _number, _string
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


def _source_runtime(engine):
    """Reuse original runtime/SDK checks, with the actual frozen read role."""
    role = getattr(engine, "_management_only_policy", None)
    if role is None or engine.mode != role.mode or engine.dry_run is not role.dry_run:
        _fail()
    from . import NativePreparation as Prepare
    from . import NativePreparedClient as Client
    from . import NativeInstrumentCurrent as Instrument
    from . import NativeCurrentComponents as Current
    from . import NativeAdmission as Admission
    from . import AccountSources as Account
    from . import NativePendingOrders as Pending
    from . import NativeMarketEvidence as Market
    from . import AccountRiskStore as Risk
    from . import AccountReconcile as Reconcile
    from . import NativeAccountCheck as Check
    from . import ExecutionFacts as Facts
    if any(globals()[name] is not getattr(module, name) for module, names in
            ((Facts, ("_market", "_number", "_string")), (Risk, ("account_key", "_sha"))) for name in names):
        _fail()
    modules = {}
    selected = [(Prepare, "_selected_runtime"), (Prepare, "_client_binding"), (Client, "initialize_native_order_recovery_client"),
        (Instrument, "collect_native_instruments_for_engine"), (Current, "read_native_component_policy"),
        (Admission, "_assert_current_windows"), (Account, "collect_account_snapshot"),
        (Account, "verify_account_snapshot"), (Pending, "collect_native_pending_orders"),
        (Pending, "verify_native_pending_orders"), (Market, "collect_native_market_evidence"),
        (Market, "verify_native_market_evidence")]
    selected.extend((module, name) for module, names in (
        (Risk, ("_ledger", "_trade_tables", "_client_roots", "account_key", "_sha")),
        (Reconcile, ("_native_positions", "_key", "_number")),
        (Check, ("_journal_prefix", "_verify_complete_histories")),
        (Ownership, ("_build", "_match", "_validate_contract", "_terminal_reference")),
        (Facts, ("_market", "_number", "_string")),
    ) for name in names)
    callables = {module.__name__+":"+name: Prepare._function_identity(module.__name__, name,
        getattr(module, name), modules) for module, name in selected}
    for owner, module, cls, names in (
        (engine, "Trade.TradeEngine", "CTradeEngine", ("_query_persisted_order",)),
        (engine.chan_db, "Trade.db_util", "CChanDB", ("get_record", "get_order_history")),
    ):
        for name in names:
            method = getattr(owner, name)
            if type(method) is not types.MethodType or method.__self__ is not owner:
                _fail()
            callables[module+":"+cls+"."+name] = Prepare._function_identity(module, cls+"."+name, method.__func__, modules)
    for name in ("read_native_management_order_identity", "_source_runtime", "collect_native_management_sources", "observe_native_management_quantity"):
        callables[__name__+":"+name] = Prepare._function_identity(__name__, name, globals()[name], modules)
    return {"engine": Prepare._selected_runtime(engine, None, engine._management_only_policy), "sources": callables}


def collect_native_management_sources(engine, record_id, *, phase, policy,
        instrument_max_age_ms, instrument_max_observation_span_ms, order_max_age_ms, order_max_observation_span_ms):
    """Own current GETs, not quantity capability, CAS, release or permission.

    Query may persist its original ACK/terminal observation, never apply fills.
    A new cumulative fill needs the original report consumer before management.
    No caller source, clock, cache refresh or generic PASS is accepted.
    """
    from .CCXTTradeEngine import CCCXTTradeEngine
    from . import NativePreparation as Prepare
    from . import NativePreparedClient as Client
    from . import NativeInstrumentCurrent as Instrument
    from . import NativeCurrentComponents as Current
    from . import NativeAdmission as Admission
    from . import AccountSources as Account
    from . import NativePendingOrders as Pending
    from . import NativeMarketEvidence as Market
    try:
        if (type(engine) is not CCCXTTradeEngine or engine.dry_run is not False or engine.market_type != "swap"
                or engine.mode not in {"live", "testnet"}):
            _fail()
        provided = {"policy": policy, "instrument_max_age_ms": instrument_max_age_ms,
            "instrument_max_observation_span_ms": instrument_max_observation_span_ms,
            "order_max_age_ms": order_max_age_ms, "order_max_observation_span_ms": order_max_observation_span_ms}
        original = canonical_bytes(provided)
        values = json.loads(original)
        for name, value in values.items():
            if name != "policy" and (type(value) is not int or not 0 <= value < 2**63):
                _fail()
        values["policy"] = Current.read_native_component_policy(values["policy"])
        runtime = _source_runtime(engine)
        chan, mode, role = engine.chan_db, engine.mode, engine._management_only_policy
        database = Boundary._database(chan)
        connection, table = database.conn, chan.table
        Boundary._same_database(chan, database, connection, table, owned=False)
        config = canonical_bytes(engine.ccxt_conf)
        started, elapsed_start = utc_now_ms(), _monotonic_ns()
        local = read_native_management_order_identity(chan, record_id, phase=phase)
        with database.transaction():
            Boundary._same_database(chan, database, connection, table, owned=True)
            record = chan.get_record(record_id)
            Boundary._same_database(chan, database, connection, table, owned=True)
            transition = Transition._read(chan, record)
            Boundary._same_database(chan, database, connection, table, owned=True)
            codes = transition["payload"]["root"]["preparation"]["identity"]["payload"]["scope"]["code_list"]
        if engine.exchange is None:
            Client.initialize_native_order_recovery_client(engine, record_id)
        exchange = engine.exchange
        from requests import Session
        session = exchange.session
        if type(session) is not Session or type(session.request) not in {types.FunctionType, types.MethodType}:
            _fail()
        request = session.request
        binding = Prepare._client_binding(exchange)
        location = canonical_bytes(database.query("PRAGMA database_list"))
        implementation = {**Prepare._implementation(), __name__: hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

        def owners(*, identity=True):
            Boundary._same_database(chan, database, connection, table, owned=False)
            if (engine.chan_db is not chan or engine.exchange is not exchange or engine.mode != mode
                    or engine.dry_run is not False or engine.market_type != "swap"
                    or engine._management_only_policy is not role or engine.safety_policy is not role
                    or exchange.session is not session or session.request != request
                    or canonical_bytes(engine.ccxt_conf) != config or canonical_bytes(provided) != original
                    or canonical_bytes(database.query("PRAGMA database_list")) != location
                    or Prepare._client_binding(exchange) != binding or _source_runtime(engine) != runtime
                    or {**Prepare._implementation(), __name__: hashlib.sha256(Path(__file__).read_bytes()).hexdigest()} != implementation):
                _fail()
            # Same original Entry verifier, not a second source/SDK verifier.
            Prepare._assert_execution_sdk(exchange, mode, source_entries=("fapiPrivateV3GetBalance", "fapiPrivateV3GetAccount",
                "fapiPrivateV3GetPositionRisk", "fapiPrivateGetSymbolConfig", "fapiPrivateGetMultiAssetsMargin",
                "fapiPrivateGetOpenAlgoOrders", "fapiPublicGetPremiumIndex", "fapiPublicGetTickerBookTicker", "fapiPublicGetExchangeInfo"))
            from . import NativePreparedIntent as Prepared
            Prepared._assert_native_adapter_retry_policy(exchange)
            if identity and read_native_management_order_identity(chan, record_id, phase=phase) != local:
                _fail()

        owners()
        instrument_elapsed_start = _monotonic_ns()
        instruments = Instrument.collect_native_instruments_for_engine(engine, codes, max_age_ms=instrument_max_age_ms,
            max_observation_span_ms=instrument_max_observation_span_ms)
        instrument_elapsed_end = _monotonic_ns()
        owners()
        query_start = utc_now_ms()
        query_elapsed_start = _monotonic_ns()
        result = engine._query_persisted_order(record, phase)
        owners(identity=False)  # Only the original query may append its ACK/terminal source.
        query_end = utc_now_ms()
        query_elapsed_end = _monotonic_ns()
        current = read_native_management_order_identity(chan, record_id, phase=phase)
        fresh = chan.get_record(record_id)
        owners(identity=False)
        expected = dict(record)
        prefix = "open" if phase == "open" else "cover"
        if record[prefix+"_order_id"] is None:
            expected.update({key: fresh[key] for key in (prefix+"_order_id", "order_last_update")})
        if (current["payload"]["identity"] != local["payload"]["identity"]
                or current["payload"]["local_remaining_quantity"] != local["payload"]["local_remaining_quantity"]
                or canonical_bytes(fresh) != canonical_bytes(expected)):
            _fail()
        local = current
        record = fresh
        owners()
        history = chan.get_order_history(record_id)
        owners()
        attempt = next(a for a in history["attempts"] if a["identity"] == local["payload"]["identity"])
        if (_number(str(result.filled)) != _number(str(attempt["events"][-1]["state"]["filled_qty"]))
                or result.order_id != record[prefix+"_order_id"]):
            _fail()
        units = [engine._market_contract(code)[0] for code in codes]
        owners()
        account = Account.collect_account_snapshot(exchange, units, mode=mode)
        owners()
        pending = Pending.collect_native_pending_orders(exchange, units, mode=mode)
        owners()
        market = Market.collect_native_market_evidence(exchange, units, mode=mode)
        owners()
        context = local["payload"]["account_context"]
        if any(document["payload"]["account_context"] != context for document in (account, pending)):
            _fail()
        if read_native_management_order_identity(chan, record_id, phase=phase) != local:
            _fail()
        quantity = observe_native_management_quantity(chan, record_id, phase=phase, account_snapshot=account, pending_orders=pending)
        owners()
        payload = {"identity": local, "account_context": context, "instruments": instruments,
            "order": {name: getattr(result, name) for name in ("order_id", "client_order_id", "requested", "filled", "avg_price", "status")},
            "order_window": {"started_ms": query_start, "finished_ms": query_end}, "account": account,
            "pending": pending, "market": market, "quantity": quantity, "policy": values, "runtime": runtime, "implementation_sha256": implementation,
            "started_ms": started, "finished_ms": utc_now_ms(), "native_quantity_verified": False, "operation_authorized": False}
        document = json.loads(canonical_bytes({"schema": "chan-native-management-sources-v2", "payload": payload, "payload_sha256": _sha(payload)}))
        owners()
        finished, elapsed_end = utc_now_ms(), _monotonic_ns()
        instrument = instruments["payload"]
        elapsed_clocks = (elapsed_start, instrument_elapsed_start, instrument_elapsed_end,
            query_elapsed_start, query_elapsed_end, elapsed_end)
        if (any(type(value) is not int or value < 0 for value in elapsed_clocks)
                or tuple(sorted(elapsed_clocks)) != elapsed_clocks):
            _fail()
        if (not 0 <= started <= query_start <= query_end <= finished < 2**63
                or finished-query_start > order_max_age_ms or query_end-query_start > order_max_observation_span_ms
                or finished-instrument["started_ms"] > instrument_max_age_ms
                or instrument["finished_ms"]-instrument["started_ms"] > instrument_max_observation_span_ms
                or elapsed_end-instrument_elapsed_start > instrument_max_age_ms*1_000_000
                or instrument_elapsed_end-instrument_elapsed_start > instrument_max_observation_span_ms*1_000_000
                or elapsed_end-query_elapsed_start > order_max_age_ms*1_000_000
                or query_elapsed_end-query_elapsed_start > order_max_observation_span_ms*1_000_000
                or finished-started > values["policy"]["max_observation_span_ms"]["total"]
                or elapsed_end-elapsed_start > values["policy"]["max_observation_span_ms"]["total"]*1_000_000):
            _fail()
        Admission._assert_current_windows(values["policy"], started, finished, account=account["payload"],
            market=market["payload"], wallets=[], executions=[], additional=[("open_orders", pending["payload"])])
        return document
    except Exception:
        _fail()


def observe_native_management_quantity(chan, record_id, *, phase, account_snapshot, pending_orders):
    """Associate exact original quantities; caller JSON never authorizes close.

    Pure DB/read-only observation, with no freshness or atomic-absence claim.
    The eventual consumer must own its sources and recheck them in its CAS.
    """
    from .AccountSources import verify_account_snapshot
    from .NativePendingOrders import verify_native_pending_orders
    from .AccountRiskStore import _ledger, _client_roots
    from .AccountReconcile import _native_positions
    from .NativeAccountCheck import _journal_prefix, _verify_complete_histories
    try:
        original = canonical_bytes({"account": account_snapshot, "pending": pending_orders})
        values = json.loads(original)
        account, pending = values["account"], values["pending"]
        verify_account_snapshot(account)
        verify_native_pending_orders(pending)
        database = Boundary._database(chan)
        connection, table, owned = database.conn, chan.table, database.conn.in_transaction
        Boundary._same_database(chan, database, connection, table, owned=owned)
        with database.transaction(), localcontext(_MONEY):
            Boundary._same_database(chan, database, connection, table, owned=True)
            local = read_native_management_order_identity(chan, record_id, phase=phase)
            Boundary._same_database(chan, database, connection, table, owned=True)
            context = local["payload"]["account_context"]
            if any(document["payload"]["account_context"] != context for document in (account, pending)):
                _fail()
            account_units = {row["symbol"]: _market(row) for row in account["payload"]["markets"]}
            pending_units = {row["symbol"]: _market(row) for row in pending["payload"]["markets"]}
            if (account_units != pending_units or len(account_units) != len(account["payload"]["markets"])
                    or len(pending_units) != len(pending["payload"]["markets"])):
                _fail()
            ledger = _ledger(chan)
            Boundary._same_database(chan, database, connection, table, owned=True)
            prefix = _journal_prefix(database)
            _verify_complete_histories(database, ledger["histories"], prefix)
            if prefix["attempt_count"] != database.query_one(f"SELECT count(*) AS n FROM {Audit.ATTEMPTS}")["n"]:
                _fail()
            Boundary._same_database(chan, database, connection, table, owned=True)
            roots = _client_roots(chan, ledger["histories"])
            Boundary._same_database(chan, database, connection, table, owned=True)
            ownership = Ownership._build(pending["payload"], ledger, client_roots=roots)
            if ownership["issues"]:
                _fail()

            def issue(*args, **kwargs):
                _fail()

            native = _native_positions(account["payload"], issue, "management")
            histories = {(row["attempts"][0]["identity"]["trade_table"], row["attempts"][0]["identity"]["record_id"]): row
                for row in ledger["histories"]}
            records, leg_totals, record_map = [], {}, {}
            for projection in ledger["projections"]:
                ref = (projection["trade_table"], projection["record_id"])
                history = histories[ref]
                attempts = history["attempts"]
                if history["gaps"] or not attempts:
                    _fail()
                opening = [a for a in attempts if a["identity"]["phase"] == "open"]
                if len(opening) != 1:
                    _fail()
                identity = opening[0]["identity"]
                contract = identity["order_contract"]
                if account_key(contract["account_context"]) != account_key(context):
                    continue  # Original ownership reader verified this other account.
                leg = (identity["instrument"], identity["position_side"], contract["execution"]["margin_mode"])
                totals = {"open": Decimal(0), "close": Decimal(0)}
                blockers = []
                for attempt in attempts:
                    current, state = attempt["identity"], attempt["events"][-1]["state"]
                    current_contract = current["order_contract"]
                    if (current_contract["account_context"] != context or current["instrument"] != leg[0]
                            or current["position_side"] != leg[1] or current_contract["execution"]["margin_mode"] != leg[2]
                            or bool(current["is_buy"]) != bool(identity["is_buy"])
                            or _market(current_contract["market"]) != account_units.get(current["instrument"])):
                        _fail()
                    quantity = _number(str(state["filled_qty"]))
                    if not 0 <= quantity <= _number(current_contract["quantity"], positive=True):
                        _fail()
                    observed_fill = Decimal(0)
                    for event in attempt["events"]:
                        cumulative = _number(str(event["state"]["filled_qty"]))
                        if cumulative != observed_fill and event["observed_ms"] > account["payload"]["finished_ms"]:
                            _fail()  # A later local fill cannot be assigned to an earlier endpoint.
                        observed_fill = cumulative
                    totals[current["phase"]] += quantity
                    if state["order_status"] not in {"closed", "canceled", "rejected"}:
                        blockers.append(current["phase"]+"_order_not_terminal")
                remaining = totals["open"]-totals["close"]
                if (remaining < 0 or remaining != _number(str(projection["current_qty"]))
                        or projection["instrument"] != leg[0] or projection["position_side"] != leg[1]
                        or bool(projection["is_buy"]) != bool(identity["is_buy"])):
                    _fail()
                entry = {"trade_table": ref[0], "record_id": ref[1], "leg": list(leg),
                    "direction": "long" if identity["is_buy"] else "short", "remaining_base_quantity": _string(remaining),
                    "reserved_close_base_quantity": "0", "new_close_blockers": sorted(set(blockers))}
                if ref in record_map:
                    _fail()
                record_map[ref] = entry
                records.append(entry)
                total = leg_totals.setdefault(leg, {"quantity": Decimal(0), "directions": set(), "reserved": Decimal(0)})
                total["quantity"] += remaining
                if remaining:
                    total["directions"].add(entry["direction"])
            for reservation in ownership["reservations"]:
                ref = (reservation["attempt"]["trade_table"], reservation["attempt"]["record_id"])
                if reservation["attempt"]["phase"] != "close":
                    continue
                entry = record_map[ref]
                remaining = _number(reservation["remaining_base_quantity"])
                entry["reserved_close_base_quantity"] = _string(_number(entry["reserved_close_base_quantity"])+remaining)
                leg_totals[tuple(entry["leg"])]["reserved"] += remaining
            legs = []
            for leg in sorted(set(leg_totals) | set(native)):
                total = leg_totals.get(leg, {"quantity": Decimal(0), "directions": set(), "reserved": Decimal(0)})
                position = native.get(leg)
                quantity = Decimal(0) if position is None else _number(position["quantity"])
                if (quantity != total["quantity"] or total["reserved"] > quantity or len(total["directions"]) > 1
                        or (quantity and (position is None or total["directions"] != {position["direction"]}))):
                    _fail()
                legs.append({"leg": list(leg), "quantity": _string(quantity), "reserved_close_quantity": _string(total["reserved"])})
            for entry in records:
                if _number(entry["reserved_close_base_quantity"]) > _number(entry["remaining_base_quantity"]):
                    _fail()
            selected = record_map[(table, record_id)]
            leg = tuple(selected["leg"])
            record_remaining = _number(selected["remaining_base_quantity"])
            reserved = _number(selected["reserved_close_base_quantity"])
            leg_quantity, leg_reserved = leg_totals[leg]["quantity"], leg_totals[leg]["reserved"]
            available = min(record_remaining-reserved, leg_quantity-leg_reserved)
            if selected["new_close_blockers"]:
                available = Decimal(0)
            payload = {"identity": local, "account_context": context, "source_account_sha256": _sha(account),
                "source_pending_sha256": _sha(pending), "ledger_sha256": _sha(ledger), "journal_prefix": prefix,
                "pending_ownership": {"payload": ownership, "payload_sha256": _sha(ownership)},
                "local_remaining_quantity": _string(record_remaining), "native_leg_quantity": _string(leg_quantity),
                "reserved_record_close_quantity": _string(reserved), "reserved_leg_close_quantity": _string(leg_reserved),
                "observed_available_base_quantity": _string(available), "new_close_blockers": selected["new_close_blockers"],
                "records": records, "legs": legs, "native_quantity_verified": False, "operation_authorized": False}
            result = json.loads(canonical_bytes({"schema": "chan-native-management-quantity-v1", "payload": payload, "payload_sha256": _sha(payload)}))
            Boundary._same_database(chan, database, connection, table, owned=True)
            if _ledger(chan) != ledger or read_native_management_order_identity(chan, record_id, phase=phase) != local:
                _fail()
            Boundary._same_database(chan, database, connection, table, owned=True)
        Boundary._same_database(chan, database, connection, table, owned=owned)
        if canonical_bytes({"account": account_snapshot, "pending": pending_orders}) != original:
            _fail()
        return result
    except Exception:
        _fail()
