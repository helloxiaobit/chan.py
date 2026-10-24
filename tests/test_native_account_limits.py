"""Original persisted-book projection, not proof of native collection/admission.

The capacity document is fresh synthetic *historical reader input*. It never
claims this SDK's Futures testnet signing path succeeded. Collector coverage
and its testnet refusal remain in test_native_capacity_evidence separately.
"""
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from contextlib import contextmanager
from fractions import Fraction

import ccxt
import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade import NativeCapacityEvidence as Capacity
from Trade.db_util import CChanDB
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_current_components import collect_later, current_case, exact_policy
from .test_native_margin_envelope import corners, fraction
from .test_m6_trade import make_signal


def binding_api():
    assert importlib.util.find_spec("Trade.NativeAccountLimits") is not None, "original-account book binding is missing"
    from Trade import NativeAccountLimits
    return NativeAccountLimits


def historical_capacity(case):
    market, check = case["arguments"]["market_evidence"]["payload"], case["check"]["payload"]
    units = [row["market"] for row in market["observations"]]
    settings = {row["symbol"]: row for row in check["inputs"]["after"]["payload"]["raw"]["symbol_configs"]}
    now = case["clock"]["now"]
    observations = []
    for role, instrument in Capacity._roles(units):
        endpoint, method = Capacity._REQUESTS[role]
        if role == "fee_burn":
            raw, shape = {"feeBurn": False}, "object"
        elif role == "commission":
            raw, shape = {"symbol": instrument, "makerCommissionRate": "0.0002", "takerCommissionRate": "0.0004"}, "object"
        elif role == "configuration":
            raw, shape = {**settings[instrument], "maxNotionalValue": "10000"}, "single_row_array"
        else:
            raw, shape = {"symbol": instrument, "brackets": [{"bracket": 1, "initialLeverage": 20,
                "notionalFloor": "0", "notionalCap": "10000", "maintMarginRatio": "0.005", "cum": "0"}]}, "object"
        observations.append({"role": role, "instrument_id": instrument, "endpoint": endpoint, "method": method,
            "params": {} if instrument is None else {"symbol": instrument}, "response_shape": shape, "raw": raw,
            "started_ms": now-5, "request_started_ms": now-5, "request_finished_ms": now-1, "finished_ms": now})
        # Consecutive source windows may touch but must not overlap.
        now += 5
    case["clock"]["now"] = now
    p = {"exchange_id": market["exchange_id"], "venue": "binance", "mode": market["mode"],
         "account_context": check["account_context"], "sdk": market["sdk"], "implementation_sha256": Capacity._implementation(),
         "markets": units, "observations": observations, "started_ms": observations[0]["started_ms"],
         "finished_ms": observations[-1]["finished_ms"], "requests": 3*len(observations), "source_requests": len(observations),
         "identity_requests": 2*len(observations), "coverage": "native_fee_configuration_and_raw_brackets", "source_ms": None,
         "clock_kind": "local_request_window_only", "economics_complete": False, "native_admission_verified": False,
         "fee_currency": None, "notional_coefficient_applied": False, "disclosures": list(Capacity._DISCLOSURES)}
    document = {"schema": Capacity.SCHEMA, "payload": p, "payload_sha256": hashlib.sha256(canonical_bytes(p)).hexdigest()}
    return json.loads(canonical_bytes(document))


