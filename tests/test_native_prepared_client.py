"""Actual cold SDK construction with fake native transport, never send permission."""
import importlib.util
import copy
import json
import subprocess
import sys

import ccxt
import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.NativeOrderTransition import read_native_order_transition
from .native_order_preparation_case import native_order_case
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_prepared_intent import acquire


def client_api():
    assert importlib.util.find_spec("Trade.NativePreparedClient") is not None, "source-owned cold SDK startup is missing"
    from Trade.NativePreparedClient import initialize_native_prepared_client
    return initialize_native_prepared_client


def test_cold_native_client_api_exists():
    assert callable(client_api())


def cold_case(store, tmp_path, monkeypatch, venue, mode="one_way", side=True):
    from Trade import NativePreparedIntent
    case = native_order_case(*store, tmp_path, monkeypatch, venue, mode=mode, side=side)
    monkeypatch.setattr(NativePreparedIntent, "utc_now_ms", lambda: case["clock"]["now"])
    transport = ({("fapiPublic", "exchangeInfo"): "fapiPublicGetExchangeInfo",
                  ("fapiPrivate", "positionSide/dual"): "fapiPrivateGetPositionSideDual",
                  ("fapiPrivate", "leverageBracket"): "fapiPrivateGetLeverageBracket",
                  ("fapiPrivate", "symbolConfig"): "fapiPrivateGetSymbolConfig",
                  ("fapiPrivateV3", "balance"): "fapiPrivateV3GetBalance",
                  ("fapiPrivateV3", "account"): "fapiPrivateV3GetAccount",
                  ("fapiPrivateV3", "positionRisk"): "fapiPrivateV3GetPositionRisk",
                  ("fapiPrivate", "accountConfig"): "fapiPrivateGetAccountConfig",
                  ("fapiPrivate", "multiAssetsMargin"): "fapiPrivateGetMultiAssetsMargin",
                  ("fapiPrivate", "openOrders"): "fapiPrivateGetOpenOrders",
                  ("fapiPrivate", "openAlgoOrders"): "fapiPrivateGetOpenAlgoOrders",
                  ("fapiPrivate", "userTrades"): "fapiPrivateGetUserTrades",
                  ("fapiPrivate", "income"): "fapiPrivateGetIncome",
                  ("fapiPublic", "premiumIndex"): "fapiPublicGetPremiumIndex",
                  ("fapiPublic", "ticker/bookTicker"): "fapiPublicGetTickerBookTicker"} if venue == "binance" else
                 {("public", "public/instruments"): "publicGetPublicInstruments",
                  ("private", "account/config"): "privateGetAccountConfig",
                  ("private", "account/leverage-info"): "privateGetAccountLeverageInfo",
                  ("private", "account/balance"): "privateGetAccountBalance",
                  ("private", "account/positions"): "privateGetAccountPositions",
                  ("private", "trade/orders-pending"): "privateGetTradeOrdersPending",
                  ("private", "trade/orders-algo-pending"): "privateGetTradeOrdersAlgoPending",
                  ("private", "trade/fills"): "privateGetTradeFills",
                  ("private", "trade/fills-history"): "privateGetTradeFillsHistory",
                  ("private", "account/bills-archive"): "privateGetAccountBillsArchive",
                  ("public", "public/mark-price"): "publicGetPublicMarkPrice",
                  ("public", "market/books"): "publicGetMarketBooks"})
    readers = {key: getattr(case["client"], name) for key, name in transport.items()}
    calls = []
    def request(client, path, api="public", method="GET", params=None, *args, **kwargs):
        assert not case["db"].db.conn.in_transaction, "cold startup GET under writer lock"
        api = api[0] if type(api) is list and len(api) == 1 else api
        assert method == "GET" and (api, path) in readers, "unexpected product, endpoint or write"
        calls.append((api, path, copy.deepcopy(params)))
        return readers[(api, path)]({} if params is None else params)
    monkeypatch.setattr(getattr(ccxt, venue), "request", request)
    case["trade"].exchange = None
    case["cold_calls"] = calls
    case["cold_readers"] = readers
    case["monkeypatch"] = monkeypatch
    return case


