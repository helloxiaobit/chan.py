"""原始已收盘行情→真实策略决策→next-real-open→显式 USDT 账户。

输入为已声明来源的小型/显式数据包，不读取研究路径、环境配置或下载行情。
该执行口径不是线上 limit 撮合：决策在收盘确认，只在随后真实 base open 成交，
一律 taker+不利滑点，不能回填决策 K 内的有利价格。验证窗口保留结构预热但平仓起步。
"""
import copy
import hashlib
import json
from collections import defaultdict
from decimal import Decimal, localcontext
from pathlib import Path

from Chan import CChan
from ChanConfig import CChanConfig
from ChanModel.GeneratorModel import CGeneratorModel
from ChanModel.ModelContract import feature_code_identity, freeze_config, read_model_contract
from Common.CEnum import AUTYPE, KL_TYPE
from Common.ChanException import CChanException, ErrCode
from Common.func_util import check_kltype_order
from Common.KLineTime import bar_close_ms, make_crypto_klu, validate_ohlcv_page
from CustomBuySellPoint.CustomStrategy import CCustomStrategy
from CustomBuySellPoint.MultiLevelStrategy import CMultiLevelStrategy
from CustomBuySellPoint.Decision import bar_snapshot, canonical_bytes, read_decision
from OfflineData.offline_data_util import parse_dt_to_ts, validate_source_identity

from .crypto_account import CCryptoAccountConfig, _clock, _number, evaluate_crypto_account

EXECUTION = "confirmed-decision-next-real-base-open-v1"
WARMUP = "structure-only-flat-account-before-start"


def _error(message):
    return CChanException(message, ErrCode.PARA_ERROR)


def evaluation_code_identity():
    return {"feature_code": feature_code_identity(),
            "adapter_sha256": hashlib.sha256(Path(__file__).read_text(encoding="utf-8").replace("\r\n", "\n").encode()).hexdigest()}


