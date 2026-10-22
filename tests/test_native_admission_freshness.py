"""Explicit native use policy; no local proof becomes account admission."""
import copy
import hashlib
import importlib.util
import subprocess
import sys
import traceback
from decimal import Decimal

import ccxt
import pytest

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.AccountSources import collect_account_snapshot
from Trade.NativeMarketEvidence import collect_native_market_evidence
from .test_native_account_snapshot import asset, position, snapshot_client
from .test_native_market_evidence import reseal


def admission_api():
    assert importlib.util.find_spec("Trade.NativeAdmission") is not None, "native freshness policy is not implemented"
    from Trade import NativeAdmission
    return NativeAdmission


def explicit_policy():
    # Synthetic test choices only, never production defaults or user settings.
    return {"schema": "chan-native-freshness-policy-v1",
            "max_age_ms": {"account": 1000, "mark": 1000, "book": 1000, "wallet": 1100,
                           "execution": 1200, "open_orders": 1300},
            "max_observation_span_ms": {"account": 500, "market": 500, "wallet": 600,
                                        "execution": 700, "open_orders": 800, "total": 1000},
            "max_source_skew_ms": 1000}


def test_full_explicit_policy_is_copied_without_enabling_admission_or_reading_configuration():
    api = admission_api()
    source = explicit_policy()
    read = api.read_native_freshness_policy(source)
    assert read == source and read is not source
    source["max_age_ms"]["mark"] = 99
    assert read["max_age_ms"]["mark"] == 1000
    assert "native_admission_verified" not in read and "amount_tolerance" not in read


@pytest.mark.parametrize("key", ["schema", "max_age_ms", "max_observation_span_ms", "max_source_skew_ms"])
def test_missing_top_level_policy_field_has_no_implicit_fallback(key):
    api = admission_api()
    policy = explicit_policy()
    del policy[key]
    with pytest.raises(CChanException) as error:
        api.read_native_freshness_policy(policy)
    assert error.value.errcode == ErrCode.CONFIG_ERROR


@pytest.mark.parametrize("key", ["account", "mark", "book", "wallet", "execution", "open_orders"])
def test_every_source_age_is_required_even_before_all_consumers_are_integrated(key):
    api = admission_api()
    policy = explicit_policy()
    del policy["max_age_ms"][key]
    with pytest.raises(CChanException):
        api.read_native_freshness_policy(policy)


@pytest.mark.parametrize("key", ["account", "market", "wallet", "execution", "open_orders", "total"])
def test_every_observation_span_is_required(key):
    api = admission_api()
    policy = explicit_policy()
    del policy["max_observation_span_ms"][key]
    with pytest.raises(CChanException):
        api.read_native_freshness_policy(policy)


@pytest.mark.parametrize("container,key", [("max_age_ms", "mark"), ("max_observation_span_ms", "total"), (None, "max_source_skew_ms")])
@pytest.mark.parametrize("value", [None, True, False, -1, 1.0, "1000", float("nan"), float("inf"), 2**63, []])
def test_bounds_are_exact_nonnegative_integer_milliseconds_not_truthy_or_coerced(container, key, value):
    api = admission_api()
    policy = explicit_policy()
    (policy if container is None else policy[container])[key] = value
    with pytest.raises(CChanException):
        api.read_native_freshness_policy(policy)


@pytest.mark.parametrize("damage", ["wrong_schema", "ticker_alias", "amount_tolerance", "ready", "partial_dict", "not_dict"])
def test_legacy_quotes_aliases_and_caller_ready_or_tolerance_knobs_are_not_policies(damage):
    api = admission_api()
    policy = explicit_policy()
    if damage == "wrong_schema":
        policy["schema"] = "chan-market-quotes-v1"
    elif damage == "ticker_alias":
        policy["max_age_ms"]["ticker"] = 999999
    elif damage == "amount_tolerance":
        policy["amount_tolerance"] = "0.00001"
    elif damage == "ready":
        policy["native_admission_verified"] = True
    elif damage == "partial_dict":
        policy["max_age_ms"] = {}
    else:
        policy = []
    with pytest.raises(CChanException):
        api.read_native_freshness_policy(policy)


