"""Actual local prepare identity, not collection ownership or permission.

This read-only order boundary calls the original input guard and Engine. It
does not accept a caller's check/receipt, publish an intent, allocate funds or
enable the diagnostic CAS contract. The next collector-owned path must call
this logic itself; its JSON must never become a transferable admission token.
"""
import ast
import hashlib
import json
import math
import platform
import sys
import types
import weakref
from pathlib import Path

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes


SCHEMA = "chan-native-prepare-identity-v1"
_ROOT = Path(__file__).resolve().parents[1]
_FILES = ("Trade/NativePreparation.py", "Trade/CCXTTradeEngine.py", "Trade/TradeEngine.py", "Trade/SafetyPolicy.py",
          "Trade/Script/OpeningInputs.py", "Trade/Script/Deployment.py", "Trade/db_util.py", "Trade/OrderAudit.py", "Trade/PaperState.py")
_ENV_KEYS = ("CHANPY_KILL_SWITCH", "CHANPY_ENABLE_TESTNET", "CHANPY_LIVE_TRADING_UNLOCK")


class _NativePrepareContext:
    """An empty live-call handle, not a reconstructible admission document."""
    __slots__ = ("__weakref__",)


_PREPARED = weakref.WeakKeyDictionary()


def _fail():
    raise CChanException("原生 prepare 的实际输入/候选/执行身份已变；不是资金或发送许可", ErrCode.TRADE_UNLOCK_FAIL) from None


