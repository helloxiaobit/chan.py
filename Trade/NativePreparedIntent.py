"""Own one prepare/source call and bind its original conditional-money intent.

No new funding formula, HTTP send, order table or claim permission. Persisted
bindings describe historical facts, not server signatures or capabilities.
"""
import hashlib
import json
import re
import sys
import types
import weakref
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
from . import NativeLastPrice as Last
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
MONETARY_BINDING_SCHEMA = "chan-native-prepared-intent-binding-v4"
CURRENT_BINDING_SCHEMAS = {BINDING_SCHEMA, CAPACITY_BINDING_SCHEMA, MONETARY_BINDING_SCHEMA}
_IDENTITY_FIELDS = {"record_sha256", "config_sha256", "engine_config_sha256", "engine_execution_sha256", "environment_sha256",
    "database_location_sha256", "trade_table", "candidate", "opening_inputs", "scope", "runtime", "request", "quantity", "price",
    "order_contract", "entry_assessment_sha256", "implementation_sha256", "started_ms", "finished_ms", "coverage", "economics_complete", "native_admission_verified"}
_COMPONENT_FIELDS = {"coverage", "economics_complete", "native_admission_verified", "account_context", "source_ids", "check_id",
    "market_evidence", "policy", "operations", "observed_sdk_calls", "sdk_call_upper_bound", "implementation_sha256", "database_location_sha256", "started_ms", "finished_ms"}
_ROOT = Path(__file__).resolve().parents[1]
_FILES = ("Trade/NativePreparedIntent.py", "Trade/NativeInstrumentCurrent.py", "Trade/NativeInstrumentEvidence.py",
          "Trade/NativePreparedClient.py", "DataAPI/ccxt.py", "Trade/NativeCapacityEvidence.py", "Trade/NativeAccountLimits.py",
          "Trade/NativeLeverageLimits.py", "Trade/NativeMarginEnvelope.py")


class _NativeClaimContext:
    """Same Engine/owned view and actual L1, never a portable receipt."""
    __slots__ = ("__weakref__",)


_CLAIMS = weakref.WeakKeyDictionary()


def _fail():
    raise CChanException("同次原生准备/自采与原 CAS 引用不一致；资金/claim/发送仍未授权", ErrCode.TRADE_UNLOCK_FAIL) from None


def _implementation():
    return {**Prepare._implementation(), **Boundary._component_implementation(),
            **{name: hashlib.sha256((_ROOT/name).read_bytes()).hexdigest() for name in _FILES}}


def _binding_implementation(binding):
    if binding["schema"] != MONETARY_BINDING_SCHEMA:
        return _implementation()
    return {**_implementation(), **Last._implementation(),
            "Trade/NativeOrderCost.py": hashlib.sha256((_ROOT/"Trade/NativeOrderCost.py").read_bytes()).hexdigest()}


def _budget(value):
    if type(value) is not int or not 0 <= value < 2**63:
        _fail()
    return value


