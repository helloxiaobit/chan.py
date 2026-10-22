"""Fixed original collectors and fake native transports, never order sends."""
import copy
import hashlib
import importlib.util
import sqlite3
import subprocess
import sys
from contextlib import contextmanager

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from .test_execution_store import store
from .test_native_current_components import current_case
from .test_native_admission_interval import explicit_path_environment


def collector_api():
    assert importlib.util.find_spec("Trade.NativeComponentCollector") is not None, "collector-owned native component pipeline is missing"
    from Trade import NativeComponentCollector
    return NativeComponentCollector


def owned_case(db, tmp_path, monkeypatch, venue, *, mode="one_way", side=True, fail_stage=None, effect=None):
    api = collector_api()
    case = current_case(db, tmp_path, monkeypatch, venue, mode=mode, side=side)
    client, clock = case["client"], case["clock"]
    from .test_execution_facts import NativeSources
    from .test_native_account_sources import AccountSourceIO
    scopes, execution = [], {}
    for item in case["inputs"]["executions"]:
        p = item["receipt"]["payload"]
        scopes.append(p["account_scope"])
        execution[p["market"]["id"]] = NativeSources(venue,
            [copy.deepcopy(row["raw"]) for row in p["facts"] if row["kind"] == "trade"],
            [copy.deepcopy(row["raw"]) for row in p["facts"] if row["kind"] == "funding"])
    assert len(set(scopes)) == 1
    wallet = AccountSourceIO(venue, [copy.deepcopy(row["raw"]) for row in case["inputs"]["wallets"][0]["payload"]["facts"]])
    if venue == "binance":
        monkeypatch.setattr(client, "fapiPrivateGetUserTrades", lambda p: execution[p["symbol"]].request("trades", p))
        monkeypatch.setattr(client, "fapiPrivateGetIncome", lambda p: execution[p["symbol"]].request("funding", p)
                            if p.get("incomeType") == "FUNDING_FEE" else wallet.wallet(p))
    else:
        for method in ("privateGetTradeFills", "privateGetTradeFillsHistory"):
            monkeypatch.setattr(client, method, lambda p: execution[p["instId"]].request("trades", p))
        monkeypatch.setattr(client, "privateGetAccountBillsArchive", lambda p: execution[p["instId"]].request("funding", p)
                            if p.get("type") == "8" else wallet.wallet(p))
    for module in ("Trade.NativeComponentCollector", "Trade.AccountSources", "Trade.ExecutionFacts", "Trade.NativePendingOrders",
                   "Trade.NativeBalanceReservations"):
        monkeypatch.setattr(module+".utc_now_ms", lambda: clock["now"])
    methods = (("fapiPrivateV3GetBalance", "fapiPrivateGetOpenOrders", "fapiPrivateGetOpenAlgoOrders", "fapiPrivateGetAccountConfig",
                "fapiPrivateV3GetAccount", "fapiPrivateV3GetPositionRisk", "fapiPrivateGetSymbolConfig", "fapiPrivateGetMultiAssetsMargin",
                "fapiPrivateGetUserTrades", "fapiPrivateGetIncome", "fapiPublicGetPremiumIndex", "fapiPublicGetTickerBookTicker") if venue == "binance" else
               ("privateGetAccountConfig", "privateGetTradeOrdersPending", "privateGetTradeOrdersAlgoPending", "privateGetAccountBalance",
                "privateGetAccountPositions", "privateGetTradeFills", "privateGetTradeFillsHistory", "privateGetAccountBillsArchive",
                "publicGetPublicMarkPrice", "publicGetMarketBooks"))
    roles = ({"pending": "fapiPrivateGetOpenOrders", "balance": "fapiPrivateV3GetAccount", "after": "fapiPrivateV3GetPositionRisk",
              "execution": "fapiPrivateGetUserTrades", "wallet": "fapiPrivateGetIncome", "market": "fapiPublicGetPremiumIndex",
              "current": "fapiPrivateV3GetBalance"} if venue == "binance" else
             {"pending": "privateGetTradeOrdersPending", "balance": "privateGetAccountBalance", "after": "privateGetAccountPositions",
              "execution": "privateGetTradeFills", "wallet": "privateGetAccountBillsArchive", "market": "publicGetPublicMarkPrice",
              "current": "privateGetAccountConfig"})
    trace, failures, books, effects = [], [], [], []
    for name in methods:
        get = getattr(client, name)
        def observed(options, get=get, name=name):
            assert not db.db.conn.in_transaction, "private/public source I/O must stay outside the writer lock"
            trace.append((name, copy.deepcopy(options)))
            clock["now"] += 1
            is_stage = fail_stage is not None and name == roles[fail_stage]
            if fail_stage == "wallet":
                is_stage &= not options.get("incomeType") and not options.get("type")
            elif fail_stage == "current":
                is_stage &= len(books) == len(case["arguments"]["markets"])
            if is_stage:
                failures.append(name)
                raise RuntimeError("PRIVATE_SOURCE_EXCEPTION_DO_NOT_COPY")
            if effect is not None and not effects:
                effects.append(1)
                effect(case)
            result = get(options)
            if name in {"fapiPublicGetTickerBookTicker", "publicGetMarketBooks"}:
                books.append(1)
            return result
        monkeypatch.setattr(client, name, observed)
    args = {"mode": "testnet", "markets": case["arguments"]["markets"], "before_id": case["params"]["before_id"],
            "account_scope": scopes[0], "policy": case["arguments"]["policy"]}
    return {**case, "collector": api, "collect_args": args, "trace": trace, "failures": failures}


