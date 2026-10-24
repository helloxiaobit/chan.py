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
from .AccountReconcile import _sha
from .NativeAdmission import _assert_current_windows
from .NativeCapacityEvidence import verify_binance_capacity_evidence
from .NativeCurrentComponents import _sources_snapshot
from .NativeLeverageLimits import evaluate_binance_leverage_limits
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
    _assert_current_windows(policy, started, checked, account=saved["after"]["payload"],
        market=values["market_evidence"]["payload"], wallets=[row["payload"] for row in saved["wallets"]],
        executions=snapshot["execution_observations"], additional=[("open_orders", saved["pending"]["payload"]),
            ("balance", saved["balance"]["payload"]), ("capacity", cap), ("capacity", endpoint)])


def observe_binance_account_limits(chan, *, check_id, capacity_evidence, market_evidence, candidate, policy,
                                  max_age_ms, max_observation_span_ms):
    """Derive only from the original check; no caller-supplied position book."""
    try:
        database = Boundary._database(chan)
        connection, table = database.conn, chan.table
        Boundary._same_database(chan, database, connection, table, owned=False)
        tick_start, started = _monotonic_ns(), utc_now_ms()
        provided = {"check_id": check_id, "capacity_evidence": capacity_evidence, "market_evidence": market_evidence,
            "candidate": candidate, "policy": policy, "max_age_ms": max_age_ms,
            "max_observation_span_ms": max_observation_span_ms}
        original = canonical_bytes(provided)
        values = json.loads(original)
        source = values["capacity_evidence"]
        verify_binance_capacity_evidence(source, max_age_ms=max_age_ms, max_observation_span_ms=max_observation_span_ms)
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
        book = {"positions": saved["after"]["payload"]["raw"]["positions"],
            "pending_orders": [row["raw"] for row in saved["pending"]["payload"]["orders"]],
            "mark_prices": {row["market"]["id"]: row["mark"]["price"] for row in values["market_evidence"]["payload"]["observations"]},
            "position_mode": check["payload"]["report"]["payload"]["components"]["payload"]["margin"]["position_mode"],
            "candidate": values["candidate"]}
        limits = evaluate_binance_leverage_limits(source, **book, max_age_ms=max_age_ms,
                                                   max_observation_span_ms=max_observation_span_ms)
        payload = {"check_id": values["check_id"], "source_ids": check["payload"]["source_ids"],
            "account_context": check["payload"]["account_context"], "boundary_payload_sha256": boundary["payload_sha256"],
            "capacity_evidence_sha256": _sha(source), "market_evidence_sha256": _sha(values["market_evidence"]),
            "provided_inputs_sha256": _sha(values), "derived_book_inputs_sha256": _sha(book), "limits": limits,
            "coverage": "original_check_bound_limit_diagnostic_only", "book_bound_to_original_check": True,
            "source_collection_owned": False, "book_origin_verified": False,
            "economics_complete": False, "native_admission_verified": False}
        document = json.loads(canonical_bytes({"schema": SCHEMA, "payload": payload, "payload_sha256": _sha(payload)}))
        checked = utc_now_ms()
        Boundary._same_database(chan, database, connection, table, owned=False)
        verify_binance_capacity_evidence(source, max_age_ms=max_age_ms, max_observation_span_ms=max_observation_span_ms)
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
