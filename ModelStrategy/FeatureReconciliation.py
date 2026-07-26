"""离线在线特征一致性校验

同一 code 用两种模式各跑一遍:
- 离线模式:一次性 load(回测/训练产样本的路径)
- 在线模式:trigger_load 逐根投喂(实盘的路径)
逐个 cbsp 比对特征名与特征值,不一致即说明存在未来函数或状态泄漏。

用法: python -m ModelStrategy.FeatureReconciliation sz.000001
"""
import os
import sys
from typing import Dict, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE


class CReconcileReport:
    def __init__(self):
        self.cbsp_cnt_offline = 0
        self.cbsp_cnt_online = 0
        self.mismatches: List[Dict] = []

    @property
    def is_consistent(self) -> bool:
        return self.cbsp_cnt_offline == self.cbsp_cnt_online and not self.mismatches

    def __str__(self):
        if self.is_consistent:
            return f"[FeatureReconciliation] 一致 ✓ cbsp={self.cbsp_cnt_offline},特征全部对齐"
        lines = [f"[FeatureReconciliation] 不一致 ✗ 离线cbsp={self.cbsp_cnt_offline} 在线cbsp={self.cbsp_cnt_online}"]
        lines.extend(f"  {m}" for m in self.mismatches[:20])
        return "\n".join(lines)


def feature_reconcile(
    code: str,
    chan_config: Dict,
    data_src=DATA_SRC.CSV,
    lv: KL_TYPE = KL_TYPE.K_DAY,
    begin_time: Optional[str] = None,
    end_time: Optional[str] = None,
    autype: AUTYPE = AUTYPE.NONE,
    rel_tol: float = 1e-9,
) -> CReconcileReport:
    assert chan_config.get("cbsp_strategy") is not None, "需要配置 cbsp_strategy"
    # 离线:一次性 load
    chan_offline = CChan(
        code=code, begin_time=begin_time, end_time=end_time, data_src=data_src,
        lv_list=[lv], config=CChanConfig(dict(chan_config)), autype=autype,
    )
    # 在线:trigger_load 逐根投喂(从同一数据源重新取K线,保证对象独立)
    chan_online = CChan(
        code=code, begin_time=begin_time, end_time=end_time, data_src=data_src,
        lv_list=[lv], config=CChanConfig({**chan_config, "trigger_step": True}), autype=autype,
    )
    stockapi_cls = chan_offline.GetStockAPI()
    stockapi_cls.do_init()
    try:
        api = stockapi_cls(code=code, k_type=lv, begin_date=begin_time, end_date=end_time, autype=autype)
        for klu in api.get_kl_data():
            chan_online.trigger_load({lv: [klu]})
    finally:
        stockapi_cls.do_close()

    report = CReconcileReport()
    cbsp_offline = list(chan_offline[0].cbsp_strategy)
    cbsp_online = list(chan_online[0].cbsp_strategy)
    report.cbsp_cnt_offline = len(cbsp_offline)
    report.cbsp_cnt_online = len(cbsp_online)
    for ca, cb in zip(cbsp_offline, cbsp_online):
        fa, fb = dict(ca.features.items()), dict(cb.features.items())
        if fa.keys() != fb.keys():
            report.mismatches.append({
                "time": ca.klu.time.to_str(),
                "type": "特征名不一致",
                "diff": sorted(fa.keys() ^ fb.keys())[:10],
            })
            continue
        for k in fa:
            va, vb = fa[k], fb[k]
            if va == vb:
                continue
            if va is None or vb is None or abs(va - vb) > rel_tol * max(abs(va), abs(vb), 1e-12):
                report.mismatches.append({
                    "time": ca.klu.time.to_str(), "type": "特征值不一致",
                    "feat": k, "offline": va, "online": vb,
                })
    return report


if __name__ == "__main__":
    from CustomBuySellPoint.CustomStrategy import CCustomStrategy
    arg_code = sys.argv[1] if len(sys.argv) > 1 else "sz.000001"
    conf = {
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
    rep = feature_reconcile(arg_code, conf)
    print(rep)
    sys.exit(0 if rep.is_consistent else 1)
