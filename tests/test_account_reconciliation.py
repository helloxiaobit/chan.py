"""Observed account intervals: real native parsing and SQLite attempts, no HTTP."""
import copy
import hashlib
from decimal import Decimal, Subnormal, localcontext

import pytest

from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.AccountReconcile import build_account_reconciliation
from Trade.AccountSources import collect_account_snapshot, collect_wallet_scan
from . import test_crypto_order_contract as order_fixture
from .test_crypto_order_contract import CODE
from .test_crypto_venue_parameters import venue_engine
from .test_execution_account_binding import observation
from .test_execution_facts import NativeSources, collect, definition, fill, funding
from .test_execution_store import store
from .test_m6_trade import make_signal
from .test_native_account_snapshot import asset, position, snapshot_client
from .test_native_account_sources import AccountSourceIO, wallet_client, wallet_row


def interval_case(db, tmp_path, monkeypatch, venue, *, side=True, mode="one_way", store_source=True, after_sources=None, source_markets=None, before_sources=None):
    import Trade.AccountSources as account_source
    import Trade.OrderAudit as audit
    import Trade.db_util as db_module
    at = utc_now_ms()-10_000
    clock = [at]
    for module in (account_source, audit, db_module, order_fixture):
        monkeypatch.setattr(module, "utc_now_ms", lambda: clock[0])
    native, positions, account, settings, _, _ = snapshot_client(monkeypatch, venue)
    trade = venue_engine(db, tmp_path, venue, mode)
    if venue == "binance":
        trade.exchange.account_alias = "fake-Futures-A"
    assets = account["assets" if venue == "binance" else "details"]
    assets[:] = [asset(venue, at, cash="1000", unrealized="0")]
    assets[0]["marginBalance" if venue == "binance" else "eq"] = "1000"
    positions[:] = []
    if venue == "binance":
        account["positions"] = []
        account.update(totalUnrealizedProfit="0", totalMarginBalance="1000")
    else:
        account["uTime"] = str(at)
    if before_sources is not None:
        before_sources(native, positions, account, settings, clock, trade)
    source_markets = [definition(venue)] if source_markets is None else source_markets
    before = collect_account_snapshot(native, source_markets, mode="testnet")
    clock[0] = at+100
    trade.exchange.fill, trade.exchange.status = 3, "closed"
    key = db.add_signal(make_signal(code=CODE, is_buy=side))
    trade.add_trade(db.get_record(key), 100)
    clock[0] = at+200
    trade.exchange.fill, trade.exchange.status = 1, "canceled"
    trade.cover_trade(db.get_record(key), 110 if side else 90, "partial close")
    history = db.get_order_history(key)
    rows = []
    for index, order in enumerate(trade.exchange.orders.values(), 1):
        quantity = str(Decimal(str(order["filled"]))*Decimal("0.01")) if venue == "binance" else str(order["filled"])
        row = fill(venue, at+index*100, key=100+index, quantity=quantity, price=str(order["average"]),
            fee="0.003" if index == 1 else "0.001", side=order["side"], leg=db.get_record(key)["position_side"])
        row["orderId" if venue == "binance" else "ordId"] = order["id"]
        row["realizedPnl" if venue == "binance" else "fillPnl"] = "0" if index == 1 else "0.1"
        if venue == "okx":
            row["clOrdId"] = order["clientOrderId"]
        rows.append(row)
    clock[0] = at+400
    assets[:] = [asset(venue, at+400, cash="1000.076", unrealized="0.4")]
    assets[0]["marginBalance" if venue == "binance" else "eq"] = "1000.476"
    leg = db.get_record(key)["position_side"]
    quantity = ("0.02" if side else "-0.02") if venue == "binance" else ("2" if side or leg != "BOTH" else "-2")
    pos = position(venue, at+200, leg=leg, quantity=quantity)
    pos["markPrice" if venue == "binance" else "markPx"] = "120" if side else "80"
    pos["unRealizedProfit" if venue == "binance" else "upl"] = "0.4"
    if venue == "binance":
        pos["notional"] = "2.4" if side else "-1.6"
    positions[:] = [pos]
    if venue == "binance":
        account["positions"] = [{"symbol": "TESTUSDT", "positionSide": leg, "positionAmt": quantity,
            "unrealizedProfit": "0.4", "updateTime": at+200}]
        account.update(totalWalletBalance="1000.076", totalUnrealizedProfit="0.4", totalMarginBalance="1000.476")
    else:
        account["uTime"] = str(at+400)
    if after_sources is not None:
        after_sources(native, positions, account, settings, clock, trade, key)
    after = collect_account_snapshot(native, source_markets, mode="testnet")
    end_ms = after["payload"]["finished_ms"]+1
    clock[0] = at+500
    source = collect(NativeSources(venue, rows, [funding(venue, at+300)]), at-1, end_ms)
    observed = observation(trade)
    if store_source:
        db.store_execution_scan(source, account_observation=observed)
        linked = db.get_execution_scan_account(source["payload_sha256"])
    else:
        linked = {"observation": {"account_context": observed["before"], "finished_ms": at+500}, "manifest_sha256": "0"*64}
    wallet_rows = []
    if venue == "binance":
        for index, (time, kind, amount, trade_id) in enumerate(((100, "COMMISSION", "-0.003", "101"),
                (200, "COMMISSION", "-0.001", "102"), (200, "REALIZED_PNL", "0.1", "102"),
                (300, "FUNDING_FEE", "-0.02", "")), 1):
            row = wallet_row(venue, at+time, key=901 if kind == "FUNDING_FEE" else index,
                kind=kind, amount=amount, instrument="TESTUSDT")
            row["tradeId"] = trade_id
            wallet_rows.append(row)
    else:
        for index, (time, amount, pnl, fee, balance) in enumerate(((100, "-0.003", "0", "-0.003", "999.997"),
                (200, "0.099", "0.1", "-0.001", "1000.096"), (300, "-0.02", "-0.02", "0", "1000.076")), 1):
            row = wallet_row(venue, at+time, key=1000+index+100 if index < 3 else 901,
                kind="TRADE" if index < 3 else "FUNDING_FEE", amount=amount, instrument="TEST-USDT-SWAP")
            row.update(pnl=pnl, fee=fee, bal=balance)
            if index < 3:
                row.update(ordId=str(index), tradeId=str(100+index), clOrdId=rows[index-1]["clOrdId"])
            wallet_rows.append(row)
    io = AccountSourceIO(venue, wallet_rows)
    monkeypatch.setattr(native, "fapiPrivateGetIncome" if venue == "binance" else "privateGetAccountBillsArchive", io.wallet)
    wallet = collect_wallet_scan(native, mode="testnet", start_ms=at-1, end_ms=end_ms)
    inputs = {"before": before, "after": after, "wallets": [wallet],
        "executions": [{"receipt": source, "account_context": linked["observation"]["account_context"],
            "manifest_sha256": linked["manifest_sha256"], "observed_ms": linked["observation"]["finished_ms"]}],
        "histories": [history], "projections": [{"trade_table": db.table, "record_id": key, "instrument": CODE,
            "current_qty": db.get_record(key)["current_qty"], "position_side": leg, "is_buy": side}]}
    return inputs, trade, key