def test_explicit_zero_bounds_are_preserved_as_strict_zero_not_replaced_with_defaults():
    api = admission_api()
    policy = explicit_policy()
    for field in ("max_age_ms", "max_observation_span_ms"):
        policy[field] = dict.fromkeys(policy[field], 0)
    policy["max_source_skew_ms"] = 0
    assert api.read_native_freshness_policy(policy) == copy.deepcopy(policy)


NOW = 1_800_000_000_000


def source_bundle(monkeypatch, venue, *, mode="testnet", legs="hedged", exchange_id=None, capture=True):
    """Original collectors, complete native wire structures, two actual markets."""
    client, positions, account, settings, requests, profiles = snapshot_client(monkeypatch, venue)
    if exchange_id == "binanceusdm":
        # A real distinct credential-free SDK class, never client.id relabeling.
        usdm = ccxt.binanceusdm()
        usdm.set_sandbox_mode(True)
        for name in ("request", "fapiPrivateV3GetAccount", "fapiPrivateV3GetPositionRisk", "fapiPrivateGetSymbolConfig",
                     "fapiPrivateGetMultiAssetsMargin", "fapiPrivateV3GetBalance"):
            monkeypatch.setattr(usdm, name, getattr(client, name))
        client = usdm
    if mode == "live":
        client.set_sandbox_mode(False)
    clock = {"now": NOW-200, "profile_step": 0}
    markets, positions[:] = [], []
    old = NOW-86_400_000  # A mutation time, deliberately not a fresh-price clock.
    for base, size, factor, offset in (("TEST", "0.01", Decimal(1), 70), ("ALT", "0.1", Decimal(10), 80)):
        instrument = base+"USDT" if venue == "binance" else base+"-USDT-SWAP"
        markets.append({"exchange": client.id, "id": instrument, "symbol": base+"/USDT:USDT", "type": "swap",
                        "base": base, "quote": "USDT", "settle": "USDT", "contractSize": size,
                        "precision_mode": ccxt.TICK_SIZE, "precision": {"amount": 1.0, "price": 0.1},
                        "limits": {"amount": {"min": 1.0}, "price": {}, "cost": {"min": 5.0}}})
        for leg in (["LONG", "SHORT"] if legs == "hedged" else ["BOTH"]):
            row = position(venue, old, leg=leg, instrument=instrument)
            quantity = Decimal("0.02" if leg == "SHORT" else "0.03")*factor
            upl = -quantity*10 if leg == "SHORT" else quantity*10
            if venue == "binance":
                row.update(positionAmt=str(-quantity if leg == "SHORT" else quantity), unRealizedProfit=str(upl),
                           notional=str((-1 if leg == "SHORT" else 1)*quantity*110), isolatedMargin="0")
            else:
                row.update(posId=str(offset+(1 if leg == "SHORT" else 0)), upl=str(upl), notionalUsd=str(quantity*110))
            positions.append(row)
    unrealized = "1.1" if legs == "hedged" else "3.3"
    equity = "1001.1" if legs == "hedged" else "1003.3"
    details = [asset(venue, old, unrealized=unrealized)]
    if venue == "binance":
        details[0].update(marginBalance=equity)
        settings[:] = [{"symbol": m["id"], "marginType": "CROSSED", "leverage": 3, "isAutoAddMargin": False} for m in markets]
        account.update(assets=details, totalUnrealizedProfit=unrealized, totalMarginBalance=equity,
                       positions=[{"symbol": p["symbol"], "positionSide": p["positionSide"], "positionAmt": p["positionAmt"],
                                   "unrealizedProfit": p["unRealizedProfit"], "isolatedWallet": "0", "isolatedMargin": "0",
                                   "initialMargin": "1", "maintMargin": "0.05", "notional": p["notional"], "updateTime": old}
                                  for p in positions])
    else:
        details[0].update(eq=equity)
        account.update(details=details, upl=unrealized, totalEq=equity, uTime=str(old))

    native_methods = (["fapiPrivateV3GetAccount", "fapiPrivateV3GetPositionRisk", "fapiPrivateGetSymbolConfig", "fapiPrivateGetMultiAssetsMargin"]
                      if venue == "binance" else ["privateGetAccountBalance", "privateGetAccountPositions"])
    for name in native_methods:
        get = getattr(client, name)
        def timed(params, get=get):
            result = get(params)
            clock["now"] += 10
            return result
        monkeypatch.setattr(client, name, timed)
    profile_method = "fapiPrivateV3GetBalance" if venue == "binance" else "privateGetAccountConfig"
    profile_get = getattr(client, profile_method)
    def profile(params):
        result = profile_get(params)
        clock["now"] += clock["profile_step"]
        return result
    monkeypatch.setattr(client, profile_method, profile)
    def mark(params):
        clock["now"] += 10
        if venue == "binance":
            return {"symbol": params["symbol"], "markPrice": "110", "time": NOW-220}
        return {"code": "0", "data": [{"instId": params["instId"], "instType": "SWAP", "markPx": "110", "ts": str(NOW-220)}]}
    def book(params):
        clock["now"] += 10
        if venue == "binance":
            return {"symbol": params["symbol"], "bidPrice": "109", "askPrice": "111", "bidQty": "0.12", "askQty": "0.09", "time": NOW-210}
        return {"code": "0", "data": [{"bids": [["109", "12", "0", "2"]], "asks": [["111", "9", "0", "1"]], "ts": str(NOW-210), "seqId": 10}]}
    monkeypatch.setattr(client, "fapiPublicGetPremiumIndex" if venue == "binance" else "publicGetPublicMarkPrice", mark)
    monkeypatch.setattr(client, "fapiPublicGetTickerBookTicker" if venue == "binance" else "publicGetMarketBooks", book)
    for module in ("Trade.AccountSources", "Trade.NativeMarketEvidence", "Trade.NativeAdmission"):
        monkeypatch.setattr(module+".utc_now_ms", lambda: clock["now"], raising=False)
    unit_keys = ("exchange", "id", "symbol", "type", "base", "quote", "settle", "contractSize")
    snapshot = evidence = None
    if capture:
        snapshot = collect_account_snapshot(client, [{k: m[k] for k in unit_keys} for m in markets], mode=mode)
        evidence = collect_native_market_evidence(client, markets, mode=mode)
        clock["now"] = NOW
    return {"client": client, "mode": mode, "markets": markets, "account_snapshot": snapshot, "market_evidence": evidence,
            "policy": explicit_policy(), "clock": clock, "requests": requests, "profiles": profiles,
            "native_positions": positions, "native_account": account}


