"""Native account-wide sources; real CCXT routing, private GETs are fake."""
import copy
import hashlib
import traceback
from decimal import Decimal, Subnormal, localcontext

import ccxt
import pytest

from Common.ChanException import CChanException
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.AccountSources import collect_wallet_scan, verify_wallet_scan
from .test_account_identity import native_client
from .native_source_io import AccountSourceIO


def wallet_row(venue, at, *, key=101, kind="TRANSFER", amount="25", asset="USDT", instrument=""):
    if venue == "binance":
        return {"symbol": instrument, "incomeType": kind, "income": amount, "asset": asset,
            "time": at, "tranId": key, "tradeId": "", "info": "SECRET_WALLET_NOTES"}
    return {"billId": str(key), "ts": str(at), "type": {"TRANSFER": "1", "FUNDING_FEE": "8", "TRADE": "2"}.get(kind, kind),
        "subType": "12", "ccy": asset, "balChg": amount, "posBalChg": "0", "bal": "1025", "posBal": "0",
        "instId": instrument, "instType": "SWAP" if instrument else "", "mgnMode": "cross" if instrument else "",
        "ordId": "", "clOrdId": "", "tradeId": "", "fee": "0", "pnl": "0", "interest": "0",
        "notes": "SECRET_WALLET_NOTES", "from": "6", "to": "18"}


def wallet_client(monkeypatch, venue, rows):
    client, profiles, native = native_client(monkeypatch, venue)
    io = AccountSourceIO(venue, rows)
    monkeypatch.setattr(client, "fapiPrivateGetIncome" if venue == "binance" else "privateGetAccountBillsArchive", io.wallet)
    return client, io, profiles, native


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_all_account_cashflows_are_requested_without_instrument_type_or_currency_filters(monkeypatch, venue):
    at = utc_now_ms()-10_000
    rows = [wallet_row(venue, at, amount="25"), wallet_row(venue, at+1, key=102, kind="FUNDING_FEE", amount="-0.2", instrument="OTHERUSDT"),
        wallet_row(venue, at+2, key=103, kind="999" if venue == "okx" else "INSURANCE_CLEAR", amount="-0.3", asset="BNB")]
    client, io, profiles, _ = wallet_client(monkeypatch, venue, rows)
    receipt = collect_wallet_scan(client, mode="testnet", start_ms=at, end_ms=at+100)
    assert verify_wallet_scan(receipt) == receipt
    payload = receipt["payload"]
    assert payload["coverage"] == "observed_account_cashflows" and payload["economics_complete"] is False
    assert payload["account_domain"] == ("binance_usdt_m_futures" if venue == "binance" else "okx_trading_account")
    assert [(r["currency"], r["account_cash_delta"]) for r in payload["facts"]] == [("USDT", "25"), ("USDT", "-0.2"), ("BNB", "-0.3")]
    assert len(profiles) == 2
    assert all(not ({"symbol", "incomeType", "instId", "instType", "ccy", "type", "ctType"} & set(p)) for p in io.requests)
    assert "SECRET_WALLET_NOTES" not in canonical_bytes(receipt).decode()


def test_binance_ids_are_unique_by_income_type_not_merely_tran_id(monkeypatch):
    at = utc_now_ms()-5_000
    rows = [wallet_row("binance", at, key=7, kind="COMMISSION", amount="-0.003"),
        wallet_row("binance", at, key=7, kind="REALIZED_PNL", amount="1.2")]
    client, _, _, _ = wallet_client(monkeypatch, "binance", rows)
    facts = collect_wallet_scan(client, mode="testnet", start_ms=at, end_ms=at+100)["payload"]["facts"]
    assert [r["source_id"] for r in facts] == ["COMMISSION:7", "REALIZED_PNL:7"]
    assert [r["native_type"] for r in facts] == ["COMMISSION", "REALIZED_PNL"]


