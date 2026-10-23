"""Native instrument metadata from raw public endpoints, never SDK cache/I/O."""
import copy
import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import ccxt
import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes


NOW = 1_800_000_000_000


def instrument_api():
    assert importlib.util.find_spec("Trade.NativeInstrumentEvidence") is not None, "native instrument source is missing"
    from Trade import NativeInstrumentEvidence
    return NativeInstrumentEvidence


def test_native_instrument_source_api_exists():
    api = instrument_api()
    assert callable(api.collect_native_instrument_evidence)
    assert callable(api.verify_native_instrument_evidence)


def raw_instrument(exchange_id, base):
    if exchange_id == "okx":
        return {"instId": base+"-USDT-SWAP", "instType": "SWAP", "baseCcy": "", "quoteCcy": "",
            "settleCcy": "USDT", "uly": base+"-USDT", "instFamily": base+"-USDT", "ctType": "linear",
            "ctVal": "0.01" if base == "TEST" else "0.1", "ctMult": "1", "ctValCcy": base,
            "state": "live", "lotSz": "1", "minSz": "1", "maxLmtSz": "10000", "maxMktSz": "1000",
            "tickSz": "0.1", "lever": "20", "listTime": str(NOW-1000), "contTdSwTime": "",
            "expTime": "", "upcChg": [{"param": "tickSz", "newValue": "0.2", "effTime": str(NOW+1000)}],
            "private_unused": "DO_NOT_PERSIST"}
    return {"symbol": base+"USDT", "pair": base+"USDT", "baseAsset": base, "quoteAsset": "USDT", "marginAsset": "USDT",
        "contractType": "PERPETUAL", "status": "TRADING", "onboardDate": NOW-1000, "deliveryDate": 4133404800000,
        "quantityPrecision": 3, "pricePrecision": 2, "baseAssetPrecision": 8, "quotePrecision": 8,
        "orderTypes": ["LIMIT", "MARKET"], "timeInForce": ["GTC", "IOC", "FOK", "GTX"],
        "filters": [{"filterType": "PRICE_FILTER", "minPrice": "0.1", "maxPrice": "1000000", "tickSize": "0.1"},
                    {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "1000", "stepSize": "0.001"},
                    {"filterType": "MARKET_LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5"}],
        "private_unused": "DO_NOT_PERSIST"}


@pytest.fixture(params=[(name, mode) for name in ("binance", "binanceusdm", "okx") for mode in ("testnet", "live")])
def native_instruments(request, monkeypatch):
    api = instrument_api()
    exchange_id, mode = request.param
    client = getattr(ccxt, exchange_id)()
    if mode == "testnet":
        client.set_sandbox_mode(True)
    rows = [raw_instrument(exchange_id, base) for base in ("TEST", "ALT")]
    clock, calls = {"now": NOW}, []
    reference = getattr(ccxt, exchange_id)()
    poisoned = [reference.parse_market(row) for row in rows]
    for row in poisoned:
        row["contractSize"], row["precision"]["price"] = 999, 99
    client.set_markets(poisoned)
    def public(options):
        calls.append(copy.deepcopy(options))
        clock["now"] += 10
        return ({"code": "0", "data": copy.deepcopy(rows), "msg": ""} if exchange_id == "okx" else
                {"symbols": copy.deepcopy(rows), "serverTime": NOW+999_999, "timezone": "UTC"})
    def no_io(*args, **kwargs):
        raise AssertionError("no cache reload, private, cross-product or actual HTTP in instrument source")
    monkeypatch.setattr(ccxt.Exchange, "fetch", no_io)
    for name in ("request", "load_markets", "fetch_markets", "fetch_currencies"):
        monkeypatch.setattr(client, name, no_io)
    method = "publicGetPublicInstruments" if exchange_id == "okx" else "fapiPublicGetExchangeInfo"
    monkeypatch.setattr(client, method, public)
    monkeypatch.setattr(api, "utc_now_ms", lambda: clock["now"])
    return {"api": api, "client": client, "mode": mode, "codes": ["TEST/USDT:USDT", "ALT/USDT:USDT"],
            "rows": rows, "calls": calls, "clock": clock, "method": method, "public": public}


