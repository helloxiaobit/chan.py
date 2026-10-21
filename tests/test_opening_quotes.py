"""真实报价来源/时钟必须沿开仓边界保留；只 fake 外部 ticker I/O。"""
import copy
import hashlib
import json

import pytest

from Common.ChanException import CChanException
from CustomBuySellPoint.Decision import canonical_bytes
from DataAPI.SnapshotAPI.CCXTSnapshot import CCCXTSnapshot
from .test_opening_inputs import inputs, add_signal, bound_engine, explicit_open_conf
from .test_trade_cycle import cycle, CODES


NOW = 1_704_067_200_000
CODE = "ALPHA/USDT:USDT"
SOURCE = dict(exchange="binance", market_type="swap", settle="USDT", price_type="contract")


class CQuoteExchange:
    id = "binance"
    options = {"defaultType": "swap"}

    def __init__(self):
        self.ticker = dict(symbol=CODE, timestamp=NOW-100, datetime=None,
            high=101, low=99, bid=100.4, bidVolume=1, ask=100.6, askVolume=1,
            vwap=None, open=100, close=100.5, last=100.5, previousClose=100,
            change=0.5, percentage=0.5, average=100.25, baseVolume=100,
            quoteVolume=10000, info={"not_for_logs": "private-transport-text"})
        self.calls = []

    def fetch_tickers(self, codes):
        self.calls.append(list(codes))
        return {code: copy.deepcopy(self.ticker) for code in codes}


@pytest.fixture()
def quotes(monkeypatch):
    exchange = CQuoteExchange()
    monkeypatch.setattr(CCCXTSnapshot, "exchange", exchange)
    return exchange


def collect():
    return CCCXTSnapshot.query_quotes([CODE], now_ms=lambda: NOW)


def test_strict_quote_producer_preserves_actual_source_clock_and_owned_values(quotes):
    result = collect()
    assert result["schema"] == "chan-market-quotes-v1"
    payload = result["payload"]
    assert set(result) == {"schema", "payload", "payload_sha256"}
    assert result["payload_sha256"] == hashlib.sha256(canonical_bytes(payload)).hexdigest()
    assert payload == dict(source=SOURCE, started_ms=NOW, finished_ms=NOW,
        quotes=[dict(symbol=CODE, price=100.5, timestamp_ms=NOW-100)], clock_kind="exchange_ticker_timestamp")
    assert quotes.calls == [[CODE]] and "private-transport-text" not in str(result)
    quotes.ticker["last"] = 102
    assert payload["quotes"][0]["price"] == 100.5


@pytest.mark.parametrize("field,value", [("timestamp", None), ("timestamp", True), ("timestamp", float(NOW)),
    ("timestamp", NOW+1), ("symbol", "OTHER/USDT:USDT"), ("last", True), ("last", float("nan")),
    ("last", float("inf")), ("last", 0), ("last", -1)])
def test_strict_quote_never_replaces_bad_source_times_or_prices_with_now_or_last(quotes, field, value):
    quotes.ticker[field] = value
    with pytest.raises(CChanException):
        collect()


def test_transport_failure_is_redacted_without_printing_private_body(quotes, monkeypatch, capsys):
    def failed(codes):
        raise RuntimeError("api_key=DO_NOT_LOG secret=PRIVATE_BODY")
    monkeypatch.setattr(quotes, "fetch_tickers", failed)
    with pytest.raises(CChanException) as error:
        collect()
    assert "DO_NOT_LOG" not in str(error.value) and "PRIVATE_BODY" not in str(error.value)
    assert capsys.readouterr() == ("", "")


def test_source_mutation_during_public_request_is_not_a_fresh_same_market_quote(quotes, monkeypatch):
    original = quotes.fetch_tickers
    def changed(codes):
        result = original(codes)
        quotes.id = "okx"
        return result
    monkeypatch.setattr(quotes, "fetch_tickers", changed)
    with pytest.raises(CChanException):
        collect()