def reseal(document):
    document["payload_sha256"] = hashlib.sha256(canonical_bytes(document["payload"])).hexdigest()


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("side,mode", [(True, "one_way"), (False, "one_way"), (True, "hedged"), (False, "hedged")])
def test_observed_interval_closes_wallet_and_pooled_leg_without_fee_double_count(store, tmp_path, monkeypatch, venue, side, mode):
    db, _ = store
    inputs, _, key = interval_case(db, tmp_path, monkeypatch, venue, side=side, mode=mode)
    original = db.get_record(key)
    report = build_account_reconciliation(**inputs)
    payload = report["payload"]
    assert payload["status"] == "matched_observations", payload["issues"]
    assert payload["issues"] == [] and payload["economics_complete"] is False
    assert payload["coverage"] == "observed_account_interval"
    assert payload["wallets"][0]["difference"] == {"numerator": "0", "denominator": "1"}
    leg, = payload["positions"]
    assert leg["quantity"] == {"numerator": "1", "denominator": "50"}
    assert leg["entry_price"] == {"numerator": "100", "denominator": "1"}
    assert leg["unrealized_pnl"] == {"numerator": "2", "denominator": "5"}
    assert payload["disclosures"]["funding_allocation"] == "account_only_native_leg_missing"
    assert payload["disclosures"]["mark_generation_clock"] == "unknown"
    assert payload["disclosures"]["position_margin_currency"] == ("USDT" if venue == "binance" else "USD")
    assert db.get_record(key) == original


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage,reason", [("cash", "wallet_difference"), ("entry", "entry_price_difference"),
    ("mark", "position_unrealized_difference"), ("leg_quantity", "position_quantity_difference"),
    ("missing_execution", "execution_window_missing"), ("missing_wallet", "wallet_window_missing"),
    ("projection", "db_quantity_difference"), ("missing_asset", "asset_endpoint_missing")])
