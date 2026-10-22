"""Real credential-free SDK routes with fake native responses; never HTTP."""
import copy
import hashlib
import subprocess
import sys
import traceback
from decimal import localcontext

import ccxt
import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from Trade.NativeMarketEvidence import collect_native_market_evidence, verify_native_market_evidence


NOW = 1_800_000_000_000
_BOTH = [("binance", "testnet"), ("okx", "testnet")]


@pytest.fixture(params=[("binance", "testnet"), ("binance", "live"),
                       ("binanceusdm", "testnet"), ("binanceusdm", "live"),
                       ("okx", "testnet"), ("okx", "live")])
def native_market(request, monkeypatch):
    exchange_id, mode = request.param
    client = getattr(ccxt, exchange_id)()
    if mode == "testnet":
        client.set_sandbox_mode(True)
    clock, calls, responses = {"now": NOW}, [], {}
    markets = []
    for base, size in (("TEST", "0.01"), ("ALT", "0.1")):
        instrument = base+"-USDT-SWAP" if exchange_id == "okx" else base+"USDT"
        markets.append({"exchange": exchange_id, "id": instrument, "symbol": base+"/USDT:USDT", "type": "swap",
                        "base": base, "quote": "USDT", "settle": "USDT", "contractSize": size,
                        "precision_mode": ccxt.TICK_SIZE, "precision": {"amount": 1.0, "price": 0.1},
                        "limits": {"amount": {"min": 1.0, "max": None}, "price": {}, "cost": {"min": 5.0}}})
        if exchange_id == "okx":
            responses[instrument] = {
                "mark": {"code": "0", "msg": "", "data": [{"instType": "SWAP", "instId": instrument,
                         "markPx": "100.2500", "ts": str(NOW-20), "private_unused": "DO_NOT_PERSIST"}]},
                "book": {"code": "0", "msg": "", "data": [{"bids": [["100.0", "12", "0", "2"]],
                         "asks": [["100.5", "9", "0", "1"]], "ts": str(NOW-10), "seqId": 21}]}}
        else:
            responses[instrument] = {"mark": {"symbol": instrument, "markPrice": "100.2500", "time": NOW-20,
                                      "lastFundingRate": "0.0001", "private_unused": "DO_NOT_PERSIST"},
                                     "book": {"symbol": instrument, "bidPrice": "100.0", "bidQty": "0.12",
                                              "askPrice": "100.5", "askQty": "0.09", "time": NOW-10}}

    def source(kind, params):
        instrument = params["instId" if exchange_id == "okx" else "symbol"]
        calls.append((kind, copy.deepcopy(params)))
        clock["now"] += 10
        return copy.deepcopy(responses[instrument][kind])

    def no_http(*args, **kwargs):
        raise AssertionError("native market fixtures must not perform HTTP or private reads")

    monkeypatch.setattr(client, "request", no_http)
    monkeypatch.setattr(client, "publicGetPublicMarkPrice" if exchange_id == "okx" else "fapiPublicGetPremiumIndex",
                        lambda params: source("mark", params))
    monkeypatch.setattr(client, "publicGetMarketBooks" if exchange_id == "okx" else "fapiPublicGetTickerBookTicker",
                        lambda params: source("book", params))
    monkeypatch.setattr("Trade.NativeMarketEvidence.utc_now_ms", lambda: clock["now"])
    return client, mode, markets, responses, calls, clock


