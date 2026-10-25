"""Owned monetary CAS; real original SDK/SQLite, bottom-only fake transport."""
import copy
import json
from contextlib import closing
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade import NativeLastPrice as Last
from Trade import NativeAccountLimits as Account
from Trade import NativeCapacityEvidence as Capacity
from Trade import NativePreparedIntent as Prepared
from Trade import NativePreparedClient as Cold
from Trade.AccountRiskStore import _sha
from Trade.NativeOrderTransition import read_native_order_transition
from Trade.db_util import CChanDB
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import capacity_case, single_case, options
from .test_native_last_price import native_last, collect as collect_last
from .test_native_prepared_last import install_last
from .test_native_standard_order_capacity import oracle
from .test_m6_trade import make_signal


def acquire(case, *, amount=.1, price=100, **changes):
    entry = getattr(Prepared, "acquire_binance_standard_prepared_intent", None)
    assert callable(entry), "actual source-owned monetary acquisition must enter the original CAS"
    return entry(case["trade"], case["key"], amount, price, **({**options(case),
        "capacity_max_age_ms": 2000, "capacity_max_observation_span_ms": 2000,
        "last_max_age_ms": 2000, "last_max_observation_span_ms": 2000} | changes))


@pytest.mark.parametrize("kind,post_only", [("limit", False), ("limit", True), ("market", False)])
def test_same_prepare_raw_sources_and_native_cash_are_bound_by_original_monetary_cas(capacity_case, monkeypatch, kind, post_only):
    case = capacity_case
    last_calls = install_last(case, monkeypatch)
    price = None if kind == "market" else 110 if case["db"].get_record(case["key"])["is_buy"] else 90
    assert acquire(case, price=price, post_only=post_only) is True
    document = read_native_order_transition(case["db"], case["key"])
    b = document["payload"]["root"]["preparation"]
    assert b["schema"] == "chan-native-prepared-intent-binding-v4"
    assert b["capacity_evidence"]["schema"] == "chan-binance-capacity-evidence-v2"
    assert b["last_price_evidence"]["schema"] == Last.SCHEMA
    assert b["monetary"]["payload"]["status"] == "within_model_capacity"
    money = b["monetary"]["payload"]
    inputs = {"candidate": money["candidate"], "market_evidence": b["components"]["payload"]["market_evidence"],
        "capacity_evidence": b["capacity_evidence"], "last_price_evidence": b["last_price_evidence"]}
    for field, expected in oracle(inputs).items():
        ratio = money["order_cost"]["payload"][field]
        assert Fraction(int(ratio["numerator"]), int(ratio["denominator"])) == expected
    assert money["standard_commission_assumption"]["native_fee_currency_verified"] is False
    assert money["native_admission_verified"] is money["economics_complete"] is False
    assert {"Trade/NativeOrderCost.py", "Trade/NativeLastPrice.py"} <= set(b["implementation_sha256"])
    assert last_calls == ["ALTUSDT", "TESTUSDT"]
    assert [name for name, _ in case["http_calls"]].count("fapiPrivateGetFeeBurn") == 1
    contract = json.loads(case["db"].get_record(case["key"])["open_order_contract"])
    assert contract["schema"] == "chan-native-client-order-v1"
    assert contract["monetary_basis_sha256"] == b["monetary"]["payload_sha256"]
    assert case["db"].get_record(case["key"])["open_attempt"] == 1
    assert len(case["created"]) == 3
    # No claim/software send until the remaining full consumers are closed.
    with pytest.raises(CChanException): case["db"].claim_order_submission(case["key"], "open")
    assert case["db"].get_record(case["key"])["open_order_status"] == "created"


@pytest.mark.parametrize("field", ["capacity_max_age_ms", "capacity_max_observation_span_ms", "last_max_age_ms", "last_max_observation_span_ms"])
@pytest.mark.parametrize("bad", [None, True, -1, "2000", 2000.5, 2**63])
def test_owned_monetary_budgets_refuse_before_any_prepare_or_source(single_case, monkeypatch, field, bad):
    case = single_case
    calls = install_last(case, monkeypatch)
    with pytest.raises(CChanException): acquire(case, **{field: bad})
    assert case["db"].get_record(case["key"])["open_attempt"] == 0 and not case["http_calls"] and not calls


