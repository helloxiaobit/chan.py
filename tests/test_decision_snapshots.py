"""真实 CStrategy 生命周期的不可变证据；不运行经济研究。"""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE
from Common.ChanException import CChanException
from Common.KLineTime import make_crypto_klu
from CustomBuySellPoint.CustomBSP import CCustomBSP
from CustomBuySellPoint.Signal import CSignal
from CustomBuySellPoint.Strategy import CStrategy

START = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
HOUR = 3_600_000


def klu(n):
    return make_crypto_klu([START + n * HOUR, 100, 110, 90, 100 + n, 1], KL_TYPE.K_60M)


class CDecisionStrategy(CStrategy):
    def __init__(self, conf):
        super().__init__(conf)
        self.opened_bsp_klu_idx = set()

    def try_open(self, chan, lv):
        cur = chan[lv][-1][-1]
        if cur.idx not in (0, 2):
            return None
        cbsp = CCustomBSP(None, cur, "fixture", cur.idx == 0, sl_price=95)
        cbsp.add_feat({"known": self.conf.strategy_para.get("fixture_feature", cur.close)})
        self.opened_bsp_klu_idx.add(cur.idx)
        return cbsp

    def try_close(self, chan, lv):
        cur = chan[lv][-1][-1]
        if cur.idx in (1, 2):
            for cbsp in self.holding_cbsp():
                cbsp.do_close(cur.close, cur, "fixture_exit", quota=0.5 if cur.idx == 1 else None)

    def bsp_signal(self, chan, lv):
        cur = chan[lv][-1][-1]
        return [CSignal(chan.code, chan.lv_list[lv], True, "watch", cur, 105,
                        sl_thred=95, target_klu_time=cur.time, score=0.75)]


def channel(**extra):
    return CChan("BTC/USDT", lv_list=[KL_TYPE.K_60M], config=CChanConfig({
        "trigger_step": True, "cbsp_strategy": CDecisionStrategy,
        "strategy_para": {"skip_features": True, **extra}}))


def feed(chan, n):
    chan.trigger_load({KL_TYPE.K_60M: [klu(n)]})


def read(raw):
    from CustomBuySellPoint.Decision import read_decision
    return read_decision(raw)


def test_strategy_publishes_an_immutable_finite_open_decision():
    chan = channel()
    feed(chan, 0)
    strategy = chan[0].cbsp_strategy
    cbsp = strategy[0]
    raw = cbsp.open_decision
    assert isinstance(raw, bytes)
    record = read(raw)
    assert record["identity"]["code"] == "BTC/USDT"
    assert record["identity"]["level"] == "K_60M"
    assert record["identity"]["decision_ms"] == START + HOUR
    assert record["payload"]["features"] == {"known": 100.0}
    assert record["payload"]["sl_price"] == 95
    assert record["payload"]["dedupe"]["opened_bsp_klu_idx"] == [0]
    assert strategy.decision_records == (raw,)
    cbsp.features.add_feat({"known": 999})
    cbsp.sl_price = 98
    record["payload"]["features"]["known"] = -1
    assert read(raw)["payload"]["features"] == {"known": 100.0}
    assert read(raw)["payload"]["sl_price"] == 95
    assert cbsp.open_decision == raw
    with pytest.raises(AttributeError):
        cbsp.open_decision = b"replace"


def test_partial_and_final_exits_reference_the_original_open_identity():
    chan = channel()
    for n in range(3):
        feed(chan, n)
    strategy = chan[0].cbsp_strategy
    records = [read(raw) for raw in strategy.decision_records]
    assert [r["identity"]["kind"] for r in records] == ["open", "exit", "exit", "open"]
    assert records[1]["identity"]["parent_event_id"] == records[0]["event_id"]
    assert records[2]["identity"]["parent_event_id"] == records[0]["event_id"]
    assert [records[i]["payload"]["quota"] for i in (1, 2)] == [0.5, None]
    assert records[2]["identity"]["decision_ms"] == records[3]["identity"]["decision_ms"]
    first_action = strategy[0].close_actions[0]
    raw = first_action.decision
    first_action.price = 999
    first_action.reason = "later mutation"
    assert first_action.decision == raw
    assert read(raw)["payload"]["price"] == 101.0