def assert_sources(api, bundle):
    fn = getattr(api, "assert_native_account_market_freshness", None)
    assert callable(fn), "native account/market use assertion is not implemented"
    return fn(bundle["client"], **{key: bundle[key] for key in ("mode", "markets", "account_snapshot", "market_evidence", "policy")})


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mode", ["testnet", "live"])
@pytest.mark.parametrize("legs", ["one_way", "hedged"])
def test_fresh_multi_market_sources_bind_original_collectors_but_return_no_admission(monkeypatch, venue, mode, legs):
    api = admission_api()
    assert callable(getattr(api, "assert_native_account_market_freshness", None)), "native source use assertion is not implemented"
    bundle = source_bundle(monkeypatch, venue, mode=mode, legs=legs)
    before = canonical_bytes({k: bundle[k] for k in ("markets", "account_snapshot", "market_evidence", "policy")})
    assert assert_sources(api, bundle) is None
    assert canonical_bytes({k: bundle[k] for k in ("markets", "account_snapshot", "market_evidence", "policy")}) == before
    assert bundle["market_evidence"]["payload"]["native_admission_verified"] is False
    assert bundle["account_snapshot"]["payload"]["economics_complete"] is False
    assert all(row["mark_ms"] is None and row["update_ms"] == NOW-86_400_000 for row in bundle["account_snapshot"]["payload"]["positions"])