def collect(case):
    return case["api"].collect_native_instrument_evidence(case["client"], case["codes"], mode=case["mode"])


def test_native_rows_ignore_poisoned_sdk_cache_and_match_original_engine_metadata(native_instruments):
    case = native_instruments
    client, rows = case["client"], case["rows"]
    cached = canonical_bytes({"markets": client.markets, "options": client.options, "urls": client.urls, "headers": client.headers})
    document = collect(case)
    assert case["api"].verify_native_instrument_evidence(copy.deepcopy(document)) == document
    assert document["schema"] == "chan-native-instrument-evidence-v1"
    p = document["payload"]
    assert document["payload_sha256"] == hashlib.sha256(canonical_bytes(p)).hexdigest()
    assert p["coverage"] == "allowlisted_native_instrument_metadata"
    assert p["economics_complete"] is p["native_admission_verified"] is False
    assert p["codes"] == sorted(case["codes"])
    assert p["clock_kind"] == "local_request_window_only" and p["source_ms"] is None
    assert p["requests"] == 1 and case["calls"] == ([{"instType": "SWAP"}] if client.id == "okx" else [{}])
    assert p["endpoint"] == ("/api/v5/public/instruments" if client.id == "okx" else "/fapi/v1/exchangeInfo")
    assert (p["started_ms"], p["request_started_ms"], p["request_finished_ms"], p["finished_ms"]) == (NOW, NOW, NOW+10, NOW+10)
    assert "DO_NOT_PERSIST" not in canonical_bytes(document).decode()
    assert canonical_bytes({"markets": client.markets, "options": client.options, "urls": client.urls, "headers": client.headers}) == cached
    # Compare the actual original Engine projection; no engine initialization,
    # account I/O or user configuration is needed for its existing pure branch.
    from Trade.CCXTTradeEngine import CCCXTTradeEngine
    engine = CCCXTTradeEngine.__new__(CCCXTTradeEngine)
    engine.market_type, engine.dry_run = "swap", False
    engine.exchange = getattr(ccxt, client.id)()
    engine.exchange.set_markets([engine.exchange.parse_market(row) for row in rows])
    for observed in p["observations"]:
        definition, _ = engine._market_contract(observed["market"]["symbol"])
        assert canonical_bytes(observed["market"]) == canonical_bytes(definition)
        assert observed["active"] is True
        assert p["raw_rows"][observed["raw_index"]]["instId" if client.id == "okx" else "symbol"] == definition["id"]


def test_codes_mutated_during_the_public_get_cannot_change_the_frozen_target_pool(native_instruments, monkeypatch):
    case = native_instruments
    def mutate(options):
        response = case["public"](options)
        case["codes"].append("NEW/USDT:USDT")
        return response
    monkeypatch.setattr(case["client"], case["method"], mutate)
    with pytest.raises(CChanException):
        collect(case)
    assert len(case["calls"]) == 1


@pytest.mark.parametrize("missing", ["tick", "lot"])
def test_missing_native_ticks_never_fall_back_to_decimal_digit_counts(native_instruments, missing):
    case = native_instruments
    if case["client"].id == "okx":
        del case["rows"][0]["tickSz" if missing == "tick" else "lotSz"]
    else:
        kind = "PRICE_FILTER" if missing == "tick" else "LOT_SIZE"
        case["rows"][0]["filters"] = [row for row in case["rows"][0]["filters"] if row["filterType"] != kind]
    with pytest.raises(CChanException):
        collect(case)
    assert len(case["calls"]) == 1


def test_native_unit_declaration_cannot_contradict_sdk_inference(native_instruments):
    case = native_instruments
    row = case["rows"][0]
    if case["client"].id == "okx":
        row["ctType"] = "inverse"  # SDK infers linear from quote/settle instead.
    else:
        del row["contractType"]
        # The SDK can infer swap from the sentinel delivery date even when
        # this explicit native contract identity is absent.
    with pytest.raises(CChanException):
        collect(case)


