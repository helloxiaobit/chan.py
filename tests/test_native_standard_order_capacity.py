"""Original check and actual prepared SDK sources; bottom-only fake HTTP."""
import copy
import json
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade import NativeAccountLimits as Account
from Trade import NativeCapacityEvidence as Capacity
from Trade import NativePreparation as Prepare
from Trade import NativePreparedIntent as Prepared
from Trade.db_util import CChanDB
from .test_execution_store import store
from .test_native_admission_interval import explicit_path_environment
from .test_native_capacity_prepared_intent import capacity_case, single_case
from .test_native_prepared_last import install_last
from .test_native_capacity_evidence import reseal
from .test_m6_trade import make_signal


def assemble(case, monkeypatch, *, price=100, post_only=False, amount=.1):
    install_last(case, monkeypatch)
    context = Prepare._capture_native_prepare_context(case["trade"], case["key"], amount, price, post_only=post_only)
    identity = json.loads(Prepare._PREPARED[context][1])["payload"]
    capacity = Capacity.collect_binance_standard_capacity_evidence(case["client"], case["units"], mode=case["trade"].mode,
        max_age_ms=2000, max_observation_span_ms=2000)
    components = Prepared.collect_and_check_native_components(case["db"], case["client"], mode=case["trade"].mode,
        markets=capacity["payload"]["markets"], before_id=case["before_id"], account_scope="standard-cost-fixture", policy=case["policy"])
    last = Prepared.collect_prepared_binance_last_prices(case["trade"], context, max_age_ms=2000, max_observation_span_ms=2000)
    contract = identity["order_contract"]
    candidate = {"instrument_id": contract["market"]["id"], "position_side": contract["execution"]["position_side"],
        "side": "BUY" if case["db"].get_record(case["key"])["is_buy"] else "SELL",
        "base_quantity": contract["quantity"], "contracts": contract["exchange_amount"],
        "order_type": "MARKET" if price is None else "LIMIT", "limit_price": contract["price"],
        "post_only": post_only, "reduce_only": False}
    p = components["payload"]
    return {"check_id": p["check_id"], "capacity_evidence": capacity, "market_evidence": p["market_evidence"],
        "candidate": candidate, "policy": case["policy"], "max_age_ms": 2000, "max_observation_span_ms": 2000,
        "last_price_evidence": last, "last_max_age_ms": 2000, "last_max_observation_span_ms": 2000}


def entry():
    value = getattr(Account, "observe_binance_account_order_capacity_v1", None)
    assert callable(value), "approved F cost is not reconstructed from the original account check"
    return value


def f(value):
    return Fraction(int(value["numerator"]), int(value["denominator"]))


def oracle(args):
    request = args["candidate"]
    q = Fraction(request["base_quantity"])
    instrument = request["instrument_id"]
    mark_row = next(row for row in args["market_evidence"]["payload"]["observations"] if row["market"]["id"] == instrument)
    mark = Fraction(mark_row["mark"]["price"])
    last = Fraction(next(row["price"] for row in args["last_price_evidence"]["payload"]["observations"] if row["instrument_id"] == instrument))
    source = {row["role"]: row["raw"] for row in args["capacity_evidence"]["payload"]["observations"] if row["instrument_id"] == instrument}
    maker, taker = (Fraction(source["commission"][key]) for key in ("makerCommissionRate", "takerCommissionRate"))
    padded = last*Fraction(2003, 2000)
    if request["order_type"] == "MARKET":
        assumed = loss_price = padded
        fee_price = max(padded, mark, Fraction(mark_row["book"]["bid_price"]), Fraction(mark_row["book"]["ask_price"]))
        fee_rate = max(Fraction(0), taker)
    else:
        loss_price = Fraction(request["limit_price"])
        assumed = loss_price if request["side"] == "BUY" else max(padded, mark, loss_price)
        fee_price = loss_price if request["post_only"] else max(assumed, mark, Fraction(mark_row["book"]["bid_price"]), Fraction(mark_row["book"]["ask_price"]), loss_price)
        fee_rate = max(Fraction(0), maker) if request["post_only"] else max(Fraction(0), maker, taker)
    initial = q*assumed/Fraction(source["configuration"]["leverage"])
    loss = q*max(Fraction(0), (1 if request["side"] == "BUY" else -1)*(loss_price-mark))
    fee = q*fee_price*fee_rate
    return {"assumed_price": assumed, "loss_price": loss_price, "fee_price": fee_price, "fee_rate": fee_rate,
        "initial_margin": initial, "opening_loss": loss, "estimated_fee": fee, "total_cost": initial+loss+fee}