def test_difference_or_missing_evidence_is_explicit_and_never_account_pass(store, tmp_path, monkeypatch, venue, damage, reason):
    inputs, _, _ = interval_case(store[0], tmp_path, monkeypatch, venue)
    if damage in {"cash", "missing_asset"}:
        raw = inputs["after"]["payload"]["raw"]["account"]
        rows = raw["assets" if venue == "binance" else "details"]
        if damage == "cash":
            rows[0]["walletBalance" if venue == "binance" else "cashBal"] = "1000.077"
            inputs["after"]["payload"]["assets"][0]["cash_balance"] = "1000.077"
        else:
            rows[:] = []
            inputs["after"]["payload"]["assets"] = []
        reseal(inputs["after"])
    elif damage in {"entry", "mark", "leg_quantity"}:
        payload = inputs["after"]["payload"]
        native_key, normalized_key, value = {"entry": ("entryPrice" if venue == "binance" else "avgPx", "entry_price", "101"),
            "mark": ("markPrice" if venue == "binance" else "markPx", "mark_price", "121"),
            "leg_quantity": ("positionAmt" if venue == "binance" else "pos", "quantity", "0.01" if venue == "binance" else "1")}[damage]
        payload["raw"]["positions"][0][native_key] = value
        payload["positions"][0][normalized_key] = "0.01" if damage == "leg_quantity" else value
        if damage == "leg_quantity":
            payload["positions"][0]["contracts"] = "1"
        reseal(inputs["after"])
    elif damage == "missing_execution":
        inputs["executions"] = []
    elif damage == "missing_wallet":
        inputs["wallets"] = []
    else:
        inputs["projections"][0]["current_qty"] = 0.01
    report = build_account_reconciliation(**inputs)["payload"]
    assert report["status"] in {"mismatch", "incomplete"}
    assert reason in {row["reason"] for row in report["issues"]}
    assert report["economics_complete"] is False


def test_fraction_math_does_not_inherit_callers_precision_or_subnormal_traps(store, tmp_path, monkeypatch):
    inputs, _, _ = interval_case(store[0], tmp_path, monkeypatch, "okx")
    expected = build_account_reconciliation(**inputs)
    with localcontext() as context:
        context.prec, context.Emax, context.Emin, context.traps[Subnormal] = 2, 1, -1, True
        assert build_account_reconciliation(**inputs) == expected


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage,reason", [("snapshot_event", "event_inside_snapshot_interval"),
    ("window_gap", "wallet_window_missing"), ("fee", "trade_cash_component_difference"),
    ("unowned_cash", "unowned_trade_cashflow"), ("isolated_channel", "position_cash_channel_unallocated"),
    ("late_db", "db_event_at_or_after_endpoint"), ("unrealized_asset", "asset_unrealized_difference")])