def _sha(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _codes(code):
    yield code
    for item in code.co_consts:
        if type(item) is types.CodeType:
            yield from _codes(item)


def _function_node(tree, qualname):
    node = tree
    for name in qualname.split("."):
        if name == "<locals>":
            continue
        pending, matches = list(node.body), []
        while pending:
            child = pending.pop()
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if child.name == name:
                    matches.append(child)
                continue  # Control flow is lexical; a different function/class is not.
            pending.extend(ast.iter_child_nodes(child))
        if len(matches) != 1:
            _fail()
        node = matches[0]
    return node


def _function_identity(module, qualname, function, modules, *, path=None):
    """The same fresh-compile/default check for local and installed SDK code."""
    path = _ROOT/(module.replace(".", "/")+".py") if path is None else path
    if (type(function) is not types.FunctionType or function.__module__ != module or function.__qualname__ != qualname
            or function.__globals__ is not vars(sys.modules[module])
            or Path(function.__code__.co_filename).resolve() != path.resolve()):
        _fail()
    if module not in modules:
        source = path.read_text(encoding="utf-8")
        modules[module] = (ast.parse(source), compile(source, function.__code__.co_filename, "exec", dont_inherit=True,
                                                    optimize=sys.flags.optimize), hashlib.sha256(source.encode()).hexdigest())
    tree, compiled, digest = modules[module]
    expected = next(code for code in _codes(compiled) if code.co_qualname == qualname)
    node = _function_node(tree, qualname)
    defaults = tuple(ast.literal_eval(n) for n in node.args.defaults) or None
    keywords = {name.arg: ast.literal_eval(value) for name, value in zip(node.args.kwonlyargs, node.args.kw_defaults) if value is not None} or None
    if (function.__code__ != expected or canonical_bytes(function.__defaults__) != canonical_bytes(defaults)
            or canonical_bytes(function.__kwdefaults__) != canonical_bytes(keywords)):
        _fail()
    return {"source_sha256": digest, "qualname": qualname,
            "defaults_sha256": _sha({"positional": defaults, "keywords": keywords})}


def _assert_execution_sdk(exchange, mode, *, source_entries=()):
    """Check declared Binance SDK execution paths, never grant send permission.

    No SDK re-import/exec, cache renewal, endpoint, caller receipt or permit.
    This is not trust in every dependency or the entire Python process.
    """
    import ccxt
    from ccxt.base.types import Entry
    try:
        if (type(source_entries) is not tuple or any(type(name) is not str for name in source_entries)
                or mode not in {"live", "testnet"} or exchange.id not in {"binance", "binanceusdm"}
                or type(exchange) is not getattr(ccxt, exchange.id)):
            _fail()
        sdk_root, modules = Path(ccxt.__file__).resolve().parent, {}
        from . import NativePreparedIntent as prepared_module
        fetch_policy = prepared_module._assert_native_fetch_policy
        _function_identity("Trade.NativePreparedIntent", "_assert_native_fetch_policy", fetch_policy, modules)
        fetch_policy(exchange)
        allowed = {cls.__module__ for cls in type(exchange).__mro__ if cls.__module__.startswith("ccxt.")}
        for name in ("create_order", "create_order_request", "fetch_order", "fetch_orders", "fetch_open_orders", "fetch_closed_orders",
                     "cancel_order", "parse_order", "parse_order_status", "safe_order", "parse_trade", "parse_market", "set_markets",
                     "market", "load_markets", "amount_to_precision", "price_to_precision", "cost_to_precision", "handle_post_only",
                     "handle_margin_mode_and_params", "handle_market_type_and_params", "fetch_leverage", "fetch_position_mode",
                     "request", "fetch2", "fetch", "sign", "handle_errors",
                     "prepare_request_headers", "set_headers", "check_proxy_url_settings", "check_proxy_settings",
                     "check_conflicting_proxies", "value_is_defined",
                     "handle_option_integer_and_params", "handle_option_and_params", "check_option_integer"):
            owner = next(cls for cls in type(exchange).__mro__ if name in vars(cls))
            descriptor = vars(owner)[name]
            if type(descriptor) is not types.FunctionType or descriptor.__module__ not in allowed:
                _fail()
            _function_identity(owner.__module__, owner.__qualname__+"."+name, descriptor, modules,
                               path=sdk_root.joinpath(*owner.__module__.split(".")[1:]).with_suffix(".py"))
            method = getattr(exchange, name)
            if name == "fetch" and type(method) is types.FunctionType:
                from . import NativePreparedIntent as prepared_module
                reader = prepared_module._native_http_fetch_delegate
                _function_identity("Trade.NativePreparedIntent", "_native_http_fetch_delegate", reader, modules)
                method = reader(exchange, method)
            if (type(method) is not types.MethodType or getattr(method, "__self__", None) is not exchange
                    or getattr(method, "__func__", None) is not descriptor):
                _fail()
        entry_path = sdk_root/"base/types.py"
        for name in ("__init__", "__get__"):
            _function_identity("ccxt.base.types", "Entry."+name, vars(Entry)[name], modules, path=entry_path)
        for name in ("fapiPrivatePostOrder", "fapiPrivateGetOrder", "fapiPrivateDeleteOrder",
                     "fapiPrivateGetAllOrders", "fapiPrivateGetOpenOrders")+source_entries:
            owner = next(cls for cls in type(exchange).__mro__ if name in vars(cls))
            descriptor = vars(owner)[name]
            if type(descriptor) is not Entry:
                _fail()
            route_path = sdk_root.joinpath(*owner.__module__.split(".")[1:]).with_suffix(".py")
            tree = ast.parse(route_path.read_text(encoding="utf-8"))
            statement = next(node for node in _function_node(tree, owner.__qualname__).body if isinstance(node, ast.Assign)
                             and any(isinstance(target, ast.Name) and target.id == name for target in node.targets))
            if (not isinstance(statement.value, ast.Call) or not isinstance(statement.value.func, ast.Subscript)
                    or not isinstance(statement.value.func.value, ast.Name) or statement.value.func.value.id != "Entry"
                    or statement.value.keywords or len(statement.value.args) != 4):
                _fail()
            fields = vars(descriptor)
            if (set(fields) != {"name", "path", "api", "method", "config", "unbound_method"}
                    or fields["name"] != statement.targets[-1].id
                    or canonical_bytes([fields[key] for key in ("path", "api", "method", "config")]) !=
                       canonical_bytes([ast.literal_eval(value) for value in statement.value.args])):
                _fail()
            function = fields["unbound_method"]
            _function_identity("ccxt.base.types", "Entry.__init__.<locals>.unbound_method", function, modules, path=entry_path)
            if (function.__code__.co_freevars != ("self",) or len(function.__closure__ or ()) != 1
                    or function.__closure__[0].cell_contents is not descriptor):
                _fail()
            method = getattr(exchange, name)
            if (type(method) is not types.MethodType or getattr(method, "__self__", None) is not exchange
                    or getattr(method, "__func__", None) is not function):
                _fail()
    except Exception:
        _fail()


def _selected_runtime(engine, guard, policy):
    """Fresh compile only, never exec/import a second copy of trading code."""
    from . import CCXTTradeEngine as engine_module
    from . import SafetyPolicy as safety_module
    from . import PaperState as paper_module
    from . import NativePreparedClient as client_module
    from . import NativePreparedIntent as prepared_module
    from . import OrderAudit as audit_module
    from . import TradeEngine as trade_module
    from DataAPI import ccxt as data_module
    from .Script import Deployment as deployment_module
    management = guard is None
    if management and (type(policy) is not safety_module.ManagementOnlyTradingSafetyPolicy
            or engine._management_only_policy is not policy or engine.safety_policy is not policy
            or engine._query_only_policy is not None):
        _fail()
    policy_class = "ManagementOnlyTradingSafetyPolicy" if management else "TradingSafetyPolicy"
    selected = []
    for owner, module, cls, names in (
        (engine, "Trade.CCXTTradeEngine", "CCCXTTradeEngine", ("prepare_order", "get_exchange", "check_open_inputs", "assert_order_mutation_allowed", "_market_contract",
             "_native_entry_profile", "_acquire_open_intent",
             "_execution_settings", "_observe_account", "_assert_account_context", "_validated_persisted_intent",
             "_read_order_contract", "_assert_persisted_monetary_contract", "_monetary_consumer_owner", "_fetch_persisted_order",
             "_find_order_in_history", "_check_order_identity", "_result_from_ccxt", "_resolve_position_side")),
        (guard, "Trade.Script.OpeningInputs", "COpeningInputs", () if management else ("check", "assert_current", "snapshot")),
        (policy, "Trade.SafetyPolicy", policy_class, ("assert_order_allowed",)),
        (engine.chan_db, "Trade.db_util", "CChanDB", ("_order_write", "claim_order_submission", "record_order_ack")),
        (engine, "Trade.TradeEngine", "CTradeEngine", ("add_trade",)),
    ):
        for name in names:
            method = getattr(owner, name)
            if type(method) is not types.MethodType or getattr(method, "__self__", None) is not owner:
                _fail()
            selected.append((module, cls+"."+name, method.__func__))
    for name in (() if management else ("env", "scope")):
        descriptor = vars(type(guard))[name]
        if type(descriptor) is not property or descriptor.fset is not None or descriptor.fdel is not None:
            _fail()
        selected.append(("Trade.Script.OpeningInputs", "COpeningInputs."+name, descriptor.fget))
    for name in ("_check_limits", "_venue_params", "_check_execution_evidence", "_check_execution_report", "_order_client_id"):
        descriptor = vars(type(engine))[name]
        if type(descriptor) is not staticmethod or getattr(engine, name) is not descriptor.__func__:
            _fail()
        selected.append(("Trade.CCXTTradeEngine", "CCCXTTradeEngine."+name, descriptor.__func__))
    # functools metadata is not proof of the callable that really executes.
    # Check the original wrapper code/globals AND its actual closed-over body.
    wrapper_path = _ROOT/"Trade/PaperState.py"
    for name in ("place_order", "query_order", "cancel_order"):
        method = getattr(engine, name)
        if type(method) is not types.MethodType or getattr(method, "__self__", None) is not engine:
            _fail()
        wrapper = method.__func__
        body = getattr(wrapper, "__wrapped__", None)
        if (type(wrapper) is not types.FunctionType or type(body) is not types.FunctionType
                or wrapper.__globals__ is not vars(paper_module)
                or Path(wrapper.__code__.co_filename).resolve() != wrapper_path.resolve()
                or wrapper.__defaults__ is not None or wrapper.__kwdefaults__ is not None
                or wrapper.__code__.co_freevars != ("method",) or len(wrapper.__closure__ or ()) != 1
                or wrapper.__closure__[0].cell_contents is not body):
            _fail()
        compiled = compile(wrapper_path.read_text(encoding="utf-8"), wrapper.__code__.co_filename, "exec",
                           dont_inherit=True, optimize=sys.flags.optimize)
        expected = next(code for code in _codes(compiled) if code.co_qualname == "paper_state_operation.<locals>.checked")
        if wrapper.__code__ != expected:
            _fail()
        selected.append(("Trade.CCXTTradeEngine", "CCCXTTradeEngine."+name, body))
    selected.append(("Trade.PaperState", "paper_state_operation", paper_module.paper_state_operation))
    selected.extend(("Trade.NativePreparedClient", name, getattr(client_module, name)) for name in (
        "initialize_native_order_recovery_client", "initialize_native_prepared_client"))
    selected.append(("DataAPI.ccxt", "create_exchange", data_module.create_exchange))
    selected.append(("Trade.TradeEngine", "CTradeEngine._acquire_open_intent", trade_module.CTradeEngine._acquire_open_intent))
    selected.extend(("Trade.NativePreparedIntent", name, getattr(prepared_module, name)) for name in (
        "acquire_binance_standard_prepared_intent", "_acquire_prepared_diagnostic_intent",
        "_capture_native_claim_context", "_assert_native_claim_owner", "_claim_live",
        "consume_prepared_claim_context", "finish_prepared_claim_context",
        "assert_native_prepared_claim_before_http", "_read_native_prepared_claim_before_http", "_native_prepared_claim_http_use",
        "_native_http_fetch_delegate",
        "_assert_native_adapter_retry_policy", "_assert_native_fetch_policy",
        "_assert_native_prepared_transition_current",
        "_read_native_prepared_transition_current", "_windows", "_check_window_tail"))
    selected.extend(("Trade.OrderAudit", name, getattr(audit_module, name)) for name in (
        "_native_terminal_observation", "_sdk_submission_report", "_assert_sdk_submission",
        "_append", "_read_attempt", "read_history", "_history_header"))
    selected.extend(("Trade.CCXTTradeEngine", name, getattr(engine_module, name))
                    for name in ("_quantity", "_float_exact", "_contract_id"))
    selected.extend(("Trade.SafetyPolicy", name, getattr(safety_module, name))
                    for name in ("build_trading_safety_policy", "build_query_only_safety_policy", "build_management_only_safety_policy",
                                 "_load_candidate_receipt", "_configured_mode", "_assert_private_configuration"))
    selected.append(("Trade.AccountIdentity", "observe_account_context", engine_module.observe_account_context))
    selected.append(("Trade.Script.Deployment", "verify_entry_assessment", deployment_module.verify_entry_assessment))
    selected.extend((__name__, name, globals()[name]) for name in ("_local_prepare_view", "_stable_local_view", "_function_identity", "_assert_execution_sdk"))
    modules, result = {}, {}
    for module, qualname, function in selected:
        result[module+":"+qualname] = _function_identity(module, qualname, function, modules)
    return {"coverage": "selected_management_callables" if management else "selected_prepare_callables", "python": platform.python_version(),
            "implementation": platform.python_implementation(), "optimize": sys.flags.optimize, "callables": result}


def _implementation():
    return {name: hashlib.sha256((_ROOT/name).read_bytes()).hexdigest() for name in _FILES}


def _client_binding(client):
    # Only read initialized data. In particular do not call market(), precision
    # helpers or load_markets(), which can perform I/O when a cache is absent.
    if type(client.markets) is not dict or not client.markets or type(client.markets_by_id) is not dict or not client.markets_by_id:
        _fail()
    return _sha({name: getattr(client, name, None) for name in (
        "markets", "markets_by_id", "symbols", "ids", "options", "precisionMode", "urls", "headers", "hostname",
        "verify", "isSandboxModeEnabled", "proxies", "proxyUrl", "httpProxy", "httpsProxy", "socksProxy", "apiKey", "secret", "password")})


def _stable_local_view(value):
    return {**value, "opening_inputs": {k: v for k, v in value["opening_inputs"].items() if k != "checked_at_ms"}}


def _local_prepare_view(engine, guard, policy, chan, database, table, record_id, price, runtime, owners, *,
                        signal_record=None, expected_record=None, persisted_record_sha256=None, persisted_order_status="created"):
    """One local reader; persisted hashes must come from original CAS events."""
    env = guard.env
    owners()
    if (engine.mode != env.ccxt_conf.get("mode") or engine.dry_run is not False or engine.market_type != "swap"
            or canonical_bytes(engine.ccxt_conf) != canonical_bytes(env.ccxt_conf)):
        _fail()
    from .SafetyPolicy import build_trading_safety_policy
    fresh_policy = build_trading_safety_policy(engine.ccxt_conf, env.get_section("trade"), policy.environ)
    if fresh_policy.mode != policy.mode or fresh_policy.strategy_receipt != policy.strategy_receipt:
        _fail()
    policy.assert_order_allowed()
    owners()
    candidate = fresh_policy.strategy_receipt
    candidate_identity = {**candidate, "file_sha256": hashlib.sha256(Path(candidate["path"]).read_bytes()).hexdigest()}
    actual = chan.get_record(record_id)
    if persisted_record_sha256 is not None:
        if (persisted_order_status not in {"created", "submitting"}
                or actual is None or _sha(actual) != persisted_record_sha256 or actual["status"] != "submitted"
                or actual["open_order_status"] != persisted_order_status or actual["open_attempt"] != 1):
            _fail()
    else:
        if persisted_order_status != "created":
            _fail()
        if expected_record is not None:
            if canonical_bytes(actual) != canonical_bytes(expected_record):
                _fail()
            actual = signal_record
        if (actual is None or actual["status"] != "signal" or actual["watching"] != 1 or actual["is_open"] != 0
                or actual["open_attempt"] != 0 or actual["open_client_order_id"] is not None):
            _fail()
    stamp = guard.check(actual, engine=engine, price=price)
    owners()
    scope = guard.scope
    owners()
    if _sha(scope) != stamp["scope_sha256"]:
        _fail()
    return {"record_sha256": _sha(actual), "config_sha256": hashlib.sha256(guard.path.read_bytes()).hexdigest(),
            "engine_config_sha256": _sha(engine.ccxt_conf), "engine_execution_sha256": _sha({"mode": engine.mode,
                 "market_type": engine.market_type, "leverage": engine.leverage, "position_side": engine.position_side}),
            "environment_sha256": _sha({key: policy.environ.get(key) for key in _ENV_KEYS}),
            "database_location_sha256": _sha(database.query("PRAGMA database_list")), "trade_table": table,
            "candidate": candidate_identity, "opening_inputs": stamp, "scope": scope, "runtime": runtime}, actual


def capture_native_prepare_identity(engine, record_id, amount, price, *, post_only=False, entry_assessment=None):
    """Keep the original non-executable JSON interface; do not export a handle."""
    context = _capture_native_prepare_context(engine, record_id, amount, price, post_only=post_only, entry_assessment=entry_assessment)
    return json.loads(_PREPARED[context][1])


def assert_native_prepare_context_current(engine, context):
    """Pre-intent local consistency in the original owned view, no SDK calls.

    JSON, copies and freshly constructed lookalikes are not live invocation
    handles. Success is None, never funding, collector ownership or permission.
    """
    try:
        if type(context) is not _NativePrepareContext or context not in _PREPARED:
            _fail()
        owner, _, check = _PREPARED[context][:3]
        if engine is not owner:
            _fail()
        check()
    except Exception:
        _fail()


def _assert_native_prepare_owner(chan, context):
    """Check the original live owner before any writer transaction/SQL."""
    if type(context) is not _NativePrepareContext or context not in _PREPARED:
        _fail()
    entry = _PREPARED[context]
    if len(entry) not in {4, 5} or entry[0].chan_db is not chan:
        _fail()
    entry[3](owned=None)


def _capture_native_prepare_context(engine, record_id, amount, price, *, post_only=False, entry_assessment=None):
    """Read actual record/config/input/candidate; prepare via the original API.

    No SDK replacement, settings mutation, default sender hook, order journal
    write or synthetic proof repair. A later source pipeline owns failures and
    must independently consume its own fresh observations inside the real CAS.
    """
    try:
        from .CCXTTradeEngine import CCCXTTradeEngine
        from .Script.OpeningInputs import COpeningInputs
        from .SafetyPolicy import TradingSafetyPolicy
        from .db_util import CChanDB
        from .NativeOrderBoundary import _same_database
        if (type(engine) is not CCCXTTradeEngine or type(engine.opening_inputs) is not COpeningInputs
                or type(engine.safety_policy) is not TradingSafetyPolicy or type(engine.chan_db) is not CChanDB
                or engine.dry_run is not False or engine.market_type != "swap" or engine.mode not in {"testnet", "live"}
                or type(record_id) is not int or record_id <= 0 or type(post_only) is not bool
                or type(amount) not in (int, float) or not math.isfinite(amount) or amount <= 0
                or (price is not None and (type(price) not in (int, float) or not math.isfinite(price) or price <= 0))
                or (post_only and price is None)):
            _fail()
        chan, guard, policy, exchange = engine.chan_db, engine.opening_inputs, engine.safety_policy, engine.exchange
        if exchange is None:
            _fail()
        database, connection, table = chan.db, chan.db.conn, chan.table
        _same_database(chan, database, connection, table, owned=False)
        provided = {"record_id": record_id, "amount": amount, "price": price, "post_only": post_only, "entry_assessment": entry_assessment}
        frozen_request, start = canonical_bytes(provided), utc_now_ms()
        if type(start) is not int or not 0 <= start < 2**63:
            _fail()
        implementation = _implementation()
        original_clock = guard.now_ms

        def owners(*, owned=False):
            _same_database(chan, database, connection, table,
                           owned=connection.in_transaction if owned is None else owned)
            if (engine.chan_db is not chan or engine.exchange is not exchange or engine.opening_inputs is not guard
                    or engine.safety_policy is not policy or guard.now_ms is not original_clock):
                _fail()

        def current(*, check_implementation=True, owned=False, expected_record=None):
            owners(owned=owned)
            if (canonical_bytes(provided) != frozen_request or (check_implementation and _implementation() != implementation)):
                _fail()
            owners(owned=owned)
            runtime = _selected_runtime(engine, guard, policy)
            owners(owned=owned)
            return _local_prepare_view(engine, guard, policy, chan, database, table, record_id, price, runtime,
                lambda: owners(owned=owned), signal_record=signal_record if expected_record is not None else None,
                expected_record=expected_record)

        first, record = current()
        signal_record = json.loads(canonical_bytes(record))
        assessment = None
        if record.get("deployment_id") or record.get("model_version"):
            from .Script.Deployment import verify_entry_assessment
            assessment = verify_entry_assessment(record, entry_assessment, price, engine)
        elif entry_assessment is not None:
            _fail()
        quantity, order_price, contract = engine.prepare_order(record["stock_code"], amount, price, record=record, post_only=post_only)
        second, _ = current()
        stable = _stable_local_view
        if (canonical_bytes(stable(first)) != canonical_bytes(stable(second)) or contract["schema"] != "chan-ccxt-order-v3"
                or contract["post_only"] is not post_only or contract["reduce_only"] is not False):
            _fail()
        if assessment is not None:
            if canonical_bytes(verify_entry_assessment(record, entry_assessment, price, engine)) != canonical_bytes(assessment):
                _fail()
        finished = utc_now_ms()
        last, _ = current()
        if canonical_bytes(stable(second)) != canonical_bytes(stable(last)):
            _fail()
        payload = {**last, "request": {k: provided[k] for k in ("record_id", "amount", "price", "post_only")},
                   "quantity": quantity, "price": order_price, "order_contract": contract,
                   "entry_assessment_sha256": None if assessment is None else _sha(assessment), "implementation_sha256": implementation,
                   "started_ms": start, "finished_ms": max(finished, last["opening_inputs"]["checked_at_ms"]),
                   "coverage": "actual_local_prepare_identity_only",
                   "economics_complete": False, "native_admission_verified": False}
        if (type(start) is not int or type(finished) is not int or type(payload["finished_ms"]) is not int
                or not 0 <= start <= second["opening_inputs"]["checked_at_ms"] <= finished <= payload["finished_ms"] < 2**63):
            _fail()
        result = json.loads(canonical_bytes({"schema": SCHEMA, "payload": payload, "payload_sha256": _sha(payload)}))
        _same_database(chan, database, connection, table, owned=False)
        if canonical_bytes(provided) != frozen_request or _implementation() != implementation:
            _fail()
        owners()
        final, _ = current(check_implementation=False)
        if canonical_bytes(stable(final)) != canonical_bytes(stable(last)):
            _fail()
        owners()
        client_binding = _client_binding(exchange)
        owners()

        def recheck(*, expected_record=None):
            owners(owned=True)
            begin = utc_now_ms()
            if type(begin) is not int or not result["payload"]["finished_ms"] <= begin < 2**63:
                _fail()
            observed, actual = current(owned=True, expected_record=expected_record)
            if canonical_bytes(stable(observed)) != canonical_bytes(stable(last)) or _client_binding(exchange) != client_binding:
                _fail()
            if assessment is not None and canonical_bytes(verify_entry_assessment(actual, entry_assessment, price, engine)) != canonical_bytes(assessment):
                _fail()
            chan.assert_account_new_risk_allowed(result["payload"]["order_contract"]["account_context"])
            owners(owned=True)
            end = utc_now_ms()
            if type(end) is not int or not begin <= observed["opening_inputs"]["checked_at_ms"] <= end < 2**63:
                _fail()
            # Reuse the same local reader after code/entry checks. It performs
            # no prepare or profile lookup, and does not advance order state.
            observed, _ = current(owned=True, expected_record=expected_record)
            if (canonical_bytes(stable(observed)) != canonical_bytes(stable(last)) or _client_binding(exchange) != client_binding
                    or not end <= observed["opening_inputs"]["checked_at_ms"] < 2**63):
                _fail()
            owners(owned=True)

        context = _NativePrepareContext()
        _PREPARED[context] = (engine, canonical_bytes(result), recheck, owners)
        return context
    except Exception:
        _fail()
