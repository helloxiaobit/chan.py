"""Original check + Last/V1 projection; still no collection or cash authority."""
import copy
from fractions import Fraction

import ccxt
import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade import NativeAccountLimits as Account
from Trade import NativeLastPrice as Last
from Trade.db_util import CChanDB
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_account_limits import bound_case, reseal
from .test_native_margin_envelope import fraction
from .test_native_current_components import exact_policy
from .test_m6_trade import make_signal


def observe(case, arguments):
    assert hasattr(Account, "observe_binance_account_order_limits_v1"), "V1 price/full-book path is not bound to original check"
    return Account.observe_binance_account_order_limits_v1(case["db"], **arguments)


def arguments(case):
    args = copy.deepcopy(case["bound_arguments"])
    c = args["candidate"]
    c.pop("valuation_price")
    c.update(order_type="MARKET", limit_price=None, post_only=False, reduce_only=False)
    cap = args["capacity_evidence"]["payload"]
    reference = getattr(ccxt, cap["exchange_id"])()
    if cap["mode"] == "testnet": reference.set_sandbox_mode(True)
    now = case["clock"]["now"]
    rows = []
    for unit in cap["markets"]:
        raw = {"symbol": unit["id"], "price": "123.12345678901234567890123456789012345678901234567", "time": now}
        rows.append({"instrument_id": unit["id"], "endpoint": Last._ENDPOINT, "method": Last._METHOD,
            "params": {"symbol": unit["id"]}, "started_ms": now, "finished_ms": now+1, **Last._values(unit["id"], raw)})
        now += 1
    p = {"exchange_id": cap["exchange_id"], "venue": "binance", "mode": cap["mode"],
        "environment": Last._environment(reference, reference, cap["mode"]), "sdk": cap["sdk"],
        "implementation_sha256": Last._implementation(), "markets": cap["markets"], "observations": rows,
        "started_ms": rows[0]["started_ms"], "finished_ms": rows[-1]["finished_ms"], "requests": len(rows),
        "coverage": "observed_native_last_transaction_prices", "economics_complete": False, "native_admission_verified": False}
    document = {"schema": Last.SCHEMA, "payload": p}
    reseal(document)
    case["clock"]["now"] = now
    case["monkeypatch"].setattr(Last, "utc_now_ms", lambda: case["clock"]["now"])
    case["monkeypatch"].setattr(Last, "_monotonic_ns", lambda: 0)
    case["monkeypatch"].setattr(Account, "utc_now_ms", lambda: case["clock"]["now"])
    args.update(last_price_evidence=copy.deepcopy(document), last_max_age_ms=2000, last_max_observation_span_ms=2000)
    return args


def test_v1_exact_price_full_book_and_native_limits_stay_on_original_check_without_write(bound_case):
    case = bound_case
    args = arguments(case)
    original, changes = canonical_bytes(args), case["db"].db.conn.total_changes
    p = observe(case, args)["payload"]
    assert p["check_id"] == args["check_id"] and p["book_bound_to_original_check"] is True
    assert p["coverage"] == "original_check_bound_client_v1_price_limits_only"
    assert all(p[key] is False for key in ("source_collection_owned", "book_origin_verified", "economics_complete", "native_admission_verified"))
    assert p["last_price_evidence_sha256"] == Last._sha(args["last_price_evidence"])
    expected = Fraction("123.12345678901234567890123456789012345678901234567")*Fraction(2003, 2000)
    assert fraction(p["limits"]["payload"]["order_price_projection"]["payload"]["assumed_price"]) == expected
    assert p["limits"]["payload"]["margin_envelope"]["payload"]["native_position_count"] == 2
    assert p["limits"]["payload"]["margin_envelope"]["payload"]["native_pending_count"] == 1
    assert case["db"].db.conn.total_changes == changes and canonical_bytes(args) == original


@pytest.mark.parametrize("damage", ["missing", "pool", "sdk", "stale", "native_time", "future", "caller_price"])
def test_last_source_and_raw_order_cannot_be_missing_swapped_or_refreshed_at_read(bound_case, damage):
    case = bound_case
    args = arguments(case)
    last = args["last_price_evidence"]
    if damage == "missing": args["last_price_evidence"] = None
    elif damage == "pool": last["payload"]["markets"][0]["precision"]["price"] = "0.2"
    elif damage == "sdk": last["payload"]["sdk"]["version"] = "unknown"
    elif damage == "stale": case["clock"]["now"] += 2001
    elif damage == "native_time":
        row = last["payload"]["observations"][0]
        row["source_ms"] = row["raw"]["time"] = row["started_ms"]-2001
    elif damage == "future": last["payload"]["finished_ms"] += 10
    else: args["candidate"]["valuation_price"] = "0"
    reseal(last)
    changes = case["db"].db.conn.total_changes
    with pytest.raises(CChanException):
        observe(case, args)
    assert case["db"].db.conn.total_changes == changes


