"""Original persisted account/book projection, not native funding/admission.

These documents are reader inputs, not collector capabilities. Only the later
controlled prepare/CAS may own and bind actual source collection. This module
does not refresh a source, write a database, or permit an order.
"""
import json
from time import monotonic_ns as _monotonic_ns

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from . import NativeOrderBoundary as Boundary
from . import NativeCapacityEvidence as Capacity
from . import NativeLeverageLimits as Limits
from . import NativeLastPrice as Last
from .NativeOrderCost import calculate_binance_order_cost_v1
from .AccountReconcile import _sha
from .NativeAdmission import _assert_current_windows
from .NativeCapacityEvidence import verify_binance_capacity_evidence
from .NativeCurrentComponents import _sources_snapshot
from .NativeLeverageLimits import evaluate_binance_leverage_limits
from .NativeLeverageLimits import evaluate_binance_order_leverage_limits_v1
from .NativeLastPrice import verify_binance_last_prices
from .NativeMarginEnvelope import _n


SCHEMA = "chan-binance-account-limits-v1"


def _fail():
    raise CChanException("Binance原账户book/限额绑定不完整或漂移；不构成资金或下单准入", ErrCode.TRADE_UNLOCK_FAIL) from None


def _bindings(source, market, saved):
    if (source["exchange_id"] != market["exchange_id"] or source["mode"] != market["mode"]
            or canonical_bytes(source["sdk"]) != canonical_bytes(market["sdk"])
            or canonical_bytes(source["markets"]) != canonical_bytes([row["market"] for row in market["observations"]])):
        _fail()
    old = {row["symbol"]: row for row in saved["after"]["payload"]["raw"]["symbol_configs"]}
    for row in source["observations"]:
        if row["role"] == "configuration":
            current, prior = row["raw"], old[row["instrument_id"]]
            if (any(current[key] != prior[key] for key in ("symbol", "marginType", "isAutoAddMargin"))
                    or _n(current["leverage"], positive=True) != _n(prior["leverage"], positive=True)):
                _fail()


def _windows(values, snapshot, started, checked):
    policy = json.loads(canonical_bytes(values["policy"]))
    policy["max_age_ms"]["capacity"] = values["max_age_ms"]
    policy["max_observation_span_ms"]["capacity"] = values["max_observation_span_ms"]
    cap = values["capacity_evidence"]["payload"]
    saved = snapshot["check"]["payload"]["inputs"]
    # Both local endpoints: later parameter observations must not hide behind
    # the first request's earlier anchor. No native generation clock is added.
    endpoint = {"started_ms": cap["finished_ms"], "finished_ms": cap["finished_ms"]}
    additional = [("open_orders", saved["pending"]["payload"]), ("balance", saved["balance"]["payload"]),
                  ("capacity", cap), ("capacity", endpoint)]
    if "last_price_evidence" in values:
        policy["max_age_ms"]["last_price"] = values["last_max_age_ms"]
        policy["max_observation_span_ms"]["last_price"] = values["last_max_observation_span_ms"]
        last = values["last_price_evidence"]["payload"]
        additional.extend([("last_price", last), ("last_price", {"started_ms": last["finished_ms"], "finished_ms": last["finished_ms"]})])
        additional.extend(("last_price", {"started_ms": row["source_ms"], "finished_ms": row["source_ms"]})
                          for row in last["observations"])
    _assert_current_windows(policy, started, checked, account=saved["after"]["payload"],
        market=values["market_evidence"]["payload"], wallets=[row["payload"] for row in saved["wallets"]],
        executions=snapshot["execution_observations"], additional=additional)


def _last_links(values, capacity, *, checked_ms=None):
    last = values["last_price_evidence"]
    budgets = {"max_age_ms": values["last_max_age_ms"], "max_observation_span_ms": values["last_max_observation_span_ms"]}
    if checked_ms is None:
        verify_binance_last_prices(last, **budgets)
    else:
        Last._verify_binance_last_prices_at(last, checked_ms=checked_ms, **budgets)
    p = last["payload"]
    if (any(p[key] != capacity[key] for key in ("exchange_id", "mode", "sdk"))
            or canonical_bytes(p["markets"]) != canonical_bytes(capacity["markets"])):
        _fail()
    return {row["instrument_id"]: row["price"] for row in p["observations"]}


def observe_binance_account_limits(chan, *, check_id, capacity_evidence, market_evidence, candidate, policy,
                                  max_age_ms, max_observation_span_ms):
    """Derive only from the original check; no caller-supplied position book."""
    return _observe_account_limits(chan, check_id=check_id, capacity_evidence=capacity_evidence,
        market_evidence=market_evidence, candidate=candidate, policy=policy, max_age_ms=max_age_ms,
        max_observation_span_ms=max_observation_span_ms, price_inputs=None)