def tight_bounds(bundle):
    account, market = bundle["account_snapshot"]["payload"], bundle["market_evidence"]["payload"]
    anchors = [account["started_ms"]]+[row[role]["source_ms"] for row in market["observations"] for role in ("mark", "book")]
    return {"account_age": NOW-account["started_ms"],
            "mark_age": max(NOW-row["mark"]["source_ms"] for row in market["observations"]),
            "book_age": max(NOW-row["book"]["source_ms"] for row in market["observations"]),
            "account_span": account["finished_ms"]-account["started_ms"],
            "market_span": market["finished_ms"]-market["started_ms"],
            "total_span": NOW-min(account["started_ms"], market["started_ms"]),
            "source_skew": max(anchors)-min(anchors)}


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("boundary", ["account_age", "mark_age", "book_age", "account_span", "market_span", "total_span", "source_skew"])
def test_each_explicit_bound_accepts_exact_equality_and_rejects_one_millisecond_less(monkeypatch, venue, boundary):
    api = admission_api()
    bundle = source_bundle(monkeypatch, venue)
    value = tight_bounds(bundle)[boundary]
    if boundary.endswith("_age"):
        container, key = bundle["policy"]["max_age_ms"], boundary.removesuffix("_age")
    elif boundary.endswith("_span"):
        container, key = bundle["policy"]["max_observation_span_ms"], boundary.removesuffix("_span")
    else:
        container, key = bundle["policy"], "max_source_skew_ms"
    assert value > 0
    container[key] = value
    assert assert_sources(api, bundle) is None
    container[key] = value-1
    with pytest.raises(CChanException):
        assert_sources(api, bundle)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_account_finished_time_cannot_refresh_the_first_account_read(monkeypatch, venue):
    api = admission_api()
    bundle = source_bundle(monkeypatch, venue)
    bundle["account_snapshot"]["payload"]["finished_ms"] = NOW
    reseal(bundle["account_snapshot"])
    bundle["policy"]["max_age_ms"]["account"] = 100
    with pytest.raises(CChanException):
        assert_sources(api, bundle)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_recent_mark_inside_a_long_request_does_not_refresh_old_request_start(monkeypatch, venue):
    api = admission_api()
    bundle = source_bundle(monkeypatch, venue)
    market = bundle["market_evidence"]["payload"]
    market["started_ms"] = market["observations"][0]["mark"]["started_ms"] = NOW-2000
    reseal(bundle["market_evidence"])
    bundle["policy"]["max_observation_span_ms"].update(market=3000, total=3000)
    with pytest.raises(CChanException):
        assert_sources(api, bundle)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["summary", "raw", "metadata", "account_cash", "policy", "book_tradeable"])
def test_native_profile_reads_cannot_mutate_the_already_checked_input_bytes(monkeypatch, venue, damage):
    api = admission_api()
    bundle = source_bundle(monkeypatch, venue)
    method = "fapiPrivateV3GetBalance" if venue == "binance" else "privateGetAccountConfig"
    get = getattr(bundle["client"], method)
    row = bundle["market_evidence"]["payload"]["observations"][0]
    if damage == "book_tradeable":
        book = row["book"]
        if venue == "binance":
            book["raw"]["bidPrice"] = "111"
        else:
            book["raw"]["bids"][0][0] = "111"
        book.update(bid_price="111", tradeable=False)
        reseal(bundle["market_evidence"])

    def mutate(params):
        result = get(params)
        if damage == "summary":
            row["mark"]["price"] = "999"
        elif damage == "raw":
            row["mark"]["raw"]["markPrice" if venue == "binance" else "markPx"] = "999"
        elif damage == "metadata":
            bundle["markets"][0]["precision"]["price"] = 99
        elif damage == "account_cash":
            bundle["account_snapshot"]["payload"]["assets"][0]["cash_balance"] = "999"
        elif damage == "policy":
            bundle["policy"]["max_age_ms"]["mark"] = 1
        else:
            row["book"]["tradeable"] = True
        return result
    monkeypatch.setattr(bundle["client"], method, mutate)
    with pytest.raises(CChanException):
        assert_sources(api, bundle)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["precision", "contract_size", "mode", "relabelled_environment", "relabelled_account", "software_schema"])