@pytest.mark.parametrize("point", [1, 2])
def test_each_last_reader_is_followed_by_original_owner_check_before_any_sql(bound_case, tmp_path, monkeypatch, point):
    case = bound_case
    args = arguments(case)
    replacement = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"replacement-v1.db")})
    original_db, queries, calls = case["db"].db, [], {"n": 0}
    reader, query, query_one = Account.verify_binance_last_prices, replacement.db.query, replacement.db.query_one
    monkeypatch.setattr(replacement.db, "query", lambda *a, **kw: (queries.append(a), query(*a, **kw))[1])
    monkeypatch.setattr(replacement.db, "query_one", lambda *a, **kw: (queries.append(a), query_one(*a, **kw))[1])
    def change(*a, **kw):
        result = reader(*a, **kw)
        calls["n"] += 1
        if calls["n"] == point: case["db"].db = replacement.db
        return result
    monkeypatch.setattr(Account, "verify_binance_last_prices", change)
    changes = replacement.db.conn.total_changes
    try:
        with pytest.raises(CChanException):
            observe(case, args)
        assert not queries and replacement.db.conn.total_changes == changes
    finally:
        case["db"].db = original_db
        replacement.close()


@pytest.mark.parametrize("target", ["last", "candidate", "intent"])
def test_final_business_clock_cannot_hide_input_or_original_cas_drift(bound_case, monkeypatch, target):
    case, calls = bound_case, {"n": 0}
    args = arguments(case)
    if target == "intent":
        key = case["db"].add_signal(make_signal(code="ALT/USDT:USDT", is_buy=True))
        quantity, _, contract = case["trade"].prepare_order("ALT/USDT:USDT", 0.3, 100, record=case["db"].get_record(key))
    def clock():
        calls["n"] += 1
        if calls["n"] == 2:
            if target == "last": args["last_price_evidence"]["payload"]["observations"][0]["price"] = "1"
            elif target == "candidate": args["candidate"]["contracts"] = "999"
            else:
                assert case["db"].acquire_open_intent(key, quantity, "lateV1OriginalCAS", order_contract=contract,
                    position_side=contract["execution"]["position_side"])
        return case["clock"]["now"]
    monkeypatch.setattr(Account, "utc_now_ms", clock)
    with pytest.raises(CChanException):
        observe(case, args)
    if target == "intent": assert case["db"].get_record(key)["open_attempt"] == 1


def test_individually_fresh_last_native_clock_must_fit_original_group_skew(bound_case):
    case = bound_case
    args = arguments(case)
    budget = max(1000, exact_policy(case)["max_source_skew_ms"]+100)
    args["policy"]["max_source_skew_ms"] = budget
    args["policy"]["max_observation_span_ms"]["total"] = max(args["policy"]["max_observation_span_ms"]["total"], budget+500)
    args["last_max_age_ms"] = budget+100
    last = args["last_price_evidence"]
    for row in last["payload"]["observations"]:
        row["source_ms"] = row["raw"]["time"] = case["clock"]["now"]-budget-1
    reseal(last)
    assert Last.verify_binance_last_prices(last, max_age_ms=budget+100, max_observation_span_ms=2000) == last
    legacy = copy.deepcopy(case["bound_arguments"])
    legacy["policy"] = copy.deepcopy(args["policy"])
    assert Account.observe_binance_account_limits(case["db"], **legacy)["payload"]["book_bound_to_original_check"] is True
    with pytest.raises(CChanException):
        observe(case, args)


@pytest.mark.parametrize("kind,post", [("LIMIT", False), ("LIMIT", True), ("MARKET", False)])
def test_same_original_check_supports_all_six_raw_order_paths_without_price_override(bound_case, kind, post):
    case = bound_case
    args = arguments(case)
    args["candidate"].update(order_type=kind, post_only=post, limit_price=None if kind == "MARKET" else "105")
    p = observe(case, args)["payload"]
    price = Fraction("123.12345678901234567890123456789012345678901234567")*Fraction(2003, 2000)
    if kind == "LIMIT" and args["candidate"]["side"] == "BUY": price = Fraction(105)
    assert fraction(p["limits"]["payload"]["order_price_projection"]["payload"]["assumed_price"]) == price
