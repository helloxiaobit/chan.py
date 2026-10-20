"""统一部署身份与评分配置；不是 candidate、测试网或实盘准入收据。"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

from Chan import CChan
from ChanConfig import CChanConfig
from ChanModel.FeatureEngine import CFeatureEngine
from ChanModel.GeneratorModel import CGeneratorModel
from ChanModel.ModelContract import freeze_config, read_model_contract
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from Common.ChanException import CChanException, ErrCode
from Common.func_util import check_kltype_order
from Common.KLineTime import utc_now_ms
from CustomBuySellPoint.CustomBSP import CCustomBSP
from CustomBuySellPoint.CustomStrategy import CCustomStrategy
from CustomBuySellPoint.MultiLevelStrategy import CMultiLevelStrategy
from CustomBuySellPoint.Signal import CSignal
from CustomBuySellPoint.Decision import bar_snapshot, bsp_origin_snapshot, canonical_bytes, read_decision
from OfflineData.offline_data_util import CKLineDB, validate_source_identity

SCHEMA = "chan-deployment-v1"
PHASES = {"candidate": "closed-signal-at-threshold", "entry": "closed-signal-at-observed-quote",
          "post": "closed-execution-interval"}
STRATEGIES = {f"{c.__module__}.{c.__qualname__}": c for c in (CCustomStrategy, CMultiLevelStrategy)}


def _workflow_identity():
    root = Path(__file__).resolve().parents[2]
    names = ("Trade/Script/Deployment.py", "Trade/Script/StaticsChanConfig.py", "Trade/Script/SignalMonitor.py",
             "Trade/Script/MakeOpenTrade.py", "Trade/Script/CheckOpenScore.py", "Trade/TradeEngine.py",
             "Trade/db_util.py", "Trade/SqliteDB.py")
    hashes = {name: hashlib.sha256((root/name).read_text(encoding="utf-8").replace("\r\n", "\n").encode()).hexdigest()
              for name in names}
    return hashlib.sha256(canonical_bytes(hashes)).hexdigest()


def _error(message):
    return CChanException(message, ErrCode.MODEL_ERROR)


def _restore(value):
    if isinstance(value, list):
        return [_restore(v) for v in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"class"}:
        if value["class"] not in STRATEGIES:
            raise _error("部署策略类未获得软件适配，不允许动态导入")
        return STRATEGIES[value["class"]]
    if set(value) == {"enum", "name"}:
        allowed = {f"{c.__module__}.{c.__qualname__}": c for c in (AUTYPE, DATA_SRC, KL_TYPE)}
        return allowed[value["enum"]][value["name"]]
    if set(value) == {"nonfinite_config"}:
        number = value["nonfinite_config"]
        if number not in ("inf", "-inf"):
            raise _error("不支持的非有限配置值")
        return float(number)
    return {k: _restore(v) for k, v in value.items()}


def _thresholds(values):
    if set(values) != set(PHASES) or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
                                       for v in values.values()):
        raise _error("部署三个阶段均须有有限概率阈值")
    return dict(values)


def _scope(contract):
    context = contract["generation_context"]
    if not isinstance(context, dict):
        raise _error("模型缺少实际训练的策略/来源上下文，不能补写部署证据")
    config = _restore(context["chan_config"])
    strategy = config.get("cbsp_strategy", CCustomStrategy)
    if strategy not in STRATEGIES.values() or config.get("model") is not None or config.get("only_judge_last", False):
        raise _error("部署需要已适配的逐 K 策略且不能隐式替换训练时过滤模型")
    levels = _restore(context["lv_list"])
    check_kltype_order(levels)
    trade_lv = context["trade_lv_idx"]
    if (not levels or any(not isinstance(lv, KL_TYPE) for lv in levels) or type(trade_lv) is not int
            or not 0 <= trade_lv < len(levels) or (strategy is CMultiLevelStrategy and trade_lv != (1 if len(levels)>1 else 0))):
        raise _error("模型交易级别/策略角色不一致")
    codes = context["code_list"]
    if not codes or len(set(codes)) != len(codes) or any(not isinstance(c, str) or "/" not in c for c in codes):
        raise _error("部署只支持明确的虚拟货币 symbol")
    sources = [context["source_identities"][code][lv.name] for code in codes for lv in levels]
    source = validate_source_identity(sources[0])
    if any(s != source for s in sources):
        raise _error("训练来源不完整或混用，不能导出统一部署")
    if (source["price_type"] != "contract" or source["exchange"] not in {"binance", "okx"}
            or source["market_type"] not in {"spot", "swap"}
            or (source["market_type"] == "swap" and (source["settle"] != "USDT" or any(not c.endswith(":USDT") for c in codes)))):
        raise _error("本部署仅适配 Binance/OKX spot 或 USDT 线性永续 contract 输入")
    for code in codes:
        for lv in levels:
            evidence = context["input_manifests"][code][lv.name]
            if type(evidence["count"]) is not int or evidence["count"] <= 0 or len(evidence["sha256"]) != 64:
                raise _error("缺少实际训练输入摘要")
    config["cbsp_strategy"] = strategy
    return config, levels, sorted(codes), trade_lv, source


def publish_deployment(path, model_path, *, candidate_score, entry_score, post_score):
    destination, model_path = Path(path).resolve(), Path(model_path).resolve()
    thresholds = _thresholds({"candidate": candidate_score, "entry": entry_score, "post": post_score})
    try:
        contract, artifact_id = read_model_contract(model_path, model_path.with_suffix(".meta"))
        _scope(contract)
        body = {"schema": SCHEMA, "model_path": os.path.relpath(model_path, destination.parent).replace("\\", "/"),
                "model_artifact_id": artifact_id, "thresholds": thresholds, "score_phases": PHASES,
                "workflow_sha256": _workflow_identity(),
                "generation_context": contract["generation_context"]}
        deployment_id = hashlib.sha256(canonical_bytes(body)).hexdigest()
        raw = canonical_bytes({**body, "deployment_id": deployment_id})
        if destination.exists() or not destination.parent.is_dir():
            raise _error("部署目标已存在或父目录不存在，禁止覆盖")
        fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, destination)
        finally:
            os.unlink(temporary)
        return deployment_id
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
        raise _error("部署清单缺少完整证据或 write-once 发布失败") from exc


class CDeployment:
    def __init__(self, path):
        try:
            self.path = Path(path).resolve()
            raw = self.path.read_bytes()
            body = json.loads(raw)
            identity = body.pop("deployment_id")
            if (set(body) != {"schema", "model_path", "model_artifact_id", "thresholds", "score_phases", "generation_context", "workflow_sha256"}
                    or body["schema"] != SCHEMA or body["score_phases"] != PHASES
                    or body["workflow_sha256"] != _workflow_identity()
                    or identity != hashlib.sha256(canonical_bytes(body)).hexdigest()
                    or canonical_bytes({**body, "deployment_id": identity}) != raw):
                raise _error("部署 canonical 字节或身份漂移")
            self.thresholds = _thresholds(body["thresholds"])
            model_path = (self.path.parent / body["model_path"]).resolve()
            self.model = CGeneratorModel(str(model_path))
            if (self.model.artifact_id != body["model_artifact_id"]
                    or body["generation_context"] != self.model.contract["generation_context"]):
                raise _error("部署模型或训练配置身份漂移")
            self._config, self.lv_list, self.code_list, self.trade_lv_idx, self.source_identity = _scope(self.model.contract)
            self.deployment_id, self.record = identity, {**body, "deployment_id": identity}
        except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
            raise _error("部署清单或模型配置不完整/不兼容") from exc

    @property
    def chan_config(self):
        config = copy.deepcopy(self._config)
        config.update(model=self.model, score_thred=self.thresholds["entry"], trigger_step=False)
        return config

    @classmethod
    def configured(cls):
        from Config.EnvConfig import CEnv
        env = CEnv.get_instance()
        path = env.get_section("trade").get("deployment_manifest")
        if path is not None:
            if not isinstance(path, str) or not path:
                raise _error("deployment_manifest 必须是明确文件路径")
            return cls(env.abs_path(path))
        if env.model_conf.get("required") or env.model_conf.get("path"):
            raise _error("模型被要求或配置，但缺少统一 deployment_manifest")
        return None

    def check_overrides(self, extra):
        expected = self.chan_config
        if any(k not in expected or canonical_bytes(freeze_config(v)) != canonical_bytes(freeze_config(expected[k]))
               for k, v in (extra or {}).items()):
            raise _error("运行配置不能覆盖已绑定的策略/特征/阈值")

    def check_source(self, source):
        if validate_source_identity(source) != self.source_identity:
            raise _error("运行市场来源与部署身份不一致")

    def build_chan(self, code, cutoff_ms):
        self._check_clock(cutoff_ms)
        if code not in self.code_list:
            raise _error("symbol 不在冻结部署范围")
        with CKLineDB() as db:
            self.check_source(db.source_identity)
        # 当前模型只用于当前准入；不能用新权重重写训练前的策略状态。
        config = copy.deepcopy(self._config)
        config.update(model=None, trigger_step=False)
        return _CClosedPrefixChan(code=code, lv_list=self.lv_list, config=CChanConfig(config),
            autype=_restore(self.record["generation_context"]["autype"]),
            begin_time=self.record["generation_context"]["begin_time"],
            data_src="custom:OfflineDataAPI.CStockFileReader", cutoff_ms=cutoff_ms)

    def _check_clock(self, at_ms):
        if (type(at_ms) is not int or at_ms < self.model.contract["training_window"]["last_label_end_ms"]
                or at_ms > utc_now_ms()):
            raise _error("评分时刻早于训练标签可用窗口或晚于实际时钟")

    def prepare_signal(self, chan, signal, *, observed_ms, phase="candidate", price=None):
        self._check_clock(observed_ms)
        lv = self.trade_lv_idx
        if (phase not in PHASES or signal.code not in self.code_list or chan.code != signal.code
                or signal.lv != self.lv_list[lv] or signal.bsp is None
                or signal.sig_klu.time.ts != chan[lv][-1][-1].time.ts):
            raise _error("模型信号缺少真实来源或 instrument/level/anchor 不匹配")
        available = max(int(chan[i][-1][-1].time.ts * 1000) for i in range(len(self.lv_list)) if len(chan[i]))
        if available > observed_ms:
            raise _error("评分上下文包含观察时刻之后的数据")
        bar = bar_snapshot(signal.sig_klu)
        self.check_source(bar.get("market"))
        price = signal.open_thred if price is None else price
        if type(price) not in (int, float) or not math.isfinite(price) or price <= 0:
            raise _error("评分观察价格必须有限且为正")
        candidate = CCustomBSP(signal.bsp, signal.sig_klu, signal.bs_type, signal.is_buy,
            target_klc=signal.target_klc, price=price, sl_price=signal.sl_thred, is_segbsp=signal.is_segbsp)
        candidate.add_feat(CFeatureEngine.cal_features(chan, lv, candidate))
        features = dict(candidate.features.items())
        score = self.model.predict(candidate)
        snapshot = {"schema": "chan-score-v1", "phase": phase, "phase_contract": PHASES[phase],
                    "deployment_id": self.deployment_id, "model_artifact_id": self.model.artifact_id,
                    "decision_ms": observed_ms, "feature_available_at_ms": available,
                    "bar": bar, "observed_price": price, "score": score,
                    "threshold": self.thresholds[phase], "passed": score >= self.thresholds[phase],
                    "origin": bsp_origin_snapshot(signal.bsp, observed_ms), "features": features,
                    "features_sha256": hashlib.sha256(canonical_bytes(features)).hexdigest()}
        canonical_bytes(snapshot)
        signal.score, signal.assessment = score, snapshot
        signal.model_artifact_id, signal.deployment_id = self.model.artifact_id, self.deployment_id
        signal.deployment_path = str(self.path)
        return snapshot

    def assess_entry(self, record, price, *, observed_ms):
        original = read_decision(record["signal_decision"].encode("utf-8"))
        verify_signal_assessment(self, original)
        if record.get("deployment_id") != self.deployment_id or record.get("model_version") != self.model.artifact_id:
            raise _error("当前部署与候选信号版本不一致")
        chan = self.build_chan(record["stock_code"], observed_ms)
        candidates = chan[self.trade_lv_idx].cbsp_strategy.bsp_signal(chan, self.trade_lv_idx)
        for candidate in candidates:
            origin = bsp_origin_snapshot(candidate.bsp, observed_ms)
            if (candidate.is_buy == bool(record["is_buy"]) and candidate.bs_type == record["bstype"]
                    and candidate.open_thred == original["payload"]["open_thred"]
                    and candidate.sl_thred == original["payload"]["sl_thred"]
                    and int(candidate.sig_klu.time.ts*1000) == original["identity"]["anchor_ms"]
                    and origin["anchor_ms"] == original["payload"]["origin"]["anchor_ms"]):
                assessment = self.prepare_signal(chan, candidate, observed_ms=observed_ms, phase="entry", price=price)
                assessment["signal_event_id"] = original["event_id"]
                if not assessment["passed"]:
                    raise _error("entry_score_filtered")
                return assessment
        raise _error("候选上下文已失效，不能用旧分数开仓")

    def assess_post(self, record, close_ms):
        original = read_decision(record["signal_decision"].encode("utf-8"))
        verify_signal_assessment(self, original)
        chan = self.build_chan(record["stock_code"], close_ms)
        lv = self.trade_lv_idx
        if int(chan[lv][-1][-1].time.ts*1000) != close_ms:
            raise _error("后验缺少指定收盘周期")
        points = chan[lv].seg_bs_point_lst if original["identity"]["is_segbsp"] else chan[lv].bs_point_lst
        for point in points.getSortedBspList():
            if (int(point.klu.time.ts*1000) == original["payload"]["origin"]["anchor_ms"]
                    and point.is_buy == original["identity"]["is_buy"]):
                signal = CSignal(record["stock_code"], self.lv_list[lv], point.is_buy, original["identity"]["bs_type"],
                    chan[lv][-1][-1], original["payload"]["open_thred"], sl_thred=original["payload"]["sl_thred"],
                    is_segbsp=original["identity"]["is_segbsp"], bsp=point)
                snapshot = self.prepare_signal(chan, signal, observed_ms=close_ms, phase="post", price=signal.sig_klu.close)
                snapshot["signal_event_id"] = original["event_id"]
                return snapshot
        raise _error("后验原始机会已失效，不能伪造来源特征")


def validate_assessment(snapshot, *, phase, deployment_id, model_artifact_id):
    if not isinstance(snapshot, dict):
        raise _error("模型评分证据必须是对象")
    bar, features = snapshot.get("bar"), snapshot.get("features")
    if (not isinstance(bar, dict) or not isinstance(features, dict) or not features
            or any(not isinstance(k, str) or not k or type(v) not in (int, float) or not math.isfinite(v)
                   for k, v in features.items())
            or any(type(snapshot.get(k)) is not int or snapshot[k] < 0
                   for k in ("decision_ms", "feature_available_at_ms"))
            or any(type(bar.get(k)) is not int or bar[k] < 0
                   for k in ("open_ms", "close_ms", "available_at_ms", "time_ms"))
            or not bar["open_ms"] < bar["close_ms"] == bar["time_ms"] <= snapshot["feature_available_at_ms"]
            or bar["available_at_ms"] > bar["close_ms"]
            or type(snapshot.get("observed_price")) not in (int, float)
            or not math.isfinite(snapshot["observed_price"]) or snapshot["observed_price"] <= 0):
        raise _error("模型评分缺少有限特征、真实观察价或可用的收盘周期")
    if (snapshot.get("schema") != "chan-score-v1"
            or snapshot.get("phase") != phase or snapshot.get("phase_contract") != PHASES[phase]
            or snapshot.get("deployment_id") != deployment_id or snapshot.get("model_artifact_id") != model_artifact_id
            or snapshot["feature_available_at_ms"] > snapshot["decision_ms"]
            or type(snapshot.get("passed")) is not bool
            or snapshot.get("features_sha256") != hashlib.sha256(canonical_bytes(snapshot["features"])).hexdigest()
            or any(type(snapshot.get(k)) not in (int, float) or not math.isfinite(snapshot[k]) or not 0 <= snapshot[k] <= 1
                   for k in ("score", "threshold"))
            or snapshot["passed"] != (snapshot["score"] >= snapshot["threshold"])):
        raise _error("模型评分证据缺失、漂移或阶段不一致")
    canonical_bytes(snapshot)
    return snapshot


def verify_signal_assessment(deployment, decision):
    identity, payload = decision["identity"], decision["payload"]
    assessment = validate_assessment(payload.get("assessment"), phase="candidate", deployment_id=deployment.deployment_id,
        model_artifact_id=deployment.model.artifact_id)
    if (identity["kind"] != "signal" or identity["code"] not in deployment.code_list
            or identity["level"] != deployment.lv_list[deployment.trade_lv_idx].name
            or payload["deployment_id"] != deployment.deployment_id or payload["model_artifact_id"] != deployment.model.artifact_id
            or assessment["threshold"] != deployment.thresholds["candidate"] or not assessment["passed"]
            or assessment["score"] != deployment.model.generator.predict_features(assessment["features"])):
        raise _error("候选模型/部署/评分证据漂移")
    deployment.check_source(identity["market"])
    return assessment


def verify_entry_assessment(record, snapshot, price, engine):
    """订单意图的最后本地门槛；不替代引擎原有 candidate/模式/资金安全门禁。"""
    if not record.get("deployment_path") or not record.get("signal_decision"):
        raise _error("部署 entry 缺少原始信号/清单")
    deployment = CDeployment(record["deployment_path"])
    if deployment.deployment_id != record.get("deployment_id") or deployment.model.artifact_id != record.get("model_version"):
        raise _error("订单部署/模型版本漂移")
    signal = read_decision(record["signal_decision"].encode("utf-8"))
    verify_signal_assessment(deployment, signal)
    assessment = validate_assessment(snapshot, phase="entry", deployment_id=deployment.deployment_id,
                                     model_artifact_id=deployment.model.artifact_id)
    deployment._check_clock(assessment["decision_ms"])
    if (assessment.get("signal_event_id") != signal["event_id"] or assessment.get("observed_price") != price
            or signal["identity"]["code"] != record["stock_code"] or signal["identity"]["level"] != record["lv"]
            or signal["identity"]["is_buy"] != bool(record["is_buy"]) or signal["identity"]["bs_type"] != record["bstype"]
            or signal["payload"]["open_thred"] != record["open_thred"] or signal["payload"]["sl_thred"] != record["sl_thred"]
            or assessment["threshold"] != deployment.thresholds["entry"] or not assessment["passed"]
            or assessment["score"] != deployment.model.generator.predict_features(assessment["features"])):
        raise _error("entry 评分未通过或与订单/模型内容漂移")
    deployment.check_source(assessment["bar"].get("market"))
    if (getattr(engine, "market_type", None) != deployment.source_identity["market_type"]
            or getattr(engine, "ccxt_conf", {}).get("exchange") != deployment.source_identity["exchange"]):
        raise _error("部署行情与订单账户的交易所/市场类型不一致")
    return assessment


class _CClosedPrefixChan(CChan):
    def __init__(self, *args, cutoff_ms, **kwargs):
        self.cutoff_ms = cutoff_ms
        super().__init__(*args, **kwargs)

    def load_stock_data(self, stockapi_instance, lv):
        source = super().load_stock_data(stockapi_instance, lv)
        try:
            for klu in source:
                if int(klu.time.ts * 1000) > self.cutoff_ms:
                    break
                yield klu
        finally:
            source.close()