@pytest.fixture(params=[(mode, side) for mode in ("one_way", "hedged") for side in (True, False)])
def bound_case(request, store, tmp_path, monkeypatch):
    db, conf = store
    mode, side = request.param
    case = current_case(db, tmp_path, monkeypatch, "binance", mode=mode, side=side)
    capacity = historical_capacity(case)
    monkeypatch.setattr(Capacity, "utc_now_ms", lambda: case["clock"]["now"])
    monkeypatch.setattr("Trade.NativeOrderBoundary.utc_now_ms", lambda: case["clock"]["now"])
    assert Capacity.verify_binance_capacity_evidence(capacity, max_age_ms=2000, max_observation_span_ms=2000) == capacity
    def no_http(*args, **kwargs):
        raise AssertionError("a historical account/book reader must never perform HTTP")
    monkeypatch.setattr("requests.sessions.Session.request", no_http)
    candidate = {"instrument_id": "TESTUSDT", "position_side": "BOTH" if mode == "one_way" else ("LONG" if side else "SHORT"),
        "side": "BUY" if side else "SELL", "base_quantity": "0.01", "contracts": "1", "valuation_price": "110"}
    args = {key: copy.deepcopy(case["arguments"][key]) for key in ("check_id", "market_evidence", "policy")}
    args.update(capacity_evidence=capacity, candidate=candidate, max_age_ms=2000, max_observation_span_ms=2000)
    return {**case, "bound_arguments": args, "conf": conf, "monkeypatch": monkeypatch}


def bound_api(case):
    if "binding_api" not in case:
        case["binding_api"] = binding_api()
        case["monkeypatch"].setattr(case["binding_api"], "utc_now_ms", lambda: case["clock"]["now"])
    return case["binding_api"]


def observe(case, db=None):
    return bound_api(case).observe_binance_account_limits(case["db"] if db is None else db, **case["bound_arguments"])


def test_book_comes_from_original_persisted_check_and_reopens_without_get_or_write(bound_case):
    case = bound_case
    db, saved = case["db"], case["check"]["payload"]["inputs"]
    changes, created, original = db.db.conn.total_changes, len(case["trade"].exchange.created), canonical_bytes(case["bound_arguments"])
    document = observe(case)
    p = document["payload"]
    assert document["schema"] == "chan-binance-account-limits-v1"
    assert document["payload_sha256"] == hashlib.sha256(canonical_bytes(p)).hexdigest()
    assert p["check_id"] == case["arguments"]["check_id"] and p["source_ids"] == case["check"]["payload"]["source_ids"]
    assert p["book_bound_to_original_check"] is True
    assert all(p[key] is False for key in ("source_collection_owned", "book_origin_verified", "economics_complete", "native_admission_verified"))
    assert p["coverage"] == "original_check_bound_limit_diagnostic_only"
    limits = p["limits"]["payload"]
    assert limits["status"] == "within_observed_limits" and limits["issues"] == []
    assert limits["margin_envelope"]["payload"]["native_position_count"] == len(saved["after"]["payload"]["raw"]["positions"]) == 2
    assert limits["margin_envelope"]["payload"]["native_pending_count"] == 1
    settings = [row["raw"] for row in case["bound_arguments"]["capacity_evidence"]["payload"]["observations"] if row["role"] == "configuration"]
    marks = {row["market"]["id"]: row["mark"]["price"] for row in case["arguments"]["market_evidence"]["payload"]["observations"]}
    oracle = {"positions": saved["after"]["payload"]["raw"]["positions"],
        "pending_orders": [row["raw"] for row in saved["pending"]["payload"]["orders"]],
        "mark_prices": marks, "symbol_configs": settings, "candidate": case["bound_arguments"]["candidate"]}
    for row in limits["limits"]:
        legs = ("BOTH",) if case["bound_arguments"]["candidate"]["position_side"] == "BOTH" else ("LONG", "SHORT")
        for label in ("before", "after"):
            expected = sum((corners(oracle, row["instrument_id"], leg, label == "after")[1] for leg in legs), Fraction())
            assert fraction(row[label+"_exposure_notional"]) == expected
    restarted = CChanDB(db_conf=case["conf"])
    try:
        assert observe(case, restarted) == document
    finally:
        restarted.close()
    assert db.db.conn.total_changes == changes and len(case["trade"].exchange.created) == created
    assert canonical_bytes(case["bound_arguments"]) == original


def reseal(document):
    document["payload_sha256"] = hashlib.sha256(canonical_bytes(document["payload"])).hexdigest()