def test_quote_reader_revalidates_actual_age_not_a_precomputed_ready_boolean(quotes):
    from Common.MarketQuote import read_quote_batch
    original = collect()
    current = read_quote_batch(original, source=SOURCE, symbols=[CODE], now_ms=NOW, max_age_ms=100)
    assert current == original and current is not original
    current["payload"]["quotes"][0]["price"] = 1
    assert original["payload"]["quotes"][0]["price"] == 100.5
    with pytest.raises(CChanException):
        read_quote_batch(original, source=SOURCE, symbols=[CODE], now_ms=NOW+1, max_age_ms=100)


@pytest.mark.parametrize("damage", ["digest", "source", "symbol", "time", "future_receive", "extra", "missing", "policy_bool", "policy_zero"])
def test_quote_reader_rejects_resealed_wrong_context_or_malformed_evidence(quotes, damage):
    from Common.MarketQuote import read_quote_batch
    document = collect()
    policy = 1000
    if damage == "digest":
        document["payload_sha256"] = "0"*64
    else:
        if damage == "source":
            document["payload"]["source"]["exchange"] = "okx"
        elif damage == "symbol":
            document["payload"]["quotes"][0]["symbol"] = "OTHER/USDT:USDT"
        elif damage == "time":
            document["payload"]["quotes"][0]["timestamp_ms"] = True
        elif damage == "future_receive":
            document["payload"]["finished_ms"] = NOW+1
        elif damage == "extra":
            document["payload"]["ready"] = True
        elif damage == "missing":
            document["payload"]["quotes"] = []
        else:
            policy = True if damage == "policy_bool" else 0
        document["payload_sha256"] = hashlib.sha256(canonical_bytes(document["payload"])).hexdigest()
    with pytest.raises(CChanException):
        read_quote_batch(document, source=SOURCE, symbols=[CODE], now_ms=NOW, max_age_ms=policy)


def guard_batch(guard, monkeypatch, *, price=100.5):
    exchange = CQuoteExchange()
    exchange.id = guard.scope["source"]["exchange"]
    def tickers(codes):
        return {code: {**copy.deepcopy(exchange.ticker), "symbol": code, "last": price,
            "timestamp": guard.now_ms()-100} for code in codes}
    monkeypatch.setattr(exchange, "fetch_tickers", tickers)
    monkeypatch.setattr(CCCXTSnapshot, "exchange", exchange)
    return CCCXTSnapshot.query_quotes(guard.scope["code_list"], now_ms=guard.now_ms)


def test_actual_guarded_intent_keeps_original_quote_batch_and_policy_in_the_journal(inputs, cycle, monkeypatch):
    guard, db = inputs
    batch = guard_batch(guard, monkeypatch)
    prices = guard.bind_quotes(batch, max_age_ms=1000)
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    opened = engine.add_trade(record, prices[CODES[0]])
    assert opened.filled > 0 and engine.exchange is None
    stamp = json.loads(db.get_record(record["id"])["snapshot_before"])["opening_inputs"]
    assert stamp["schema"] == "chan-opening-input-check-v2" and stamp["native_admission_verified"] is False
    assert stamp["quote"] == {"batch": batch, "max_age_ms": 1000}
    assert db.get_order_history(record["id"])["attempts"][0]["identity"]["opening_inputs"] == stamp
    batch["payload"]["quotes"][0]["price"] = 1
    assert guard.check(record, engine=engine)["quote"] == stamp["quote"]


@pytest.mark.parametrize("stage", ["before_intent", "after_intent", "after_claim"])
def test_expired_quote_blocks_each_real_open_boundary_without_resubmission(inputs, cycle, monkeypatch, stage):
    guard, db = inputs
    clock = {"now": guard.now_ms()}
    guard.now_ms = lambda: clock["now"]
    guard.bind_quotes(guard_batch(guard, monkeypatch), max_age_ms=1000)
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    def expire():
        clock["now"] += 1001
    if stage == "before_intent":
        expire()
    elif stage == "after_intent":
        monkeypatch.setattr(engine, "rate_limit", expire)
    else:
        original = db.claim_order_submission
        def claim(*args, **kwargs):
            result = original(*args, **kwargs)
            expire()
            return result
        monkeypatch.setattr(db, "claim_order_submission", claim)
    with pytest.raises(CChanException):
        engine.add_trade(record, 100.5)
    current = db.get_record(record["id"])
    assert current["current_qty"] == 0 and engine.sim_state.orders == {}
    assert current["open_attempt"] == (0 if stage == "before_intent" else 1)
    if stage != "before_intent":
        assert current["open_order_status"] == ("created" if stage == "after_intent" else "submitting")
        engine.restore()
        assert db.get_record(record["id"])["open_attempt"] == 1 and engine.sim_state.orders == {}