def collect(case):
    return case["collector"].collect_and_check_native_components(case["db"], case["client"], **case["collect_args"])


def source_rows(db):
    return {name: db.db.query(f"SELECT * FROM {name}") for name in ("chanpy_account_evidence",
        "chanpy_native_account_observations", "chanpy_execution_facts", "chanpy_execution_scans")}


def damage_pending_price(case, monkeypatch, venue):
    method = "fapiPrivateGetOpenOrders" if venue == "binance" else "privateGetTradeOrdersPending"
    get = getattr(case["client"], method)
    def different_price(options):
        response = get(options)
        rows = response if venue == "binance" else response["data"]
        for row in rows:
            row["price" if venue == "binance" else "px"] = "101"
        return response
    monkeypatch.setattr(case["client"], method, different_price)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mode,side", [(mode, side) for mode in ("one_way", "hedged") for side in (True, False)])
def test_owned_nonempty_sources_have_fixed_order_actual_counts_original_math_and_no_order_writes(store, tmp_path, monkeypatch, venue, mode, side):
    db, _ = store
    case = owned_case(db, tmp_path, monkeypatch, venue, mode=mode, side=side)
    old_orders = db.db.query("SELECT * FROM chan_trade")
    result = collect(case)
    assert result["schema"] == "chan-native-collected-components-v1"
    assert result["payload_sha256"] == hashlib.sha256(canonical_bytes(result["payload"])).hexdigest()
    p = result["payload"]
    assert p["economics_complete"] is p["native_admission_verified"] is False
    assert p["coverage"] == "local_collector_owned_observations"
    assert p["operations"] == ["pending", "balance", "after", "execution:ALT/USDT:USDT", "execution:TEST/USDT:USDT", "wallet", "market", "current"]
    assert p["observed_sdk_calls"] == len(case["trace"]) == (39 if venue == "binance" else 58)
    assert p["sdk_call_upper_bound"] == (276 if venue == "binance" else 274)+132*2
    assert p["observed_sdk_calls"] <= p["sdk_call_upper_bound"]
    assert p["implementation_sha256"] and p["database_location_sha256"]
    check = db.get_account_check(p["check_id"])
    assert check["payload"]["report"]["payload"]["status"] == "matched_observations"
    assert check["payload"]["inputs"]["before"]["payload"]["markets"] == check["payload"]["inputs"]["after"]["payload"]["markets"]
    assert db.get_account_risk_state(case["params"]["account_context"])["frozen"] is False
    assert db.db.query("SELECT * FROM chan_trade") == old_orders and len(case["trade"].exchange.created) == 3
    assert p["policy"] == case["collect_args"]["policy"]


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("stage", ["pending", "balance", "after", "execution", "wallet", "market", "current"])
def test_stage_failure_is_redacted_sticky_without_retry_or_new_orders(store, tmp_path, monkeypatch, venue, stage):
    db, _ = store
    case = owned_case(db, tmp_path, monkeypatch, venue, fail_stage=stage)
    old_orders = db.db.query("SELECT * FROM chan_trade")
    with pytest.raises(CChanException) as caught:
        collect(case)
    assert "PRIVATE_SOURCE_EXCEPTION" not in str(caught.value)
    assert len(case["failures"]) == 1
    state = db.get_account_risk_state(case["params"]["account_context"])
    assert state["frozen"] is True
    assert db.db.query("SELECT * FROM chan_trade") == old_orders and len(case["trade"].exchange.created) == 3
    assert not db.db.conn.in_transaction


