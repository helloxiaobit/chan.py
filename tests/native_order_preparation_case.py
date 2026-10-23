"""A single fake account whose history starts with native instrument units.

Nothing rewrites an accepted fixture/receipt. The original Engine writes the
original SQLite journal; source endpoints expose the resulting explicit facts.
"""
import copy
import json
from decimal import Decimal

import ccxt
import pytest

from Common.CEnum import KL_TYPE
from Common.KLineTime import make_crypto_klu
from CustomBuySellPoint.Decision import canonical_bytes
from CustomBuySellPoint.Signal import CSignal
from OfflineData.offline_data_util import CKLineDB
from Trade.AccountSources import collect_account_snapshot
from Trade.OpenQuotaGen import CBenchPriceQuotaGen
from Trade.Script.OpeningInputs import COpeningInputs
from .test_crypto_venue_parameters import venue_engine
from .test_execution_facts import NativeSources, fill, funding
from .test_m6_trade import make_signal
from .test_native_account_snapshot import asset, position, snapshot_client
from .test_native_account_sources import AccountSourceIO, wallet_row
from .test_native_current_components import component_policy
from .test_native_instrument_evidence import NOW, raw_instrument
from .test_native_pending_orders import regular_row


HOUR = 3_600_000
CODES = ["TEST/USDT:USDT", "ALT/USDT:USDT"]