def test_independent_raw_mark_and_book_keep_full_market_windows_and_never_become_admission(native_market):
    client, mode, markets, _, calls, clock = native_market
    document = collect_native_market_evidence(client, markets, mode=mode)
    assert verify_native_market_evidence(document) == document
    assert set(document) == {"schema", "payload", "payload_sha256"}
    assert document["schema"] == "chan-native-market-evidence-v1"
    payload = document["payload"]
    assert payload["native_admission_verified"] is False
    assert payload["coverage"] == "observed_native_mark_and_best_book"
    assert payload["mode"] == mode and payload["exchange_id"] == client.id
    assert (payload["started_ms"], payload["finished_ms"], payload["requests"]) == (NOW, clock["now"], 4)
    assert document["payload_sha256"] == hashlib.sha256(canonical_bytes(payload)).hexdigest()
    assert payload["sdk"]["version"] == ccxt.__version__ and payload["sdk"]["source_sha256"]
    assert payload["implementation_sha256"]["Trade/NativeMarketEvidence.py"]
    assert "DO_NOT_PERSIST" not in canonical_bytes(document).decode()
    assert len(calls) == 4 and [kind for kind, _ in calls] == ["mark", "book", "mark", "book"]
    for observation in payload["observations"]:
        market, mark, book = (observation[k] for k in ("market", "mark", "book"))
        assert market == next(m for m in markets if m["id"] == market["id"])
        assert mark["price"] == "100.25" and mark["source_ms"] == NOW-20
        assert book["source_ms"] == NOW-10 and book["tradeable"] is True
        assert mark["started_ms"] <= mark["finished_ms"] <= book["started_ms"] <= book["finished_ms"]
        if client.id == "okx":
            assert mark["clock_kind"] == "data_return_time" and book["clock_kind"] == "book_generation_time"
            assert book["instrument_binding"] == "request_only" and "instId" not in book["raw"]
            assert book["native_quantity_unit"] == "contracts" and book["bid_contracts"] == "12"
            assert book["bid_quantity"] == ("0.12" if market["base"] == "TEST" else "1.2")
            assert mark["params"] == {"instType": "SWAP", "instId": market["id"]}
            assert book["params"] == {"instId": market["id"], "sz": "1"}
        else:
            assert mark["clock_kind"] == "native_time" and book["clock_kind"] == "transaction_time"
            assert book["instrument_binding"] == "response_symbol" and book["native_quantity_unit"] == "base_currency"
            assert book["bid_quantity"] == "0.12"
            assert book["bid_contracts"] == ("12" if market["base"] == "TEST" else "1.2")
            assert mark["params"] == book["params"] == {"symbol": market["id"]}


def reseal(document):
    document["payload_sha256"] = hashlib.sha256(canonical_bytes(document["payload"])).hexdigest()


def first_raw(native_market, kind):
    client, _, markets, responses, _, _ = native_market
    # The collector sorts the full explicit market pool, not just the candidate.
    wire = responses[min(markets, key=lambda m: m["id"])["id"]][kind]
    return wire["data"][0] if client.id == "okx" else wire


@pytest.mark.parametrize("native_market", _BOTH, indirect=True)
@pytest.mark.parametrize("damage", ["route", "sandbox", "tls", "simulated", "duplicate_header"])
def test_public_environment_is_guarded_before_any_source_request(native_market, damage):
    client, mode, markets, _, calls, _ = native_market
    if damage == "route":
        client.urls["api"]["rest" if client.id == "okx" else "fapiPublic"] = "https://wrong.example.invalid/data"
    elif damage == "sandbox":
        client.isSandboxModeEnabled = False
    elif damage == "tls":
        client.verify = False
    elif damage == "simulated":
        client.headers = {"x-simulated-trading": "0" if client.id == "okx" else "1"}
    else:
        client.headers = {"x-simulated-trading": "1", "X-Simulated-Trading": "1"}
    with pytest.raises(CChanException):
        collect_native_market_evidence(client, markets, mode=mode)
    assert calls == []


@pytest.mark.parametrize("native_market", [("okx", "testnet")], indirect=True)
def test_okx_unchanged_template_does_not_hide_a_changed_hostname(native_market):
    client, mode, markets, _, calls, _ = native_market
    client.hostname = "wrong.example.invalid"
    with pytest.raises(CChanException):
        collect_native_market_evidence(client, markets, mode=mode)
    assert calls == []


@pytest.mark.parametrize("native_market", _BOTH, indirect=True)
@pytest.mark.parametrize("kind", ["mark", "book"])
@pytest.mark.parametrize("damage", ["route", "id", "tls"])
def test_each_request_rechecks_client_identity_and_route_before_publishing(native_market, monkeypatch, kind, damage):
    client, mode, markets, _, calls, _ = native_market
    method = (("publicGetPublicMarkPrice" if kind == "mark" else "publicGetMarketBooks") if client.id == "okx" else
              ("fapiPublicGetPremiumIndex" if kind == "mark" else "fapiPublicGetTickerBookTicker"))
    get = getattr(client, method)
    key = "rest" if client.id == "okx" else "fapiPublic"

    def changed(params):
        result = get(params)
        if damage == "route":
            client.urls["api"][key] = "https://changed.example.invalid/data"
        elif damage == "id":
            client.id = "different-exchange"
        else:
            client.verify = False
        return result

    monkeypatch.setattr(client, method, changed)
    with pytest.raises(CChanException):
        collect_native_market_evidence(client, markets, mode=mode)
    assert len(calls) == (1 if kind == "mark" else 2)


