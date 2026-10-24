"""Real SDK HTTP/JSON path with fake session transport, never an exchange."""
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import traceback
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import ccxt
import pytest
from requests import Response

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes


NOW = 1_800_000_000_000


def capacity_api():
    assert importlib.util.find_spec("Trade.NativeCapacityEvidence") is not None, "native capacity inputs are missing"
    from Trade import NativeCapacityEvidence as api
    return api


def test_capacity_input_api_exists_without_becoming_a_funding_permission():
    api = capacity_api()
    assert api.SCHEMA == "chan-binance-capacity-evidence-v1"
    assert callable(api.collect_binance_capacity_evidence)
    assert callable(api.verify_binance_capacity_evidence)


@pytest.fixture(params=[(name, "live") for name in ("binance", "binanceusdm")])
def native_capacity(request, monkeypatch):
    api = capacity_api()
    exchange_id, mode = request.param
    client = getattr(ccxt, exchange_id)({"apiKey": "FAKE_KEY_DO_NOT_PUBLISH", "secret": "FAKE_SECRET_DO_NOT_PUBLISH",
                                        "enableRateLimit": False})
    if mode == "testnet":
        client.set_sandbox_mode(True)
    markets = [{"exchange": exchange_id, "id": base+"USDT", "symbol": base+"/USDT:USDT", "type": "swap",
                "base": base, "quote": "USDT", "settle": "USDT", "contractSize": size,
                "precision_mode": ccxt.TICK_SIZE, "precision": {"amount": 1.0, "price": 0.1},
                "limits": {"amount": {"min": 1.0}, "price": {}, "cost": {"min": 5.0}}}
               for base, size in (("TEST", "0.01"), ("ALT", "0.1"))]
    bodies = {("balance", None): '[{"accountAlias":"fake-Futures-A","asset":"USDT","balance":"987"}]',
              ("fee_burn", None): '{"feeBurn":false,"private_unused":"DO_NOT_PUBLISH"}'}
    for market in markets:
        symbol = market["id"]
        bodies["commission", symbol] = json.dumps({"symbol": symbol, "makerCommissionRate": "-0.00002",
            "takerCommissionRate": "0.000401234567890123456789", "rpiCommissionRate": "0.00005",
            "private_unused": "DO_NOT_PUBLISH"})
        bodies["configuration", symbol] = json.dumps([{"symbol": symbol, "marginType": "CROSSED",
            "isAutoAddMargin": False, "leverage": 21, "maxNotionalValue": "500000"}])
        # Native numeric tokens must not first be rounded through Python float.
        bodies["brackets", symbol] = ('{"symbol":"'+symbol+'","notionalCoef":1.2500000000000000001,"brackets":['
            '{"bracket":1,"initialLeverage":75,"notionalFloor":0,"notionalCap":10000,'
            '"maintMarginRatio":0.0065000000000000001,"cum":0},'
            '{"bracket":2,"initialLeverage":50,"notionalFloor":10000,"notionalCap":50000,'
            '"maintMarginRatio":0.01,"cum":35.000000000000000001}],"private_unused":"DO_NOT_PUBLISH"}')
    paths = {"/fapi/v3/balance": "balance", "/fapi/v1/feeBurn": "fee_burn", "/fapi/v1/commissionRate": "commission",
             "/fapi/v1/symbolConfig": "configuration", "/fapi/v1/leverageBracket": "brackets"}
    s = SimpleNamespace(api=api, client=client, mode=mode, markets=markets, bodies=bodies, calls=[], attempts=[],
                        clock={"now": NOW}, hook=None, paths=paths, monkeypatch=monkeypatch)

    def no_io(*args, **kwargs):
        raise AssertionError("capacity fixtures cannot use actual HTTP, loaders, cached or normalized helpers")

    monkeypatch.setattr("requests.sessions.Session.request", no_io)
    for name in ("load_markets", "fetch_markets", "fetch_currencies", "load_leverage_brackets", "fetch_trading_fee",
                 "fetch_leverage_tiers", "create_order", "set_leverage"):
        monkeypatch.setattr(client, name, no_io)
    # Poisoned cache is deliberately irrelevant. The source never repairs it.
    client.options["leverageBrackets"] = {"TEST/USDT:USDT": [[0, "0"]]}

    def transport(method, url, **kwargs):
        s.attempts.append(method)
        parsed, params = urlsplit(url), parse_qs(urlsplit(url).query)
        assert method == "GET" and parsed.path in paths and kwargs["verify"] is True
        role, symbol = paths[parsed.path], params.get("symbol", [None])[0]
        assert set(params) == ({"timestamp", "recvWindow", "signature", "symbol"} if symbol else
                               {"timestamp", "recvWindow", "signature"})
        assert kwargs["headers"]["X-MBX-APIKEY"] == "FAKE_KEY_DO_NOT_PUBLISH"
        s.calls.append((role, symbol))
        s.clock["now"] += 2
        body = s.bodies[role, symbol]
        if s.hook:
            body = s.hook(role, symbol, body)
        response = Response()
        response.status_code, response.reason, response.url = 200, "OK", url
        response.headers["Content-Type"] = "application/json"
        response._content = body.encode()
        return response

    monkeypatch.setattr(client.session, "request", transport)
    monkeypatch.setattr(api, "utc_now_ms", lambda: s.clock["now"])
    monkeypatch.setattr(api, "_monotonic_ns", lambda: 0)
    return s