def observe_binance_account_order_limits_v1(chan, *, check_id, capacity_evidence, market_evidence, candidate, policy,
        max_age_ms, max_observation_span_ms, last_price_evidence, last_max_age_ms, last_max_observation_span_ms):
    """Bind Last and V1 whole-book limits to original check/L0, not cash authority."""
    return _observe_account_limits(chan, check_id=check_id, capacity_evidence=capacity_evidence,
        market_evidence=market_evidence, candidate=candidate, policy=policy, max_age_ms=max_age_ms,
        max_observation_span_ms=max_observation_span_ms, price_inputs={"last_price_evidence": last_price_evidence,
            "last_max_age_ms": last_max_age_ms, "last_max_observation_span_ms": last_max_observation_span_ms})


def observe_binance_account_order_capacity_v1(chan, *, check_id, capacity_evidence, market_evidence, candidate, policy,
        max_age_ms, max_observation_span_ms, last_price_evidence, last_max_age_ms, last_max_observation_span_ms):
    """Recompute approved F/P cost from original native cash, not caller funds.

    This report is not source-collection ownership or a trading permission.
    Original monetary acquisition and every execution consumer must own it.
    """
    return _observe_account_limits(chan, check_id=check_id, capacity_evidence=capacity_evidence,
        market_evidence=market_evidence, candidate=candidate, policy=policy, max_age_ms=max_age_ms,
        max_observation_span_ms=max_observation_span_ms, price_inputs={"last_price_evidence": last_price_evidence,
            "last_max_age_ms": last_max_age_ms, "last_max_observation_span_ms": last_max_observation_span_ms}, standard=True)


def _standard_order_cost(values, snapshot, book, last_prices):
    saved = snapshot["check"]["payload"]["inputs"]
    balance = saved["balance"]["payload"]
    configuration = balance["configuration"]
    if (configuration.get("canTrade") is not True or configuration.get("multiAssetsMargin") is not False
            or type(configuration.get("dualSidePosition")) is not bool
            or saved["after"]["payload"]["raw"]["multi_assets_margin"] is not False
            or balance["reported_totals"]["currency"] != "USDT"
            or book["position_mode"] != ("hedged" if configuration["dualSidePosition"] else "one_way")):
        _fail()
    source, candidate = values["capacity_evidence"]["payload"], values["candidate"]
    instrument = candidate["instrument_id"]
    observations = {row["role"]: row["raw"] for row in source["observations"]
                    if row["instrument_id"] in {None, instrument}}
    if observations["fee_burn"]["feeBurn"] is not False:
        _fail()
    unit = next(row for row in source["markets"] if row["id"] == instrument)
    prices = next(row for row in values["market_evidence"]["payload"]["observations"] if row["market"]["id"] == instrument)
    native_cash = next(row["native_fields"] for row in balance["assets"] if row["currency"] == "USDT")
    cost = calculate_binance_order_cost_v1(market=unit, position_mode=book["position_mode"], candidate=candidate,
        mark_price=prices["mark"]["price"], last_price=last_prices[instrument], bid_price=prices["book"]["bid_price"],
        ask_price=prices["book"]["ask_price"], leverage=observations["configuration"]["leverage"],
        commission=observations["commission"], fee_burn=False, fee_currency="USDT",
        available_balance=native_cash["availableBalance"], margin_balance=native_cash["marginBalance"])
    assumption = {"model_id": "binance-standard-usdt-commission-client-v1", "approval_date": "2026-10-25",
        "scope": "usdt_linear_cross_single_asset_regular_limit_market_gtx", "currency": "USDT", "fee_currency_basis": "client_assumption",
        "native_fee_currency_verified": False, "native_extra_charges_complete_verified": False}
    return {"order_cost": cost, "standard_commission_assumption": assumption,
        "native_cash_basis": {"balance_source_id": snapshot["check"]["payload"]["source_ids"]["balance"],
            "currency": "USDT", "available_field": "assets[USDT].availableBalance", "equity_field": "assets[USDT].marginBalance"}}


def _book(snapshot, market, candidate):
    check = snapshot["check"]
    saved = check["payload"]["inputs"]
    return {"positions": saved["after"]["payload"]["raw"]["positions"],
        "pending_orders": [row["raw"] for row in saved["pending"]["payload"]["orders"]],
        "mark_prices": {row["market"]["id"]: row["mark"]["price"] for row in market["payload"]["observations"]},
        "position_mode": check["payload"]["report"]["payload"]["components"]["payload"]["margin"]["position_mode"],
        "candidate": candidate}


def _standard_capacity(values, snapshot, book, last_prices, *, checked_ms=None):
    limits = Limits._evaluate_limits(values["capacity_evidence"], **book, price_inputs={"last_prices": last_prices},
        standard=True, max_age_ms=values["max_age_ms"], max_observation_span_ms=values["max_observation_span_ms"], checked_ms=checked_ms)
    result = {**_standard_order_cost(values, snapshot, book, last_prices), "limits": limits}
    result["status"] = ("within_model_capacity" if result["order_cost"]["payload"]["local_model_funds_sufficient"]
        and limits["payload"]["status"] == "within_observed_limits" else "exceeds_model_capacity")
    return result


