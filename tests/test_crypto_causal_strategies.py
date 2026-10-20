"""提供的真实策略：未来父 K 和 suffix 不能改变历史已接受决策（不计算绩效）。"""
from copy import deepcopy

import pytest

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import KL_TYPE
from Common.KLineTime import KLTYPE_TO_MS, make_crypto_klu
from CustomBuySellPoint.CustomStrategy import CCustomStrategy
from CustomBuySellPoint.Decision import read_decision
from CustomBuySellPoint.MultiLevelStrategy import CMultiLevelStrategy
from .test_multilv import BASE_CONF, LV_LIST, aggregate, gen_15m_bars


def source():
    bars = gen_15m_bars(n_4h=80)
    return {KL_TYPE.K_4H: aggregate(bars, 16), KL_TYPE.K_60M: aggregate(bars, 4), KL_TYPE.K_15M: bars}


def run(rows, strategy):
    chan = CChan("TEST/USDT:USDT", lv_list=LV_LIST, config=CChanConfig({
        **BASE_CONF, "cbsp_strategy": strategy, "trigger_step": True, "cal_feature": True,
        "strategy_para": {"require_sub_confirm": False}}))
    payload = {}
    for lv, bars in rows.items():
        payload[lv] = []
        for bar in bars:
            klu = make_crypto_klu(bar, lv)
            klu.source_identity = {"exchange": "binance", "market_type": "swap", "settle": "USDT",
                                   "price_type": "contract"}
            payload[lv].append(klu)
    chan.trigger_load(payload)
    return chan


def history(chan, cutoff):
    return tuple(tuple(raw for raw in chan[i].cbsp_strategy.decision_records
                       if read_decision(raw)["identity"]["decision_ms"] < cutoff) for i in range(3))


@pytest.mark.parametrize("strategy,has_virtual_origin", [(CCustomStrategy, True), (CMultiLevelStrategy, False)])
def test_native_strategy_history_survives_prefix_future_and_unclosed_parent_mutation(strategy, has_virtual_origin):
    rows = source()
    # 切在 4h 区间中间：prefix 根本没有那根尚未收盘的父 K。
    cutoff = rows[KL_TYPE.K_15M][0][0] + 194 * 3_600_000
    short = {lv: [bar for bar in bars if bar[0] + KLTYPE_TO_MS[lv] < cutoff] for lv, bars in rows.items()}
    mutated = deepcopy(rows)
    for lv, bars in mutated.items():
        for i, bar in enumerate(bars):
            if bar[0] + KLTYPE_TO_MS[lv] >= cutoff:
                bars[i] = (bar[0], *(v * 1.25 for v in bar[1:5]), bar[5])
    prefix, full, future = (run(data, strategy) for data in (short, rows, mutated))
    assert history(prefix, cutoff) == history(full, cutoff) == history(future, cutoff)
    early = [read_decision(raw) for level in history(prefix, cutoff) for raw in level]
    assert any(r["identity"]["kind"] == "open" and r["payload"]["features"] for r in early)
    all_records = [read_decision(raw) for i in range(3) for raw in full[i].cbsp_strategy.decision_records]
    openings = [r for r in all_records if r["identity"]["kind"] == "open"]
    assert {r["identity"]["is_buy"] for r in openings} == {False, True}
    assert any(r["identity"]["kind"] == "exit" for r in all_records)
    assert any(r["payload"]["origin"] and not r["payload"]["origin"]["line"]["is_sure"]
               for r in openings) is has_virtual_origin
    # 后来的来源笔/段端点或类型可以正常重建，先前决策字节不跟着当前对象变化。
    rewritten = [cb for i in range(3) for cb in full[i].cbsp_strategy if cb.bsp is not None and
                 (read_decision(cb.open_decision)["payload"]["origin"]["types"] != [t.value for t in cb.bsp.type]
                  or read_decision(cb.open_decision)["payload"]["origin"]["line"]["end_ms"] !=
                  int(cb.bsp.bi.get_end_klu().time.ts * 1000))]
    assert rewritten


def test_native_three_level_feature_reconciliation_is_exact(monkeypatch):
    from ModelStrategy.FeatureReconciliation import feature_reconcile
    rows = source()
    class CFixtureAPI:
        def __init__(self, code, k_type, **kwargs):
            self.lv = k_type

        @classmethod
        def do_init(cls):
            pass

        @classmethod
        def do_close(cls):
            pass

        def get_kl_data(self):
            for bar in rows[self.lv]:
                klu = make_crypto_klu(bar, self.lv)
                klu.source_identity = {"exchange": "binance", "market_type": "swap", "settle": "USDT",
                                       "price_type": "contract"}
                yield klu
    monkeypatch.setattr(CChan, "GetStockAPI", lambda self: CFixtureAPI)
    report = feature_reconcile("TEST/USDT:USDT", {**BASE_CONF, "cal_feature": True,
        "strategy_para": {"require_sub_confirm": False}}, lv_list=LV_LIST)
    assert report.is_exact and report.input_verified, str(report)
    assert report.event_cnt_offline > report.cbsp_cnt_offline > 10
    assert len(report.checkpoints_offline) == 80 * 21  # 4h + 1h + 15m decisions
