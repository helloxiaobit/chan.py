"""Own native instrument collection against the original Engine's cache."""
import copy
import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import ccxt
import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_instrument_evidence import NOW, raw_instrument


def current_api():
    assert importlib.util.find_spec("Trade.NativeInstrumentCurrent") is not None, "original Engine native instrument binding is missing"
    from Trade import NativeInstrumentCurrent
    return NativeInstrumentCurrent


def test_native_instrument_current_api_exists():
    assert callable(current_api().collect_native_instruments_for_engine)


@pytest.fixture(params=[(name, mode) for name in ("binance", "binanceusdm", "okx") for mode in ("testnet", "live")])
def current_instruments(request, monkeypatch, store):
    from Trade.CCXTTradeEngine import CCCXTTradeEngine
    from Trade import NativeInstrumentEvidence
    api = current_api()
    name, mode = request.param
    client = getattr(ccxt, name)()
    if mode == "testnet":
        client.set_sandbox_mode(True)
    rows = [raw_instrument(name, base) for base in ("TEST", "ALT")]
    client.set_markets([client.parse_market(row) for row in rows])
    db, _ = store
    engine = CCCXTTradeEngine.__new__(CCCXTTradeEngine)
    engine.market_type, engine.dry_run, engine.mode = "swap", False, mode
    engine.exchange, engine.chan_db = client, db
    calls, clock = [], {"now": NOW}
    def public(options):
        assert not db.db.conn.in_transaction
        calls.append(copy.deepcopy(options))
        clock["now"] += 10
        return ({"code": "0", "data": copy.deepcopy(rows)} if name == "okx" else {"symbols": copy.deepcopy(rows)})
    def no_io(*args, **kwargs):
        raise AssertionError("no actual HTTP, private I/O, cache reload, mutation or order send")
    monkeypatch.setattr(ccxt.Exchange, "fetch", no_io)
    for method in ("request", "fetch_markets", "fetch_currencies", "set_markets", "create_order"):
        monkeypatch.setattr(client, method, no_io)
    method = "publicGetPublicInstruments" if name == "okx" else "fapiPublicGetExchangeInfo"
    monkeypatch.setattr(client, method, public)
    for module in (api, NativeInstrumentEvidence):
        monkeypatch.setattr(module, "utc_now_ms", lambda: clock["now"])
    return {"api": api, "engine": engine, "client": client, "db": db, "rows": rows,
            "codes": ["TEST/USDT:USDT", "ALT/USDT:USDT"], "calls": calls, "clock": clock,
            "public": public, "method": method, "budgets": {"max_age_ms": 10, "max_observation_span_ms": 10}}


def collect(case, **budgets):
    return case["api"].collect_native_instruments_for_engine(case["engine"], case["codes"], **(case["budgets"] | budgets))


def test_original_engine_uses_identical_native_metadata_without_cache_or_database_writes(current_instruments):
    case = current_instruments
    client, conn = case["client"], case["db"].db.conn
    cache = canonical_bytes({"markets": client.markets, "by_id": client.markets_by_id, "options": client.options})
    changes = conn.total_changes
    document = collect(case)
    assert document["schema"] == "chan-native-instrument-evidence-v1"
    assert document["payload"]["codes"] == sorted(case["codes"])
    assert document["payload"]["economics_complete"] is False
    assert document["payload"]["native_admission_verified"] is False
    for observed in document["payload"]["observations"]:
        definition, market = case["engine"]._market_contract(observed["market"]["symbol"])
        assert canonical_bytes(definition) == canonical_bytes(observed["market"])
        assert market["active"] is observed["active"]
    assert canonical_bytes({"markets": client.markets, "by_id": client.markets_by_id, "options": client.options}) == cache
    assert conn.total_changes == changes and not conn.in_transaction
    assert case["calls"] == ([{"instType": "SWAP"}] if client.id == "okx" else [{}])


