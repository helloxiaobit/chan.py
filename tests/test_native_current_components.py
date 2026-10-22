"""Joint source use from real fake collectors and original persisted ledger."""
import copy
import hashlib
import importlib.util
import subprocess
import sys

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.NativeMarketEvidence import collect_native_market_evidence
from .test_execution_store import store
from .test_native_account_components import component_case
from .test_native_account_component_checks import save_sources
from .test_native_admission_interval import explicit_path_environment


def current_api():
    assert importlib.util.find_spec("Trade.NativeCurrentComponents") is not None, "joint native component freshness consumer is missing"
    from Trade import NativeCurrentComponents
    return NativeCurrentComponents


def component_policy():
    # Fixture choices only. Every number must be provided by a real consumer.
    return {"schema": "chan-native-component-freshness-policy-v1",
            "max_age_ms": {key: 2000 for key in ("account", "mark", "book", "wallet", "execution", "open_orders", "balance")},
            "max_observation_span_ms": {key: 2000 for key in ("account", "market", "wallet", "execution", "open_orders", "balance", "total")},
            "max_source_skew_ms": 2000}


def test_component_policy_has_explicit_balance_budgets_and_copies_strict_zeros():
    api = current_api()
    policy = component_policy()
    for field in ("max_age_ms", "max_observation_span_ms"):
        policy[field]["balance"] = 0
    value = api.read_native_component_policy(policy)
    assert value == policy and value is not policy
    policy["max_age_ms"]["balance"] = 99
    assert value["max_age_ms"]["balance"] == 0


@pytest.mark.parametrize("field", ["max_age_ms", "max_observation_span_ms"])
@pytest.mark.parametrize("bad", [None, True, -1, 1.0, "10", float("nan"), 2**63, "missing"])
def test_balance_budget_is_never_filled_from_account_or_coerced(field, bad):
    api = current_api()
    policy = component_policy()
    if bad == "missing":
        del policy[field]["balance"]
    else:
        policy[field]["balance"] = bad
    with pytest.raises(CChanException):
        api.read_native_component_policy(policy)


@pytest.mark.parametrize("damage", ["legacy", "extra_role", "tolerance", "passed", "missing_account"])
def test_new_component_policy_does_not_widen_old_policy_or_accept_capabilities(damage):
    api = current_api()
    from Trade.NativeAdmission import read_native_freshness_policy
    policy = component_policy()
    with pytest.raises(CChanException):
        read_native_freshness_policy(policy)
    if damage == "legacy":
        policy["schema"] = "chan-native-freshness-policy-v1"
    elif damage == "extra_role":
        policy["max_age_ms"]["ticker"] = 1
    elif damage == "tolerance":
        policy["amount_tolerance"] = "0.01"
    elif damage == "passed":
        policy["native_admission_verified"] = True
    else:
        del policy["max_age_ms"]["account"]
    with pytest.raises(CChanException):
        api.read_native_component_policy(policy)


