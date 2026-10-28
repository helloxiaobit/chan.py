"""Original persisted sources and full SQLite history; no network/admission."""
import copy
import hashlib
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from decimal import Decimal

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.AccountIdentity import observe_account_context
from Trade.AccountSources import collect_account_snapshot, collect_wallet_scan
from Trade.ExecutionFacts import collect_execution_scan
from Trade.NativeMarketEvidence import collect_native_market_evidence
from Trade.OpenQuotaGen import CBenchPriceQuotaGen
from Trade.db_util import CChanDB
from .test_account_risk_freeze import persist
from .test_crypto_venue_parameters import venue_engine
from .test_crypto_order_contract import open_legacy_history
from .test_execution_facts import NativeSources
from .test_execution_store import store
from .test_m6_trade import make_signal
from .test_native_account_sources import AccountSourceIO
from .test_native_admission_freshness import NOW, admission_api, source_bundle


@pytest.fixture(autouse=True)
def explicit_path_environment(monkeypatch):
    from Config.EnvConfig import CEnv
    # The old DB constructor resolves paths through CEnv even with db_conf.
    # Supply only its pure path environment; do not read any actual YAML.
    env = CEnv.__new__(CEnv)
    env.conf = {}
    monkeypatch.setattr(CEnv, "_instance", env)


def persisted_case(db, tmp_path, monkeypatch, venue, *, legs="one_way", delayed_import=False):
    bundle = source_bundle(monkeypatch, venue, legs=legs, capture=False)
    clock, client = bundle["clock"], bundle["client"]
    for module in ("Trade.AccountRiskStore", "Trade.AccountStore", "Trade.ExecutionStore", "Trade.ExecutionFacts", "Trade.OrderAudit",
                   "Trade.db_util", "tests.test_crypto_order_contract"):
        monkeypatch.setattr(module+".utc_now_ms", lambda: clock["now"])
    trade = venue_engine(db, tmp_path, venue, "hedged" if legs == "hedged" else "one_way")
    if venue == "binance":
        trade.exchange.account_alias = "fake-Futures-A"
    first_market = trade.exchange.market("TEST/USDT:USDT")
    other_market = copy.deepcopy(first_market)
    other_market.update(symbol="ALT/USDT:USDT", base="ALT", baseId="ALT", contractSize=0.1,
                        id="ALTUSDT" if venue == "binance" else "ALT-USDT-SWAP")
    trade.exchange.set_markets([first_market, other_market])
    trade.exchange.builder.set_markets([first_market, other_market])
    clock["now"] = NOW-20_000
    keys = []
    for market in bundle["markets"]:
        for is_buy in ([True, False] if legs == "hedged" else [True]):
            contracts = 3 if is_buy else 2
            quantity = Decimal(market["contractSize"])*contracts
            trade.quota_gen = CBenchPriceQuotaGen(float(quantity*100+Decimal("0.7")))
            trade.exchange.fill, trade.exchange.status = contracts, "closed"
            key = db.add_signal(make_signal(code=market["symbol"], is_buy=is_buy))
            open_legacy_history(trade, db.get_record(key), 100)
            keys.append(key)
    units = [{k: m[k] for k in ("exchange", "id", "symbol", "type", "base", "quote", "settle", "contractSize")} for m in bundle["markets"]]
    clock["now"] = NOW-5000
    before = collect_account_snapshot(client, units, mode="testnet")
    clock["now"] = NOW-200
    after = collect_account_snapshot(client, units, mode="testnet")
    clock["now"] = NOW
    inputs, native_observations = observed_interval(db, client, before, after, clock, venue, monkeypatch,
                                                   delayed_import=delayed_import)
    params = persist(db, inputs)
    check = db.reconcile_account(**params)
    assert check["payload"]["report"]["payload"]["status"] == "matched_observations", check["payload"]["report"]["payload"]["issues"]
    market_evidence = collect_native_market_evidence(client, [trade._market_contract(m["symbol"])[0] for m in bundle["markets"]], mode="testnet")
    return {"chan": db, "account_context": params["account_context"], "check_id": hashlib.sha256(canonical_bytes(check)).hexdigest(),
            "market_evidence": market_evidence, "policy": bundle["policy"], "inputs": inputs, "check": check,
            "clock": clock, "keys": keys, "trade": trade, "native_observations": native_observations,
            "params": params, "client": client, "native_account": bundle["native_account"]}