@pytest.mark.parametrize("field", ["capacity_evidence", "last_price_evidence", "check_id", "source", "candidate", "cost", "fee_currency", "passed", "checked_ms"])
def test_money_acquire_cannot_accept_caller_authority_or_sources(single_case, field):
    with pytest.raises(TypeError): acquire(single_case, **{field: True})
    assert not single_case["http_calls"]


def test_initial_monetary_calculation_cost_is_not_lost_before_the_later_cas_timer(single_case, monkeypatch):
    case = single_case
    install_last(case, monkeypatch)
    original, elapsed, calls = Account.calculate_binance_order_cost_v1, [0], []
    def slow(**kwargs):
        result = original(**kwargs)
        calls.append(1)
        if len(calls) == 1: elapsed[0] += 2_001_000_000
        return result
    monkeypatch.setattr(Account, "calculate_binance_order_cost_v1", slow)
    monkeypatch.setattr(Prepared, "_monotonic_ns", lambda: elapsed[0])
    with pytest.raises(CChanException): acquire(case)
    assert calls and case["db"].get_record(case["key"])["open_attempt"] == 0


def test_monetary_history_survives_age_but_current_cannot_borrow_the_intent_clock(single_case, monkeypatch):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    original = read_native_order_transition(case["db"], case["key"])
    row, changes, calls = case["db"].get_record(case["key"]), case["db"].db.conn.total_changes, list(case["http_calls"])
    case["clock"]["now"] += 2001
    assert read_native_order_transition(case["db"], case["key"]) == original
    with case["db"].db.transaction(), pytest.raises(CChanException):
        Prepared.assert_native_prepared_intent_current(case["trade"], case["key"])
    assert case["db"].get_record(case["key"]) == row and case["db"].db.conn.total_changes == changes
    assert case["http_calls"] == calls


@pytest.mark.parametrize("difference", [Fraction(0), -Fraction(1, 10**40)])
def test_original_cas_uses_exact_native_available_without_deducting_old_reservations_again(single_case, monkeypatch, difference):
    case = single_case
    install_last(case, monkeypatch)
    # Actual prepared BUY .3 at 100, native leverage 3, maker .0002, mark
    # 120: margin 10, loss 0, fee .006. Old pending IM is already reserved.
    target = Fraction("10.006")+difference
    with localcontext() as precision:
        precision.prec = 100
        amount = format(Decimal(target.numerator)/Decimal(target.denominator), "f")
    assert Fraction(amount) == target
    asset = next(row for row in case["account_raw"]["assets"] if row["asset"] == "USDT")
    asset["availableBalance"] = case["account_raw"]["availableBalance"] = amount
    if difference == 0:
        assert acquire(case, amount=.3, post_only=True)
        money = read_native_order_transition(case["db"], case["key"])["payload"]["root"]["preparation"]["monetary"]["payload"]
        assert money["order_cost"]["payload"]["available_after_cost"] == {"numerator": "0", "denominator": "1"}
    else:
        with pytest.raises(CChanException): acquire(case, amount=.3, post_only=True)
        assert case["db"].get_record(case["key"])["open_attempt"] == 0
        assert case["db"].get_account_risk_state(case["before"]["payload"]["account_context"])["frozen"] is True


@pytest.mark.parametrize("damage", ["fee_burn", "unknown_fee", "non_candidate_limit", "missing_capacity", "missing_last"])
def test_owned_source_failures_cannot_downgrade_the_monetary_intent(single_case, monkeypatch, damage):
    case = single_case
    install_last(case, monkeypatch)
    if damage.startswith("missing_"):
        module, name = ((Capacity, "collect_binance_standard_capacity_evidence") if damage == "missing_capacity"
                        else (Prepared, "collect_prepared_binance_last_prices"))
        original = getattr(module, name)
        def missing(*args, **kwargs):
            original(*args, **kwargs)
            return None
        monkeypatch.setattr(module, name, missing)
    else:
        transport, touched = case["client"].session.request, []
        def changed(method, url, **kwargs):
            response = transport(method, url, **kwargs)
            if "/feeBurn?" in url and damage == "fee_burn":
                raw = json.loads(response.text)
                raw["feeBurn"] = True
            elif "/commissionRate?" in url and damage == "unknown_fee":
                raw = json.loads(response.text)
                raw["extraTaxRate"] = "0"
            elif "/symbolConfig?" in url and "symbol=ALTUSDT" in url and damage == "non_candidate_limit":
                raw = json.loads(response.text)
                raw[0]["maxNotionalValue"] = "0.0000001"
            else:
                return response
            touched.append(1)
            response._content = json.dumps(raw).encode()
            return response
        monkeypatch.setattr(case["client"].session, "request", changed)
    with pytest.raises(CChanException): acquire(case)
    assert case["db"].get_record(case["key"])["open_attempt"] == 0
    assert case["db"].get_order_history(case["key"])["attempts"] == []
    assert case["db"].get_account_risk_state(case["before"]["payload"]["account_context"])["frozen"] is True
    assert len(case["created"]) == 3
    if not damage.startswith("missing_"): assert touched


