"""每笔开仓复查真实输入；不连接行情或账户端点。"""
import json

import pytest

from Common.CEnum import KL_TYPE
from Common.ChanException import CChanException
from Common.KLineTime import make_crypto_klu
from CustomBuySellPoint.Signal import CSignal
from CustomBuySellPoint.Decision import make_decision, read_decision
from OfflineData.offline_data_util import CKLineDB
from Trade.db_util import CChanDB
from Trade.Script.OpeningInputs import COpeningInputs, inspect_opening_inputs
from .test_trade_cycle import cycle, CODES, HOUR, NOW, SOURCE


@pytest.fixture()
def inputs(cycle, monkeypatch):
    from Config.EnvConfig import CEnv
    monkeypatch.setenv("CHANPY_CONFIG", str(cycle[0]))
    CEnv.reset_instance()
    db = CChanDB(db_conf=cycle[2]["db"])
    try:
        yield COpeningInputs(cycle[0], now_ms=lambda: NOW), db
    finally:
        db.close()
        CEnv.reset_instance()


def add_signal(db, *, code=CODES[0], level=KL_TYPE.K_60M):
    interval = 4*HOUR if level == KL_TYPE.K_4H else HOUR
    unit = make_crypto_klu([NOW-interval, 100, 101, 99, 100, 1], level, NOW)
    unit.source_identity = SOURCE
    signal = CSignal(code, level, True, "1", unit, 100, sl_thred=90, target_klu_time=unit.time)
    signal.freeze_decision()
    return db.get_record(db.add_signal(signal))


def test_actual_closed_rows_and_frozen_signal_produce_only_an_input_check(inputs):
    guard, db = inputs
    record = add_signal(db)
    result = guard.check(record)
    assert result["schema"] == "chan-opening-input-check-v1"
    assert result["signal_event_id"] == read_decision(record["signal_decision"].encode())["event_id"]
    assert result["checked_at_ms"] == NOW and result["native_admission_verified"] is False
    assert result["inputs_sha256"] == guard.snapshot()["inputs_sha256"]
    modified = guard.snapshot()
    modified["inputs_sha256"] = "0"*64
    assert guard.check(record)["inputs_sha256"] != modified["inputs_sha256"]


@pytest.mark.parametrize("damage", ["gap", "revision", "source", "config"])
def test_later_input_mutation_never_reuses_an_earlier_success(inputs, cycle, damage):
    guard, db = inputs
    record = add_signal(db)
    guard.check(record)
    if damage == "config":
        cycle[0].write_text(cycle[0].read_text()+"\n# changed\n")
    else:
        with CKLineDB(cycle[2]["offline_data"]["sqlite_path"]) as market:
            if damage == "source":
                market.conn.execute("UPDATE kline_source SET payload=?", (json.dumps({**SOURCE, "exchange": "okx"}),))
            elif damage == "gap":
                market.conn.execute("DELETE FROM kline WHERE symbol=? AND lv='K_60M' AND ts=?", (CODES[1], 2*HOUR))
            else:
                market.conn.execute("UPDATE kline SET v=9 WHERE symbol=? AND lv='K_60M' AND ts=?", (CODES[0], 2*HOUR))
            market.conn.commit()
    with pytest.raises(CChanException):
        guard.check(record)


def test_child_cannot_replace_the_parent_input_epoch_with_a_new_valid_one(inputs, cycle):
    guard, db = inputs
    expected = guard.snapshot()
    with CKLineDB(cycle[2]["offline_data"]["sqlite_path"]) as market:
        market.conn.execute("UPDATE kline SET v=9 WHERE symbol=? AND lv='K_60M' AND ts=?", (CODES[0], HOUR))
        market.conn.commit()
    with pytest.raises(CChanException):
        COpeningInputs(cycle[0], expected=expected, now_ms=lambda: NOW)


@pytest.mark.parametrize("field,value", [("stock_code", "OTHER/USDT:USDT"), ("lv", "K_4H"),
    ("is_buy", 0), ("open_thred", 101), ("sl_thred", 95), ("deployment_id", "another-model"),
    ("signal_decision", None)])