def test_deepcopy_keeps_future_exit_records_in_the_copied_strategy():
    original = channel()
    feed(original, 0)
    copied = deepcopy(original)
    feed(copied, 1)
    assert len(original[0].cbsp_strategy.decision_records) == 1
    assert len(copied[0].cbsp_strategy.decision_records) == 2
    assert copied[0].cbsp_strategy[0].close_actions[0].decision in copied[0].cbsp_strategy.decision_records


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_open_evidence_is_rejected_before_accepting_the_trade(value):
    chan = channel(fixture_feature=value)
    with pytest.raises(CChanException, match="有限|finite"):
        feed(chan, 0)
    assert len(chan[0].cbsp_strategy) == 0
    assert chan[0].cbsp_strategy.decision_records == ()


def test_non_finite_exit_is_rejected_before_mutating_the_position():
    chan = channel()
    feed(chan, 0)
    cbsp = chan[0].cbsp_strategy[0]
    with pytest.raises(CChanException, match="有限|finite"):
        cbsp.do_close(float("nan"), klu(1), "bad")
    assert not cbsp.is_cover
    assert cbsp.close_actions == []
    assert len(chan[0].cbsp_strategy.decision_records) == 1


def test_open_with_an_immediate_exit_is_recorded_in_causal_order():
    class CInstant(CDecisionStrategy):
        def try_open(self, chan, lv):
            cbsp = super().try_open(chan, lv)
            if cbsp is not None:
                cbsp.do_close(cbsp.open_price, cbsp.klu, "same_bar")
            return cbsp
    chan = CChan("BTC/USDT", lv_list=[KL_TYPE.K_60M], config=CChanConfig({
        "trigger_step": True, "cbsp_strategy": CInstant, "strategy_para": {"skip_features": True}}))
    feed(chan, 0)
    records = [read(raw) for raw in chan[0].cbsp_strategy.decision_records]
    assert [r["identity"]["kind"] for r in records] == ["open", "exit"]
    assert records[1]["identity"]["parent_event_id"] == records[0]["event_id"]


def test_signal_publication_is_immutable_and_repeated_publication_is_idempotent():
    chan = channel()
    feed(chan, 0)
    strategy = chan[0].cbsp_strategy
    signal = strategy.publish_signals(chan, 0)[0]
    raw = signal.decision
    assert read(raw)["identity"]["kind"] == "signal"
    assert read(raw)["payload"]["score"] == 0.75
    signal.open_thred = 999
    assert read(signal.decision)["payload"]["open_thred"] == 105
    strategy.publish_signals(chan, 0)
    assert len(strategy.decision_records) == 2
    assert strategy.decision_records[-1] == raw


def test_same_identity_with_different_payload_is_not_silently_deduplicated():
    chan = channel()
    feed(chan, 0)
    strategy = chan[0].cbsp_strategy
    strategy.publish_signals(chan, 0)
    before = strategy.decision_records
    signal = strategy.bsp_signal(chan, 0)[0]
    signal.score = 0.1
    strategy.bsp_signal = lambda *args: [signal]
    with pytest.raises(CChanException, match="身份|identity"):
        strategy.publish_signals(chan, 0)
    assert strategy.decision_records == before


def test_reader_rejects_noncanonical_and_tampered_decision_bytes():
    chan = channel()
    feed(chan, 0)
    raw = chan[0].cbsp_strategy[0].open_decision
    with pytest.raises(CChanException):
        read(raw + b"\n")
    tampered = json.loads(raw)
    tampered["event_id"] = "0" * 64
    with pytest.raises(CChanException):
        read(json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode())
    tampered = json.loads(raw)
    tampered["payload"]["sl_price"] = 1
    with pytest.raises(CChanException):
        read(json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode())