@pytest.mark.parametrize("damage", ["leverage", "auto_add", "metadata_precision", "metadata_limit", "sdk_alias"])
def test_individually_valid_capacity_cannot_replace_another_configuration_or_market_identity(bound_case, damage):
    case = bound_case
    source = case["bound_arguments"]["capacity_evidence"]
    p = source["payload"]
    config = next(row["raw"] for row in p["observations"] if row["role"] == "configuration")
    if damage == "leverage":
        config["leverage"] += 1
    elif damage == "auto_add":
        config["isAutoAddMargin"] = not config["isAutoAddMargin"]
    elif damage == "metadata_precision":
        p["markets"][0]["precision"]["price"] = 0.2
    elif damage == "metadata_limit":
        p["markets"][0]["limits"]["cost"]["min"] = 6
    else:
        p["exchange_id"] = "binanceusdm"
        for row in p["markets"]:
            row["exchange"] = "binanceusdm"
        reference = ccxt.binanceusdm()
        reference.set_sandbox_mode(True)
        p["sdk"] = Capacity._sdk(reference, ccxt)
    reseal(source)
    assert Capacity.verify_binance_capacity_evidence(source, max_age_ms=2000, max_observation_span_ms=2000) == source
    changes = case["db"].db.conn.total_changes
    with pytest.raises(CChanException):
        observe(case)
    assert case["db"].db.conn.total_changes == changes


@pytest.mark.parametrize("field", ["total", "skew"])
def test_separately_fresh_capacity_and_original_book_must_also_pass_joint_time_policy(bound_case, monkeypatch, field):
    case = bound_case
    api = bound_api(case)
    monkeypatch.setattr(api, "_monotonic_ns", lambda: 0, raising=False)
    source = case["bound_arguments"]["capacity_evidence"]
    for row in [source["payload"], *source["payload"]["observations"]]:
        for key in ("started_ms", "finished_ms", "request_started_ms", "request_finished_ms"):
            if key in row:
                row[key] -= 600
    reseal(source)
    exact = exact_policy(case)
    policy = case["bound_arguments"]["policy"]
    if field == "total":
        policy["max_observation_span_ms"]["total"] = exact["max_observation_span_ms"]["total"]
    else:
        policy["max_source_skew_ms"] = exact["max_source_skew_ms"]
    # Both groups genuinely pass separately, without changing source clocks or budgets.
    assert Capacity.verify_binance_capacity_evidence(source, max_age_ms=2000, max_observation_span_ms=2000) == source
    from Trade.NativeOrderBoundary import capture_native_order_boundary
    old_group = capture_native_order_boundary(case["db"], account_context=case["arguments"]["account_context"],
        **{key: case["bound_arguments"][key] for key in ("check_id", "market_evidence", "policy")})
    assert old_group["payload"]["economics_complete"] is False
    with pytest.raises(CChanException):
        observe(case)


@pytest.mark.parametrize("target", ["candidate", "capacity", "database", "new_intent"])
def test_last_business_clock_cannot_hide_input_owner_or_real_cas_changes(bound_case, tmp_path, monkeypatch, target):
    case, api = bound_case, bound_api(bound_case)
    db, original_db, calls, replacement = case["db"], case["db"].db, [0], None
    if target == "database":
        replacement = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"replacement.db")})
        replacement_changes = replacement.db.conn.total_changes
        queries, query, query_one = [], replacement.db.query, replacement.db.query_one
        monkeypatch.setattr(replacement.db, "query", lambda *args, **kwargs: (queries.append(args), query(*args, **kwargs))[1])
        monkeypatch.setattr(replacement.db, "query_one", lambda *args, **kwargs: (queries.append(args), query_one(*args, **kwargs))[1])
    if target == "new_intent":
        new_key = db.add_signal(make_signal(code="ALT/USDT:USDT", is_buy=True))
        quantity, _, contract = case["trade"].prepare_order("ALT/USDT:USDT", 0.3, 100, record=db.get_record(new_key))
    def clock():
        calls[0] += 1
        if calls[0] == 2:
            if target == "candidate":
                case["bound_arguments"]["candidate"]["contracts"] = "999"
            elif target == "capacity":
                case["bound_arguments"]["capacity_evidence"]["payload"]["mode"] = "paper"
            elif target == "database":
                db.db = replacement.db
            else:
                assert db.acquire_open_intent(new_key, quantity, "lateCapacityIntent", order_contract=contract,
                                              position_side=contract["execution"]["position_side"])
        return case["clock"]["now"]
    monkeypatch.setattr(api, "utc_now_ms", clock)
    try:
        with pytest.raises(CChanException):
            observe(case)
        if target == "database":
            assert not queries and replacement.db.conn.total_changes == replacement_changes
        elif target == "new_intent":
            assert db.get_record(new_key)["open_attempt"] == 1
            assert db.get_record(new_key)["open_order_status"] == "created"
            assert db.get_order_history(new_key)["attempts"][-1]["events"][-1]["state"]["order_status"] == "created"
    finally:
        db.db = original_db
        if replacement is not None:
            replacement.close()