def collect_prepared_binance_last_prices(engine, context, *, max_age_ms, max_observation_span_ms):
    """Read Last inside the original, still-unconsumed prepare invocation.

    No new context, binding, prepare, intent or permission is produced. The
    returned Last document keeps its original false flags; later acquisition
    must itself own and consume this source in the original monetary CAS.
    """
    try:
        from . import NativeInstrumentCurrent as Instrument
        from .CCXTTradeEngine import CCCXTTradeEngine
        _budget(max_age_ms)
        _budget(max_observation_span_ms)
        if (type(engine) is not CCCXTTradeEngine or type(context) is not Prepare._NativePrepareContext
                or context not in Prepare._PREPARED):
            _fail()
        entry = Prepare._PREPARED[context]
        if len(entry) != 4 or entry[0] is not engine:
            _fail()
        chan, client, guard, policy = engine.chan_db, engine.exchange, engine.opening_inputs, engine.safety_policy
        original_clock = guard.now_ms
        database = Boundary._database(chan)
        connection, table = database.conn, chan.table
        Boundary._same_database(chan, database, connection, table, owned=False)
        identity = json.loads(entry[1])["payload"]
        codes, mode = identity["scope"]["code_list"], identity["order_contract"]["account_context"]["mode"]
        if client.id not in {"binance", "binanceusdm"} or mode != engine.mode:
            _fail()
        reference, ccxt = Instrument.source._reference(client.id, mode)
        implementation = {**_implementation(), **Last._implementation()}
        client_binding = Prepare._client_binding(client)

        def owners(*, owned=False):
            Boundary._same_database(chan, database, connection, table, owned=owned)
            if (engine.chan_db is not chan or engine.exchange is not client
                    or engine.opening_inputs is not guard or engine.safety_policy is not policy or guard.now_ms is not original_clock
                    or Prepare._PREPARED.get(context) is not entry or engine.mode != mode
                    or engine.dry_run is not False or engine.market_type != "swap"):
                _fail()

        def view():
            owners()
            if {**_implementation(), **Last._implementation()} != implementation:
                _fail()
            owners()
            cache, observed = Instrument._cache_view(engine, codes, reference, ccxt, "binance", mode)
            markets = Last._markets([row["market"] for row in observed], client.id)
            owners()
            with database.transaction():
                owners(owned=True)
                Prepare.assert_native_prepare_context_current(engine, context)
                owners(owned=True)
            owners()
            if Prepare._client_binding(client) != client_binding:
                _fail()
            owners()
            return cache, markets

        before, markets = view()
        document = Last.collect_binance_last_prices(client, markets, mode=mode, max_age_ms=max_age_ms,
                                                     max_observation_span_ms=max_observation_span_ms)
        owners()
        Last.verify_binance_last_prices(document, max_age_ms=max_age_ms, max_observation_span_ms=max_observation_span_ms)
        owners()
        encoded = canonical_bytes(document)
        p = document["payload"]
        if (p["mode"] != mode or p["exchange_id"] != client.id
                or canonical_bytes(p["markets"]) != canonical_bytes(markets)):
            _fail()
        tail_start, checked = _monotonic_ns(), utc_now_ms()
        Last._windows(p, checked, max_age_ms, max_observation_span_ms)
        after, _ = view()
        if before != after or canonical_bytes(document) != encoded:
            _fail()
        tail_end = _monotonic_ns()
        if type(tail_start) is not int or type(tail_end) is not int or not 0 <= tail_start <= tail_end:
            _fail()
        Last._windows(p, checked+(tail_end-tail_start+999_999)//1_000_000, max_age_ms, max_observation_span_ms)
        return document
    except Exception:
        _fail()


def _snapshot(binding):
    p = binding["identity"]["payload"]
    return {"price": p["request"]["price"], "opening_inputs": p["opening_inputs"], "entry": binding["entry_assessment"]}


def _contract(binding):
    from .NativeOrderTransition import CONTRACT_SCHEMA, CLIENT_CONTRACT_SCHEMA
    monetary = binding["schema"] == MONETARY_BINDING_SCHEMA
    contract = {**binding["identity"]["payload"]["order_contract"], "schema": CLIENT_CONTRACT_SCHEMA if monetary else CONTRACT_SCHEMA}
    if monetary:
        contract["monetary_basis_sha256"] = binding["monetary"]["payload_sha256"]
    contract["contract_id"] = _sha({k: v for k, v in contract.items() if k != "contract_id"})
    return contract


def _live(chan, context):
    if type(context) is not Prepare._NativePrepareContext or context not in Prepare._PREPARED:
        _fail()
    entry = Prepare._PREPARED[context]
    if len(entry) != 5 or entry[0].chan_db is not chan:
        _fail()
    Prepare._assert_native_prepare_owner(chan, context)
    binding = json.loads(entry[4])
    if binding["schema"] in CURRENT_BINDING_SCHEMAS and Prepare._client_binding(entry[0].exchange) != binding["client_binding_sha256"]:
        _fail()
    if binding["schema"] == MONETARY_BINDING_SCHEMA:
        Prepare._assert_execution_sdk(entry[0].exchange, entry[0].mode)
        Prepare._assert_native_prepare_owner(chan, context)
    return entry[0], binding, entry[2]


def _candidate(binding, is_buy):
    if type(is_buy) not in (bool, int) or is_buy not in (True, False):
        _fail()
    contract = binding["identity"]["payload"]["order_contract"]
    return {"instrument_id": contract["market"]["id"], "position_side": contract["execution"]["position_side"],
        "side": "BUY" if is_buy else "SELL", "base_quantity": contract["quantity"], "contracts": contract["exchange_amount"],
        "order_type": "MARKET" if contract["price"] is None else "LIMIT", "limit_price": contract["price"],
        "post_only": contract["post_only"], "reduce_only": False}


def _monetary_result(binding, values, snapshot, *, checked_ms=None):
    book = AccountLimits._book(snapshot, values["market_evidence"], values["candidate"])
    prices = AccountLimits._last_links(values, values["capacity_evidence"]["payload"], checked_ms=checked_ms)
    result = AccountLimits._standard_capacity(values, snapshot, book, prices, checked_ms=checked_ms)
    payload = {"candidate": values["candidate"], "check_id": binding["components"]["payload"]["check_id"],
        "capacity_evidence_sha256": _sha(values["capacity_evidence"]), "last_price_evidence_sha256": _sha(values["last_price_evidence"]),
        "market_evidence_sha256": _sha(values["market_evidence"]), "derived_book_inputs_sha256": _sha(book),
        **result, "coverage": "original_prepared_conditional_monetary_model_only", "economics_complete": False,
        "native_admission_verified": False}
    return {"schema": "chan-native-client-monetary-v1", "payload": payload, "payload_sha256": _sha(payload)}


def _assert_monetary(binding, values, snapshot, *, checked_ms=None):
    expected = _monetary_result(binding, values, snapshot, checked_ms=checked_ms)
    if (expected["payload"]["status"] != "within_model_capacity"
            or canonical_bytes(expected) != canonical_bytes(binding["monetary"])):
        _fail()


def _capacity_links(database, binding, boundary, checked, snapshot=None, *, is_buy=None):
    connection = database.conn
    source, policy = binding["capacity_evidence"], binding["capacity_policy"]
    historical, monetary = snapshot is None, binding["schema"] == MONETARY_BINDING_SCHEMA
    if type(policy) is not dict or set(policy) != {"max_age_ms", "max_observation_span_ms"}:
        _fail()
    for value in policy.values():
        _budget(value)
    if historical:
        Capacity._verify_binance_capacity_evidence_at(source, checked_ms=checked, standard=monetary, **policy)
    elif monetary:
        Capacity.verify_binance_standard_capacity_evidence(source, **policy)
    else:
        Capacity.verify_binance_capacity_evidence(source, **policy)
    c = binding["components"]["payload"]
    if canonical_bytes(source["payload"]["account_context"]) != canonical_bytes(c["account_context"]):
        _fail()
    if snapshot is None:
        from .ExecutionStore import read_scan_with_account
        if database.conn is not connection:
            _fail()
        check = read_check(database, c["check_id"])
        snapshot = {"check": check, "execution_observations": [read_scan_with_account(database, key)[1]["observation"]
                                                                for key in c["source_ids"]["executions"]]}
    saved = snapshot["check"]["payload"]["inputs"]
    AccountLimits._bindings(source["payload"], c["market_evidence"]["payload"], saved)
    values = {"capacity_evidence": source, "market_evidence": c["market_evidence"], "policy": c["policy"], **policy}
    if monetary:
        last_policy = binding["last_price_policy"]
        if type(last_policy) is not dict or set(last_policy) != {"max_age_ms", "max_observation_span_ms"}:
            _fail()
        for value in last_policy.values():
            _budget(value)
        if is_buy is None:
            side = binding["monetary"]["payload"]["candidate"]["side"]
            if side not in {"BUY", "SELL"}:
                _fail()
            is_buy = side == "BUY"
        values.update(candidate=_candidate(binding, is_buy), last_price_evidence=binding["last_price_evidence"],
            last_max_age_ms=last_policy["max_age_ms"], last_max_observation_span_ms=last_policy["max_observation_span_ms"])
        AccountLimits._last_links(values, source["payload"], checked_ms=checked if historical else None)
    AccountLimits._windows(values, snapshot, binding["started_ms"], checked)
    return values


def _windows(chan, binding, boundary, *, final_check=None):
    with_capacity = binding["schema"] in {CAPACITY_BINDING_SCHEMA, MONETARY_BINDING_SCHEMA}
    tick_start = _monotonic_ns() if with_capacity else None
    if binding["implementation_sha256"] != _binding_implementation(binding):
        _fail()
    inputs = Boundary._inputs({key: boundary["payload"][key] for key in Boundary._INPUTS})
    sources = _sources_snapshot(chan, inputs["account_context"], inputs["check_id"], inputs["market_evidence"])
    now, instrument = utc_now_ms(), binding["instruments"]["payload"]
    if (type(now) is not int or not binding["finished_ms"] <= now < 2**63
            or now-instrument["started_ms"] > binding["instrument_policy"]["max_age_ms"]
            or instrument["finished_ms"]-instrument["started_ms"] > binding["instrument_policy"]["max_observation_span_ms"]):
        _fail()
    Boundary._windows(inputs, sources, binding["started_ms"], now)
    if with_capacity:
        values = _capacity_links(chan.db, binding, boundary, now, sources)
        if binding["schema"] == MONETARY_BINDING_SCHEMA:
            _assert_monetary(binding, values, sources)
            if binding["implementation_sha256"] != _binding_implementation(binding):
                _fail()
        if final_check is not None:
            final_check()
        window = sources, values, now, tick_start
        _check_window_tail(binding, window)
        return window  # Private original read data, never a ready/permit receipt.


def _check_window_tail(binding, window):
    """Recheck the original pure windows through work/transaction exit."""
    sources, values, checked, tick_start = window
    tick_end = _monotonic_ns()
    if type(tick_start) is not int or type(tick_end) is not int or not 0 <= tick_start <= tick_end:
        _fail()
    finished = checked+(tick_end-tick_start+999_999)//1_000_000
    instrument = binding["instruments"]["payload"]
    Capacity._window(instrument["started_ms"], instrument["finished_ms"], finished, **binding["instrument_policy"])
    AccountLimits._windows(values, sources, binding["started_ms"], finished)


def validate_stored_preparation(chan, root, attempt):
    """Independent raw/check/immutable-attempt links, not current admission."""
    try:
        _validate_stored_preparation(chan.db, root, attempt)
    except Exception:
        _fail()


def _validate_stored_preparation(database, root, attempt):
    """Same original SQLite facts for frozen checks; never a live handle."""
    try:
        connection = database.conn
        b = root["preparation"]
        if (type(b) is not dict or b["schema"] not in {LEGACY_BINDING_SCHEMA, *CURRENT_BINDING_SCHEMAS}
                or set(b) != {"schema", "identity", "instruments", "components", "instrument_policy", "boundary_sha256",
                    "baseline_records_sha256", "baseline_prefix", "entry_assessment", "started_ms", "finished_ms", "implementation_sha256"}
                    | ({"client_binding_sha256"} if b["schema"] in CURRENT_BINDING_SCHEMAS else set())
                    | ({"capacity_evidence", "capacity_policy"} if b["schema"] in {CAPACITY_BINDING_SCHEMA, MONETARY_BINDING_SCHEMA} else set())
                    | ({"last_price_evidence", "last_price_policy", "monetary"} if b["schema"] == MONETARY_BINDING_SCHEMA else set())
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
        if database.conn is not connection:
            _fail()
        check = read_check(database, c["check_id"])
        if check["payload"]["source_ids"] != c["source_ids"] or check["payload"]["inputs"] is None:
            _fail()
        cap_clocks = []
        snapshot = {"check": check, "execution_observations": []}
        if b["schema"] in {CAPACITY_BINDING_SCHEMA, MONETARY_BINDING_SCHEMA}:
            values = _capacity_links(database, b, root["boundary"], a["intent_ms"], is_buy=a["is_buy"])
            if b["schema"] == MONETARY_BINDING_SCHEMA:
                _assert_monetary(b, values, snapshot, checked_ms=a["intent_ms"])
            cap_clocks = [b["capacity_evidence"]["payload"][key] for key in ("started_ms", "finished_ms")]
        last_clocks = ([b["last_price_evidence"]["payload"][key] for key in ("started_ms", "finished_ms")]
                       if b["schema"] == MONETARY_BINDING_SCHEMA else [])
        clocks = [b["started_ms"], p["started_ms"], p["finished_ms"], instrument["started_ms"], instrument["finished_ms"], *cap_clocks,
                  c["started_ms"], c["finished_ms"], *last_clocks, boundary["captured_ms"], b["finished_ms"], a["intent_ms"]]
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
    risk = float(before.get("risk_multiplier") or 1.0) if binding["schema"] == MONETARY_BINDING_SCHEMA else 1.0
    if (binding["schema"] == MONETARY_BINDING_SCHEMA
            and canonical_bytes(binding["monetary"]["payload"]["candidate"]) != canonical_bytes(_candidate(binding, before["is_buy"]))):
        _fail()
    if (binding["boundary_sha256"] != _sha(boundary) or p["record_sha256"] != _sha(before)
            or binding["baseline_records_sha256"] != _sha(_records(chan)) or binding["baseline_prefix"] != _prefix(chan.db)
            or updates["open_requested_qty"] != p["quantity"]
            or updates["open_order_contract"] != canonical_bytes(_contract(binding)).decode()
            or json.loads(updates["snapshot_before"]) != _snapshot(binding)
            or updates["strategy_version"] != p["scope"]["strategy"] or updates["risk_multiplier"] != risk
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
    _assert_native_prepared_transition_current(engine, record_id, stage="intent")


def _assert_native_prepared_transition_current(engine, record_id, *, stage):
    """One local reader; the original transition determines the exact L1/L2."""
    return _read_native_prepared_transition_current(engine, record_id, stage=stage)[0]


def _read_native_prepared_transition_current(engine, record_id, *, stage):
    """Same full reader, retaining only its internal pure window data."""
    try:
        from . import NativeOrderTransition as Transition
        from . import NativeInstrumentCurrent as Instrument
        from .AccountIdentity import _environment
        from .CCXTTradeEngine import CCCXTTradeEngine
        from .Script.OpeningInputs import COpeningInputs
        from .SafetyPolicy import TradingSafetyPolicy
        if (stage not in {"intent", "claim"}
                or type(engine) is not CCCXTTradeEngine or type(record_id) is not int or record_id <= 0
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
        if document["schema"] != Transition.PREPARED_DOCUMENT_SCHEMA or document["payload"]["stage"] != stage:
            _fail()
        root, after_sha = document["payload"]["root"], document["payload"]["after_record_sha256"]
        binding = root["preparation"]
        p, instrument = binding["identity"]["payload"], binding["instruments"]["payload"]
        if (binding["schema"] not in CURRENT_BINDING_SCHEMAS
                or (stage == "claim" and binding["schema"] != MONETARY_BINDING_SCHEMA)
                or binding["implementation_sha256"] != _binding_implementation(binding) or p["implementation_sha256"] != Prepare._implementation()
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
                record_id, p["request"]["price"], runtime, owners, persisted_record_sha256=after_sha,
                persisted_order_status="created" if stage == "intent" else "submitting")
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
            if binding["schema"] == MONETARY_BINDING_SCHEMA:
                Prepare._assert_execution_sdk(exchange, engine.mode)
                owners()
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
            Transition._current(chan, document)
            owners()
        window = _windows(chan, binding, root["boundary"], final_check=final_check)
        owners()
        return document, window
    except Exception:
        _fail()


def assert_native_prepared_claim_before_http(engine, record_id):
    """Original complete assertion; success remains None, never a permit."""
    _read_native_prepared_claim_before_http(engine, record_id)


def _assert_native_fetch_policy(exchange):
    """SDK fetch-source identity only; no cash, age or trading permission."""
    from inspect import getattr_static

    for name in ("proxyUrlCallback", "proxy_url_callback", "httpProxyCallback", "http_proxy_callback",
                 "httpsProxyCallback", "https_proxy_callback", "socksProxyCallback", "socks_proxy_callback", "proxy"):
        if getattr_static(exchange, name, None) is not None:
            _fail()  # Do not execute an unproven SDK callback/descriptor to qualify it.


def _assert_native_adapter_retry_policy(exchange):
    """Necessary original POST-adapter configuration, never a send permit."""
    from collections import OrderedDict
    from requests import Session, sessions
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = exchange.session
    if (type(session) is not Session or type(session.adapters) is not OrderedDict
            or not session.adapters or any(type(prefix) is not str for prefix in session.adapters)):
        _fail()
    descriptor = vars(Session).get("get_adapter")
    if type(descriptor) is not types.FunctionType:
        _fail()
    method = session.get_adapter
    if type(method) is not types.MethodType or method.__self__ is not session or method.__func__ is not descriptor:
        _fail()
    Prepare._function_identity("requests.sessions", "Session.get_adapter", descriptor, {}, path=Path(sessions.__file__).resolve())
    base = exchange.urls["api"]["fapiPrivate"]
    if type(base) is not str:
        _fail()
    adapter = method(base.rstrip("/")+"/order")
    if type(adapter) is not HTTPAdapter:
        _fail()
    retry = vars(adapter).get("max_retries")
    if type(retry) is not Retry or type(vars(retry).get("total")) is not int or vars(retry)["total"] != 0:
        _fail()


def _read_native_prepared_claim_before_http(engine, record_id):
    """Original L2/profile/use-time checks; no claim, send or permission token.

    Native I/O is outside every writer lock. Existing source clocks/budgets
    are not renewed, and failures cannot recreate or release a claimed order.
    Private original read data stays in this invocation, never caller JSON.
    """
    source_started, account, request = False, None, None
    try:
        from .CCXTTradeEngine import CCCXTTradeEngine
        from .Script.OpeningInputs import COpeningInputs
        from .SafetyPolicy import TradingSafetyPolicy
        if (type(engine) is not CCCXTTradeEngine or type(record_id) is not int or record_id <= 0
                or type(engine.opening_inputs) is not COpeningInputs or type(engine.safety_policy) is not TradingSafetyPolicy
                or engine.dry_run is not False or engine.market_type != "swap" or engine.exchange is None):
            _fail()
        chan, exchange, guard, policy = engine.chan_db, engine.exchange, engine.opening_inputs, engine.safety_policy
        from requests import Session
        session = exchange.session
        if type(session) is not Session or type(session.request) not in {types.FunctionType, types.MethodType}:
            _fail()
        delegate, expected_transport = session.request, [session.request]
        database = Boundary._database(chan)
        connection, table, clock, mode = database.conn, chan.table, guard.now_ms, engine.mode
        configuration, client_binding = canonical_bytes(engine.ccxt_conf), Prepare._client_binding(exchange)
        runtime = None

        def database_owner(*, owned=False):
            Boundary._same_database(chan, database, connection, table, owned=owned)
            if engine.chan_db is not chan:
                _fail()

        def owners(*, owned=False):
            database_owner(owned=owned)
            if (engine.exchange is not exchange or engine.opening_inputs is not guard
                    or exchange.session is not session or session.request != expected_transport[0]
                    or engine.safety_policy is not policy or guard.now_ms is not clock or engine.mode != mode
                    or engine.dry_run is not False or engine.market_type != "swap"
                    or canonical_bytes(engine.ccxt_conf) != configuration or Prepare._client_binding(exchange) != client_binding):
                _fail()
            observed_runtime = Prepare._selected_runtime(engine, guard, policy)
            if runtime is not None and canonical_bytes(observed_runtime) != canonical_bytes(runtime):
                _fail()
            Prepare._assert_execution_sdk(exchange, mode)
            _assert_native_adapter_retry_policy(exchange)

        def source_failure():
            database_owner()
            with database.transaction():
                database_owner(owned=True)
                if not risk_state(database, account)["frozen"]:
                    from .NativeAccountCheck import _publish_unavailable
                    _publish_unavailable(database, account, request)
                database_owner(owned=True)

        owners()
        with database.transaction():
            owners(owned=True)
            document = _assert_native_prepared_transition_current(engine, record_id, stage="claim")
            owners(owned=True)
        owners()
        binding = document["payload"]["root"]["preparation"]
        if binding["schema"] != MONETARY_BINDING_SCHEMA:
            _fail()
        runtime = binding["identity"]["payload"]["runtime"]
        contract = _contract(binding)
        account, request = contract["account_context"], binding["components"]["payload"]["source_ids"]
        if client_binding != binding["client_binding_sha256"]:
            _fail()
        owners()
        source_started = True
        engine._assert_account_context(contract)
        owners()
        observation = engine._observe_account(contract["market"]["symbol"], contract["execution"], reduce_only=False,
                                              _assert_current=owners)
        owners()
        if canonical_bytes(observation) != canonical_bytes(contract["account_observation"]):
            _fail()
        with database.transaction():
            owners(owned=True)
            current, window = _read_native_prepared_transition_current(engine, record_id, stage="claim")
            owners(owned=True)
            if canonical_bytes(current) != canonical_bytes(document):
                _fail()
            record = chan.get_record(record_id)
            owners(owned=True)
            if _sha(record) != document["payload"]["after_record_sha256"]:
                _fail()
            client_id = record["open_client_order_id"]
        owners()
        Prepare._assert_execution_sdk(exchange, mode)
        owners()
        if Prepare._client_binding(exchange) != client_binding:
            _fail()
        owners()
        # Include final code/SDK checks and the original transaction exit in
        # use time, without another caller/business-clock callback afterward.
        _check_window_tail(binding, window)
        return document, binding, window, owners, source_failure, (session, delegate, expected_transport, client_id)
    except Exception:
        if source_started and account is not None:
            try:
                source_failure()
            except Exception:
                _fail()
        _fail()


def _native_http_fetch_delegate(exchange, bridge):
    """Read only this suspended original invocation, not wrapper metadata/proof.

    The caller still fresh-checks the returned bound SDK method against its
    installed descriptor. No registry, caller context or permission is used.
    """
    from threading import get_ident

    modules = {}
    qualname = "_native_prepared_claim_http_use.<locals>.use.<locals>.fetch_guard"
    Prepare._function_identity(__name__, qualname, bridge, modules)
    if bridge.__dict__ or not bridge.__closure__:
        _fail()
    cells = {name: cell.cell_contents for name, cell in zip(bridge.__code__.co_freevars, bridge.__closure__)}
    frame = cells.get("call_frame")
    if type(frame) is not types.FrameType or frame.f_globals is not globals():
        _fail()
    compiled = modules[__name__][1]
    expected = next(code for code in Prepare._codes(compiled)
                    if code.co_qualname == "_native_prepared_claim_http_use.<locals>.use")
    local = frame.f_locals
    if (frame.f_code != expected or local.get("call_frame") is not frame
            or local.get("fetch_guard") is not bridge or local.get("installed_fetch") is not bridge or exchange.fetch is not bridge
            or local.get("exchange") is not exchange or local.get("active") is not True
            or type(local.get("thread_id")) is not int or local["thread_id"] != get_ident()
            or local.get("engine") is None or local["engine"].exchange is not exchange
            or any(name not in local or local[name] is not value for name, value in cells.items())):
        _fail()
    for name, qualname in (
        ("current_claim", "_native_prepared_claim_http_use.<locals>.use.<locals>.current_claim"),
        ("owners", "_read_native_prepared_claim_before_http.<locals>.owners"),
        ("source_failure", "_read_native_prepared_claim_before_http.<locals>.source_failure"),
    ):
        Prepare._function_identity(__name__, qualname, local[name], modules)
    checker = local["current_claim"]
    if any(local.get(name) is not cell.cell_contents for name, cell in zip(checker.__code__.co_freevars, checker.__closure__)):
        _fail()
    owner = local["owners"]
    captured = {name: cell.cell_contents for name, cell in zip(owner.__code__.co_freevars, owner.__closure__)}
    if any(captured[name] is not local[field] for name, field in (
        ("engine", "engine"), ("exchange", "exchange"), ("session", "session"), ("expected_transport", "expected"),
    )):
        _fail()
    database_owner = captured["database_owner"]
    Prepare._function_identity(__name__, "_read_native_prepared_claim_before_http.<locals>.database_owner", database_owner, modules)
    database_cells = {name: cell.cell_contents for name, cell in zip(database_owner.__code__.co_freevars, database_owner.__closure__)}
    engine, database = local["engine"], local["database"]
    if (database_cells["engine"] is not engine or database_cells["chan"] is not engine.chan_db
            or database_cells["database"] is not database or database_cells["connection"] is not database.conn
            or database_cells["table"] != engine.chan_db.table
            or captured["guard"] is not engine.opening_inputs or captured["policy"] is not engine.safety_policy
            or captured["clock"] is not engine.opening_inputs.now_ms
            or captured["mode"] != engine.mode or captured["configuration"] != canonical_bytes(engine.ccxt_conf)
            or captured["client_binding"] != local["binding"]["client_binding_sha256"]
            or canonical_bytes(captured["runtime"]) != canonical_bytes(local["binding"]["identity"]["payload"]["runtime"])):
        _fail()
    failure = local["source_failure"]
    failure_cells = {name: cell.cell_contents for name, cell in zip(failure.__code__.co_freevars, failure.__closure__)}
    if failure_cells["database_owner"] is not database_owner or failure_cells["database"] is not database:
        _fail()
    return local["fetch_delegate"]


def _native_prepared_claim_http_use(engine, record_id):
    """One original SDK invocation, old L2/window, original request delegate."""
    from contextlib import contextmanager
    from threading import get_ident
    from urllib.parse import parse_qs

    @contextmanager
    def use():
        from .CCXTTradeEngine import CCCXTTradeEngine
        if type(engine) is not CCCXTTradeEngine or engine.exchange is None:
            _fail()
        if getattr(engine.exchange.session.request, "_chan_native_http_scope", False):
            _fail()  # Negative reentry marker, never permission or caller proof.
        document, binding, window, owners, source_failure, transport = _read_native_prepared_claim_before_http(engine, record_id)
        session, delegate, expected, client_id = transport
        exchange, database = engine.exchange, engine.chan_db.db
        fetch_delegate = exchange.fetch
        fetch_override, had_fetch_override = exchange.__dict__.get("fetch"), "fetch" in exchange.__dict__
        original_override = session.__dict__.get("request")
        had_override = "request" in session.__dict__
        thread_id, active, used, fetch_used, completed = get_ident(), True, False, False, False
        call_frame = sys._getframe()
        expected_url = exchange.urls["api"]["fapiPrivate"].rstrip("/")+"/order"

        def current_claim():
            owners()
            with database.transaction():
                owners(owned=True)
                current = _assert_native_prepared_transition_current(engine, record_id, stage="claim")
                owners(owned=True)
                if canonical_bytes(current) != canonical_bytes(document):
                    _fail()
            owners()

        def fetch_guard(url, method="GET", headers=None, body=None):
            nonlocal fetch_used
            if method != "POST":
                return fetch_delegate(url, method, headers, body)
            if call_frame is None or not active or fetch_used or get_ident() != thread_id:
                _fail()  # A stale/reused/foreign-thread callback owns no failure writer.
            Prepare._function_identity(__name__, "_native_http_fetch_delegate", _native_http_fetch_delegate, {})
            _native_http_fetch_delegate(exchange, fetch_guard)
            try:
                if exchange.fetch is not fetch_guard or url != expected_url:
                    _fail()
                # owners checks the actual bridge/closure AND all original SDK
                # descriptors, including the captured unwrapped bound fetch.
                current_claim()
            except Exception:
                source_failure()
                _fail()
            fetch_used = True
            return fetch_delegate(url, method, headers, body)

        def guarded(method, url, **kwargs):
            nonlocal used
            if method != "POST":
                return delegate(method, url, **kwargs)
            body = kwargs.get("data", b"")
            if type(body) is bytes:
                body = body.decode("utf-8")
            fields = parse_qs(body, keep_blank_values=True, strict_parsing=True)
            own_order = fields.get("newClientOrderId") == [client_id]
            if get_ident() != thread_id:
                if own_order:
                    _fail()
                return delegate(method, url, **kwargs)  # No new budget on other management calls.
            Prepare._function_identity(__name__, "_native_http_fetch_delegate", _native_http_fetch_delegate, {})
            _native_http_fetch_delegate(exchange, fetch_guard)
            try:
                if not active or used or not own_order or url != expected_url or kwargs.get("verify") is not True:
                    _fail()
                kwargs["allow_redirects"] = False  # One guarded POST must not spawn an unchecked send below Requests.
                current_claim()
                _check_window_tail(binding, window)  # Keep the PRE-SDK anchor, including SDK wait/work.
            except Exception:
                source_failure()
                _fail()
            used = True  # Unknown transport outcome still consumes this one invocation.
            return delegate(method, url, **kwargs)

        guarded._chan_native_http_scope = True
        installed_fetch = fetch_guard  # Original fast local, not a rebindable bridge closure cell.
        try:
            session.request, expected[0] = guarded, guarded
            exchange.fetch = fetch_guard
            yield None
            completed = True
        finally:
            active = False
            changed = False
            if exchange.fetch is not installed_fetch:
                changed = True
            elif had_fetch_override:
                exchange.fetch = fetch_override
            else:
                del exchange.fetch
            if session.request is not guarded:
                changed = True  # Restore the other hook, never an external replacement.
            elif had_override:
                session.request = original_override
            else:
                del session.request
            expected[0] = delegate
            call_frame = None
            if changed:
                _fail()
            Prepare._function_identity(__name__, "_read_native_prepared_claim_before_http.<locals>.owners", owners, {})
            owners()
            if completed and (not used or not fetch_used):
                _fail()
    return use()


def _capture_native_claim_context(engine, record_id):
    """Capture real current L1 under the original lock, without collection/send."""
    try:
        from . import NativeOrderTransition as Transition
        document = _assert_native_prepared_transition_current(engine, record_id, stage="intent")
        if document["payload"]["root"]["preparation"]["schema"] != MONETARY_BINDING_SCHEMA:
            _fail()  # Older diagnostic bindings never acquire monetary execution.
        chan, exchange, guard, policy = engine.chan_db, engine.exchange, engine.opening_inputs, engine.safety_policy
        database = Transition._owned(chan)
        connection, table, clock = database.conn, chan.table, guard.now_ms
        frozen = canonical_bytes(document)

        def owners(*, owned=True):
            Boundary._same_database(chan, database, connection, table,
                                    owned=connection.in_transaction if owned is None else owned)
            if (engine.chan_db is not chan or engine.exchange is not exchange or engine.opening_inputs is not guard
                    or engine.safety_policy is not policy or guard.now_ms is not clock):
                _fail()

        def check(stage):
            owners()
            actual = _assert_native_prepared_transition_current(engine, record_id, stage=stage)
            owners()
            if stage == "intent":
                if canonical_bytes(actual) != frozen:
                    _fail()
            elif (canonical_bytes(actual["payload"]["root"]) != canonical_bytes(document["payload"]["root"])
                    or actual["payload"]["previous_sha256"] != document["payload_sha256"]):
                _fail()
            return actual

        owners()
        context = _NativeClaimContext()
        _CLAIMS[context] = (engine, owners, check)
        return context
    except Exception:
        _fail()


def _assert_native_claim_owner(chan, context):
    """No SQL: reject a changed owner before the original writer opens a txn."""
    if type(context) is not _NativeClaimContext or context not in _CLAIMS:
        _fail()
    engine, owners, _ = _CLAIMS[context]
    if engine.chan_db is not chan:
        _fail()
    owners(owned=None)


def _claim_live(chan, context, *, stage):
    _assert_native_claim_owner(chan, context)
    _, _, check = _CLAIMS[context]
    return check(stage)


def consume_prepared_claim_context(chan, before, context, document):
    """Original writer verifies its actual L1, not caller-provided identity."""
    current = _claim_live(chan, context, stage="intent")
    if (canonical_bytes(current) != canonical_bytes(document)
            or _sha(before) != current["payload"]["after_record_sha256"]):
        _fail()


def finish_prepared_claim_context(chan, context, document):
    """After the original single claim event, validate exact L2 and its tail."""
    current = _claim_live(chan, context, stage="claim")
    if canonical_bytes(current) != canonical_bytes(document):
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


def acquire_binance_standard_prepared_intent(engine, record_id, amount, price, *, before_id, account_scope, policy,
        instrument_max_age_ms, instrument_max_observation_span_ms, capacity_max_age_ms, capacity_max_observation_span_ms,
        last_max_age_ms, last_max_observation_span_ms, client_order_id, post_only=False, entry_assessment=None):
    """Own F/P sources and monetary model in the original intent CAS.

    The full claim/send consumer gate remains separate; this does not send.
    """
    return _acquire_prepared_diagnostic_intent(engine, record_id, amount, price, before_id=before_id,
        account_scope=account_scope, policy=policy, instrument_max_age_ms=instrument_max_age_ms,
        instrument_max_observation_span_ms=instrument_max_observation_span_ms, client_order_id=client_order_id,
        post_only=post_only, entry_assessment=entry_assessment,
        capacity_policy={"max_age_ms": capacity_max_age_ms, "max_observation_span_ms": capacity_max_observation_span_ms},
        monetary_policy={"max_age_ms": last_max_age_ms, "max_observation_span_ms": last_max_observation_span_ms})


def _acquire_prepared_diagnostic_intent(engine, record_id, amount, price, *, before_id, account_scope, policy,
        instrument_max_age_ms, instrument_max_observation_span_ms, client_order_id, post_only, entry_assessment, capacity_policy,
        monetary_policy=None):
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
        if monetary_policy is not None:
            if capacity_policy is None:
                _fail()
            for value in monetary_policy.values():
                _budget(value)
            Prepare._assert_execution_sdk(engine.exchange, engine.mode)
            Prepare._function_identity(__name__, "_assert_native_adapter_retry_policy", _assert_native_adapter_retry_policy, {})
            _assert_native_adapter_retry_policy(engine.exchange)
            retries, _ = engine.exchange.handle_option_integer_and_params({}, "order", "maxRetriesOnFailure", 0)
            if type(retries) is not int or retries != 0:
                _fail()  # An accepted but unknown POST must never be retried by the SDK.
        policy_value = read_native_component_policy(policy)
        venue_pattern = r"[.A-Za-z0-9_:/-]{1,36}" if engine.ccxt_conf.get("exchange") in {"binance", "binanceusdm"} else r"[A-Za-z0-9]{1,32}"
        if (type(client_order_id) is not str or re.fullmatch(venue_pattern, client_order_id) is None
                or type(account_scope) is not str or re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", account_scope) is None):
            _fail()
        original = canonical_bytes({"before_id": before_id, "account_scope": account_scope, "policy": policy,
            "instrument_age": instrument_max_age_ms, "instrument_span": instrument_max_observation_span_ms, "client_order_id": client_order_id,
            "capacity_policy": capacity_policy, "monetary_policy": monetary_policy})
        chan, client = engine.chan_db, engine.exchange
        database = Boundary._database(chan)
        connection, table = database.conn, chan.table
        Boundary._same_database(chan, database, connection, table, owned=False)
        schema = MONETARY_BINDING_SCHEMA if monetary_policy is not None else BINDING_SCHEMA if capacity_policy is None else CAPACITY_BINDING_SCHEMA
        implementation, started = _binding_implementation({"schema": schema}), utc_now_ms()
        if type(started) is not int or not 0 <= started < 2**63:
            _fail()
        with database.transaction():
            before = read_evidence(database, before_id)
            if (before["schema"] != SNAPSHOT_SCHEMA or before["payload"]["account_context"]["mode"] != engine.mode
                    or risk_state(database, before["payload"]["account_context"])["frozen"]):
                _fail()
            records, prefix = _sha(_records(chan)), _prefix(database)
            signal = chan.get_record(record_id)
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
        capacity_reader = Capacity.collect_binance_standard_capacity_evidence if monetary_policy is not None else Capacity.collect_binance_capacity_evidence
        capacity = None if capacity_policy is None else capacity_reader(client, units, mode=engine.mode, **capacity_policy)
        if capacity_policy is not None:
            Boundary._same_database(chan, database, connection, table, owned=False)
            if engine.chan_db is not chan or engine.exchange is not client or type(capacity) is not dict:
                _fail()
        components = collect_and_check_native_components(chan, client, mode=engine.mode, markets=units,
                            before_id=before_id, account_scope=account_scope, policy=policy_value)
        Boundary._same_database(chan, database, connection, table, owned=False)
        last = (None if monetary_policy is None else collect_prepared_binance_last_prices(engine, context, **monetary_policy))
        Boundary._same_database(chan, database, connection, table, owned=False)
        c = components["payload"]
        boundary = Boundary.capture_native_order_boundary(chan, account_context=account, check_id=c["check_id"],
                                              market_evidence=c["market_evidence"], policy=policy_value)
        binding = {"schema": schema,
            "identity": identity, "instruments": instruments, "components": components,
            "client_binding_sha256": client_binding,
            "instrument_policy": {"max_age_ms": instrument_max_age_ms, "max_observation_span_ms": instrument_max_observation_span_ms},
            "boundary_sha256": _sha(boundary), "baseline_records_sha256": records, "baseline_prefix": prefix,
            "entry_assessment": entry_assessment, "started_ms": started, "finished_ms": utc_now_ms(), "implementation_sha256": implementation}
        if capacity_policy is not None:
            binding.update(capacity_evidence=capacity, capacity_policy=capacity_policy)
        if monetary_policy is not None:
            binding.update(last_price_evidence=last, last_price_policy=monetary_policy)
            tick_start, checked = _monotonic_ns(), utc_now_ms()
            with database.transaction():
                snapshot = _sources_snapshot(chan, account, c["check_id"], c["market_evidence"])
                Boundary._same_database(chan, database, connection, table, owned=True)
            Boundary._same_database(chan, database, connection, table, owned=False)
            values = _capacity_links(chan.db, binding, boundary, checked, snapshot, is_buy=signal["is_buy"])
            binding["monetary"] = _monetary_result(binding, values, snapshot)
            Boundary._same_database(chan, database, connection, table, owned=False)
            tick_end = _monotonic_ns()
            if type(tick_start) is not int or type(tick_end) is not int or not 0 <= tick_start <= tick_end:
                _fail()
            finished = checked+(tick_end-tick_start+999_999)//1_000_000
            Capacity._window(instruments["payload"]["started_ms"], instruments["payload"]["finished_ms"], finished,
                             **binding["instrument_policy"])
            AccountLimits._windows(values, snapshot, binding["started_ms"], finished)
            if binding["monetary"]["payload"]["status"] != "within_model_capacity":
                _fail()
        if (engine.chan_db is not chan or engine.exchange is not client or original != canonical_bytes({"before_id": before_id,
                "account_scope": account_scope, "policy": policy, "instrument_age": instrument_max_age_ms,
                "instrument_span": instrument_max_observation_span_ms, "client_order_id": client_order_id,
                "capacity_policy": capacity_policy, "monetary_policy": monetary_policy})):
            _fail()
        Boundary._same_database(chan, database, connection, table, owned=False)
        Prepare._PREPARED[context] = (*Prepare._PREPARED[context], canonical_bytes(binding))
        return chan.acquire_open_intent(record_id, requested_qty=identity["payload"]["quantity"], client_order_id=client_order_id,
            position_side=identity["payload"]["order_contract"]["execution"]["position_side"], strategy_version=identity["payload"]["scope"]["strategy"],
            risk_multiplier=float(signal.get("risk_multiplier") or 1.0) if monetary_policy is not None else 1.0,
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