@pytest.mark.parametrize("kind,post", [("LIMIT", False), ("LIMIT", True), ("MARKET", False)])
def test_actual_sources_and_original_available_feed_conditional_cost_without_intent_or_permission(capacity_case, monkeypatch, kind, post):
    observe = entry()
    case = capacity_case
    price = None if kind == "MARKET" else 110 if case["db"].get_record(case["key"])["is_buy"] else 90
    args = assemble(case, monkeypatch, price=price, post_only=post)
    changes, record, raw = case["db"].db.conn.total_changes, case["db"].get_record(case["key"]), canonical_bytes(args)
    calls = list(case["http_calls"])
    result = observe(case["db"], **args)
    assert result["schema"] == "chan-binance-account-order-capacity-client-v1"
    p = result["payload"]
    assert p["status"] == "within_model_capacity"
    assert p["standard_commission_assumption"]["model_id"] == "binance-standard-usdt-commission-client-v1"
    assert p["standard_commission_assumption"]["fee_currency_basis"] == "client_assumption"
    assert p["standard_commission_assumption"]["currency"] == "USDT"
    assert p["standard_commission_assumption"]["native_fee_currency_verified"] is False
    assert p["standard_commission_assumption"]["native_extra_charges_complete_verified"] is False
    cost = p["order_cost"]["payload"]
    for field, expected in oracle(args).items(): assert f(cost[field]) == expected
    native = next(row for row in case["account_raw"]["assets"] if row["asset"] == "USDT")
    assert f(cost["available_balance"]) == Fraction(native["availableBalance"])
    assert f(cost["margin_balance"]) == Fraction(native["marginBalance"])
    assert Fraction(native["openOrderInitialMargin"]) > 0
    assert f(cost["available_after_cost"]) == f(cost["available_balance"])-f(cost["total_cost"])
    assert all(p[key] is False for key in ("source_collection_owned", "economics_complete", "native_admission_verified"))
    assert case["db"].db.conn.total_changes == changes and case["db"].get_record(case["key"]) == record
    assert canonical_bytes(args) == raw and case["http_calls"] == calls and len(case["created"]) == 3


@pytest.mark.parametrize("difference", [Fraction(0), -Fraction(1, 10**40)])
def test_native_available_exact_cost_and_tiny_shortfall_are_not_rounded_or_debited_again(single_case, monkeypatch, difference):
    case = single_case
    # The native fixture's leverage is 3. Choose an actual prepared quantity
    # that cancels 3 so a finite native amount can equal the cost exactly.
    # Other cases keep the nonterminating cost and compare exact Fractions.
    args = assemble(case, monkeypatch, amount=.3)
    target = oracle(args)["total_cost"]+difference
    with localcontext() as context:
        context.prec = 100
        amount = format(Decimal(target.numerator)/Decimal(target.denominator), "f")
    assert Fraction(amount) == target
    asset = next(row for row in case["account_raw"]["assets"] if row["asset"] == "USDT")
    asset["availableBalance"] = case["account_raw"]["availableBalance"] = amount
    p = Prepared.collect_and_check_native_components(case["db"], case["client"], mode=case["trade"].mode,
        markets=args["capacity_evidence"]["payload"]["markets"], before_id=case["before_id"],
        account_scope="standard-cost-refreshed", policy=case["policy"])["payload"]
    args.update(check_id=p["check_id"], market_evidence=p["market_evidence"])
    result = entry()(case["db"], **args)["payload"]
    assert result["status"] == ("within_model_capacity" if difference == 0 else "exceeds_model_capacity")
    assert f(result["order_cost"]["payload"]["available_after_cost"]) == difference


@pytest.mark.parametrize("damage", ["burn_on", "unknown_fee", "legacy", "wrong_sdk", "wrong_pool", "coefficient", "leverage", "isolated", "old_last"])
def test_unproved_or_conflicting_f_inputs_cannot_become_model_capacity(single_case, monkeypatch, damage):
    case = single_case
    args = assemble(case, monkeypatch)
    cap = args["capacity_evidence"]
    rows = cap["payload"]["observations"]
    if damage == "burn_on": rows[0]["raw"]["feeBurn"] = True
    elif damage == "unknown_fee": rows[1]["raw"]["extraTaxRate"] = "0"
    elif damage == "legacy":
        cap["schema"] = Capacity.SCHEMA
        cap["payload"].pop("field_policy")
        for row in rows: row.pop("uninterpreted_paths")
    elif damage == "wrong_sdk": cap["payload"]["sdk"]["version"] = "unknown"
    elif damage == "wrong_pool": cap["payload"]["markets"][0]["precision"]["price"] = "0.2"
    elif damage == "coefficient": next(row for row in rows if row["role"] == "brackets")["raw"]["notionalCoef"] = "1.01"
    elif damage == "leverage": next(row for row in rows if row["role"] == "configuration")["raw"]["leverage"] = 7
    elif damage == "isolated": next(row for row in rows if row["role"] == "configuration")["raw"]["marginType"] = "ISOLATED"
    else: case["clock"]["now"] += 2001
    reseal(cap)
    changes = case["db"].db.conn.total_changes
    with pytest.raises(CChanException): entry()(case["db"], **args)
    assert case["db"].db.conn.total_changes == changes