def test_positive_one_ns_of_account_observer_cost_cannot_disappear_at_exact_age(bound_case, monkeypatch):
    case, api = bound_case, bound_api(bound_case)
    case["bound_arguments"]["policy"] = exact_policy(case)
    # This case isolates use-age, not capacity-vs-book skew. Keep the separate
    # skew budget explicit; the earlier counterexamples exercise that rule.
    case["bound_arguments"]["policy"]["max_source_skew_ms"] = 2000
    monkeypatch.setattr("Trade.NativeLeverageLimits._monotonic_ns", lambda: 0)
    ticks, original_sha = {"now": 0}, api._sha
    monkeypatch.setattr(api, "_monotonic_ns", lambda: ticks["now"], raising=False)
    assert observe(case)["payload"]["book_bound_to_original_check"] is True
    def cost(value):
        result = original_sha(value)
        if "limits" in value:
            ticks["now"] += 1
        return result
    monkeypatch.setattr(api, "_sha", cost)
    with pytest.raises(CChanException):
        observe(case)


@pytest.mark.parametrize("ticks", [(False, 1), (1, False), (-1, 0), (2, 1)])
def test_core_clock_type_and_monotonicity_are_not_coerced(bound_case, monkeypatch, ticks):
    api = bound_api(bound_case)
    readings = iter(ticks)
    monkeypatch.setattr(api, "_monotonic_ns", lambda: next(readings))
    with pytest.raises(CChanException):
        observe(bound_case)


def test_last_owned_exit_cost_is_inside_shared_source_budget(bound_case, monkeypatch):
    case, api = bound_case, bound_api(bound_case)
    ticks, exits = {"now": 0}, [0]
    transaction = case["db"].db.transaction
    monkeypatch.setattr(api, "_monotonic_ns", lambda: ticks["now"])
    @contextmanager
    def costly_exit():
        with transaction():
            yield
        if not case["db"].db.conn.in_transaction:
            exits[0] += 1
            if exits[0] == 3:
                ticks["now"] += 2_001_000_000
    monkeypatch.setattr(case["db"].db, "transaction", costly_exit)
    with pytest.raises(CChanException):
        observe(case)
    assert exits[0] == 3


def test_native_leverage_string_matches_exact_account_integer_without_tolerance(bound_case):
    case = bound_case
    source = case["bound_arguments"]["capacity_evidence"]
    for row in source["payload"]["observations"]:
        if row["role"] == "configuration":
            row["raw"]["leverage"] = str(row["raw"]["leverage"])
    reseal(source)
    assert observe(case)["payload"]["limits"]["payload"]["status"] == "within_observed_limits"


