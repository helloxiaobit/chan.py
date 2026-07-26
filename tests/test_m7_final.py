"""M7 验收测试:FeatureReconciliation、多级别全量一致性、ExamGenerator、CosApi降级"""
import os

import pytest

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from Common.ChanException import CChanException
from CustomBuySellPoint.CustomStrategy import CCustomStrategy

from .conftest import ROOT, make_klu

FULL_CONF = {
    "divergence_rate": float("inf"),
    "min_zs_cnt": 0,
    "bs_type": "1,2,3a,1p,2s,3b",
    "cbsp_strategy": CCustomStrategy,
    "mean_metrics": [5, 20, 60],
    "trend_metrics": [10, 20],
    "cal_rsi": True,
    "cal_kdj": True,
    "cal_demark": True,
}


def test_feature_reconciliation_synthetic(synthetic_csv_code):
    from ModelStrategy.FeatureReconciliation import feature_reconcile
    report = feature_reconcile(synthetic_csv_code, FULL_CONF, data_src=DATA_SRC.CSV, autype=AUTYPE.NONE)
    assert report.cbsp_cnt_offline > 0
    assert report.is_consistent, str(report)


def test_feature_reconciliation_real_data():
    """sz.000001 真实数据的离线在线特征一致性(最高验收)"""
    from ModelStrategy.FeatureReconciliation import feature_reconcile
    report = feature_reconcile("sz.000001", FULL_CONF, data_src=DATA_SRC.CSV,
                               begin_time="2022-01-01", autype=AUTYPE.NONE)
    assert report.cbsp_cnt_offline > 5
    assert report.is_consistent, str(report)


def test_multi_lv_full_consistency(synthetic_bars, synthetic_csv_code):
    """多级别(日线+60分钟)load vs trigger 全量一致性:两级别的笔/段/中枢/bsp/cbsp 全部一致"""
    sub_path = os.path.join(ROOT, f"{synthetic_csv_code}_60m.csv")
    with open(sub_path, "w", encoding="utf-8") as f:
        f.write("datetime,open,high,low,close\n")
        for b in synthetic_bars:
            o, h, l, c = b["open"], b["high"], b["low"], b["close"]
            pairs = [(o, h), (h, l), (l, c), (c, c)]
            times = ["10:30:00", "11:30:00", "14:00:00", "15:00:00"]
            for (so, sc), t in zip(pairs, times):
                f.write(f"{b['year']:04}-{b['month']:02}-{b['day']:02} {t},{so},{max(so, sc)},{min(so, sc)},{sc}\n")
    try:
        conf = {**FULL_CONF, "kl_data_check": False}
        chan_a = CChan(code=synthetic_csv_code, data_src=DATA_SRC.CSV,
                       lv_list=[KL_TYPE.K_DAY, KL_TYPE.K_60M],
                       config=CChanConfig(dict(conf)), autype=AUTYPE.NONE)

        chan_b = CChan(code=synthetic_csv_code, data_src=DATA_SRC.CSV,
                       lv_list=[KL_TYPE.K_DAY, KL_TYPE.K_60M],
                       config=CChanConfig({**conf, "trigger_step": True}), autype=AUTYPE.NONE)
        for b in synthetic_bars:
            day_klu = make_klu(b)
            sub_klus = []
            o, h, l, c = b["open"], b["high"], b["low"], b["close"]
            for (so, sc), (hh, mm) in zip([(o, h), (h, l), (l, c), (c, c)],
                                          [(10, 30), (11, 30), (14, 0), (15, 0)]):
                from Common.CEnum import DATA_FIELD
                from Common.CTime import CTime
                from KLine.KLine_Unit import CKLine_Unit
                sub_klus.append(CKLine_Unit({
                    DATA_FIELD.FIELD_TIME: CTime(b["year"], b["month"], b["day"], hh, mm),
                    DATA_FIELD.FIELD_OPEN: so,
                    DATA_FIELD.FIELD_HIGH: max(so, sc),
                    DATA_FIELD.FIELD_LOW: min(so, sc),
                    DATA_FIELD.FIELD_CLOSE: sc,
                }))
            chan_b.trigger_load({KL_TYPE.K_DAY: [day_klu], KL_TYPE.K_60M: sub_klus})

        for lv_idx in range(2):
            lv_a, lv_b = chan_a[lv_idx], chan_b[lv_idx]
            bi_a = [(bi.idx, bi.get_begin_klu().idx, bi.get_end_klu().idx, bi.is_sure) for bi in lv_a.bi_list]
            bi_b = [(bi.idx, bi.get_begin_klu().idx, bi.get_end_klu().idx, bi.is_sure) for bi in lv_b.bi_list]
            assert bi_a == bi_b, f"lv{lv_idx} 笔不一致"
            seg_a = [(s.idx, s.start_bi.idx, s.end_bi.idx, s.is_sure) for s in lv_a.seg_list]
            seg_b = [(s.idx, s.start_bi.idx, s.end_bi.idx, s.is_sure) for s in lv_b.seg_list]
            assert seg_a == seg_b, f"lv{lv_idx} 段不一致"
            zs_a = [(z.begin_bi.idx, z.end_bi.idx, round(z.low, 6), round(z.high, 6)) for z in lv_a.zs_list]
            zs_b = [(z.begin_bi.idx, z.end_bi.idx, round(z.low, 6), round(z.high, 6)) for z in lv_b.zs_list]
            assert zs_a == zs_b, f"lv{lv_idx} 中枢不一致"
            bsp_a = sorted((p.klu.idx, p.is_buy, p.type2str()) for p in lv_a.bs_point_lst.getSortedBspList())
            bsp_b = sorted((p.klu.idx, p.is_buy, p.type2str()) for p in lv_b.bs_point_lst.getSortedBspList())
            assert bsp_a == bsp_b, f"lv{lv_idx} bsp不一致"
            cbsp_a = [(cb.klu.idx, cb.is_buy, cb.bs_type, round(cb.open_price, 6)) for cb in lv_a.cbsp_strategy]
            cbsp_b = [(cb.klu.idx, cb.is_buy, cb.bs_type, round(cb.open_price, 6)) for cb in lv_b.cbsp_strategy]
            assert cbsp_a == cbsp_b, f"lv{lv_idx} cbsp不一致"
    finally:
        os.remove(sub_path)


