"""Native balance components, no orders, real credentials or network."""
import copy
import hashlib
import importlib.util
import subprocess
import sys
import traceback
from types import SimpleNamespace

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from .test_account_identity import native_client


NOW = 1_800_000_000_000


def balance_api(source=None):
    assert importlib.util.find_spec("Trade.NativeBalanceReservations") is not None, "native balance reservation source is missing"
    from Trade import NativeBalanceReservations as api
    assert callable(getattr(api, "collect_native_balance_reservations", None))
    assert callable(getattr(api, "verify_native_balance_reservations", None))
    if source is not None:
        source.monkeypatch.setattr(api, "utc_now_ms", lambda: source.clock["now"])
    return api


@pytest.fixture(params=[("binance", "testnet"), ("binance", "live"), ("binanceusdm", "testnet"),
                       ("binanceusdm", "live"), ("okx", "testnet"), ("okx", "live")])
def balance_source(request, monkeypatch):
    exchange_id, mode = request.param
    venue = "okx" if exchange_id == "okx" else "binance"
    client, profiles, profile = native_client(monkeypatch, exchange_id, mode)
    clock, calls = {"now": NOW}, []
    if venue == "binance":
        configuration = {"canTrade": True, "dualSidePosition": False, "multiAssetsMargin": False, "updateTime": 0,
                         "feeTier": 0, "private_label": "PRIVATE_DO_NOT_COPY"}
        balance = {"totalWalletBalance": "100", "totalUnrealizedProfit": "0.3", "totalMarginBalance": "100.3",
                   "totalInitialMargin": "7.1", "totalPositionInitialMargin": "5", "totalOpenOrderInitialMargin": "2.1",
                   "totalMaintMargin": "0.05", "totalCrossWalletBalance": "100", "totalCrossUnPnl": "0.3",
                   "availableBalance": "93.2", "maxWithdrawAmount": "93.2", "assets": [], "positions": [],
                   "private_label": "PRIVATE_DO_NOT_COPY"}
        for currency, cash, pending in (("USDT", "100", "2.1"), ("BNB", "0.5", "0.1")):
            balance["assets"].append({"asset": currency, "walletBalance": cash, "unrealizedProfit": "0.3",
                "marginBalance": "100.3", "initialMargin": "7.1", "positionInitialMargin": "5",
                "openOrderInitialMargin": pending, "maintMargin": "0.05", "crossWalletBalance": cash,
                "crossUnPnl": "0.3", "availableBalance": "93.2", "maxWithdrawAmount": "93.2", "updateTime": NOW-1000})
        balance["positions"].append({"symbol": "TESTUSDT", "positionSide": "BOTH", "positionAmt": "0.03",
            "unrealizedProfit": "0.3", "initialMargin": "5", "maintMargin": "0.05", "isolatedMargin": "0",
            "isolatedWallet": "0", "notional": "3.3", "updateTime": NOW-1000})
        profile_get = client.fapiPrivateV3GetBalance
        def get_profile(params):
            calls.append(("profile", copy.deepcopy(params)))
            clock["now"] += 2
            return profile_get(params)
        monkeypatch.setattr(client, "fapiPrivateV3GetBalance", get_profile)
    else:
        configuration = profile["data"][0]
        configuration.update(acctLv="2", posMode="net_mode", autoLoan=False, enableSpotBorrow=False,
                             ctIsoMode="automatic", stgyType="0", roleType="0", spotRoleType="0")
        balance = {"uTime": str(NOW-1000), "totalEq": "100.3", "imr": "", "mmr": "", "isoEq": "0",
                   "upl": "0.3", "ordFroz": "", "details": [], "private_label": "PRIVATE_DO_NOT_COPY"}
        for currency, cash, frozen in (("USDT", "100", "2.1"), ("BNB", "0.5", "0.1")):
            balance["details"].append({"ccy": currency, "cashBal": cash, "eq": "100.3", "upl": "0.3",
                "availBal": "93", "availEq": "93.2", "imr": "5", "mmr": "0.05", "frozenBal": "7.3", "ordFrozen": frozen,
                "isoEq": "0", "isoUpl": "0", "liab": "0", "interest": "0", "stgyEq": "0", "smtSyncEq": "0",
                "spotCopyTradingEq": "0", "fixedBal": "0", "uTime": str(NOW-1000)})
    def get_configuration(params):
        calls.append(("configuration", copy.deepcopy(params)))
        profiles.append(copy.deepcopy(params)) if venue == "okx" else None
        clock["now"] += 2
        return copy.deepcopy(configuration) if venue == "binance" else {"code": "0", "data": [copy.deepcopy(configuration)]}
    def get_balance(params):
        calls.append(("balance", copy.deepcopy(params)))
        clock["now"] += 5
        return copy.deepcopy(balance) if venue == "binance" else {"code": "0", "data": [copy.deepcopy(balance)]}
    monkeypatch.setattr(client, "fapiPrivateGetAccountConfig" if venue == "binance" else "privateGetAccountConfig", get_configuration)
    monkeypatch.setattr(client, "fapiPrivateV3GetAccount" if venue == "binance" else "privateGetAccountBalance", get_balance)
    return SimpleNamespace(client=client, mode=mode, venue=venue, clock=clock, calls=calls, configuration=configuration,
                           balance=balance, profiles=profiles, profile=profile, monkeypatch=monkeypatch)