def collect(s, **kwargs):
    return s.api.collect_binance_capacity_evidence(s.client, s.markets, mode=s.mode,
        max_age_ms=kwargs.get("age", 1000), max_observation_span_ms=kwargs.get("span", 1000))


def verify(s, document, **kwargs):
    return s.api.verify_binance_capacity_evidence(document, max_age_ms=kwargs.get("age", 1000),
                                                 max_observation_span_ms=kwargs.get("span", 1000))


def reseal(document):
    document["payload_sha256"] = hashlib.sha256(canonical_bytes(document["payload"])).hexdigest()


def test_two_symbols_use_only_fixed_native_gets_and_keep_exact_json_numeric_tokens(native_capacity):
    s = native_capacity
    cached = canonical_bytes({"markets": s.client.markets, "options": s.client.options})
    document = collect(s)
    p = document["payload"]
    assert verify(s, copy.deepcopy(document)) == document
    assert document["payload_sha256"] == hashlib.sha256(canonical_bytes(p)).hexdigest()
    assert p["economics_complete"] is p["native_admission_verified"] is False
    assert p["fee_currency"] is None and p["notional_coefficient_applied"] is False
    assert p["coverage"] == "native_fee_configuration_and_raw_brackets"
    assert p["source_ms"] is None and p["clock_kind"] == "local_request_window_only"
    assert p["markets"] == sorted(s.markets, key=lambda m: (m["id"], m["symbol"]))
    roles = [("fee_burn", None)]+[(role, market["id"]) for market in p["markets"]
                                for role in ("commission", "configuration", "brackets")]
    assert [(row["role"], row["instrument_id"]) for row in p["observations"]] == roles
    assert s.calls == [call for role in roles for call in (("balance", None), role, ("balance", None))]
    assert (p["requests"], p["source_requests"], p["identity_requests"]) == (21, 7, 14)
    assert (p["started_ms"], p["finished_ms"]) == (NOW, NOW+42)
    previous = NOW
    for row in p["observations"]:
        assert previous <= row["started_ms"] <= row["request_started_ms"] <= row["request_finished_ms"] <= row["finished_ms"]
        assert row["method"].startswith("fapiPrivateGet")
        assert row["params"] == ({} if row["instrument_id"] is None else {"symbol": row["instrument_id"]})
        previous = row["finished_ms"]
        if row["role"] == "brackets":
            assert row["raw"]["notionalCoef"] == "1.2500000000000000001"
            assert row["raw"]["brackets"][0]["maintMarginRatio"] == "0.0065000000000000001"
            assert row["raw"]["brackets"][1]["cum"] == "35.000000000000000001"
    encoded = canonical_bytes(document).decode()
    assert all(secret not in encoded for secret in ("FAKE_KEY", "FAKE_SECRET", "fake-Futures-A", "DO_NOT_PUBLISH",
                                                    '"signature"', '"headers"', '"balance"'))
    assert canonical_bytes({"markets": s.client.markets, "options": s.client.options}) == cached


@pytest.mark.parametrize("change", ["missing_rpi", "missing_coef", "array_brackets", "fee_burn", "isolated"])
def test_observed_variants_remain_raw_inputs_not_inferred_funding(native_capacity, change):
    s = native_capacity
    if change == "missing_rpi":
        body = json.loads(s.bodies["commission", "ALTUSDT"])
        del body["rpiCommissionRate"]
        s.bodies["commission", "ALTUSDT"] = json.dumps(body)
    elif change == "missing_coef":
        s.bodies["brackets", "ALTUSDT"] = s.bodies["brackets", "ALTUSDT"].replace('"notionalCoef":1.2500000000000000001,', '')
    elif change == "array_brackets":
        s.bodies["brackets", "ALTUSDT"] = '['+s.bodies["brackets", "ALTUSDT"]+']'
    elif change == "fee_burn":
        s.bodies["fee_burn", None] = '{"feeBurn":true}'
    else:
        s.bodies["configuration", "ALTUSDT"] = s.bodies["configuration", "ALTUSDT"].replace('"CROSSED"', '"ISOLATED"')
    document = collect(s)
    assert verify(s, document) == document
    rows = document["payload"]["observations"]
    if change == "missing_rpi":
        assert "rpiCommissionRate" not in rows[1]["raw"]
    elif change == "missing_coef":
        assert "notionalCoef" not in rows[3]["raw"]
    assert document["payload"]["native_admission_verified"] is False