def initialize(case, **changes):
    method = client_api()
    monkey_clock = lambda: case["clock"]["now"]
    from Trade import NativePreparedClient
    case["monkeypatch"].setattr(NativePreparedClient, "utc_now_ms", monkey_clock)
    return method(case["trade"], case["key"], **({"instrument_max_age_ms": 2000, "instrument_max_observation_span_ms": 2000} | changes))


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mode,side", [(m, s) for m in ("one_way", "hedged") for s in (True, False)])
def test_real_cold_sdk_bootstrap_and_restart_consume_original_sources_not_a_transferred_cache(store, tmp_path, monkeypatch, venue, mode, side):
    from Trade.NativePreparedIntent import assert_native_prepared_intent_current
    case = cold_case(store, tmp_path, monkeypatch, venue, mode, side)
    before, changes = case["db"].get_record(case["key"]), case["db"].db.conn.total_changes
    assert initialize(case) is None
    client = case["trade"].exchange
    assert type(client) is getattr(ccxt, venue) and client is not case["client"]
    assert client.apiKey == case["trade"].ccxt_conf["api_key"]
    assert set(client.markets) == {"TEST/USDT:USDT", "ALT/USDT:USDT"}
    assert case["db"].get_record(case["key"]) == before and case["db"].db.conn.total_changes == changes
    assert acquire(case)
    original = read_native_order_transition(case["db"], case["key"])
    record = case["db"].get_record(case["key"])
    case["trade"].exchange = None
    changes = case["db"].db.conn.total_changes
    assert initialize(case) is None
    assert case["trade"].exchange is not client and type(case["trade"].exchange) is getattr(ccxt, venue)
    with case["db"].db.transaction():
        assert assert_native_prepared_intent_current(case["trade"], case["key"]) is None
    assert read_native_order_transition(case["db"], case["key"]) == original
    assert case["db"].get_record(case["key"]) == record and case["db"].db.conn.total_changes == changes
    assert canonical_bytes(original).find(b'"apiKey"') == -1
    with pytest.raises(CChanException):
        case["db"].claim_order_submission(case["key"], "open")


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["record", "candidate", "client"])
def test_final_cold_clock_cannot_leave_a_late_local_change_outside_the_original_view(store, tmp_path, monkeypatch, venue, damage):
    from pathlib import Path
    from Trade import NativePreparedClient
    case = cold_case(store, tmp_path, monkeypatch, venue)
    ticks = []
    def late():
        ticks.append(1)
        if len(ticks) == 2:
            if damage == "record":
                case["db"].db.execute(f"UPDATE {case['db'].table} SET unwatch_reason='late-cold-startup' WHERE id=?", (case["key"],))
            elif damage == "candidate":
                path = Path(case["trade"].safety_policy.strategy_receipt["path"])
                path.write_bytes(path.read_bytes()+b"\n ")
            else:
                case["trade"].exchange.secret = "late-client-drift"
        return case["clock"]["now"]
    monkeypatch.setattr(NativePreparedClient, "utc_now_ms", late)
    before = case["db"].get_record(case["key"])
    with pytest.raises(CChanException):
        client_api()(case["trade"], case["key"], instrument_max_age_ms=2000, instrument_max_observation_span_ms=2000)
    assert len(ticks) >= 2 and case["trade"].exchange is None
    assert case["db"].get_record(case["key"])["open_attempt"] == before["open_attempt"]


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_fresh_python_process_rebuilds_sdk_and_original_l1_without_receiving_a_cache(store, tmp_path, monkeypatch, venue):
    case = cold_case(store, tmp_path, monkeypatch, venue)
    assert initialize(case) is None and acquire(case)
    original = read_native_order_transition(case["db"], case["key"])
    keys = ([('fapiPublic', 'exchangeInfo'), ('fapiPrivate', 'positionSide/dual'), ('fapiPrivate', 'leverageBracket'),
             ('fapiPrivate', 'symbolConfig'), ('fapiPrivateV3', 'balance')] if venue == 'binance' else
            [('public', 'public/instruments'), ('private', 'account/config'), ('private', 'account/leverage-info')])
    instrument = original["payload"]["root"]["preparation"]["identity"]["payload"]["order_contract"]["market"]["id"]
    packets = {api+':'+path: case["cold_readers"][(api,path)]({"instId": instrument} if path == 'account/leverage-info' else {})
               for api,path in keys}
    request = {"config": str(case["config"]), "db": store[1], "record_id": case["key"], "venue": venue,
               "now_ms": case["clock"]["now"], "packets": packets, "original": original}
    assert not {"markets", "options", "client_binding"} & set(request)
    script = r'''
import copy, importlib, json, sys
from contextlib import closing
from pathlib import Path
import ccxt
from Common.ChanException import CChanException
from Trade.CCXTTradeEngine import CCCXTTradeEngine
from Trade.db_util import CChanDB
from Trade.Script.OpeningInputs import COpeningInputs
from Trade.NativePreparedClient import initialize_native_prepared_client
from Trade.NativeOrderTransition import read_native_order_transition
from Trade.NativePreparedIntent import assert_native_prepared_intent_current
request = json.load(sys.stdin)
configuration = json.loads(Path(request['config']).read_bytes())
clock = {'now':request['now_ms']}
for name in ('AccountSources','AccountStore','ExecutionFacts','ExecutionStore','OrderAudit','db_util','NativeInstrumentEvidence',
             'NativeInstrumentCurrent','NativePreparation','NativeComponentCollector','NativePendingOrders','NativeBalanceReservations',
             'NativeMarketEvidence','NativeAdmission','NativeCurrentComponents','NativeAccountCheck','NativeAccountStore','AccountRiskStore',
             'NativeOrderBoundary','NativeOrderTransition','NativePreparedIntent','NativePreparedClient'):
    importlib.import_module('Trade.'+name).utc_now_ms = lambda: clock['now']
with closing(CChanDB(db_conf=request['db'])) as db:
    def native(client, path, api='public', method='GET', params=None, *a, **kw):
        api = api[0] if type(api) is list and len(api)==1 else api
        assert not db.db.conn.in_transaction and method == 'GET'
        key = api+':'+path
        assert key in request['packets'], 'non-allowlisted request'
        clock['now'] += 1
        return copy.deepcopy(request['packets'][key])
    getattr(ccxt, request['venue']).request = native
    ccxt.Exchange.fetch = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('real HTTP forbidden'))
    guard = COpeningInputs(request['config'], now_ms=lambda:clock['now'])
    engine = CCCXTTradeEngine(db, ccxt_conf=configuration['ccxt'], trade_conf=configuration['trade'],
                             environ={'CHANPY_ENABLE_TESTNET':'YES'}, push_msg=False, opening_inputs=guard)
    assert engine.exchange is None
    before, changes = db.get_record(request['record_id']), db.db.conn.total_changes
    assert initialize_native_prepared_client(engine, request['record_id'], instrument_max_age_ms=2000,
                                            instrument_max_observation_span_ms=2000) is None
    assert type(engine.exchange) is getattr(ccxt, request['venue'])
    with db.db.transaction():
        assert assert_native_prepared_intent_current(engine, request['record_id']) is None
    assert read_native_order_transition(db, request['record_id']) == request['original']
    assert db.db.conn.total_changes == changes and db.get_record(request['record_id']) == before
    try:
        db.claim_order_submission(request['record_id'], 'open')
    except CChanException:
        pass
    else:
        raise AssertionError('unfunded claim escaped')
print('fresh-process SDK rebuilt; original L1 unchanged; claim blocked')
'''
    result = subprocess.run([sys.executable, "-c", script], input=canonical_bytes(request), capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"fresh-process SDK rebuilt" in result.stdout
    assert read_native_order_transition(case["db"], case["key"]) == original


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["instrument", "account", "settings", "exception", "expired"])
def test_failed_restart_does_not_reprepare_reseal_or_release_original_intent(store, tmp_path, monkeypatch, venue, damage):
    case = cold_case(store, tmp_path, monkeypatch, venue)
    assert initialize(case) is None and acquire(case)
    original = read_native_order_transition(case["db"], case["key"])
    record = case["db"].get_record(case["key"])
    case["trade"].exchange = None
    if damage == "expired":
        case["clock"]["now"] += 2001
    else:
        key = (("fapiPublic", "exchangeInfo") if venue == "binance" else ("public", "public/instruments"))
        if damage == "settings":
            key = ("fapiPrivate", "symbolConfig") if venue == "binance" else ("private", "account/leverage-info")
        elif damage == "account":
            key = ("fapiPrivateV3", "balance") if venue == "binance" else ("private", "account/config")
        reader = case["cold_readers"][key]
        def changed(params):
            response = reader(params)
            if damage == "exception":
                raise RuntimeError('FAKE_PRIVATE_COLD_RESPONSE')
            rows = response['symbols' if venue == 'binance' else 'data'] if damage == 'instrument' or venue == 'okx' else response
            if damage == "instrument":
                if venue == "binance":
                    rows[0]['filters'][0]['tickSize'] = '.2'
                else:
                    rows[0]['tickSz'] = '.2'
            elif damage == "settings":
                rows[0]['leverage' if venue == 'binance' else 'lever'] = 4 if venue == 'binance' else '4'
            else:
                for row in rows:
                    row['accountAlias' if venue == 'binance' else 'uid'] = 'different-Futures-account' if venue == 'binance' else '98765432'
            return response
        case["cold_readers"][key] = changed
    calls = len(case["cold_calls"])
    with pytest.raises(CChanException) as error:
        initialize(case)
    assert 'FAKE_PRIVATE_COLD_RESPONSE' not in str(error.value)
    assert case["trade"].exchange is None
    assert case["db"].get_record(case["key"]) == record
    assert read_native_order_transition(case["db"], case["key"]) == original
    if damage == "expired":
        assert len(case["cold_calls"]) == calls


