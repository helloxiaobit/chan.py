"""Explicit joint source-use checks; not collector ownership or admission."""
import json

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .NativeAdmission import (POLICY_SCHEMA as LEGACY_POLICY_SCHEMA, _assert_current_windows, _current_interval_sources,
                              _fail_sources, assert_native_account_market_freshness, read_native_freshness_policy)
from .NativeMarketEvidence import verify_native_market_evidence


POLICY_SCHEMA = "chan-native-component-freshness-policy-v1"


def _legacy_policy(values):
    legacy = json.loads(canonical_bytes(values))
    legacy["schema"] = LEGACY_POLICY_SCHEMA
    for field in ("max_age_ms", "max_observation_span_ms"):
        value = legacy[field].pop("balance")
        if type(value) is not int or not 0 <= value < 2**63:
            raise ValueError
    return read_native_freshness_policy(legacy)


def read_native_component_policy(document):
    """Separate version: balance age/span are explicit, never account defaults."""
    try:
        values = json.loads(canonical_bytes(document))
        if values["schema"] != POLICY_SCHEMA:
            raise ValueError
        _legacy_policy(values)
        return values
    except Exception:
        raise CChanException("原生组件政策须显式完整提供各来源含余额的非负整毫秒，无默认值或容差", ErrCode.CONFIG_ERROR) from None


def _latest(document, selected):
    """No SHA/timestamp ranking of distinct same-clock observations."""
    latest = max(row["payload"]["finished_ms"] for row in selected)
    at = document["payload"]["finished_ms"]
    if at > latest or (at == latest and canonical_bytes(document) not in {canonical_bytes(row) for row in selected}):
        _fail_sources()


def _known_facts(document, selected, start, end):
    """A newer source cannot erase known facts, even zero-net round trips."""
    expected = {canonical_bytes(fact) for row in selected for fact in row["payload"]["facts"]
                if start <= fact["timestamp_ms"] < end}
    for fact in document["payload"]["facts"]:
        if fact["timestamp_ms"] < start:
            continue  # The accepted before endpoint already bounds this history.
        if fact["timestamp_ms"] >= end or canonical_bytes(fact) not in expected:
            _fail_sources()  # A post-endpoint fact also makes the point stale.


def _sources_snapshot(chan, context, check_id, market):
    """Original current sources only. Consumers must separately bind a ledger."""
    from .AccountRiskStore import account_key
    from .AccountStore import TABLE as ACCOUNT_EVIDENCE, read_evidence
    from .AccountSources import WALLET_SCHEMA
    from .ExecutionStore import SCANS, read_scan_with_account
    from .NativeAccountCheck import SCHEMA as CHECK_SCHEMA
    from .NativeAccountStore import read_account_observations
    from .NativePendingOrders import SCHEMA as PENDING_SCHEMA
    with chan.db.transaction():
        check, executions = _current_interval_sources(chan, context, check_id, market)
        if check["schema"] != CHECK_SCHEMA:
            _fail_sources()
        saved, key = check["payload"]["inputs"], account_key(context)
        start, end = saved["before"]["payload"]["started_ms"], saved["after"]["payload"]["finished_ms"]+1
        for row in read_account_observations(chan.db, context):
            _latest(row, [saved["pending"] if row["schema"] == PENDING_SCHEMA else saved["balance"]])
        for column in ("pending", "balance"):
            if canonical_bytes(saved[column]["payload"]["sdk"]) != canonical_bytes(market["payload"]["sdk"]):
                _fail_sources()
        for row in chan.db.query(f"SELECT evidence_id FROM {ACCOUNT_EVIDENCE} ORDER BY evidence_id"):
            document = read_evidence(chan.db, row["evidence_id"])
            if document["schema"] == WALLET_SCHEMA and account_key(document["payload"]["account_context"]) == key:
                _known_facts(document, saved["wallets"], start, end)
                _latest(document, saved["wallets"])
        by_instrument = {}
        for original, observed in zip(saved["executions"], executions):
            instrument = original["receipt"]["payload"]["market"]["symbol"]
            by_instrument.setdefault(instrument, []).append((original["receipt"], observed))
        for row in chan.db.query(f"SELECT scan_id FROM {SCANS} ORDER BY scan_id"):
            receipt, linked = read_scan_with_account(chan.db, row["scan_id"])
            if linked is None:
                if receipt["payload"]["venue"] == context["venue"] and receipt["payload"]["mode"] == context["mode"]:
                    _fail_sources()  # Unknown account is not evidence of a different account.
                continue
            if account_key(linked["observation"]["account_context"]) != key:
                continue
            instrument = receipt["payload"]["market"]["symbol"]
            selected = by_instrument.get(instrument)
            if not selected:
                _fail_sources()
            _known_facts(receipt, [value for value, _ in selected], start, end)
            at = linked["observation"]["finished_ms"]
            latest = max(observed["finished_ms"] for _, observed in selected)
            if at > latest or (at == latest and canonical_bytes(receipt) not in {canonical_bytes(value) for value, _ in selected}):
                _fail_sources()
        return {"check": check, "execution_observations": executions}


def _snapshot(chan, context, check_id, market):
    from .AccountRiskStore import _ledger
    with chan.db.transaction():
        snapshot = _sources_snapshot(chan, context, check_id, market)
        saved = snapshot["check"]["payload"]["inputs"]
        if canonical_bytes(_ledger(chan)) != canonical_bytes({key: saved[key] for key in ("histories", "projections")}):
            _fail_sources()
        return snapshot


def assert_native_components_current(chan, exchange, *, mode, markets, account_context, check_id, market_evidence, policy):
    """Joint use-time assertion, never a capability to place an order.

    Check publication owns failures. The eventual per-order consumer must own
    source collection and revalidate inside the original CAS; consistent input
    bytes and this function's None result are not authentication or admission.
    """
    try:
        start = utc_now_ms()
        if chan.db_type != "sqlite" or chan.db.conn.in_transaction:
            _fail_sources()
        provided = {"mode": mode, "markets": markets, "account_context": account_context, "check_id": check_id,
                    "market_evidence": market_evidence, "policy": policy}
        original = canonical_bytes(provided)
        values = json.loads(original)
        policy = read_native_component_policy(values["policy"])
        market, context = values["market_evidence"], values["account_context"]
        verify_native_market_evidence(market)
        first = _snapshot(chan, context, values["check_id"], market)
        saved = first["check"]["payload"]["inputs"]
        # All private identity reads occur after release of the SQLite view.
        assert_native_account_market_freshness(exchange, mode=values["mode"], markets=values["markets"],
            account_snapshot=saved["after"], market_evidence=market, policy=_legacy_policy(policy))
        second = _snapshot(chan, context, values["check_id"], market)
        if canonical_bytes(first) != canonical_bytes(second) or canonical_bytes(provided) != original:
            _fail_sources()
        _assert_current_windows(policy, start, utc_now_ms(), account=saved["after"]["payload"], market=market["payload"],
            wallets=[row["payload"] for row in saved["wallets"]], executions=first["execution_observations"],
            additional=[("open_orders", saved["pending"]["payload"]), ("balance", saved["balance"]["payload"])])
    except Exception:
        _fail_sources()
