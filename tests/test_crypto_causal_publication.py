"""C2：用真实 CChan 调度观测当时状态，禁止完整父 K 提前进入决策。"""
from datetime import datetime, timezone
from types import SimpleNamespace
import json
import pytest
from Common.ChanException import CChanException

from Chan import CChan
from ChanConfig import CChanConfig
from ChanModel.FeatureEngine import CFeatureEngine
from Common.CEnum import KL_TYPE
from Common.KLineTime import make_crypto_klu
from CustomBuySellPoint.Strategy import CStrategy

START = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
HOUR = 3_600_000
LEVELS = [KL_TYPE.K_4H, KL_TYPE.K_60M]


class CPublicationObserver(CStrategy):
    def __init__(self, conf):
        super().__init__(conf)
        self.records = []

    def update(self, chan, lv):
        cur = chan[lv][-1][-1]
        if cur.idx <= self.last_judge_klu_idx:
            return
        self.last_judge_klu_idx = cur.idx
        payload = {"time_ms": int(cur.time.ts * 1000),
                   "features": CFeatureEngine.cal_multi_lv_family(chan, lv, SimpleNamespace(klu=cur)),
                   "higher": [[int(k.time.ts * 1000) for k in chan[i].klu_iter()] for i in range(lv)]}
        self.records.append(json.dumps(payload, sort_keys=True, allow_nan=False))

    def try_open(self, chan, lv):
        return None

    def try_close(self, chan, lv):
        pass

    def bsp_signal(self, chan, lv):
        return []


def inputs(hours=12, first_parent_close=120):
    return {lv: [make_crypto_klu([START + h * HOUR, 100, 140, 60,
                                 first_parent_close if lv == KL_TYPE.K_4H and h == 0 else 105, 1], lv)
                 for h in range(0, hours, 4 if lv == KL_TYPE.K_4H else 1)] for lv in LEVELS}


def run(payload, **options):
    chan = CChan("BTC/USDT", lv_list=list(payload), config=CChanConfig({
        "trigger_step": True, "cbsp_strategy": CPublicationObserver, "kl_data_check": False, **options}))
    chan.trigger_load(payload)
    return chan


def prefix(records, cutoff):
    return [r for r in records if json.loads(r)["time_ms"] < cutoff]


def test_future_parent_final_value_cannot_change_earlier_child_decisions():
    up, down = run(inputs(first_parent_close=120)), run(inputs(first_parent_close=80))
    assert prefix(up[1].cbsp_strategy.records, START + 4 * HOUR) == prefix(
        down[1].cbsp_strategy.records, START + 4 * HOUR)


def test_higher_structures_are_published_only_at_their_close_boundary():
    chan = run(inputs())
    records = [json.loads(r) for r in chan[1].cbsp_strategy.records]
    for r in records:
        assert all(t <= r["time_ms"] for higher in r["higher"] for t in higher)
    at_four = next(r for r in records if r["time_ms"] == START + 4 * HOUR)
    assert at_four["higher"][0] == [START + 4 * HOUR]


def test_future_suffix_does_not_rewrite_canonical_prefix_decisions():
    short, full = run(inputs(hours=4)), run(inputs(hours=12))
    cutoff = START + 4 * HOUR
    assert prefix(short[1].cbsp_strategy.records, cutoff) == prefix(full[1].cbsp_strategy.records, cutoff)


def test_crypto_parent_child_alignment_uses_intervals_across_midnight():
    chan = run(inputs(hours=28), kl_data_check=True)
    assert not chan.kl_inconsistent_detail


def test_crypto_parent_child_alignment_rejects_a_child_before_parent_open():
    payload = {KL_TYPE.K_4H: [make_crypto_klu([START + 4 * HOUR, 100, 140, 60, 105, 1], KL_TYPE.K_4H)],
               KL_TYPE.K_60M: [make_crypto_klu([START + 3 * HOUR, 100, 140, 60, 105, 1], KL_TYPE.K_60M)]}
    with pytest.raises(CChanException, match="区间"):
        run(payload, kl_data_check=True)


