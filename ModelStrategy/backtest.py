"""回测样本落地:回放股票池,产出特征样本文件(libsvm+meta,兼容 Debug/strategy_demo5.py 格式)与五种标签

标签体系(只在回放结束后用未来数据打标,训练用,不进特征):
1. label_bsp_hold:    该位置最终仍是形态学 bsp
2. label_ret_N:       开仓后 N 根K线收益率是否 > x%
3. label_next_bsp:    到下一个反向 bsp 出现时的收益率符号
4. label_max_drawdown:触及止损线之前是否先达到止盈线
5. label_seg_confirm: 预期方向的线段最终被确认(is_sure)
"""
import json
import hashlib
import math
import os
from typing import Dict, List, Optional

from Chan import CChan
from ChanConfig import CChanConfig
from ChanModel.FeatureDesc import FEATURE_REG
from ChanModel.ModelContract import feature_code_identity, freeze_config
from Common.CEnum import AUTYPE, BI_DIR
from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import make_crypto_klu
from CustomBuySellPoint.Decision import bar_snapshot, canonical_bytes, read_decision

from .BacktestChanConfig import CBacktestConfig

LABEL_SEMANTICS = {"version": "observed-labels-v1", "structure_timing": "terminal-source-close", "barrier_tie": "loss-first"}


class CSample:
    def __init__(self, code: str, cbsp, labels: Dict[str, int], *, label_end_times=None):
        if cbsp.open_decision is None:
            raise CChanException("样本缺少已接受的开仓证据", ErrCode.MODEL_ERROR)
        decision = read_decision(cbsp.open_decision)
        if decision["identity"]["code"] != code:
            raise CChanException("样本 instrument 与开仓证据不一致", ErrCode.MODEL_ERROR)
        self.code = code
        self.cbsp = cbsp
        self.decision = cbsp.open_decision
        self.labels = dict(labels)
        self.label_end_times = dict(label_end_times or {})
        for name, value in self.labels.items():
            if value is not None and (type(value) is not int or value not in (0, 1)
                    or type(self.label_end_times.get(name)) is not int
                    or self.label_end_times[name] < decision["identity"]["decision_ms"]):
                raise CChanException("已知标签需要完整的观察结束时间", ErrCode.MODEL_ERROR)


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


class _CSampleChan(CChan):
    def __init__(self, *args, source_view=None, **kwargs):
        self.source_view = source_view
        self.input_hashes, self.input_counts, self.input_sources = {}, {}, {}
        super().__init__(*args, **kwargs)

    def GetStockAPI(self):
        if self.source_view is None:
            return super().GetStockAPI()
        view = self.source_view
        class CBoundPacketReader:
            @classmethod
            def do_init(cls):
                pass

            @classmethod
            def do_close(cls):
                pass

            def __init__(self, code, k_type, **kwargs):
                self.code, self.level = code, k_type

            def get_kl_data(self):
                for row in view["contract"][self.code][self.level.name]:
                    if row[0] < view["window"]["start_ms"]:
                        continue
                    unit = make_crypto_klu(row, self.level, now_ms=view["window"]["end_ms"])
                    unit.source_identity = dict(view["contract_source"])
                    yield unit
        return CBoundPacketReader

    def load_stock_data(self, stockapi_instance, lv):
        source = super().load_stock_data(stockapi_instance, lv)
        try:
            for klu in source:
                snapshot = bar_snapshot(klu)
                source_identity = snapshot.get("market")
                if lv in self.input_sources and self.input_sources[lv] != source_identity:
                    raise CChanException("同一输入流的市场来源发生漂移", ErrCode.MODEL_ERROR)
                self.input_sources[lv] = source_identity
                digest = self.input_hashes.setdefault(lv, hashlib.sha256())
                digest.update(canonical_bytes({**snapshot, "trade_info": klu.trade_info.metric}) + b"\n")
                self.input_counts[lv] = self.input_counts.get(lv, 0) + 1
                yield klu
        finally:
            source.close()

    def input_manifest(self):
        return {lv.name: {"count": self.input_counts[lv], "sha256": digest.hexdigest()}
                for lv, digest in self.input_hashes.items()}