@pytest.mark.parametrize("field", ["contract_size", "price_tick", "amount_min", "price_max", "cost_min", "active", "state"])
def test_stale_engine_cache_is_rejected_instead_of_refreshed(current_instruments, field):
    case = current_instruments
    market = case["client"].markets[case["codes"][0]]
    if field == "contract_size":
        market["contractSize"] = 99
    elif field == "price_tick":
        market["precision"]["price"] = 99
    elif field == "active":
        market["active"] = False
    elif field == "state":
        market["info"]["state" if case["client"].id == "okx" else "status"] = "not-current"
    else:
        kind, bound = field.split("_")
        market["limits"][kind][bound] = 99
    with pytest.raises(CChanException):
        collect(case)
    assert len(case["calls"]) == 1


@pytest.mark.parametrize("field", ["max_age_ms", "max_observation_span_ms"])
@pytest.mark.parametrize("bad", [None, True, -1, 1.0, "10", 2**63])
def test_invalid_explicit_budget_never_starts_source_io(current_instruments, field, bad):
    case = current_instruments
    with pytest.raises(CChanException):
        collect(case, **{field: bad})
    assert case["calls"] == []


@pytest.mark.parametrize("field", ["max_age_ms", "max_observation_span_ms"])
def test_budget_exact_boundary_passes_but_one_ms_short_rejects(current_instruments, field):
    case = current_instruments
    with pytest.raises(CChanException):
        collect(case, **{field: 9})
    assert len(case["calls"]) == 1


@pytest.mark.parametrize("bad", ["dry_run", "dry_run_alias", "spot", "future", "mode", "engine", "exchange",
                                  "database", "mysql", "markets", "by_id", "target", "active_type"])
def test_missing_original_owner_or_initialized_cache_rejects_before_io(current_instruments, bad):
    case = current_instruments
    engine, client = case["engine"], case["client"]
    if bad == "dry_run":
        engine.dry_run = True
    elif bad == "dry_run_alias":
        engine.dry_run = 0
    elif bad in {"spot", "future"}:
        engine.market_type = bad
    elif bad == "mode":
        engine.mode = "dry_run"
    elif bad == "engine":
        case["engine"] = object()
    elif bad == "exchange":
        engine.exchange = None
    elif bad == "database":
        engine.chan_db = None
    elif bad == "mysql":
        engine.chan_db.db_type = "mysql"
    elif bad == "markets":
        client.markets = {}
    elif bad == "by_id":
        client.markets_by_id = {}
    elif bad == "target":
        del client.markets[case["codes"][0]]
    else:
        client.markets[case["codes"][0]]["active"] = 1
    with pytest.raises(CChanException):
        collect(case)
    assert case["calls"] == []


@pytest.mark.parametrize("method", ["get_exchange", "_market_contract", "load_markets", "market"])
def test_instance_method_replacements_never_execute(current_instruments, monkeypatch, method):
    case, invoked = current_instruments, []
    owner = case["engine"] if method in {"get_exchange", "_market_contract"} else case["client"]
    def replacement(*args, **kwargs):
        invoked.append(1)
        raise RuntimeError("private or mutating replacement must not execute")
    monkeypatch.setattr(owner, method, replacement)
    with pytest.raises(CChanException):
        collect(case)
    assert case["calls"] == [] and invoked == []


def test_callers_transaction_never_contains_public_io(current_instruments):
    case = current_instruments
    with case["db"].db.transaction():
        with pytest.raises(CChanException):
            collect(case)
        assert case["calls"] == []


@pytest.mark.parametrize("change", ["cache", "other_market", "by_id", "symbols", "ids", "options", "precision_mode",
                                    "mode", "dry_run", "market_type", "exchange", "owner", "backend", "table",
                                    "location", "transaction", "target_pool", "method", "route", "sdk"])