@pytest.mark.parametrize("field", ["instrument_max_age_ms", "instrument_max_observation_span_ms"])
@pytest.mark.parametrize("bad", [None, True, -1, "2000", 2000.5, 2**63])
def test_cold_budget_has_no_default_or_implicit_conversion_and_starts_no_session(store, tmp_path, monkeypatch, field, bad):
    case = cold_case(store, tmp_path, monkeypatch, 'binance')
    with pytest.raises(CChanException):
        initialize(case, **{field: bad})
    assert case["trade"].exchange is None and case["cold_calls"] == []


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_existing_sdk_is_not_refreshed_or_cleared_by_the_cold_entry(store, tmp_path, monkeypatch, venue):
    case = cold_case(store, tmp_path, monkeypatch, venue)
    client = case["client"]
    case["trade"].exchange = client
    before = canonical_bytes({"markets": client.markets, "options": client.options, "urls": client.urls})
    with pytest.raises(CChanException):
        initialize(case)
    assert case["trade"].exchange is client and case["cold_calls"] == []
    assert canonical_bytes({"markets": client.markets, "options": client.options, "urls": client.urls}) == before


@pytest.mark.parametrize("raw", [False, True])
def test_cold_entry_refuses_all_caller_transactions_before_new_sdk_or_get(store, tmp_path, monkeypatch, raw):
    case = cold_case(store, tmp_path, monkeypatch, 'binance')
    if raw:
        case["db"].db.conn.execute('BEGIN')
        try:
            with pytest.raises(CChanException):
                initialize(case)
        finally:
            case["db"].db.conn.rollback()
    else:
        with case["db"].db.transaction():
            with pytest.raises(CChanException):
                initialize(case)
    assert case["trade"].exchange is None and case["cold_calls"] == []