class CCryptoEvaluationData:
    def __init__(self, *, contract_source, mark_source, contract_rows, mark_rows, mark_level,
                 funding_rows, funding_schedule_ms):
        contract_source, mark_source = validate_source_identity(contract_source), validate_source_identity(mark_source)
        if (contract_source["price_type"] != "contract" or mark_source != {**contract_source, "price_type": "mark"}
                or contract_source["market_type"] not in {"spot", "swap"}
                or contract_source["exchange"] not in {"binance", "okx"}
                or (contract_source["market_type"] == "swap" and contract_source["settle"] != "USDT")
                or not isinstance(mark_level, KL_TYPE) or not isinstance(contract_rows, dict) or not contract_rows
                or set(contract_rows) != set(mark_rows) or set(contract_rows) != set(funding_rows)
                or set(contract_rows) != set(funding_schedule_ms)):
            raise _error("账户数据必须完整绑定同源 contract/mark/资金费与 symbol，不能猜测")
        body = {"contract_source": contract_source, "mark_source": mark_source, "mark_level": mark_level.name,
                "contract": {}, "marks": {}, "funding": {}, "funding_schedule_ms": {}}
        for code, levels in sorted(contract_rows.items()):
            suffix = "/USDT:USDT" if contract_source["market_type"] == "swap" else "/USDT"
            if not isinstance(code, str) or not code.endswith(suffix) or not code[:-len(suffix)]:
                raise _error("数据 symbol 与 USDT 市场不匹配")
            if not isinstance(levels, dict) or not levels or mark_level not in levels:
                raise _error("缺少完整策略级别或执行 base 级别")
            body["contract"][code] = {}
            for level, rows in levels.items():
                if not isinstance(level, KL_TYPE):
                    raise _error("行情级别须是明确 KL_TYPE")
                values = validate_ohlcv_page(rows, level)
                if not values:
                    raise _error("策略行情不能为空")
                body["contract"][code][level.name] = values
            marks = validate_ohlcv_page(mark_rows[code], mark_level)
            if [r[0] for r in marks] != [r[0] for r in body["contract"][code][mark_level.name]]:
                raise _error("mark 与真实 base 行情必须逐时刻完整，不能填缺 K")
            body["marks"][code] = marks
            schedule = list(funding_schedule_ms[code])
            if any(type(t) is not int or t < 0 for t in schedule) or sorted(set(schedule)) != schedule:
                raise _error("资金费日程必须是独立声明的唯一递增 exact-ms 时刻")
            fund = []
            for row in funding_rows[code]:
                if len(row) != 3:
                    raise _error("资金费行须有 exact ms/rate/当时 mark 价格")
                at, rate, price = _clock(row[0]), _number(row[1]), _number(row[2], positive=True)
                if abs(rate) >= 1:
                    raise _error("资金费率绝对值必须小于 1")
                fund.append((at, str(rate), str(price)))
            if [r[0] for r in fund] != schedule or (contract_source["market_type"] == "spot" and schedule):
                raise _error("资金费缺失/重复/乱序或 spot 非空；不能把空输入当已证明完整")
            body["funding"][code], body["funding_schedule_ms"][code] = fund, schedule
        self._raw = canonical_bytes(body)

    def to_dict(self):
        return {"schema": "chan-crypto-evaluation-data-v1", **json.loads(self._raw)}

    @classmethod
    def from_dict(cls, packet):
        expected = {"schema", "contract_source", "mark_source", "mark_level", "contract", "marks", "funding", "funding_schedule_ms"}
        try:
            if not isinstance(packet, dict) or set(packet) != expected or packet["schema"] != "chan-crypto-evaluation-data-v1":
                raise _error("未知或不完整的来源数据包 schema")
            canonical_bytes(packet)
            return cls(contract_source=packet["contract_source"], mark_source=packet["mark_source"],
                contract_rows={code: {KL_TYPE[level]: rows for level, rows in by_level.items()} for code, by_level in packet["contract"].items()},
                mark_rows=packet["marks"], mark_level=KL_TYPE[packet["mark_level"]],
                funding_rows=packet["funding"], funding_schedule_ms=packet["funding_schedule_ms"])
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise _error("来源数据包无法完整重读") from error

    def view(self, *, start_ms, end_ms):
        start_ms, end_ms = _clock(start_ms), _clock(end_ms)
        if start_ms >= end_ms:
            raise _error("评估窗口必须是正的 UTC 半开区间")
        body = json.loads(self._raw)
        base = KL_TYPE[body["mark_level"]]
        body["contract_open_prices"], body["mark_open_prices"] = {}, {}
        for code, levels in body["contract"].items():
            raw_base = levels[base.name]
            if raw_base[0][0] > start_ms or bar_close_ms(raw_base[-1][0], base) < end_ms:
                raise _error("base 行情没有覆盖完整评估窗口")
            body["contract_open_prices"][code] = {str(r[0]): str(r[1]) for r in raw_base if start_ms <= r[0] < end_ms}
            body["mark_open_prices"][code] = {str(r[0]): str(r[1]) for r in body["marks"][code] if start_ms <= r[0] < end_ms}
            for level, rows in levels.items():
                levels[level] = [r for r in rows if bar_close_ms(r[0], KL_TYPE[level]) < end_ms]
                if not levels[level]:
                    raise _error("窗口内缺少实际已收盘结构行情")
            body["marks"][code] = [r for r in body["marks"][code] if start_ms <= bar_close_ms(r[0], base) < end_ms]
            body["funding"][code] = [r for r in body["funding"][code] if start_ms <= r[0] < end_ms]
            body["funding_schedule_ms"][code] = [t for t in body["funding_schedule_ms"][code] if start_ms <= t < end_ms]
        body["window"] = {"start_ms": start_ms, "end_ms": end_ms}
        body["manifest"] = {"schema": "chan-evaluation-input-v1", "payload_sha256": hashlib.sha256(canonical_bytes(body)).hexdigest(),
            "window": dict(body["window"]), "contract_source": dict(body["contract_source"]), "mark_source": dict(body["mark_source"]),
            "counts": {code: {"contract": {lv: len(rows) for lv, rows in levels.items()},
                              "mark": len(body["marks"][code]), "funding": len(body["funding"][code]),
                              "execution_opens": len(body["contract_open_prices"][code])} for code, levels in body["contract"].items()}}
        return body


