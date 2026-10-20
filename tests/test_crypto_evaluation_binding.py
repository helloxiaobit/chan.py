"""C4 实际策略/原始数据/next-open 账户桥接；只用小合成行。"""
from copy import deepcopy
from decimal import Decimal

import pytest

from Common.CEnum import KL_TYPE
from Common.ChanException import CChanException
from CustomBuySellPoint.CustomStrategy import CCustomStrategy
from ModelStrategy.parameterEvaluate.crypto_evaluate import CCryptoEvaluationData, CCryptoEvaluationConfig, evaluate_crypto_strategy
from .conftest import gen_synthetic_bars
from .test_crypto_account_contract import CODE, conf
from .test_decision_snapshots import START, HOUR
from .test_deployment_workflow import deployment_model

SOURCE = {"exchange": "binance", "market_type": "swap", "settle": "USDT", "price_type": "contract"}


def raw_fixture(count=1000):
    rows = [(START+i*HOUR, b["open"], b["high"], b["low"], b["close"], b["volume"])
            for i, b in enumerate(gen_synthetic_bars(count))]
    # 与合约价格不同的 mark，防止两者被静默复用。
    marks = [(r[0], *(v*1.001 for v in r[1:5]), r[5]) for r in rows]
    funding = [(START+i*HOUR, "0.0001", str(rows[i][1]*1.001)) for i in range(8, count, 8)]
    return rows, marks, funding


def dataset(rows, marks, funding):
    return CCryptoEvaluationData(contract_source=SOURCE, mark_source={**SOURCE, "price_type": "mark"},
        contract_rows={CODE: {KL_TYPE.K_60M: rows}}, mark_rows={CODE: marks}, mark_level=KL_TYPE.K_60M,
        funding_rows={CODE: funding}, funding_schedule_ms={CODE: [r[0] for r in funding]})


def configuration(**overrides):
    return CCryptoEvaluationConfig(**{"lv_list": [KL_TYPE.K_60M], "trade_lv_idx": 0,
        "chan_config": {"cbsp_strategy": CCustomStrategy, "divergence_rate": float("inf"), "min_zs_cnt": 0,
                        "bs_type": "1,2,3a,1p,2s,3b", "kl_data_check": True},
        "account": conf(), "entry_notional": "10", **overrides})


def test_window_view_is_immutable_and_excludes_future_ohlcv_and_funding():
    rows, marks, funding = raw_fixture(200)
    source = dataset(rows, marks, funding)
    view = source.view(start_ms=START+30*HOUR, end_ms=START+120*HOUR)
    expected = deepcopy(view)
    view["contract"][CODE]["K_60M"][0][1] = -1
    assert source.view(start_ms=START+30*HOUR, end_ms=START+120*HOUR) == expected
    assert all(r[0]+HOUR < START+120*HOUR for r in expected["contract"][CODE]["K_60M"])
    assert all(START+30*HOUR <= r[0] < START+120*HOUR for r in expected["funding"][CODE])
    assert expected["manifest"]["payload_sha256"]


@pytest.mark.parametrize("mutation", ["source", "mark_gap", "funding_missing", "funding_duplicate", "contract_gap"])
def test_bad_source_or_incomplete_raw_observations_fail_before_strategy(mutation):
    rows, marks, funding = raw_fixture(100)
    if mutation == "source":
        with pytest.raises(CChanException):
            CCryptoEvaluationData(contract_source=SOURCE, mark_source={**SOURCE, "price_type": "contract"},
                contract_rows={CODE: {KL_TYPE.K_60M: rows}}, mark_rows={CODE: marks}, mark_level=KL_TYPE.K_60M,
                funding_rows={CODE: funding}, funding_schedule_ms={CODE: [r[0] for r in funding]})
        return
    broken = dataset(rows, marks, funding)
    # source 本体不可改；构造新的明确坏输入，不绕过存储字段。
    if mutation == "mark_gap":
        marks.pop(20)
    elif mutation == "contract_gap":
        rows.pop(20)
    elif mutation == "funding_duplicate":
        funding.append(funding[0])
    else:
        funding.pop(0)
    with pytest.raises(CChanException):
        candidate = CCryptoEvaluationData(contract_source=SOURCE, mark_source={**SOURCE, "price_type": "mark"},
            contract_rows={CODE: {KL_TYPE.K_60M: rows}}, mark_rows={CODE: marks}, mark_level=KL_TYPE.K_60M,
            funding_rows={CODE: funding}, funding_schedule_ms={CODE: broken.view(start_ms=START, end_ms=START+100*HOUR)["funding_schedule_ms"][CODE]})
        evaluate_crypto_strategy(candidate, configuration(), start_ms=START, end_ms=START+100*HOUR)


