"""Original Last V2 SDK path, isolated at the bottom HTTP transport only."""
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
from .test_native_order_cost import cost_case, fraction, reference_cost


NOW = 1_800_000_000_000


def last_api():
    assert importlib.util.find_spec("Trade.NativeLastPrice") is not None, "owned fresh Last V2 source is missing"
    from Trade import NativeLastPrice
    return NativeLastPrice


def test_fresh_last_v2_api_is_explicit_and_not_a_money_or_order_permission():
    api = last_api()
    assert api.SCHEMA == "chan-binance-last-price-evidence-v1"
    assert callable(api.collect_binance_last_prices)
    assert callable(api.verify_binance_last_prices)


@pytest.fixture(params=[(exchange, mode) for exchange in ("binance", "binanceusdm") for mode in ("live", "testnet")])
def native_last(request, monkeypatch):
    api = last_api()
    exchange_id, mode = request.param
    def no_io(*args, **kwargs):
        raise AssertionError("Last tests must never use actual HTTP, ticker/cache, private sources or orders")
    monkeypatch.setattr("requests.sessions.Session.request", no_io)
    client = getattr(ccxt, exchange_id)({"apiKey": "FAKE_LAST_KEY", "secret": "FAKE_LAST_SECRET", "enableRateLimit": False})
    if mode == "testnet":
        client.set_sandbox_mode(True)
    markets = [{"exchange": exchange_id, "id": base+"USDT", "symbol": base+"/USDT:USDT", "type": "swap",
        "base": base, "quote": "USDT", "settle": "USDT", "contractSize": "0.01", "precision_mode": 4,
        "precision": {"amount": 1, "price": "0.1"}, "limits": {"amount": {"min": 1}, "price": {}, "cost": {"min": 5}}}
        for base in ("TEST", "ALT")]
    for name in ("load_markets", "fetch_markets", "fetch_ticker", "fetch_tickers", "create_order", "fapiPrivateV3GetBalance"):
        monkeypatch.setattr(client, name, no_io)
    bodies = {market["id"]: '{"symbol":"'+market["id"]+'","price":102.12345678901234567890123456789,"time":'+str(NOW)+',"private_unused":"DO_NOT_PUBLISH"}'
              for market in markets}
    state = SimpleNamespace(api=api, client=client, markets=markets, mode=mode, bodies=bodies, clock={"now": NOW},
                            calls=[], hook=None, monkeypatch=monkeypatch)
    def transport(method, url, **kwargs):
        parsed, params = urlsplit(url), parse_qs(urlsplit(url).query)
        state.calls.append((method, parsed.hostname, parsed.path, params))
        assert method == "GET" and parsed.path == "/fapi/v2/ticker/price" and set(params) == {"symbol"}
        assert kwargs["verify"] is True and parsed.hostname == ("fapi.binance.com" if mode == "live" else "testnet.binancefuture.com")
        state.clock["now"] += 2
        symbol = params["symbol"][0]
        body = state.bodies[symbol]
        if state.hook:
            body = state.hook(symbol, body)
        response = Response()
        response.status_code, response.reason, response.url = 200, "OK", url
        response.headers["Content-Type"] = "application/json"
        response._content = body.encode()
        return response
    monkeypatch.setattr(client.session, "request", transport)
    monkeypatch.setattr(api, "utc_now_ms", lambda: state.clock["now"])
    monkeypatch.setattr(api, "_monotonic_ns", lambda: 0)
    return state


def collect(s, *, age=1000, span=1000):
    return s.api.collect_binance_last_prices(s.client, s.markets, mode=s.mode, max_age_ms=age, max_observation_span_ms=span)


def verify(s, document, *, age=1000, span=1000):
    return s.api.verify_binance_last_prices(document, max_age_ms=age, max_observation_span_ms=span)


def reseal(document):
    document["payload_sha256"] = hashlib.sha256(canonical_bytes(document["payload"])).hexdigest()