def observed_interval(db, client, before, after, clock, venue, monkeypatch, *, delayed_import=False):
    executions, native_observations, captured = [], [], []
    for unit in after["payload"]["markets"]:
        transport = NativeSources(venue)
        request = transport.request
        def timed(kind, params, request=request):
            result = request(kind, params)
            clock["now"] += 5
            return result
        transport.request = timed
        for name in ("fapiPrivateGetUserTrades", "fapiPrivateGetIncome", "privateGetTradeFillsHistory", "privateGetTradeFills", "privateGetAccountBillsArchive"):
            monkeypatch.setattr(client, name, getattr(transport, name), raising=False)
        started, context_before = clock["now"], observe_account_context(client, "testnet")
        receipt = collect_execution_scan(client, unit, account_scope="offline-account", mode="testnet",
                                         start_ms=before["payload"]["started_ms"], end_ms=after["payload"]["finished_ms"]+1)
        observed = {"before": context_before, "after": observe_account_context(client, "testnet"), "started_ms": started, "finished_ms": clock["now"]}
        captured.append((receipt, observed))
    io = AccountSourceIO(venue, [])
    def wallet(params):
        result = io.wallet(params)
        clock["now"] += 5
        return result
    monkeypatch.setattr(client, "fapiPrivateGetIncome" if venue == "binance" else "privateGetAccountBillsArchive", wallet)
    wallet_receipt = collect_wallet_scan(client, mode="testnet", start_ms=before["payload"]["started_ms"], end_ms=after["payload"]["finished_ms"]+1)
    if delayed_import:
        clock["now"] += 200
    for receipt, observed in captured:
        db.store_execution_scan(receipt, account_observation=observed)
        linked = db.get_execution_scan_account(receipt["payload_sha256"])
        executions.append({"receipt": receipt, "account_context": linked["observation"]["account_context"],
                           "manifest_sha256": linked["manifest_sha256"], "observed_ms": linked["observation"]["finished_ms"]})
        native_observations.append(linked["observation"])
    return {"before": before, "after": after, "wallets": [wallet_receipt], "executions": executions}, native_observations