def test_three_levels_publish_closed_parents_before_same_boundary_children():
    steps = {KL_TYPE.K_4H: 16, KL_TYPE.K_60M: 4, KL_TYPE.K_15M: 1}
    payload = {lv: [make_crypto_klu([START + n * 900_000, 100, 140, 60, 105, 1], lv)
                    for n in range(0, 16, step)] for lv, step in steps.items()}
    chan = run(payload)
    records = [json.loads(r) for r in chan[2].cbsp_strategy.records]
    for r in records:
        assert all(t <= r["time_ms"] for higher in r["higher"] for t in higher)
    at_four = next(r for r in records if r["time_ms"] == START + 4 * HOUR)
    assert at_four["higher"] == [[START + 4 * HOUR], [START + i * HOUR for i in range(1, 5)]]


def test_future_parent_mutation_uses_the_previous_completed_parent():
    first, second = inputs(), inputs()
    first[KL_TYPE.K_4H][1].close = 120
    second[KL_TYPE.K_4H][1].close = 80
    a, b = run(first), run(second)
    a_records, b_records = a[1].cbsp_strategy.records, b[1].cbsp_strategy.records
    assert prefix(a_records, START + 8 * HOUR) == prefix(b_records, START + 8 * HOUR)
    at_five = next(json.loads(r) for r in a_records if json.loads(r)["time_ms"] == START + 5 * HOUR)
    assert at_five["features"]["sup_lv_klu_is_up"] is True


def test_only_last_mode_refuses_a_higher_state_after_the_child_decision():
    payload = inputs(hours=4)
    payload[KL_TYPE.K_60M].pop()
    with pytest.raises(CChanException, match="父级别"):
        run(payload, only_judge_last=True)


def test_ensemble_intrabar_override_changes_an_explicit_stop_fixture():
    from CustomBuySellPoint.StrategyEnsemble import CStrategyEnsemble
    from CustomBuySellPoint.CustomBSP import CCustomBSP
    payload = inputs(hours=4)
    payload[KL_TYPE.K_60M] = [make_crypto_klu([START + n * HOUR, 100 + n, 110 + n,
                                             90 + n, 100 + n, 1], KL_TYPE.K_60M) for n in range(4)]
    chan = run(payload)
    ensemble = CStrategyEnsemble(CChanConfig({"strategy_para": {
        "cover_on_trend_flip": False, "reverse_close_types": "fixture_no_reverse",
        "variants": [{"name": "base"}, {"name": "intrabar", "sl_intrabar": True}]}}))
    cur = chan[1][-1][-1]
    stop = (cur.low + cur.close) / 2
    for _, variant in ensemble.variants:
        variant.cbsp_lst.append(CCustomBSP(None, cur.pre, "fixture", True, price=cur.close, sl_price=stop))
        variant.try_close(chan, 1)
    assert not ensemble.get_variant("base").cbsp_lst[0].is_cover
    closed = ensemble.get_variant("intrabar").cbsp_lst[0]
    assert closed.is_cover
    assert closed.close_actions[0].reason == "stop_loss"


def test_lower_level_updates_continue_after_the_last_higher_close():
    chan = run(inputs(hours=4))
    next_hour = make_crypto_klu([START + 4 * HOUR, 100, 140, 60, 105, 1], KL_TYPE.K_60M)
    chan.trigger_load({KL_TYPE.K_4H: [], KL_TYPE.K_60M: [next_hour]})
    assert [k.close_ms for k in chan[1].klu_iter()] == [START + i * HOUR for i in range(1, 6)]
    record = json.loads(chan[1].cbsp_strategy.records[-1])
    assert record["time_ms"] == START + 5 * HOUR
    assert record["features"]["sup_lv_klu_is_up"] is True