def test_finite_but_different_opening_price_is_not_the_observed_quote(inputs, cycle, monkeypatch):
    guard, db = inputs
    guard.bind_quotes(guard_batch(guard, monkeypatch), max_age_ms=1000)
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    with pytest.raises(CChanException):
        engine.add_trade(record, 101)
    assert db.get_record(record["id"])["open_attempt"] == 0 and engine.sim_state.orders == {}


def test_quote_observation_is_write_once_and_fresh_reader_cannot_relabel_old_intent(inputs, cycle, monkeypatch):
    import json
    from Trade.Script.OpeningInputs import COpeningInputs
    guard, db = inputs
    batch = guard_batch(guard, monkeypatch)
    guard.bind_quotes(batch, max_age_ms=1000)
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    original = guard.check(record, engine=engine)
    client = engine.make_client_order_id(record, "open")
    assert db.acquire_open_intent(record["id"], 0.03, client, position_side="BOTH",
        snapshot={"price": 100.5, "opening_inputs": original})
    newer = guard_batch(guard, monkeypatch, price=101)
    with pytest.raises(CChanException):
        guard.bind_quotes(newer, max_age_ms=1000)
    fresh = COpeningInputs(cycle[0], now_ms=guard.now_ms)
    fresh.bind_quotes(newer, max_age_ms=1000)
    engine.opening_inputs = fresh
    with pytest.raises(CChanException):
        engine.place_order(CODES[0], True, 0.03, 100.5, client_order_id=client, position_side="BOTH")
    assert json.loads(db.get_record(record["id"])["snapshot_before"])["opening_inputs"] == original
    assert db.get_record(record["id"])["open_order_status"] == "created" and engine.sim_state.orders == {}


def test_old_quoted_order_query_cancel_and_reduce_survive_expiration(inputs, cycle, monkeypatch):
    guard, db = inputs
    clock = {"now": guard.now_ms()}
    guard.now_ms = lambda: clock["now"]
    guard.bind_quotes(guard_batch(guard, monkeypatch), max_age_ms=1000)
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    opened = engine.add_trade(record, 100.5)
    clock["now"] += 1001
    assert engine.query_order(CODES[0], opened.order_id).filled == opened.filled
    assert engine.cancel_order(CODES[0], opened.order_id)
    closed = engine.cover_trade(db.get_record(record["id"]), 100.4, "reduce old risk")
    assert closed.filled > 0 and db.get_record(record["id"])["current_qty"] == 0


def test_quote_bound_make_open_cannot_substitute_a_different_price_map(inputs, cycle, monkeypatch):
    from Trade.Script.MakeOpenTrade import make_open_trade
    guard, db = inputs
    guard.bind_quotes(guard_batch(guard, monkeypatch), max_age_ms=1000)
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    failures = []
    assert make_open_trade(db, engine, explicit_open_conf(cycle), price_map={CODES[0]: 101}, failures=failures) == []
    assert failures and db.get_record(record["id"])["open_attempt"] == 0 and engine.sim_state.orders == {}


def configure_cli(inputs, cycle, monkeypatch, *, policy=1000, snapshot_engine="ccxt"):
    import yaml
    from Config.EnvConfig import CEnv
    from Trade.Script import MakeOpenTrade as module
    from Trade.Script.OpeningInputs import COpeningInputs
    _, db = inputs
    cycle[2]["snapshot_engine"] = snapshot_engine
    if policy is not None:
        cycle[2]["trade"]["quote_max_age_ms"] = policy
    cycle[0].write_text(yaml.safe_dump(cycle[2]), encoding="utf-8")
    CEnv.reset_instance()
    now = inputs[0].now_ms()
    guard = COpeningInputs(cycle[0], now_ms=lambda: now)
    monkeypatch.setenv("CHANPY_CYCLE_ID", "1"*32)
    for key, value in guard.snapshot().items():
        monkeypatch.setenv("CHANPY_CYCLE_"+key.upper(), value)
    monkeypatch.setattr(module, "utc_now_ms", lambda: now)
    conf = explicit_open_conf(cycle)
    monkeypatch.setattr(module, "COpenConfig", lambda: conf)
    monkeypatch.setattr(module, "get_price_map", lambda codes: {code: 100.5 for code in codes})
    guard_batch(guard, monkeypatch)
    return module, db


