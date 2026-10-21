"""Real credential-free CCXT routing, fake native private responses; no HTTP."""
import copy
import hashlib
import traceback

import ccxt
import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.AccountIdentity import observe_account_context, verify_account_context


def native_client(monkeypatch, venue, mode="testnet"):
    client = getattr(ccxt, venue)()
    if mode == "testnet":
        client.set_sandbox_mode(True)
    reads = []
    response = ([{"accountAlias": "fake-Futures-A", "asset": "USDT", "balance": "50"},
                 {"accountAlias": "fake-Futures-A", "asset": "USDC", "balance": "0"}]
                if venue != "okx" else {"code": "0", "msg": "", "data": [{"uid": "12345678", "label": "PRIVATE_LABEL"}]})

    def get(params):
        reads.append(copy.deepcopy(params))
        return copy.deepcopy(response)

    def no_http(*args, **kwargs):
        raise AssertionError("account identity tests must never perform HTTP")

    monkeypatch.setattr(client, "request", no_http)
    monkeypatch.setattr(client, "privateGetAccountConfig" if venue == "okx" else "fapiPrivateV3GetBalance", get)
    return client, reads, response


@pytest.mark.parametrize("venue", ["binance", "binanceusdm", "okx"])
@pytest.mark.parametrize("mode", ["testnet", "live"])
def test_native_identity_is_typed_stable_hashed_and_not_a_caller_label(monkeypatch, venue, mode):
    client, reads, _ = native_client(monkeypatch, venue, mode)
    result = observe_account_context(client, mode)
    assert result == observe_account_context(client, mode)
    assert reads == [{}, {}]
    canonical_venue = "binance" if venue != "okx" else "okx"
    kind = "futures_account_alias" if venue != "okx" else "uid"
    value = "fake-Futures-A" if venue != "okx" else "12345678"
    assert result["schema"] == "chan-account-context-v1"
    assert (result["venue"], result["mode"], result["identifier_kind"]) == (canonical_venue, mode, kind)
    assert result["identifier_sha256"] == hashlib.sha256(canonical_bytes({"venue": canonical_venue, "kind": kind, "value": value})).hexdigest()
    encoded = canonical_bytes(result).decode()
    assert all(private not in encoded for private in (value, "PRIVATE_LABEL", '"balance"', '"asset"', '"label"', '"apiKey"'))
    assert result["environment"]["sandbox"] is (mode == "testnet")
    verify_account_context(result)


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["sandbox", "url", "tls", "simulated", "duplicate_header"])
def test_wrong_environment_is_rejected_before_any_private_read(monkeypatch, venue, damage):
    client, reads, _ = native_client(monkeypatch, venue)
    if damage == "sandbox":
        client.isSandboxModeEnabled = False
    elif damage == "url":
        client.urls["api"]["rest" if venue == "okx" else "fapiPrivateV3"] = "https://wrong.example/account"
    elif damage == "tls":
        client.verify = False
    elif damage == "simulated":
        client.headers = {"x-simulated-trading": "0" if venue == "okx" else "1"}
    else:
        client.headers = {"x-simulated-trading": "1", "X-Simulated-Trading": "1"}
    with pytest.raises(CChanException):
        observe_account_context(client, "testnet")
    assert reads == []


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("damage", ["empty", "missing", "conflict", "invalid", "error_code"])
def test_missing_or_ambiguous_native_identity_never_becomes_verified(monkeypatch, venue, damage):
    client, reads, response = native_client(monkeypatch, venue)
    rows = response if venue == "binance" else response["data"]
    key = "accountAlias" if venue == "binance" else "uid"
    if damage == "empty":
        rows.clear()
    elif damage == "missing":
        del rows[0][key]
    elif damage == "conflict":
        rows.append({key: "99999999"})
    elif damage == "invalid":
        rows[0][key] = True
    elif venue == "okx":
        response["code"] = "50001"
    else:
        rows[0][key] = "  "
    with pytest.raises(CChanException):
        observe_account_context(client, "testnet")
    assert len(reads) == 1


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_raw_account_errors_are_redacted_including_exception_chain(monkeypatch, venue):
    client, _, _ = native_client(monkeypatch, venue)

    def fail(params):
        raise ccxt.AuthenticationError("SECRET_TOKEN raw balance and uid=12345678")

    monkeypatch.setattr(client, "privateGetAccountConfig" if venue == "okx" else "fapiPrivateV3GetBalance", fail)
    with pytest.raises(CChanException) as caught:
        observe_account_context(client, "testnet")
    assert "SECRET_TOKEN" not in "".join(traceback.format_exception(caught.type, caught.value, caught.tb))


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_route_changed_during_read_cannot_publish_a_stale_context(monkeypatch, venue):
    client, _, response = native_client(monkeypatch, venue)

    def change(params):
        client.isSandboxModeEnabled = False
        return copy.deepcopy(response)

    monkeypatch.setattr(client, "privateGetAccountConfig" if venue == "okx" else "fapiPrivateV3GetBalance", change)
    with pytest.raises(CChanException):
        observe_account_context(client, "testnet")


@pytest.mark.parametrize("field", ["mode", "identifier_sha256", "context_id", "environment"])
def test_context_reader_rejects_local_drift(monkeypatch, field):
    client, _, _ = native_client(monkeypatch, "okx")
    context = observe_account_context(client, "testnet")
    context[field] = {} if field == "environment" else "changed"
    with pytest.raises(CChanException):
        verify_account_context(context)


@pytest.mark.parametrize("route", ["fapiPrivate", "fapiPrivateV2", "fapiPrivateV3"])
def test_every_binance_private_order_route_is_guarded_not_only_profile_route(monkeypatch, route):
    client, reads, _ = native_client(monkeypatch, "binance")
    client.urls["api"][route] = "https://fapi.binance.com/fapi/v1"
    with pytest.raises(CChanException):
        observe_account_context(client, "testnet")
    assert reads == []


def test_okx_hostname_cannot_redirect_an_unchanged_rest_template(monkeypatch):
    client, reads, _ = native_client(monkeypatch, "okx")
    client.hostname = "wrong.example"
    with pytest.raises(CChanException):
        observe_account_context(client, "testnet")
    assert reads == []


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_live_mode_does_not_trust_a_relabelled_testnet_client(monkeypatch, venue):
    client, reads, _ = native_client(monkeypatch, venue)
    client.isSandboxModeEnabled = False
    with pytest.raises(CChanException):
        observe_account_context(client, "live")
    assert reads == []


def test_resealed_context_still_requires_exact_environment_types(monkeypatch):
    client, _, _ = native_client(monkeypatch, "okx")
    context = observe_account_context(client, "testnet")
    context["environment"]["sandbox"] = 1
    context["context_id"] = hashlib.sha256(canonical_bytes({k: v for k, v in context.items() if k != "context_id"})).hexdigest()
    with pytest.raises(CChanException):
        verify_account_context(context)