def test_actual_sdk_fixed_single_symbol_v2_preserves_tokens_and_transaction_clocks(native_last):
    s = native_last
    before = canonical_bytes({"markets": s.client.markets, "options": s.client.options, "inputs": s.markets})
    document = collect(s)
    p = document["payload"]
    assert verify(s, copy.deepcopy(document)) == document
    assert p["requests"] == len(p["observations"]) == len(p["markets"]) == 2
    assert [row["instrument_id"] for row in p["observations"]] == ["ALTUSDT", "TESTUSDT"]
    assert p["coverage"] == "observed_native_last_transaction_prices"
    assert p["economics_complete"] is p["native_admission_verified"] is False
    assert set(p["environment"]["public_routes"]) == {"fapiPublic", "fapiPublicV2"}
    assert (p["started_ms"], p["finished_ms"]) == (NOW, NOW+4)
    for index, row in enumerate(p["observations"]):
        assert row["endpoint"] == "/fapi/v2/ticker/price" and row["method"] == "fapiPublicV2GetTickerPrice"
        assert row["params"] == {"symbol": row["instrument_id"]}
        assert row["price"] == row["raw"]["price"] == "102.12345678901234567890123456789"
        assert row["source_ms"] == row["raw"]["time"] == NOW and row["clock_kind"] == "transaction_time"
        assert (row["started_ms"], row["finished_ms"]) == (NOW+2*index, NOW+2*index+2)
    assert len(s.calls) == 2
    assert document["payload_sha256"] == hashlib.sha256(canonical_bytes(p)).hexdigest()
    encoded = canonical_bytes(document).decode()
    assert all(value not in encoded for value in ("FAKE_LAST_KEY", "FAKE_LAST_SECRET", "private_unused", "DO_NOT_PUBLISH", '"signature"'))
    assert canonical_bytes({"markets": s.client.markets, "options": s.client.options, "inputs": s.markets}) == before


def test_owned_last_price_feeds_exact_v1_math_without_ticker_cache_or_authority(native_last, cost_case):
    s = native_last
    document = collect(s)
    row = next(row for row in document["payload"]["observations"] if row["instrument_id"] == "TESTUSDT")
    case = cost_case
    case.update(market=next(m for m in s.markets if m["id"] == "TESTUSDT"), last_price=row["price"])
    case["candidate"].update(order_type="MARKET", limit_price=None)
    from Trade.NativeOrderCost import calculate_binance_order_cost_v1
    p = calculate_binance_order_cost_v1(**case)["payload"]
    assert fraction(p["total_cost"]) == reference_cost(case)[-1]
    assert p["provided_inputs_sha256"] == hashlib.sha256(canonical_bytes(case)).hexdigest()
    assert p["input_provenance_verified"] is p["native_admission_verified"] is False
    assert len(s.calls) == 2  # Pure math cannot refresh clocks or acquire a source/claim.


@pytest.mark.parametrize("damage", ["v2_route", "v1_route", "tls", "verify", "response_retention", "response_headers",
    "method", "request", "fetch2", "fetch", "sign", "parse_json", "rest_response", "last_request", "json_callback",
    "retry_global", "retry_endpoint", "retry_bool"])
def test_overrides_or_unchecked_transport_policy_are_rejected_before_any_get(native_last, damage):
    s, c = native_last, native_last.client
    if damage in {"v2_route", "v1_route"}:
        c.urls["api"]["fapiPublicV2" if damage == "v2_route" else "fapiPublic"] = "https://invalid.example/fapi/v2"
    elif damage == "tls": c.validateServerSsl = False
    elif damage == "verify": c.verify = False
    elif damage == "response_retention": c.enableLastHttpResponse = False
    elif damage == "response_headers": c.returnResponseHeaders = True
    elif damage == "json_callback": c.on_json_response = lambda value: value
    elif damage.startswith("retry"):
        c.options["ticker/price"] = {"maxRetriesOnFailure": True if damage == "retry_bool" else 1} if damage != "retry_global" else {}
        if damage == "retry_global": c.options["maxRetriesOnFailure"] = 1
    else:
        name = {"method": "fapiPublicV2GetTickerPrice", "rest_response": "on_rest_response", "last_request": "set_last_request"}.get(damage, damage)
        setattr(c, name, lambda *args, **kwargs: None)
    with pytest.raises(CChanException, match="Last V2"):
        collect(s)
    assert s.calls == []


@pytest.mark.parametrize("damage", ["symbol", "array", "missing_price", "zero", "negative", "nonfinite", "duplicate_key",
    "oversize", "missing_time", "bool_time", "string_time", "future_time", "old_time", "decoded_mix"])