def native_order_case(db, db_conf, tmp_path, monkeypatch, venue, *, mode="one_way", side=True):
    at = NOW//(4*HOUR)*(4*HOUR)
    clock = {"now": at}
    for module in ("Trade.AccountSources", "Trade.AccountStore", "Trade.ExecutionFacts", "Trade.ExecutionStore", "Trade.OrderAudit", "Trade.db_util",
                   "tests.test_crypto_order_contract", "Trade.NativeInstrumentEvidence", "Trade.NativeInstrumentCurrent",
                   "Trade.NativePreparation", "Trade.NativeComponentCollector", "Trade.NativePendingOrders",
                   "Trade.NativeBalanceReservations", "Trade.NativeMarketEvidence", "Trade.NativeAdmission",
                   "Trade.NativeCurrentComponents", "Trade.NativeAccountCheck", "Trade.NativeAccountStore", "Trade.AccountRiskStore", "Trade.NativeOrderBoundary"):
        monkeypatch.setattr(module+".utc_now_ms", lambda: clock["now"])
    client, positions, account, settings, _, _ = snapshot_client(monkeypatch, venue)
    client.options["defaultType"] = "swap"
    raw = [raw_instrument(venue, base) for base in ("TEST", "ALT")]
    client.set_markets([client.parse_market(copy.deepcopy(row)) for row in raw])
    trade = venue_engine(db, tmp_path, venue, mode)
    fake = trade.exchange
    if venue == "binance":
        fake.account_alias = "fake-Futures-A"
    fake.set_markets([copy.deepcopy(client.markets[code]) for code in CODES])
    fake.builder.set_markets([copy.deepcopy(client.markets[code]) for code in CODES])
    units = [trade._market_contract(code)[0] for code in CODES]
    assets = account["assets" if venue == "binance" else "details"]
    assets[:] = [asset(venue, at, cash="1000", unrealized="0")]
    assets[0]["marginBalance" if venue == "binance" else "eq"] = "1000"
    positions[:] = []
    config = ({"canTrade": True, "dualSidePosition": mode == "hedged", "multiAssetsMargin": False, "updateTime": 0}
              if venue == "binance" else {"uid": "12345678", "acctLv": "2", "posMode": "long_short_mode" if mode == "hedged" else "net_mode",
                  "autoLoan": False, "enableSpotBorrow": False, "ctIsoMode": "automatic", "stgyType": "0", "roleType": "0", "spotRoleType": "0"})
    if venue == "binance":
        assets[0].update(initialMargin="0", maintMargin="0", availableBalance="1000", positionInitialMargin="0", openOrderInitialMargin="0")
        account.update(positions=[], totalWalletBalance="1000", totalUnrealizedProfit="0", totalMarginBalance="1000", totalInitialMargin="0",
            totalPositionInitialMargin="0", totalOpenOrderInitialMargin="0", totalMaintMargin="0", totalCrossWalletBalance="1000", totalCrossUnPnl="0", availableBalance="1000")
        monkeypatch.setattr(client, "fapiPrivateGetAccountConfig", lambda p: copy.deepcopy(config))
        monkeypatch.setattr(client, "fapiPrivateGetPositionSideDual", lambda p: {"dualSidePosition": mode == "hedged"})
        monkeypatch.setattr(client, "fapiPrivateGetLeverageBracket", lambda p: [{"symbol": unit["id"], "brackets": [
            {"bracket": 1, "initialLeverage": 3, "notionalCap": "10000", "notionalFloor": "0", "maintMarginRatio": ".005", "cum": "0"}]} for unit in units])
    else:
        assets[0].update(imr="0", mmr="0", availBal="1000", availEq="1000")
        account.update(uTime=str(at), totalEq="1000", imr="0", mmr="0", upl="0")
        monkeypatch.setattr(client, "privateGetAccountConfig", lambda p: {"code": "0", "data": [copy.deepcopy(config)]})
    before = collect_account_snapshot(client, units, mode="testnet")
    before_id = db.store_account_evidence(before)
    history_keys, trades = [], []
    for index, (code, amount, done, price, status) in enumerate(((CODES[0], ".06", ".06", 100, "closed"),
            (CODES[0], ".06", ".02", 110 if side else 90, "canceled"), (CODES[1], ".6", ".3", 100, "open")), 1):
        clock["now"] = at+index*100
        size = Decimal(str(fake.market(code)["contractSize"]))
        fake.fill, fake.status = float(Decimal(done)/size), status
        if index != 2:
            trade.quota_gen = CBenchPriceQuotaGen(float(Decimal(amount)*price))
            key = db.add_signal(make_signal(code=code, is_buy=side))
            history_keys.append(key)
            trade.add_trade(db.get_record(key), price)
        else:
            key = history_keys[0]
            trade.cover_trade(db.get_record(key), price, "native-unit partial close")
        record = db.get_record(key)
        order = list(fake.orders.values())[-1]
        row = fill(venue, clock["now"], key=100+index,
                   quantity=done if venue == "binance" else str(Decimal(done)/size), price=str(price),
                   fee=(".006", ".002", ".003")[index-1], side=order["side"], leg=record["position_side"])
        row["symbol" if venue == "binance" else "instId"] = units[0 if index < 3 else 1]["id"]
        row["orderId" if venue == "binance" else "ordId"] = order["id"]
        row["realizedPnl" if venue == "binance" else "fillPnl"] = ".2" if index == 2 else "0"
        if venue == "okx":
            row["clOrdId"] = record["open_client_order_id"] if index != 2 else record["cover_client_order_id"]
        trades.append(row)
    clock["now"] = at+500
    for index, (code, quantity, mark, pnl) in enumerate(((CODES[0], ".04", "120" if side else "80", ".8"), (CODES[1], ".3", "100", "0"))):
        unit, record = units[index], db.get_record(history_keys[index])
        size = Decimal(unit["contractSize"])
        native_qty = Decimal(quantity)/(1 if venue == "binance" else size)
        if not side and (venue == "binance" or mode == "one_way"):
            native_qty = -native_qty
        row = position(venue, at+300, leg=record["position_side"], quantity=str(native_qty), instrument=unit["id"])
        if venue == "binance":
            row.update(markPrice=mark, unRealizedProfit=pnl, notional=str(Decimal(quantity)*Decimal(mark)*(1 if side else -1)))
            account["positions"].append({"symbol": unit["id"], "positionSide": record["position_side"], "positionAmt": str(native_qty),
                "unrealizedProfit": pnl, "initialMargin": "1", "maintMargin": ".05", "notional": row["notional"], "updateTime": at+300})
        else:
            row.update(markPx=mark, upl=pnl, posId=str(70+index))
        positions.append(row)
    if venue == "binance":
        settings[:] = [{"symbol": unit["id"], "marginType": "CROSSED", "leverage": 3, "isAutoAddMargin": False} for unit in units]
        assets[0].update(walletBalance="1000.169", unrealizedProfit=".8", marginBalance="1000.969", crossWalletBalance="1000.169",
            crossUnPnl=".8", positionInitialMargin="2", openOrderInitialMargin="10", initialMargin="12", maintMargin=".1", availableBalance="988.969")
        account.update(totalWalletBalance="1000.169", totalUnrealizedProfit=".8", totalMarginBalance="1000.969", totalInitialMargin="12",
            totalPositionInitialMargin="2", totalOpenOrderInitialMargin="10", totalMaintMargin=".1", totalCrossWalletBalance="1000.169", totalCrossUnPnl=".8", availableBalance="988.969")
    else:
        account.update(uTime=str(clock["now"]), totalEq="1000.969", imr="12", mmr=".1", upl=".8")
        assets[0].update(cashBal="1000.169", upl=".8", eq="1000.969", availBal="988.169", availEq="988.969", imr="12", mmr=".1",
            frozenBal="10", ordFrozen="10", isoUpl="0", isoLiab="0", crossLiab="0", uplLiab="0", stgyEq="0", smtSyncEq="0",
            spotCopyTradingEq="0", fixedBal="0", spotIsoBal="0")
    pending_record = db.get_record(history_keys[1])
    pending_contract = json.loads(pending_record["open_order_contract"])
    pending = regular_row(venue, units[1]["id"], int(pending_record["open_order_id"]), partial=True)
    if venue == "binance":
        pending.update(origQty=pending_contract["quantity"], executedQty=".3", clientOrderId=pending_record["open_client_order_id"],
            side="BUY" if side else "SELL", positionSide=pending_record["position_side"], price="100", reduceOnly=False,
            time=at+300, updateTime=at+300)
        monkeypatch.setattr(client, "fapiPrivateGetOpenOrders", lambda p: [copy.deepcopy(pending)])
        monkeypatch.setattr(client, "fapiPrivateGetOpenAlgoOrders", lambda p: [])
    else:
        pending.update(sz=pending_contract["exchange_amount"], accFillSz="3", clOrdId=pending_record["open_client_order_id"],
            side="buy" if side else "sell", posSide="net" if mode == "one_way" else pending_record["position_side"].lower(),
            px="100", reduceOnly="false", cTime=str(at+300), uTime=str(at+300))
        monkeypatch.setattr(client, "privateGetTradeOrdersPending", lambda p: {"code": "0", "data": [copy.deepcopy(pending)]})
        monkeypatch.setattr(client, "privateGetTradeOrdersAlgoPending", lambda p: {"code": "0", "data": []})
    execution = {unit["id"]: NativeSources(venue, [row for row in trades if row["symbol" if venue == "binance" else "instId"] == unit["id"]],
                    [funding(venue, at+400)] if index == 0 else []) for index, unit in enumerate(units)}
    wallet_rows = []
    for index, (offset, amount, pnl, fee) in enumerate(((100, "-.006", "0", "-.006"), (200, ".198", ".2", "-.002"),
                                                     (300, "-.003", "0", "-.003"), (400, "-.02", "-.02", "0")), 1):
        instrument = units[1 if index == 3 else 0]["id"]
        if venue == "binance":
            kinds = [("FUNDING_FEE", amount)] if index == 4 else [("COMMISSION", fee)]+([("REALIZED_PNL", pnl)] if index == 2 else [])
            for n, (kind, cash) in enumerate(kinds):
                row = wallet_row(venue, at+offset, key=901 if index == 4 else index*10+n, kind=kind, amount=cash, instrument=instrument)
                row["tradeId"] = "" if index == 4 else str(100+index)
                wallet_rows.append(row)
        else:
            row = wallet_row(venue, at+offset, key=901 if index == 4 else 1100+index,
                            kind="FUNDING_FEE" if index == 4 else "TRADE", amount=amount, instrument=instrument)
            row.update(pnl=pnl, fee=fee, bal=("999.994", "1000.192", "1000.189", "1000.169")[index-1])
            if index < 4:
                row.update(ordId=trades[index-1]["ordId"], clOrdId=trades[index-1]["clOrdId"], tradeId=str(100+index))
            wallet_rows.append(row)
    wallet = AccountSourceIO(venue, wallet_rows)
    if venue == "binance":
        monkeypatch.setattr(client, "fapiPrivateGetUserTrades", lambda p: execution[p["symbol"]].request("trades", p))
        monkeypatch.setattr(client, "fapiPrivateGetIncome", lambda p: execution[p["symbol"]].request("funding", p) if p.get("incomeType") == "FUNDING_FEE" else wallet.wallet(p))
    else:
        for name in ("privateGetTradeFills", "privateGetTradeFillsHistory"):
            monkeypatch.setattr(client, name, lambda p: execution[p["instId"]].request("trades", p))
        monkeypatch.setattr(client, "privateGetAccountBillsArchive", lambda p: execution[p["instId"]].request("funding", p) if p.get("type") == "8" else wallet.wallet(p))
        monkeypatch.setattr(client, "privateGetAccountLeverageInfo", lambda p: {"code": "0", "data": [
            {"instId": p["instId"], "mgnMode": "cross", "lever": "3", "posSide": s} for s in (["long", "short"] if mode == "hedged" else ["net"])]})
    prices = {unit["id"]: positions[index]["markPrice" if venue == "binance" else "markPx"] for index, unit in enumerate(units)}
    def mark(p):
        code = p["symbol" if venue == "binance" else "instId"]
        return ({"symbol": code, "markPrice": prices[code], "time": clock["now"]} if venue == "binance" else
                {"code": "0", "data": [{"instId": code, "instType": "SWAP", "markPx": prices[code], "ts": str(clock["now"])}]})
    def book(p):
        code = p["symbol" if venue == "binance" else "instId"]
        price = Decimal(prices[code])
        return ({"symbol": code, "bidPrice": str(price-1), "askPrice": str(price+1), "bidQty": "1", "askQty": "1", "time": clock["now"]}
                if venue == "binance" else {"code": "0", "data": [{"bids": [[str(price-1), "10", "0", "1"]],
                    "asks": [[str(price+1), "10", "0", "1"]], "ts": str(clock["now"]), "seqId": 1}]})
    monkeypatch.setattr(client, "fapiPublicGetPremiumIndex" if venue == "binance" else "publicGetPublicMarkPrice", mark)
    monkeypatch.setattr(client, "fapiPublicGetTickerBookTicker" if venue == "binance" else "publicGetMarketBooks", book)
    monkeypatch.setattr(client, "fapiPublicGetExchangeInfo" if venue == "binance" else "publicGetPublicInstruments",
                        lambda p: {"symbols": copy.deepcopy(raw)} if venue == "binance" else {"code": "0", "data": copy.deepcopy(raw)})
    trace = []
    for name in ("fapiPrivateV3GetBalance", "fapiPrivateGetAccountConfig", "fapiPrivateV3GetAccount", "fapiPrivateV3GetPositionRisk",
                 "fapiPrivateGetSymbolConfig", "fapiPrivateGetLeverageBracket", "fapiPrivateGetMultiAssetsMargin", "fapiPrivateGetPositionSideDual", "fapiPrivateGetOpenOrders",
                 "fapiPrivateGetOpenAlgoOrders", "fapiPrivateGetUserTrades", "fapiPrivateGetIncome", "fapiPublicGetExchangeInfo",
                 "fapiPublicGetPremiumIndex", "fapiPublicGetTickerBookTicker") if venue == "binance" else (
                 "privateGetAccountConfig", "privateGetAccountBalance", "privateGetAccountPositions", "privateGetAccountLeverageInfo",
                 "privateGetTradeOrdersPending", "privateGetTradeOrdersAlgoPending", "privateGetTradeFills", "privateGetTradeFillsHistory",
                 "privateGetAccountBillsArchive", "publicGetPublicInstruments", "publicGetPublicMarkPrice", "publicGetMarketBooks"):
        get = getattr(client, name)
        def observed(params, get=get, name=name):
            assert not db.db.conn.in_transaction, "native I/O under writer lock"
            trace.append((name, copy.deepcopy(params)))
            clock["now"] += 1
            return get(params)
        monkeypatch.setattr(client, name, observed)
    monkeypatch.setattr(ccxt.Exchange, "fetch", lambda *a, **k: pytest.fail("actual HTTP forbidden"))
    monkeypatch.setattr(client, "create_order", lambda *a, **k: pytest.fail("preparation must never send"))
    trade.exchange = client
    market_path = tmp_path/"native-order-bars.db"
    source = dict(exchange=venue, market_type="swap", settle="USDT", price_type="contract")
    with CKLineDB(str(market_path)) as market:
        market.bind_source(source)
        for code in CODES:
            for level, interval in ((KL_TYPE.K_4H, 4*HOUR), (KL_TYPE.K_60M, HOUR)):
                market.upsert_klines(code, level, [(t, 100, 101, 99, 100, 1) for t in range(at-24*HOUR, at, interval)])
    config_path = tmp_path/"native-order-config.json"
    config_path.write_bytes(canonical_bytes({"db": db_conf, "offline_data": {"sqlite_path": str(market_path), "source_identity": source},
        "ccxt": copy.deepcopy(trade.ccxt_conf), "trade": {"code_list": CODES, "lv_list": ["K_4H", "K_60M"], "strategy": "multi_lv",
            "strategy_receipt": trade.safety_policy.strategy_receipt["path"]}, "notify": {"backend": "none"}}))
    trade.opening_inputs = COpeningInputs(config_path, now_ms=lambda: clock["now"])
    unit = make_crypto_klu([at-HOUR, 100, 101, 99, 100, 1], KL_TYPE.K_60M, clock["now"])
    unit.source_identity = source
    signal = CSignal(CODES[0], KL_TYPE.K_60M, side, "1", unit, 100, sl_thred=90, target_klu_time=unit.time)
    signal.freeze_decision()
    key = db.add_signal(signal)
    return {"db": db, "trade": trade, "client": client, "before_id": before_id, "before": before, "units": units,
            "raw": raw, "clock": clock, "trace": trace, "key": key, "history_keys": history_keys, "created": copy.deepcopy(fake.created),
            "policy": component_policy(), "config": config_path, "market_path": market_path,
            "pending_raw": pending, "account_raw": account, "wallet_io": wallet, "execution_io": execution}
