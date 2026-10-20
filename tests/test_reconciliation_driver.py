"""真正的 load/逐收盘 trigger 多级别对账，不用最终特征 zip 充当因果证明。"""
import pytest

from Chan import CChan
from Common.CEnum import KL_TYPE
from Common.ChanException import CChanException
from ModelStrategy.FeatureReconciliation import feature_reconcile
from .test_crypto_causal_publication import inputs, LEVELS
from .test_decision_snapshots import CDecisionStrategy


def install_source(monkeypatch, *, mutate=None):
    class CFixtureAPI:
        generation = 0

        def __init__(self, code, k_type, **kwargs):
            self.lv = k_type

        @classmethod
        def do_init(cls):
            cls.generation += 1

        @classmethod
        def do_close(cls):
            pass

        def get_kl_data(self):
            rows = inputs(hours=8)[self.lv]
            for row in rows:
                row.source_identity = {"exchange": "binance", "market_type": "swap", "settle": "USDT",
                                       "price_type": "contract"}
            if mutate is not None:
                mutate(rows, self.lv, self.generation)
            yield from rows
    monkeypatch.setattr(CChan, "GetStockAPI", lambda self: CFixtureAPI)
    return CFixtureAPI


def reconcile(strategy=CDecisionStrategy, **kwargs):
    return feature_reconcile("BTC/USDT:USDT", {
        "cbsp_strategy": strategy, "kl_data_check": False,
        "strategy_para": {"skip_features": True}, **kwargs}, lv_list=LEVELS)


def kinds(report):
    return {m["type"] for m in report.mismatches}


def test_driver_uses_fresh_multilevel_sources_and_full_event_identities(monkeypatch):
    source = install_source(monkeypatch)
    report = reconcile()
    assert report.is_exact and report.input_verified, str(report)
    assert report.event_cnt_offline == report.event_cnt_online > 10
    assert report.cbsp_cnt_offline == report.cbsp_cnt_online == 3
    assert report.checkpoints_offline == report.checkpoints_online
    assert len(report.checkpoints_offline) == 10
    assert source.generation == 3  # observed load, online source, unobserved control
    assert all(m["K_60M"]["count"] == 8 for m in report.input_manifests.values())


def test_same_empty_decisions_do_not_hide_a_changed_input(monkeypatch):
    class CNoTrades(CDecisionStrategy):
        def try_open(self, chan, lv):
            return None

        def bsp_signal(self, chan, lv):
            return []
    def mutate(rows, lv, generation):
        if generation == 2 and lv == KL_TYPE.K_60M:
            rows[1].trade_info.metric["volume"] = 2.0
    install_source(monkeypatch, mutate=mutate)
    report = reconcile(CNoTrades)
    assert report.event_cnt_offline == report.event_cnt_online == 0
    assert not report.is_exact and not report.input_verified
    assert "input_mismatch" in kinds(report)


def test_signal_observer_side_effect_cannot_self_certify_two_instrumented_lanes(monkeypatch):
    class CImpureSignals(CDecisionStrategy):
        def bsp_signal(self, chan, lv):
            self.opened_bsp_klu_idx.add(9000 + chan[lv][-1][-1].idx)
            return super().bsp_signal(chan, lv)
    install_source(monkeypatch)
    report = reconcile(CImpureSignals)
    assert not report.is_exact
    assert "observer_effect" in kinds(report)


def test_driver_rejects_missing_native_evidence_even_when_both_lanes_agree(monkeypatch):
    class CHiddenLedger(CDecisionStrategy):
        @property
        def decision_records(self):
            return ()
    install_source(monkeypatch)
    report = reconcile(CHiddenLedger)
    assert not report.is_exact
    assert "missing_native_record" in kinds(report)


def test_checkpoint_dedupe_drift_is_checked_even_without_any_trade(monkeypatch):
    class CStateDrift(CDecisionStrategy):
        def try_open(self, chan, lv):
            if self.conf.trigger_step:
                self.opened_bsp_klu_idx.add(chan[lv][-1][-1].idx)
            return None

        def bsp_signal(self, chan, lv):
            return []
    install_source(monkeypatch)
    report = reconcile(CStateDrift)
    assert report.event_cnt_offline == report.event_cnt_online == 0
    assert report.input_verified
    assert kinds(report) == {"checkpoint_mismatch"}
    assert not report.is_exact


def test_control_checks_temporary_structure_side_effects_not_only_final_trades(monkeypatch):
    class CStructureSignals(CDecisionStrategy):
        def try_open(self, chan, lv):
            if hasattr(self, "touched"):
                self.touched.close = self.original_close
            return None

        def bsp_signal(self, chan, lv):
            cur = chan[lv][-1][-1]
            if lv == 1 and cur.idx == 1:
                self.touched, self.original_close = cur, cur.close
                cur.close += 0.25
            return []
    install_source(monkeypatch)
    report = reconcile(CStructureSignals)
    assert report.event_cnt_offline == report.event_cnt_online == 0
    assert report.input_verified
    assert not report.is_exact
    assert "observer_effect" in kinds(report)


def test_reconciliation_refuses_last_only_instead_of_claiming_historical_coverage(monkeypatch):
    install_source(monkeypatch)
    with pytest.raises(CChanException, match="only_judge_last|逐"):
        reconcile(only_judge_last=True)