@pytest.mark.parametrize("field", ["base", "quote", "value_currency"])
def test_explicit_currency_fields_cannot_be_overridden_by_underlying_inference(native_instruments, field):
    case = native_instruments
    fields = ({"base": "baseCcy", "quote": "quoteCcy", "value_currency": "ctValCcy"} if case["client"].id == "okx" else
              {"base": "baseAsset", "quote": "quoteAsset", "value_currency": "marginAsset"})
    case["rows"][0][fields[field]] = "OTHER"
    with pytest.raises(CChanException):
        collect(case)


def test_ignored_numeric_metadata_still_has_to_be_finite_and_parser_bounded(native_instruments):
    case = native_instruments
    if case["client"].id == "okx":
        # The SDK's contract cost limit ignores this spot-only intermediate.
        case["rows"][0]["maxMktSz"] = "NaN"
    else:
        # Its large fallback string is overwritten by PRICE_FILTER, but is
        # still constructed before then. Do not feed unbounded digit counts.
        case["rows"][0]["pricePrecision"] = 1000
    with pytest.raises(CChanException):
        collect(case)


def reseal(document):
    document["payload_sha256"] = hashlib.sha256(canonical_bytes(document["payload"])).hexdigest()
    return document


def test_reader_does_not_accept_a_numeric_alias_for_the_native_environment_bool(native_instruments):
    case = native_instruments
    document = collect(case)
    document["payload"]["environment"]["sandbox"] = int(case["mode"] == "testnet")
    with pytest.raises(CChanException):
        case["api"].verify_native_instrument_evidence(reseal(document))


@pytest.mark.parametrize("damage", ["missing_market", "duplicate_id", "ambiguous_symbol", "wrong_product", "wrong_settle",
    "zero_tick", "negative_lot", "nan_contract", "bad_state_type", "bad_nested", "float_raw"])
def test_bad_native_rows_fail_the_whole_batch_without_retries(native_instruments, damage):
    case = native_instruments
    rows, okx = case["rows"], case["client"].id == "okx"
    row = rows[0]
    if damage == "missing_market":
        rows.pop(0)
    elif damage in {"duplicate_id", "ambiguous_symbol"}:
        other = copy.deepcopy(row)
        if damage == "ambiguous_symbol":
            other["instId" if okx else "symbol"] = "SHADOW-USDT-SWAP" if okx else "SHADOWUSDT"
        rows.append(other)
    elif damage == "wrong_product":
        row["instType" if okx else "contractType"] = "FUTURES" if okx else "CURRENT_QUARTER"
    elif damage == "wrong_settle":
        row["settleCcy" if okx else "marginAsset"] = "OTHER"
    elif damage == "zero_tick":
        if okx:
            row["tickSz"] = "0"
        else:
            row["filters"][0]["tickSize"] = "0"
    elif damage == "negative_lot":
        if okx:
            row["lotSz"] = "-1"
        else:
            row["filters"][1]["stepSize"] = "-1"
    elif damage == "nan_contract":
        row["ctVal" if okx else "contractSize"] = "NaN"
    elif damage == "bad_state_type":
        row["state" if okx else "status"] = 0
    elif damage == "bad_nested":
        if okx:
            row["upcChg"] = "not-an-array"
        else:
            row["filters"].append(copy.deepcopy(row["filters"][0]))
    else:
        row["ctVal" if okx else "contractSize"] = 0.01
    with pytest.raises(CChanException):
        collect(case)
    assert len(case["calls"]) == 1


@pytest.mark.parametrize("damage", ["envelope", "extra", "admission", "economics", "venue", "mode", "code_order", "endpoint",
    "params", "native_clock", "sdk", "implementation", "future", "bool_clock", "bool_requests", "extra_raw", "active",
    "precision", "raw_index", "missing_observation", "native_state", "raw_size", "digest"])
