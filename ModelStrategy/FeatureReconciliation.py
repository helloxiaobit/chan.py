"""按不可变事件身份核对 load 与逐收盘 trigger；一致不单独证明没有共同窥视未来。

三次独立读取还核对输入、结构/去重检查点，以及信号观察对原生决策的影响。
诊断不计算绩效；旧单级别调用仍可用，多级别通过 lv_list 显式指定。
"""
import hashlib
import heapq
import itertools
import math
import os
import sys
from typing import Dict, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import bar_snapshot, canonical_bytes, read_decision


class CReconcileReport:
    def __init__(self):
        self.cbsp_cnt_offline = 0
        self.cbsp_cnt_online = 0
        self.event_cnt_offline = 0
        self.event_cnt_online = 0
        self.input_verified = False
        self.input_manifests = {}
        self.checkpoints_offline = self.checkpoints_online = ()
        self.records_offline = self.records_online = ()
        self._exact_match = False
        self.mismatches: List[Dict] = []

    @property
    def is_consistent(self) -> bool:
        return (self.cbsp_cnt_offline == self.cbsp_cnt_online
                and self.event_cnt_offline == self.event_cnt_online and not self.mismatches)

    @property
    def is_exact(self):
        return self.is_consistent and self._exact_match

    def __str__(self):
        if self.is_consistent:
            return (f"[FeatureReconciliation] {'精确' if self.is_exact else '容差'}一致 ✓ "
                    f"cbsp={self.cbsp_cnt_offline}, events={self.event_cnt_offline}, input_verified={self.input_verified}")
        lines = [f"[FeatureReconciliation] 不一致 ✗ 离线cbsp={self.cbsp_cnt_offline} 在线cbsp={self.cbsp_cnt_online}"]
        lines.extend(f"  {m}" for m in self.mismatches[:20])
        return "\n".join(lines)


def _index_records(records, lane, report):
    indexed = {}
    order = []
    previous_ms = -1
    exit_counts = {}
    for n, raw in enumerate(records):
        try:
            record = read_decision(raw)
        except CChanException:
            report.mismatches.append({"type": "invalid_record", "lane": lane, "index": n})
            continue
        event_id, identity = record["event_id"], record["identity"]
        if event_id in indexed:
            report.mismatches.append({"type": "duplicate_event", "lane": lane, "event_id": event_id})
            continue
        if identity["decision_ms"] < previous_ms:
            report.mismatches.append({"type": "non_monotonic", "lane": lane, "event_id": event_id})
        previous_ms = max(previous_ms, identity["decision_ms"])
        if identity["kind"] == "exit":
            parent_id = identity["parent_event_id"]
            parent = indexed.get(parent_id)
            fields = ("code", "level", "market", "is_buy", "is_segbsp", "bs_type", "anchor_ms")
            if (parent is None or parent["identity"]["kind"] != "open"
                    or any(identity[k] != parent["identity"][k] for k in fields)):
                report.mismatches.append({"type": "invalid_parent", "lane": lane, "event_id": event_id})
            expected_sequence = exit_counts.get(parent_id, 0)
            if identity["sequence"] != expected_sequence:
                report.mismatches.append({"type": "exit_sequence", "lane": lane, "event_id": event_id})
            exit_counts[parent_id] = expected_sequence + 1
        indexed[event_id] = record
        order.append(event_id)
    return indexed, order


def _payload_paths(left, right, path, rel_tol):
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        result = []
        for key in sorted(left.keys() | right.keys()):
            if key not in left or key not in right:
                result.append([*path, key])
            else:
                result.extend(_payload_paths(left[key], right[key], [*path, key], rel_tol))
        return result
    if (isinstance(left, float) and path[:2] == ["payload", "features"]
            and math.isclose(left, right, rel_tol=rel_tol, abs_tol=0.0)):
        return []
    return [] if canonical_bytes(left) == canonical_bytes(right) else [path]


def reconcile_decision_records(offline_records, online_records, *, rel_tol=0.0):
    """按完整身份核对，默认逐字节；容差只用于显式要求的特征值，不产生 exact PASS。"""
    if type(rel_tol) not in (int, float) or not math.isfinite(rel_tol) or rel_tol < 0:
        raise CChanException("对账容差必须是有限非负数", ErrCode.PARA_ERROR)
    offline, online = tuple(offline_records), tuple(online_records)
    report = CReconcileReport()
    report.event_cnt_offline, report.event_cnt_online = len(offline), len(online)
    report._exact_match = offline == online
    expected, expected_order = _index_records(offline, "offline", report)
    actual, actual_order = _index_records(online, "online", report)
    report.cbsp_cnt_offline = sum(r["identity"]["kind"] == "open" for r in expected.values())
    report.cbsp_cnt_online = sum(r["identity"]["kind"] == "open" for r in actual.values())
    for event_id in sorted(expected.keys() - actual.keys()):
        report.mismatches.append({"type": "missing_event", "event_id": event_id})
    for event_id in sorted(actual.keys() - expected.keys()):
        report.mismatches.append({"type": "extra_event", "event_id": event_id})
    shared = expected.keys() & actual.keys()
    if [k for k in expected_order if k in shared] != [k for k in actual_order if k in shared]:
        report.mismatches.append({"type": "event_order"})
    for event_id in expected_order:
        if event_id in shared:
            paths = _payload_paths(expected[event_id]["payload"], actual[event_id]["payload"], ["payload"], rel_tol)
            report.mismatches.extend({"type": "payload_mismatch", "event_id": event_id, "path": path} for path in paths)
    return report


