"""Original cash/position engine plus native pending and margin observations."""
import copy
import importlib.util
import json
import subprocess
import sys

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.AccountReconcile import build_account_reconciliation
from Trade.AccountSources import collect_wallet_scan
from Trade.ExecutionFacts import collect_execution_scan
from Trade.OpenQuotaGen import CBenchPriceQuotaGen
from Trade.db_util import CChanDB
from Trade.NativeBalanceReservations import collect_native_balance_reservations
from Trade.NativePendingOrders import collect_native_pending_orders
from .test_account_reconciliation import interval_case
from .test_crypto_order_contract import open_legacy_history
from .test_account_risk_freeze import persist
from .test_execution_account_binding import observation
from .test_execution_facts import NativeSources, definition, fill
from .test_execution_store import store
from .test_m6_trade import make_signal
from .test_native_admission_interval import explicit_path_environment
from .test_native_pending_orders import regular_row
from .test_native_account_snapshot import position
from .test_native_account_sources import AccountSourceIO, wallet_row


def components_api():
    assert importlib.util.find_spec("Trade.NativeAccountReconcile") is not None, "original-ledger native component reconciler is missing"
    from Trade.NativeAccountReconcile import observe_native_account_components
    return observe_native_account_components


def component_case(db, tmp_path, monkeypatch, venue, *, side=True, mode="one_way", damage=None, foreign_margin=None, per_market_ids=False,
                   balance_damage=None, pending_terminal=False):
    captured = {}
    units = [definition(venue)]
    units.append({**units[0], "id": "ALTUSDT" if venue == "binance" else "ALT-USDT-SWAP",
                  "symbol": "ALT/USDT:USDT", "base": "ALT", "contractSize": "0.1"})
    def foreign_asset(at):
        if venue == "binance":
            return {"asset": "BNB", "walletBalance": "0.5", "unrealizedProfit": "0", "marginBalance": "0.5",
                    "initialMargin": foreign_margin, "positionInitialMargin": "0", "openOrderInitialMargin": foreign_margin,
                    "maintMargin": "0", "availableBalance": "0.5", "crossWalletBalance": "0.5", "crossUnPnl": "0", "updateTime": at}
        return {"ccy": "BNB", "cashBal": "0.5", "eq": "0.5", "upl": "0", "availBal": "0.5", "availEq": "0.5", "imr": "0", "mmr": "0",
                "ordFrozen": foreign_margin, "frozenBal": foreign_margin, "isoEq": "0", "isoUpl": "0", "isoLiab": "0", "crossLiab": "0", "uplLiab": "0",
                "liab": "0", "interest": "0", "stgyEq": "0", "smtSyncEq": "0", "spotCopyTradingEq": "0", "fixedBal": "0", "spotIsoBal": "0", "uTime": str(at)}
    def before_sources(native, positions, account, settings, clock, trade):
        if foreign_margin is not None:
            account["assets" if venue == "binance" else "details"].append(foreign_asset(clock[0]))
    def after_sources(native, positions, account, settings, clock, trade, key):
        for module in ("Trade.NativeBalanceReservations", "Trade.NativePendingOrders"):
            monkeypatch.setattr(module+".utc_now_ms", lambda: clock[0])
        first = trade.exchange.market("TEST/USDT:USDT")
        second = copy.deepcopy(first)
        second.update(id=units[1]["id"], symbol=units[1]["symbol"], base="ALT", baseId="ALT", contractSize=0.1)
        trade.exchange.set_markets([first, second])
        trade.exchange.builder.set_markets([first, second])
        clock[0] -= 50
        if per_market_ids:
            create = trade.exchange.create_order
            def create_per_market(*args, **kwargs):
                result = create(*args, **kwargs)
                result["id"] = db.get_record(key)["open_order_id"]
                return result
            monkeypatch.setattr(trade.exchange, "create_order", create_per_market)
        trade.quota_gen = CBenchPriceQuotaGen(60.7)
        trade.exchange.fill, trade.exchange.status = 3, "canceled" if pending_terminal else "open"
        pending_key = db.add_signal(make_signal(code=units[1]["symbol"], is_buy=side))
        open_legacy_history(trade, db.get_record(pending_key), 100)
        captured.update(pending_key=pending_key, native=native, clock=clock, at=clock[0])
        clock[0] += 50
        record = db.get_record(pending_key)
        contract = json.loads(record["open_order_contract"])
        quantity = ("0.3" if side else "-0.3") if venue == "binance" else ("3" if side or mode == "hedged" else "-3")
        other = position(venue, captured["at"], leg=record["position_side"], quantity=quantity, instrument=units[1]["id"])
        if venue == "binance":
            other.update(entryPrice="100", markPrice="100", unRealizedProfit="0", notional="30" if side else "-30", initialMargin="10", maintMargin="0.15")
            account["positions"].append({"symbol": units[1]["id"], "positionSide": record["position_side"], "positionAmt": quantity,
                "unrealizedProfit": "0", "initialMargin": "10", "maintMargin": "0.15", "notional": "30" if side else "-30", "updateTime": captured["at"]})
            settings.append({**settings[0], "symbol": units[1]["id"]})
        else:
            other.update(avgPx="100", markPx="100", upl="0", notionalUsd="30", imr="10", mmr="0.15", posId="72")
        positions.append(other)
        config = ({"canTrade": True, "dualSidePosition": mode == "hedged", "multiAssetsMargin": False, "updateTime": 0}
                  if venue == "binance" else {"uid": "12345678", "acctLv": "2", "posMode": "long_short_mode" if mode == "hedged" else "net_mode",
                    "autoLoan": False, "enableSpotBorrow": False, "ctIsoMode": "automatic", "stgyType": "0", "roleType": "0", "spotRoleType": "0"})
        if venue == "binance":
            monkeypatch.setattr(native, "fapiPrivateGetAccountConfig", lambda params: copy.deepcopy(config))
            asset = account["assets"][0]
            asset.update(walletBalance="1000.073", marginBalance="1000.473", maintMargin="0.2", positionInitialMargin="11", openOrderInitialMargin="10", initialMargin="21",
                         crossWalletBalance="1000.073", crossUnPnl=asset["unrealizedProfit"], availableBalance="979.473")
            account.update(totalWalletBalance="1000.073", totalMarginBalance="1000.473", totalInitialMargin="21", totalMaintMargin="0.2",
                           totalPositionInitialMargin="11", totalOpenOrderInitialMargin="10",
                           totalCrossWalletBalance=asset["walletBalance"], totalCrossUnPnl=asset["unrealizedProfit"], availableBalance="979.473")
        else:
            monkeypatch.setattr(native, "privateGetAccountConfig", lambda params: {"code": "0", "data": [copy.deepcopy(config)]})
            asset = account["details"][0]
            asset.update(cashBal="1000.073", eq="1000.473", availBal="979.073", availEq="979.473", imr="21", mmr="0.2", frozenBal="10", ordFrozen="10", isoUpl="0", isoLiab="0",
                         crossLiab="0", uplLiab="0", stgyEq="0", smtSyncEq="0", spotCopyTradingEq="0", fixedBal="0", spotIsoBal="0")
        if foreign_margin is not None:
            account["assets" if venue == "binance" else "details"].append(foreign_asset(clock[0]))
        pending = regular_row(venue, contract["market"]["id"], int(record["open_order_id"]), partial=True)
        if venue == "binance":
            pending.update(origQty=contract["quantity"], executedQty="0.3", clientOrderId=record["open_client_order_id"],
                           side="BUY" if side else "SELL", positionSide=record["position_side"], price=contract["price"],
                           reduceOnly=False, time=record["open_intent_ms"]+1, updateTime=record["open_intent_ms"]+1)
            monkeypatch.setattr(native, "fapiPrivateGetOpenOrders", lambda params: [] if pending_terminal else [copy.deepcopy(pending)])
            monkeypatch.setattr(native, "fapiPrivateGetOpenAlgoOrders", lambda params: [])
        else:
            pending.update(sz=contract["exchange_amount"], accFillSz="3", clOrdId=record["open_client_order_id"],
                           side="buy" if side else "sell", posSide="net" if mode == "one_way" else record["position_side"].lower(),
                           px=contract["price"], reduceOnly="false",
                           cTime=str(record["open_intent_ms"]+1), uTime=str(record["open_intent_ms"]+1))
            monkeypatch.setattr(native, "privateGetTradeOrdersPending", lambda params: {"code": "0", "data": [] if pending_terminal else [copy.deepcopy(pending)]})
            monkeypatch.setattr(native, "privateGetTradeOrdersAlgoPending", lambda params: {"code": "0", "data": []})
        if damage is not None:
            damage(account, config, pending)
        method = "fapiPrivateV3GetAccount" if venue == "binance" else "privateGetAccountBalance"
        get_balance = getattr(native, method)
        if balance_damage is not None:
            def separate_balance(params):
                response = get_balance(params)
                balance_damage(response if venue == "binance" else response["data"][0])
                return response
            monkeypatch.setattr(native, method, separate_balance)
        captured.update(pending_orders=collect_native_pending_orders(native, [trade._market_contract(unit["symbol"])[0] for unit in units], mode="testnet"),
                        balance_reservations=collect_native_balance_reservations(native, mode="testnet"))
        monkeypatch.setattr(native, method, get_balance)
        clock[0] += 1  # Final account snapshot covers the two earlier observations.
    inputs, trade, key = interval_case(db, tmp_path, monkeypatch, venue, side=side, mode=mode,
                                      source_markets=units, after_sources=after_sources, before_sources=before_sources)
    record = db.get_record(captured["pending_key"])
    row = fill(venue, captured["at"], key=103, quantity="0.3" if venue == "binance" else "3", price="100", fee="0.003",
               side="buy" if side else "sell", leg=record["position_side"])
    row["symbol" if venue == "binance" else "instId"] = units[1]["id"]
    row["orderId" if venue == "binance" else "ordId"] = record["open_order_id"]
    if venue == "okx":
        row["clOrdId"] = record["open_client_order_id"]
    source = collect_execution_scan(NativeSources(venue, [row], []), units[1], account_scope="offline-account", mode="testnet",
                                    start_ms=inputs["before"]["payload"]["started_ms"]-1,
                                    end_ms=inputs["after"]["payload"]["finished_ms"]+1)
    db.store_execution_scan(source, account_observation=observation(trade))
    linked = db.get_execution_scan_account(source["payload_sha256"])
    inputs["executions"].append({"receipt": source, "account_context": linked["observation"]["account_context"],
                                  "manifest_sha256": linked["manifest_sha256"], "observed_ms": linked["observation"]["finished_ms"]})
    flow = wallet_row(venue, captured["at"], key=104 if venue == "binance" else 1103,
                      kind="COMMISSION" if venue == "binance" else "TRADE", amount="-0.003", instrument=units[1]["id"])
    flow["tradeId"] = "103"
    if venue == "okx":
        flow.update(fee="-0.003", pnl="0", bal="1000.073", ordId=record["open_order_id"], clOrdId=record["open_client_order_id"])
    io = AccountSourceIO(venue, [*[copy.deepcopy(fact["raw"]) for fact in inputs["wallets"][0]["payload"]["facts"]], flow])
    monkeypatch.setattr(captured["native"], "fapiPrivateGetIncome" if venue == "binance" else "privateGetAccountBillsArchive", io.wallet)
    inputs["wallets"] = [collect_wallet_scan(captured["native"], mode="testnet", start_ms=inputs["before"]["payload"]["started_ms"]-1,
                                             end_ms=inputs["after"]["payload"]["finished_ms"]+1)]
    inputs["histories"].append(db.get_order_history(captured["pending_key"]))
    inputs["projections"].append({"trade_table": db.table, "record_id": captured["pending_key"], "instrument": units[1]["symbol"],
                                  "current_qty": record["current_qty"], "position_side": record["position_side"], "is_buy": side})
    return {**persist(db, inputs), **{name: captured[name] for name in ("pending_orders", "balance_reservations")}}, inputs, trade, key


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mode,side", [(mode, side) for mode in ("one_way", "hedged") for side in (True, False)])
def test_real_partial_close_fees_and_funding_use_original_core_with_nonzero_native_pending(store, tmp_path, monkeypatch, venue, mode, side):
    read = components_api()
    db, conf = store
    params, inputs, trade, key = component_case(db, tmp_path, monkeypatch, venue, mode=mode, side=side)
    old = build_account_reconciliation(**inputs)
    assert old["schema"] == "chan-account-reconciliation-v1"
    assert old["payload"]["status"] == "incomplete" and {issue["reason"] for issue in old["payload"]["issues"]} == {"unresolved_attempt"}
    before, history, changes = db.get_record(key), db.get_order_history(key), db.db.conn.total_changes
    report = read(db, **params)
    assert report["schema"] == "chan-native-account-components-v1"
    p = report["payload"]
    assert p["status"] == "matched_components" and p["issues"] == [], p["issues"]
    assert p["economics_complete"] is p["native_admission_verified"] is False
    interval = p["interval"]["payload"]
    assert p["interval"]["schema"] == "chan-account-reconciliation-pending-v2"
    assert interval["status"] == "matched_observations"
    assert interval["wallets"][0]["difference"] == {"numerator": "0", "denominator": "1"}
    primary = next(row for row in interval["positions"] if row["leg"][0] == "TEST/USDT:USDT")
    assert primary["quantity"] == {"numerator": "1", "denominator": "50"}
    assert primary["unrealized_pnl"] == {"numerator": "2", "denominator": "5"}
    assert p["margin"]["currency"] == "USDT" and p["margin"]["reported_available"] == "979.473"
    assert p["margin"]["aggregate_order_margin"] == "10"
    assert len(p["pending"]["payload"]["reservations"]) == 1
    assert db.get_record(key) == before and db.get_order_history(key) == history and db.db.conn.total_changes == changes
    assert len(trade.exchange.created) == 3


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["cash", "missing_margin", "negative_margin", "available", "mode", "pending_qty", "pending_client", "initial_or_frozen",
                                    "available_coverage", "maintenance"])