@pytest.mark.parametrize("native_market", _BOTH, indirect=True)
@pytest.mark.parametrize("damage", ["empty", "duplicate_id", "duplicate_symbol", "wrong_venue", "zero_size", "float_size",
                                   "spot", "settle", "precision", "limits", "secret_field", "nonfinite", "budget"])
def test_missing_duplicate_or_bad_market_pool_is_rejected_whole_before_get(native_market, damage):
    client, mode, markets, _, calls, _ = native_market
    if damage == "empty":
        markets.clear()
    elif damage == "duplicate_id":
        markets[1]["id"] = markets[0]["id"]
    elif damage == "duplicate_symbol":
        markets[1]["symbol"] = markets[0]["symbol"]
    elif damage == "wrong_venue":
        markets[0]["exchange"] = "okx" if client.id == "binance" else "binance"
    elif damage in {"zero_size", "float_size"}:
        markets[0]["contractSize"] = 0 if damage == "zero_size" else 0.1
    elif damage == "spot":
        markets[0]["type"] = "spot"
    elif damage == "settle":
        markets[0]["settle"] = "USD"
    elif damage == "precision":
        del markets[0]["precision"]["amount"]
    elif damage == "limits":
        del markets[0]["limits"]["cost"]
    elif damage == "secret_field":
        markets[0]["apiKey"] = "PRIVATE_DO_NOT_PERSIST"
    elif damage == "nonfinite":
        markets[0]["precision"]["price"] = float("nan")
    else:
        markets[:] = [copy.deepcopy(markets[0]) for _ in range(65)]
    with pytest.raises(CChanException):
        collect_native_market_evidence(client, markets, mode=mode)
    assert calls == []


@pytest.mark.parametrize("native_market", _BOTH, indirect=True)
@pytest.mark.parametrize("damage", ["price_missing", "price_zero", "price_nan", "price_float", "price_bool", "time_missing",
                                   "time_bool", "time_future", "wrong_instrument"])
def test_native_mark_requires_its_own_exact_raw_price_clock_and_instrument(native_market, damage):
    client, mode, markets, _, calls, _ = native_market
    raw = first_raw(native_market, "mark")
    price, clock, instrument = (("markPx", "ts", "instId") if client.id == "okx" else ("markPrice", "time", "symbol"))
    if damage == "price_missing":
        del raw[price]
    elif damage.startswith("price_"):
        raw[price] = {"price_zero": "0", "price_nan": "NaN", "price_float": 100.25, "price_bool": True}[damage]
    elif damage == "time_missing":
        del raw[clock]
    elif damage == "time_bool":
        raw[clock] = True
    elif damage == "time_future":
        raw[clock] = NOW+100_000
    else:
        raw[instrument] = "WRONG"
    with pytest.raises(CChanException):
        collect_native_market_evidence(client, markets, mode=mode)
    assert len(calls) == 1


@pytest.mark.parametrize("native_market", _BOTH, indirect=True)
@pytest.mark.parametrize("damage", ["negative_quantity", "nonfinite", "float_quantity", "future_clock", "missing_clock"])
def test_native_book_never_uses_mark_or_receive_time_to_fill_missing_evidence(native_market, damage):
    client, mode, markets, _, calls, _ = native_market
    raw = first_raw(native_market, "book")
    clock = "ts" if client.id == "okx" else "time"
    if damage in {"future_clock", "missing_clock"}:
        if damage == "missing_clock":
            del raw[clock]
        else:
            raw[clock] = NOW+100_000
    else:
        value = {"negative_quantity": "-1", "nonfinite": "Infinity", "float_quantity": 1.2}[damage]
        if client.id == "okx":
            raw["bids"][0][1] = value
        else:
            raw["bidQty"] = value
    with pytest.raises(CChanException):
        collect_native_market_evidence(client, markets, mode=mode)
    assert len(calls) == 2