def _digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _time(klu):
    return None if klu is None else int(klu.time.ts * 1000)


def _line_state(line):
    state = {"idx": line.idx, "direction": line.dir.name, "is_sure": line.is_sure,
             "used_to_be_sure": line.used_to_be_sure, "seg_idx": line.seg_idx,
             "begin_ms": _time(line.get_begin_klu()), "end_ms": _time(line.get_end_klu()),
             "begin_price": line.get_begin_val(), "end_price": line.get_end_val()}
    if hasattr(line, "sure_end"):
        state.update(type=line.type.name, sure_end=[k.idx for k in line.sure_end])
    else:
        state.update(reason=line.reason, children=[b.idx for b in line.bi_list])
    return state


def _zone_state(zone):
    return {"begin_ms": _time(zone.begin), "end_ms": _time(zone.end), "is_sure": zone.is_sure,
            "begin_idx": zone.begin_bi.idx, "end_idx": zone.end_bi.idx,
            "low": zone.low, "high": zone.high, "mid": zone.mid,
            "peak_low": zone.peak_low, "peak_high": zone.peak_high,
            "in_idx": None if zone.bi_in is None else zone.bi_in.idx,
            "out_idx": None if zone.bi_out is None else zone.bi_out.idx,
            "children": [_zone_state(z) for z in zone.sub_zs_lst]}


def _level_state(data):
    # 每个分量承诺完整 canonical 内容，不按末端计数/四舍五入/过滤虚结构消除漂移。
    # 检查点保留摘要而不是重复保存完整历史图，限制诊断结果的内存大小。
    components = {
        "bars": [{**bar_snapshot(k), "idx": k.idx, "trade_info": k.trade_info.metric,
                  "pre_ms": _time(k.pre), "next_ms": _time(k.next), "parent_ms": _time(k.sup_kl),
                  "children_ms": [_time(c) for c in k.sub_kl_list]} for k in data.klu_iter()],
        "combined": [{"idx": k.idx, "direction": k.dir.name, "fx": k.fx.name,
                      "low": k.low, "high": k.high, "children": [c.idx for c in k]} for k in data],
        "bi": [_line_state(b) for b in data.bi_list],
        "seg": [_line_state(s) for s in data.seg_list],
        "segseg": [_line_state(s) for s in data.segseg_list],
        "zs": [_zone_state(z) for z in data.zs_list],
        "segzs": [_zone_state(z) for z in data.segzs_list],
    }
    for key, points in (("bsp", data.bs_point_lst), ("seg_bsp", data.seg_bs_point_lst)):
        components[key] = [{"anchor_ms": _time(p.klu), "is_buy": p.is_buy,
                            "is_segbsp": p.is_segbsp, "types": [t.value for t in p.type],
                            "line": _line_state(p.bi), "features": dict(p.features.items()),
                            "relate_ms": None if p.relate_bsp1 is None else _time(p.relate_bsp1.klu)}
                           for p in points.getSortedBspList()]
    return {k: {"count": len(v), "sha256": _digest(v)} for k, v in components.items()}


class _CReconcileChan(CChan):
    def __init__(self, *args, observe=True, **kwargs):
        self.observe = observe
        self.input_hashes = {}
        self.input_counts = {}
        self.checkpoints = []
        self.record_offsets = {}
        self.records = []
        super().__init__(*args, **kwargs)

    def load_stock_data(self, stockapi_instance, lv):
        for klu in super().load_stock_data(stockapi_instance, lv):
            # source bytes 在策略获得可变 KLU 之前记录，且包含量能和明确的市场来源。
            payload = canonical_bytes({**bar_snapshot(klu), "trade_info": klu.trade_info.metric})
            self.input_hashes.setdefault(lv, hashlib.sha256()).update(payload + b"\n")
            self.input_counts[lv] = self.input_counts.get(lv, 0) + 1
            yield klu

    def collect_records(self, lv):
        records = self[lv].cbsp_strategy.decision_records
        self.records.extend(records[self.record_offsets.get(lv, 0):])
        self.record_offsets[lv] = len(records)

    def update_cbsp_strategy(self, lv_idx):
        previous = self.strategy_last_idx.get(self.lv_list[lv_idx], -1)
        super().update_cbsp_strategy(lv_idx)
        if self.strategy_last_idx.get(self.lv_list[lv_idx], -1) <= previous:
            return
        if self.observe:
            self[lv_idx].cbsp_strategy.publish_signals(self, lv_idx)
            self.collect_records(lv_idx)
        self.checkpoints.append(canonical_bytes({"schema": "chan-reconcile-state-v1", "code": self.code,
            "level": self.lv_list[lv_idx].name, "decision_ms": _time(self[lv_idx][-1][-1]),
            "levels": [{"level": lv.name, "structures": _level_state(self[i]),
                        "dedupe": self[i].cbsp_strategy.decision_state()} for i, lv in enumerate(self.lv_list)]}))

    def manifest(self):
        return {lv.name: {"count": self.input_counts.get(lv, 0),
                          "sha256": self.input_hashes.get(lv, hashlib.sha256()).hexdigest()}
                for lv in self.lv_list}


