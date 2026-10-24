"""Own one prepare/source call and bind an original, non-executable intent.

No funding formula, HTTP send, new order table or claim permission. Persisted
bindings describe historical facts, not server signatures or capabilities.
"""
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from time import monotonic_ns as _monotonic_ns

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from . import NativePreparation as Prepare
from . import NativeOrderBoundary as Boundary
from . import NativeAccountLimits as AccountLimits
from . import NativeCapacityEvidence as Capacity
from .AccountRiskStore import _sha, read_check, risk_state
from .AccountStore import read_evidence
from .AccountSources import SNAPSHOT_SCHEMA
from .NativeComponentCollector import collect_and_check_native_components
from .NativeCurrentComponents import _sources_snapshot, read_native_component_policy
from .NativeInstrumentCurrent import collect_native_instruments_for_engine
from .NativeInstrumentEvidence import verify_native_instrument_evidence


LEGACY_BINDING_SCHEMA = "chan-native-prepared-intent-binding-v1"
BINDING_SCHEMA = "chan-native-prepared-intent-binding-v2"
CAPACITY_BINDING_SCHEMA = "chan-native-prepared-intent-binding-v3"
CURRENT_BINDING_SCHEMAS = {BINDING_SCHEMA, CAPACITY_BINDING_SCHEMA}
_IDENTITY_FIELDS = {"record_sha256", "config_sha256", "engine_config_sha256", "engine_execution_sha256", "environment_sha256",
    "database_location_sha256", "trade_table", "candidate", "opening_inputs", "scope", "runtime", "request", "quantity", "price",
    "order_contract", "entry_assessment_sha256", "implementation_sha256", "started_ms", "finished_ms", "coverage", "economics_complete", "native_admission_verified"}
_COMPONENT_FIELDS = {"coverage", "economics_complete", "native_admission_verified", "account_context", "source_ids", "check_id",
    "market_evidence", "policy", "operations", "observed_sdk_calls", "sdk_call_upper_bound", "implementation_sha256", "database_location_sha256", "started_ms", "finished_ms"}
_ROOT = Path(__file__).resolve().parents[1]
_FILES = ("Trade/NativePreparedIntent.py", "Trade/NativeInstrumentCurrent.py", "Trade/NativeInstrumentEvidence.py",
          "Trade/NativePreparedClient.py", "DataAPI/ccxt.py", "Trade/NativeCapacityEvidence.py", "Trade/NativeAccountLimits.py",
          "Trade/NativeLeverageLimits.py", "Trade/NativeMarginEnvelope.py")


def _fail():
    raise CChanException("同次原生准备/自采与原 CAS 引用不一致；资金/claim/发送仍未授权", ErrCode.TRADE_UNLOCK_FAIL) from None


def _implementation():
    return {**Prepare._implementation(), **Boundary._component_implementation(),
            **{name: hashlib.sha256((_ROOT/name).read_bytes()).hexdigest() for name in _FILES}}


def _budget(value):
    if type(value) is not int or not 0 <= value < 2**63:
        _fail()
    return value


def _snapshot(binding):
    p = binding["identity"]["payload"]
    return {"price": p["request"]["price"], "opening_inputs": p["opening_inputs"], "entry": binding["entry_assessment"]}


def _contract(binding):
    from .NativeOrderTransition import CONTRACT_SCHEMA
    contract = {**binding["identity"]["payload"]["order_contract"], "schema": CONTRACT_SCHEMA}
    contract["contract_id"] = _sha({k: v for k, v in contract.items() if k != "contract_id"})
    return contract


def _live(chan, context):
    if type(context) is not Prepare._NativePrepareContext or context not in Prepare._PREPARED:
        _fail()
    entry = Prepare._PREPARED[context]
    if len(entry) != 4 or entry[0].chan_db is not chan:
        _fail()
    binding = json.loads(entry[3])
    if binding["schema"] in CURRENT_BINDING_SCHEMAS and Prepare._client_binding(entry[0].exchange) != binding["client_binding_sha256"]:
        _fail()
    return entry[0], binding, entry[2]


