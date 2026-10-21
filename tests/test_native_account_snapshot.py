"""Native balance/leg/mark observations without netting or real private I/O."""
import copy
import hashlib
from decimal import Subnormal, localcontext

import ccxt
import pytest

from Common.ChanException import CChanException
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.AccountSources import collect_account_snapshot, verify_account_snapshot
from .test_account_identity import native_client
from .test_execution_facts import definition


def asset(venue, at, *, currency="USDT", cash="1000", unrealized="0.1"):
    if venue == "binance":
        return {"asset": currency, "walletBalance": cash, "unrealizedProfit": unrealized, "marginBalance": "1000.1",
            "initialMargin": "1", "maintMargin": "0.05", "availableBalance": "999.1", "updateTime": at,
            "crossWalletBalance": cash, "crossUnPnl": unrealized}
    return {"ccy": currency, "cashBal": cash, "eq": "1000.1", "upl": unrealized, "availBal": "999", "availEq": "999.1",
        "imr": "1", "mmr": "0.05", "isoEq": "0", "liab": "0", "interest": "0", "uTime": str(at)}


def position(venue, at, *, leg="LONG", quantity=None, margin="cross", instrument=None):
    quantity = ("-0.02" if leg == "SHORT" else "0.03") if quantity is None and venue == "binance" else ("2" if leg == "SHORT" else "3") if quantity is None else quantity
    if venue == "binance":
        return {"symbol": instrument or "TESTUSDT", "positionSide": leg, "positionAmt": quantity,
            "entryPrice": "100", "markPrice": "110", "unRealizedProfit": "-0.2" if leg == "SHORT" else "0.3",
            "notional": "-2.2" if leg == "SHORT" else "3.3", "marginAsset": "USDT", "isolatedWallet": "5" if margin == "isolated" else "0",
            "isolatedMargin": "5", "initialMargin": "1", "maintMargin": "0.05", "liquidationPrice": "0", "updateTime": at,
            "private": "SECRET_POSITION"}
    return {"instId": instrument or "TEST-USDT-SWAP", "instType": "SWAP", "posId": "71" if leg == "SHORT" else "70",
        "posSide": "net" if leg == "BOTH" else leg.lower(), "pos": quantity, "avgPx": "100", "markPx": "110", "upl": "-0.2" if leg == "SHORT" else "0.3",
        "ccy": "USDT", "mgnMode": margin, "margin": "5" if margin == "isolated" else "", "lever": "3", "imr": "1", "mmr": "0.05",
        "notionalUsd": "2.2" if leg == "SHORT" else "3.3", "liqPx": "", "uTime": str(at), "realizedPnl": "0.25", "private": "SECRET_POSITION"}