def cal_labels(chan: CChan, cbsp, label_para: Dict, lv_idx: int = 0, *, with_end_times=False):
    """已知标签与实际观察结束时间；没观察完不是负例，终局结构不冒充端点时已确认。"""
    lv_data = chan[lv_idx]
    labels: Dict[str, int] = {}
    ends = {}
    all_klus = list(lv_data.klu_iter())
    decision = read_decision(cbsp.open_decision)
    identity, payload = decision["identity"], decision["payload"]
    at_ms, is_buy = identity["decision_ms"], identity["is_buy"]
    open_pos = next((i for i, k in enumerate(all_klus) if int(k.time.ts * 1000) == at_ms), None)
    if open_pos is None:
        raise CChanException("标签来源窗口缺少实际开仓决策时刻", ErrCode.MODEL_ERROR)
    def profit_at(price):
        return (price-payload["open_price"])/payload["open_price"] * (100 if is_buy else -100)

    # 1. label_bsp_hold:关联 bsp 最终仍在形态学 bsp 列表里(按 klu.idx+方向比对,
    #    bsp 对象在计算过程中会被重建,不能用对象身份比对;与 demo5 的 bsp_academy 逻辑一致)
    final_bsp_keys = {(int(b.klu.time.ts*1000), b.is_buy, False) for b in lv_data.bs_point_lst.bsp_iter()}
    final_bsp_keys.update((int(b.klu.time.ts*1000), b.is_buy, True) for b in lv_data.seg_bs_point_lst.bsp_iter())
    origin = payload["origin"]
    if open_pos < len(all_klus)-1:
        labels["label_bsp_hold"] = int(origin is not None and
            (origin["anchor_ms"], origin["is_buy"], origin["is_segbsp"]) in final_bsp_keys)
        ends["label_bsp_hold"] = int(all_klus[-1].time.ts * 1000)

    # 2. label_ret_N:开仓后 N 根K线收益率 > 阈值
    n, thred = label_para["ret_n"], label_para["ret_thred"]
    if type(n) is not int or n <= 0:
        raise CChanException("ret_n 必须为正整数", ErrCode.MODEL_ERROR)
    if any(type(label_para[k]) not in (int, float) or not math.isfinite(label_para[k])
           for k in ("ret_thred", "dd_profit", "dd_loss")) or min(label_para["dd_profit"], label_para["dd_loss"]) < 0:
        raise CChanException("标签阈值必须有限，barrier 幅度非负", ErrCode.MODEL_ERROR)
    if open_pos + n < len(all_klus):
        labels["label_ret_N"] = int(profit_at(all_klus[open_pos + n].close) > thred * 100)
        ends["label_ret_N"] = int(all_klus[open_pos + n].time.ts * 1000)

    # 3. label_next_bsp:到下一个反向 bsp 出现时的收益率符号
    for bsp in lv_data.bs_point_lst.getSortedBspList():
        if int(bsp.klu.time.ts*1000) > at_ms and bsp.is_buy != is_buy:
            labels["label_next_bsp"] = int(profit_at(bsp.klu.close) > 0)
            ends["label_next_bsp"] = int(all_klus[-1].time.ts * 1000)
            break

    # 4. label_max_drawdown:先触止盈(+x%)还是先触止损(-y%)
    profit_thred, loss_thred = label_para["dd_profit"] * 100, label_para["dd_loss"] * 100
    for klu in all_klus[open_pos + 1:]:
        best = profit_at(klu.high if is_buy else klu.low)
        worst = profit_at(klu.low if is_buy else klu.high)
        if worst < -loss_thred:
            labels["label_max_drawdown"] = 0
            ends["label_max_drawdown"] = int(klu.time.ts * 1000)
            break
        if best > profit_thred:
            labels["label_max_drawdown"] = 1
            ends["label_max_drawdown"] = int(klu.time.ts * 1000)
            break

    # 5. label_seg_confirm:预期方向的线段最终被确认
    expect_dir = BI_DIR.UP if is_buy else BI_DIR.DOWN
    for seg in lv_data.seg_list:
        if int(seg.end_bi.get_end_klu().time.ts*1000) >= at_ms and seg.dir == expect_dir and seg.is_sure:
            labels["label_seg_confirm"] = 1
            ends["label_seg_confirm"] = int(all_klus[-1].time.ts * 1000)
            break
    return (labels, ends) if with_end_times else labels