def test_exam_generator(tmp_path):
    from ExamGenerator import CQuestion
    Q = CQuestion(
        area='cn', begin_time='2018-01-01', kl_type=KL_TYPE.K_DAY,
        _config={"min_zs_cnt": 0, "bs_type": '1,1p,2'},
        data_src=DATA_SRC.CSV, autype=AUTYPE.NONE,
        code_pool=["sz.000001"], seed=42, out_dir=str(tmp_path),
    )
    assert Q.QuestionGenerator(is_buy=True), "sz.000001 上应能出题"
    q_path = Q.PlotTestFigure()
    a_path = Q.PlotAnswerFigure()
    assert os.path.exists(q_path) and os.path.getsize(q_path) > 0
    assert os.path.exists(a_path) and os.path.getsize(a_path) > 0
    # 题目不含未来:题目 chan 的最后一根K线不晚于出题 cbsp 的K线
    assert not Q.question_chan[0][-1][-1].time > Q.question_cbsp.klu.time


def test_exam_generator_not_found():
    from ExamGenerator import CQuestion
    Q = CQuestion(area='cn', _config={"min_zs_cnt": 99}, data_src=DATA_SRC.CSV,
                  autype=AUTYPE.NONE, code_pool=["not_exist_code"], seed=1)
    assert Q.QuestionGenerator(is_buy=True) is False


def test_cos_not_configured():
    from Plot.CosApi import upload_file
    with pytest.raises(CChanException) as e:
        upload_file("whatever.png", conf={"backend": "none"})
    assert "图床" in str(e.value)


def test_etf_and_marketvalue_import():
    # 低优先模块至少可导入
    from DataAPI.ETFStockAPI import CETF_API
    from DataAPI.MarketValueFilter import filter_by_market_value, query_marketvalue
    assert CETF_API is not None
    assert callable(query_marketvalue) and callable(filter_by_market_value)