def test_default_cli_uses_strict_actual_quote_batch_not_the_legacy_float_reader(inputs, cycle, monkeypatch):
    module, db = configure_cli(inputs, cycle, monkeypatch)
    record = add_signal(db)
    monkeypatch.setattr(module, "get_price_map", lambda codes: pytest.fail("bare price must not reach configured new risk"))
    assert module.main() == 0
    current = db.get_record(record["id"])
    assert current["current_qty"] > 0
    proof = json.loads(current["snapshot_before"])["opening_inputs"]
    assert proof["schema"] == "chan-opening-input-check-v2"
    assert proof["quote"]["batch"]["payload"]["source"] == SOURCE
    assert proof["quote"]["max_age_ms"] == 1000
    assert db.get_order_history(record["id"])["attempts"][0]["identity"]["opening_inputs"] == proof


@pytest.mark.parametrize("policy", [None, True, 0, -1, "1000"])
def test_default_cli_missing_or_invalid_explicit_age_policy_never_opens(inputs, cycle, monkeypatch, policy):
    module, db = configure_cli(inputs, cycle, monkeypatch, policy=policy)
    record = add_signal(db)
    assert module.main() != 0
    assert db.get_record(record["id"])["open_attempt"] == 0


def test_default_crypto_cli_never_uses_an_unscoped_stock_snapshot_provider(inputs, cycle, monkeypatch):
    module, db = configure_cli(inputs, cycle, monkeypatch, snapshot_engine="sina")
    record = add_signal(db)
    assert module.main() != 0
    assert db.get_record(record["id"])["open_attempt"] == 0


def test_default_cli_with_no_eligible_signal_does_not_need_or_fetch_new_risk_quotes(inputs, cycle, monkeypatch):
    module, db = configure_cli(inputs, cycle, monkeypatch, policy=None)
    monkeypatch.setattr(CCCXTSnapshot, "query_quotes", lambda *a, **k: pytest.fail("no new risk means no quote I/O"))
    assert module.main() == 0


def test_quote_age_policy_cannot_be_enlarged_outside_the_frozen_configuration(inputs, cycle, monkeypatch):
    from Trade.Script.OpeningInputs import COpeningInputs
    configure_cli(inputs, cycle, monkeypatch, policy=1000)
    guard = COpeningInputs(cycle[0], now_ms=inputs[0].now_ms, require_quotes=True)
    with pytest.raises(CChanException):
        guard.bind_quotes(guard_batch(guard, monkeypatch), max_age_ms=2000)


def test_quote_expiring_inside_the_final_input_scan_never_reaches_the_server(inputs, cycle, monkeypatch):
    guard, db = inputs
    clock = {"now": guard.now_ms()}
    guard.now_ms = lambda: clock["now"]
    guard.bind_quotes(guard_batch(guard, monkeypatch), max_age_ms=1000)
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    original = guard.assert_current
    scanned = []
    def scan():
        result = original()
        scanned.append(True)
        if len(scanned) == 5:  # actual legacy-sim post-claim, immediately before send
            clock["now"] += 1001
        return result
    monkeypatch.setattr(guard, "assert_current", scan)
    with pytest.raises(CChanException):
        engine.add_trade(record, 100.5)
    assert len(scanned) == 5 and engine.sim_state.orders == {}
    assert db.get_record(record["id"])["open_order_status"] == "submitting"