def test_component_disagreement_or_unknown_never_yields_a_matched_account(store, tmp_path, monkeypatch, venue, damage):
    read = components_api()
    db, _ = store
    def alter(account, config, pending):
        asset = account["assets" if venue == "binance" else "details"][0]
        if damage == "cash":
            asset["walletBalance" if venue == "binance" else "cashBal"] = "1001"
        elif damage == "missing_margin":
            del asset["openOrderInitialMargin" if venue == "binance" else "ordFrozen"]
        elif damage == "negative_margin":
            asset["openOrderInitialMargin" if venue == "binance" else "ordFrozen"] = "-1"
        elif damage == "available":
            asset["availableBalance" if venue == "binance" else "availEq"] = "2000"
        elif damage == "available_coverage":
            asset["availableBalance" if venue == "binance" else "availEq"] = "990"
            if venue == "binance":
                account["availableBalance"] = "990"
        elif damage == "maintenance":
            asset["maintMargin" if venue == "binance" else "mmr"] = "2000"
            if venue == "binance":
                account["totalMaintMargin"] = "2000"
        elif damage == "mode":
            config["multiAssetsMargin" if venue == "binance" else "acctLv"] = True if venue == "binance" else "4"
        elif damage == "pending_qty":
            pending["origQty" if venue == "binance" else "sz"] = "0.7" if venue == "binance" else "7"
        elif damage == "pending_client":
            pending["clientOrderId" if venue == "binance" else "clOrdId"] = "cpDifferentOwner"
        else:
            asset["initialMargin" if venue == "binance" else "frozenBal"] = "1"
    params, _, _, _ = component_case(db, tmp_path, monkeypatch, venue, damage=alter)
    before = db.db.conn.total_changes
    result = read(db, **params)["payload"]
    assert result["status"] in {"incomplete", "mismatch"} and result["issues"]
    reasons = {row["reason"] for row in result["issues"]}
    expected = {"cash": "wallet_difference", "missing_margin": "native_margin_component_missing",
                "negative_margin": "native_margin_component_negative", "available": "native_available_exceeds_equity",
                "mode": "native_account_mode_unproven", "pending_qty": "native_pending_pending_quantity_difference",
                "pending_client": "native_pending_client_id_mismatch", "initial_or_frozen": "native_initial_margin_partition_difference" if venue == "binance" else "native_order_margin_exceeds_frozen",
                "available_coverage": "native_available_margin_coverage_difference", "maintenance": "native_maintenance_not_covered"}[damage]
    assert expected in reasons
    assert result["native_admission_verified"] is False and db.db.conn.total_changes == before


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("foreign_margin", ["0", "1"])
def test_foreign_fee_cash_is_kept_separate_and_cannot_hide_unexplained_margin(store, tmp_path, monkeypatch, venue, foreign_margin):
    db, _ = store
    params, _, _, _ = component_case(db, tmp_path, monkeypatch, venue, foreign_margin=foreign_margin)
    result = components_api()(db, **params)["payload"]
    if foreign_margin == "0":
        assert result["status"] == "matched_components" and result["margin"]["reported_available"] == "979.473"
        assert {row["currency"] for row in result["interval"]["payload"]["wallets"]} == {"USDT", "BNB"}
    else:
        assert result["status"] == "incomplete"
        assert "foreign_margin_channel_unproven" in {row["reason"] for row in result["issues"]}


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_an_old_incomplete_check_remains_sticky_after_component_match(store, tmp_path, monkeypatch, venue):
    db, _ = store
    params, _, _, _ = component_case(db, tmp_path, monkeypatch, venue)
    original_params = {key: value for key, value in params.items() if key not in {"pending_orders", "balance_reservations"}}
    old = db.reconcile_account(**original_params)
    assert old["payload"]["report"]["payload"]["status"] == "incomplete"
    before = db.db.conn.total_changes
    result = components_api()(db, **params)["payload"]
    assert result["status"] == "incomplete" and "persisted_account_frozen" in {row["reason"] for row in result["issues"]}
    assert db.get_account_risk_state(params["account_context"])["frozen"] and db.db.conn.total_changes == before


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_component_reader_restarts_without_optional_sdk_and_does_not_publish(store, tmp_path, monkeypatch, venue):
    db, conf = store
    params, _, _, _ = component_case(db, tmp_path, monkeypatch, venue)
    expected = components_api()(db, **params)
    code = """
import importlib.abc, json, sys
blocked = {'ccxt', 'yaml', 'xgboost', 'lightgbm', 'sklearn', 'optuna', 'PyQt6', 'minio', 'qcloud_cos'}
attempted = []
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            attempted.append(fullname)
            raise ModuleNotFoundError('optional dependency intentionally absent')
sys.meta_path.insert(0, BlockOptional())
from Config.EnvConfig import CEnv
from Trade.NativeAccountReconcile import observe_native_account_components
from Trade.db_util import CChanDB
values = json.loads(sys.stdin.buffer.read())
env = CEnv.__new__(CEnv)
env.conf = {}
CEnv._instance = env
db = CChanDB(db_conf=values['db'])
try:
    changes = db.db.conn.total_changes
    assert observe_native_account_components(db, **values['params']) == values['expected']
    assert db.db.conn.total_changes == changes and not db.db.conn.in_transaction
finally:
    db.close()
assert not attempted, attempted
print('Original financial components without optional SDK PASS')
"""
    result = subprocess.run([sys.executable, "-c", code], input=canonical_bytes({"db": conf, "params": params, "expected": expected}),
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.strip() == b"Original financial components without optional SDK PASS" and result.stderr == b""


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_zero_fill_terminal_history_cannot_create_a_best_match_for_a_duplicate_native_id(store, tmp_path, monkeypatch, venue):
    db, conf = store
    params, inputs, trade, key = component_case(db, tmp_path, monkeypatch, venue)
    before = inputs["before"]["payload"]["started_ms"]-100
    for module in ("Trade.OrderAudit", "Trade.db_util"):
        monkeypatch.setattr(module+".utc_now_ms", lambda: before)
    other = CChanDB(db_conf=conf, table_name="duplicate_attempts")
    try:
        duplicate = other.add_signal(make_signal(code="TEST/USDT:USDT"))
        qty, _, contract = trade.prepare_order("TEST/USDT:USDT", 0.03, 100, record=other.get_record(duplicate))
        native_id = db.get_record(key)["open_order_id"]
        assert other.acquire_open_intent(duplicate, qty, "cpDuplicateCanceled", order_contract=contract)
        assert other.claim_order_submission(duplicate, "open")
        other.record_order_ack(duplicate, "open", native_id, client_order_id="cpDuplicateCanceled", expected_attempt=1)
        other.apply_open_fill(duplicate, 0, None, "canceled", order_id=native_id, client_order_id="cpDuplicateCanceled", expected_attempt=1)
        result = components_api()(db, **params)["payload"]
        assert result["status"] == "incomplete"
        assert "ambiguous_historical_order_id" in {row["reason"] for row in result["issues"]}
    finally:
        other.close()


def test_binance_cross_market_id_collision_is_a_legal_separate_namespace(store, tmp_path, monkeypatch):
    db, _ = store
    params, _, _, key = component_case(db, tmp_path, monkeypatch, "binance", per_market_ids=True)
    result = components_api()(db, **params)["payload"]
    assert result["status"] == "matched_components" and result["issues"] == []
    pending_order = params["pending_orders"]["payload"]["orders"][0]
    assert pending_order["native_order_id"] == db.get_record(key)["open_order_id"]


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("source", ["wallet_ids", "execution_scan_ids"])
def test_missing_original_scan_coverage_is_not_replaced_by_native_margin_fields(store, tmp_path, monkeypatch, venue, source):
    db, _ = store
    params, _, _, _ = component_case(db, tmp_path, monkeypatch, venue)
    params[source] = []
    result = components_api()(db, **params)["payload"]
    assert result["status"] == "incomplete"
    assert ("wallet_window_missing" if source == "wallet_ids" else "execution_window_missing") in {row["reason"] for row in result["issues"]}


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("mutate", [False, True])
def test_original_savepoint_and_source_bytes_survive_the_component_read(store, tmp_path, monkeypatch, venue, mutate):
    db, _ = store
    params, _, _, _ = component_case(db, tmp_path, monkeypatch, venue)
    query = db.db.query
    def inspect(sql, *args, **kwargs):
        assert db.db.conn.in_transaction
        if mutate:
            params["wallet_ids"].clear()
        return query(sql, *args, **kwargs)
    monkeypatch.setattr(db.db, "query", inspect)
    with db.db.transaction():
        before = db.db.conn.total_changes
        if mutate:
            with pytest.raises(CChanException):
                components_api()(db, **params)
        else:
            assert components_api()(db, **params)["payload"]["status"] == "matched_components"
        assert db.db.conn.total_changes == before and db.db.conn.in_transaction
    assert not db.db.conn.in_transaction


@pytest.mark.parametrize("damage", ["quantity", "unrealized", "missing_quantity", "extra_leg", "isolated_wallet"])
def test_independent_balance_position_rows_must_agree_with_the_final_account(store, tmp_path, monkeypatch, damage):
    db, _ = store
    def alter(balance):
        row = balance["positions"][0]
        if damage == "quantity":
            row["positionAmt"] = "0.03"
        elif damage == "unrealized":
            row["unrealizedProfit"] = "0.5"
        elif damage == "missing_quantity":
            del row["positionAmt"]
        elif damage == "extra_leg":
            balance["positions"].append({"symbol": "FOREIGNUSDT", "positionSide": "BOTH", "positionAmt": "0.01", "unrealizedProfit": "0", "updateTime": row["updateTime"]})
        else:
            row["isolatedWallet"] = "5"
    params, _, _, _ = component_case(db, tmp_path, monkeypatch, "binance", balance_damage=alter)
    result = components_api()(db, **params)["payload"]
    assert result["status"] in {"incomplete", "mismatch"}
    expected = {"quantity": "native_balance_position_difference", "unrealized": "native_balance_position_difference",
                "missing_quantity": "native_balance_position_component_missing", "extra_leg": "native_balance_position_coverage",
                "isolated_wallet": "native_position_isolated_channel_unproven"}[damage]
    assert expected in {row["reason"] for row in result["issues"]}


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_empty_native_lists_cannot_explain_nonzero_account_order_margin(store, tmp_path, monkeypatch, venue):
    db, _ = store
    params, _, _, _ = component_case(db, tmp_path, monkeypatch, venue, pending_terminal=True)
    assert params["pending_orders"]["payload"]["orders"] == []
    result = components_api()(db, **params)["payload"]
    assert result["status"] == "incomplete" and "unexplained_native_order_margin" in {row["reason"] for row in result["issues"]}


@pytest.mark.parametrize("field", ["cross_cash", "cross_upl", "avail_eq"])
def test_new_balance_amounts_cannot_override_a_different_final_snapshot_field(store, tmp_path, monkeypatch, field):
    db, _ = store
    venue = "okx" if field == "avail_eq" else "binance"
    def final_values(account, config, pending):
        row = account["assets" if venue == "binance" else "details"][0]
        if field == "avail_eq":
            row["availEq"] = "900"
        elif field == "cross_cash":
            row["crossWalletBalance"], account["totalCrossWalletBalance"] = "990", "990"
        else:
            row["crossUnPnl"], account["totalCrossUnPnl"] = "0.3", "0.3"
    def earlier_values(balance):
        row = balance["assets" if venue == "binance" else "details"][0]
        if field == "avail_eq":
            row["availEq"] = "950"
        elif field == "cross_cash":
            row["crossWalletBalance"], balance["totalCrossWalletBalance"] = "1000.073", "1000.073"
        else:
            row["crossUnPnl"], balance["totalCrossUnPnl"] = "0.4", "0.4"
    params, _, _, _ = component_case(db, tmp_path, monkeypatch, venue, damage=final_values, balance_damage=earlier_values)
    result = components_api()(db, **params)["payload"]
    assert result["status"] in {"mismatch", "incomplete"}
    assert "native_snapshot_raw_component_difference" in {row["reason"] for row in result["issues"]}


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_reported_native_restrictions_can_make_available_amount_lower_than_the_ceiling(store, tmp_path, monkeypatch, venue):
    db, _ = store
    def lower(account, config, pending):
        row = account["assets" if venue == "binance" else "details"][0]
        row["availableBalance" if venue == "binance" else "availEq"] = "900"
        if venue == "binance":
            account["availableBalance"] = "900"
    params, _, _, _ = component_case(db, tmp_path, monkeypatch, venue, damage=lower)
    result = components_api()(db, **params)["payload"]
    assert result["status"] == "matched_components" and result["margin"]["reported_available"] == "900"
