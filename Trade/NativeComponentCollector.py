"""Own original native collection and publication, never order permission.

The per-order path must call its own collector, bind actual instrument/runtime
identity and consume the original CAS. A returned locally hashed wrapper is
only diagnostic evidence, not a transferable capability or server signature.
"""
import hashlib
import json
import re
from pathlib import Path

from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountIdentity import observe_account_context
from .AccountRiskStore import _ledger, _sha, risk_state
from .AccountSources import SNAPSHOT_SCHEMA, collect_account_snapshot, collect_wallet_scan
from .AccountStore import read_evidence
from .ExecutionFacts import MAX_REQUESTS, _market, collect_execution_scan
from .NativeAccountCheck import _publish_unavailable, reconcile_native_account
from .NativeBalanceReservations import collect_native_balance_reservations
from .NativeCurrentComponents import assert_native_components_current, read_native_component_policy
from .NativeMarketEvidence import _markets, collect_native_market_evidence
from .NativePendingOrders import collect_native_pending_orders


SCHEMA = "chan-native-collected-components-v1"
_ROOT = Path(__file__).resolve().parents[1]
_SOURCES = ("Trade/NativeComponentCollector.py", "Trade/NativeCurrentComponents.py", "Trade/NativeAdmission.py",
            "Trade/NativeAccountCheck.py", "Trade/NativeAccountReconcile.py", "Trade/AccountRiskStore.py", "Trade/AccountReconcile.py",
            "Trade/AccountIdentity.py", "Trade/AccountSources.py", "Trade/AccountStore.py", "Trade/ExecutionFacts.py",
            "Trade/ExecutionStore.py", "Trade/ExecutionReconcile.py", "Trade/NativePendingOrders.py", "Trade/NativePendingOwnership.py",
            "Trade/NativeBalanceReservations.py", "Trade/NativeAccountStore.py", "Trade/NativeMarketEvidence.py",
            "Trade/OrderAudit.py", "Trade/db_util.py", "Trade/SqliteDB.py", "CustomBuySellPoint/Decision.py", "Common/KLineTime.py")


def _fail():
    raise CChanException("原生组件自采/持久核验失败，禁止据此新增风险；不得自动重试或解冻", ErrCode.TRADE_UNLOCK_FAIL) from None


def _implementation():
    return {name: hashlib.sha256((_ROOT/name).read_bytes()).hexdigest() for name in _SOURCES}