def current_case(db, tmp_path, monkeypatch, venue, *, mode="one_way", side=True, timed_native=False, sdk_drift=None):
    api = current_api()
    from . import test_native_account_components as fixtures
    from . import test_crypto_order_contract as order_clock
    # The older component fixture intentionally needs no use-time policy.
    # Its execution observer otherwise uses wall time ~10s after its synthetic
    # account clock. Bracket raw execution and native association with the
    # same existing fake clock; do not enlarge freshness budgets to hide it.
    for module in ("Trade.ExecutionFacts", "tests.test_execution_account_binding"):
        monkeypatch.setattr(module+".utc_now_ms", lambda: order_clock.utc_now_ms())
    captured, collect = {}, fixtures.collect_native_balance_reservations
    def capture(client, **options):
        captured["client"] = client
        return collect(client, **options)
    monkeypatch.setattr(fixtures, "collect_native_balance_reservations", capture)
    params, inputs, trade, key = component_case(db, tmp_path, monkeypatch, venue, mode=mode, side=side)
    client = captured["client"]
    if timed_native:
        from Trade.NativeBalanceReservations import collect_native_balance_reservations
        from Trade.NativePendingOrders import collect_native_pending_orders
        end = inputs["after"]["payload"]["started_ms"]
        native_clock = {"now": end-49}
        def mutation_clocks(value):
            if isinstance(value, dict):
                for name in list(value):
                    if name in {"updateTime", "uTime"}:
                        value[name] = str(end-51) if name == "uTime" else end-51
                    else:
                        mutation_clocks(value[name])
            elif isinstance(value, list):
                for row in value:
                    mutation_clocks(row)
        methods = (("fapiPrivateV3GetBalance", "fapiPrivateGetOpenOrders", "fapiPrivateGetOpenAlgoOrders",
                    "fapiPrivateGetAccountConfig", "fapiPrivateV3GetAccount") if venue == "binance" else
                   ("privateGetAccountConfig", "privateGetTradeOrdersPending", "privateGetTradeOrdersAlgoPending", "privateGetAccountBalance"))
        for name in methods:
            get = getattr(client, name)
            def timed(options, get=get, is_balance=name in {"fapiPrivateV3GetAccount", "privateGetAccountBalance"}):
                raw = get(options)
                if is_balance:
                    mutation_clocks(raw)
                native_clock["now"] += 1
                return raw
            monkeypatch.setattr(client, name, timed)
        for module in ("Trade.NativeBalanceReservations", "Trade.NativePendingOrders"):
            monkeypatch.setattr(module+".utc_now_ms", lambda: native_clock["now"])
        markets = [trade._market_contract(row["symbol"])[0] for row in inputs["after"]["payload"]["markets"]]
        params["pending_orders"] = collect_native_pending_orders(client, markets, mode="testnet")
        params["balance_reservations"] = collect_native_balance_reservations(client, mode="testnet")
        assert native_clock["now"] < end
    if sdk_drift is not None:
        source, field = sdk_drift
        document = params["pending_orders" if source == "pending" else "balance_reservations"]
        if field == "version":
            document["payload"]["sdk"]["version"] = "0.0.0"
        else:
            hashes = document["payload"]["sdk"]["source_sha256"]
            hashes[next(iter(hashes))] = "f"*64
        document["payload_sha256"] = hashlib.sha256(canonical_bytes(document["payload"])).hexdigest()
    clock = {"now": max([inputs["after"]["payload"]["finished_ms"],
                         *[row["payload"]["finished_ms"] for row in inputs["wallets"]],
                         *[row["observed_ms"] for row in inputs["executions"]]])+10}
    for module in ("Trade.NativeMarketEvidence", "Trade.NativeAdmission", "Trade.NativeCurrentComponents",
                   "Trade.AccountRiskStore", "Trade.NativeAccountCheck"):
        monkeypatch.setattr(module+".utc_now_ms", lambda: clock["now"])
    prices = {row["instrument_id"]: row["mark_price"] for row in inputs["after"]["payload"]["positions"]}
    def mark(options):
        assert not db.db.conn.in_transaction
        instrument = options["symbol" if venue == "binance" else "instId"]
        clock["now"] += 5
        if venue == "binance":
            return {"symbol": instrument, "markPrice": prices[instrument], "time": clock["now"]-5}
        return {"code": "0", "data": [{"instId": instrument, "instType": "SWAP", "markPx": prices[instrument], "ts": str(clock["now"]-5)}]}
    def book(options):
        assert not db.db.conn.in_transaction
        instrument = options["symbol" if venue == "binance" else "instId"]
        from decimal import Decimal
        price = Decimal(prices[instrument])
        clock["now"] += 5
        if venue == "binance":
            return {"symbol": instrument, "bidPrice": str(price-1), "askPrice": str(price+1), "bidQty": "1", "askQty": "1", "time": clock["now"]-5}
        return {"code": "0", "data": [{"bids": [[str(price-1), "10", "0", "1"]], "asks": [[str(price+1), "10", "0", "1"]],
                                         "ts": str(clock["now"]-5), "seqId": 1}]}
    monkeypatch.setattr(client, "fapiPublicGetPremiumIndex" if venue == "binance" else "publicGetPublicMarkPrice", mark)
    monkeypatch.setattr(client, "fapiPublicGetTickerBookTicker" if venue == "binance" else "publicGetMarketBooks", book)
    markets = [trade._market_contract(row["symbol"])[0] for row in inputs["after"]["payload"]["markets"]]
    request = save_sources(db, params)
    check = db.reconcile_native_account(**request)
    assert check["payload"]["report"]["payload"]["status"] == "matched_observations"
    check_id = hashlib.sha256(canonical_bytes(check)).hexdigest()
    market = collect_native_market_evidence(client, markets, mode="testnet")
    clock["now"] += 10
    return {"api": api, "db": db, "client": client, "check": check, "clock": clock, "trade": trade, "key": key,
            "params": params, "request": request, "inputs": inputs,
            "arguments": {"mode": "testnet", "markets": markets, "account_context": params["account_context"],
                          "check_id": check_id, "market_evidence": market, "policy": component_policy()}}