def test_okx_fee_pnl_and_isolated_channels_are_not_added_twice_to_wallet(monkeypatch):
    at = utc_now_ms()-5_000
    row = wallet_row("okx", at, kind="TRADE", amount="0.197")
    row.update(fee="-0.003", pnl="0.2", interest="0", posBalChg="-0.4", posBal="5.6", ordId="19", tradeId="-1")
    client, _, _, _ = wallet_client(monkeypatch, "okx", [row])
    fact, = collect_wallet_scan(client, mode="testnet", start_ms=at, end_ms=at+100)["payload"]["facts"]
    assert fact["account_cash_delta"] == "0.197" and fact["position_cash_delta"] == "-0.4"
    assert fact["balance_after"] == "1025" and fact["position_balance_after"] == "5.6"
    assert fact["fee_cash_delta"] == "-0.003" and fact["reported_pnl"] == "0.2"
    assert fact["order_id"] == "19" and fact["trade_id"] == "-1"


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["nan", "missing_cash", "bool_time", "duplicate_conflict", "bad_currency", "nested_raw"])
def test_bad_cash_source_never_publishes_a_wallet_receipt(monkeypatch, venue, damage):
    at = utc_now_ms()-5_000
    row = wallet_row(venue, at)
    if damage == "nan":
        row["income" if venue == "binance" else "balChg"] = "NaN"
    elif damage == "missing_cash":
        del row["income" if venue == "binance" else "balChg"]
    elif damage == "bool_time":
        row["time" if venue == "binance" else "ts"] = True
    elif damage == "bad_currency":
        row["asset" if venue == "binance" else "ccy"] = "usdt"
    elif damage == "nested_raw":
        row["incomeType" if venue == "binance" else "type"] = {"secret": "raw"}
    rows = [row]
    if damage == "duplicate_conflict":
        rows.append({**row, "income" if venue == "binance" else "balChg": "26"})
    client, io, _, _ = wallet_client(monkeypatch, venue, rows)
    if damage == "bool_time":
        # Return the corrupt wire row, not a fake server that filters it away
        # before the real parser sees it.
        io.override = lambda params: rows if venue == "binance" else {"code": "0", "data": rows}
    with pytest.raises(CChanException):
        collect_wallet_scan(client, mode="testnet", start_ms=at, end_ms=at+100)