def test_balance_source_api_is_explicit():
    assert balance_api().SCHEMA == "chan-native-balance-reservations-v1"


def test_nonzero_pending_margin_preserves_all_currency_channels_and_native_units(balance_source):
    s = balance_source
    api = balance_api(s)
    document = api.collect_native_balance_reservations(s.client, mode=s.mode)
    assert api.verify_native_balance_reservations(document) == document
    p = document["payload"]
    assert p["economics_complete"] is p["native_admission_verified"] is False
    assert p["coverage"] == "reported_balance_and_configuration_components"
    assert [row["role"] for row in p["observations"]] == ["configuration_before", "balance", "configuration_after"]
    assert p["requests"] == len(s.calls) == 9 and p["source_requests"] == 3 and p["identity_requests"] == 6
    assert all(params == {} for _, params in s.calls)
    assert (p["started_ms"], p["finished_ms"]) == (NOW, s.clock["now"])
    assets = {row["currency"]: row for row in p["assets"]}
    field = "openOrderInitialMargin" if s.venue == "binance" else "ordFrozen"
    assert assets["USDT"]["native_fields"][field] == "2.1" and assets["BNB"]["native_fields"][field] == "0.1"
    assert p["reported_totals"]["currency"] == ("USDT" if s.venue == "binance" else "USD")
    assert "PRIVATE_DO_NOT_COPY" not in canonical_bytes(document).decode()
    if s.venue == "okx":
        assert p["reported_totals"]["native_fields"]["imr"] is None
        assert "12345678" not in canonical_bytes(document).decode()
    else:
        assert p["reported_totals"]["native_fields"]["totalOpenOrderInitialMargin"] == "2.1"
        assert p["native_account_positions"][0]["quantity_unit"] == "base_currency"