def snapshot_client(monkeypatch, venue, *, multi=False):
    client, profiles, identity = native_client(monkeypatch, venue)
    at = utc_now_ms()-1000
    positions = [position(venue, at), position(venue, at, leg="SHORT")]
    assets = [asset(venue, at), asset(venue, at, currency="BNB", cash="0.5", unrealized="0")]
    account = ({"assets": assets, "positions": [{"symbol": p["symbol"], "positionSide": p["positionSide"], "positionAmt": p["positionAmt"],
        "unrealizedProfit": p["unRealizedProfit"], "isolatedWallet": p["isolatedWallet"], "isolatedMargin": p["isolatedMargin"],
        "initialMargin": p["initialMargin"], "maintMargin": p["maintMargin"], "notional": p["notional"], "updateTime": at} for p in positions],
        "totalWalletBalance": "1000", "totalUnrealizedProfit": "0.1", "totalMarginBalance": "1000.1", "totalInitialMargin": "1",
        "totalMaintMargin": "0.05", "availableBalance": "999.1", "SECRET_ACCOUNT": "DO_NOT_COPY"}
        if venue == "binance" else {"uTime": str(at), "totalEq": "1000", "isoEq": "0", "imr": "1", "mmr": "0.05", "upl": "0.1", "details": assets, "uid": "DO_NOT_COPY"})
    requests = []
    settings = [{"symbol": "TESTUSDT", "marginType": "CROSSED", "leverage": 3, "isAutoAddMargin": False}]

    def read(kind, data, wrapped=False):
        def get(params):
            requests.append((kind, copy.deepcopy(params)))
            return {"code": "0", "data": copy.deepcopy(data)} if wrapped else copy.deepcopy(data)
        return get

    if venue == "binance":
        monkeypatch.setattr(client, "fapiPrivateV3GetAccount", read("account", account))
        monkeypatch.setattr(client, "fapiPrivateV3GetPositionRisk", read("positions", positions))
        monkeypatch.setattr(client, "fapiPrivateGetSymbolConfig", read("settings", settings))
        monkeypatch.setattr(client, "fapiPrivateGetMultiAssetsMargin", read("multi", {"multiAssetsMargin": multi}))
    else:
        monkeypatch.setattr(client, "privateGetAccountBalance", read("account", [account], True))
        monkeypatch.setattr(client, "privateGetAccountPositions", read("positions", positions, True))
    return client, positions, account, settings, requests, profiles


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_native_snapshot_keeps_both_legs_units_currencies_and_real_mark_clock_unknown(monkeypatch, venue):
    client, _, _, _, requests, profiles = snapshot_client(monkeypatch, venue)
    receipt = collect_account_snapshot(client, [definition(venue)], mode="testnet")
    assert verify_account_snapshot(receipt) == receipt
    payload = receipt["payload"]
    assert payload["coverage"] == "observed_native_account" and payload["economics_complete"] is False
    assert [(p["position_side"], p["quantity"], p["contracts"], p["direction"]) for p in payload["positions"]] == [
        ("LONG", "0.03", "3", "long"), ("SHORT", "0.02", "2", "short")]
    assert [(a["currency"], a["cash_balance"]) for a in payload["assets"]] == [("BNB", "0.5"), ("USDT", "1000")]
    assert all(p["mark_price"] == "110" and p["mark_ms"] is None for p in payload["positions"])
    assert all(p["quantity_unit"] == "base_currency" and p["contracts_unit"] == "contracts" for p in payload["positions"])
    assert payload["reported_totals"]["currency"] == ("USDT" if venue == "binance" else "USD")
    assert all(params == {} for _, params in requests) and len(profiles) == 2
    assert "DO_NOT_COPY" not in canonical_bytes(receipt).decode() and "SECRET_POSITION" not in canonical_bytes(receipt).decode()


def test_binance_multi_asset_usd_total_is_not_relabelled_as_usdt(monkeypatch):
    client, _, _, _, _, _ = snapshot_client(monkeypatch, "binance", multi=True)
    receipt = collect_account_snapshot(client, [definition("binance")], mode="testnet")
    assert receipt["payload"]["reported_totals"]["currency"] == "USD"
    assert receipt["payload"]["raw"]["multi_assets_margin"] is True


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_zero_quantity_isolated_balance_is_preserved_as_a_leg_not_dropped(monkeypatch, venue):
    client, positions, _, settings, _, _ = snapshot_client(monkeypatch, venue)
    positions[:] = [position(venue, positions[0]["updateTime" if venue == "binance" else "uTime"], leg="LONG", quantity="0", margin="isolated")]
    if venue == "binance":
        settings[0]["marginType"] = "ISOLATED"
    receipt = collect_account_snapshot(client, [definition(venue)], mode="testnet")
    leg, = receipt["payload"]["positions"]
    assert leg["quantity"] == "0" and leg["isolated_balance"] == "5" and leg["margin_mode"] == "isolated"


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_unknown_market_positions_remain_explicit_without_unit_guessing(monkeypatch, venue):
    client, positions, _, _, _, _ = snapshot_client(monkeypatch, venue)
    positions.append(position(venue, utc_now_ms()-1000, instrument="OTHER"))
    receipt = collect_account_snapshot(client, [definition(venue)], mode="testnet")
    unknown, = receipt["payload"]["unsupported_positions"]
    assert unknown["instrument_id"] == "OTHER" and unknown["reason"] == "market_metadata_missing"
    assert "quantity" not in unknown and "contracts" not in unknown
    assert len(receipt["payload"]["positions"]) == 2


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["missing_cash", "bad_quantity", "missing_mark", "bad_leg", "duplicate_asset", "duplicate_leg", "bad_clock"])
def test_invalid_snapshot_source_is_not_normalized_with_defaults(monkeypatch, venue, damage):
    client, positions, account, _, _, _ = snapshot_client(monkeypatch, venue)
    assets = account["assets" if venue == "binance" else "details"]
    if damage == "missing_cash":
        del assets[0]["walletBalance" if venue == "binance" else "cashBal"]
    elif damage == "bad_quantity":
        positions[0]["positionAmt" if venue == "binance" else "pos"] = True
    elif damage == "missing_mark":
        del positions[0]["markPrice" if venue == "binance" else "markPx"]
    elif damage == "bad_leg":
        positions[0]["positionSide" if venue == "binance" else "posSide"] = "unknown"
    elif damage == "duplicate_asset":
        assets.append(copy.deepcopy(assets[0]))
    elif damage == "duplicate_leg":
        positions.append(copy.deepcopy(positions[0]))
    else:
        positions[0]["updateTime" if venue == "binance" else "uTime"] = float(utc_now_ms())
    with pytest.raises(CChanException):
        collect_account_snapshot(client, [definition(venue)], mode="testnet")


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_native_snapshot_revalidation_does_not_accept_resealed_summary_drift(monkeypatch, venue):
    client, _, _, _, _, _ = snapshot_client(monkeypatch, venue)
    source = collect_account_snapshot(client, [definition(venue)], mode="testnet")
    for field in ("quantity", "unrealized_pnl", "mark_ms"):
        receipt = copy.deepcopy(source)
        receipt["payload"]["positions"][0][field] = 999 if field == "mark_ms" else "999"
        receipt["payload_sha256"] = hashlib.sha256(canonical_bytes(receipt["payload"])).hexdigest()
        with pytest.raises(CChanException):
            verify_account_snapshot(receipt)