def test_a_prefix_with_no_future_parent_matches_full_source_child_decisions():
    short_payload = inputs(hours=8)
    short_payload[KL_TYPE.K_4H] = short_payload[KL_TYPE.K_4H][:1]
    short_payload[KL_TYPE.K_60M] = short_payload[KL_TYPE.K_60M][:6]
    full_payload = inputs(hours=8)
    full_payload[KL_TYPE.K_60M] = full_payload[KL_TYPE.K_60M][:6]
    short, full = run(short_payload), run(full_payload)
    assert len(short[1].cbsp_strategy.records) == 6
    cutoff = START + 7 * HOUR
    assert prefix(short[1].cbsp_strategy.records, cutoff) == prefix(full[1].cbsp_strategy.records, cutoff)


def test_late_parent_attachment_preserves_bulk_parent_child_relations():
    bulk = run(inputs(hours=8))
    stream = run(inputs(hours=4))
    future = inputs(hours=8)
    stream.trigger_load({KL_TYPE.K_4H: [], KL_TYPE.K_60M: future[KL_TYPE.K_60M][4:7]})
    stream.trigger_load({KL_TYPE.K_4H: [future[KL_TYPE.K_4H][1]],
                         KL_TYPE.K_60M: [future[KL_TYPE.K_60M][7]]})
    def relation(chan):
        return [(k.close_ms, k.sup_kl.close_ms if k.sup_kl else None) for k in chan[1].klu_iter()]
    assert relation(stream) == relation(bulk)
    assert [len(k.sub_kl_list) for k in stream[0].klu_iter()] == [4, 4]
    assert stream[1].cbsp_strategy.records == bulk[1].cbsp_strategy.records


def test_late_higher_bar_cannot_rejudge_using_future_lower_state():
    chan = run(inputs(hours=4))
    new = inputs(hours=12)
    chan.trigger_load({KL_TYPE.K_4H: [], KL_TYPE.K_60M: new[KL_TYPE.K_60M][4:9]})
    with pytest.raises(CChanException, match="决策|发布"):
        chan.trigger_load({KL_TYPE.K_4H: [new[KL_TYPE.K_4H][1]], KL_TYPE.K_60M: []})