def assert_current(case):
    return case["api"].assert_native_components_current(case["db"], case["client"], **case["arguments"])


def exact_policy(case):
    now = case["clock"]["now"]
    saved = case["check"]["payload"]["inputs"]
    market = case["arguments"]["market_evidence"]["payload"]
    role_rows = {"account": [saved["after"]["payload"]], "wallet": [row["payload"] for row in saved["wallets"]],
                 "execution": [{"started_ms": row["observed_ms"], "finished_ms": row["observed_ms"]} for row in saved["executions"]],
                 "open_orders": [saved["pending"]["payload"]], "balance": [saved["balance"]["payload"]]}
    policy, starts, anchors = component_policy(), [market["started_ms"]], []
    for role, rows in role_rows.items():
        policy["max_age_ms"][role] = max(now-row["started_ms"] for row in rows)
        policy["max_observation_span_ms"][role] = max(row["finished_ms"]-row["started_ms"] for row in rows)
        starts.extend(row["started_ms"] for row in rows)
        anchors.extend(row["started_ms"] for row in rows)
    for role in ("mark", "book"):
        policy["max_age_ms"][role] = max(now-min(row[role]["started_ms"], row[role]["source_ms"]) for row in market["observations"])
        anchors.extend(row[role]["source_ms"] for row in market["observations"])
    policy["max_observation_span_ms"]["market"] = market["finished_ms"]-market["started_ms"]
    policy["max_observation_span_ms"]["total"] = now-min(starts)
    policy["max_source_skew_ms"] = max(anchors)-min(anchors)
    return policy


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mode,side", [(mode, side) for mode in ("one_way", "hedged") for side in (True, False)])
def test_joint_current_use_covers_nonempty_pending_native_margin_and_all_ledger_without_writes(store, tmp_path, monkeypatch, venue, mode, side):
    db, _ = store
    case = current_case(db, tmp_path, monkeypatch, venue, mode=mode, side=side)
    function = getattr(case["api"], "assert_native_components_current", None)
    assert callable(function), "joint current component assertion is not implemented"
    changes, source = db.db.conn.total_changes, canonical_bytes(case["arguments"])
    assert assert_current(case) is None
    assert db.db.conn.total_changes == changes and canonical_bytes(case["arguments"]) == source
    assert len(case["trade"].exchange.created) == 3
    assert db.get_account_check(case["arguments"]["check_id"]) == case["check"]
    assert case["check"]["payload"]["report"]["payload"]["native_admission_verified"] is False


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("role", ["account", "mark", "book", "wallet", "execution", "open_orders", "balance"])
def test_every_source_age_accepts_its_exact_bound_and_rejects_one_millisecond_less(store, tmp_path, monkeypatch, venue, role):
    db, _ = store
    case = current_case(db, tmp_path, monkeypatch, venue)
    policy = case["arguments"]["policy"] = exact_policy(case)
    assert assert_current(case) is None
    assert policy["max_age_ms"][role] > 0
    policy["max_age_ms"][role] -= 1
    with pytest.raises(CChanException):
        assert_current(case)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("field,role", [("max_observation_span_ms", "market"), ("max_observation_span_ms", "total"), (None, "max_source_skew_ms")])