def test_consistent_local_hashes_do_not_replace_current_market_account_or_environment_binding(monkeypatch, venue, damage):
    api = admission_api()
    bundle = source_bundle(monkeypatch, venue)
    if damage == "precision":
        bundle["markets"][0]["precision"]["price"] = 0.2
    elif damage == "contract_size":
        bundle["markets"][0]["contractSize"] = "0.02"
    elif damage == "mode":
        bundle["mode"] = "live"
    elif damage == "relabelled_environment":
        env = bundle["market_evidence"]["payload"]["environment"]
        env["public_routes"]["fapiPublic" if venue == "binance" else "rest"] = "https://wrong.example.invalid"
        reseal(bundle["market_evidence"])
    elif damage == "relabelled_account":
        context = bundle["account_snapshot"]["payload"]["account_context"]
        context["identifier_sha256"] = "0"*64
        context["context_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in context.items() if k != "context_id"})).hexdigest()
        reseal(bundle["account_snapshot"])
    else:
        bundle["market_evidence"]["schema"] = "chan-software-entry-quotes-v1"
    with pytest.raises(CChanException):
        assert_sources(api, bundle)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_missing_market_cannot_hide_an_actual_returned_holding(monkeypatch, venue):
    api = admission_api()
    bundle = source_bundle(monkeypatch, venue)
    bundle["markets"] = [m for m in bundle["markets"] if m["base"] == "TEST"]
    unit_keys = ("exchange", "id", "symbol", "type", "base", "quote", "settle", "contractSize")
    bundle["account_snapshot"] = collect_account_snapshot(bundle["client"], [{k: m[k] for k in unit_keys} for m in bundle["markets"]], mode=bundle["mode"])
    bundle["market_evidence"] = collect_native_market_evidence(bundle["client"], bundle["markets"], mode=bundle["mode"])
    assert bundle["account_snapshot"]["payload"]["unsupported_positions"]
    with pytest.raises(CChanException):
        assert_sources(api, bundle)


def test_binance_independent_account_position_cannot_be_hidden_by_a_narrower_risk_position_channel(monkeypatch):
    api = admission_api()
    bundle = source_bundle(monkeypatch, "binance")
    bundle["markets"] = [m for m in bundle["markets"] if m["base"] == "TEST"]
    bundle["native_positions"][:] = [p for p in bundle["native_positions"] if p["symbol"] == "TESTUSDT"]
    unit_keys = ("exchange", "id", "symbol", "type", "base", "quote", "settle", "contractSize")
    bundle["account_snapshot"] = collect_account_snapshot(bundle["client"], [{k: m[k] for k in unit_keys} for m in bundle["markets"]], mode=bundle["mode"])
    bundle["market_evidence"] = collect_native_market_evidence(bundle["client"], bundle["markets"], mode=bundle["mode"])
    assert bundle["account_snapshot"]["payload"]["unsupported_positions"] == []
    assert any(p["instrument_id"] == "ALTUSDT" for p in bundle["account_snapshot"]["payload"]["native_account_positions"])
    with pytest.raises(CChanException):
        assert_sources(api, bundle)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_identity_read_latency_is_included_at_use_not_frozen_at_function_start(monkeypatch, venue):
    api = admission_api()
    bundle = source_bundle(monkeypatch, venue)
    bundle["clock"]["profile_step"] = 1000
    with pytest.raises(CChanException):
        assert_sources(api, bundle)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["public_route", "sdk", "account", "backwards_clock", "client_id"])
