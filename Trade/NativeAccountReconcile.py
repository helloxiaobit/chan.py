"""Original-ledger interval and native margin components; no admission/write.

The consumer of this observation must still own collection, freshness, durable
failure publication and the original order CAS. Native amounts are not fitted
to software leverage rates or divided among pending orders.
"""
import json

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes
from .AccountReconcile import _number, _sha, build_account_reconciliation_with_pending
from .AccountRiskStore import _ledger, _sources, _client_roots, risk_state
from .NativeBalanceReservations import verify_native_balance_reservations


SCHEMA = "chan-native-account-components-v1"


def _fail():
    raise CChanException("原生账户组件/原账本证据缺失或漂移，不能作为资金准入", ErrCode.TRADE_UNLOCK_FAIL) from None


def _balance_positions(after, balances, issue):
    if after["account_context"]["venue"] != "binance":
        return  # OKX balance has no position rows; the original unfiltered source supplies them.
    key = lambda row: (row["symbol"], row["positionSide"])
    final = {key(row): row for row in after["raw"]["account"]["positions"]}
    earlier = {(row["instrument_id"], row["position_side"]): row["native_fields"] for row in balances["native_account_positions"]}
    if set(final) != set(earlier):
        issue("native_balance_position_coverage", incomplete=True)
    for identity in sorted(set(final) & set(earlier)):
        old, new = earlier[identity], final[identity]
        for field in ("positionAmt", "unrealizedProfit", "initialMargin", "maintMargin", "isolatedMargin", "isolatedWallet", "notional"):
            left, right = old.get(field), new.get(field)
            if left is None and right is None and field not in {"positionAmt", "unrealizedProfit"}:
                continue  # Optional fields unused by this comparison remain unknown.
            if left is None or right is None:
                issue("native_balance_position_component_missing", incomplete=True, leg=list(identity), field=field)
            elif _number(left) != _number(right):
                issue("native_balance_position_difference", leg=list(identity), field=field)
            if field in {"isolatedMargin", "isolatedWallet"} and any(value is not None and _number(value) != 0 for value in (left, right)):
                issue("native_position_isolated_channel_unproven", incomplete=True, leg=list(identity), field=field)