@pytest.mark.parametrize("owned", [True, False])
def test_observer_cannot_adopt_or_commit_an_outer_database_transaction(bound_case, owned):
    case = bound_case
    db, before = case["db"].db, case["db"].db.conn.total_changes
    if owned:
        with db.transaction():
            with pytest.raises(CChanException):
                observe(case)
            assert db.conn.in_transaction
    else:
        db.conn.execute("BEGIN")
        try:
            with pytest.raises(CChanException):
                observe(case)
            assert db.conn.in_transaction
        finally:
            db.conn.rollback()
    assert db.conn.total_changes == before


@pytest.mark.parametrize("source", ["sticky_freeze", "newer_balance"])
def test_original_sticky_risk_and_known_newer_sources_cannot_be_bypassed(bound_case, monkeypatch, source):
    case = bound_case
    if source == "sticky_freeze":
        from Trade.NativeAccountCheck import _publish_unavailable
        with case["db"].db.transaction():
            _publish_unavailable(case["db"].db, case["arguments"]["account_context"], case["check"]["payload"]["source_ids"])
    else:
        collect_later(case, monkeypatch, "binance", "balance")
    before, histories = case["db"].db.conn.total_changes, case["db"].get_order_history(case["key"])
    with pytest.raises(CChanException):
        observe(case)
    assert case["db"].db.conn.total_changes == before
    assert case["db"].get_order_history(case["key"]) == histories


@pytest.mark.parametrize("damage", ["implementation", "internal_clone"])
def test_post_calculation_capacity_or_cloned_input_drift_does_not_become_bound_evidence(bound_case, monkeypatch, damage):
    case, api = bound_case, bound_api(bound_case)
    calculate = api.evaluate_binance_leverage_limits
    original_implementation = Capacity._implementation()
    def drift(source, **kwargs):
        result = calculate(source, **kwargs)
        if damage == "implementation":
            changed = dict(original_implementation)
            changed["Trade/NativeCapacityEvidence.py"] = "0"*64
            monkeypatch.setattr(Capacity, "_implementation", lambda: changed)
        else:
            config = next(row["raw"] for row in source["payload"]["observations"] if row["role"] == "configuration")
            config["leverage"] += 1
            reseal(source)  # Valid shape/SHA is still not the original immutable input.
        return result
    monkeypatch.setattr(api, "evaluate_binance_leverage_limits", drift)
    original, changes = canonical_bytes(case["bound_arguments"]), case["db"].db.conn.total_changes
    with pytest.raises(CChanException):
        observe(case)
    assert canonical_bytes(case["bound_arguments"]) == original
    assert case["db"].db.conn.total_changes == changes


@pytest.mark.parametrize("stage", ["first_reader_owner", "last_reader_connection"])
def test_source_reader_callbacks_cannot_make_the_observer_query_a_replacement_database(bound_case, tmp_path, monkeypatch, stage):
    case, api = bound_case, bound_api(bound_case)
    original_db, connection = case["db"].db, case["db"].db.conn
    replacement = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"reader-replacement.db")})
    trace, calls, verify = [], [0], api.verify_binance_capacity_evidence
    replacement.db.conn.set_trace_callback(trace.append)
    def changing_reader(*args, **kwargs):
        result = verify(*args, **kwargs)
        calls[0] += 1
        if calls[0] == 1 and stage == "first_reader_owner":
            case["db"].db = replacement.db
        elif calls[0] == 2 and stage == "last_reader_connection":
            original_db.conn = replacement.db.conn
        return result
    monkeypatch.setattr(api, "verify_binance_capacity_evidence", changing_reader)
    try:
        with pytest.raises(CChanException):
            observe(case)
        assert trace == []  # Even BEGIN/PRAGMA must not reach the foreign connection.
    finally:
        case["db"].db = original_db
        original_db.conn = connection
        replacement.close()


def test_core_import_needs_no_sdk_configuration_models_or_transport():
    code = """import sys
from Trade.NativeAccountLimits import observe_binance_account_limits
assert callable(observe_binance_account_limits)
assert not any(name.split('.')[0] in {'ccxt','Config','numpy','pandas','torch','xgboost'} for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout+result.stderr