def test_snapshot_decimal_units_are_independent_of_callers_context(monkeypatch):
    client, _, _, _, _, _ = snapshot_client(monkeypatch, "okx")
    with localcontext() as context:
        context.prec, context.Emax, context.Emin, context.traps[Subnormal] = 2, 1, -1, True
        receipt = collect_account_snapshot(client, [definition("okx")], mode="testnet")
    assert receipt["payload"]["positions"][0]["quantity"] == "0.03"


@pytest.mark.parametrize("damage", ["duplicate_account_leg", "nonfinite_account_position", "nonfinite_unsupported", "future_unsupported"])
def test_unusable_independent_or_unsupported_position_data_is_not_silently_trusted(monkeypatch, damage):
    client, positions, account, _, _, _ = snapshot_client(monkeypatch, "binance")
    if damage == "duplicate_account_leg":
        account["positions"].append(copy.deepcopy(account["positions"][0]))
    elif damage == "nonfinite_account_position":
        account["positions"][0]["isolatedWallet"] = "NaN"
    else:
        row = position("binance", utc_now_ms()-1000, instrument="OTHER")
        if damage == "nonfinite_unsupported":
            row["markPrice"] = "NaN"
        else:
            row["updateTime"] = utc_now_ms()+86_400_000
        positions.append(row)
    with pytest.raises(CChanException):
        collect_account_snapshot(client, [definition("binance")], mode="testnet")


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_snapshot_identity_change_and_private_errors_cannot_publish(monkeypatch, venue):
    import traceback
    client, _, account, _, _, _ = snapshot_client(monkeypatch, venue)
    name = "fapiPrivateV3GetAccount" if venue == "binance" else "privateGetAccountBalance"

    def changed(params):
        client.isSandboxModeEnabled = False
        return copy.deepcopy(account) if venue == "binance" else {"code": "0", "data": [copy.deepcopy(account)]}

    monkeypatch.setattr(client, name, changed)
    with pytest.raises(CChanException):
        collect_account_snapshot(client, [definition(venue)], mode="testnet")
    client.isSandboxModeEnabled = True

    def failed(params):
        raise ccxt.AuthenticationError("SECRET_SNAPSHOT_ERROR")

    monkeypatch.setattr(client, name, failed)
    with pytest.raises(CChanException) as caught:
        collect_account_snapshot(client, [definition(venue)], mode="testnet")
    assert "SECRET_SNAPSHOT_ERROR" not in "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