def test_failed_signal_batch_leaves_the_decision_ledger_unchanged():
    chan = channel()
    feed(chan, 0)
    strategy = chan[0].cbsp_strategy
    good = strategy.bsp_signal(chan, 0)[0]
    bad = strategy.bsp_signal(chan, 0)[0]
    bad.bs_type, bad.score = "invalid", float("inf")
    strategy.bsp_signal = lambda *args: [good, bad]
    before = strategy.decision_records
    with pytest.raises(CChanException):
        strategy.publish_signals(chan, 0)
    assert strategy.decision_records == before


@pytest.mark.parametrize("field,value", [("code", "ETH/USDT"), ("lv", KL_TYPE.K_4H), ("sig_klu", klu(1))])
def test_signal_publication_checks_actual_instrument_level_and_time(field, value):
    chan = channel()
    feed(chan, 0)
    strategy = chan[0].cbsp_strategy
    signal = strategy.bsp_signal(chan, 0)[0]
    setattr(signal, field, value)
    strategy.bsp_signal = lambda *args: [signal]
    with pytest.raises(CChanException, match="决策|身份"):
        strategy.publish_signals(chan, 0)
    assert len(strategy.decision_records) == 1


def test_future_availability_cannot_be_sealed_as_a_current_decision():
    chan = channel()
    feed(chan, 0)
    signal = chan[0].cbsp_strategy.bsp_signal(chan, 0)[0]
    signal.sig_klu.available_at_ms += HOUR
    with pytest.raises(CChanException, match="可用|available"):
        signal.freeze_decision()


def test_ensemble_delegates_the_selected_variant_ledger_and_signal_state():
    from CustomBuySellPoint.StrategyEnsemble import CStrategyEnsemble
    conf = CChanConfig({"strategy_para": {"skip_features": True}})
    wrapper = CStrategyEnsemble(conf)
    wrapper.variants = [(name, CDecisionStrategy(conf)) for name in ("base", "other")]
    chan = CChan("BTC/USDT", lv_list=[KL_TYPE.K_60M], config=CChanConfig({
        "trigger_step": True, "cbsp_strategy": lambda unused: wrapper}))
    feed(chan, 0)
    base = wrapper.get_variant("base")
    assert wrapper.decision_records == base.decision_records
    signal = wrapper.publish_signals(chan, 0)[0]
    assert read(signal.decision)["payload"]["dedupe"] == base.decision_state()
    assert wrapper.decision_records == base.decision_records
    assert len(wrapper.decision_records) == 2


def test_signal_decision_time_is_the_latest_published_clock_not_its_anchor_bar():
    from tests.test_crypto_causal_publication import inputs, run
    payload = inputs(hours=8)
    payload[KL_TYPE.K_4H] = payload[KL_TYPE.K_4H][:1]
    payload[KL_TYPE.K_60M] = payload[KL_TYPE.K_60M][:6]
    chan = run(payload, cbsp_strategy=CDecisionStrategy, strategy_para={"skip_features": True})
    signal = chan[0].cbsp_strategy.publish_signals(chan, 0)[0]
    record = read(signal.decision)
    assert record["identity"]["decision_ms"] == START + 6 * HOUR
    assert record["identity"]["anchor_ms"] == START + 4 * HOUR
    assert record["payload"]["bar"]["time_ms"] == START + 4 * HOUR


@pytest.mark.parametrize("invalid", [False, True])
def test_signal_monitor_uses_publication_and_keeps_old_watches_on_failure(tmp_path, monkeypatch, invalid):
    from Trade.Script import SignalMonitor as monitor
    from Trade.db_util import CChanDB
    chan = channel()
    feed(chan, 0)
    strategy = chan[0].cbsp_strategy
    monkeypatch.setattr(monitor, "CChan", lambda **kwargs: chan)
    monkeypatch.setattr(monitor, "get_trade_conf", lambda: {
        "code_list": ["BTC/USDT"], "lv_list": [KL_TYPE.K_60M], "strategy": "custom"})
    monkeypatch.setattr(monitor, "get_statics_chan_config", lambda extra: {})
    db = CChanDB(db_conf={"type": "sqlite", "sqlite_path": str(tmp_path / "trade.db")})
    try:
        if invalid:
            old_id = db.add_signal(strategy.bsp_signal(chan, 0)[0])
            bad = strategy.bsp_signal(chan, 0)[0]
            bad.score = float("inf")
            bad.target_klu_time = klu(2).time
            strategy.bsp_signal = lambda *args: [bad]
        stat = monitor.run_signal_monitor(db, code_list=["BTC/USDT"], lv=KL_TYPE.K_60M, push=False)
        if invalid:
            assert stat == {"added": 0, "existed": 0, "unwatched": 0, "failed": 1}
            assert db.get_record(old_id)["watching"] == 1
            assert len(strategy.decision_records) == 1
        else:
            assert stat["added"] == 1
            assert len(strategy.decision_records) == 2
            assert read(strategy.decision_records[-1])["identity"]["kind"] == "signal"
    finally:
        db.close()


