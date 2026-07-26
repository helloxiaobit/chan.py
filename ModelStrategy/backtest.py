"""回测样本落地:回放股票池,产出特征样本文件(libsvm+meta,兼容 Debug/strategy_demo5.py 格式)与五种标签

标签体系(只在回放结束后用未来数据打标,训练用,不进特征):
1. label_bsp_hold:    该位置最终仍是形态学 bsp
2. label_ret_N:       开仓后 N 根K线收益率是否 > x%
3. label_next_bsp:    到下一个反向 bsp 出现时的收益率符号
4. label_max_drawdown:触及止损线之前是否先达到止盈线
5. label_seg_confirm: 预期方向的线段最终被确认(is_sure)
"""
import json
import os
from typing import Dict, List, Optional

from Chan import CChan
from ChanConfig import CChanConfig
from ChanModel.FeatureDesc import FEATURE_REG
from Common.CEnum import BI_DIR

from .BacktestChanConfig import CBacktestConfig


class CSample:
    def __init__(self, code: str, cbsp, labels: Dict[str, int]):
        self.code = code
        self.cbsp = cbsp
        self.labels = labels


class CBacktestResult:
    def __init__(self, samples: List[CSample], output_dir: str, feature_meta: Dict[str, int], unregistered: List[str]):
        self.samples = samples
        self.output_dir = output_dir
        self.feature_meta = feature_meta
        self.unregistered_features = unregistered

    @property
    def feature_cnt(self) -> int:
        return len(self.feature_meta)

    @property
    def libsvm_path(self) -> str:
        return os.path.join(self.output_dir, "feature.libsvm")

    @property
    def meta_path(self) -> str:
        return os.path.join(self.output_dir, "feature.meta")

    @property
    def sample_info_path(self) -> str:
        return os.path.join(self.output_dir, "sample_info.jsonl")


def cal_labels(chan: CChan, cbsp, label_para: Dict) -> Dict[str, int]:
    """五种标签,均只用 cbsp.klu 之后的数据(打标允许看未来)"""
    lv_data = chan[0]
    labels: Dict[str, int] = {}
    all_klus = list(lv_data.klu_iter())
    open_idx = cbsp.klu.idx

    # 1. label_bsp_hold:关联 bsp 最终仍在形态学 bsp 列表里
    final_bsp_ids = {id(b) for b in lv_data.bs_point_lst.bsp_iter()}
    final_bsp_ids.update(id(b) for b in lv_data.seg_bs_point_lst.bsp_iter())
    labels["label_bsp_hold"] = int(cbsp.bsp is not None and id(cbsp.bsp) in final_bsp_ids)

    # 2. label_ret_N:开仓后 N 根K线收益率 > 阈值
    n, thred = label_para["ret_n"], label_para["ret_thred"]
    if open_idx + n < len(all_klus):
        labels["label_ret_N"] = int(cbsp.profit_at(all_klus[open_idx + n].close) > thred * 100)

    # 3. label_next_bsp:到下一个反向 bsp 出现时的收益率符号
    for bsp in lv_data.bs_point_lst.getSortedBspList():
        if bsp.klu.idx > open_idx and bsp.is_buy != cbsp.is_buy:
            labels["label_next_bsp"] = int(cbsp.profit_at(bsp.klu.close) > 0)
            break

    # 4. label_max_drawdown:先触止盈(+x%)还是先触止损(-y%)
    profit_thred, loss_thred = label_para["dd_profit"] * 100, label_para["dd_loss"] * 100
    for klu in all_klus[open_idx + 1:]:
        best = cbsp.profit_at(klu.high if cbsp.is_buy else klu.low)
        worst = cbsp.profit_at(klu.low if cbsp.is_buy else klu.high)
        if worst < -loss_thred:
            labels["label_max_drawdown"] = 0
            break
        if best > profit_thred:
            labels["label_max_drawdown"] = 1
            break

    # 5. label_seg_confirm:预期方向的线段最终被确认
    expect_dir = BI_DIR.UP if cbsp.is_buy else BI_DIR.DOWN
    labels["label_seg_confirm"] = 0
    for seg in lv_data.seg_list:
        if seg.end_bi.get_end_klu().idx >= open_idx and seg.dir == expect_dir:
            labels["label_seg_confirm"] = int(seg.is_sure)
            break
    return labels


def run_backtest(bt_conf: CBacktestConfig) -> CBacktestResult:
    samples: List[CSample] = []
    for code in bt_conf.code_list:
        chan_conf = dict(bt_conf.chan_config)
        if chan_conf.get("cbsp_strategy") is None:
            from CustomBuySellPoint.CustomStrategy import CCustomStrategy
            chan_conf["cbsp_strategy"] = CCustomStrategy
        chan = CChan(
            code=code,
            begin_time=bt_conf.begin_time,
            end_time=bt_conf.end_time,
            data_src=bt_conf.data_src,
            lv_list=bt_conf.lv_list,
            config=CChanConfig(chan_conf),
            autype=bt_conf.autype,
        )
        strategy = chan[0].cbsp_strategy
        assert strategy is not None
        samples.extend(
            CSample(code, cbsp, cal_labels(chan, cbsp, bt_conf.label_para))
            for cbsp in strategy
        )
    feature_meta, unregistered = write_samples(samples, bt_conf.output_dir, bt_conf.primary_label)
    return CBacktestResult(samples, bt_conf.output_dir, feature_meta, unregistered)


def write_samples(samples: List[CSample], output_dir: str, primary_label: str):
    """样本落地:feature.libsvm + feature.meta(demo5 格式)+ sample_info.jsonl(全标签与开仓信息)"""
    os.makedirs(output_dir, exist_ok=True)
    feature_meta: Dict[str, int] = {}
    cur_idx = 0
    with open(os.path.join(output_dir, "feature.libsvm"), "w", encoding="utf-8") as fid, \
         open(os.path.join(output_dir, "sample_info.jsonl"), "w", encoding="utf-8") as finfo:
        for sample in samples:
            label = sample.labels.get(primary_label, 0)
            features = []
            for name, value in sample.cbsp.features.items():
                if value is None:
                    continue
                if name not in feature_meta:
                    feature_meta[name] = cur_idx
                    cur_idx += 1
                features.append((feature_meta[name], value))
            features.sort(key=lambda x: x[0])
            feature_str = " ".join(f"{idx}:{value}" for idx, value in features)
            fid.write(f"{label} {feature_str}\n")
            finfo.write(json.dumps({
                "code": sample.code,
                "time": sample.cbsp.klu.time.to_str(),
                "is_buy": sample.cbsp.is_buy,
                "bs_type": sample.cbsp.bs_type,
                "is_segbsp": sample.cbsp.is_segbsp,
                "open_price": sample.cbsp.open_price,
                "labels": sample.labels,
            }, ensure_ascii=False) + "\n")
    with open(os.path.join(output_dir, "feature.meta"), "w", encoding="utf-8") as fmeta:
        fmeta.write(json.dumps(feature_meta))
    unregistered = FEATURE_REG.check_features(feature_meta.keys())
    if unregistered:
        print(f"[WARNING] 存在未注册特征 {len(unregistered)} 个: {unregistered[:10]} ...")
    return feature_meta, unregistered