def run_backtest(bt_conf: CBacktestConfig, *, source_data=None) -> CBacktestResult:
    source_view = None
    if source_data is not None:
        from .parameterEvaluate.crypto_evaluate import CCryptoEvaluationData
        from OfflineData.offline_data_util import parse_dt_to_ts
        if not isinstance(source_data, CCryptoEvaluationData) or not bt_conf.begin_time or not bt_conf.end_time:
            raise CChanException("显式数据包训练需要真实 packet 与完整 UTC 起止窗口", ErrCode.MODEL_ERROR)
        try:
            source_view = source_data.view(start_ms=parse_dt_to_ts(bt_conf.begin_time), end_ms=parse_dt_to_ts(bt_conf.end_time))
        except (ValueError, TypeError) as error:
            raise CChanException("显式数据包训练窗口格式无效", ErrCode.MODEL_ERROR) from error
        if (set(bt_conf.code_list) != set(source_view["contract"]) or len(set(bt_conf.code_list)) != len(bt_conf.code_list)
                or any(lv.name not in source_view["contract"][code] for code in bt_conf.code_list for lv in bt_conf.lv_list)
                or bt_conf.chan_config.get("trigger_step") or bt_conf.autype != AUTYPE.NONE):
            raise CChanException("训练标的/级别或复权方式与显式数据包不匹配", ErrCode.MODEL_ERROR)
    samples: List[CSample] = []
    input_manifests = {}
    source_identities = {}
    for code in bt_conf.code_list:
        chan_conf = dict(bt_conf.chan_config)
        if chan_conf.get("cbsp_strategy") is None:
            from CustomBuySellPoint.CustomStrategy import CCustomStrategy
            chan_conf["cbsp_strategy"] = CCustomStrategy
        chan = _CSampleChan(
            code=code,
            begin_time=bt_conf.begin_time,
            end_time=bt_conf.end_time,
            data_src=bt_conf.data_src,
            lv_list=bt_conf.lv_list,
            config=CChanConfig(chan_conf),
            autype=bt_conf.autype,
            source_view=source_view,
        )
        input_manifests[code] = chan.input_manifest()
        source_identities[code] = {lv.name: identity for lv, identity in chan.input_sources.items()}
        strategy = chan[bt_conf.lv_idx].cbsp_strategy
        assert strategy is not None
        for cbsp in strategy:
            labels, ends = cal_labels(chan, cbsp, bt_conf.label_para, bt_conf.lv_idx, with_end_times=True)
            samples.append(CSample(code, cbsp, labels, label_end_times=ends))
    feature_meta, unregistered = write_samples(samples, bt_conf.output_dir, bt_conf.primary_label,
        label_parameters=bt_conf.label_para, generation_context=freeze_config({
            "chan_config": bt_conf.chan_config, "lv_list": bt_conf.lv_list, "trade_lv_idx": bt_conf.lv_idx,
            "code_list": sorted(bt_conf.code_list), "begin_time": bt_conf.begin_time, "end_time": bt_conf.end_time,
            "data_src": "explicit-crypto-evaluation-packet" if source_view is not None else bt_conf.data_src,
            "autype": bt_conf.autype, "input_manifests": input_manifests,
            "source_identities": source_identities}))
    return CBacktestResult(samples, bt_conf.output_dir, feature_meta, unregistered)