def test_real_strategy_decisions_use_next_actual_contract_open_and_independent_marks():
    rows, marks, funding = raw_fixture()
    result = evaluate_crypto_strategy(dataset(rows, marks, funding), configuration(), start_ms=START, end_ms=START+1000*HOUR)
    report = result.to_dict()
    assert report["decisions"] and report["account"]["events"]
    assert report["data_manifest"]["payload_sha256"] and report["evaluation_id"]
    opens = [r for r in report["account"]["events"] if r["event"]["kind"] == "open"]
    assert opens, "真实 CCustomStrategy 夹具必须有非空开仓"
    indexed = {r[0]: r for r in rows}
    decisions = {r["event_id"]: r for r in report["decisions"]}
    for item in opens:
        event = item["event"]
        decision = decisions[event["position_id"]]
        assert event["at_ms"] == decision["identity"]["decision_ms"]
        assert Decimal(event["price"]) == Decimal(str(indexed[event["at_ms"]][1]))
        assert event["mark_price"] != event["price"]
    assert report["execution_contract"] == "confirmed-decision-next-real-base-open-v1"


def test_future_suffix_mutation_cannot_change_an_earlier_bound_evaluation():
    rows, marks, funding = raw_fixture()
    end = START+700*HOUR
    first = evaluate_crypto_strategy(dataset(rows, marks, funding), configuration(), start_ms=START, end_ms=end).to_dict()
    changed_rows = [r if r[0] < end else (r[0], *(v*1.01 for v in r[1:5]), r[5]) for r in rows]
    changed_marks = [r if r[0] < end else (r[0], *(v*1.02 for v in r[1:5]), r[5]) for r in marks]
    changed_funding = [r if r[0] < end else (r[0], "0.2", r[2]) for r in funding]
    second = evaluate_crypto_strategy(dataset(changed_rows, changed_marks, changed_funding), configuration(), start_ms=START, end_ms=end).to_dict()
    assert first == second


def test_evaluation_start_is_flat_with_prior_structure_warmup_not_prior_fills():
    rows, marks, funding = raw_fixture()
    start = START+600*HOUR
    result = evaluate_crypto_strategy(dataset(rows, marks, funding), configuration(), start_ms=start, end_ms=START+1000*HOUR).to_dict()
    assert result["decisions"]
    assert all(r["identity"]["decision_ms"] >= start for r in result["decisions"])
    assert result["account"]["snapshot"]["initial_equity"] == "1000"
    assert result["warmup_policy"] == "structure-only-flat-account-before-start"