def test_raw_body_or_native_clock_gaps_never_become_last(native_last, damage):
    s = native_last
    body = json.loads(s.bodies["ALTUSDT"])
    if damage == "symbol": body["symbol"] = "TESTUSDT"
    elif damage == "missing_price": del body["price"]
    elif damage in {"zero", "negative", "nonfinite"}: body["price"] = {"zero": "0", "negative": "-1", "nonfinite": "NaN"}[damage]
    elif damage == "missing_time": del body["time"]
    elif damage == "bool_time": body["time"] = True
    elif damage == "string_time": body["time"] = str(NOW)
    elif damage == "future_time": body["time"] = NOW+3
    elif damage == "old_time": body["time"] = NOW-1001
    wire = json.dumps([body] if damage == "array" else body)
    if damage == "duplicate_key": wire = '{"symbol":"ALTUSDT","price":"1","price":"2","time":'+str(NOW)+'}'
    elif damage == "oversize": wire = json.dumps({**body, "private_unused": "x"*1_048_576})
    elif damage == "decoded_mix":
        original = s.api._exact_response
        def mix(client, decoded):
            client.last_http_response = json.dumps({**body, "price": "1"})
            return original(client, decoded)
        s.monkeypatch.setattr(s.api, "_exact_response", mix)
    s.bodies["ALTUSDT"] = wire
    with pytest.raises(CChanException, match="Last V2") as error:
        collect(s)
    assert len(s.calls) == 1
    rendered = ''.join(traceback.format_exception(error.type, error.value, error.tb))
    assert all(value not in rendered for value in ("FAKE_LAST_KEY", "FAKE_LAST_SECRET", "DO_NOT_PUBLISH"))


@pytest.mark.parametrize("damage", ["source", "price", "endpoint", "method", "params", "missing_symbol", "extra_symbol", "order",
    "requests_bool", "requests_count", "sdk", "implementation", "route", "clock_kind", "native_admission", "economics"])
def test_consistent_resealing_cannot_bypass_current_reader_contract(native_last, damage):
    s = native_last
    document = collect(s)
    p, row = document["payload"], document["payload"]["observations"][0]
    if damage == "source": row["source_ms"] += 1
    elif damage == "price": row["price"] = "1"
    elif damage == "endpoint": row["endpoint"] = "/fapi/v1/ticker/price"
    elif damage == "method": row["method"] = "fapiPublicGetTickerPrice"
    elif damage == "params": row["params"] = {}
    elif damage == "missing_symbol": p["observations"].pop()
    elif damage == "extra_symbol": p["observations"].append(copy.deepcopy(row))
    elif damage == "order": p["observations"].reverse()
    elif damage == "requests_bool": p["requests"] = True
    elif damage == "requests_count": p["requests"] = 1
    elif damage == "sdk": p["sdk"]["version"] = "other"
    elif damage == "implementation": p["implementation_sha256"]["Trade/NativeLastPrice.py"] = "0"*64
    elif damage == "route": p["environment"]["public_routes"]["fapiPublicV2"] = "https://invalid.example"
    elif damage == "clock_kind": row["clock_kind"] = "local_request_window_only"
    elif damage == "native_admission": p["native_admission_verified"] = True
    else: p["economics_complete"] = True
    reseal(document)
    s.calls.clear()
    with pytest.raises(CChanException, match="Last V2"):
        verify(s, document)
    assert not s.calls


@pytest.mark.parametrize("damage", ["route", "secret", "options", "inputs", "method"])
def test_sdk_and_inputs_cannot_change_during_the_real_response_path(native_last, damage):
    s = native_last
    def change(symbol, body):
        if damage == "route": s.client.urls["api"]["fapiPublicV2"] = "https://invalid.example/fapi/v2"
        elif damage == "secret": s.client.secret = "FAKE_CHANGED_SECRET"
        elif damage == "options": s.client.options["late"] = True
        elif damage == "inputs": s.markets[0]["contractSize"] = "0.02"
        else: s.client.sign = lambda *args, **kwargs: None
        return body
    s.hook = change
    with pytest.raises(CChanException, match="Last V2"):
        collect(s)
    assert len(s.calls) == 1


@pytest.mark.parametrize("kind,budget", [("age", 4), ("span", 4), ("native_age", 9)])
def test_local_age_span_and_native_transaction_age_each_have_exact_boundaries(native_last, kind, budget):
    s = native_last
    if kind == "native_age":
        for symbol in s.bodies:
            body = json.loads(s.bodies[symbol])
            body["time"] = NOW-5
            s.bodies[symbol] = json.dumps(body)
    document = collect(s, age=budget if kind != "span" else 1000, span=budget if kind == "span" else 1000)
    assert verify(s, document, age=budget if kind != "span" else 1000, span=budget if kind == "span" else 1000) == document
    with pytest.raises(CChanException, match="Last V2"):
        verify(s, document, age=budget-1 if kind != "span" else 1000, span=budget-1 if kind == "span" else 1000)


@pytest.mark.parametrize("value", [True, -1, 0.5, None, 2**63])
@pytest.mark.parametrize("field", ["age", "span"])
def test_budgets_have_no_float_bool_negative_missing_or_overflow_defaults(native_last, field, value):
    s = native_last
    with pytest.raises(CChanException, match="Last V2"):
        collect(s, **{field: value})
    assert not s.calls