def test_sources_share_total_span_and_skew_instead_of_separate_passing_subgroups(store, tmp_path, monkeypatch, venue, field, role):
    db, _ = store
    case = current_case(db, tmp_path, monkeypatch, venue)
    policy = case["arguments"]["policy"] = exact_policy(case)
    assert assert_current(case) is None
    target = policy if field is None else policy[field]
    assert target[role] > 0
    target[role] -= 1
    with pytest.raises(CChanException):
        assert_current(case)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["mode", "missing_market", "source_sha", "public_route", "private_account"])
def test_joint_binding_refuses_context_pool_version_and_public_route_drift(store, tmp_path, monkeypatch, venue, damage):
    db, _ = store
    case = current_case(db, tmp_path, monkeypatch, venue)
    assert assert_current(case) is None
    if damage == "mode":
        case["arguments"]["mode"] = "live"
    elif damage == "missing_market":
        case["arguments"]["markets"].pop()
    elif damage == "source_sha":
        case["arguments"]["market_evidence"]["payload_sha256"] = "0"*64
    elif damage == "public_route":
        case["client"].urls["api"]["fapiPublic" if venue == "binance" else "rest"] = "https://wrong.example.invalid"
    else:
        method = "fapiPrivateV3GetBalance" if venue == "binance" else "privateGetAccountConfig"
        get = getattr(case["client"], method)
        def wrong(options):
            raw = get(options)
            for row in (raw if venue == "binance" else raw["data"]):
                row["accountAlias" if venue == "binance" else "uid"] = "other-native-account"
            return raw
        monkeypatch.setattr(case["client"], method, wrong)
    changes = db.db.conn.total_changes
    with pytest.raises(CChanException):
        assert_current(case)
    assert db.db.conn.total_changes == changes


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_current_private_reads_are_never_performed_in_caller_owned_transaction(store, tmp_path, monkeypatch, venue):
    db, _ = store
    case = current_case(db, tmp_path, monkeypatch, venue)
    method = "fapiPrivateV3GetBalance" if venue == "binance" else "privateGetAccountConfig"
    monkeypatch.setattr(case["client"], method, lambda options: pytest.fail("private I/O under caller's writer lock"))
    with db.db.transaction():
        with pytest.raises(CChanException):
            assert_current(case)
        assert db.db.conn.in_transaction


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["freeze", "ledger", "input_packet", "delay"])
def test_private_binding_latency_and_other_connection_changes_are_rechecked(store, tmp_path, monkeypatch, venue, damage):
    from Trade.db_util import CChanDB
    db, conf = store
    case = current_case(db, tmp_path, monkeypatch, venue)
    case["arguments"]["policy"] = exact_policy(case)
    other = CChanDB(db_conf=conf)
    method = "fapiPrivateV3GetBalance" if venue == "binance" else "privateGetAccountConfig"
    get, calls = getattr(case["client"], method), []
    def changed(options):
        assert not db.db.conn.in_transaction
        if not calls:
            calls.append(1)
            if damage == "freeze":
                other.reconcile_native_account(**{**case["request"], "wallet_ids": []})
            elif damage == "ledger":
                other.db.execute("UPDATE chan_trade SET current_qty=9 WHERE id=?", (case["key"],))
            elif damage == "input_packet":
                case["arguments"]["policy"]["max_age_ms"]["balance"] += 100
            else:
                case["clock"]["now"] += 1
        return get(options)
    monkeypatch.setattr(case["client"], method, changed)
    try:
        with pytest.raises(CChanException):
            assert_current(case)
        assert calls == [1]
        if damage == "ledger":
            assert db.get_record(case["key"])["current_qty"] == 9
        assert len(case["trade"].exchange.created) == 3
    finally:
        other.close()


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_final_use_time_includes_last_database_commit_latency(store, tmp_path, monkeypatch, venue):
    from contextlib import contextmanager
    db, _ = store
    case = current_case(db, tmp_path, monkeypatch, venue)
    case["arguments"]["policy"] = exact_policy(case)
    original, exits = db.db.transaction, []
    @contextmanager
    def delayed():
        with original():
            yield
        exits.append(1)
        if len(exits) == 2:
            case["clock"]["now"] += 1
    monkeypatch.setattr(db.db, "transaction", delayed)
    with pytest.raises(CChanException):
        assert_current(case)
    assert exits == [1, 1] and not db.db.conn.in_transaction


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("role", ["open_orders", "balance"])
def test_independent_pending_and_balance_span_budgets_use_actual_nonzero_collector_windows(store, tmp_path, monkeypatch, venue, role):
    db, _ = store
    case = current_case(db, tmp_path, monkeypatch, venue, timed_native=True)
    policy = case["arguments"]["policy"] = exact_policy(case)
    assert policy["max_observation_span_ms"][role] > 0
    assert assert_current(case) is None
    policy["max_observation_span_ms"][role] -= 1
    with pytest.raises(CChanException):
        assert_current(case)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("source", ["pending", "balance"])