def assert_interval(api, case):
    fn = getattr(api, "assert_native_persisted_interval", None)
    assert callable(fn), "persisted native interval use check is not implemented"
    return fn(case["chan"], **{key: case[key] for key in ("account_context", "check_id", "market_evidence", "policy")})


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("legs", ["one_way", "hedged"])
def test_two_nonempty_markets_use_the_original_persisted_report_without_publishing_or_admitting(store, tmp_path, monkeypatch, venue, legs):
    api = admission_api()
    assert callable(getattr(api, "assert_native_persisted_interval", None)), "persisted native interval use check is not implemented"
    db, _ = store
    case = persisted_case(db, tmp_path, monkeypatch, venue, legs=legs)
    before = db.db.conn.total_changes
    assert assert_interval(api, case) is None
    assert db.db.conn.total_changes == before and not db.db.conn.in_transaction
    assert len(case["inputs"]["after"]["payload"]["positions"]) == (4 if legs == "hedged" else 2)
    assert {p["contracts"] for p in case["inputs"]["after"]["payload"]["positions"]} == ({"2", "3"} if legs == "hedged" else {"3"})
    assert case["check"]["payload"]["report"]["payload"]["economics_complete"] is False


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("role", ["wallet", "execution"])
@pytest.mark.parametrize("kind", ["age", "span"])
def test_source_native_request_windows_not_history_or_later_import_define_exact_bounds(store, tmp_path, monkeypatch, venue, role, kind):
    api = admission_api()
    db, _ = store
    case = persisted_case(db, tmp_path, monkeypatch, venue, delayed_import=True)
    windows = [doc["payload"] for doc in case["inputs"]["wallets"]] if role == "wallet" else case["native_observations"]
    value = max((case["clock"]["now"]-row["started_ms"]) if kind == "age" else row["finished_ms"]-row["started_ms"] for row in windows)
    assert value > 0
    if role == "execution":
        imported = db.db.query_one("SELECT max(observed_ms) AS at FROM chanpy_execution_scans")["at"]
        assert imported > max(row["finished_ms"] for row in windows)
    field = "max_age_ms" if kind == "age" else "max_observation_span_ms"
    case["policy"][field][role] = value
    assert assert_interval(api, case) is None
    case["policy"][field][role] = value-1
    with pytest.raises(CChanException):
        assert_interval(api, case)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_historical_baseline_is_not_mislabelled_as_a_current_source_clock(store, tmp_path, monkeypatch, venue):
    api = admission_api()
    case = persisted_case(store[0], tmp_path, monkeypatch, venue)
    assert case["clock"]["now"]-case["inputs"]["before"]["payload"]["started_ms"] > case["policy"]["max_age_ms"]["account"]
    assert assert_interval(api, case) is None


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("checked", [False, True])
def test_newer_known_account_point_invalidates_old_check_even_inside_ttl_with_unchanged_ledger(store, tmp_path, monkeypatch, venue, checked):
    api = admission_api()
    db, _ = store
    case = persisted_case(db, tmp_path, monkeypatch, venue)
    assert assert_interval(api, case) is None
    case["clock"]["now"] += 1
    latest = collect_account_snapshot(case["client"], case["inputs"]["after"]["payload"]["markets"], mode="testnet")
    db.store_account_evidence(latest)
    if checked:
        case["clock"]["now"] += 1  # The covered end-exclusive boundary must already be in the past.
        inputs, _ = observed_interval(db, case["client"], case["inputs"]["before"], latest, case["clock"], venue, monkeypatch)
        current = db.reconcile_account(**persist(db, inputs))
        assert current["payload"]["report"]["payload"]["status"] == "matched_observations"
        assert current["payload"]["inputs"]["histories"] == case["check"]["payload"]["inputs"]["histories"]
        assert current["payload"]["inputs"]["projections"] == case["check"]["payload"]["inputs"]["projections"]
    assert db.get_account_check(case["check_id"]) == case["check"]  # Still valid history, not current admission.
    assert db.get_account_risk_state(case["account_context"])["frozen"] is False
    changes = db.db.conn.total_changes
    with pytest.raises(CChanException):
        assert_interval(api, case)
    if checked:
        case["check_id"] = hashlib.sha256(canonical_bytes(current)).hexdigest()
        assert assert_interval(api, case) is None
    assert db.db.conn.total_changes == changes


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_same_finish_clock_with_distinct_original_snapshot_is_ambiguous_not_sha_ranked(store, tmp_path, monkeypatch, venue):
    api = admission_api()
    db, _ = store
    case = persisted_case(db, tmp_path, monkeypatch, venue)
    account = case["native_account"]
    row = account["assets" if venue == "binance" else "details"][0]
    field = "updateTime" if venue == "binance" else "uTime"
    row[field] = int(row[field])+1 if venue == "binance" else str(int(row[field])+1)
    now = case["clock"]["now"]
    case["clock"]["now"] = case["inputs"]["after"]["payload"]["started_ms"]
    tied = collect_account_snapshot(case["client"], case["inputs"]["after"]["payload"]["markets"], mode="testnet")
    case["clock"]["now"] = now
    assert tied != case["inputs"]["after"]
    assert tied["payload"]["finished_ms"] == case["inputs"]["after"]["payload"]["finished_ms"]
    inputs, _ = observed_interval(db, case["client"], case["inputs"]["before"], tied, case["clock"], venue, monkeypatch)
    other = db.reconcile_account(**persist(db, inputs))
    assert other["payload"]["report"]["payload"]["status"] == "matched_observations"
    for check in (case["check"], other):
        case["check_id"] = hashlib.sha256(canonical_bytes(check)).hexdigest()
        with pytest.raises(CChanException):
            assert_interval(api, case)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_corrupt_index_on_an_unchecked_newer_snapshot_cannot_hide_it(store, tmp_path, monkeypatch, venue):
    from Trade.AccountStore import SCHEMA
    api = admission_api()
    db, _ = store
    case = persisted_case(db, tmp_path, monkeypatch, venue)
    latest = collect_account_snapshot(case["client"], case["inputs"]["after"]["payload"]["markets"], mode="testnet")
    key = db.store_account_evidence(latest)
    db.db.execute("DROP TRIGGER chanpy_account_evidence_no_update")
    db.db.execute("UPDATE chanpy_account_evidence SET context_id=? WHERE evidence_id=?", ("0"*64, key))
    db.db.execute(SCHEMA["chanpy_account_evidence_no_update"])
    with pytest.raises(CChanException):
        assert_interval(api, case)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_wallet_and_execution_observations_participate_in_joint_not_separate_source_skew(store, tmp_path, monkeypatch, venue):
    api = admission_api()
    case = persisted_case(store[0], tmp_path, monkeypatch, venue, delayed_import=True)
    account = case["inputs"]["after"]["payload"]
    market = case["market_evidence"]["payload"]
    native = [row[k]["source_ms"] for row in market["observations"] for k in ("mark", "book")]
    others = [doc["payload"]["started_ms"] for doc in case["inputs"]["wallets"]]+[row["started_ms"] for row in case["native_observations"]]
    combined = [account["started_ms"], *native, *others]
    limit = max(combined)-min(combined)
    case["policy"]["max_source_skew_ms"] = limit
    assert assert_interval(api, case) is None
    case["policy"]["max_source_skew_ms"] = limit-1
    api.assert_native_account_market_freshness(case["client"], mode="testnet", markets=[row["market"] for row in market["observations"]],
                                             account_snapshot=case["inputs"]["after"], market_evidence=case["market_evidence"], policy=case["policy"])
    with pytest.raises(CChanException):
        assert_interval(api, case)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["unknown_check", "context", "market_price", "missing_market", "projection", "new_attempt"])