class CCryptoEvaluationConfig:
    def __init__(self, *, lv_list, trade_lv_idx, chan_config, account=None, entry_notional="100"):
        self.lv_list, self.chan_config = list(lv_list), copy.deepcopy(chan_config)
        check_kltype_order(self.lv_list)
        strategy = self.chan_config.get("cbsp_strategy")
        if (not self.lv_list or any(not isinstance(v, KL_TYPE) for v in self.lv_list)
                or type(trade_lv_idx) is not int or not 0 <= trade_lv_idx < len(self.lv_list)
                or strategy not in {CCustomStrategy, CMultiLevelStrategy}
                or (strategy is CMultiLevelStrategy and trade_lv_idx != (1 if len(self.lv_list)>1 else 0))):
            raise _error("评估策略/交易级别尚未适配")
        self.trade_lv_idx, self.account = trade_lv_idx, account or CCryptoAccountConfig()
        self.entry_notional = _number(entry_notional, positive=True)
        if not isinstance(self.account, CCryptoAccountConfig) or self.chan_config.get("only_judge_last"):
            raise _error("账户配置无效或 only-last 不能做时序评估")
        freeze_config(self.chan_config)

    def to_dict(self):
        return {"lv_list": [v.name for v in self.lv_list], "trade_lv_idx": self.trade_lv_idx,
                "chan_config": freeze_config(self.chan_config), "account": self.account.to_dict(),
                "entry_notional": str(self.entry_notional), "sizing_contract": "fixed_USDT_notional_per_accepted_lot"}


class CCryptoEvaluationResult:
    def __init__(self, report):
        self._raw = canonical_bytes(report)

    @property
    def trade_cnt(self):
        return self.to_dict()["account"]["metrics"]["closed_position_count"]

    def to_dict(self):
        return json.loads(self._raw)


def _validate_model(view, config, start_ms):
    model = config.chan_config.get("model")
    if model is None:
        return None
    if not isinstance(model, CGeneratorModel):
        raise _error("账户评估必须使用已验证版本化 generator 模型")
    contract, identity = read_model_contract(model.path, Path(model.path).with_suffix(".meta"))
    context = contract["generation_context"]
    if (identity != model.artifact_id or contract != model.contract or not isinstance(context, dict)
            or contract["training_window"]["last_label_end_ms"] > start_ms
            or set(context["code_list"]) != set(view["contract"])
            or context["lv_list"] != freeze_config(config.lv_list) or context["trade_lv_idx"] != config.trade_lv_idx):
        raise _error("模型身份/完整标的级别/训练可用时刻与账户评估不一致")
    ignored = {"model", "score_thred", "trigger_step"}
    actual = freeze_config({k: v for k, v in config.chan_config.items() if k not in ignored})
    expected = {k: v for k, v in context["chan_config"].items() if k not in ignored}
    if canonical_bytes(actual) != canonical_bytes(expected):
        raise _error("不能用不同于实际训练的策略/特征上下文给评估贴模型版本")
    begin = parse_dt_to_ts(context["begin_time"]) if context["begin_time"] is not None else None
    for code, by_level in view["contract"].items():
        for lv in config.lv_list:
            if context["source_identities"][code][lv.name] != view["contract_source"]:
                raise _error("模型实际训练来源与评估市场不一致")
            evidence = context["input_manifests"][code][lv.name]
            rows = [r for r in by_level[lv.name] if begin is None or r[0] >= begin][:evidence["count"]]
            if len(rows) != evidence["count"] or bar_close_ms(rows[-1][0], lv) > start_ms:
                raise _error("评估开始前缺少完整训练输入前缀")
            digest = hashlib.sha256()
            for row in rows:
                unit = make_crypto_klu(row, lv, now_ms=start_ms)
                unit.source_identity = dict(view["contract_source"])
                digest.update(canonical_bytes({**bar_snapshot(unit), "trade_info": unit.trade_info.metric})+b"\n")
            if digest.hexdigest() != evidence["sha256"]:
                raise _error("实际训练 raw 输入前缀摘要漂移，不能换数据后沿用模型")
    return identity