@pytest.mark.parametrize("field", ["version", "source_sha256"])
def test_self_consistent_historical_source_sdk_cannot_replace_current_client_binding(store, tmp_path, monkeypatch, venue, source, field):
    db, _ = store
    case = current_case(db, tmp_path, monkeypatch, venue, sdk_drift=(source, field))
    assert case["check"]["payload"]["report"]["payload"]["status"] == "matched_observations"
    with pytest.raises(CChanException):
        assert_current(case)


def collect_later(case, monkeypatch, venue, source, *, same_clock=False, reimport=False):
    client, clock, params = case["client"], case["clock"], case["params"]
    if source in {"pending", "balance"}:
        from Trade.NativeBalanceReservations import collect_native_balance_reservations
        from Trade.NativePendingOrders import collect_native_pending_orders
        module = "Trade.NativePendingOrders" if source == "pending" else "Trade.NativeBalanceReservations"
        selected = params["pending_orders" if source == "pending" else "balance_reservations"]
        if same_clock:
            clock = {"now": selected["payload"]["finished_ms"]}
            method = (("fapiPrivateGetOpenOrders" if venue == "binance" else "privateGetTradeOrdersPending") if source == "pending" else
                      ("fapiPrivateV3GetAccount" if venue == "binance" else "privateGetAccountBalance"))
            get = getattr(client, method)
            def distinct(options):
                raw = get(options)
                if source == "pending":
                    (raw if venue == "binance" else raw["data"])[0]["price" if venue == "binance" else "px"] = "101"
                else:
                    account = raw if venue == "binance" else raw["data"][0]
                    account["assets" if venue == "binance" else "details"][0]["availableBalance" if venue == "binance" else "availEq"] = "900"
                return raw
            monkeypatch.setattr(client, method, distinct)
        monkeypatch.setattr(module+".utc_now_ms", lambda: clock["now"])
        document = (collect_native_pending_orders(client, case["arguments"]["markets"], mode="testnet") if source == "pending" else
                    collect_native_balance_reservations(client, mode="testnet"))
        return case["db"].store_native_account_observation(document)
    if source == "wallet":
        from Trade.AccountSources import collect_wallet_scan
        monkeypatch.setattr("Trade.AccountSources.utc_now_ms", lambda: clock["now"])
        p = case["inputs"]["wallets"][0]["payload"]
        return case["db"].store_account_evidence(collect_wallet_scan(client, mode="testnet", start_ms=p["start_ms"], end_ms=p["end_ms"]))
    from Trade.ExecutionFacts import collect_execution_scan
    from Trade.AccountIdentity import observe_account_context
    from .test_execution_facts import NativeSources
    monkeypatch.setattr("Trade.ExecutionFacts.utc_now_ms", lambda: clock["now"])
    p = case["inputs"]["executions"][0]["receipt"]["payload"]
    rows = [copy.deepcopy(row["raw"]) for row in p["facts"] if row["kind"] == "trade"]
    funding = [copy.deepcopy(row["raw"]) for row in p["facts"] if row["kind"] == "funding"]
    document = collect_execution_scan(NativeSources(venue, rows, funding), p["market"], account_scope=p["account_scope"],
                                      mode="testnet", start_ms=p["start_ms"], end_ms=p["end_ms"]+(0 if reimport else 1))
    context = observe_account_context(client, "testnet")
    observed = {"before": context, "after": context, "started_ms": clock["now"], "finished_ms": clock["now"]}
    case["db"].store_execution_scan(document, account_observation=observed)
    return document["payload_sha256"]


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("source,same_clock", [(source, False) for source in ("pending", "balance", "wallet", "execution")]+[("pending", True), ("balance", True)])
def test_known_newer_or_same_clock_distinct_unintegrated_source_invalidates_current_check(store, tmp_path, monkeypatch, venue, source, same_clock):
    db, _ = store
    case = current_case(db, tmp_path, monkeypatch, venue)
    assert assert_current(case) is None
    collect_later(case, monkeypatch, venue, source, same_clock=same_clock)
    changes = db.db.conn.total_changes
    with pytest.raises(CChanException):
        assert_current(case)
    assert db.db.conn.total_changes == changes
    assert db.get_account_check(case["arguments"]["check_id"]) == case["check"]  # Still valid history, not current.


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_idempotent_execution_import_keeps_original_native_observation_instead_of_refreshing_age(store, tmp_path, monkeypatch, venue):
    db, _ = store
    case = current_case(db, tmp_path, monkeypatch, venue)
    original = case["inputs"]["executions"][0]
    scan_id = collect_later(case, monkeypatch, venue, "execution", reimport=True)
    assert scan_id == original["receipt"]["payload_sha256"]
    assert db.get_execution_scan_account(scan_id)["observation"]["finished_ms"] == original["observed_ms"]
    assert assert_current(case) is None
    case["arguments"]["policy"] = exact_policy(case)
    case["arguments"]["policy"]["max_age_ms"]["execution"] -= 1
    with pytest.raises(CChanException):
        assert_current(case)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("source", ["pending", "balance", "wallet", "execution"])