@pytest.mark.parametrize("balance_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("kind", ["missing", "empty", "zero", "negative"])
def test_missing_or_inapplicable_margin_is_not_zero_and_signed_balances_are_not_hidden(balance_source, kind):
    s, api = balance_source, balance_api(balance_source)
    row = s.balance["assets" if s.venue == "binance" else "details"][0]
    field = "openOrderInitialMargin" if s.venue == "binance" else "ordFrozen"
    if kind == "missing":
        del row[field]
    else:
        row[field] = {"empty": "", "zero": "0", "negative": "-0.1"}[kind]
    p = api.collect_native_balance_reservations(s.client, mode=s.mode)["payload"]
    usdt = next(row for row in p["assets"] if row["currency"] == "USDT")
    assert usdt["native_fields"][field] == (None if kind in {"missing", "empty"} else row[field])
    assert p["native_admission_verified"] is False  # No financial plausibility inferred by this source.


@pytest.mark.parametrize("balance_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("damage", ["nan", "bool_money", "float_money", "duplicate_asset", "future_time", "bool_time", "missing_currency", "nested_money"])
def test_malformed_native_money_or_currency_rows_never_publish_partial_evidence(balance_source, damage):
    s, api = balance_source, balance_api(balance_source)
    rows = s.balance["assets" if s.venue == "binance" else "details"]
    row = rows[0]
    amount = "openOrderInitialMargin" if s.venue == "binance" else "ordFrozen"
    clock = "updateTime" if s.venue == "binance" else "uTime"
    if damage in {"nan", "bool_money", "float_money", "nested_money"}:
        row[amount] = {"nan": "NaN", "bool_money": True, "float_money": 1.5, "nested_money": {"secret": "PRIVATE_NATIVE_DATA"}}[damage]
    elif damage == "duplicate_asset":
        rows.append(copy.deepcopy(row))
    elif damage == "missing_currency":
        del row["asset" if s.venue == "binance" else "ccy"]
    else:
        row[clock] = NOW+10000 if damage == "future_time" else True
    with pytest.raises(CChanException):
        api.collect_native_balance_reservations(s.client, mode=s.mode)
    assert sum(kind == "balance" for kind, _ in s.calls) == 1


@pytest.mark.parametrize("balance_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("damage", ["configuration", "account", "route", "tls", "client_id", "clock", "private_error"])
def test_current_identity_and_configuration_bracket_cannot_drift_during_get(balance_source, monkeypatch, damage):
    s, api = balance_source, balance_api(balance_source)
    method = "fapiPrivateV3GetAccount" if s.venue == "binance" else "privateGetAccountBalance"
    get = getattr(s.client, method)
    def interleave(params):
        response = get(params)
        if damage == "configuration":
            s.configuration["dualSidePosition" if s.venue == "binance" else "posMode"] = True if s.venue == "binance" else "long_short_mode"
        elif damage == "account":
            if s.venue == "binance":
                for row in s.profile:
                    row["accountAlias"] = "different-native-account"
            else:
                s.profile["data"][0]["uid"] = "87654321"
        elif damage == "route":
            s.client.urls["api"]["fapiPrivate" if s.venue == "binance" else "rest"] = "https://foreign.invalid/private"
        elif damage == "tls":
            s.client.verify = False
        elif damage == "client_id":
            s.client.id = "foreign"
        elif damage == "clock":
            s.clock["now"] = NOW-100
        else:
            raise RuntimeError("PRIVATE_NATIVE_DATA")
        return response
    monkeypatch.setattr(s.client, method, interleave)
    with pytest.raises(CChanException) as caught:
        api.collect_native_balance_reservations(s.client, mode=s.mode)
    assert "PRIVATE_NATIVE_DATA" not in "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert sum(kind == "balance" for kind, _ in s.calls) == 1


@pytest.mark.parametrize("balance_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("damage", ["amount", "source_count", "endpoint", "window", "flags", "config", "currency_unit", "extra_raw"])
def test_reader_recomputes_native_fields_and_rejects_resealed_derived_changes(balance_source, damage):
    s, api = balance_source, balance_api(balance_source)
    document = api.collect_native_balance_reservations(s.client, mode=s.mode)
    p = document["payload"]
    if damage == "amount":
        p["assets"][0]["native_fields"]["openOrderInitialMargin" if s.venue == "binance" else "ordFrozen"] = "0"
    elif damage == "source_count":
        p["source_requests"] = 1
    elif damage == "endpoint":
        p["observations"][1]["params"] = {"ccy": "USDT"}
    elif damage == "window":
        p["observations"][1]["request_finished_ms"] = p["finished_ms"]+1
    elif damage == "flags":
        p["economics_complete"] = True
    elif damage == "config":
        p["configuration"]["dualSidePosition" if s.venue == "binance" else "posMode"] = True if s.venue == "binance" else "long_short_mode"
    elif damage == "currency_unit":
        p["reported_totals"]["currency"] = "JPY"
    else:
        p["observations"][1]["raw"]["secret"] = "PRIVATE_NATIVE_DATA"
    document["payload_sha256"] = hashlib.sha256(canonical_bytes(p)).hexdigest()
    with pytest.raises(CChanException):
        api.verify_native_balance_reservations(document)


@pytest.mark.parametrize("balance_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
def test_other_account_modes_are_preserved_without_usdt_or_admission_promotion(balance_source):
    s, api = balance_source, balance_api(balance_source)
    if s.venue == "binance":
        s.configuration.update(dualSidePosition=True, multiAssetsMargin=True)
    else:
        s.configuration.update(posMode="long_short_mode", acctLv="4", autoLoan=True)
    p = api.collect_native_balance_reservations(s.client, mode=s.mode)["payload"]
    assert p["configuration"] == {k: v for k, v in s.configuration.items() if k not in {"uid", "label", "feeTier", "private_label"}}
    assert p["reported_totals"]["currency"] == "USD" and p["native_admission_verified"] is False


@pytest.mark.parametrize("balance_source", [("binance", "testnet"), ("okx", "testnet")], indirect=True)
def test_saved_balance_reader_is_core_only_and_does_not_need_an_exchange_client(balance_source):
    s, api = balance_source, balance_api(balance_source)
    document = api.collect_native_balance_reservations(s.client, mode=s.mode)
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
from Trade import NativeBalanceReservations as api
document = json.loads(sys.stdin.buffer.read())
api.utc_now_ms = lambda: document['payload']['finished_ms']
assert api.verify_native_balance_reservations(document) == document
assert not attempted, attempted
assert not any(name.split('.')[0] in blocked for name in sys.modules)
print('Native balance components without optional SDK PASS')
"""
    result = subprocess.run([sys.executable, "-c", code], input=canonical_bytes(document), capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.strip() == b"Native balance components without optional SDK PASS" and result.stderr == b""


@pytest.mark.parametrize("balance_source", [("okx", "testnet")], indirect=True)
def test_explicit_okx_configuration_response_uid_must_match_the_surrounding_typed_account(balance_source, monkeypatch):
    s, api = balance_source, balance_api(balance_source)
    get = s.client.privateGetAccountConfig
    calls = []
    def interleave(params):
        response = get(params)
        calls.append(params)
        if len(calls) == 2:  # First explicit configuration read, between its profile reads.
            response["data"][0]["uid"] = "87654321"
        return response
    monkeypatch.setattr(s.client, "privateGetAccountConfig", interleave)
    with pytest.raises(CChanException):
        api.collect_native_balance_reservations(s.client, mode=s.mode)