def test_last_profile_read_cannot_leave_a_new_environment_account_or_clock_unchecked(monkeypatch, venue, damage):
    api = admission_api()
    bundle = source_bundle(monkeypatch, venue)
    method = "fapiPrivateV3GetBalance" if venue == "binance" else "privateGetAccountConfig"
    get = getattr(bundle["client"], method)
    calls = []
    def change(params):
        result = get(params)
        calls.append(True)
        if len(calls) == 2:
            if damage == "public_route":
                bundle["client"].urls["api"]["fapiPublic" if venue == "binance" else "rest"] = "https://changed.example.invalid"
            elif damage == "sdk":
                monkeypatch.setattr(ccxt, "__version__", "0.0.0-changed")
            elif damage == "account":
                if venue == "binance":
                    for row in result:
                        row["accountAlias"] = "fake-DIFFERENT"
                else:
                    result["data"][0]["uid"] = "99999999"
            elif damage == "backwards_clock":
                bundle["clock"]["now"] = NOW-1
            else:
                bundle["client"].id = "different-exchange"
        return result
    monkeypatch.setattr(bundle["client"], method, change)
    with pytest.raises(CChanException):
        assert_sources(api, bundle)
    assert len(calls) == 2


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_revalidation_rejects_aging_sources_instead_of_caching_a_previous_result(monkeypatch, venue):
    api = admission_api()
    bundle = source_bundle(monkeypatch, venue)
    assert assert_sources(api, bundle) is None
    original = canonical_bytes({key: bundle[key] for key in ("account_snapshot", "market_evidence", "policy")})
    bundle["clock"]["now"] += 2000
    with pytest.raises(CChanException):
        assert_sources(api, bundle)
    assert canonical_bytes({key: bundle[key] for key in ("account_snapshot", "market_evidence", "policy")}) == original


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_private_identity_errors_are_redacted_without_retries_or_recollecting_money(monkeypatch, venue, capsys):
    api = admission_api()
    bundle = source_bundle(monkeypatch, venue)
    before = copy.deepcopy(bundle["requests"])
    method = "fapiPrivateV3GetBalance" if venue == "binance" else "privateGetAccountConfig"
    calls = []
    def fail(params):
        calls.append(True)
        raise ccxt.NetworkError("SECRET_PRIVATE_FRESHNESS_ACCOUNT_ERROR")
    monkeypatch.setattr(bundle["client"], method, fail)
    with pytest.raises(CChanException) as error:
        assert_sources(api, bundle)
    assert "SECRET_PRIVATE_FRESHNESS_ACCOUNT_ERROR" not in "".join(traceback.format_exception(error.type, error.value, error.tb))+str(capsys.readouterr())
    assert len(calls) == 1 and bundle["requests"] == before


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("boundary", ["account_age", "mark_age", "book_age", "account_span", "market_span", "total_span", "source_skew"])
def test_zero_use_bounds_are_enforced_not_treated_as_unset(monkeypatch, venue, boundary):
    api = admission_api()
    bundle = source_bundle(monkeypatch, venue)
    if boundary.endswith("_age"):
        bundle["policy"]["max_age_ms"][boundary.removesuffix("_age")] = 0
    elif boundary.endswith("_span"):
        bundle["policy"]["max_observation_span_ms"][boundary.removesuffix("_span")] = 0
    else:
        bundle["policy"]["max_source_skew_ms"] = 0
    with pytest.raises(CChanException):
        assert_sources(api, bundle)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("role", ["mark", "book"])