@pytest.mark.parametrize("damage", ["nan", "bool", "float_object", "missing", "wrong_symbol", "duplicate_key"])
@pytest.mark.parametrize("role", ["commission", "configuration", "brackets"])
def test_bad_native_fields_never_fall_back_to_cached_tiers_or_zero_fees(native_capacity, damage, role):
    s = native_capacity
    key = {"commission": "takerCommissionRate", "configuration": "maxNotionalValue", "brackets": "notionalCap"}[role]
    body = s.bodies[role, "ALTUSDT"]
    if damage == "duplicate_key":
        body = body.replace('"symbol":', '"symbol":"ALTUSDT","symbol":', 1)
    elif damage == "wrong_symbol":
        body = body.replace("ALTUSDT", "OTHERUSDT")
    else:
        parsed = json.loads(body)
        row = parsed[0] if role == "configuration" else parsed
        row = row["brackets"][0] if role == "brackets" else row
        if damage == "missing":
            del row[key]
        else:
            row[key] = {"nan": "NaN", "bool": True, "float_object": {"value": "0.4"}}[damage]
        body = json.dumps(parsed)
    s.bodies[role, "ALTUSDT"] = body
    with pytest.raises(CChanException):
        collect(s)
    assert sum(item == (role, "ALTUSDT") for item in s.calls) == 1


@pytest.mark.parametrize("damage", ["empty_config", "extra_config", "empty_brackets", "duplicate_bracket", "missing_burn", "typed_burn"])
def test_incomplete_ambiguous_native_shapes_do_not_publish_partial_inputs(native_capacity, damage):
    s = native_capacity
    if damage.endswith("config"):
        body = json.loads(s.bodies["configuration", "ALTUSDT"])
        s.bodies["configuration", "ALTUSDT"] = json.dumps([] if damage == "empty_config" else body+body)
    elif damage.endswith("brackets") or damage == "duplicate_bracket":
        body = json.loads(s.bodies["brackets", "ALTUSDT"])
        body["brackets"] = [] if damage == "empty_brackets" else body["brackets"]+body["brackets"][:1]
        s.bodies["brackets", "ALTUSDT"] = json.dumps(body)
    else:
        s.bodies["fee_burn", None] = '{}' if damage == "missing_burn" else '{"feeBurn":"false"}'
    with pytest.raises(CChanException):
        collect(s)


@pytest.mark.parametrize("damage", ["route", "tls", "sandbox", "missing_age", "bool_age", "negative_span", "oversized_pool",
                                   "empty_pool", "wrong_venue", "missing_body", "sdk_retry"])
def test_invalid_environment_pool_and_explicit_policy_refuse_before_any_get(native_capacity, damage):
    s, kwargs = native_capacity, {}
    if damage == "route":
        s.client.urls["api"]["fapiPrivate"] = "https://changed.invalid/private"
    elif damage == "tls":
        s.client.verify = False
    elif damage == "sandbox":
        s.client.isSandboxModeEnabled = not (s.mode == "testnet")
    elif damage == "missing_age":
        with pytest.raises(TypeError):
            s.api.collect_binance_capacity_evidence(s.client, s.markets, mode=s.mode, max_observation_span_ms=1000)
        assert s.calls == []
        return
    elif damage == "bool_age":
        kwargs["age"] = True
    elif damage == "negative_span":
        kwargs["span"] = -1
    elif damage == "oversized_pool":
        s.markets[:] = [{**s.markets[0], "id": f"X{i}USDT", "symbol": f"X{i}/USDT:USDT"} for i in range(14)]
    elif damage == "empty_pool":
        s.markets.clear()
    elif damage == "wrong_venue":
        s.client.id = "okx"
    elif damage == "missing_body":
        s.client.enableLastHttpResponse = False
    else:
        s.client.options["maxRetriesOnFailure"] = 1
    with pytest.raises(CChanException):
        collect(s, **kwargs)
    assert s.calls == []