@pytest.mark.parametrize("field", ["receipts", "passed", "check_id"])
def test_producer_does_not_accept_external_receipts_or_a_preapproved_check(store, tmp_path, monkeypatch, field):
    db, _ = store
    case = owned_case(db, tmp_path, monkeypatch, "binance")
    with pytest.raises(TypeError):
        case["collector"].collect_and_check_native_components(db, case["client"], **case["collect_args"], **{field: True})
    assert case["trace"] == []


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_already_frozen_account_and_ambient_transaction_fail_before_source_io(store, tmp_path, monkeypatch, venue):
    db, _ = store
    case = owned_case(db, tmp_path, monkeypatch, venue)
    with db.db.transaction():
        with pytest.raises(CChanException):
            collect(case)
        assert db.db.conn.in_transaction
    assert case["trace"] == []
    db.reconcile_native_account(**{**case["request"], "wallet_ids": []})
    with pytest.raises(CChanException):
        collect(case)
    assert case["trace"] == []


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mismatch", [False, True])
def test_failed_publication_commit_does_not_mistake_rolled_back_check_for_a_persisted_freeze(store, tmp_path, monkeypatch, venue, mismatch):
    db, _ = store
    case = owned_case(db, tmp_path, monkeypatch, venue)
    if mismatch:
        damage_pending_price(case, monkeypatch, venue)
    old_sources, old_orders = source_rows(db), db.db.query("SELECT * FROM chan_trade")
    old_checks = {row["check_id"] for row in db.db.query("SELECT check_id FROM chanpy_account_checks")}
    transaction, outer, rolled_status = db.db.transaction, [], []
    @contextmanager
    def fail_commit_once():
        is_outer = db.db._transaction_depth == 0
        with transaction():
            if is_outer:
                outer.append(1)
            yield
            if is_outer and len(outer) == 2:
                rolled_status.extend(row["status"] for row in db.db.query("SELECT check_id,status FROM chanpy_account_checks")
                                     if row["check_id"] not in old_checks)
                raise RuntimeError("PRIVATE_COMMIT_EXCEPTION_DO_NOT_COPY")
    monkeypatch.setattr(db.db, "transaction", fail_commit_once)
    with pytest.raises(CChanException) as caught:
        collect(case)
    assert "PRIVATE_COMMIT_EXCEPTION" not in str(caught.value)
    assert rolled_status == (["incomplete"] if mismatch else ["matched_observations"])
    assert source_rows(db) == old_sources and db.db.query("SELECT * FROM chan_trade") == old_orders
    assert not db.db.conn.in_transaction and len(case["trade"].exchange.created) == 3
    state = db.get_account_risk_state(case["params"]["account_context"])
    assert state["frozen"] is True
    checks = [row for row in db.db.query("SELECT check_id,status FROM chanpy_account_checks") if row["check_id"] not in old_checks]
    assert len(checks) == 1 and checks[0]["status"] == "incomplete"
    assert db.get_account_check(checks[0]["check_id"])["payload"]["inputs"] is None


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("scope", [None, True, 7, "", "two words", "中", "x"*65])
def test_invalid_scope_rejects_before_private_io_and_does_not_publish_a_check(store, tmp_path, monkeypatch, venue, scope):
    db, _ = store
    case = owned_case(db, tmp_path, monkeypatch, venue)
    sources, checks = source_rows(db), db.db.query("SELECT * FROM chanpy_account_checks")
    case["collect_args"]["account_scope"] = scope
    with pytest.raises(CChanException):
        collect(case)
    assert case["trace"] == []
    assert source_rows(db) == sources and db.db.query("SELECT * FROM chanpy_account_checks") == checks


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("target", ["balance", "check"])
def test_sqlite_publication_failure_is_atomic_and_does_not_claim_an_unpublished_freeze(store, tmp_path, monkeypatch, venue, target):
    db, _ = store
    case = owned_case(db, tmp_path, monkeypatch, venue)
    sources, orders = source_rows(db), db.db.query("SELECT * FROM chan_trade")
    checks = db.db.query("SELECT * FROM chanpy_account_checks")
    table = "chanpy_native_account_observations" if target == "balance" else "chanpy_account_checks"
    condition = "WHEN NEW.kind='balance'" if target == "balance" else ""
    db.db.execute(f"CREATE TRIGGER fail_owned_publication BEFORE INSERT ON {table} {condition} BEGIN SELECT RAISE(ABORT,'PRIVATE_SQL_FAILURE'); END")
    with pytest.raises(CChanException) as caught:
        collect(case)
    assert "PRIVATE_SQL_FAILURE" not in str(caught.value)
    assert source_rows(db) == sources and db.db.query("SELECT * FROM chan_trade") == orders
    assert not db.db.conn.in_transaction and len(case["trade"].exchange.created) == 3
    state = db.get_account_risk_state(case["params"]["account_context"])
    assert state["frozen"] is (target == "balance")
    if target == "check":
        assert db.db.query("SELECT * FROM chanpy_account_checks") == checks


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_precise_failed_check_is_committed_once_and_blocks_the_next_collection(store, tmp_path, monkeypatch, venue):
    db, conf = store
    case = owned_case(db, tmp_path, monkeypatch, venue)
    damage_pending_price(case, monkeypatch, venue)
    ids = {row["check_id"] for row in db.db.query("SELECT check_id FROM chanpy_account_checks")}
    orders = db.db.query("SELECT * FROM chan_trade")
    with pytest.raises(CChanException):
        collect(case)
    new = [row for row in db.db.query("SELECT check_id,status FROM chanpy_account_checks") if row["check_id"] not in ids]
    assert len(new) == 1 and new[0]["status"] == "incomplete"
    assert db.get_account_check(new[0]["check_id"])["payload"]["inputs"] is not None
    calls = len(case["trace"])
    with pytest.raises(CChanException):
        collect(case)
    assert len(case["trace"]) == calls
    from Trade.db_util import CChanDB
    restarted = CChanDB(db_conf=conf)
    try:
        assert restarted.get_account_risk_state(case["params"]["account_context"])["frozen"] is True
        assert restarted.db.query("SELECT * FROM chan_trade") == orders
    finally:
        restarted.close()


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("change", ["ledger", "freeze", "policy", "markets"])
def test_collection_rejects_concurrent_writes_or_caller_packet_drift_without_overwriting_them(store, tmp_path, monkeypatch, venue, change):
    db, conf = store
    def effect(case):
        if change == "ledger":
            with sqlite3.connect(conf["sqlite_path"]) as writer:
                writer.execute("UPDATE chan_trade SET current_qty=9 WHERE id=?", (case["key"],))
        elif change == "freeze":
            from Trade.db_util import CChanDB
            writer = CChanDB(db_conf=conf)
            try:
                writer.reconcile_native_account(**{**case["request"], "wallet_ids": []})
            finally:
                writer.close()
        elif change == "policy":
            case["arguments"]["policy"]["max_age_ms"]["balance"] += 1
        else:
            case["arguments"]["markets"][0]["contractSize"] = "99"
    case = owned_case(db, tmp_path, monkeypatch, venue, effect=effect)
    orders = db.db.query("SELECT * FROM chan_trade")
    with pytest.raises(CChanException):
        collect(case)
    assert db.get_account_risk_state(case["params"]["account_context"])["frozen"] is True
    if change == "ledger":
        assert db.get_record(case["key"])["current_qty"] == 9
    else:
        assert db.db.query("SELECT * FROM chan_trade") == orders
    assert len(case["trade"].exchange.created) == 3 and not db.db.conn.in_transaction


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_connection_swap_cannot_publish_failure_into_a_different_database(store, tmp_path, monkeypatch, venue):
    from Trade.db_util import CChanDB
    db, _ = store
    backend, connection = db.db, db.db.conn
    other = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"unrelated.db")})
    case = owned_case(db, tmp_path, monkeypatch, venue, effect=lambda case: setattr(backend, "conn", other.db.conn))
    original_checks = db.db.query("SELECT * FROM chanpy_account_checks")
    try:
        with pytest.raises(CChanException):
            collect(case)
        assert other.db.query("SELECT * FROM chanpy_account_checks") == []
        assert other.db.query("SELECT * FROM chanpy_native_account_observations") == []
    finally:
        backend.conn = connection
        other.close()
    assert db.db.query("SELECT * FROM chanpy_account_checks") == original_checks
    assert db.get_account_risk_state(case["params"]["account_context"])["frozen"] is False


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("change", ["mode", "policy", "missing_before", "wallet_before", "partial_markets"])
def test_invalid_entry_keeps_sources_checks_and_orders_unchanged_without_io(store, tmp_path, monkeypatch, venue, change):
    db, _ = store
    case = owned_case(db, tmp_path, monkeypatch, venue)
    sources, checks, orders = source_rows(db), db.db.query("SELECT * FROM chanpy_account_checks"), db.db.query("SELECT * FROM chan_trade")
    if change == "mode":
        case["collect_args"]["mode"] = "paper"
    elif change == "policy":
        del case["collect_args"]["policy"]["max_age_ms"]["balance"]
    elif change == "missing_before":
        case["collect_args"]["before_id"] = "0"*64
    elif change == "wallet_before":
        case["collect_args"]["before_id"] = case["request"]["wallet_ids"][0]
    else:
        case["collect_args"]["markets"] = case["collect_args"]["markets"][:1]
    with pytest.raises(CChanException):
        collect(case)
    assert case["trace"] == []
    assert source_rows(db) == sources and db.db.query("SELECT * FROM chanpy_account_checks") == checks
    assert db.db.query("SELECT * FROM chan_trade") == orders


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("change", ["backend", "table", "code"])
def test_db_owner_table_and_collector_code_drift_fail_and_freeze_only_original_target(store, tmp_path, monkeypatch, venue, change):
    from pathlib import Path
    from Trade.db_util import CChanDB
    db, _ = store
    backend, table = db.db, db.table
    other = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"unrelated.db")})
    read_bytes = Path.read_bytes
    def effect(case):
        if change == "backend":
            db.db = other.db
        elif change == "table":
            db.table = "different_trade_table"
        else:
            def changed(path):
                result = read_bytes(path)
                return result+b"\n# source drift" if path.name == "NativeComponentCollector.py" else result
            monkeypatch.setattr(Path, "read_bytes", changed)
    case = owned_case(db, tmp_path, monkeypatch, venue, effect=effect)
    sources, orders = source_rows(db), backend.query("SELECT * FROM chan_trade")
    try:
        with pytest.raises(CChanException):
            collect(case)
        assert other.db.query("SELECT * FROM chanpy_account_checks") == []
        assert source_rows(other) == {name: [] for name in sources}
    finally:
        db.db, db.table = backend, table
        other.close()
    assert source_rows(db) == sources and backend.query("SELECT * FROM chan_trade") == orders
    assert db.get_account_risk_state(case["params"]["account_context"])["frozen"] is True


def test_collector_import_needs_neither_optional_sdk_nor_configuration():
    code = """
import importlib.abc, sys
attempted = []
class NoOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ccxt', 'Config', 'numpy', 'pandas', 'xgboost', 'lightgbm', 'torch', 'matplotlib'}:
            attempted.append(fullname)
            raise ImportError('no optional dependencies or configuration')
sys.meta_path.insert(0, NoOptional())
from Trade.NativeComponentCollector import SCHEMA, collect_and_check_native_components
assert SCHEMA == 'chan-native-collected-components-v1'
assert callable(collect_and_check_native_components)
assert not attempted, attempted
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stderr == b""