@pytest.mark.parametrize("remove_quote", [False, True])
def test_malformed_quote_check_version_is_a_closed_history_error_not_a_raw_type_error(inputs, cycle, monkeypatch, remove_quote):
    guard, db = inputs
    guard.bind_quotes(guard_batch(guard, monkeypatch), max_age_ms=1000)
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    engine.add_trade(record, 100.5)
    snapshot = json.loads(db.get_record(record["id"])["snapshot_before"])
    snapshot["opening_inputs"]["schema"] = []
    if remove_quote:
        del snapshot["opening_inputs"]["quote"]
    db.db.execute("UPDATE chan_trade SET snapshot_before=? WHERE id=?", (json.dumps(snapshot), record["id"]))
    with pytest.raises(CChanException):
        db.get_order_history(record["id"])


@pytest.mark.parametrize("field,value", [("lv", "K_4H"), ("bstype", "other")])
def test_quoted_history_still_requires_the_original_signal_level(inputs, cycle, monkeypatch, field, value):
    guard, db = inputs
    guard.bind_quotes(guard_batch(guard, monkeypatch), max_age_ms=1000)
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    engine.add_trade(record, 100.5)
    db.db.execute(f"UPDATE chan_trade SET {field}=? WHERE id=?", (value, record["id"]))
    with pytest.raises(CChanException):
        db.get_order_history(record["id"])


@pytest.mark.parametrize("phase", ["fill", "before_claim", "after_claim"])
def test_full_paper_uses_quote_proof_without_turning_ticker_into_mark_or_reopening_old_intents(inputs, cycle, monkeypatch, phase):
    from ModelStrategy.parameterEvaluate.crypto_account import CCryptoAccountConfig
    from Trade.LinearPaperAccount import CLinearPaperAccount
    from Trade.Script.MakeOpenTrade import make_open_trade
    guard, db = inputs
    clock = {"now": guard.now_ms()}
    guard.now_ms = lambda: clock["now"]
    paper = CLinearPaperAccount(CCryptoAccountConfig(initial_equity="1000", leverage="3", taker_fee="0.001",
        taker_slippage="0.001"), position_mode="one_way", start_ms=clock["now"], identity_seed="quoted-opening",
        markets=[dict(exchange="binance", id="ALPHAUSDT", symbol=CODES[0], type="swap", base="ALPHA", quote="USDT",
            settle="USDT", contractSize="0.01", amount_step="1", price_tick="0.1", min_notional="1")])
    guard.bind_quotes(guard_batch(guard, monkeypatch), max_age_ms=1000)
    engine = bound_engine(inputs, cycle, paper=paper)
    engine.set_sim_quote(CODES[0], at_ms=clock["now"], bid="99.9", ask="100", mark_price="100")
    record = add_signal(db)
    if phase == "before_claim":
        original = engine._read_paper_contract
        def read_contract(*args, **kwargs):
            result = original(*args, **kwargs)
            clock["now"] += 1001
            return result
        monkeypatch.setattr(engine, "_read_paper_contract", read_contract)
    elif phase == "after_claim":
        original = db.claim_order_submission
        def claim(*args, **kwargs):
            result = original(*args, **kwargs)
            clock["now"] += 1001
            return result
        monkeypatch.setattr(db, "claim_order_submission", claim)
    failures = []
    opened = make_open_trade(db, engine, explicit_open_conf(cycle), price_map={CODES[0]: 100.5}, failures=failures)
    current = db.get_record(record["id"])
    if phase == "fill":
        assert opened == [record["id"]] and failures == [] and current["current_qty"] == 0.03
        assert engine.get_sim_account_report()["account"]["snapshot"]["fees"] == "0.003003"
        assert json.loads(current["snapshot_before"])["opening_inputs"]["schema"] == "chan-opening-input-check-v2"
    else:
        assert opened == [] and failures and current["current_qty"] == 0
        assert current["open_order_status"] == ("created" if phase == "before_claim" else "submitting")
        assert engine.get_sim_account_report()["account"]["snapshot"]["fees"] == "0"
        assert engine.sim_state.orders == {}
    assert engine.exchange is None