def _capacity_links(chan, binding, boundary, checked, snapshot=None):
    source, policy = binding["capacity_evidence"], binding["capacity_policy"]
    if type(policy) is not dict or set(policy) != {"max_age_ms", "max_observation_span_ms"}:
        _fail()
    for value in policy.values():
        _budget(value)
    if snapshot is None:
        Capacity._verify_binance_capacity_evidence_at(source, checked_ms=checked, **policy)
    else:
        Capacity.verify_binance_capacity_evidence(source, **policy)
    c = binding["components"]["payload"]
    if canonical_bytes(source["payload"]["account_context"]) != canonical_bytes(c["account_context"]):
        _fail()
    if snapshot is None:
        from .ExecutionStore import read_scan_with_account
        check = read_check(chan.db, c["check_id"])
        snapshot = {"check": check, "execution_observations": [read_scan_with_account(chan.db, key)[1]["observation"]
                                                                for key in c["source_ids"]["executions"]]}
    saved = snapshot["check"]["payload"]["inputs"]
    AccountLimits._bindings(source["payload"], c["market_evidence"]["payload"], saved)
    values = {"capacity_evidence": source, "market_evidence": c["market_evidence"], "policy": c["policy"], **policy}
    AccountLimits._windows(values, snapshot, binding["started_ms"], checked)
    return values