def test_cashflow_timing_ownership_and_channels_are_not_guessed(store, tmp_path, monkeypatch, venue, damage, reason):
    inputs, _, _ = interval_case(store[0], tmp_path, monkeypatch, venue)
    document = inputs["wallets"][0]
    rows = [copy.deepcopy(f["raw"]) for f in document["payload"]["facts"]]
    begin, end = document["payload"]["start_ms"], document["payload"]["end_ms"]
    if damage == "snapshot_event":
        rows[0]["time" if venue == "binance" else "ts"] = str(begin+1) if venue == "okx" else begin+1
    elif damage == "window_gap":
        begin += 2
    elif damage == "fee":
        rows[0]["income" if venue == "binance" else "fee"] = "-0.004"
    elif damage == "unowned_cash":
        rows[0]["tradeId"] = "999"
    elif damage == "isolated_channel":
        if venue == "binance":
            pytest.skip("Binance income has no isolated position cash channel")
        rows[0]["posBalChg"] = "0.5"
    elif damage == "late_db":
        inputs["histories"][0]["attempts"][0]["events"][-1]["observed_ms"] = inputs["after"]["payload"]["started_ms"]
    else:
        payload = inputs["after"]["payload"]
        payload["raw"]["account"]["assets" if venue == "binance" else "details"][0]["unrealizedProfit" if venue == "binance" else "upl"] = "0.5"
        payload["assets"][0]["unrealized_pnl"] = "0.5"
        reseal(inputs["after"])
    client, _, _, _ = wallet_client(monkeypatch, venue, rows)
    inputs["wallets"] = [collect_wallet_scan(client, mode="testnet", start_ms=begin, end_ms=end)]
    report = build_account_reconciliation(**inputs)["payload"]
    assert reason in {i["reason"] for i in report["issues"]}
    assert report["status"] != "matched_observations"


def test_internally_consistent_sources_with_inconsistent_native_totals_still_fail(store, tmp_path, monkeypatch):
    inputs, _, _ = interval_case(store[0], tmp_path, monkeypatch, "binance")
    inputs["after"]["payload"]["raw"]["account"]["totalWalletBalance"] = "1000.075"
    inputs["after"]["payload"]["reported_totals"]["wallet_balance"] = "1000.075"
    reseal(inputs["after"])
    result = build_account_reconciliation(**inputs)["payload"]
    assert "native_total_difference" in {i["reason"] for i in result["issues"]}


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_duplicate_overlapping_sources_deduplicate_without_double_booking(store, tmp_path, monkeypatch, venue):
    inputs, _, _ = interval_case(store[0], tmp_path, monkeypatch, venue)
    inputs["wallets"] *= 2
    inputs["executions"] *= 2
    assert build_account_reconciliation(**inputs)["payload"]["status"] == "matched_observations"


def test_native_usdt_notional_is_checked_but_okx_usd_notional_is_not_mislabeled(store, tmp_path, monkeypatch):
    inputs, _, _ = interval_case(store[0], tmp_path, monkeypatch, "binance")
    inputs["after"]["payload"]["raw"]["positions"][0]["notional"] = "999"
    inputs["after"]["payload"]["positions"][0]["reported_notional"] = "999"
    reseal(inputs["after"])
    result = build_account_reconciliation(**inputs)["payload"]
    assert "position_notional_difference" in {i["reason"] for i in result["issues"]}


def test_nonterminal_intent_without_native_fill_does_not_become_a_clean_empty_scan(store, tmp_path, monkeypatch):
    db, _ = store
    inputs, trade, _ = interval_case(db, tmp_path, monkeypatch, "binance")
    quantity, _, contract = trade.prepare_order(CODE, 0.03, 100)
    key = db.add_signal(make_signal(code=CODE, is_buy=False))
    assert db.acquire_open_intent(key, quantity, "unresolved-intent", order_contract=contract)
    history = db.get_order_history(key)
    # Keep this test at the original observation interval, rather than using a
    # later event that would already be rejected by the endpoint clock check.
    for attempt in history["attempts"]:
        for event in attempt["events"]:
            event["observed_ms"] = inputs["before"]["payload"]["finished_ms"]+150
    inputs["histories"].append(history)
    inputs["projections"].append({"trade_table": db.table, "record_id": key, "instrument": CODE,
        "current_qty": 0, "position_side": "BOTH", "is_buy": False})
    result = build_account_reconciliation(**inputs)["payload"]
    assert "unresolved_attempt" in {i["reason"] for i in result["issues"]}