def collect_and_check_native_components(chan, exchange, *, mode, markets, before_id, account_scope, policy):
    """Collect GETs outside writer locks, publish via original stores/checks."""
    # Invalid entry arguments and already-owned/frozen databases do not start
    # I/O. A valid baseline supplies the target account for failure publication.
    if chan.db_type != "sqlite" or chan.db.conn.in_transaction:
        _fail()
    provided = {"mode": mode, "markets": markets, "before_id": before_id, "account_scope": account_scope, "policy": policy}
    original = canonical_bytes(provided)
    values = json.loads(original)
    policy = read_native_component_policy(values["policy"])
    if (mode not in {"testnet", "live"} or type(values["account_scope"]) is not str
            or re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", values["account_scope"]) is None):
        _fail()
    units = _markets(values["markets"], exchange.id)
    database, connection, table = chan.db, chan.db.conn, chan.table
    implementation, started = _implementation(), utc_now_ms()
    with database.transaction():
        before = read_evidence(database, values["before_id"])
        if before["schema"] != SNAPSHOT_SCHEMA or before["payload"]["account_context"]["mode"] != mode:
            _fail()
        context = before["payload"]["account_context"]
        baseline_units = before["payload"]["markets"]
        if canonical_bytes(sorted(baseline_units, key=lambda row: row["id"])) != canonical_bytes(sorted((_market(row) for row in units), key=lambda row: row["id"])):
            _fail()
        by_id = {row["id"]: row for row in units}
        after_units = [by_id[row["id"]] for row in baseline_units]
        if risk_state(database, context)["frozen"]:
            _fail()
        ledger = canonical_bytes(_ledger(chan))
        location = _sha(database.query("PRAGMA database_list"))
    request = {"before": values["before_id"], "after": "0"*64, "wallets": [], "executions": [], "pending": "0"*64, "balance": "0"*64}
    check, published, operations, scans = None, False, [], []

    def same_database():
        if database.conn is not connection or _sha(database.query("PRAGMA database_list")) != location:
            _fail()

    def stable():
        same_database()
        if (chan.db is not database or chan.table != table or _implementation() != implementation
                or canonical_bytes(provided) != original):
            _fail()

    def same_context(actual):
        if canonical_bytes(actual) != canonical_bytes(context):
            _fail()

    try:
        pending = collect_native_pending_orders(exchange, units, mode=mode)
        request["pending"] = _sha(pending)
        same_context(pending["payload"]["account_context"])
        operations.append("pending")
        balance = collect_native_balance_reservations(exchange, mode=mode)
        request["balance"] = _sha(balance)
        same_context(balance["payload"]["account_context"])
        operations.append("balance")
        # A real additional identity observation also separates the integer
        # millisecond endpoints. No invented clock advance or network retry.
        same_context(observe_account_context(exchange, mode))
        after = collect_account_snapshot(exchange, after_units, mode=mode)
        request["after"] = _sha(after)
        same_context(after["payload"]["account_context"])
        operations.append("after")
        start, end = before["payload"]["started_ms"], after["payload"]["finished_ms"]+1
        for unit in units:
            begin = utc_now_ms()
            first = observe_account_context(exchange, mode)
            same_context(first)
            receipt = collect_execution_scan(exchange, unit, account_scope=values["account_scope"], mode=mode, start_ms=start, end_ms=end)
            last = observe_account_context(exchange, mode)
            same_context(last)
            scans.append((receipt, {"before": first, "after": last, "started_ms": begin, "finished_ms": utc_now_ms()}))
            request["executions"].append(receipt["payload_sha256"])
            operations.append("execution:"+unit["symbol"])
        wallet = collect_wallet_scan(exchange, mode=mode, start_ms=start, end_ms=end)
        request["wallets"] = [_sha(wallet)]
        same_context(wallet["payload"]["account_context"])
        operations.append("wallet")
        market = collect_native_market_evidence(exchange, units, mode=mode)
        operations.append("market")
        stable()
        with database.transaction():
            stable()
            if canonical_bytes(_ledger(chan)) != ledger:
                _fail()
            chan.store_native_account_observation(pending)
            chan.store_native_account_observation(balance)
            chan.store_account_evidence(after)
            for receipt, observed in scans:
                chan.store_execution_scan(receipt, account_observation=observed)
            chan.store_account_evidence(wallet)
            check = reconcile_native_account(chan, context, request)
        published = True
        if check["payload"]["report"]["payload"]["status"] != "matched_observations":
            _fail()  # Its precise original failure has already been committed.
        assert_native_components_current(chan, exchange, mode=mode, markets=units, account_context=context,
            check_id=_sha(check), market_evidence=market, policy=policy)
        operations.append("current")
        stable()
        observed = (pending["payload"]["requests"]+balance["payload"]["requests"]+after["payload"]["requests"]+3
                    +sum(receipt["payload"]["requests"]+2 for receipt, _ in scans)+wallet["payload"]["requests"]+2
                    +market["payload"]["requests"]+2)
        bound = (2*MAX_REQUESTS+20 if context["venue"] == "binance" else 2*MAX_REQUESTS+18)+(MAX_REQUESTS+4)*len(units)
        if len(operations) != len(units)+6 or observed > bound:
            _fail()
        payload = {"coverage": "local_collector_owned_observations", "economics_complete": False, "native_admission_verified": False,
                   "account_context": context, "source_ids": request, "check_id": _sha(check), "market_evidence": market,
                   "policy": policy, "operations": operations, "observed_sdk_calls": observed, "sdk_call_upper_bound": bound,
                   "implementation_sha256": implementation, "database_location_sha256": location,
                   "started_ms": started, "finished_ms": utc_now_ms()}
        return {"schema": SCHEMA, "payload": payload, "payload_sha256": _sha(payload)}
    except Exception:
        # Do not raise from inside the publication transaction and undo the
        # very freeze a missing/unusable source must create. Never reset one.
        if not published or check["payload"]["report"]["payload"]["status"] == "matched_observations":
            try:
                same_database()
                with database.transaction():
                    same_database()
                    _publish_unavailable(database, context, request)
            except Exception:
                _fail()  # No persisted-freeze claim when publication failed.
        _fail()