def test_every_market_clock_is_checked_not_only_the_first_candidate(monkeypatch, venue, role):
    api = admission_api()
    bundle = source_bundle(monkeypatch, venue)
    source = bundle["market_evidence"]["payload"]["observations"][1][role]
    source["source_ms"] = NOW-2000
    source["raw"]["time" if venue == "binance" else "ts"] = NOW-2000 if venue == "binance" else str(NOW-2000)
    reseal(bundle["market_evidence"])
    bundle["policy"]["max_source_skew_ms"] = 5000
    with pytest.raises(CChanException):
        assert_sources(api, bundle)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_optional_free_policy_reader_and_missing_sdk_cannot_report_native_readiness(monkeypatch, venue):
    api = admission_api()
    bundle = source_bundle(monkeypatch, venue)
    values = {key: bundle[key] for key in ("mode", "markets", "account_snapshot", "market_evidence", "policy")}
    code = """
import importlib.abc, json, sys
from types import SimpleNamespace
blocked = {'ccxt', 'xgboost', 'lightgbm', 'sklearn', 'optuna', 'yaml', 'PyQt6', 'minio', 'qcloud_cos'}
attempted = []
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            attempted.append(fullname.split('.')[0])
            raise ModuleNotFoundError('optional SDK intentionally absent')
sys.meta_path.insert(0, BlockOptional())
import Trade.NativeAdmission as api
import Trade.AccountSources as accounts
import Trade.NativeMarketEvidence as markets
from Common.ChanException import CChanException, ErrCode
values = json.loads(sys.stdin.buffer.read())
for module in (api, accounts, markets):
    module.utc_now_ms = lambda: 1800000000000
assert api.read_native_freshness_policy(values['policy']) == values['policy']
assert not attempted
try:
    api.assert_native_account_market_freshness(SimpleNamespace(id=values['markets'][0]['exchange']), **values)
except CChanException as error:
    assert error.errcode == ErrCode.TRADE_UNLOCK_FAIL
else:
    raise AssertionError('missing SDK cannot authorize a current-client observation')
assert attempted == ['ccxt']
assert not any(name.split('.')[0] in blocked for name in sys.modules)
print('optional-free policy reader and fail-closed SDK check PASS')
"""
    result = subprocess.run([sys.executable, "-c", code], input=canonical_bytes(values), capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.strip() == b"optional-free policy reader and fail-closed SDK check PASS" and result.stderr == b""


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_final_input_byte_check_time_is_included_in_freshness_not_only_network_time(monkeypatch, venue):
    api = admission_api()
    bundle = source_bundle(monkeypatch, venue)
    class ClockedPolicy(dict):
        observations = 0
        def items(self):
            self.observations += 1
            if self.observations == 2:
                # Actual canonical serializer still runs unchanged; only the
                # synthetic clock models time spent verifying the final bytes.
                bundle["clock"]["now"] += 2000
            return super().items()
    bundle["policy"] = ClockedPolicy(bundle["policy"])
    error = None
    try:
        assert_sources(api, bundle)
    except CChanException as caught:
        error = caught
    assert bundle["clock"]["now"] == NOW+2000 and bundle["policy"].observations == 2
    assert error is not None, "elapsed final input verification must not escape the use-time bounds"


@pytest.mark.parametrize("mode", ["testnet", "live"])
@pytest.mark.parametrize("legs", ["one_way", "hedged"])
def test_binanceusdm_sdk_identity_is_not_replaced_with_a_generic_binance_label(monkeypatch, mode, legs):
    api = admission_api()
    bundle = source_bundle(monkeypatch, "binance", mode=mode, legs=legs, exchange_id="binanceusdm")
    assert type(bundle["client"]) is ccxt.binanceusdm
    assert bundle["market_evidence"]["payload"]["sdk"]["exchange_class"] == "ccxt.binanceusdm.binanceusdm"
    assert {m["exchange"] for m in bundle["markets"]} == {"binanceusdm"}
    assert assert_sources(api, bundle) is None
