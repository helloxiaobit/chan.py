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
from .AccountSources import verify_account_snapshot
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
        if (type(start) is not int or type(checked) is not int or not 0 <= start <= checked < 2**63
                or account["finished_ms"] > checked or market["finished_ms"] > checked):
            _fail_sources()
        ages, spans = policy["max_age_ms"], policy["max_observation_span_ms"]
        if (checked-account["started_ms"] > ages["account"]
                or account["finished_ms"]-account["started_ms"] > spans["account"]
                or market["finished_ms"]-market["started_ms"] > spans["market"]
                or checked-min(account["started_ms"], market["started_ms"]) > spans["total"]):
            _fail_sources()
        anchors = [account["started_ms"]]
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
        # None, not ready/passed/admission or a new locally resealable receipt.
    except Exception:
        _fail_sources()