def test_changes_during_public_get_cannot_publish_current_binding(current_instruments, monkeypatch, change):
    case = current_instruments
    client, engine, db = case["client"], case["engine"], case["db"]
    def mutate(options):
        response = case["public"](options)
        if change in {"cache", "other_market"}:
            target = case["codes"][0 if change == "cache" else 1]
            client.markets[target]["contractSize"] = 99
        elif change == "by_id":
            client.markets_by_id = {"different": []}
        elif change in {"symbols", "ids"}:
            getattr(client, change).append("NEW")
        elif change == "options":
            client.options["defaultType"] = "future"
        elif change == "precision_mode":
            client.precisionMode = ccxt.DECIMAL_PLACES
        elif change == "mode":
            engine.mode = "live" if engine.mode == "testnet" else "testnet"
        elif change == "dry_run":
            engine.dry_run = True
        elif change == "market_type":
            engine.market_type = "spot"
        elif change == "exchange":
            engine.exchange = getattr(ccxt, client.id)()
        elif change == "owner":
            engine.chan_db = object()
        elif change == "backend":
            db.db = object()
        elif change == "table":
            db.table = "unrelated_table"
        elif change == "location":
            db.db.conn.execute("ATTACH ':memory:' AS unrelated")
        elif change == "transaction":
            db.db.conn.execute("BEGIN")
        elif change == "target_pool":
            case["codes"].pop()
        elif change == "method":
            monkeypatch.setattr(client, "load_markets", lambda: None)
        elif change == "route":
            client.urls["api"]["rest" if client.id == "okx" else "fapiPublic"] = "https://changed.invalid"
        else:
            monkeypatch.setattr(ccxt, "__version__", "not-original")
        return response
    backend = db.db
    changes = backend.conn.total_changes
    monkeypatch.setattr(client, case["method"], mutate)
    try:
        with pytest.raises(CChanException):
            collect(case)
        assert len(case["calls"]) == 1 and backend.conn.total_changes == changes
    finally:
        db.db = backend
        if backend.conn.in_transaction:
            backend.conn.rollback()


def test_swapped_database_connection_is_never_queried_or_written(current_instruments, monkeypatch):
    case = current_instruments
    backend = case["db"].db
    original, replacement = backend.conn, sqlite3.connect(":memory:")
    queries = []
    replacement.set_trace_callback(queries.append)
    def mutate(options):
        response = case["public"](options)
        backend.conn = replacement
        return response
    monkeypatch.setattr(case["client"], case["method"], mutate)
    try:
        with pytest.raises(CChanException):
            collect(case)
        assert queries == [] and replacement.total_changes == 0
    finally:
        backend.conn = original
        replacement.close()


def test_current_binding_does_not_age_from_the_later_reader_time(current_instruments, monkeypatch):
    case = current_instruments
    source = case["api"].source
    original = source.verify_native_instrument_evidence
    def slow_reader(document):
        result = original(document)
        case["clock"]["now"] += 1
        return result
    monkeypatch.setattr(source, "verify_native_instrument_evidence", slow_reader)
    with pytest.raises(CChanException):
        collect(case)
    assert len(case["calls"]) == 1


def test_age_includes_the_final_database_identity_check(current_instruments, monkeypatch):
    case = current_instruments
    query = case["db"].db.query
    def delayed(sql, *args, **kwargs):
        result = query(sql, *args, **kwargs)
        if case["calls"] and sql == "PRAGMA database_list":
            case["clock"]["now"] += 1
        return result
    monkeypatch.setattr(case["db"].db, "query", delayed)
    with pytest.raises(CChanException):
        collect(case)


def test_explicit_age_and_capture_span_are_independent_budgets(current_instruments, monkeypatch):
    case = current_instruments
    query = case["db"].db.query
    def delayed(sql, *args, **kwargs):
        result = query(sql, *args, **kwargs)
        if case["calls"] and sql == "PRAGMA database_list":
            case["clock"]["now"] += 1
        return result
    monkeypatch.setattr(case["db"].db, "query", delayed)
    document = collect(case, max_age_ms=11, max_observation_span_ms=10)
    assert document["payload"]["finished_ms"]-document["payload"]["started_ms"] == 10
    assert case["clock"]["now"]-document["payload"]["started_ms"] == 11