def test_identical_decisions_on_different_exchanges_have_different_identities():
    records = []
    for exchange in ("binance", "okx"):
        chan = channel()
        unit = klu(0)
        unit.source_identity = {"exchange": exchange, "market_type": "spot", "settle": "", "price_type": "contract"}
        chan.trigger_load({KL_TYPE.K_60M: [unit]})
        records.append(read(chan[0].cbsp_strategy[0].open_decision))
    assert records[0]["event_id"] != records[1]["event_id"]
    assert records[0]["identity"]["market"]["exchange"] == "binance"
    assert records[1]["identity"]["market"]["exchange"] == "okx"


def test_an_exit_cannot_silently_change_its_market_source():
    chan = channel()
    first = klu(0)
    first.source_identity = {"exchange": "binance", "market_type": "spot", "settle": "", "price_type": "contract"}
    chan.trigger_load({KL_TYPE.K_60M: [first]})
    cbsp = chan[0].cbsp_strategy[0]
    next_bar = klu(1)
    next_bar.source_identity = {**first.source_identity, "exchange": "okx"}
    with pytest.raises(CChanException, match="来源|market"):
        cbsp.do_close(101, next_bar, "wrong_market")
    assert cbsp.close_actions == []


def test_an_exit_parent_must_be_an_open_not_a_signal_record():
    from CustomBuySellPoint.Decision import make_decision
    chan = channel()
    feed(chan, 0)
    strategy = chan[0].cbsp_strategy
    signal = strategy.publish_signals(chan, 0)[0]
    parent = read(signal.decision)
    raw = make_decision({**parent["identity"], "kind": "exit", "parent_event_id": parent["event_id"]},
                        {"bar": parent["payload"]["bar"], "price": 100, "quota": None, "reason": "bad_parent"})
    before = strategy.decision_records
    with pytest.raises(CChanException, match="开仓"):
        strategy._record_decision(raw)
    assert strategy.decision_records == before


def test_unavailable_target_structure_is_not_silently_sealed():
    from KLine.KLine import CKLine
    cur = klu(0)
    cbsp = CCustomBSP(None, cur, "fixture", True, target_klc=CKLine(klu(2), idx=0))
    with pytest.raises(CChanException, match="结构|时刻"):
        cbsp.freeze_open_decision("BTC/USDT", KL_TYPE.K_60M, cur)
    assert cbsp.open_decision is None


def test_actual_bsp_origin_is_frozen_before_future_type_rewrites(synthetic_csv_code):
    from Common.CEnum import DATA_SRC, BSP_TYPE
    from CustomBuySellPoint.CustomStrategy import CCustomStrategy
    chan = CChan(synthetic_csv_code, lv_list=[KL_TYPE.K_DAY], data_src=DATA_SRC.CSV,
                 config=CChanConfig({"cbsp_strategy": CCustomStrategy, "min_zs_cnt": 0,
                                     "divergence_rate": float("inf")}))
    cbsp = next(c for c in chan[0].cbsp_strategy if c.bsp is not None)
    raw = cbsp.open_decision
    origin = read(raw)["payload"]["origin"]
    assert type(origin["line"]["is_sure"]) is bool
    assert origin["line"]["end_ms"] <= read(raw)["identity"]["decision_ms"]
    cbsp.bsp.add_type(BSP_TYPE.T2)
    assert read(cbsp.open_decision)["payload"]["origin"] == origin
