"""C6 行情/模型/信号输入观察；不是原生账户或策略准入收据。"""
import hashlib
import json
import math
import re
import copy
import platform
from pathlib import Path

from Common.CEnum import KL_TYPE
from Common.ChanException import CChanException, ErrCode
from Common.KLineTime import bar_close_ms, utc_now_ms
from Config.EnvConfig import CEnv
from CustomBuySellPoint.Decision import canonical_bytes, read_decision
from OfflineData.offline_data_util import CKLineDB, validate_source_identity


def _fail():
    raise CChanException("开仓行情/模型/信号输入已失效或来源不符，禁止新增风险", ErrCode.TRADE_UNLOCK_FAIL) from None


def _sha(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _clock(value):
    if type(value) is not int or not 0 <= value < 2**63:
        _fail()
    return value


def _evaluator_identity():
    from ChanModel.ModelContract import feature_code_identity
    root = Path(__file__).resolve().parents[2]
    paths = ("Trade/Script/OpeningInputs.py", "Trade/Script/RunTradeCycle.py", "Trade/Script/MakeOpenTrade.py",
        "Trade/Script/SignalMonitor.py", "Trade/TradeEngine.py", "Trade/CCXTTradeEngine.py", "Trade/OrderAudit.py",
        "Trade/Script/StaticsChanConfig.py", "Trade/Script/OpenConfig.py", "Trade/Script/Deployment.py", "Config/EnvConfig.py",
        "OfflineData/offline_data_util.py", "CustomBuySellPoint/Decision.py", "CustomBuySellPoint/Signal.py")
    files = {name: hashlib.sha256((root/name).read_text(encoding="utf-8").replace("\r\n", "\n").encode()).hexdigest()
             for name in paths}
    return _sha({"input_code": files, "strategy_features": feature_code_identity()["sha256"],
        "python": platform.python_version(), "implementation": platform.python_implementation()})


def read_cycle_scope(env):
    source = validate_source_identity(env.offline_data_conf.get("source_identity"))
    if (source["exchange"] not in {"binance", "okx"} or source["price_type"] != "contract"
            or source["market_type"] not in {"spot", "swap"}
            or env.ccxt_conf.get("exchange") != source["exchange"]
            or env.ccxt_conf.get("default_type") != source["market_type"]):
        _fail()
    trade, model = env.get_section("trade"), env.model_conf
    deployment = trade.get("deployment_manifest")
    if deployment is not None:
        if not isinstance(deployment, str) or not deployment:
            _fail()
        from .Deployment import CDeployment
        deployed = CDeployment(env.abs_path(deployment))
        if deployed.source_identity != source:
            _fail()
        codes, levels = deployed.code_list, deployed.lv_list
        strategy, trade_index = deployed._config["cbsp_strategy"].__name__, deployed.trade_lv_idx
        model = {"deployment_id": deployed.deployment_id, "model_artifact_id": deployed.model.artifact_id}
    else:
        if model.get("required") or model.get("path"):
            _fail()
        codes, names, strategy = trade.get("code_list"), trade.get("lv_list"), trade.get("strategy")
        if names is None and "lv" in trade:
            names = [trade["lv"]]
        if not isinstance(names, list) or not names or any(type(name) is not str or name not in KL_TYPE.__members__ for name in names):
            _fail()
        levels = [KL_TYPE[name] for name in names]
        if strategy not in {"custom", "multi_lv"}:
            _fail()
        trade_index = 1 if strategy == "multi_lv" and len(levels) >= 2 else 0
        model = {"deployment_id": None, "model_artifact_id": None}
    pattern = r"[A-Za-z0-9._-]+/USDT:USDT" if source["market_type"] == "swap" else r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+"
    if (not isinstance(codes, list) or not codes or any(not isinstance(code, str) or re.fullmatch(pattern, code) is None for code in codes)
            or len(codes) != len(set(codes)) or (source["market_type"] == "swap" and source["settle"] != "USDT")
            or any(left.value <= right.value for left, right in zip(levels, levels[1:]))):
        _fail()
    return {"code_list": codes, "lv_list": [lv.name for lv in levels], "trade_lv": levels[trade_index].name,
            "strategy": strategy, "source": source, "input_evaluator_sha256": _evaluator_identity(), **model}


def inspect_opening_inputs(env, *, now_ms):
    """同一只读事务观察实际 closed rows；水位相同不代表原始值相同。"""
    try:
        now_ms = _clock(now_ms)
        scope = read_cycle_scope(env)
        quality, manifests = [], []
        with CKLineDB(env.abs_path(env.offline_data_conf["sqlite_path"]), read_only=True) as market:
            market.conn.execute("BEGIN")
            market.check_source(scope["source"])
            for code in scope["code_list"]:
                for name in scope["lv_list"]:
                    level = KL_TYPE[name]
                    item = market.inspect_quality(code, level, now_ms=now_ms)
                    if not item["ready"]:
                        _fail()
                    rows = [row for row in market.query_klines(code, level) if bar_close_ms(row[0], level) <= now_ms]
                    manifests.append({"code": code, "level": name, "rows_sha256": _sha(rows),
                        "count": len(rows), "latest_close_ms": item["latest_close_ms"]})
                    quality.append(item)
        return {"scope": scope, "quality": quality, "scope_sha256": _sha(scope),
                "inputs_sha256": _sha({"scope": scope, "manifests": manifests})}
    except Exception:
        _fail()


class COpeningInputs:
    def __init__(self, config_path, *, expected=None, now_ms=None):
        self.path, self.now_ms = Path(config_path).resolve(), now_ms or utc_now_ms
        try:
            raw = self.path.read_bytes()
            self._env = CEnv(str(self.path))
            self._config_sha = hashlib.sha256(raw).hexdigest()
            if hashlib.sha256(self.path.read_bytes()).hexdigest() != self._config_sha:
                _fail()
            observation = inspect_opening_inputs(self.env, now_ms=self.now_ms())
            self._scope = observation["scope"]
            self._expected = {"config_sha256": self._config_sha,
                **{key: observation[key] for key in ("scope_sha256", "inputs_sha256")}}
            if expected is not None and expected != self._expected:
                _fail()
        except Exception:
            _fail()

    @property
    def env(self):
        return copy.deepcopy(self._env)  # 交给 broker 的可变配置不是检查器自己的冻结配置。

    @property
    def scope(self):
        return json.loads(canonical_bytes(self._scope))

    def snapshot(self):
        return dict(self._expected)

    def assert_current(self):
        try:
            if hashlib.sha256(self.path.read_bytes()).hexdigest() != self._config_sha:
                _fail()
            observed = inspect_opening_inputs(self.env, now_ms=self.now_ms())
            if any(observed[key] != self._expected[key] for key in ("scope_sha256", "inputs_sha256")):
                _fail()
            return observed
        except Exception:
            _fail()

    def check(self, record, *, engine=None):
        try:
            checked = _clock(self.now_ms())
            self.assert_current()
            scope = self._scope
            if (record["stock_code"] not in scope["code_list"] or record["lv"] != scope["trade_lv"]
                    or record.get("deployment_id") != scope["deployment_id"]
                    or record.get("model_version") != scope["model_artifact_id"]):
                _fail()
            if engine is not None:
                expected_db = self.env.db_conf
                if expected_db.get("type") != "sqlite" or engine.chan_db.db_type != "sqlite":
                    _fail()
                database = next(row["file"] for row in engine.chan_db.db.query("PRAGMA database_list") if row["name"] == "main")
                if (Path(database).resolve() != Path(self.env.abs_path(expected_db["sqlite_path"])).resolve()
                        or engine.market_type != scope["source"]["market_type"]
                        or engine.ccxt_conf.get("exchange") != scope["source"]["exchange"]
                        or engine.mode != self.env.ccxt_conf.get("mode")):
                    _fail()
                actual = engine.chan_db.get_record(record["id"])
                keys = ("stock_code", "lv", "is_buy", "bstype", "open_thred", "sl_thred",
                        "signal_decision", "model_version", "deployment_id", "deployment_path")
                if any(actual.get(key) != record.get(key) for key in keys):
                    _fail()
            decision = read_decision(record["signal_decision"].encode())
            identity, payload = decision["identity"], decision["payload"]
            bar = payload["bar"]
            if (identity["kind"] != "signal" or identity["code"] != record["stock_code"] or identity["level"] != record["lv"]
                    or identity["is_buy"] != bool(record["is_buy"]) or identity["bs_type"] != record["bstype"]
                    or identity["market"] != scope["source"] or bar["market"] != scope["source"]
                    or payload["open_thred"] != record["open_thred"] or payload["sl_thred"] != record["sl_thred"]
                    or payload.get("deployment_id") != scope["deployment_id"]
                    or payload.get("model_artifact_id") != scope["model_artifact_id"]):
                _fail()
            if any(value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0)
                   for value in (record["open_thred"], record["sl_thred"])) or record["open_thred"] is None:
                _fail()
            level, opened = KL_TYPE[record["lv"]], _clock(bar["open_ms"])
            closed = _clock(bar["close_ms"])
            if (bar_close_ms(opened, level) != closed or bar["time_ms"] != closed or identity["anchor_ms"] != closed
                    or not closed <= _clock(bar["available_at_ms"]) <= identity["decision_ms"] <= checked):
                _fail()
            with CKLineDB(self.env.abs_path(self.env.offline_data_conf["sqlite_path"]), read_only=True) as market:
                market.check_source(scope["source"])
                rows = market.query_klines(record["stock_code"], level, begin_ts=opened, end_ts=opened+1)
            if len(rows) != 1 or list(rows[0][1:5]) != [bar[key] for key in ("open", "high", "low", "close")]:
                _fail()
            if engine is not None and actual.get("open_attempt", 0):
                # 新检查器不能以新输入时代重标记已经冻结的旧意图；旧意图只许恢复管理。
                history = engine.chan_db.get_order_history(record["id"])
                stamp = json.loads(actual.get("snapshot_before") or "{}").get("opening_inputs")
                if (not isinstance(stamp, dict) or not history["attempts"]
                        or history["attempts"][0]["identity"].get("opening_inputs") != stamp
                        or any(stamp.get(key) != value for key, value in self._expected.items())
                        or stamp.get("signal_event_id") != decision["event_id"]
                        or not identity["decision_ms"] <= _clock(stamp.get("checked_at_ms")) <= checked):
                    _fail()
            return {"schema": "chan-opening-input-check-v1", **self.snapshot(), "checked_at_ms": checked,
                    "signal_event_id": decision["event_id"], "native_admission_verified": False}
        except Exception:
            _fail()