def _margin(after, balances, pending_validation, issue):
    venue, config = after["account_context"]["venue"], balances["configuration"]
    if venue == "binance":
        if config.get("canTrade") is not True or config.get("multiAssetsMargin") is not False or after["raw"]["multi_assets_margin"] is not False:
            issue("native_account_mode_unproven", incomplete=True)
        mode = "hedged" if config["dualSidePosition"] else "one_way"
    else:
        if (config.get("acctLv") != "2" or config.get("autoLoan") is not False or config.get("enableSpotBorrow") is not False
                or any(config.get(key) != "0" for key in ("stgyType", "roleType", "spotRoleType"))):
            issue("native_account_mode_unproven", incomplete=True)
        mode = "one_way" if config["posMode"] == "net_mode" else "hedged"
    for position in after["positions"]:
        if position["margin_mode"] != "cross" or ((position["position_side"] == "BOTH") != (mode == "one_way")):
            issue("native_position_mode_unproven", incomplete=True, instrument=position["instrument_id"])
    observed = {row["currency"]: row["native_fields"] for row in balances["assets"]}
    previous = {row["currency"]: row for row in after["assets"]}
    label, group = ("asset", "assets") if venue == "binance" else ("ccy", "details")
    final_raw = {row[label]: row for row in after["raw"]["account"][group]}
    if set(observed) != set(previous) or "USDT" not in observed:
        issue("native_balance_currency_coverage", incomplete=True)
    links = ({"walletBalance": "cash_balance", "unrealizedProfit": "unrealized_pnl", "marginBalance": "equity",
              "initialMargin": "initial_margin", "maintMargin": "maintenance_margin", "availableBalance": "available_balance"}
             if venue == "binance" else {"cashBal": "cash_balance", "upl": "unrealized_pnl", "eq": "equity",
                "imr": "initial_margin", "mmr": "maintenance_margin", "availBal": "available_balance"})
    def amount(row, key, currency):
        value = row.get(key)
        if value is None:
            issue("native_margin_component_missing", incomplete=True, currency=currency, field=key)
            return None
        return _number(value)
    for currency in sorted(set(observed) & set(previous)):
        row, snapshot = observed[currency], previous[currency]
        for native, normalized in links.items():
            left, right = amount(row, native, currency), snapshot[normalized]
            if right is None:
                issue("native_snapshot_component_missing", incomplete=True, currency=currency, field=normalized)
            elif left is not None and left != _number(right):
                issue("native_snapshot_component_difference", currency=currency, field=native)
        # These fields are retained in the original snapshot raw body but do
        # not have a normalized v1 alias. Never let an earlier value supersede
        # the final endpoint, especially OKX derivative available equity.
        for key in (("crossWalletBalance", "crossUnPnl") if venue == "binance" else ("availEq",)):
            left, right = amount(row, key, currency), final_raw[currency].get(key)
            if right is None or right == "":
                issue("native_snapshot_raw_component_missing", incomplete=True, currency=currency, field=key)
            elif left is not None and left != _number(right):
                issue("native_snapshot_raw_component_difference", currency=currency, field=key)
        if currency != "USDT":
            fields = (("initialMargin", "positionInitialMargin", "openOrderInitialMargin", "maintMargin")
                      if venue == "binance" else ("imr", "mmr", "ordFrozen", "frozenBal"))
            for key in fields:
                value = amount(row, key, currency)
                if value is None or value != 0:
                    issue("foreign_margin_channel_unproven", incomplete=True, currency=currency, field=key)
        if venue == "okx":
            for key in ("isoEq", "isoUpl", "isoLiab", "crossLiab", "uplLiab", "liab", "interest", "stgyEq", "smtSyncEq", "spotCopyTradingEq", "fixedBal", "spotIsoBal"):
                value = amount(row, key, currency)
                if value:
                    issue("native_other_cash_channels_unproven", incomplete=True, currency=currency, field=key)
    usdt = observed.get("USDT", {})
    available_key = "availableBalance" if venue == "binance" else "availEq"
    margin_key = "openOrderInitialMargin" if venue == "binance" else "ordFrozen"
    available, pending = amount(usdt, available_key, "USDT"), amount(usdt, margin_key, "USDT")
    if pending is not None and pending > 0 and not pending_validation["payload"]["orders"]:
        issue("unexplained_native_order_margin", incomplete=True)
    for key in (("initialMargin", "positionInitialMargin", "openOrderInitialMargin", "maintMargin") if venue == "binance" else ("imr", "mmr", "ordFrozen", "frozenBal")):
        value = amount(usdt, key, "USDT")
        if value is not None and value < 0:
            issue("native_margin_component_negative", currency="USDT", field=key)
    if available is not None and available < 0:
        issue("native_available_negative")
    equity = amount(usdt, "marginBalance" if venue == "binance" else "eq", "USDT")
    if available is not None and equity is not None and available > equity:
        issue("native_available_exceeds_equity")
    initial = amount(usdt, "initialMargin" if venue == "binance" else "imr", "USDT")
    maintenance = amount(usdt, "maintMargin" if venue == "binance" else "mmr", "USDT")
    # Use the reported native IMR once. In particular, do not assume OKX IMR
    # excludes pending orders and then subtract ordFrozen a second time.
    if available is not None and initial is not None and equity is not None and available+initial > equity:
        issue("native_available_margin_coverage_difference")
    if equity is not None and maintenance is not None and maintenance > 0 and equity <= maintenance:
        issue("native_maintenance_not_covered")
    if venue == "binance":
        initial, position = amount(usdt, "initialMargin", "USDT"), amount(usdt, "positionInitialMargin", "USDT")
        if initial is not None and position is not None and pending is not None and initial != position+pending:
            issue("native_initial_margin_partition_difference")
        totals = balances["reported_totals"]
        if totals["currency"] != "USDT":
            issue("native_total_currency_unproven", incomplete=True)
        fields = {"totalWalletBalance": "walletBalance", "totalUnrealizedProfit": "unrealizedProfit", "totalMarginBalance": "marginBalance",
                  "totalInitialMargin": "initialMargin", "totalPositionInitialMargin": "positionInitialMargin",
                  "totalOpenOrderInitialMargin": "openOrderInitialMargin", "totalMaintMargin": "maintMargin",
                  "totalCrossWalletBalance": "crossWalletBalance", "totalCrossUnPnl": "crossUnPnl", "availableBalance": "availableBalance"}
        for total, asset in fields.items():
            left, right = amount(totals["native_fields"], total, "USDT"), amount(usdt, asset, "USDT")
            if left is not None and right is not None and left != right:
                issue("native_total_component_difference", field=total)
        for cross, whole in (("crossWalletBalance", "walletBalance"), ("crossUnPnl", "unrealizedProfit")):
            left, right = amount(usdt, cross, "USDT"), amount(usdt, whole, "USDT")
            if left is not None and right is not None and left != right:
                issue("native_cross_cash_channels_unproven", incomplete=True, field=cross)
    else:
        frozen = amount(usdt, "frozenBal", "USDT")
        if frozen is not None and pending is not None and pending > frozen:
            issue("native_order_margin_exceeds_frozen")
    return {"currency": "USDT", "position_mode": mode, "reported_available": usdt.get(available_key),
            "available_field": available_key, "aggregate_order_margin": usdt.get(margin_key),
            "order_margin_field": margin_key, "per_order_allocation": "not_inferred"}