def pooled_case(db, tmp_path, monkeypatch, venue, extra_contracts):
    from Trade.OpenQuotaGen import CBenchPriceQuotaGen
    import Trade.AccountSources as account_source
    import Trade.OrderAudit as audit
    import Trade.db_util as db_module
    inputs, trade, _ = interval_case(db, tmp_path, monkeypatch, venue, store_source=False)
    at = inputs["before"]["payload"]["started_ms"]
    clock = [at+150]
    for module in (account_source, audit, db_module, order_fixture):
        monkeypatch.setattr(module, "utc_now_ms", lambda: clock[0])
    trade.quota_gen = CBenchPriceQuotaGen(6.5)
    trade.exchange.fill, trade.exchange.status = extra_contracts, "canceled"
    key = db.add_signal(make_signal(code=CODE))
    trade.add_trade(db.get_record(key), 101)
    inputs["histories"].append(db.get_order_history(key))
    inputs["projections"].append({"trade_table": db.table, "record_id": key, "instrument": CODE,
        "current_qty": db.get_record(key)["current_qty"], "position_side": "BOTH", "is_buy": True})
    q, entry, upl, pnl, cash = (("0.03", "100.25", "0.5925", "0.0975", "1000.0725") if extra_contracts == 1 else
        ("0.06", "100.57142857", "1.16571429", "0.09428571", "1000.06928571"))
    clock[0] = at+400
    native, positions, account, _, _, _ = snapshot_client(monkeypatch, venue)
    assets = account["assets" if venue == "binance" else "details"]
    assets[:] = [asset(venue, at+400, cash=cash, unrealized=upl)]
    assets[0]["marginBalance" if venue == "binance" else "eq"] = str(Decimal(cash)+Decimal(upl))
    pos = position(venue, at+200, leg="BOTH", quantity=q if venue == "binance" else str(Decimal(q)/Decimal("0.01")))
    pos.update({"entryPrice" if venue == "binance" else "avgPx": entry,
        "markPrice" if venue == "binance" else "markPx": "120", "unRealizedProfit" if venue == "binance" else "upl": upl})
    if venue == "binance":
        pos["notional"] = str(Decimal(q)*120)
        account["positions"] = [{"symbol": "TESTUSDT", "positionSide": "BOTH", "positionAmt": q, "unrealizedProfit": upl, "updateTime": at+200}]
        account.update(totalWalletBalance=cash, totalUnrealizedProfit=upl, totalMarginBalance=assets[0]["marginBalance"])
    else:
        account["uTime"] = str(at+400)
    positions[:] = [pos]
    inputs["after"] = collect_account_snapshot(native, [definition(venue)], mode="testnet")
    rows = [copy.deepcopy(f["raw"]) for f in inputs["executions"][0]["receipt"]["payload"]["facts"] if f["kind"] == "trade"]
    rows[1]["realizedPnl" if venue == "binance" else "fillPnl"] = pnl
    row = fill(venue, at+150, key=103, price="101", fee="0.001", quantity=str(Decimal(extra_contracts)*Decimal("0.01")) if venue == "binance" else str(extra_contracts))
    row["orderId" if venue == "binance" else "ordId"] = "3"
    if venue == "okx":
        row["clOrdId"] = trade.exchange.orders["3"]["clientOrderId"]
    rows.append(row)
    source = collect(NativeSources(venue, rows, [funding(venue, at+300)]), at-1, at+401)
    clock[0] = at+500
    db.store_execution_scan(source, account_observation=observation(trade))
    linked = db.get_execution_scan_account(source["payload_sha256"])
    inputs["executions"] = [{"receipt": source, "account_context": linked["observation"]["account_context"],
        "manifest_sha256": linked["manifest_sha256"], "observed_ms": linked["observation"]["finished_ms"]}]
    wallet_rows = [copy.deepcopy(f["raw"]) for f in inputs["wallets"][0]["payload"]["facts"]]
    if venue == "binance":
        next(r for r in wallet_rows if r["incomeType"] == "REALIZED_PNL")["income"] = pnl
        extra = wallet_row(venue, at+150, key=9, kind="COMMISSION", amount="-0.001", instrument="TESTUSDT")
        extra["tradeId"] = "103"
    else:
        closed = next(r for r in wallet_rows if r["billId"] == "1102")
        closed.update(pnl=pnl, balChg=str(Decimal(pnl)-Decimal("0.001")), bal=str(Decimal(cash)+Decimal("0.02")))
        next(r for r in wallet_rows if r["billId"] == "901")["bal"] = cash
        extra = wallet_row(venue, at+150, key=1103, kind="TRADE", amount="-0.001", instrument="TEST-USDT-SWAP")
        extra.update(pnl="0", fee="-0.001", ordId="3", tradeId="103", clOrdId=row["clOrdId"], bal="999.996")
    wallet_rows.append(extra)
    io = AccountSourceIO(venue, wallet_rows)
    monkeypatch.setattr(native, "fapiPrivateGetIncome" if venue == "binance" else "privateGetAccountBillsArchive", io.wallet)
    inputs["wallets"] = [collect_wallet_scan(native, mode="testnet", start_ms=at-1, end_ms=at+401)]
    return inputs


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_partial_close_uses_native_pooled_basis_not_virtual_record_cost(store, tmp_path, monkeypatch, venue):
    inputs = pooled_case(store[0], tmp_path, monkeypatch, venue, 1)
    payload = build_account_reconciliation(**inputs)["payload"]
    assert payload["status"] == "matched_observations", payload["issues"]
    assert payload["positions"][0]["entry_price"] == {"numerator": "401", "denominator": "4"}
    assert payload["positions"][0]["unrealized_pnl"] == {"numerator": "237", "denominator": "400"}


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_repeating_native_basis_remains_exact_and_rounded_report_is_not_epsilon_pass(store, tmp_path, monkeypatch, venue):
    inputs = pooled_case(store[0], tmp_path, monkeypatch, venue, 4)
    payload = build_account_reconciliation(**inputs)["payload"]
    assert payload["positions"][0]["entry_price"] == {"numerator": "704", "denominator": "7"}
    assert payload["status"] == "mismatch"
    assert {"entry_price_difference", "execution_realized_difference"} <= {i["reason"] for i in payload["issues"]}