def test_damaged_index_of_unselected_new_source_cannot_hide_it_from_joint_reader(store, tmp_path, monkeypatch, venue, source):
    db, _ = store
    case = current_case(db, tmp_path, monkeypatch, venue)
    key = collect_later(case, monkeypatch, venue, source)
    if source in {"pending", "balance"}:
        from Trade.NativeAccountStore import SCHEMA, TABLE
        identity, column, value = "evidence_id", "account_key", "0"*64
    elif source == "wallet":
        from Trade.AccountStore import SCHEMA, TABLE
        identity, column, value = "evidence_id", "context_id", "0"*64
    else:
        from Trade.ExecutionStore import SCHEMA, SCANS as TABLE
        identity, column, value = "scan_id", "instrument", "HIDDEN/USDT:USDT"
    db.db.execute(f"DROP TRIGGER {TABLE}_no_update")
    db.db.execute(f"UPDATE {TABLE} SET {column}=? WHERE {identity}=?", (value, key))
    db.db.execute(SCHEMA[f"{TABLE}_no_update"])
    with pytest.raises(CChanException):
        assert_current(case)


def test_component_policy_import_needs_no_sdk_config_models_or_private_io():
    current_api()
    code = """
import importlib.abc, json, sys
attempted = []
class NoOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ccxt','yaml','Config','xgboost','lightgbm','torch','sklearn','minio','PyQt6'}:
            attempted.append(fullname)
            raise ImportError('no optional dependencies or configuration')
sys.meta_path.insert(0, NoOptional())
from Trade.NativeCurrentComponents import read_native_component_policy
value = json.loads(sys.stdin.buffer.read())
assert read_native_component_policy(value) == value
assert not attempted, attempted
"""
    result = subprocess.run([sys.executable, "-c", code], input=canonical_bytes(component_policy()), capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stderr == b""