@pytest.mark.parametrize("stage", ["sql", "reference", "expired_after_reference", "forged_context"])
def test_monetary_intent_retains_original_atomic_cas_rollback(single_case, monkeypatch, stage):
    case = single_case
    install_last(case, monkeypatch)
    execute, touched = case["db"].db.execute, []
    def changed(sql, params=()):
        if sql.startswith("UPDATE "+case["db"].table+" SET status='submitted'") and stage == "sql":
            touched.append(1)
            raise RuntimeError("PRIVATE_MONEY_CAS_FAILURE")
        if sql.startswith("INSERT INTO chanpy_native_order_transitions"):
            touched.append(1)
            if stage == "reference": raise RuntimeError("PRIVATE_MONEY_REFERENCE_FAILURE")
            result = execute(sql, params)
            if stage == "expired_after_reference": case["clock"]["now"] += 2001
            return result
        return execute(sql, params)
    monkeypatch.setattr(case["db"].db, "execute", changed)
    if stage == "forged_context":
        writer = case["db"]._order_write
        def forged(*args, **kwargs):
            touched.append(1)
            kwargs["native_preparation"] = {"monetary_verified": True}
            return writer(*args, **kwargs)
        monkeypatch.setattr(case["db"], "_order_write", forged)
    with pytest.raises(CChanException) as caught: acquire(case)
    assert touched and "PRIVATE_" not in str(caught.value)
    assert case["db"].get_record(case["key"])["open_attempt"] == 0
    assert case["db"].get_order_history(case["key"])["attempts"] == []
    assert case["db"].db.query("SELECT * FROM chanpy_native_order_transitions") == []


@pytest.mark.parametrize("point", ["after_intent", "current"])
def test_final_monetary_work_cannot_outlive_its_complete_implementation_closure(single_case, monkeypatch, point):
    case = single_case
    install_last(case, monkeypatch)
    if point == "current": assert acquire(case)
    capacity, implementation, drift = Account._standard_capacity, Last._implementation, []
    def changed(*args, **kwargs):
        result = capacity(*args, **kwargs)
        if kwargs.get("checked_ms") is None and case["db"].get_record(case["key"])["open_attempt"]:
            drift.append(1)
        return result
    def observed_implementation():
        return implementation() | ({"Trade/NativeLastPrice.py": "0"*64} if drift else {})
    monkeypatch.setattr(Account, "_standard_capacity", changed)
    monkeypatch.setattr(Last, "_implementation", observed_implementation)
    with pytest.raises(CChanException):
        if point == "current":
            with case["db"].db.transaction(): Prepared.assert_native_prepared_intent_current(case["trade"], case["key"])
        else: acquire(case)
    assert drift
    if point == "after_intent": assert case["db"].get_record(case["key"])["open_attempt"] == 0


def test_monetary_callback_replacement_database_receives_no_sql(single_case, tmp_path, monkeypatch):
    case = single_case
    install_last(case, monkeypatch)
    original_db, calculate, touched = case["db"].db, Account.calculate_binance_order_cost_v1, []
    with closing(CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"monetary-replacement.db")})) as replacement:
        changes, queries = replacement.db.conn.total_changes, []
        replacement.db.conn.set_trace_callback(queries.append)
        def swapped(**kwargs):
            result = calculate(**kwargs)
            touched.append(1)
            case["db"].db = replacement.db
            return result
        monkeypatch.setattr(Account, "calculate_binance_order_cost_v1", swapped)
        try:
            with pytest.raises(CChanException): acquire(case)
        finally:
            case["db"].db = original_db
        assert touched and queries == [] and replacement.db.conn.total_changes == changes
        assert case["db"].get_record(case["key"])["open_attempt"] == 0