def _result(payload, issues):
    payload["issues"] = sorted({canonical_bytes(row): row for row in issues}.values(), key=canonical_bytes)
    payload["status"] = "incomplete" if any(row["severity"] == "incomplete" for row in issues) else "mismatch" if issues else "matched_components"
    return {"schema": "chan-native-account-components-v3" if payload["interval"]["schema"] == "chan-account-reconciliation-pending-v4"
            else "chan-native-account-components-v2" if "client_order_references" in payload["interval"]["payload"] else SCHEMA,
            "payload": payload, "payload_sha256": _sha(payload)}


def _components(context, request, sources, ledger, pending, balances, *, client_roots=()):
    """Pure historical component rebuild; no risk-state recursion or writes."""
    verify_native_balance_reservations(balances)
    after, balance = sources["after"]["payload"], balances["payload"]
    if (canonical_bytes(after["account_context"]) != canonical_bytes(context)
            or canonical_bytes(balance["account_context"]) != canonical_bytes(context)
            or not sources["before"]["payload"]["finished_ms"] < balance["started_ms"] <= balance["finished_ms"] < after["started_ms"]):
        _fail()
    interval = build_account_reconciliation_with_pending(**sources, **ledger, pending_orders=pending, client_roots=client_roots)
    issues = list(interval["payload"]["issues"])
    def issue(reason, *, incomplete=False, **details):
        issues.append({"reason": reason, "severity": "incomplete" if incomplete else "mismatch", **details})
    _balance_positions(after, balance, issue)
    margin = _margin(after, balance, interval["payload"]["pending"], issue)
    payload = {"account_context": context, "source_ids": request, "ledger_sha256": _sha(ledger),
               "balance_source_sha256": balances["payload_sha256"], "interval": interval,
               "pending": interval["payload"]["pending"], "margin": margin,
               "coverage": "provided_native_account_components", "economics_complete": False, "native_admission_verified": False}
    return _result(payload, issues)


def observe_native_account_components(chan, *, account_context, before_id, after_id, wallet_ids, execution_scan_ids,
                                      pending_orders, balance_reservations):
    """Reload original sources/ledger in one SQLite view; do no private I/O."""
    try:
        provided = {"account_context": account_context, "before_id": before_id, "after_id": after_id,
                    "wallet_ids": wallet_ids, "execution_scan_ids": execution_scan_ids,
                    "pending_orders": pending_orders, "balance_reservations": balance_reservations}
        original = canonical_bytes(provided)
        values = json.loads(original)
        if chan.db_type != "sqlite":
            _fail()
        request = {"before": values["before_id"], "after": values["after_id"], "wallets": values["wallet_ids"], "executions": values["execution_scan_ids"]}
        with chan.db.transaction():
            sources, ledger = _sources(chan.db, request), _ledger(chan)
            roots = _client_roots(chan, ledger["histories"])
            report = _components(values["account_context"], request, sources, ledger, values["pending_orders"],
                                 values["balance_reservations"], client_roots=roots)
            if risk_state(chan.db, values["account_context"])["frozen"]:
                report = _result(report["payload"], [*report["payload"]["issues"], {"reason": "persisted_account_frozen", "severity": "incomplete"}])
        if canonical_bytes(provided) != original:
            _fail()
        return report
    except Exception:
        _fail()