def test_signal_projection_cannot_drift_or_silently_downgrade_model_identity(inputs, field, value):
    guard, db = inputs
    record = add_signal(db)
    record[field] = value
    with pytest.raises(CChanException):
        guard.check(record)


def test_resealed_signal_bar_is_compared_to_actual_source_not_to_its_own_hash(inputs):
    guard, db = inputs
    record = add_signal(db)
    body = read_decision(record["signal_decision"].encode())
    body["payload"]["bar"]["close"] = 100.25
    record["signal_decision"] = make_decision(body["identity"], body["payload"]).decode()
    with pytest.raises(CChanException):
        guard.check(record)


def test_readonly_observation_binds_volume_even_when_quality_and_prices_are_unchanged(cycle):
    from Config.EnvConfig import CEnv
    env = CEnv(str(cycle[0]))
    first = inspect_opening_inputs(env, now_ms=NOW)
    with CKLineDB(cycle[2]["offline_data"]["sqlite_path"]) as market:
        market.conn.execute("UPDATE kline SET v=7 WHERE symbol=? AND lv='K_60M' AND ts=?", (CODES[1], HOUR))
        market.conn.commit()
    second = inspect_opening_inputs(env, now_ms=NOW)
    assert first["quality"] == second["quality"]
    assert first["inputs_sha256"] != second["inputs_sha256"]


def bound_engine(inputs, cycle, *, paper=None):
    from Trade.CCXTTradeEngine import CCCXTTradeEngine, CSimExchangeState
    from Trade.OpenQuotaGen import CBenchPriceQuotaGen
    guard, db = inputs
    result = CCCXTTradeEngine(db, quota_gen=CBenchPriceQuotaGen(3.7), ccxt_conf=cycle[2]["ccxt"],
        trade_conf=cycle[2]["trade"], environ={}, push_msg=False, opening_inputs=guard,
        sim_state=None if paper is None else CSimExchangeState(paper_account=paper))
    result.api_interval = 0
    return result


def damage_market(cycle):
    with CKLineDB(cycle[2]["offline_data"]["sqlite_path"]) as market:
        market.conn.execute("DELETE FROM kline WHERE symbol=? AND lv='K_60M' AND ts=?", (CODES[1], HOUR))
        market.conn.commit()


def test_actual_intent_freezes_the_selected_input_check_in_original_journal_identity(inputs, cycle):
    guard, db = inputs
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    result = engine.add_trade(record, 100.5)
    assert result.filled > 0
    stamp = json.loads(db.get_record(record["id"])["snapshot_before"])["opening_inputs"]
    assert stamp["inputs_sha256"] == guard.snapshot()["inputs_sha256"]
    assert db.get_order_history(record["id"])["attempts"][0]["identity"]["opening_inputs"] == stamp
    current = json.loads(db.get_record(record["id"])["snapshot_before"])
    current["opening_inputs"]["inputs_sha256"] = "0"*64
    db.db.execute("UPDATE chan_trade SET snapshot_before=? WHERE id=?", (json.dumps(current), record["id"]))
    with pytest.raises(CChanException):
        db.get_order_history(record["id"])


def test_input_loss_during_prepare_is_rechecked_before_intent_acquisition(inputs, cycle, monkeypatch):
    guard, db = inputs
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    original = engine.prepare_order
    def prepare(*args, **kwargs):
        result = original(*args, **kwargs)
        damage_market(cycle)
        return result
    monkeypatch.setattr(engine, "prepare_order", prepare)
    with pytest.raises(CChanException):
        engine.add_trade(record, 100.5)
    assert db.get_record(record["id"])["open_attempt"] == 0
    assert engine.sim_state.orders == {}


def test_input_loss_after_intent_does_not_send_or_reset_and_restore_does_not_resubmit(inputs, cycle, monkeypatch):
    guard, db = inputs
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    monkeypatch.setattr(engine, "rate_limit", lambda: damage_market(cycle))
    with pytest.raises(CChanException):
        engine.add_trade(record, 100.5)
    current = db.get_record(record["id"])
    assert current["open_attempt"] == 1 and current["open_order_status"] == "created"
    assert current["current_qty"] == 0 and engine.sim_state.orders == {}
    engine.restore()
    assert db.get_record(record["id"])["open_attempt"] == 1 and engine.sim_state.orders == {}


