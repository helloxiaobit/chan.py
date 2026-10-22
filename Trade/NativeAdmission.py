"""Explicit native observation-use policy; not a complete account admission.

No configuration fallback, tolerance knob, new ledger or order state machine.
Observation checks alone must never enable native new risk.
"""
import json
from decimal import localcontext

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountIdentity import observe_account_context
from .AccountReconcile import _number as _exact_number
from .AccountSources import SNAPSHOT_SCHEMA, verify_account_snapshot
from .ExecutionFacts import _MONEY, _market
from .NativeMarketEvidence import _markets, _public_environment, _sdk, verify_native_market_evidence


POLICY_SCHEMA = "chan-native-freshness-policy-v1"
_AGE_ROLES = {"account", "mark", "book", "wallet", "execution", "open_orders"}
_SPAN_ROLES = {"account", "market", "wallet", "execution", "open_orders", "total"}


def read_native_freshness_policy(document):
    """Copy the complete explicit millisecond policy, including strict zeros."""
    try:
        if (not isinstance(document, dict)
                or set(document) != {"schema", "max_age_ms", "max_observation_span_ms", "max_source_skew_ms"}
                or document["schema"] != POLICY_SCHEMA):
            raise ValueError
        for field, roles in (("max_age_ms", _AGE_ROLES), ("max_observation_span_ms", _SPAN_ROLES)):
            values = document[field]
            if not isinstance(values, dict) or set(values) != roles:
                raise ValueError
            if any(type(value) is not int or not 0 <= value < 2**63 for value in values.values()):
                raise ValueError
        skew = document["max_source_skew_ms"]
        if type(skew) is not int or not 0 <= skew < 2**63:
            raise ValueError
        return json.loads(canonical_bytes(document))
    except Exception:
        raise CChanException("原生鲜活性政策必须显式完整提供非负整毫秒；无默认值或容差回退", ErrCode.CONFIG_ERROR) from None


def _fail_sources():
    raise CChanException("原生账户/市场来源使用检查失败；不是完整账户准入，禁止据此新增风险", ErrCode.TRADE_UNLOCK_FAIL) from None


def _assert_current_windows(policy, start, checked, *, account, market, wallets, executions):
    """Pure shared use-time checks; historical coverage bounds are not clocks."""
    if type(start) is not int or type(checked) is not int or not 0 <= start <= checked < 2**63:
        _fail_sources()
    ages, spans = policy["max_age_ms"], policy["max_observation_span_ms"]
    current = [("account", account), *[("wallet", row) for row in wallets], *[("execution", row) for row in executions]]
    anchors, starts = [], [market["started_ms"]]
    for role, row in current:
        begin, finish = row["started_ms"], row["finished_ms"]
        if (type(begin) is not int or type(finish) is not int or not 0 <= begin <= finish <= checked
                or checked-begin > ages[role] or finish-begin > spans[role]):
            _fail_sources()
        anchors.append(begin)
        starts.append(begin)
    if (not 0 <= market["started_ms"] <= market["finished_ms"] <= checked
            or market["finished_ms"]-market["started_ms"] > spans["market"]
            or checked-min(starts) > spans["total"]):
        _fail_sources()
    for row in market["observations"]:
        if row["book"]["tradeable"] is not True:
            _fail_sources()
        for role in ("mark", "book"):
            source = row[role]
            if checked-source["source_ms"] > ages[role] or checked-source["started_ms"] > ages[role]:
                _fail_sources()
            anchors.append(source["source_ms"])
    if max(anchors)-min(anchors) > policy["max_source_skew_ms"]:
        _fail_sources()


def assert_native_account_market_freshness(exchange, *, mode, markets, account_snapshot, market_evidence, policy):
    """Validate ONLY account/market observation bindings, returning no proof.

    This neither reconciles money/history nor verifies wallet/execution/native
    open orders/reservations. The complete consumer must collect its own inputs
    and consume the original CAS; caller-supplied consistent bytes are not a
    capability. Callers must run these read-only profile checks outside every
    DB write lock; this helper neither owns nor checks an ambient transaction.
    """
    try:
        start = utc_now_ms()
        provided = {"policy": policy, "markets": markets, "account_snapshot": account_snapshot, "market_evidence": market_evidence}
        original_bytes = canonical_bytes(provided)
        inputs = json.loads(original_bytes)
        policy, markets = read_native_freshness_policy(inputs["policy"]), inputs["markets"]
        account_snapshot, market_evidence = inputs["account_snapshot"], inputs["market_evidence"]
        verify_account_snapshot(account_snapshot)
        verify_native_market_evidence(market_evidence)
        account, market = account_snapshot["payload"], market_evidence["payload"]
        if mode not in {"live", "testnet"} or market["mode"] != mode or market["exchange_id"] != exchange.id:
            _fail_sources()
        with localcontext(_MONEY):
            expected = _markets(markets, exchange.id)
            units = sorted((_market(m) for m in expected), key=lambda m: (m["id"], m["symbol"]))
        import ccxt  # only the explicit current-client check needs the SDK
        reference = getattr(ccxt, exchange.id)()
        if mode == "testnet":
            reference.set_sandbox_mode(True)

        def current():
            if (canonical_bytes(_public_environment(exchange, reference, market["venue"], mode)) != canonical_bytes(market["environment"])
                    or canonical_bytes(_sdk(exchange, ccxt)) != canonical_bytes(market["sdk"])
                    or canonical_bytes(observe_account_context(exchange, mode)) != canonical_bytes(account["account_context"])):
                _fail_sources()

        current()
        if (canonical_bytes(expected) != canonical_bytes([row["market"] for row in market["observations"]])
                or canonical_bytes(units) != canonical_bytes(sorted(account["markets"], key=lambda m: (m["id"], m["symbol"])))
                or account["unsupported_positions"]):
            _fail_sources()
        instruments = {m["id"] for m in expected}
        if any(row["instrument_id"] not in instruments for row in account["positions"]+account["native_account_positions"]):
            _fail_sources()
        current()
        # The private profile guard does not cover Binance fapiPublic. Recheck
        # public routing and SDK identity after the final private read as well.
        if (canonical_bytes(_public_environment(exchange, reference, market["venue"], mode)) != canonical_bytes(market["environment"])
                or canonical_bytes(_sdk(exchange, ccxt)) != canonical_bytes(market["sdk"])):
            _fail_sources()
        if canonical_bytes(provided) != original_bytes:
            _fail_sources()
        checked = utc_now_ms()
        _assert_current_windows(policy, start, checked, account=account, market=market, wallets=[], executions=[])
        # None, not ready/passed/admission or a new locally resealable receipt.
    except Exception:
        _fail_sources()