def test_resealed_packets_cannot_replace_raw_reconstruction_or_exact_identity(native_instruments, damage):
    case = native_instruments
    document = collect(case)
    p = document["payload"]
    if damage == "envelope":
        document["passed"] = True
    elif damage == "extra":
        p["passed"] = True
    elif damage in {"admission", "economics"}:
        p["native_admission_verified" if damage == "admission" else "economics_complete"] = True
    elif damage == "venue":
        p["venue"] = "spot"
    elif damage == "mode":
        p["mode"] = "live" if p["mode"] == "testnet" else "testnet"
    elif damage == "code_order":
        p["codes"].reverse()
    elif damage == "endpoint":
        p["endpoint"] = "/ticker"
    elif damage == "params":
        p["params"]["caller_approved"] = True
    elif damage == "native_clock":
        p["source_ms"] = NOW
    elif damage == "sdk":
        p["sdk"]["version"] = "0.0.0"
    elif damage == "implementation":
        p["implementation_sha256"]["Trade/NativeInstrumentEvidence.py"] = "0"*64
    elif damage == "future":
        p["finished_ms"] = case["clock"]["now"]+1
    elif damage == "bool_clock":
        p["started_ms"] = False
    elif damage == "bool_requests":
        p["requests"] = True
    elif damage == "extra_raw":
        p["raw_rows"][0]["unknown"] = "do not trust"
    elif damage == "active":
        p["observations"][0]["active"] = False
    elif damage == "precision":
        p["observations"][0]["market"]["precision"]["price"] *= 2
    elif damage == "raw_index":
        p["observations"][0]["raw_index"] = bool(p["observations"][0]["raw_index"])
    elif damage == "missing_observation":
        p["observations"].pop()
    elif damage == "native_state":
        p["observations"][0]["native_state"] = "live-but-caller-replaced"
    elif damage == "raw_size":
        p["raw_rows"][0]["ctVal" if case["client"].id == "okx" else "contractSize"] = "7"
    else:
        document["payload_sha256"] = "0"*64
    if damage != "digest":
        reseal(document)
    with pytest.raises(CChanException):
        case["api"].verify_native_instrument_evidence(document)


@pytest.mark.parametrize("change", ["public_route", "private_route", "mode", "clock", "sdk", "source"])
def test_request_boundary_drift_is_rejected_without_second_get(native_instruments, monkeypatch, change):
    case = native_instruments
    client, read_bytes = case["client"], Path.read_bytes
    def changed(options):
        response = case["public"](options)
        if change in {"public_route", "private_route"}:
            route = ("rest" if client.id == "okx" else "fapiPublic" if change == "public_route" else "fapiPrivate")
            client.urls["api"][route] = "https://different.invalid"
        elif change == "mode":
            if client.id == "okx":
                client.headers["x-simulated-trading"] = "0" if case["mode"] == "testnet" else "1"
            else:
                client.isSandboxModeEnabled = not client.isSandboxModeEnabled
        elif change == "clock":
            case["clock"]["now"] = NOW-1
        elif change == "sdk":
            monkeypatch.setattr(ccxt, "__version__", "0.0.0")
        else:
            def drift(path):
                result = read_bytes(path)
                return result+b"# drift" if path.name == "NativeInstrumentEvidence.py" else result
            monkeypatch.setattr(Path, "read_bytes", drift)
        return response
    monkeypatch.setattr(client, case["method"], changed)
    with pytest.raises(CChanException):
        collect(case)
    assert len(case["calls"]) == 1


@pytest.mark.parametrize("bad", [None, [], "TEST/USDT:USDT", [True], ["TEST/USDT"], ["TEST/USDT:USDT"]*2,
    [f"C{index}/USDT:USDT" for index in range(65)], ["X/USDT:USDT "]])
def test_invalid_declared_pool_never_calls_a_native_endpoint(native_instruments, bad):
    case = native_instruments
    case["codes"] = bad
    with pytest.raises(CChanException):
        collect(case)
    assert case["calls"] == []


def test_existing_pool_bound_allows_exactly_64_targets_with_one_get(native_instruments):
    case = native_instruments
    case["codes"] = [f"C{index}/USDT:USDT" for index in range(64)]
    case["rows"][:] = [raw_instrument(case["client"].id, f"C{index}") for index in range(64)]
    result = collect(case)["payload"]
    assert len(result["observations"]) == 64 and len(case["calls"]) == result["requests"] == 1