def write_samples(samples: List[CSample], output_dir: str, primary_label: str, *, label_parameters=None, generation_context=None):
    """保留全部样本说明，libsvm 只含主标签已知行；原 meta 格式保留并绑定 manifest。"""
    prepared = []
    for sample in samples:
        decision = read_decision(sample.decision)
        ident, payload = decision["identity"], decision["payload"]
        if (not isinstance(payload.get("features"), dict)
                or any(not isinstance(name, str) or not name or
                       (value is not None and (type(value) not in (int, float, bool) or not math.isfinite(value)))
                       for name, value in payload["features"].items())):
            raise CChanException("样本特征必须为有限数字或显式缺失值", ErrCode.MODEL_ERROR)
        prepared.append((ident["decision_ms"], sample.code, decision["event_id"], sample, ident, payload))
    prepared.sort(key=lambda row: row[:3])
    if len({row[2] for row in prepared}) != len(prepared):
        raise CChanException("重复样本 event identity", ErrCode.MODEL_ERROR)
    names = sorted({name for _, _, _, _, _, payload in prepared for name in payload["features"]})
    feature_meta = {name: i for i, name in enumerate(names)}
    training_row, rows, libsvm = 0, [], []
    for _, _, event_id, sample, ident, payload in prepared:
        label = sample.labels.get(primary_label)
        end_ms = sample.label_end_times.get(primary_label) if label is not None else None
        if label is not None and (type(label) is not int or label not in (0, 1)
                or type(end_ms) is not int or end_ms < ident["decision_ms"]):
            raise CChanException("主标签缺少观察结束证据", ErrCode.MODEL_ERROR)
        features = [(feature_meta[name], float(value)) for name, value in payload["features"].items() if value is not None]
        features.sort()
        row = {"schema": "chan-samples-v1", "event_id": event_id, "code": sample.code,
               "level": ident["level"], "market": ident["market"], "decision_ms": ident["decision_ms"],
               "feature_available_at_ms": ident["decision_ms"], "label_end_ms": end_ms,
               "label_end_times": sample.label_end_times, "primary_label": primary_label, "label": label,
               "training_row": training_row if label is not None else None,
               "decision_sha256": hashlib.sha256(sample.decision).hexdigest(),
               "features": payload["features"],
               "features_sha256": hashlib.sha256(canonical_bytes(payload["features"])).hexdigest(),
               "time": sample.cbsp.klu.time.to_str(), "is_buy": ident["is_buy"], "bs_type": ident["bs_type"],
               "is_segbsp": ident["is_segbsp"], "open_price": payload["open_price"],
               "profit": sample.cbsp.profit,
               "cover_reason": sample.cbsp.close_actions[-1].reason if sample.cbsp.close_actions else None,
               "labels": sample.labels}
        rows.append(canonical_bytes(row).decode("utf-8"))
        if label is not None:
            libsvm.append(f"{label} " + " ".join(f"{idx}:{value}" for idx, value in features))
            training_row += 1
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "feature.libsvm"), "w", encoding="utf-8") as fid, \
         open(os.path.join(output_dir, "sample_info.jsonl"), "w", encoding="utf-8") as finfo:
        fid.writelines(line + "\n" for line in libsvm)
        finfo.writelines(line + "\n" for line in rows)
    with open(os.path.join(output_dir, "feature.meta"), "w", encoding="utf-8") as fmeta:
        fmeta.write(canonical_bytes(feature_meta).decode("utf-8"))
    files = {}
    for name in ("feature.libsvm", "feature.meta", "sample_info.jsonl"):
        with open(os.path.join(output_dir, name), "rb") as handle:
            files[name] = hashlib.sha256(handle.read()).hexdigest()
    with open(os.path.join(output_dir, "sample_manifest.json"), "w", encoding="utf-8") as manifest:
        manifest.write(canonical_bytes({"schema": "chan-samples-v1", "primary_label": primary_label,
            "generation_context": generation_context, "feature_code": feature_code_identity(),
            "label_definition": {**LABEL_SEMANTICS, "parameters": label_parameters},
            "known_count": training_row, "unknown_count": len(rows)-training_row, "files": files}).decode("utf-8"))
    unregistered = FEATURE_REG.check_features(feature_meta.keys())
    if unregistered:
        print(f"[WARNING] 存在未注册特征 {len(unregistered)} 个: {unregistered[:10]} ...")
    return feature_meta, unregistered