@pytest.mark.parametrize("damage", ["account", "route", "credentials", "arguments", "raw_mismatch", "body_missing", "sdk_error"])
def test_drift_during_native_request_is_redacted_and_not_retried(native_capacity, damage):
    s = native_capacity
    def hook(role, symbol, body):
        if role != "commission":
            return body
        if damage == "account":
            s.bodies["balance", None] = s.bodies["balance", None].replace("fake-Futures-A", "different-account")
        elif damage == "route":
            s.client.urls["api"]["fapiPrivateV3"] = "https://foreign.invalid/private"
        elif damage == "credentials":
            s.client.secret = "MUTATED_SECRET"
        elif damage == "arguments":
            s.markets[0]["contractSize"] = "99"
        elif damage == "raw_mismatch":
            s.monkeypatch.setattr(s.client, "on_rest_response", lambda *args: '{"symbol":"ALTUSDT"}')
        elif damage == "body_missing":
            s.client.enableLastHttpResponse = False
        else:
            raise ccxt.AuthenticationError("SECRET_TOKEN balance=987 raw=PRIVATE_NATIVE_RESPONSE")
        return body
    s.hook = hook
    with pytest.raises(CChanException) as error:
        collect(s)
    assert sum(role == "commission" for role, _ in s.calls) == 1
    assert all(text not in "".join(traceback.format_exception(error.value)) for text in
               ("SECRET_TOKEN", "MUTATED_SECRET", "PRIVATE_NATIVE_RESPONSE", "balance=987"))


@pytest.mark.parametrize("budget", ["age", "span"])
def test_explicit_age_and_span_allow_exact_boundary_and_refuse_one_ms_over(native_capacity, budget):
    s = native_capacity
    document = collect(s, **{budget: 42})
    assert verify(s, document, **{budget: 42}) == document
    with pytest.raises(CChanException):
        verify(s, document, **{budget: 41})
    s.clock["now"] += 1
    if budget == "age":
        with pytest.raises(CChanException):
            verify(s, document, age=42)


@pytest.mark.parametrize("damage", ["money", "request", "market", "identity", "sdk", "implementation", "flag", "derived",
                                   "requests", "clock_bool", "clock_order", "clock_future", "extra"])
def test_reader_rederives_strict_evidence_even_when_caller_reseals_it(native_capacity, damage):
    s = native_capacity
    document = collect(s)
    p = document["payload"]
    if damage == "money":
        p["observations"][1]["raw"]["makerCommissionRate"] = True
    elif damage == "request":
        p["observations"][1]["params"]["symbol"] = "OTHERUSDT"
    elif damage == "market":
        p["markets"][0]["contractSize"] = "0"
    elif damage == "identity":
        p["account_context"]["mode"] = "paper"
    elif damage == "sdk":
        p["sdk"]["version"] = "0.0"
    elif damage == "implementation":
        p["implementation_sha256"]["Trade/NativeCapacityEvidence.py"] = "0"*64
    elif damage == "flag":
        p["native_admission_verified"] = True
    elif damage == "derived":
        p["fee_currency"] = "USDT"
    elif damage == "requests":
        p["requests"] = 7
    elif damage == "clock_bool":
        p["observations"][0]["started_ms"] = True
    elif damage == "clock_order":
        p["observations"][1]["started_ms"] = NOW
    elif damage == "clock_future":
        p["finished_ms"] += 1
    else:
        p["amount_available"] = "987"
    reseal(document)
    before = len(s.calls)
    with pytest.raises(CChanException):
        verify(s, document)
    assert len(s.calls) == before