def _observe_account_limits(chan, *, check_id, capacity_evidence, market_evidence, candidate, policy,
                            max_age_ms, max_observation_span_ms, price_inputs, standard=False):
    try:
        database = Boundary._database(chan)
        connection, table = database.conn, chan.table
        Boundary._same_database(chan, database, connection, table, owned=False)
        tick_start, started = _monotonic_ns(), utc_now_ms()
        provided = {"check_id": check_id, "capacity_evidence": capacity_evidence, "market_evidence": market_evidence,
            "candidate": candidate, "policy": policy, "max_age_ms": max_age_ms,
            "max_observation_span_ms": max_observation_span_ms}
        if price_inputs is not None:
            provided.update(price_inputs)
        original = canonical_bytes(provided)
        values = json.loads(original)
        source = values["capacity_evidence"]
        if standard and price_inputs is None:
            _fail()
        reader = Capacity.verify_binance_standard_capacity_evidence if standard else verify_binance_capacity_evidence
        reader(source, max_age_ms=max_age_ms, max_observation_span_ms=max_observation_span_ms)
        Boundary._same_database(chan, database, connection, table, owned=False)
        last_prices = _last_links(values, source["payload"]) if price_inputs is not None else None
        Boundary._same_database(chan, database, connection, table, owned=False)
        boundary = Boundary.capture_native_order_boundary(chan, account_context=source["payload"]["account_context"],
            check_id=values["check_id"], market_evidence=values["market_evidence"], policy=values["policy"])
        Boundary._same_database(chan, database, connection, table, owned=False)
        with database.transaction():
            snapshot = _sources_snapshot(chan, source["payload"]["account_context"], values["check_id"], values["market_evidence"])
            Boundary.assert_native_order_boundary(chan, boundary)
            Boundary._same_database(chan, database, connection, table, owned=True)
        check = snapshot["check"]
        saved = check["payload"]["inputs"]
        _bindings(source["payload"], values["market_evidence"]["payload"], saved)
        book = _book(snapshot, values["market_evidence"], values["candidate"])
        if standard:
            money = _standard_capacity(values, snapshot, book, last_prices)
            limits = money["limits"]
        elif price_inputs is None:
            limits = evaluate_binance_leverage_limits(source, **book, max_age_ms=max_age_ms,
                                                      max_observation_span_ms=max_observation_span_ms)
        else:
            limits = evaluate_binance_order_leverage_limits_v1(source, **book, last_prices=last_prices,
                max_age_ms=max_age_ms, max_observation_span_ms=max_observation_span_ms)
        payload = {"check_id": values["check_id"], "source_ids": check["payload"]["source_ids"],
            "account_context": check["payload"]["account_context"], "boundary_payload_sha256": boundary["payload_sha256"],
            "capacity_evidence_sha256": _sha(source), "market_evidence_sha256": _sha(values["market_evidence"]),
            "provided_inputs_sha256": _sha(values), "derived_book_inputs_sha256": _sha(book), "limits": limits,
            "coverage": "original_check_bound_limit_diagnostic_only", "book_bound_to_original_check": True,
            "source_collection_owned": False, "book_origin_verified": False,
            "economics_complete": False, "native_admission_verified": False}
        if price_inputs is not None:
            payload.update(last_price_evidence_sha256=_sha(values["last_price_evidence"]),
                           coverage="original_check_bound_client_v1_price_limits_only")
        if standard:
            payload.update(money,
                           coverage="original_check_bound_standard_commission_client_v1_only")
        document = json.loads(canonical_bytes({"schema": "chan-binance-account-order-capacity-client-v1" if standard else
            "chan-binance-account-order-limits-client-v1" if price_inputs is not None else SCHEMA,
            "payload": payload, "payload_sha256": _sha(payload)}))
        checked = utc_now_ms()
        Boundary._same_database(chan, database, connection, table, owned=False)
        reader(source, max_age_ms=max_age_ms, max_observation_span_ms=max_observation_span_ms)
        Boundary._same_database(chan, database, connection, table, owned=False)
        if price_inputs is not None:
            _last_links(values, source["payload"])
            Boundary._same_database(chan, database, connection, table, owned=False)
        with database.transaction():
            Boundary.assert_native_order_boundary(chan, boundary)
            Boundary._same_database(chan, database, connection, table, owned=True)
        Boundary._same_database(chan, database, connection, table, owned=False)
        if canonical_bytes(provided) != original or canonical_bytes(values) != original:
            _fail()
        _windows(values, snapshot, started, checked)
        tick_end = _monotonic_ns()
        if type(tick_start) is not int or type(tick_end) is not int or not 0 <= tick_start <= tick_end:
            _fail()
        _windows(values, snapshot, started, max(checked, started+(tick_end-tick_start+999_999)//1_000_000))
        return document
    except Exception:
        _fail()