def assert_native_persisted_interval(chan, *, account_context, check_id, market_evidence, policy):
    """DB-only check of original evidence and an unchanged current journal.

    No profile GET, row write or proof publication. A current financial failure
    must still be published by the original reconciler, not by this assertion.
    Native pending orders/reservations and live-client checks remain separate;
    None is not admission. The original v1 report's limitations are preserved.
    """
    try:
        from .AccountRiskStore import _ledger, account_key, read_check, risk_state
        from .AccountStore import TABLE as ACCOUNT_EVIDENCE, read_evidence
        from .ExecutionStore import read_scan_with_account
        start = utc_now_ms()
        provided = {"account_context": account_context, "check_id": check_id, "market_evidence": market_evidence, "policy": policy}
        original_bytes = canonical_bytes(provided)
        inputs = json.loads(original_bytes)
        policy = read_native_freshness_policy(inputs["policy"])
        context, market_document = inputs["account_context"], inputs["market_evidence"]
        verify_native_market_evidence(market_document)
        if chan.db_type != "sqlite":
            _fail_sources()
        with chan.db.transaction():
            check = read_check(chan.db, inputs["check_id"])
            state = risk_state(chan.db, context)
            saved = check["payload"]["inputs"]
            if (state["frozen"] or canonical_bytes(check["payload"]["account_context"]) != canonical_bytes(context)
                    or saved is None or check["payload"]["report"]["payload"]["status"] != "matched_observations"):
                _fail_sources()
            if canonical_bytes(_ledger(chan)) != canonical_bytes({key: saved[key] for key in ("histories", "projections")}):
                _fail_sources()
            market, after = market_document["payload"], saved["after"]["payload"]
            after_bytes = canonical_bytes(saved["after"])
            # A later known observation invalidates this old current point even
            # before it has a report. Validate every original row before using
            # indexed metadata; same-clock distinct snapshots are ambiguous.
            for row in chan.db.query(f"SELECT evidence_id FROM {ACCOUNT_EVIDENCE} ORDER BY evidence_id"):
                document = read_evidence(chan.db, row["evidence_id"])
                observed = document["payload"]
                if document["schema"] == SNAPSHOT_SCHEMA and account_key(observed["account_context"]) == state["account_key"]:
                    if (observed["finished_ms"] > after["finished_ms"]
                            or (observed["finished_ms"] == after["finished_ms"] and canonical_bytes(document) != after_bytes)):
                        _fail_sources()
            if (market["venue"] != context["venue"] or market["mode"] != context["mode"]
                    or any(market["environment"][key] != context["environment"][key]
                           for key in ("sandbox", "hostname", "simulated_trading"))):
                _fail_sources()
            with localcontext(_MONEY):
                units = sorted((_market(row["market"]) for row in market["observations"]), key=lambda row: row["id"])
            if canonical_bytes(units) != canonical_bytes(sorted(after["markets"], key=lambda row: row["id"])):
                _fail_sources()
            by_id = {row["market"]["id"]: row for row in market["observations"]}
            for position in after["positions"]:
                if _exact_number(position["quantity"]) and _exact_number(position["mark_price"]) != _exact_number(by_id[position["instrument_id"]]["mark"]["price"]):
                    _fail_sources()
            observations = []
            ids = check["payload"]["source_ids"]["executions"]
            if len(ids) != len(saved["executions"]):
                _fail_sources()
            for scan_id, original in zip(ids, saved["executions"]):
                receipt, linked = read_scan_with_account(chan.db, scan_id)
                if (linked is None or canonical_bytes(receipt) != canonical_bytes(original["receipt"])
                        or linked["manifest_sha256"] != original["manifest_sha256"]
                        or canonical_bytes(linked["observation"]["account_context"]) != canonical_bytes(context)):
                    _fail_sources()
                observations.append(linked["observation"])
        # Include release/commit latency too. These are the immutable values
        # read in the owned snapshot, not a claim that the DB remains unchanged
        # after release; the later original CAS must perform its own recheck.
        if canonical_bytes(provided) != original_bytes:
            _fail_sources()
        _assert_current_windows(policy, start, utc_now_ms(), account=after, market=market,
                                wallets=[row["payload"] for row in saved["wallets"]], executions=observations)
    except Exception:
        _fail_sources()