@pytest.mark.parametrize("damage,reason", [("trade_delta", "trade_cash_delta_difference"), ("funding_pnl", "funding_cash_source_difference")])
def test_okx_cash_components_must_close_without_hiding_differences_in_final_wallet(store, tmp_path, monkeypatch, damage, reason):
    inputs, _, _ = interval_case(store[0], tmp_path, monkeypatch, "okx")
    rows = [copy.deepcopy(f["raw"]) for f in inputs["wallets"][0]["payload"]["facts"]]
    if damage == "trade_delta":
        rows[0]["balChg"] = "0.007"
        for row in rows:
            row["bal"] = str(Decimal(row["bal"])+Decimal("0.01"))
        payload = inputs["after"]["payload"]
        for key, normalized in (("cashBal", "cash_balance"), ("eq", "equity")):
            value = str(Decimal(payload["raw"]["account"]["details"][0][key])+Decimal("0.01"))
            payload["raw"]["account"]["details"][0][key] = value
            payload["assets"][0][normalized] = value
        reseal(inputs["after"])
    else:
        next(r for r in rows if r["type"] == "8")["pnl"] = "-0.03"
    client, _, _, _ = wallet_client(monkeypatch, "okx", rows)
    old = inputs["wallets"][0]["payload"]
    inputs["wallets"] = [collect_wallet_scan(client, mode="testnet", start_ms=old["start_ms"], end_ms=old["end_ms"])]
    payload = build_account_reconciliation(**inputs)["payload"]
    assert reason in {i["reason"] for i in payload["issues"]}
    assert payload["status"] != "matched_observations"


def test_execution_source_clock_inside_window_does_not_hide_outside_fill_clock(store, tmp_path, monkeypatch):
    inputs, _, _ = interval_case(store[0], tmp_path, monkeypatch, "okx")
    original = inputs["executions"][0]["receipt"]["payload"]
    rows = [copy.deepcopy(f["raw"]) for f in original["facts"] if f["kind"] == "trade"]
    rows[0]["fillTime"] = str(original["start_ms"]-1)
    inputs["executions"][0]["receipt"] = collect(NativeSources("okx", rows, [funding("okx", original["start_ms"]+301)]), original["start_ms"], original["end_ms"])
    report = build_account_reconciliation(**inputs)["payload"]
    assert "execution_clock_outside_interval" in {i["reason"] for i in report["issues"]}


def test_nonmonotonic_journal_clock_is_not_reordered_into_a_false_snapshot(store, tmp_path, monkeypatch):
    inputs, _, _ = interval_case(store[0], tmp_path, monkeypatch, "binance")
    events = inputs["histories"][0]["attempts"][0]["events"]
    events[1]["observed_ms"] += 50
    report = build_account_reconciliation(**inputs)["payload"]
    assert "nonmonotonic_journal_clock" in {i["reason"] for i in report["issues"]}