@pytest.mark.parametrize("value", [True, -1, 0.5, None, 2**63])
@pytest.mark.parametrize("point", ["initial", "before_get"])
def test_invalid_clock_is_rejected_before_the_next_network_operation(native_last, value, point):
    s, calls = native_last, {"count": 0}
    def clock():
        calls["count"] += 1
        return value if point == "initial" or calls["count"] == 2 else s.clock["now"]
    s.monkeypatch.setattr(s.api, "utc_now_ms", clock)
    with pytest.raises(CChanException, match="Last V2"):
        collect(s)
    assert not s.calls


@pytest.mark.parametrize("point", ["reader", "collector"])
def test_positive_one_nanosecond_of_terminal_checks_is_not_truncated_to_zero(native_last, point):
    s = native_last
    document = collect(s, age=4)
    s.clock["now"] = NOW if point == "collector" else NOW+4
    ticks = iter([0, 0, 0, 1] if point == "collector" else [0, 1])
    s.monkeypatch.setattr(s.api, "_monotonic_ns", lambda: next(ticks))
    with pytest.raises(CChanException, match="Last V2"):
        collect(s, age=4) if point == "collector" else verify(s, document, age=4)


@pytest.mark.parametrize("ticks", [(True, 0), (0, False), (-1, 0), (2, 1), (0, 0.5)])
def test_reader_rejects_invalid_or_backwards_core_clock(native_last, ticks):
    s = native_last
    document = collect(s)
    values = iter(ticks)
    s.monkeypatch.setattr(s.api, "_monotonic_ns", lambda: next(values))
    with pytest.raises(CChanException, match="Last V2"):
        verify(s, document)


def test_reader_does_not_take_a_caller_supplied_as_of_clock(native_last):
    s = native_last
    document = collect(s)
    s.clock["now"] = NOW+1001
    with pytest.raises(CChanException, match="Last V2"):
        verify(s, document)
    with pytest.raises(TypeError):
        s.api.verify_binance_last_prices(document, max_age_ms=1000, max_observation_span_ms=1000, checked_ms=NOW+4)


def test_reader_final_source_check_cannot_hide_a_late_document_rewrite(native_last):
    s = native_last
    document = collect(s)
    original, calls = s.api._implementation, {"n": 0}
    def change():
        result = original()
        calls["n"] += 1
        if calls["n"] == 2:
            document["payload"]["observations"][0]["price"] = "1"
            reseal(document)
        return result
    s.monkeypatch.setattr(s.api, "_implementation", change)
    with pytest.raises(CChanException, match="Last V2"):
        verify(s, document)


@pytest.mark.parametrize("damage", ["route", "options", "method"])
def test_last_business_clock_cannot_change_sdk_before_the_actual_get(native_last, damage):
    s, calls = native_last, {"n": 0}
    def change():
        calls["n"] += 1
        if calls["n"] == 2:
            if damage == "route": s.client.urls["api"]["fapiPublicV2"] = "https://invalid.example/fapi/v2"
            elif damage == "options": s.client.options["maxRetriesOnFailure"] = 1
            else: s.client.fapiPublicV2GetTickerPrice = lambda *args: s.calls.append(("OVERRIDDEN_METHOD",)) or {}
        return s.clock["now"]
    s.monkeypatch.setattr(s.api, "utc_now_ms", change)
    with pytest.raises(CChanException, match="Last V2"):
        collect(s)
    assert not s.calls


def test_collector_terminal_sdk_check_cannot_publish_a_rewritten_document(native_last):
    s = native_last
    reader, sdk, saved = s.api.verify_binance_last_prices, s.api._sdk, {}
    def remember(document, **kwargs):
        result = reader(document, **kwargs)
        saved["document"] = document
        return result
    def change(*args):
        result = sdk(*args)
        if saved:
            saved["document"]["payload"]["observations"][0]["price"] = "1"
            reseal(saved["document"])
        return result
    s.monkeypatch.setattr(s.api, "verify_binance_last_prices", remember)
    s.monkeypatch.setattr(s.api, "_sdk", change)
    with pytest.raises(CChanException, match="Last V2"):
        collect(s)


def test_import_is_offline_and_does_not_initialize_sdk_configuration_or_database():
    script = """
import sys
import Trade.NativeLastPrice
assert not any(x in sys.modules for x in ('ccxt', 'Config', 'Trade.CCXTTradeEngine', 'db_util'))
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout+result.stderr
