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
          "Trade/Script/OpeningInputs.py", "Trade/Script/Deployment.py", "Trade/db_util.py", "Trade/OrderAudit.py")
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
        node = next(n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name)
    return node


def _selected_runtime(engine, guard, policy):
    """Fresh compile only, never exec/import a second copy of trading code."""
    from . import CCXTTradeEngine as engine_module
    from . import SafetyPolicy as safety_module
    from .Script import Deployment as deployment_module
    selected = []
    for owner, module, cls, names in (
        (engine, "Trade.CCXTTradeEngine", "CCCXTTradeEngine", ("prepare_order", "get_exchange", "check_open_inputs", "_market_contract",
             "_execution_settings", "_observe_account", "_assert_account_context")),
        (guard, "Trade.Script.OpeningInputs", "COpeningInputs", ("check", "assert_current", "snapshot")),
        (policy, "Trade.SafetyPolicy", "TradingSafetyPolicy", ("assert_order_allowed",)),
    ):
        for name in names:
            method = getattr(owner, name)
            if getattr(method, "__self__", None) is not owner:
                _fail()
            selected.append((module, cls+"."+name, method.__func__))
    for name in ("env", "scope"):
        descriptor = vars(type(guard))[name]
        if type(descriptor) is not property or descriptor.fset is not None or descriptor.fdel is not None:
            _fail()
        selected.append(("Trade.Script.OpeningInputs", "COpeningInputs."+name, descriptor.fget))
    limits = vars(type(engine))["_check_limits"]
    if type(limits) is not staticmethod or getattr(engine, "_check_limits") is not limits.__func__:
        _fail()
    selected.append(("Trade.CCXTTradeEngine", "CCCXTTradeEngine._check_limits", limits.__func__))
    selected.extend(("Trade.CCXTTradeEngine", name, getattr(engine_module, name))
                    for name in ("_quantity", "_float_exact", "_contract_id"))
    selected.extend(("Trade.SafetyPolicy", name, getattr(safety_module, name))
                    for name in ("build_trading_safety_policy", "_load_candidate_receipt"))
    selected.append(("Trade.AccountIdentity", "observe_account_context", engine_module.observe_account_context))
    selected.append(("Trade.Script.Deployment", "verify_entry_assessment", deployment_module.verify_entry_assessment))
    modules, result = {}, {}
    for module, qualname, function in selected:
        path = _ROOT/(module.replace(".", "/")+".py")
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
        result[module+":"+qualname] = {"source_sha256": digest, "qualname": qualname,
                                      "defaults_sha256": _sha({"positional": defaults, "keywords": keywords})}
    return {"coverage": "selected_prepare_callables", "python": platform.python_version(),
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
        "verify", "isSandboxModeEnabled", "proxies", "proxyUrl", "httpProxy", "httpsProxy", "socksProxy")})


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


def _capture_native_prepare_context(engine, record_id, amount, price, *, post_only=False, entry_assessment=None):
    """Read actual record/config/input/candidate; prepare via the original API.

    No SDK replacement, settings mutation, default sender hook, order journal
    write or synthetic proof repair. A later source pipeline owns failures and
    must independently consume its own fresh observations inside the real CAS.
    """
    try:
        from .CCXTTradeEngine import CCCXTTradeEngine
        from .Script.OpeningInputs import COpeningInputs
        from .SafetyPolicy import TradingSafetyPolicy, build_trading_safety_policy
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
            _same_database(chan, database, connection, table, owned=owned)
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
            env = guard.env
            if (engine.mode != env.ccxt_conf.get("mode") or engine.dry_run is not False or engine.market_type != "swap"
                    or canonical_bytes(engine.ccxt_conf) != canonical_bytes(env.ccxt_conf)):
                _fail()
            fresh_policy = build_trading_safety_policy(engine.ccxt_conf, env.get_section("trade"), policy.environ)
            if fresh_policy.mode != policy.mode or fresh_policy.strategy_receipt != policy.strategy_receipt:
                _fail()
            policy.assert_order_allowed()
            candidate = fresh_policy.strategy_receipt
            candidate_raw = Path(candidate["path"]).read_bytes()
            candidate_identity = {**candidate, "file_sha256": hashlib.sha256(candidate_raw).hexdigest()}
            actual = chan.get_record(record_id)
            if expected_record is not None:
                # Only the original transition writer supplies its independently
                # verified, exact full after-row. No arbitrary own-row exclusion.
                if canonical_bytes(actual) != canonical_bytes(expected_record):
                    _fail()
                actual = signal_record
            if (actual is None or actual["status"] != "signal" or actual["watching"] != 1 or actual["is_open"] != 0
                    or actual["open_attempt"] != 0 or actual["open_client_order_id"] is not None):
                _fail()
            stamp = guard.check(actual, engine=engine, price=price)
            scope = guard.scope
            if _sha(scope) != stamp["scope_sha256"]:
                _fail()
            return {"record_sha256": _sha(actual), "config_sha256": hashlib.sha256(guard.path.read_bytes()).hexdigest(),
                    "engine_config_sha256": _sha(engine.ccxt_conf), "engine_execution_sha256": _sha({"mode": engine.mode,
                         "market_type": engine.market_type, "leverage": engine.leverage, "position_side": engine.position_side}),
                    "environment_sha256": _sha({key: policy.environ.get(key) for key in _ENV_KEYS}),
                    "database_location_sha256": _sha(database.query("PRAGMA database_list")), "trade_table": table,
                    "candidate": candidate_identity, "opening_inputs": stamp, "scope": scope, "runtime": runtime}, actual

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
        stable = lambda value: {**value, "opening_inputs": {k: v for k, v in value["opening_inputs"].items() if k != "checked_at_ms"}}
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
        _PREPARED[context] = (engine, canonical_bytes(result), recheck)
        return context
    except Exception:
        _fail()