def test_input_guard_is_bound_to_the_actual_trade_database_and_engine_source(inputs, cycle):
    guard, db = inputs
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    engine.ccxt_conf = {**engine.ccxt_conf, "exchange": "okx"}
    with pytest.raises(CChanException):
        engine.add_trade(record, 100.5)
    assert db.get_record(record["id"])["open_attempt"] == 0


def test_original_query_cancel_and_reduce_do_not_depend_on_new_opening_inputs(inputs, cycle):
    guard, db = inputs
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    opened = engine.add_trade(record, 100.5)
    damage_market(cycle)
    assert engine.query_order(CODES[0], opened.order_id).filled == opened.filled
    assert engine.cancel_order(CODES[0], opened.order_id)
    result = engine.cover_trade(db.get_record(record["id"]), 100.6, "reduce existing risk")
    assert result.filled > 0 and db.get_record(record["id"])["current_qty"] == 0


def explicit_open_conf(cycle):
    from Trade.Script.OpenConfig import COpenConfig
    path = cycle[0].with_name("open-config.json")
    path.write_text("{}")
    return COpenConfig(str(path))


def test_actual_make_open_function_reports_input_failure_instead_of_successful_empty_result(inputs, cycle):
    from Trade.Script.MakeOpenTrade import make_open_trade
    guard, db = inputs
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    damage_market(cycle)
    failures = []
    assert make_open_trade(db, engine, open_conf=explicit_open_conf(cycle), price_map={CODES[0]: 100.5}, failures=failures) == []
    assert failures and db.get_record(record["id"])["open_attempt"] == 0
    assert engine.sim_state.orders == {}


@pytest.mark.parametrize("price", [None, True, float("nan"), float("inf"), -1])
def test_configured_missing_or_nonfinite_quote_is_an_input_failure_before_intent(inputs, cycle, price):
    from Trade.Script.MakeOpenTrade import make_open_trade
    guard, db = inputs
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    failures = []
    assert make_open_trade(db, engine, open_conf=explicit_open_conf(cycle), price_map={CODES[0]: price}, failures=failures) == []
    assert failures and db.get_record(record["id"])["open_attempt"] == 0


def test_full_paper_can_use_actual_make_open_without_fabricating_its_mark_quote(inputs, cycle):
    from ModelStrategy.parameterEvaluate.crypto_account import CCryptoAccountConfig
    from Trade.LinearPaperAccount import CLinearPaperAccount
    from Trade.Script.MakeOpenTrade import make_open_trade
    paper = CLinearPaperAccount(CCryptoAccountConfig(initial_equity="1000", leverage="3", taker_fee="0.001",
        taker_slippage="0.001"), position_mode="one_way", start_ms=NOW, identity_seed="opening-inputs",
        markets=[dict(exchange="binance", id="ALPHAUSDT", symbol=CODES[0], type="swap", base="ALPHA", quote="USDT",
            settle="USDT", contractSize="0.01", amount_step="1", price_tick="0.1", min_notional="1")])
    guard, db = inputs
    engine = bound_engine(inputs, cycle, paper=paper)
    engine.set_sim_quote(CODES[0], at_ms=NOW, bid="99.9", ask="100", mark_price="100")
    record = add_signal(db)
    failures = []
    assert make_open_trade(db, engine, open_conf=explicit_open_conf(cycle), price_map={CODES[0]: 100.5}, failures=failures) == [record["id"]]
    assert failures == [] and db.get_record(record["id"])["current_qty"] == 0.03
    report = engine.get_sim_account_report()
    assert report["account"]["snapshot"]["fees"] == "0.003003"
    assert engine.exchange is None