def evaluate_crypto_strategy(data, config, *, start_ms, end_ms):
    view = data.view(start_ms=start_ms, end_ms=end_ms)
    if view["contract_source"]["market_type"] != config.account.market_type or config.lv_list[-1].name != view["mark_level"]:
        raise _error("账户市场或 base 级别与数据不一致")
    model_id = _validate_model(view, config, start_ms)
    original_strategy = config.chan_config["cbsp_strategy"]
    class CWindowedStrategy(original_strategy):
        def update(self, chan, lv):
            self._window_lv, self._window_ms = lv, int(chan[lv][-1][-1].time.ts*1000)
            return super().update(chan, lv)

        def model_filter(self, cbsp):
            if self._window_lv != config.trade_lv_idx:
                return True
            return self._window_ms >= start_ms and super().model_filter(cbsp)
    chan_conf = {**config.chan_config, "cbsp_strategy": CWindowedStrategy, "trigger_step": True}
    decisions, accounts, execution_records = [], [], []
    with localcontext() as context:
        context.prec = 50
        for code, rows_by_level in sorted(view["contract"].items()):
            if any(lv.name not in rows_by_level for lv in config.lv_list):
                raise _error("输入缺少策略要求的完整级别")
            chan = CChan(code, lv_list=config.lv_list, config=CChanConfig(copy.deepcopy(chan_conf)), autype=AUTYPE.NONE)
            batches = defaultdict(dict)
            for lv in config.lv_list:
                for row in rows_by_level[lv.name]:
                    unit = make_crypto_klu(row, lv, now_ms=end_ms)
                    unit.source_identity = dict(view["contract_source"])
                    batches[unit.close_ms].setdefault(lv, []).append(unit)
            for at in sorted(batches):
                chan.trigger_load({lv: batches[at].get(lv, []) for lv in config.lv_list})
            records = [read_decision(raw) for raw in chan[config.trade_lv_idx].cbsp_strategy.decision_records]
            quantities, remaining = {}, {}
            for record in records:
                identity, payload = record["identity"], record["payload"]
                at, kind = identity["decision_ms"], identity["kind"]
                if not start_ms <= at < end_ms or kind not in {"open", "exit"}:
                    raise _error("策略发布窗口外决策，不能过滤后假称 flat 账户")
                try:
                    price = _number(view["contract_open_prices"][code][str(at)], positive=True)
                    mark = _number(view["mark_open_prices"][code][str(at)], positive=True)
                except KeyError as error:
                    raise _error("已确认决策缺少 next real base open，不能猜成交或用别的行") from error
                event = {"id": record["event_id"], "at_ms": at, "price": str(price), "role": "taker"}
                if kind == "open":
                    pid = record["event_id"]
                    quantity = config.entry_notional/price
                    quantities[pid], remaining[pid] = quantity, quantity
                    event.update(kind="open", symbol=code, position_id=pid, is_buy=identity["is_buy"],
                                 quantity=str(quantity), mark_price=str(mark))
                else:
                    pid = identity["parent_event_id"]
                    if pid not in quantities or remaining[pid] <= 0:
                        raise _error("退出缺少真实评估持仓")
                    quota = payload["quota"]
                    quantity = remaining[pid] if quota is None else min(remaining[pid], quantities[pid]*_number(quota, positive=True))
                    remaining[pid] -= quantity
                    event.update(kind="close", position_id=pid, quantity=str(quantity), sequence=identity["sequence"])
                decisions.append(record)
                accounts.append(event)
                execution_records.append({"event_id": event["id"], "source": "contract-next-base-open", "at_ms": at,
                                          "reference_price": str(price), "decision_payload_sha256": record["payload_sha256"]})
            base = KL_TYPE[view["mark_level"]]
            for row in view["marks"][code]:
                at = bar_close_ms(row[0], base)
                accounts.append({"id": f"mark:{code}:{at}", "kind": "mark", "at_ms": at, "symbol": code, "price": str(row[4])})
            for at, rate, price in view["funding"][code]:
                accounts.append({"id": f"funding:{code}:{at}", "kind": "funding", "at_ms": at, "symbol": code, "rate": rate, "price": price})
        account = evaluate_crypto_account(accounts, config.account, start_ms=start_ms, end_ms=end_ms)
    report = {"schema": "chan-crypto-evaluation-v1", "execution_contract": EXECUTION, "warmup_policy": WARMUP,
        "configuration": config.to_dict(), "data_manifest": view["manifest"], "source_identity": view["contract_source"],
        "code": evaluation_code_identity(), "model_artifact_id": model_id,
        "decisions": decisions, "executions": execution_records, "account": account}
    report["evaluation_id"] = hashlib.sha256(canonical_bytes(report)).hexdigest()
    return CCryptoEvaluationResult(report)