@pytest.mark.parametrize("native_market", _BOTH, indirect=True)
@pytest.mark.parametrize("damage", ["crossed", "locked", "zero_quantity"])
def test_nontradeable_native_books_remain_observations_never_admissions(native_market, damage):
    client, mode, markets, _, _, _ = native_market
    raw = first_raw(native_market, "book")
    if client.id == "okx":
        raw["bids"][0][0 if damage != "zero_quantity" else 1] = {"crossed": "101", "locked": "100.5", "zero_quantity": "0"}[damage]
    else:
        raw["bidPrice" if damage != "zero_quantity" else "bidQty"] = {"crossed": "101", "locked": "100.5", "zero_quantity": "0"}[damage]
    payload = collect_native_market_evidence(client, markets, mode=mode)["payload"]
    assert payload["observations"][0]["book"]["tradeable"] is False
    assert payload["native_admission_verified"] is False


@pytest.mark.parametrize("native_market", [("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("side", ["bids", "asks"])
def test_empty_okx_side_is_preserved_without_synthesizing_a_price(native_market, side):
    client, mode, markets, _, _, _ = native_market
    first_raw(native_market, "book")[side] = []
    book = collect_native_market_evidence(client, markets, mode=mode)["payload"]["observations"][0]["book"]
    assert book["tradeable"] is False
    assert book["bid_price" if side == "bids" else "ask_price"] is None
    assert book["raw"][side] == []


@pytest.mark.parametrize("native_market", _BOTH, indirect=True)
@pytest.mark.parametrize("damage", ["price", "quantity", "unit", "clock", "endpoint", "params", "raw_price", "source_ms",
                                   "window", "missing_market", "duplicate_market", "admission", "schema", "implementation"])
def test_resealed_inconsistent_stored_content_is_rederived_not_trusted(native_market, damage):
    client, mode, markets, _, _, _ = native_market
    document = collect_native_market_evidence(client, markets, mode=mode)
    payload = document["payload"]
    row = payload["observations"][0]
    if damage == "price":
        row["mark"]["price"] = "100.26"
    elif damage == "quantity":
        row["book"]["bid_quantity"] = "42"
    elif damage == "unit":
        row["book"]["native_quantity_unit"] = "unknown"
    elif damage == "clock":
        row["mark"]["clock_kind"] = "book_generation_time"
    elif damage == "endpoint":
        row["book"]["endpoint"] = "/ticker/last"
    elif damage == "params":
        row["mark"]["params"]["symbol" if client.id == "binance" else "instId"] = "WRONG"
    elif damage == "raw_price":
        row["mark"]["raw"]["markPrice" if client.id == "binance" else "markPx"] = "100.26"
    elif damage == "source_ms":
        row["book"]["source_ms"] = NOW
    elif damage == "window":
        row["book"]["started_ms"] = row["mark"]["started_ms"]-1
    elif damage == "missing_market":
        payload["observations"].pop()
    elif damage == "duplicate_market":
        payload["observations"][1]["market"] = copy.deepcopy(row["market"])
    elif damage == "admission":
        payload["native_admission_verified"] = True
    elif damage == "schema":
        document["schema"] = "chan-software-entry-quotes-v1"
    else:
        payload["implementation_sha256"]["Trade/NativeMarketEvidence.py"] = "0"*64
    reseal(document)
    with pytest.raises(CChanException):
        verify_native_market_evidence(document)


def test_same_native_timestamp_different_content_and_windows_get_distinct_ids(native_market):
    client, mode, markets, _, calls, _ = native_market
    first = collect_native_market_evidence(client, markets, mode=mode)
    before = canonical_bytes(first)
    raw = first_raw(native_market, "mark")
    raw["markPx" if client.id == "okx" else "markPrice"] = "100.3"
    markets[0]["limits"]["amount"]["min"] = 2.0
    second = collect_native_market_evidence(client, markets, mode=mode)
    assert canonical_bytes(first) == before and first["payload_sha256"] != second["payload_sha256"]
    assert first["payload"]["observations"][0]["mark"]["source_ms"] == second["payload"]["observations"][0]["mark"]["source_ms"]
    assert len(calls) == 8  # No timestamp-only cache/dedup or invented immutable exchange event ID.


@pytest.mark.parametrize("native_market", _BOTH, indirect=True)
def test_old_source_clock_is_preserved_without_an_implicit_freshness_default(native_market):
    client, mode, markets, _, _, _ = native_market
    first_raw(native_market, "mark")["ts" if client.id == "okx" else "time"] = NOW-86_400_000
    payload = collect_native_market_evidence(client, markets, mode=mode)["payload"]
    assert payload["observations"][0]["mark"]["source_ms"] == NOW-86_400_000
    assert payload["native_admission_verified"] is False


@pytest.mark.parametrize("native_market", _BOTH, indirect=True)
def test_native_conversion_is_independent_of_the_callers_decimal_context(native_market):
    client, mode, markets, _, _, _ = native_market
    with localcontext() as context:
        context.prec = 2
        document = collect_native_market_evidence(client, markets, mode=mode)
    assert verify_native_market_evidence(document) == document


@pytest.mark.parametrize("native_market", _BOTH, indirect=True)
def test_raw_transport_failure_is_redacted_and_never_retried(native_market, monkeypatch, capsys):
    client, mode, markets, _, calls, _ = native_market
    attempted = []
    def fail(params):
        attempted.append(params)
        raise ccxt.NetworkError("PRIVATE_NATIVE_RESPONSE_API_KEY")
    monkeypatch.setattr(client, "publicGetPublicMarkPrice" if client.id == "okx" else "fapiPublicGetPremiumIndex", fail)
    with pytest.raises(CChanException) as error:
        collect_native_market_evidence(client, markets, mode=mode)
    assert "PRIVATE_NATIVE_RESPONSE_API_KEY" not in "".join(traceback.format_exception(error.type, error.value, error.tb))+str(capsys.readouterr())
    assert len(attempted) == 1 and calls == []


@pytest.mark.parametrize("native_market", _BOTH, indirect=True)
def test_a_backwards_local_observation_clock_cannot_publish(native_market, monkeypatch):
    client, mode, markets, _, calls, clock = native_market
    method = "publicGetPublicMarkPrice" if client.id == "okx" else "fapiPublicGetPremiumIndex"
    get = getattr(client, method)
    def backwards(params):
        wire = get(params)
        clock["now"] = NOW-100
        return wire
    monkeypatch.setattr(client, method, backwards)
    with pytest.raises(CChanException):
        collect_native_market_evidence(client, markets, mode=mode)
    assert calls  # A failed observation is not proof that no remote read occurred.


@pytest.mark.parametrize("native_market", _BOTH, indirect=True)
@pytest.mark.parametrize("damage", ["zero_tick", "fractional_digits", "float_digit_type", "inverted_limits"])
def test_invalid_execution_metadata_cannot_be_disguised_as_complete_market_identity(native_market, damage):
    client, mode, markets, _, calls, _ = native_market
    market = markets[0]
    if damage == "zero_tick":
        market["precision"]["amount"] = 0.0
    elif damage == "fractional_digits":
        market["precision_mode"] = ccxt.DECIMAL_PLACES
        market["precision"]["amount"] = 1.2
    elif damage == "float_digit_type":
        market["precision_mode"] = ccxt.DECIMAL_PLACES
        market["precision"].update(amount=1.0, price=1)
    else:
        market["limits"]["cost"]["max"] = 4.0
    with pytest.raises(CChanException):
        collect_native_market_evidence(client, markets, mode=mode)
    assert calls == []


@pytest.mark.parametrize("native_market", _BOTH, indirect=True)
@pytest.mark.parametrize("mode", [ccxt.DECIMAL_PLACES, ccxt.SIGNIFICANT_DIGITS])
@pytest.mark.parametrize("digits", [-1, 0, 2])
def test_sdk_integer_digit_metadata_is_preserved_not_reinterpreted_as_a_tick(native_market, mode, digits):
    client, environment_mode, markets, _, _, _ = native_market
    for market in markets:
        market["precision_mode"] = mode
        market["precision"].update(amount=digits, price=digits)
    document = collect_native_market_evidence(client, markets, mode=environment_mode)
    for row in document["payload"]["observations"]:
        assert row["market"]["precision_mode"] == mode and row["market"]["precision"]["amount"] == digits
    assert document["payload"]["native_admission_verified"] is False


@pytest.mark.parametrize("native_market", [("okx", "testnet")], indirect=True)
@pytest.mark.parametrize("damage", ["code", "extra_row", "inst_type", "missing_sequence", "multi_depth", "bad_level"])
def test_okx_success_code_single_instrument_and_requested_depth_are_not_inferred(native_market, damage):
    client, mode, markets, responses, _, _ = native_market
    instrument = min(markets, key=lambda m: m["id"])["id"]
    if damage == "code":
        responses[instrument]["mark"]["code"] = "50001"
    elif damage == "extra_row":
        responses[instrument]["mark"]["data"] *= 2
    elif damage == "inst_type":
        first_raw(native_market, "mark")["instType"] = "FUTURES"
    elif damage == "missing_sequence":
        del first_raw(native_market, "book")["seqId"]
    elif damage == "multi_depth":
        first_raw(native_market, "book")["bids"] *= 2
    else:
        first_raw(native_market, "book")["asks"][0] = ["100.5", "9"]
    with pytest.raises(CChanException):
        collect_native_market_evidence(client, markets, mode=mode)


@pytest.mark.parametrize("native_market", _BOTH, indirect=True)
def test_sdk_identity_cannot_change_during_the_batch(native_market, monkeypatch):
    client, mode, markets, _, _, _ = native_market
    method = "publicGetPublicMarkPrice" if client.id == "okx" else "fapiPublicGetPremiumIndex"
    get = getattr(client, method)
    def changed(params):
        result = get(params)
        monkeypatch.setattr(ccxt, "__version__", "0.0.0-changed")
        return result
    monkeypatch.setattr(client, method, changed)
    with pytest.raises(CChanException):
        collect_native_market_evidence(client, markets, mode=mode)


@pytest.mark.parametrize("native_market", _BOTH, indirect=True)
def test_keyboard_interrupt_is_neither_swallowed_nor_retried(native_market, monkeypatch):
    client, mode, markets, _, _, _ = native_market
    attempted = []
    def stop(params):
        attempted.append(params)
        raise KeyboardInterrupt()
    monkeypatch.setattr(client, "publicGetPublicMarkPrice" if client.id == "okx" else "fapiPublicGetPremiumIndex", stop)
    with pytest.raises(KeyboardInterrupt):
        collect_native_market_evidence(client, markets, mode=mode)
    assert len(attempted) == 1


@pytest.mark.parametrize("native_market", [("binance", "testnet")], indirect=True)
def test_inexact_unit_conversion_is_not_hidden_by_rounding_or_epsilon(native_market):
    client, mode, markets, _, calls, _ = native_market
    min(markets, key=lambda m: m["id"])["contractSize"] = "0.07"
    with pytest.raises(CChanException):
        collect_native_market_evidence(client, markets, mode=mode)
    assert len(calls) == 2


@pytest.mark.parametrize("native_market", _BOTH, indirect=True)
def test_stored_observation_reader_imports_no_sdk_or_other_optional_runtime(native_market):
    client, mode, markets, _, _, _ = native_market
    document = collect_native_market_evidence(client, markets, mode=mode)
    code = """
import importlib.abc, json, sys
blocked = {'ccxt', 'xgboost', 'lightgbm', 'sklearn', 'optuna', 'yaml', 'PyQt6', 'minio', 'qcloud_cos'}
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise ModuleNotFoundError('optional dependency intentionally absent')
sys.meta_path.insert(0, BlockOptional())
import Trade.NativeMarketEvidence as reader
document = json.loads(sys.stdin.buffer.read())
reader.utc_now_ms = lambda: document['payload']['finished_ms']
assert reader.verify_native_market_evidence(document) == document
assert not any(name.split('.')[0] in blocked for name in sys.modules)
print('optional-free stored market reader PASS')
"""
    result = subprocess.run([sys.executable, "-c", code], input=canonical_bytes(document), capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.strip() == b"optional-free stored market reader PASS" and result.stderr == b""