def _native_outcome(chan):
    result = []
    for lv in range(len(chan.lv_list)):
        strategy = chan[lv].cbsp_strategy
        native = tuple(r for cb in strategy for r in (cb.open_decision, *(a.decision for a in cb.close_actions)))
        signals = tuple(s.decision for s in strategy.publish_signals(chan, lv)) if len(chan[lv]) else ()
        result.append((native, signals, canonical_bytes(strategy.decision_state())))
        if chan.observe:
            chan.collect_records(lv)
    return result


def feature_reconcile(
    code: str,
    chan_config: Dict,
    data_src=DATA_SRC.CSV,
    lv: KL_TYPE = KL_TYPE.K_DAY,
    begin_time: Optional[str] = None,
    end_time: Optional[str] = None,
    autype: AUTYPE = AUTYPE.NONE,
    rel_tol: float = 0.0,
    *,
    lv_list=None,
) -> CReconcileReport:
    if chan_config.get("cbsp_strategy") is None or chan_config.get("only_judge_last", False):
        raise CChanException("逐决策对账需要策略且不能 only_judge_last", ErrCode.PARA_ERROR)
    reconcile_decision_records((), (), rel_tol=rel_tol)  # 运行数据源前先校验容差。
    levels = list(lv_list) if lv_list is not None else [lv]
    common = dict(code=code, begin_time=begin_time, end_time=end_time, data_src=data_src,
                  lv_list=levels, autype=autype)
    chan_offline = _CReconcileChan(**common, config=CChanConfig({**chan_config, "trigger_step": False}))
    chan_online = _CReconcileChan(**common, config=CChanConfig({**chan_config, "trigger_step": True}))
    stockapi_cls = chan_offline.GetStockAPI()
    stockapi_cls.do_init()
    try:
        def stream(i):
            for klu in chan_online.get_load_stock_iter(stockapi_cls, levels[i]):
                yield i, klu
        streams = [stream(i) for i in range(len(levels))]
        merged = heapq.merge(*streams, key=lambda item: _time(item[1]))
        for _, group in itertools.groupby(merged, key=lambda item: _time(item[1])):
            payload = {level: [] for level in levels}
            for i, klu in group:
                payload[levels[i]].append(klu)
            chan_online.trigger_load(payload)
    finally:
        stockapi_cls.do_close()
    # 第三次独立 load 不观察历史信号，防止两条被观察路径因相同副作用而自证。
    control = _CReconcileChan(**common, observe=False, config=CChanConfig({**chan_config, "trigger_step": False}))
    offline_native, online_native, control_native = (_native_outcome(c) for c in (chan_offline, chan_online, control))
    report = reconcile_decision_records(chan_offline.records, chan_online.records, rel_tol=rel_tol)
    report.records_offline, report.records_online = tuple(chan_offline.records), tuple(chan_online.records)
    report.checkpoints_offline, report.checkpoints_online = tuple(chan_offline.checkpoints), tuple(chan_online.checkpoints)
    report.input_manifests = {"offline": chan_offline.manifest(), "online": chan_online.manifest(), "control": control.manifest()}
    report.input_verified = all(m == report.input_manifests["offline"] for m in report.input_manifests.values()) and all(
        p["count"] > 0 for p in report.input_manifests["offline"].values())
    if not report.input_verified:
        report.mismatches.append({"type": "input_mismatch", "manifests": report.input_manifests})
    if offline_native != control_native or chan_offline.checkpoints != control.checkpoints:
        report.mismatches.append({"type": "observer_effect"})
    for lane, chan, native in (("offline", chan_offline, offline_native), ("online", chan_online, online_native)):
        for i, (records, _, _) in enumerate(native):
            ledger = set(chan[i].cbsp_strategy.decision_records)
            if any(raw is None or raw not in ledger for raw in records):
                report.mismatches.append({"type": "missing_native_record", "lane": lane, "level": levels[i].name})
    if report.checkpoints_offline != report.checkpoints_online:
        report.mismatches.append({"type": "checkpoint_mismatch"})
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
    sys.exit(0 if rep.is_exact and rep.input_verified else 1)