def test_original_check_cannot_hide_current_binding_or_ledger_changes(store, tmp_path, monkeypatch, venue, damage):
    from .test_native_market_evidence import reseal
    api = admission_api()
    db, _ = store
    case = persisted_case(db, tmp_path, monkeypatch, venue)
    if damage == "unknown_check":
        case["check_id"] = "0"*64
    elif damage == "context":
        context = copy.deepcopy(case["account_context"])
        context["identifier_sha256"] = "0"*64
        context["context_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in context.items() if k != "context_id"})).hexdigest()
        case["account_context"] = context
    elif damage == "market_price":
        mark = case["market_evidence"]["payload"]["observations"][0]["mark"]
        mark["price"] = mark["raw"]["markPrice" if venue == "binance" else "markPx"] = "111"
        reseal(case["market_evidence"])
    elif damage == "missing_market":
        case["market_evidence"]["payload"]["observations"].pop()
        case["market_evidence"]["payload"]["requests"] = 2
        reseal(case["market_evidence"])
    elif damage == "projection":
        db.db.execute("UPDATE chan_trade SET current_qty=current_qty+0.01 WHERE id=?", (case["keys"][0],))
    else:
        key = db.add_signal(make_signal(code="TEST/USDT:USDT", is_buy=False))
        quantity, _, contract = case["trade"].prepare_order("TEST/USDT:USDT", 0.03, 100, record=db.get_record(key))
        assert db.acquire_open_intent(key, quantity, "after-saved-check", order_contract=contract)
    changes = db.db.conn.total_changes
    with pytest.raises(CChanException):
        assert_interval(api, case)
    assert db.db.conn.total_changes == changes


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_other_trade_shaped_table_and_other_connection_freezes_are_not_hidden(store, tmp_path, monkeypatch, venue):
    api = admission_api()
    db, conf = store
    case = persisted_case(db, tmp_path, monkeypatch, venue)
    other = CChanDB(table_name="another_strategy", db_conf=conf)
    try:
        trade = venue_engine(other, tmp_path, venue)
        if venue == "binance":
            trade.exchange.account_alias = "fake-Futures-A"
        trade.exchange.fill, trade.exchange.status = 3, "closed"
        key = other.add_signal(make_signal(code="TEST/USDT:USDT"))
        open_legacy_history(trade, other.get_record(key), 100)
        assert db.get_account_check(case["check_id"]) == case["check"]  # Old check remains a valid *historical* check.
        with pytest.raises(CChanException):
            assert_interval(api, case)
        other.reconcile_account(**{**case["params"], "wallet_ids": []})
        assert other.get_account_risk_state(case["account_context"])["frozen"] is True
        with pytest.raises(CChanException):
            assert_interval(api, case)
    finally:
        other.close()


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_restart_and_original_nested_savepoint_do_not_publish_or_end_the_callers_transaction(store, tmp_path, monkeypatch, venue):
    api = admission_api()
    db, conf = store
    case = persisted_case(db, tmp_path, monkeypatch, venue)
    reopened = CChanDB(db_conf=conf)
    try:
        case["chan"] = reopened
        changes = reopened.db.conn.total_changes
        assert assert_interval(api, case) is None
        with reopened.db.transaction():
            assert assert_interval(api, case) is None
            assert reopened.db.conn.in_transaction
        assert not reopened.db.conn.in_transaction and reopened.db.conn.total_changes == changes
    finally:
        reopened.close()


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_use_time_also_includes_the_owned_db_transaction_exit(store, tmp_path, monkeypatch, venue):
    api = admission_api()
    db, _ = store
    case = persisted_case(db, tmp_path, monkeypatch, venue)
    transaction = db.db.transaction
    @contextmanager
    def delayed_exit():
        with transaction():
            yield
        case["clock"]["now"] += 2000
    monkeypatch.setattr(db.db, "transaction", delayed_exit)
    with pytest.raises(CChanException):
        assert_interval(api, case)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("missing", ["wallet", "second_market_execution"])
def test_original_incomplete_coverage_freeze_is_sticky_even_if_the_selected_check_is_matched(store, tmp_path, monkeypatch, venue, missing):
    api = admission_api()
    db, _ = store
    case = persisted_case(db, tmp_path, monkeypatch, venue)
    request = copy.deepcopy(case["params"])
    if missing == "wallet":
        request["wallet_ids"] = []
    else:
        request["execution_scan_ids"] = request["execution_scan_ids"][:1]
    incomplete = db.reconcile_account(**request)
    reason = "wallet_window_missing" if missing == "wallet" else "execution_window_missing"
    assert reason in {row["reason"] for row in incomplete["payload"]["report"]["payload"]["issues"]}
    assert db.reconcile_account(**case["params"]) == case["check"]
    assert db.get_account_risk_state(case["account_context"])["frozen"] is True
    with pytest.raises(CChanException):
        assert_interval(api, case)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["missing_started", "missing_observation"])