@pytest.mark.parametrize("venue", ["binance", "okx"])
@pytest.mark.parametrize("expire_after_claim", [False, True])
def test_actual_native_parameter_builder_uses_quoted_intent_and_rechecks_before_fake_send(inputs, cycle, monkeypatch, tmp_path, venue, expire_after_claim):
    import yaml
    from Config.EnvConfig import CEnv
    from Common.CEnum import KL_TYPE
    from Common.KLineTime import make_crypto_klu
    from CustomBuySellPoint.Signal import CSignal
    from OfflineData.offline_data_util import CKLineDB
    from Trade.CCXTTradeEngine import CCCXTTradeEngine
    from Trade.OpenQuotaGen import CBenchPriceQuotaGen
    from Trade.Script.OpeningInputs import COpeningInputs
    from .test_crypto_venue_parameters import CVenueExchange
    from .test_crypto_order_contract import market
    from .test_trade_safety import enabled_trade_conf, write_candidate_receipt
    _, db = inputs
    source = {**SOURCE, "exchange": venue}
    new_market = tmp_path/(venue+"-market.db")
    with CKLineDB(cycle[2]["offline_data"]["sqlite_path"], read_only=True) as old, CKLineDB(str(new_market)) as fresh:
        fresh.bind_source(source)
        for code in CODES:
            for level in (KL_TYPE.K_4H, KL_TYPE.K_60M):
                fresh.upsert_klines(code, level, old.query_klines(code, level))
    cycle[2]["offline_data"].update(sqlite_path=str(new_market), source_identity=source)
    cycle[2]["ccxt"].update(exchange=venue, mode="testnet", testnet=True, api_key="fake-key", secret="fake-secret",
        position_mode="one_way", margin_mode="cross", leverage=3)
    cycle[2]["trade"].update(enabled_trade_conf(write_candidate_receipt(tmp_path)))
    cycle[0].write_text(yaml.safe_dump(cycle[2]), encoding="utf-8")
    CEnv.reset_instance()
    clock = {"now": inputs[0].now_ms()}
    guard = COpeningInputs(cycle[0], now_ms=lambda: clock["now"])
    guard.bind_quotes(guard_batch(guard, monkeypatch), max_age_ms=1000)
    exchange = CVenueExchange(venue)
    definition = market()
    definition.update(symbol=CODES[0], base="ALPHA", baseId="ALPHA", quoteId="USDT", settleId="USDT",
        id="ALPHAUSDT" if venue == "binance" else "ALPHA-USDT-SWAP",
        info={"orderTypes": ["LIMIT", "MARKET", "LIMIT_MAKER"]})
    exchange.set_markets([definition])
    exchange.builder.set_markets([definition])
    exchange.fill, exchange.status = 3, "closed"
    engine = CCCXTTradeEngine(db, quota_gen=CBenchPriceQuotaGen(3.7), ccxt_conf=cycle[2]["ccxt"],
        trade_conf=cycle[2]["trade"], opening_inputs=guard, environ={"CHANPY_ENABLE_TESTNET": "YES"}, push_msg=False)
    engine.exchange, engine.api_interval = exchange, 0
    hour = 3_600_000
    unit = make_crypto_klu([clock["now"]-hour, 100, 101, 99, 100, 1], KL_TYPE.K_60M, clock["now"])
    unit.source_identity = source
    signal = CSignal(CODES[0], KL_TYPE.K_60M, True, "1", unit, 100, sl_thred=90, target_klu_time=unit.time)
    signal.freeze_decision()
    record = db.get_record(db.add_signal(signal))
    if expire_after_claim:
        original = db.claim_order_submission
        def claim(*args, **kwargs):
            result = original(*args, **kwargs)
            clock["now"] += 1001
            return result
        monkeypatch.setattr(db, "claim_order_submission", claim)
        with pytest.raises(CChanException):
            engine.add_trade(record, 100.5)
        assert exchange.created == [] and exchange.native_requests == []
        assert db.get_record(record["id"])["open_order_status"] == "submitting"
    else:
        result = engine.add_trade(record, 100.5)
        assert result.filled == 0.03 and len(exchange.native_requests) == 1
        current = db.get_record(record["id"])
        proof = json.loads(current["snapshot_before"])["opening_inputs"]
        assert proof["quote"]["batch"]["payload"]["source"] == source
        assert proof["native_admission_verified"] is False
        assert db.get_order_history(record["id"])["attempts"][0]["identity"]["opening_inputs"] == proof