@pytest.mark.parametrize("field", ["client", "cache", "receipts", "passed", "expected"])
def test_cold_entry_does_not_accept_transferred_client_or_cache(store, tmp_path, monkeypatch, field):
    case = cold_case(store, tmp_path, monkeypatch, 'binance')
    with pytest.raises(TypeError):
        initialize(case, **{field: True})
    assert case["trade"].exchange is None and case["cold_calls"] == []


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_known_frozen_original_intent_does_not_create_a_new_sdk_session(store, tmp_path, monkeypatch, venue):
    case = cold_case(store, tmp_path, monkeypatch, venue)
    assert initialize(case) is None and acquire(case)
    case["trade"].exchange = None
    context = case["before"]["payload"]["account_context"]
    case["db"].reconcile_account(account_context=context, before_id='0'*64, after_id='1'*64, wallet_ids=[], execution_scan_ids=[])
    calls = list(case["cold_calls"])
    with pytest.raises(CChanException):
        initialize(case)
    assert case["trade"].exchange is None and case["cold_calls"] == calls


def test_cold_module_can_be_imported_without_sdk_config_or_optional_models():
    script = r'''
import importlib.abc, sys
class Absent(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ccxt','Config','yaml','numpy','pandas','xgboost','sklearn','torch','lightgbm','optuna'}:
            raise ImportError('optional dependency intentionally absent')
sys.meta_path.insert(0, Absent())
from Trade.NativePreparedClient import initialize_native_prepared_client
assert callable(initialize_native_prepared_client)
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors='replace')


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_late_sdk_binding_work_is_included_in_the_instrument_use_budget(store, tmp_path, monkeypatch, venue):
    from Trade import NativePreparation
    case = cold_case(store, tmp_path, monkeypatch, venue)
    original = NativePreparation._client_binding
    calls = []
    def delayed(client):
        result = original(client)
        calls.append(1)
        if len(calls) == 2:
            case["clock"]["now"] += 2001
        return result
    monkeypatch.setattr(NativePreparation, '_client_binding', delayed)
    with pytest.raises(CChanException):
        initialize(case)
    assert len(calls) >= 2 and case["trade"].exchange is None


def test_actual_cold_factory_is_part_of_the_original_prepared_implementation_identity(store, tmp_path, monkeypatch):
    case = cold_case(store, tmp_path, monkeypatch, 'binance')
    assert initialize(case) is None and acquire(case)
    binding = read_native_order_transition(case["db"], case["key"])["payload"]["root"]["preparation"]
    assert 'DataAPI/ccxt.py' in binding['implementation_sha256'], 'cold factory code is outside the prepared identity'


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("persisted", [False, True])
@pytest.mark.parametrize("damage", ["options", "markets", "public_route"])
def test_final_cold_clock_cannot_change_sdk_state_after_its_last_binding_check(store, tmp_path, monkeypatch, venue, persisted, damage):
    from Trade import NativePreparedClient
    case = cold_case(store, tmp_path, monkeypatch, venue)
    original = None
    if persisted:
        assert initialize(case) is None and acquire(case)
        original = read_native_order_transition(case["db"], case["key"])
        case["trade"].exchange = None
    ticks = []
    def late():
        ticks.append(1)
        if len(ticks) == 3:
            client = case["trade"].exchange
            if damage == "options":
                client.options["unobserved-final-clock-change"] = True
            elif damage == "markets":
                client.markets["TEST/USDT:USDT"]["active"] = False
            else:
                client.urls["api"]["fapiPublic" if venue == "binance" else "rest"] = "https://unapproved.invalid"
        return case["clock"]["now"]
    monkeypatch.setattr(NativePreparedClient, "utc_now_ms", late)
    before = case["db"].get_record(case["key"])
    with pytest.raises(CChanException):
        client_api()(case["trade"], case["key"], instrument_max_age_ms=2000, instrument_max_observation_span_ms=2000)
    assert len(ticks) >= 3 and case["trade"].exchange is None
    assert case["db"].get_record(case["key"]) == before
    if original is not None:
        assert read_native_order_transition(case["db"], case["key"]) == original


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_terminal_original_sdk_recheck_work_is_not_outside_the_use_time_budget(store, tmp_path, monkeypatch, venue):
    from Trade import NativePreparation, NativePreparedClient
    case = cold_case(store, tmp_path, monkeypatch, venue)
    original, calls, elapsed_ns = NativePreparation._client_binding, [], [0]
    monkeypatch.setattr(NativePreparedClient, "_monotonic_ns", lambda: elapsed_ns[0], raising=False)
    def delayed(client):
        result = original(client)
        calls.append(1)
        if len(calls) == 3:
            elapsed_ns[0] += 2_001_000_000
        return result
    monkeypatch.setattr(NativePreparation, "_client_binding", delayed)
    before = case["db"].get_record(case["key"])
    with pytest.raises(CChanException):
        initialize(case)
    assert len(calls) >= 3 and case["trade"].exchange is None
    assert case["db"].get_record(case["key"]) == before


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("excess_ns", [0, 1])
def test_terminal_elapsed_budget_keeps_the_exact_boundary_and_rounds_positive_nanoseconds_up(store, tmp_path, monkeypatch, venue, excess_ns):
    from Trade import NativePreparedClient
    case = cold_case(store, tmp_path, monkeypatch, venue)
    collector = NativePreparedClient.Instrument.source.collect_native_instrument_evidence
    source_start, samples = [], []
    def observed(*args, **kwargs):
        result = collector(*args, **kwargs)
        source_start.append(result["payload"]["started_ms"])
        return result
    def monotonic():
        samples.append(1)
        if len(samples) == 1:
            return 0
        remaining_ms = 2000-(case["clock"]["now"]-source_start[0])
        assert remaining_ms > 0
        return remaining_ms*1_000_000+excess_ns
    monkeypatch.setattr(NativePreparedClient.Instrument.source, "collect_native_instrument_evidence", observed)
    monkeypatch.setattr(NativePreparedClient, "_monotonic_ns", monotonic)
    before = case["db"].get_record(case["key"])
    if excess_ns:
        with pytest.raises(CChanException):
            initialize(case)
        assert case["trade"].exchange is None
    else:
        assert initialize(case) is None and type(case["trade"].exchange) is getattr(ccxt, venue)
    assert len(source_start) == 1 and len(samples) == 2
    assert case["db"].get_record(case["key"]) == before


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("samples", [(True, 1), (0, True), (1, 0)])
def test_terminal_elapsed_clock_requires_integer_samples_and_cannot_go_backwards(store, tmp_path, monkeypatch, venue, samples):
    from Trade import NativePreparedClient
    case = cold_case(store, tmp_path, monkeypatch, venue)
    values = iter(samples)
    monkeypatch.setattr(NativePreparedClient, "_monotonic_ns", lambda: next(values))
    before = case["db"].get_record(case["key"])
    with pytest.raises(CChanException):
        initialize(case)
    assert case["trade"].exchange is None and case["db"].get_record(case["key"]) == before