@pytest.mark.parametrize("damage", ["cost", "assumption", "cash_basis", "candidate", "permission", "missing_last", "legacy_capacity"])
def test_history_recomputes_the_whole_monetary_body_even_when_hashes_and_contract_are_resealed(single_case, monkeypatch, damage):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    root = copy.deepcopy(read_native_order_transition(case["db"], case["key"])["payload"]["root"])
    attempt = copy.deepcopy(case["db"].get_order_history(case["key"])["attempts"][0])
    binding, money = root["preparation"], root["preparation"]["monetary"]
    payload = money["payload"]
    if damage == "cost":
        payload["order_cost"]["payload"]["total_cost"] = {"numerator": "0", "denominator": "1"}
        payload["order_cost"]["payload_sha256"] = _sha(payload["order_cost"]["payload"])
    elif damage == "assumption": payload["standard_commission_assumption"]["native_fee_currency_verified"] = True
    elif damage == "cash_basis": payload["native_cash_basis"]["balance_source_id"] = "0"*64
    elif damage == "candidate": payload["candidate"]["side"] = "SELL"
    elif damage == "permission": payload["native_admission_verified"] = True
    elif damage == "missing_last": binding.pop("last_price_evidence")
    else:
        source = binding["capacity_evidence"]
        source["schema"] = Capacity.SCHEMA
        source["payload"].pop("field_policy")
        for row in source["payload"]["observations"]: row.pop("uninterpreted_paths")
        source["payload_sha256"] = _sha(source["payload"])
    money["payload_sha256"] = _sha(payload)
    attempt["identity"]["order_contract"] = Prepared._contract(binding)
    calls, changes = list(case["http_calls"]), case["db"].db.conn.total_changes
    with case["db"].db.transaction(), pytest.raises(CChanException):
        Prepared.validate_stored_preparation(case["db"], root, attempt)
    assert case["http_calls"] == calls and case["db"].db.conn.total_changes == changes


def test_real_late_competing_original_intent_is_not_ignored_as_owned_monetary_delta(single_case, monkeypatch):
    case = single_case
    install_last(case, monkeypatch)
    other = case["db"].add_signal(make_signal(code="ALT/USDT:USDT", is_buy=True))
    quantity, _, contract = case["trade"].prepare_order("ALT/USDT:USDT", .3, 100, record=case["db"].get_record(other))
    calculate, touched = Account.calculate_binance_order_cost_v1, []
    def raced(**kwargs):
        result = calculate(**kwargs)
        if not touched:
            touched.append(1)
            assert case["db"].acquire_open_intent(other, quantity, "lateMonetaryCAS", order_contract=contract,
                position_side=contract["execution"]["position_side"])
        return result
    monkeypatch.setattr(Account, "calculate_binance_order_cost_v1", raced)
    with pytest.raises(CChanException): acquire(case)
    assert touched and case["db"].get_record(other)["open_attempt"] == 1
    assert case["db"].get_record(case["key"])["open_attempt"] == 0
    assert len(case["created"]) == 3