@pytest.mark.parametrize("change", [None, "strategy", "source", "training_prefix"])
def test_modelled_evaluation_binds_actual_training_context_and_raw_prefix(deployment_model, change):
    from ChanModel.GeneratorModel import CGeneratorModel
    model = CGeneratorModel(deployment_model["model"].GetModelPath())
    rows, marks, funding = raw_fixture()
    model_config = {**deployment_model["chan_config"], "model": model, "score_thred": 0.0}
    if change == "strategy":
        model_config["mean_metrics"] = [1]
    if change == "training_prefix":
        row = rows[20]
        rows[20] = (row[0], row[1], row[2]*1.01, row[3], row[4], row[5])
    source = dataset(rows, marks, funding)
    if change == "source":
        source = CCryptoEvaluationData(contract_source={**SOURCE, "exchange": "okx"},
            mark_source={**SOURCE, "exchange": "okx", "price_type": "mark"},
            contract_rows={CODE: {KL_TYPE.K_60M: rows}}, mark_rows={CODE: marks}, mark_level=KL_TYPE.K_60M,
            funding_rows={CODE: funding}, funding_schedule_ms={CODE: [r[0] for r in funding]})
    config = configuration(chan_config=model_config)
    if change:
        with pytest.raises(CChanException):
            evaluate_crypto_strategy(source, config, start_ms=START+600*HOUR, end_ms=START+1000*HOUR)
    else:
        report = evaluate_crypto_strategy(source, config, start_ms=START+600*HOUR, end_ms=START+1000*HOUR).to_dict()
        assert report["model_artifact_id"] == model.artifact_id
        assert report["decisions"] and all(r["payload"].get("score") is not None
            for r in report["decisions"] if r["identity"]["kind"] == "open")


def test_three_levels_reject_future_parent_bodies_even_when_its_open_is_before_the_window_end():
    from .test_multilv import aggregate, gen_15m_bars, LV_LIST
    from CustomBuySellPoint.MultiLevelStrategy import CMultiLevelStrategy
    bars = gen_15m_bars(200)
    by_level = {KL_TYPE.K_15M: bars, KL_TYPE.K_60M: aggregate(bars, 4), KL_TYPE.K_4H: aggregate(bars, 16)}
    end = START+601*HOUR
    def source(rows):
        return CCryptoEvaluationData(contract_source=SOURCE, mark_source={**SOURCE, "price_type": "mark"},
            contract_rows={CODE: rows}, mark_rows={CODE: bars}, mark_level=KL_TYPE.K_15M,
            funding_rows={CODE: []}, funding_schedule_ms={CODE: []})
    config = configuration(lv_list=LV_LIST, trade_lv_idx=1,
        chan_config={"cbsp_strategy": CMultiLevelStrategy, "divergence_rate": float("inf"), "min_zs_cnt": 0,
                     "bs_type": "1,2,3a,1p,2s,3b", "kl_data_check": False,
                     "strategy_para": {"require_sub_confirm": False}})
    original = evaluate_crypto_strategy(source(by_level), config, start_ms=START, end_ms=end).to_dict()
    from Common.KLineTime import bar_close_ms
    changed = {lv: [row if bar_close_ms(row[0], lv) < end else
        (row[0], row[1], row[2]*1.05, row[3]*0.95, row[4], row[5]) for row in values] for lv, values in by_level.items()}
    rebuilt = evaluate_crypto_strategy(source(changed), config, start_ms=START, end_ms=end).to_dict()
    assert original == rebuilt
    assert original["decisions"] and any(d["identity"]["kind"] == "exit" for d in original["decisions"])
    assert {d["identity"]["is_buy"] for d in original["decisions"] if d["identity"]["kind"] == "open"} == {True, False}


def test_next_open_execution_price_does_not_depend_on_the_remainder_of_its_bar():
    rows, marks, funding = raw_fixture()
    source = dataset(rows, marks, funding)
    result = evaluate_crypto_strategy(source, configuration(), start_ms=START, end_ms=START+700*HOUR).to_dict()
    last_open = START+699*HOUR
    row = rows[699]
    rows[699] = (row[0], row[1], row[2]*2, row[3]/2, row[4]*1.1, row[5])
    mr = marks[699]
    marks[699] = (mr[0], mr[1], mr[2]*2, mr[3]/2, mr[4]*1.1, mr[5])
    assert row[0] == last_open
    assert evaluate_crypto_strategy(dataset(rows, marks, funding), configuration(), start_ms=START, end_ms=START+700*HOUR).to_dict() == result