def test_three_level_quarter_hour_stream_matches_bulk_without_future_parent_inputs():
    steps = {KL_TYPE.K_4H: 16, KL_TYPE.K_60M: 4, KL_TYPE.K_15M: 1}
    def payload():
        return {lv: [make_crypto_klu([START + n * 900_000, 100, 140, 60, 105, 1], lv)
                     for n in range(0, 32, step)] for lv, step in steps.items()}
    all_data = payload()
    bulk = run(all_data)
    source = payload()
    stream = run({lv: data[:16 // steps[lv]] for lv, data in source.items()})
    for n in range(16, 32):
        stream.trigger_load({
            KL_TYPE.K_4H: [source[KL_TYPE.K_4H][1]] if n == 31 else [],
            KL_TYPE.K_60M: [source[KL_TYPE.K_60M][n // 4]] if n % 4 == 3 else [],
            KL_TYPE.K_15M: [source[KL_TYPE.K_15M][n]],
        })
    for lv in range(3):
        assert stream[lv].cbsp_strategy.records == bulk[lv].cbsp_strategy.records
        assert [(k.close_ms, k.sup_kl.close_ms if k.sup_kl else None) for k in stream[lv].klu_iter()] == [
            (k.close_ms, k.sup_kl.close_ms if k.sup_kl else None) for k in bulk[lv].klu_iter()]


def test_stock_api_load_and_step_load_do_not_discard_lower_tail(monkeypatch):
    class CTailAPI:
        def __init__(self, code, k_type, **kwargs):
            self.k_type = k_type

        @classmethod
        def do_init(cls):
            pass

        @classmethod
        def do_close(cls):
            pass

        def get_kl_data(self):
            data = inputs(hours=8)
            data[KL_TYPE.K_4H] = data[KL_TYPE.K_4H][:1]
            data[KL_TYPE.K_60M] = data[KL_TYPE.K_60M][:6]
            yield from data[self.k_type]
    monkeypatch.setattr(CChan, "GetStockAPI", lambda self: CTailAPI)
    conf = {"cbsp_strategy": CPublicationObserver, "kl_data_check": False}
    loaded = CChan("BTC/USDT", lv_list=LEVELS, config=CChanConfig(conf))
    assert len(loaded[1].cbsp_strategy.records) == 6
    stepped = CChan("BTC/USDT", lv_list=LEVELS, config=CChanConfig({**conf, "trigger_step": True}))
    child_closes = [s[1][-1][-1].close_ms for s in stepped.step_load()]
    assert child_closes == [START + 4 * HOUR, START + 6 * HOUR]


def test_deepcopy_with_orphan_tail_can_resume_equivalently():
    from copy import deepcopy
    stream = run(inputs(hours=4))
    remaining = inputs(hours=8)
    stream.trigger_load({KL_TYPE.K_4H: [], KL_TYPE.K_60M: remaining[KL_TYPE.K_60M][4:7]})
    cloned = deepcopy(stream)
    for chan in (stream, cloned):
        source = inputs(hours=8)
        chan.trigger_load({KL_TYPE.K_4H: [source[KL_TYPE.K_4H][1]], KL_TYPE.K_60M: [source[KL_TYPE.K_60M][7]]})
    assert cloned[1].cbsp_strategy.records == stream[1].cbsp_strategy.records
    assert [len(k.sub_kl_list) for k in cloned[0].klu_iter()] == [4, 4]


def test_ensemble_wrapper_does_not_rejudge_an_old_parent_after_tail_progress():
    from CustomBuySellPoint.StrategyEnsemble import CStrategyEnsemble
    payload = inputs(hours=8)
    payload[KL_TYPE.K_4H] = payload[KL_TYPE.K_4H][:1]
    chan = run(payload, cbsp_strategy=CStrategyEnsemble,
               strategy_para={"skip_features": True, "require_sub_confirm": False})
    assert len(list(chan[1].klu_iter())) == 8
    chan.trigger_load({lv: [] for lv in LEVELS})
    assert chan[1].cbsp_strategy.get_variant("base").last_judge_klu_idx == 7


def test_raw_parent_pointer_is_not_exposed_before_parent_publication():
    class CParentObserver(CPublicationObserver):
        def __init__(self, conf):
            super().__init__(conf)
            self.raw_parents = []

        def update(self, chan, lv):
            super().update(chan, lv)
            cur = chan[lv][-1][-1]
            self.raw_parents.append((cur.close_ms, cur.sup_kl.close_ms if cur.sup_kl else None))
    chan = run(inputs(hours=8), cbsp_strategy=CParentObserver)
    for at, parent in chan[1].cbsp_strategy.raw_parents:
        assert parent is None or parent <= at
    assert chan[1].cbsp_strategy.raw_parents[0] == (START + HOUR, None)
    assert chan[1].cbsp_strategy.raw_parents[3] == (START + 4 * HOUR, START + 4 * HOUR)


def test_published_parent_next_pointer_cannot_expose_an_unpublished_successor():
    class CNextObserver(CPublicationObserver):
        def __init__(self, conf):
            super().__init__(conf)
            self.successors = []

        def update(self, chan, lv):
            super().update(chan, lv)
            if lv == 1 and len(chan[0]):
                nxt = chan[0][-1][-1].next
                self.successors.append((chan[lv][-1][-1].close_ms, nxt.close_ms if nxt else None))
    chan = run(inputs(hours=12), cbsp_strategy=CNextObserver)
    assert chan[1].cbsp_strategy.successors
    assert all(nxt is None or nxt <= at for at, nxt in chan[1].cbsp_strategy.successors)


def test_separately_arriving_child_at_closed_parent_boundary_attaches_once():
    payload = inputs(hours=4)
    final_child = payload[KL_TYPE.K_60M].pop()
    chan = run(payload)
    chan.trigger_load({KL_TYPE.K_4H: [], KL_TYPE.K_60M: [final_child]})
    parent = chan[0][-1][-1]
    assert final_child.sup_kl is parent
    assert [k.close_ms for k in parent.sub_kl_list] == [START + i * HOUR for i in range(1, 5)]