@pytest.mark.parametrize("damage", ["none", "expired", "implementation"])
def test_actual_cold_monetary_reconstitution_keeps_original_sources_and_full_code_closure(single_case, monkeypatch, damage):
    case = single_case
    transport = case["client"].session.request
    def cold_transport(session, method, url, **kwargs):
        assert session is case["trade"].exchange.session
        return transport(method, url, **kwargs)
    monkeypatch.setattr("requests.sessions.Session.request", cold_transport)
    monkeypatch.setattr(Cold, "utc_now_ms", lambda: case["clock"]["now"])
    monkeypatch.setattr(Cold, "_monotonic_ns", lambda: 0)
    case["trade"].exchange = None
    assert Cold.initialize_native_prepared_client(case["trade"], case["key"], instrument_max_age_ms=2000,
                                                 instrument_max_observation_span_ms=2000) is None
    case["client"] = first = case["trade"].exchange
    install_last(case, monkeypatch)
    assert acquire(case)
    original = read_native_order_transition(case["db"], case["key"])
    row, calls = case["db"].get_record(case["key"]), list(case["http_calls"])
    case["trade"].exchange = None
    if damage == "expired": case["clock"]["now"] += 2001
    if damage == "implementation":
        implementation, drift = Last._implementation, []
        def late_tick():
            drift.append(1)
            return 0
        monkeypatch.setattr(Last, "_implementation", lambda: implementation() | ({"Trade/NativeLastPrice.py": "0"*64} if drift else {}))
        monkeypatch.setattr(Cold, "_monotonic_ns", late_tick)
    if damage == "none":
        assert Cold.initialize_native_prepared_client(case["trade"], case["key"], instrument_max_age_ms=2000,
                                                      instrument_max_observation_span_ms=2000) is None
        assert case["trade"].exchange is not first
        with case["db"].db.transaction(): Prepared.assert_native_prepared_intent_current(case["trade"], case["key"])
    else:
        with pytest.raises(CChanException):
            Cold.initialize_native_prepared_client(case["trade"], case["key"], instrument_max_age_ms=2000,
                                                   instrument_max_observation_span_ms=2000)
        assert case["trade"].exchange is None
        if damage == "implementation":
            assert drift
            with pytest.raises(CChanException): read_native_order_transition(case["db"], case["key"])
            monkeypatch.setattr(Last, "_implementation", implementation)
        else: assert case["http_calls"] == calls
    assert read_native_order_transition(case["db"], case["key"]) == original
    assert case["db"].get_record(case["key"]) == row
    assert not any(name in {"fapiPrivateGetFeeBurn", "fapiPrivateGetCommissionRate"} for name, _ in case["http_calls"][len(calls):])


def test_current_monetary_source_snapshot_work_is_inside_the_use_time_budget(single_case, monkeypatch):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    read, elapsed, touched = Prepared._sources_snapshot, [0], []
    def slow(*args, **kwargs):
        result = read(*args, **kwargs)
        touched.append(1)
        elapsed[0] += 2_001_000_000
        return result
    monkeypatch.setattr(Prepared, "_sources_snapshot", slow)
    monkeypatch.setattr(Prepared, "_monotonic_ns", lambda: elapsed[0])
    with case["db"].db.transaction(), pytest.raises(CChanException):
        Prepared.assert_native_prepared_intent_current(case["trade"], case["key"])
    assert touched


def test_final_monetary_calculation_respects_the_instrument_budget_too(single_case, monkeypatch):
    case = single_case
    install_last(case, monkeypatch)
    assert acquire(case)
    root = copy.deepcopy(read_native_order_transition(case["db"], case["key"])["payload"]["root"])
    binding = root["preparation"]
    binding["instrument_policy"]["max_age_ms"] = case["clock"]["now"]-binding["instruments"]["payload"]["started_ms"]
    with case["db"].db.transaction(): Prepared._windows(case["db"], binding, root["boundary"])
    samples = iter((0, 1))
    monkeypatch.setattr(Prepared, "_monotonic_ns", lambda: next(samples))
    with case["db"].db.transaction(), pytest.raises(CChanException):
        Prepared._windows(case["db"], binding, root["boundary"])


def test_private_last_history_does_not_renew_or_consult_a_current_clock(native_last, monkeypatch):
    case = native_last
    source = collect_last(case)
    frozen = canonical_bytes(source)
    at = case.clock["now"]
    entry = getattr(Last, "_verify_binance_last_prices_at", None)
    assert callable(entry), "historical monetary reads need the original immutable intent time"
    case.clock["now"] += 1001
    with pytest.raises(CChanException): Last.verify_binance_last_prices(source, max_age_ms=1000, max_observation_span_ms=1000)
    def no_clock(): raise AssertionError("history must not read or replace the current clock")
    monkeypatch.setattr(Last, "utc_now_ms", no_clock)
    monkeypatch.setattr(Last, "_monotonic_ns", no_clock)
    assert entry(source, checked_ms=at, max_age_ms=1000, max_observation_span_ms=1000) is source
    assert canonical_bytes(source) == frozen
    with pytest.raises(TypeError): Last.verify_binance_last_prices(source, checked_ms=at, max_age_ms=1000, max_observation_span_ms=1000)