@pytest.mark.parametrize("state", ["suspend", "preopen", "post_only", "UNKNOWN"])
def test_nontrading_native_states_are_retained_without_becoming_permission(native_instruments, state):
    case = native_instruments
    for row in case["rows"]:
        row["state" if case["client"].id == "okx" else "status"] = state
    p = collect(case)["payload"]
    assert all(row["active"] is False and row["native_state"] == state for row in p["observations"])
    assert p["economics_complete"] is p["native_admission_verified"] is False


@pytest.mark.parametrize("failure", ["exception", "empty", "api_error"])
def test_source_failures_are_redacted_without_cache_or_retry_fallback(native_instruments, monkeypatch, failure):
    case = native_instruments
    def failed(options):
        case["calls"].append(copy.deepcopy(options))
        if failure == "exception":
            raise RuntimeError("PRIVATE_INSTRUMENT_ERROR_DO_NOT_COPY")
        if case["client"].id == "okx":
            return {"code": "0" if failure == "empty" else "500", "data": [], "msg": "PRIVATE_INSTRUMENT_ERROR_DO_NOT_COPY"}
        return {"symbols": []} if failure == "empty" else {"code": -1, "msg": "PRIVATE_INSTRUMENT_ERROR_DO_NOT_COPY"}
    monkeypatch.setattr(case["client"], case["method"], failed)
    with pytest.raises(CChanException) as caught:
        collect(case)
    assert "PRIVATE_INSTRUMENT_ERROR" not in str(caught.value) and len(case["calls"]) == 1


def test_source_module_import_does_not_require_sdk_or_user_configuration():
    code = """
import importlib.abc, sys
attempted = []
class NoOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ccxt', 'Config', 'numpy', 'pandas', 'torch', 'xgboost', 'lightgbm', 'matplotlib'}:
            attempted.append(fullname)
            raise ImportError('not installed')
sys.meta_path.insert(0, NoOptional())
from Trade.NativeInstrumentEvidence import SCHEMA, collect_native_instrument_evidence, verify_native_instrument_evidence
assert SCHEMA == 'chan-native-instrument-evidence-v1'
assert callable(collect_native_instrument_evidence) and callable(verify_native_instrument_evidence)
assert not attempted, attempted
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stderr == b""


def test_mutation_or_schedule_times_remain_exact_unix_milliseconds(native_instruments):
    case = native_instruments
    case["rows"][0]["listTime" if case["client"].id == "okx" else "deliveryDate"] = "1800000000000.5"
    with pytest.raises(CChanException):
        collect(case)


def test_present_native_constraints_cannot_turn_missing_required_fields_into_unknown_limits(native_instruments):
    case = native_instruments
    if case["client"].id == "okx":
        del case["rows"][0]["upcChg"][0]["newValue"]
    else:
        del case["rows"][0]["filters"][1]["minQty"]
    with pytest.raises(CChanException):
        collect(case)


def test_route_changed_at_request_start_is_checked_before_any_get(native_instruments, monkeypatch):
    case, reads = native_instruments, []
    def clock():
        reads.append(1)
        if len(reads) == 2:
            route = "rest" if case["client"].id == "okx" else "fapiPublic"
            case["client"].urls["api"][route] = "https://different.invalid"
        return case["clock"]["now"]
    monkeypatch.setattr(case["api"], "utc_now_ms", clock)
    with pytest.raises(CChanException):
        collect(case)
    assert case["calls"] == []


def test_native_error_envelopes_cannot_be_hidden_by_residual_valid_rows(native_instruments, monkeypatch):
    case = native_instruments
    def error(options):
        response = case["public"](options)
        response["code"] = "1" if case["client"].id == "okx" else -1
        response["msg"] = "PRIVATE_NATIVE_ERROR_DO_NOT_COPY"
        return response
    monkeypatch.setattr(case["client"], case["method"], error)
    with pytest.raises(CChanException) as caught:
        collect(case)
    assert "PRIVATE_NATIVE_ERROR" not in str(caught.value) and len(case["calls"]) == 1