def test_binance_saturated_time_window_is_split_without_skipping_a_same_ms_flow(monkeypatch):
    at = utc_now_ms()-5_000
    rows = [wallet_row("binance", at+i//2, key=i+1) for i in range(1001)]
    client, io, _, _ = wallet_client(monkeypatch, "binance", rows)
    receipt = collect_wallet_scan(client, mode="testnet", start_ms=at, end_ms=at+1000)
    assert len(receipt["payload"]["facts"]) == 1001 and len(io.requests) > 1
    assert all("fromId" not in p and "page" not in p for p in io.requests)


def test_binance_saturated_single_millisecond_is_unknown_not_a_partial_pass(monkeypatch):
    at = utc_now_ms()-5_000
    client, _, _, _ = wallet_client(monkeypatch, "binance", [wallet_row("binance", at, key=i+1) for i in range(1000)])
    with pytest.raises(CChanException):
        collect_wallet_scan(client, mode="testnet", start_ms=at, end_ms=at+1)


def test_okx_wallet_cursor_is_exclusive_bill_id_not_trade_id(monkeypatch):
    at = utc_now_ms()-5_000
    rows = [wallet_row("okx", at+i, key=1000+i) for i in range(201)]
    client, io, _, _ = wallet_client(monkeypatch, "okx", rows)
    receipt = collect_wallet_scan(client, mode="testnet", start_ms=at, end_ms=at+1000)
    assert len(receipt["payload"]["facts"]) == 201
    assert [p.get("after") for p in io.requests] == [None, "1101", "1001"]


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_account_or_environment_change_during_wallet_scan_is_not_certified(monkeypatch, venue):
    at = utc_now_ms()-5_000
    client, io, _, _ = wallet_client(monkeypatch, venue, [wallet_row(venue, at)])

    def changed(params):
        client.isSandboxModeEnabled = False
        return [] if venue == "binance" else {"code": "0", "data": []}

    io.override = changed
    with pytest.raises(CChanException):
        collect_wallet_scan(client, mode="testnet", start_ms=at, end_ms=at+100)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_wallet_native_error_is_redacted_even_in_formatted_chain(monkeypatch, venue):
    at = utc_now_ms()-5_000
    client, io, _, _ = wallet_client(monkeypatch, venue, [])

    def failed(params):
        raise ccxt.NetworkError("SECRET_WALLET_ERROR private balance uid=123")

    io.override = failed
    with pytest.raises(CChanException) as caught:
        collect_wallet_scan(client, mode="testnet", start_ms=at, end_ms=at+100)
    assert "SECRET_WALLET_ERROR" not in "".join(traceback.format_exception(caught.type, caught.value, caught.tb))


def test_rehashed_wallet_numeric_or_flag_drift_is_rejected(monkeypatch):
    at = utc_now_ms()-5_000
    client, _, _, _ = wallet_client(monkeypatch, "binance", [wallet_row("binance", at)])
    source = collect_wallet_scan(client, mode="testnet", start_ms=at, end_ms=at+100)
    for damage in ("timestamp", "cash", "complete"):
        receipt = copy.deepcopy(source)
        payload = receipt["payload"]
        if damage == "timestamp":
            payload["facts"][0]["timestamp_ms"] = float(at)
        elif damage == "cash":
            payload["facts"][0]["account_cash_delta"] = "999"
        else:
            payload["economics_complete"] = True
        receipt["payload_sha256"] = hashlib.sha256(canonical_bytes(payload)).hexdigest()
        with pytest.raises(CChanException):
            verify_wallet_scan(receipt)


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_exhausted_request_budget_and_nonprogress_are_never_partial_success(monkeypatch, venue):
    import Trade.AccountSources as sources
    at = utc_now_ms()-5_000
    size = 1000 if venue == "binance" else 100
    client, io, _, _ = wallet_client(monkeypatch, venue, [wallet_row(venue, at+i, key=i+1) for i in range(size)])
    monkeypatch.setattr(sources, "MAX_REQUESTS", 1)
    with pytest.raises(CChanException):
        collect_wallet_scan(client, mode="testnet", start_ms=at, end_ms=at+2000)
    assert len(io.requests) == 1


def test_okx_ignoring_after_cursor_is_detected(monkeypatch):
    at = utc_now_ms()-5_000
    rows = [wallet_row("okx", at+i, key=1000+i) for i in range(100)]
    client, io, _, _ = wallet_client(monkeypatch, "okx", rows)
    io.override = lambda params: {"code": "0", "data": copy.deepcopy(rows)}
    with pytest.raises(CChanException):
        collect_wallet_scan(client, mode="testnet", start_ms=at, end_ms=at+1000)
    assert len(io.requests) == 2


@pytest.mark.parametrize("strict", [True, False])
def test_okx_wallet_includes_both_target_edge_milliseconds_under_either_server_filter_semantics(monkeypatch, strict):
    at = utc_now_ms()-5_000
    end = at+10
    rows = [wallet_row("okx", value, key=101+i) for i, value in enumerate((at-1, at, end-1, end))]
    client, io, _, _ = wallet_client(monkeypatch, "okx", rows)

    def server(params):
        begin, finish = int(params["begin"]), int(params["end"])
        selected = [r for r in rows if (begin < int(r["ts"]) < finish if strict else begin <= int(r["ts"]) <= finish)]
        return {"code": "0", "data": copy.deepcopy(selected)}

    io.override = server
    receipt = collect_wallet_scan(client, mode="testnet", start_ms=at, end_ms=end)
    assert [r["timestamp_ms"] for r in receipt["payload"]["facts"]] == [at, end-1]
    assert int(io.requests[0]["begin"]) == at-1 and int(io.requests[0]["end"]) == end
