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