def _windows(chan, binding, boundary, *, final_check=None):
    if binding["implementation_sha256"] != _implementation():
        _fail()
    inputs = Boundary._inputs({key: boundary["payload"][key] for key in Boundary._INPUTS})
    sources = _sources_snapshot(chan, inputs["account_context"], inputs["check_id"], inputs["market_evidence"])
    with_capacity = binding["schema"] == CAPACITY_BINDING_SCHEMA
    tick_start = _monotonic_ns() if with_capacity else None
    now, instrument = utc_now_ms(), binding["instruments"]["payload"]
    if (type(now) is not int or not binding["finished_ms"] <= now < 2**63
            or now-instrument["started_ms"] > binding["instrument_policy"]["max_age_ms"]
            or instrument["finished_ms"]-instrument["started_ms"] > binding["instrument_policy"]["max_observation_span_ms"]):
        _fail()
    Boundary._windows(inputs, sources, binding["started_ms"], now)
    if with_capacity:
        values = _capacity_links(chan, binding, boundary, now, sources)
        if final_check is not None:
            final_check()
        tick_end = _monotonic_ns()
        if type(tick_start) is not int or type(tick_end) is not int or not 0 <= tick_start <= tick_end:
            _fail()
        AccountLimits._windows(values, sources, binding["started_ms"], now+(tick_end-tick_start+999_999)//1_000_000)


def validate_stored_preparation(chan, root, attempt):
    """Independent raw/check/immutable-attempt links, not current admission."""
    try:
        b = root["preparation"]
        if (type(b) is not dict or b["schema"] not in {LEGACY_BINDING_SCHEMA, *CURRENT_BINDING_SCHEMAS}
                or set(b) != {"schema", "identity", "instruments", "components", "instrument_policy", "boundary_sha256",
                    "baseline_records_sha256", "baseline_prefix", "entry_assessment", "started_ms", "finished_ms", "implementation_sha256"}
                    | ({"client_binding_sha256"} if b["schema"] in CURRENT_BINDING_SCHEMAS else set())
                    | ({"capacity_evidence", "capacity_policy"} if b["schema"] == CAPACITY_BINDING_SCHEMA else set())
                or b["boundary_sha256"] != _sha(root["boundary"])):
            _fail()
        if b["schema"] in CURRENT_BINDING_SCHEMAS and (type(b["client_binding_sha256"]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", b["client_binding_sha256"]) is None):
            _fail()
        identity, components, boundary = b["identity"], b["components"], root["boundary"]["payload"]
        p, c, a = identity["payload"], components["payload"], attempt["identity"]
        request = p["request"]
        if (set(identity) != {"schema", "payload", "payload_sha256"} or set(p) != _IDENTITY_FIELDS
                or set(request) != {"record_id", "amount", "price", "post_only"}
                or type(request["record_id"]) is not int or request["record_id"] <= 0
                or type(request["amount"]) not in (int, float) or request["amount"] <= 0
                or type(request["post_only"]) is not bool or request["post_only"] is not p["order_contract"]["post_only"]
                or (request["price"] is not None and (type(request["price"]) not in (int, float) or request["price"] <= 0))
                or type(p["quantity"]) is not float or p["quantity"] <= 0
                or ((p["price"] is None) != (p["order_contract"]["price"] is None))
                or (p["price"] is not None and (type(p["price"]) is not float
                    or Decimal(str(p["price"])) != Decimal(p["order_contract"]["price"])))
                or p["opening_inputs"]["scope_sha256"] != _sha(p["scope"])
                or identity["schema"] != Prepare.SCHEMA or identity["payload_sha256"] != _sha(p)
                or p["coverage"] != "actual_local_prepare_identity_only"
                or p["economics_complete"] is not False or p["native_admission_verified"] is not False
                or set(components) != {"schema", "payload", "payload_sha256"} or set(c) != _COMPONENT_FIELDS
                or components["schema"] != "chan-native-collected-components-v1" or components["payload_sha256"] != _sha(c)
                or c["economics_complete"] is not False or c["native_admission_verified"] is not False
                or c["coverage"] != "local_collector_owned_observations"
                or p["record_sha256"] != root["before_record_sha256"] or p["trade_table"] != a["trade_table"]
                or p["request"]["record_id"] != a["record_id"] or p["quantity"] != a["requested_qty"]
                or canonical_bytes(a["order_contract"]) != canonical_bytes(_contract(b))
                or a.get("opening_inputs") != p["opening_inputs"]
                or a["strategy_version"] != p["scope"]["strategy"]
                or c["check_id"] != boundary["check_id"] or c["account_context"] != boundary["account_context"]
                or canonical_bytes(c["market_evidence"]) != canonical_bytes(boundary["market_evidence"])
                or canonical_bytes(read_native_component_policy(c["policy"])) != canonical_bytes(boundary["policy"])
                or b["baseline_prefix"] != boundary["journal_prefix"]
                or c["database_location_sha256"] != boundary["database_location_sha256"]
                or p["database_location_sha256"] != boundary["database_location_sha256"]
                or (None if b["entry_assessment"] is None else _sha(b["entry_assessment"])) != p["entry_assessment_sha256"]):
            _fail()
        if type(b["instrument_policy"]) is not dict or set(b["instrument_policy"]) != {"max_age_ms", "max_observation_span_ms"}:
            _fail()
        for value in b["instrument_policy"].values():
            _budget(value)
        verify_native_instrument_evidence(b["instruments"])
        instrument = b["instruments"]["payload"]
        operations = ["pending", "balance", "after", *["execution:"+code for code in instrument["codes"]], "wallet", "market", "current"]
        if (sorted(p["scope"]["code_list"]) != instrument["codes"] or instrument["mode"] != p["order_contract"]["account_context"]["mode"]
                or c["operations"] != operations
                or any(type(c[key]) is not int for key in ("observed_sdk_calls", "sdk_call_upper_bound"))
                or not 0 < c["observed_sdk_calls"] <= c["sdk_call_upper_bound"]
                or any(b["implementation_sha256"].get(key) != value for key, value in c["implementation_sha256"].items())
                or canonical_bytes([row["market"] for row in instrument["observations"]]) !=
                    canonical_bytes([row["market"] for row in c["market_evidence"]["payload"]["observations"]])
                or any(row["active"] is not True for row in instrument["observations"])):
            _fail()
        check = read_check(chan.db, c["check_id"])
        if check["payload"]["source_ids"] != c["source_ids"] or check["payload"]["inputs"] is None:
            _fail()
        cap_clocks = []
        if b["schema"] == CAPACITY_BINDING_SCHEMA:
            _capacity_links(chan, b, root["boundary"], a["intent_ms"])
            cap_clocks = [b["capacity_evidence"]["payload"][key] for key in ("started_ms", "finished_ms")]
        clocks = [b["started_ms"], p["started_ms"], p["finished_ms"], instrument["started_ms"], instrument["finished_ms"], *cap_clocks,
                  c["started_ms"], c["finished_ms"], boundary["captured_ms"], b["finished_ms"], a["intent_ms"]]
        if any(type(t) is not int or not 0 <= t < 2**63 for t in clocks) or clocks != sorted(clocks):
            _fail()
    except Exception:
        _fail()


def consume_prepared_context(chan, before, updates, boundary, context):
    """Called only by the original owned writer, before its actual CAS SQL."""
    from .NativeOrderTransition import _records, _prefix
    engine, binding, _ = _live(chan, context)
    Prepare.assert_native_prepare_context_current(engine, context)
    p = binding["identity"]["payload"]
    if (binding["boundary_sha256"] != _sha(boundary) or p["record_sha256"] != _sha(before)
            or binding["baseline_records_sha256"] != _sha(_records(chan)) or binding["baseline_prefix"] != _prefix(chan.db)
            or updates["open_requested_qty"] != p["quantity"]
            or updates["open_order_contract"] != canonical_bytes(_contract(binding)).decode()
            or json.loads(updates["snapshot_before"]) != _snapshot(binding)
            or updates["strategy_version"] != p["scope"]["strategy"] or updates["risk_multiplier"] != 1.0
            or updates["model_score_before"] != (None if binding["entry_assessment"] is None else binding["entry_assessment"]["score"])):
        _fail()
    def final_check():
        Prepare.assert_native_prepare_context_current(engine, context)
        _live(chan, context)
    _windows(chan, binding, boundary, final_check=final_check)
    return binding


def finish_prepared_context(chan, context, expected, document):
    """Exact after-row is supplied by the original writer, never by a caller."""
    engine, binding, check = _live(chan, context)
    root = document["payload"]["root"]
    if canonical_bytes(binding) != canonical_bytes(root["preparation"]):
        _fail()
    check(expected_record=expected)
    from .NativeOrderTransition import _current
    _current(chan, document)  # Local callbacks must not escape full-ledger validation.
    def final_check():
        check(expected_record=expected)
        _current(chan, document)
        _live(chan, context)
    _windows(chan, binding, root["boundary"], final_check=final_check)


def assert_native_prepared_intent_current(engine, record_id):
    """Reconstitute local currentness from original persisted facts, not JSON.

    Requires the original owned SQLite view. No prepare, GET, new observation,
    claim or allocation; returning None cannot release the funding/send gate.
    """
    try:
        from . import NativeOrderTransition as Transition
        from . import NativeInstrumentCurrent as Instrument
        from .AccountIdentity import _environment
        from .CCXTTradeEngine import CCCXTTradeEngine
        from .Script.OpeningInputs import COpeningInputs
        from .SafetyPolicy import TradingSafetyPolicy
        if (type(engine) is not CCCXTTradeEngine or type(record_id) is not int or record_id <= 0
                or type(engine.opening_inputs) is not COpeningInputs or type(engine.safety_policy) is not TradingSafetyPolicy
                or engine.exchange is None):
            _fail()
        chan, exchange, guard, policy = engine.chan_db, engine.exchange, engine.opening_inputs, engine.safety_policy
        database = Transition._owned(chan)
        connection, table, clock = database.conn, chan.table, guard.now_ms

        def owners():
            Boundary._same_database(chan, database, connection, table, owned=True)
            if (engine.chan_db is not chan or engine.exchange is not exchange or engine.opening_inputs is not guard
                    or engine.safety_policy is not policy or guard.now_ms is not clock):
                _fail()

        document = Transition._read(chan, chan.get_record(record_id))
        if document["schema"] != Transition.PREPARED_DOCUMENT_SCHEMA or document["payload"]["stage"] != "intent":
            _fail()
        root, after_sha = document["payload"]["root"], document["payload"]["after_record_sha256"]
        binding = root["preparation"]
        p, instrument = binding["identity"]["payload"], binding["instruments"]["payload"]
        if (binding["schema"] not in CURRENT_BINDING_SCHEMAS or binding["implementation_sha256"] != _implementation() or p["implementation_sha256"] != Prepare._implementation()
                or exchange.id != instrument["exchange_id"]):
            _fail()
        owners()
        Transition._current(chan, document)
        reference, ccxt = Instrument.source._reference(exchange.id, engine.mode)
        original_client = Prepare._client_binding(exchange)
        if original_client != binding["client_binding_sha256"]:
            _fail()
        previous, cache_before = p["finished_ms"], None
        def check_local():
            nonlocal previous, cache_before
            owners()
            runtime = Prepare._selected_runtime(engine, guard, policy)
            owners()
            observed, actual = Prepare._local_prepare_view(engine, guard, policy, chan, database, table,
                record_id, p["request"]["price"], runtime, owners, persisted_record_sha256=after_sha)
            # Only the independently verified original event supplies this hash.
            # Every current column is checked, not excluded as an "own" delta.
            expected = {key: p[key] for key in observed}
            expected["record_sha256"] = after_sha
            checked = observed["opening_inputs"]["checked_at_ms"]
            if (canonical_bytes(Prepare._stable_local_view(observed)) != canonical_bytes(Prepare._stable_local_view(expected))
                    or type(checked) is not int or not previous <= checked < 2**63):
                _fail()
            previous = checked
            if actual.get("deployment_id") or actual.get("model_version"):
                from .Script.Deployment import verify_entry_assessment
                if canonical_bytes(verify_entry_assessment(actual, binding["entry_assessment"], p["request"]["price"], engine)) != canonical_bytes(binding["entry_assessment"]):
                    _fail()
            elif binding["entry_assessment"] is not None:
                _fail()
            owners()
            cache, observations = Instrument._cache_view(engine, instrument["codes"], reference, ccxt, instrument["venue"], engine.mode)
            decoded = json.loads(cache)
            if (decoded["environment"] != instrument["environment"] or decoded["sdk"] != instrument["sdk"]
                    or canonical_bytes(observations) != canonical_bytes([{key: row[key] for key in ("market", "active", "native_state")}
                                                                         for row in instrument["observations"]])
                    or canonical_bytes(_environment(exchange, reference, instrument["venue"], engine.mode)) != canonical_bytes(p["order_contract"]["account_context"]["environment"])
                    or (cache_before is not None and cache != cache_before)):
                _fail()
            owners()
            if Prepare._client_binding(exchange) != original_client:
                _fail()
            cache_before = cache
        for step in range(2):
            check_local()
            if step == 0:
                chan.assert_account_new_risk_allowed(p["order_contract"]["account_context"])
        owners()
        Transition._current(chan, document)
        def final_check():
            owners()
            Transition._current(chan, document)
            check_local()
            owners()
        _windows(chan, binding, root["boundary"], final_check=final_check)
        owners()
    except Exception:
        _fail()


def acquire_native_prepared_diagnostic_intent(engine, record_id, amount, price, *, before_id, account_scope, policy,
        instrument_max_age_ms, instrument_max_observation_span_ms, client_order_id, post_only=False, entry_assessment=None):
    """Own every collection and original intent; never claim or send an order."""
    return _acquire_prepared_diagnostic_intent(engine, record_id, amount, price, before_id=before_id,
        account_scope=account_scope, policy=policy, instrument_max_age_ms=instrument_max_age_ms,
        instrument_max_observation_span_ms=instrument_max_observation_span_ms, client_order_id=client_order_id,
        post_only=post_only, entry_assessment=entry_assessment, capacity_policy=None)


def acquire_binance_capacity_prepared_diagnostic_intent(engine, record_id, amount, price, *, before_id, account_scope, policy,
        instrument_max_age_ms, instrument_max_observation_span_ms, capacity_max_age_ms, capacity_max_observation_span_ms,
        client_order_id, post_only=False, entry_assessment=None):
    """Explicit raw-capacity v3 diagnostic; no guessed price or funding decision."""
    return _acquire_prepared_diagnostic_intent(engine, record_id, amount, price, before_id=before_id,
        account_scope=account_scope, policy=policy, instrument_max_age_ms=instrument_max_age_ms,
        instrument_max_observation_span_ms=instrument_max_observation_span_ms, client_order_id=client_order_id,
        post_only=post_only, entry_assessment=entry_assessment,
        capacity_policy={"max_age_ms": capacity_max_age_ms, "max_observation_span_ms": capacity_max_observation_span_ms})


def _acquire_prepared_diagnostic_intent(engine, record_id, amount, price, *, before_id, account_scope, policy,
        instrument_max_age_ms, instrument_max_observation_span_ms, client_order_id, post_only, entry_assessment, capacity_policy):
    chan, database, connection, table, account, components = None, None, None, None, None, None
    source_started = False
    try:
        from .NativeOrderTransition import _records, _prefix
        _budget(instrument_max_age_ms)
        _budget(instrument_max_observation_span_ms)
        if capacity_policy is not None:
            for value in capacity_policy.values():
                _budget(value)
            if engine.ccxt_conf.get("exchange") not in {"binance", "binanceusdm"}:
                _fail()
        policy_value = read_native_component_policy(policy)
        venue_pattern = r"[.A-Za-z0-9_:/-]{1,36}" if engine.ccxt_conf.get("exchange") in {"binance", "binanceusdm"} else r"[A-Za-z0-9]{1,32}"
        if (type(client_order_id) is not str or re.fullmatch(venue_pattern, client_order_id) is None
                or type(account_scope) is not str or re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", account_scope) is None):
            _fail()
        original = canonical_bytes({"before_id": before_id, "account_scope": account_scope, "policy": policy,
            "instrument_age": instrument_max_age_ms, "instrument_span": instrument_max_observation_span_ms, "client_order_id": client_order_id,
            "capacity_policy": capacity_policy})
        chan, client = engine.chan_db, engine.exchange
        database = Boundary._database(chan)
        connection, table = database.conn, chan.table
        Boundary._same_database(chan, database, connection, table, owned=False)
        implementation, started = _implementation(), utc_now_ms()
        if type(started) is not int or not 0 <= started < 2**63:
            _fail()
        with database.transaction():
            before = read_evidence(database, before_id)
            if (before["schema"] != SNAPSHOT_SCHEMA or before["payload"]["account_context"]["mode"] != engine.mode
                    or risk_state(database, before["payload"]["account_context"])["frozen"]):
                _fail()
            records, prefix = _sha(_records(chan)), _prefix(database)
        context = Prepare._capture_native_prepare_context(engine, record_id, amount, price, post_only=post_only, entry_assessment=entry_assessment)
        identity = json.loads(Prepare._PREPARED[context][1])
        client_binding = Prepare._client_binding(client)
        account = identity["payload"]["order_contract"]["account_context"]
        if account != before["payload"]["account_context"]:
            _fail()
        codes = identity["payload"]["scope"]["code_list"]
        source_started = True
        instruments = collect_native_instruments_for_engine(engine, codes, max_age_ms=instrument_max_age_ms,
                                                          max_observation_span_ms=instrument_max_observation_span_ms)
        units = [row["market"] for row in instruments["payload"]["observations"]]
        capacity = (None if capacity_policy is None else Capacity.collect_binance_capacity_evidence(client, units,
                                                                                                  mode=engine.mode, **capacity_policy))
        if capacity_policy is not None:
            Boundary._same_database(chan, database, connection, table, owned=False)
            if engine.chan_db is not chan or engine.exchange is not client or type(capacity) is not dict:
                _fail()
        components = collect_and_check_native_components(chan, client, mode=engine.mode, markets=units,
                            before_id=before_id, account_scope=account_scope, policy=policy_value)
        c = components["payload"]
        boundary = Boundary.capture_native_order_boundary(chan, account_context=account, check_id=c["check_id"],
                                              market_evidence=c["market_evidence"], policy=policy_value)
        binding = {"schema": BINDING_SCHEMA if capacity_policy is None else CAPACITY_BINDING_SCHEMA,
            "identity": identity, "instruments": instruments, "components": components,
            "client_binding_sha256": client_binding,
            "instrument_policy": {"max_age_ms": instrument_max_age_ms, "max_observation_span_ms": instrument_max_observation_span_ms},
            "boundary_sha256": _sha(boundary), "baseline_records_sha256": records, "baseline_prefix": prefix,
            "entry_assessment": entry_assessment, "started_ms": started, "finished_ms": utc_now_ms(), "implementation_sha256": implementation}
        if capacity_policy is not None:
            binding.update(capacity_evidence=capacity, capacity_policy=capacity_policy)
        if (engine.chan_db is not chan or engine.exchange is not client or original != canonical_bytes({"before_id": before_id,
                "account_scope": account_scope, "policy": policy, "instrument_age": instrument_max_age_ms,
                "instrument_span": instrument_max_observation_span_ms, "client_order_id": client_order_id,
                "capacity_policy": capacity_policy})):
            _fail()
        Boundary._same_database(chan, database, connection, table, owned=False)
        Prepare._PREPARED[context] = (*Prepare._PREPARED[context], canonical_bytes(binding))
        return chan.acquire_open_intent(record_id, requested_qty=identity["payload"]["quantity"], client_order_id=client_order_id,
            position_side=identity["payload"]["order_contract"]["execution"]["position_side"], strategy_version=identity["payload"]["scope"]["strategy"],
            score_before=None if entry_assessment is None else entry_assessment["score"], snapshot=_snapshot(binding),
            order_contract=_contract(binding), native_boundary=boundary, native_preparation=context)
    except Exception:
        if source_started and account is not None:
            try:
                Boundary._same_database(chan, database, connection, table, owned=False)
                with database.transaction():
                    if not risk_state(database, account)["frozen"]:
                        from .NativeAccountCheck import _publish_unavailable
                        request = ({"before": before_id, "after": "0"*64, "wallets": [], "executions": [], "pending": "0"*64, "balance": "0"*64}
                                   if components is None else components["payload"]["source_ids"])
                        _publish_unavailable(database, account, request)
            except Exception:
                _fail()
        _fail()