def test_non_candidate_symbol_limit_is_not_replaced_by_a_passing_cost(single_case, monkeypatch):
    case = single_case
    args = assemble(case, monkeypatch)
    cap = args["capacity_evidence"]
    row = next(row for row in cap["payload"]["observations"] if row["role"] == "configuration" and row["instrument_id"] != args["candidate"]["instrument_id"])
    row["raw"]["maxNotionalValue"] = "0.0000001"
    reseal(cap)
    p = entry()(case["db"], **args)["payload"]
    assert p["order_cost"]["payload"]["local_model_funds_sufficient"] is True
    assert p["limits"]["payload"]["status"] == "exceeds_observed_limits"
    assert p["status"] == "exceeds_model_capacity"


@pytest.mark.parametrize("api", ["observe_binance_account_order_limits_v1", "observe_binance_account_limits"])
def test_old_public_paths_do_not_silently_accept_f_source_schema(single_case, monkeypatch, api):
    case = single_case
    args = assemble(case, monkeypatch)
    if api == "observe_binance_account_limits":
        for key in ("last_price_evidence", "last_max_age_ms", "last_max_observation_span_ms"): args.pop(key)
        for key in ("order_type", "limit_price", "post_only", "reduce_only"): args["candidate"].pop(key)
        args["candidate"]["valuation_price"] = "100"
    with pytest.raises(CChanException): getattr(Account, api)(case["db"], **args)


@pytest.mark.parametrize("field", ["fee_currency", "available_balance", "margin_balance", "cost", "approved", "standard"])
def test_f_entry_never_accepts_caller_cash_currency_cost_or_authority(field):
    args = {key: None for key in ("check_id", "capacity_evidence", "market_evidence", "candidate", "policy", "max_age_ms",
        "max_observation_span_ms", "last_price_evidence", "last_max_age_ms", "last_max_observation_span_ms")}
    with pytest.raises(TypeError): entry()(None, **args, **{field: True})


@pytest.mark.parametrize("target", ["candidate", "source", "intent"])
def test_final_clock_keeps_caller_changes_and_real_competing_cas_outside_capacity(single_case, monkeypatch, target):
    case = single_case
    args = assemble(case, monkeypatch)
    key = case["db"].add_signal(make_signal(code="ALT/USDT:USDT", is_buy=True))
    quantity, _, contract = case["trade"].prepare_order("ALT/USDT:USDT", .3, 100, record=case["db"].get_record(key))
    calls = []
    def clock():
        calls.append(1)
        if len(calls) == 2:
            if target == "candidate": args["candidate"]["contracts"] = "999"
            elif target == "source": args["capacity_evidence"]["payload"]["field_policy"] = "changed"
            else:
                assert case["db"].acquire_open_intent(key, quantity, "lateStandardCostCAS", order_contract=contract,
                    position_side=contract["execution"]["position_side"])
        return case["clock"]["now"]
    monkeypatch.setattr(Account, "utc_now_ms", clock)
    with pytest.raises(CChanException): entry()(case["db"], **args)
    if target == "intent": assert case["db"].get_record(key)["open_attempt"] == 1


@pytest.mark.parametrize("point", [1, 4])
def test_each_f_reader_preserves_original_database_before_any_following_query(single_case, monkeypatch, tmp_path, point):
    case = single_case
    args = assemble(case, monkeypatch)
    original_db = case["db"].db
    replacement = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path/"f-replacement.db")})
    queries, calls = [], []
    replacement.db.conn.set_trace_callback(queries.append)
    reader = Capacity.verify_binance_standard_capacity_evidence
    def changed(*a, **kw):
        result = reader(*a, **kw)
        calls.append(1)
        if len(calls) == point: case["db"].db = replacement.db
        return result
    monkeypatch.setattr(Capacity, "verify_binance_standard_capacity_evidence", changed)
    changes = replacement.db.conn.total_changes
    try:
        with pytest.raises(CChanException): entry()(case["db"], **args)
        assert len(calls) == point and not queries and replacement.db.conn.total_changes == changes
    finally:
        case["db"].db = original_db
        replacement.close()


def test_cost_computation_time_is_inside_original_joint_source_budget(single_case, monkeypatch):
    case = single_case
    args = assemble(case, monkeypatch)
    original, elapsed = Account.calculate_binance_order_cost_v1, [0]
    def delayed(**kwargs):
        result = original(**kwargs)
        elapsed[0] += 2_001_000_000
        return result
    monkeypatch.setattr(Account, "calculate_binance_order_cost_v1", delayed)
    monkeypatch.setattr(Account, "_monotonic_ns", lambda: elapsed[0])
    with pytest.raises(CChanException): entry()(case["db"], **args)