def test_default_opening_cli_uses_parent_epoch_and_configured_notional(inputs, cycle, monkeypatch):
    import yaml
    from Trade.Script import MakeOpenTrade as module
    guard, db = inputs
    cycle[2]["trade"].update(bench_price=7, quote_max_age_ms=1000)
    cycle[2]["snapshot_engine"] = "ccxt"
    cycle[0].write_text(yaml.safe_dump(cycle[2]), encoding="utf-8")
    from Config.EnvConfig import CEnv
    CEnv.reset_instance()
    guard = COpeningInputs(cycle[0], now_ms=lambda: NOW)
    monkeypatch.setenv("CHANPY_CYCLE_ID", "1"*32)
    for key, value in guard.snapshot().items():
        monkeypatch.setenv("CHANPY_CYCLE_"+key.upper(), value)
    monkeypatch.setattr(module, "utc_now_ms", lambda: NOW)
    conf = explicit_open_conf(cycle)
    monkeypatch.setattr(module, "COpenConfig", lambda: conf)
    from DataAPI.SnapshotAPI.CCXTSnapshot import CCCXTSnapshot
    class CQuoteTransport:
        id = "binance"
        options = {"defaultType": "swap"}
        def fetch_tickers(self, codes):
            return {code: {"symbol": code, "last": 100.5, "timestamp": NOW-100} for code in codes}
    monkeypatch.setattr(CCCXTSnapshot, "exchange", CQuoteTransport())
    record = add_signal(db)
    assert module.main() == 0
    current = db.get_record(record["id"])
    assert current["current_qty"] == pytest.approx(7/100.5)
    assert json.loads(current["snapshot_before"])["opening_inputs"]["inputs_sha256"] == guard.snapshot()["inputs_sha256"]


def test_default_opening_cli_cannot_run_with_missing_parent_input_metadata(inputs, monkeypatch):
    from Trade.Script import MakeOpenTrade as module
    for key in ("ID", "CONFIG_SHA256", "SCOPE_SHA256", "INPUTS_SHA256"):
        monkeypatch.delenv("CHANPY_CYCLE_"+key, raising=False)
    monkeypatch.setattr(module, "get_price_map", lambda codes: pytest.fail("missing epoch must fail before quote I/O"))
    assert module.main() != 0


def test_public_configuration_view_does_not_mutate_the_guard_epoch(inputs):
    guard, db = inputs
    record = add_signal(db)
    view = guard.env
    view.conf["trade"]["code_list"] = ["OTHER/USDT:USDT"]
    assert guard.check(record)["inputs_sha256"] == guard.snapshot()["inputs_sha256"]


def test_input_loss_after_submission_claim_leaves_unknown_without_server_order(inputs, cycle, monkeypatch):
    guard, db = inputs
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    original = db.claim_order_submission
    def claim(*args, **kwargs):
        result = original(*args, **kwargs)
        damage_market(cycle)
        return result
    monkeypatch.setattr(db, "claim_order_submission", claim)
    with pytest.raises(CChanException):
        engine.add_trade(record, 100.5)
    assert db.get_record(record["id"])["open_order_status"] == "submitting"
    assert engine.sim_state.orders == {}


def test_input_observer_code_identity_cannot_go_missing_after_freeze(inputs, monkeypatch, tmp_path):
    from Trade.Script import OpeningInputs as module
    guard, db = inputs
    record = add_signal(db)
    monkeypatch.setattr(module, "__file__", str(tmp_path/"missing"/"Trade"/"Script"/"OpeningInputs.py"))
    with pytest.raises(CChanException):
        guard.check(record)