@pytest.mark.parametrize("bad", [True, NOW-1, float(NOW+10), 2**63])
def test_final_use_clock_must_be_ordered_exact_integer_ms(current_instruments, monkeypatch, bad):
    case = current_instruments
    monkeypatch.setattr(case["api"], "utc_now_ms", lambda: bad if case["calls"] else NOW)
    with pytest.raises(CChanException):
        collect(case)


@pytest.mark.parametrize("filename", ["NativeInstrumentCurrent.py", "CCXTTradeEngine.py"])
def test_local_consumer_or_original_engine_file_drift_rejects(current_instruments, monkeypatch, filename):
    case = current_instruments
    original = Path.read_bytes
    def changed(path):
        content = original(path)
        return content+b"\n# changed" if case["calls"] and path.name == filename else content
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(CChanException):
        collect(case)
    assert len(case["calls"]) == 1


def test_cache_outside_the_selected_target_pool_is_not_silently_changed(current_instruments, monkeypatch):
    case = current_instruments
    client = case["client"]
    rows = case["rows"]+[raw_instrument(client.id, "OTHER")]
    ccxt.Exchange.set_markets(client, [client.parse_market(row) for row in rows])
    def mutate(options):
        response = case["public"](options)
        client.markets["OTHER/USDT:USDT"]["active"] = False
        return response
    monkeypatch.setattr(client, case["method"], mutate)
    with pytest.raises(CChanException):
        collect(case)
    assert len(case["calls"]) == 1


def test_zero_budgets_have_no_implicit_grace(current_instruments, monkeypatch):
    case = current_instruments
    def zero_span(options):
        response = case["public"](options)
        case["clock"]["now"] -= 10
        return response
    monkeypatch.setattr(case["client"], case["method"], zero_span)
    document = collect(case, max_age_ms=0, max_observation_span_ms=0)
    assert document["payload"]["started_ms"] == document["payload"]["finished_ms"] == NOW
    monkeypatch.setattr(case["client"], case["method"], case["public"])
    with pytest.raises(CChanException):
        collect(case, max_age_ms=0, max_observation_span_ms=0)


def test_matching_inactive_state_is_not_promoted_into_permission(current_instruments):
    case = current_instruments
    row = case["rows"][0]
    row["state" if case["client"].id == "okx" else "status"] = "suspend" if case["client"].id == "okx" else "BREAK"
    ccxt.Exchange.set_markets(case["client"], [case["client"].parse_market(row) for row in case["rows"]])
    document = collect(case)
    assert any(row["active"] is False for row in document["payload"]["observations"])
    assert document["payload"]["native_admission_verified"] is False


def test_native_failure_is_fixed_redacted_and_never_retried(current_instruments, monkeypatch):
    case = current_instruments
    def fail(options):
        case["calls"].append(options)
        raise RuntimeError("PRIVATE_SOURCE_SECRET_DO_NOT_COPY")
    monkeypatch.setattr(case["client"], case["method"], fail)
    with pytest.raises(CChanException) as caught:
        collect(case)
    assert "PRIVATE_SOURCE_SECRET" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert len(case["calls"]) == 1


def test_core_import_does_not_need_sdk_or_actual_configuration():
    script = """
import importlib.abc, sys
attempted = []
class NoOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ccxt', 'Config', 'numpy', 'pandas', 'torch', 'xgboost', 'lightgbm', 'matplotlib'}:
            attempted.append(fullname)
            raise ImportError('not installed')
sys.meta_path.insert(0, NoOptional())
from Trade.NativeInstrumentCurrent import collect_native_instruments_for_engine
assert callable(collect_native_instruments_for_engine)
assert not attempted, attempted
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stderr == b""