def test_core_import_does_not_import_sdk_config_or_make_io():
    capacity_api()
    result = subprocess.run([sys.executable, "-c", "import sys; import Trade.NativeCapacityEvidence; "
        "assert not any(k == 'ccxt' or k.startswith('ccxt.') or k == 'Config' or k.startswith('Config.') for k in sys.modules)"],
        text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout+result.stderr


def test_original_sdk_testnet_signing_refusal_is_preserved_without_demo_fallback(native_capacity):
    s = native_capacity
    s.client.set_sandbox_mode(True)
    s.mode = "testnet"
    with pytest.raises(CChanException):
        collect(s)
    assert s.calls == []
    assert s.client.isSandboxModeEnabled is True
    assert s.client.options.get("demoTrading") is not True


def test_effective_sdk_tls_disable_refuses_before_transport_not_only_verify_flag(native_capacity):
    s = native_capacity
    s.client.validateServerSsl = False
    assert s.client.verify is True
    with pytest.raises(CChanException):
        collect(s)
    assert s.attempts == []


@pytest.mark.parametrize("bad_clock", [True, "1800000000000", -1, 2**63])
def test_invalid_initial_source_clock_refuses_before_account_get(native_capacity, bad_clock):
    s = native_capacity
    s.clock["now"] = bad_clock
    with pytest.raises(CChanException):
        collect(s)
    assert s.attempts == []


@pytest.mark.parametrize("damage", ["missing", "mismatch", "duplicate", "nonfinite", "oversized"])
def test_exact_body_reader_does_not_accept_decoded_only_or_unrelated_response(damage):
    api = capacity_api()
    body, wire = '{"symbol":"TESTUSDT","rate":0.1234567890123456789}', {"symbol": "TESTUSDT", "rate": 0.1234567890123456789}
    if damage == "missing":
        body = None
    elif damage == "mismatch":
        wire["symbol"] = "ALTUSDT"
    elif damage == "duplicate":
        body = '{"symbol":"ALTUSDT","symbol":"TESTUSDT","rate":0.1234567890123456789}'
    elif damage == "nonfinite":
        body, wire = '{"rate":NaN}', {"rate": float("nan")}
    else:
        body = ' '*(1_048_576+1)
    with pytest.raises(CChanException):
        api._exact_response(SimpleNamespace(last_http_response=body), wire)


def test_exact_body_parser_preserves_value_not_recoverable_from_decoded_float():
    api = capacity_api()
    body = '{"rate":0.1234567890123456789}'
    decoded = json.loads(body)
    assert str(decoded["rate"]) != "0.1234567890123456789"
    assert api._exact_response(SimpleNamespace(last_http_response=body), decoded) == {"rate": "0.1234567890123456789"}


@pytest.mark.parametrize("path", ["feeBurn", "commissionRate", "symbolConfig", "leverageBracket", "balance"])
def test_endpoint_specific_sdk_retries_refuse_without_changing_options(native_capacity, path):
    s = native_capacity
    s.client.options[path] = {"maxRetriesOnFailure": 1}
    frozen = canonical_bytes(s.client.options)
    with pytest.raises(CChanException):
        collect(s)
    assert s.attempts == [] and canonical_bytes(s.client.options) == frozen


@pytest.mark.parametrize("method", ["fapiPrivateGetFeeBurn", "fapiPrivateGetCommissionRate", "fapiPrivateGetSymbolConfig",
                                   "fapiPrivateGetLeverageBracket", "fapiPrivateV3GetBalance", "parse_json", "fetch", "sign"])
def test_replaced_selected_sdk_path_is_not_a_fresh_source(native_capacity, method):
    s = native_capacity
    s.monkeypatch.setattr(s.client, method, lambda *args, **kwargs: {})
    with pytest.raises(CChanException):
        collect(s)
    assert s.attempts == []


@pytest.mark.parametrize("delta", [0, 1_000_000])
def test_terminal_client_check_cost_is_inside_original_age_budget(native_capacity, delta):
    s = native_capacity
    ticks = iter((0, delta))
    s.monkeypatch.setattr(s.api, "_monotonic_ns", lambda: next(ticks))
    if delta == 0:
        assert collect(s, age=42)["payload"]["finished_ms"] == NOW+42
    else:
        with pytest.raises(CChanException):
            collect(s, age=42)
    assert len(s.calls) == 21


@pytest.mark.parametrize("ticks", [(False, 0), (0, True), (10, 9)])
def test_invalid_or_backward_terminal_monotonic_samples_never_publish(native_capacity, ticks):
    s = native_capacity
    iterator = iter(ticks)
    s.monkeypatch.setattr(s.api, "_monotonic_ns", lambda: next(iterator))
    with pytest.raises(CChanException):
        collect(s)


def test_last_business_clock_cannot_hide_late_client_or_input_drift(native_capacity):
    s = native_capacity
    def clock():
        if len(s.calls) == 21:
            s.client.secret = "LATE_FAKE_SECRET"
        return s.clock["now"]
    s.monkeypatch.setattr(s.api, "utc_now_ms", clock)
    with pytest.raises(CChanException):
        collect(s)
    assert len(s.calls) == 21


def test_terminal_typed_clock_is_checked_before_adding_monotonic_cost(native_capacity):
    s = native_capacity
    tail = {"started": False}
    def monotonic():
        tail["started"] = True
        return 0
    # Zero is a legal synthetic local epoch; bool True must not become int 1
    # through addition and accidentally pass the timestamp range check.
    s.monkeypatch.setattr(s.api, "utc_now_ms", lambda: True if tail["started"] else 0)
    s.monkeypatch.setattr(s.api, "_monotonic_ns", monotonic)
    with pytest.raises(CChanException):
        collect(s)