def test_duplicate_sql_signal_is_not_success_when_frozen_decision_payload_changed(inputs, monkeypatch):
    from Chan import CChan
    from ChanConfig import CChanConfig
    from Trade.Script import SignalMonitor as module
    from .test_decision_snapshots import CDecisionStrategy, START
    guard, db = inputs
    threshold = {"value": 105}
    base_signals = CDecisionStrategy.bsp_signal
    def signals(self, chan, lv):
        result = base_signals(self, chan, lv)
        for signal in result:
            signal.open_thred = threshold["value"]
        return result
    monkeypatch.setattr(CDecisionStrategy, "bsp_signal", signals)
    def build(*args, **kwargs):
        chan = CChan(CODES[0], lv_list=[KL_TYPE.K_60M], config=CChanConfig({
            "trigger_step": True, "cbsp_strategy": CDecisionStrategy, "strategy_para": {"skip_features": True}}))
        unit = make_crypto_klu([START, 100, 101, 99, 100, 1], KL_TYPE.K_60M, START+HOUR)
        unit.source_identity = SOURCE
        chan.trigger_load({KL_TYPE.K_60M: [unit]})
        return chan
    monkeypatch.setattr(module, "CChan", build)
    def run_monitor():
        return module.run_signal_monitor(db, code_list=[CODES[0]], lv_list=[KL_TYPE.K_60M], push=False)
    assert run_monitor()["added"] == 1
    old = db.get_watching_signals(CODES[0])[0]
    assert run_monitor()["existed"] == 1
    threshold["value"] = 106
    result = run_monitor()
    assert result["failed"] == 1 and result["existed"] == 0
    assert db.get_record(old["id"]) == old


@pytest.mark.parametrize("changed", ["quantity", "direction", "price", "leg"])
def test_guarded_low_level_simulation_cannot_submit_a_different_request_for_an_original_intent(inputs, cycle, changed):
    guard, db = inputs
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    client = engine.make_client_order_id(record, "open")
    check = guard.check(record, engine=engine)
    assert db.acquire_open_intent(record["id"], 0.03, client, position_side="BOTH",
        snapshot={"price": 100.5, "opening_inputs": check})
    quantity, buy, price, leg = 0.03, True, 100.5, "BOTH"
    if changed == "quantity":
        quantity = 0.04
    elif changed == "direction":
        buy = False
    elif changed == "price":
        price = 101
    else:
        leg = "LONG"
    with pytest.raises(CChanException):
        engine.place_order(CODES[0], buy, quantity, price, client_order_id=client, position_side=leg)
    assert db.get_record(record["id"])["open_order_status"] == "created" and engine.sim_state.orders == {}


def test_fresh_guard_does_not_relabel_an_old_intent_with_new_valid_input_epoch(inputs, cycle):
    guard, db = inputs
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    client = engine.make_client_order_id(record, "open")
    assert db.acquire_open_intent(record["id"], 0.03, client, position_side="BOTH",
        snapshot={"price": 100.5, "opening_inputs": guard.check(record, engine=engine)})
    with CKLineDB(cycle[2]["offline_data"]["sqlite_path"]) as market:
        market.conn.execute("UPDATE kline SET v=8 WHERE symbol=? AND lv='K_60M' AND ts=?", (CODES[1], HOUR))
        market.conn.commit()
    current = COpeningInputs(cycle[0], now_ms=lambda: NOW)
    engine.opening_inputs = current
    with pytest.raises(CChanException):
        engine.place_order(CODES[0], True, 0.03, 100.5, client_order_id=client, position_side="BOTH")
    assert db.get_record(record["id"])["open_order_status"] == "created" and engine.sim_state.orders == {}


def test_removing_an_intent_input_stamp_cannot_downgrade_submission_to_legacy(inputs, cycle):
    guard, db = inputs
    engine = bound_engine(inputs, cycle)
    record = add_signal(db)
    client = engine.make_client_order_id(record, "open")
    assert db.acquire_open_intent(record["id"], 0.03, client, position_side="BOTH",
        snapshot={"price": 100.5, "opening_inputs": guard.check(record, engine=engine)})
    db.db.execute("UPDATE chan_trade SET snapshot_before=? WHERE id=?", ('{"price":100.5}', record["id"]))
    with pytest.raises(CChanException):
        engine.place_order(CODES[0], True, 0.03, 100.5, client_order_id=client, position_side="BOTH")
    assert db.get_record(record["id"])["open_order_status"] == "created" and engine.sim_state.orders == {}


def test_unmodelled_scope_also_binds_the_real_strategy_feature_implementation(inputs, monkeypatch, tmp_path):
    from ChanModel import ModelContract
    guard, db = inputs
    record = add_signal(db)
    monkeypatch.setattr(ModelContract, "__file__", str(tmp_path/"unavailable"/"ChanModel"/"ModelContract.py"))
    with pytest.raises(CChanException):
        guard.check(record)