def test_resealed_scan_cannot_replace_missing_native_observation_with_import_or_coverage_time(store, tmp_path, monkeypatch, venue, damage):
    import json
    from Trade.ExecutionStore import SCHEMA
    api = admission_api()
    db, _ = store
    case = persisted_case(db, tmp_path, monkeypatch, venue)
    scan_id = case["inputs"]["executions"][0]["receipt"]["payload_sha256"]
    row = db.db.query_one("SELECT * FROM chanpy_execution_scans WHERE scan_id=?", (scan_id,))
    manifest = json.loads(row["payload"])
    if damage == "missing_started":
        del manifest["native_account"]["started_ms"]
    else:
        del manifest["native_account"]
    raw = canonical_bytes(manifest).decode()
    db.db.execute("DROP TRIGGER chanpy_execution_scans_no_update")
    db.db.execute("UPDATE chanpy_execution_scans SET payload=?,payload_sha256=?,observed_ms=? WHERE scan_id=?",
                  (raw, hashlib.sha256(raw.encode()).hexdigest(), case["clock"]["now"], scan_id))
    db.db.execute(SCHEMA["chanpy_execution_scans_no_update"])
    with pytest.raises(CChanException):
        assert_interval(api, case)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_original_reserved_snapshot_blocks_a_competing_writer_then_requires_recheck_after_release(store, tmp_path, monkeypatch, venue):
    api = admission_api()
    db, conf = store
    case = persisted_case(db, tmp_path, monkeypatch, venue)
    db.db.conn.execute("PRAGMA journal_mode=WAL")
    other = CChanDB(db_conf=conf)
    try:
        other.db.conn.execute("PRAGMA busy_timeout=0")
        query = db.db.query_one
        attempts = []
        def interleave(sql, args=()):
            if "FROM chanpy_account_checks WHERE check_id" in sql and not attempts:
                attempts.append(True)
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    other.db.execute("UPDATE chan_trade SET current_qty=current_qty+0.01 WHERE id=?", (case["keys"][0],))
            return query(sql, args)
        monkeypatch.setattr(db.db, "query_one", interleave)
        assert assert_interval(api, case) is None
        assert attempts == [True] and not other.db.conn.in_transaction
        other.db.execute("UPDATE chan_trade SET current_qty=current_qty+0.01 WHERE id=?", (case["keys"][0],))
        with pytest.raises(CChanException):
            assert_interval(api, case)
    finally:
        other.close()


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_frozen_input_packet_cannot_change_during_real_db_reads(store, tmp_path, monkeypatch, venue):
    api = admission_api()
    db, _ = store
    case = persisted_case(db, tmp_path, monkeypatch, venue)
    query = db.db.query_one
    def interleave(sql, args=()):
        if "FROM chanpy_account_checks WHERE check_id" in sql:
            case["policy"]["max_age_ms"]["execution"] = 1
        return query(sql, args)
    monkeypatch.setattr(db.db, "query_one", interleave)
    with pytest.raises(CChanException):
        assert_interval(api, case)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_persisted_interval_decoder_needs_no_sdk_and_performs_no_private_io(store, tmp_path, monkeypatch, venue):
    api = admission_api()
    db, conf = store
    case = persisted_case(db, tmp_path, monkeypatch, venue)
    values = {key: case[key] for key in ("account_context", "check_id", "market_evidence", "policy")}
    code = """
import importlib.abc, json, sys
blocked = {'ccxt', 'xgboost', 'lightgbm', 'sklearn', 'optuna', 'yaml', 'PyQt6', 'minio', 'qcloud_cos'}
attempted = []
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            attempted.append(fullname.split('.')[0])
            raise ModuleNotFoundError('optional dependency intentionally absent')
sys.meta_path.insert(0, BlockOptional())
from Trade.db_util import CChanDB
from Config.EnvConfig import CEnv
import Trade.NativeAdmission as api
import Trade.AccountSources as accounts
import Trade.AccountRiskStore as risk
import Trade.ExecutionStore as executions
import Trade.NativeMarketEvidence as market
import Trade.OrderAudit as journal
values = json.loads(sys.stdin.buffer.read())
at, config, params = values['now'], values['db'], values['params']
env = CEnv.__new__(CEnv)
env.conf = {}
CEnv._instance = env
for module in (api, accounts, risk, executions, market, journal):
    module.utc_now_ms = lambda: at
db = CChanDB(db_conf=config)
try:
    before = db.db.conn.total_changes
    assert api.assert_native_persisted_interval(db, **params) is None
    assert db.db.conn.total_changes == before and not db.db.conn.in_transaction
finally:
    db.close()
assert not attempted, attempted
assert not any(name.split('.')[0] in blocked for name in sys.modules)
print('DB-only native interval without SDK PASS')
"""
    result = subprocess.run([sys.executable, "-c", code], input=canonical_bytes({"params": values, "db": conf, "now": case["clock"]["now"]}),
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.strip() == b"DB-only native interval without SDK PASS" and result.stderr == b""
