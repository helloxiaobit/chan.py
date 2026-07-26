"""M4 验收测试:eval_strategy 回测报告、三种 automl、parse_automl_result 产出 OpenConfig.yaml"""
import json
import os

import pytest

from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from CustomBuySellPoint.CustomStrategy import CCustomStrategy
from ModelStrategy.parameterEvaluate.eval_strategy import CEvalConfig, eval_strategy
from ModelStrategy.parameterEvaluate.para_automl import CParaAutoML, CTrial
from ModelStrategy.parameterEvaluate.parse_automl_result import parse_automl_result

BASE_CHAN_CONF = {
    "divergence_rate": float("inf"),
    "min_zs_cnt": 0,
    "bs_type": "1,2,3a,1p,2s,3b",
    "cbsp_strategy": CCustomStrategy,
}


def make_eval_conf(synthetic_csv_code, **kwargs):
    return CEvalConfig(
        code_list=[synthetic_csv_code],
        data_src=DATA_SRC.CSV,
        lv_list=[KL_TYPE.K_DAY],
        autype=AUTYPE.NONE,
        chan_config=BASE_CHAN_CONF,
        **kwargs,
    )


@pytest.fixture(scope="module")
def base_result(synthetic_csv_code):
    return eval_strategy(make_eval_conf(synthetic_csv_code))


def test_eval_strategy_report(base_result, synthetic_csv_code):
    res = base_result
    assert res.trade_cnt > 0
    assert 0 <= res.win_rate <= 1
    assert res.win_cnt + res.lose_cnt == res.trade_cnt
    assert res.max_drawdown >= 0
    assert res.max_hold_cnt >= 1
    assert synthetic_csv_code in res.per_code
    report = str(res)
    for kw in ("盈亏比", "胜率", "最大回撤", "各票明细"):
        assert kw in report
    d = res.to_dict()
    json.dumps(d)  # 可序列化
    assert d["trade_cnt"] == res.trade_cnt


def test_eval_bsp_type_filter(base_result, synthetic_csv_code):
    res_filtered = eval_strategy(make_eval_conf(synthetic_csv_code, bsp_type_filter="1,1p"))
    assert res_filtered.trade_cnt <= base_result.trade_cnt
    for t in res_filtered.trades:
        assert set(t.bs_type.replace("q", "").split(",")) & {"1", "1p"}


def test_eval_max_sl_rate(synthetic_csv_code):
    res = eval_strategy(make_eval_conf(synthetic_csv_code, max_sl_rate=0.02))
    # 止损截断后,所有实际平仓交易的亏损不应显著超过止损线(留滑点余量:收盘价判断会低于止损价)
    closed_losses = [t.profit_rate for t in res.trades if t.is_closed and t.profit_rate < 0]
    assert res.trade_cnt > 0
    assert all(loss > -15 for loss in closed_losses)


def eval_func_builder(synthetic_csv_code):
    def eval_func(para):
        return eval_strategy(make_eval_conf(
            synthetic_csv_code,
            bsp_type_filter=para.get("bsp_type_filter"),
            max_sl_rate=para.get("max_sl_rate"),
            max_profit_rate=para.get("max_profit_rate"),
        ))
    return eval_func


SPACE = {
    "max_sl_rate": {"type": "float", "low": 0.02, "high": 0.10, "init": 0.05},
    "bsp_type_filter": {"type": "choice", "choices": [None, "1,1p,2"]},
}


def test_automl_grid(synthetic_csv_code, tmp_path):
    automl = CParaAutoML(eval_func_builder(synthetic_csv_code), SPACE, algo="grid")
    out = str(tmp_path / "automl_grid.jsonl")
    result = automl.run(output_path=out, grid_num=2)
    assert len(result.trials) == 4  # 2x2
    assert os.path.exists(out)
    assert result.best.score == max(t.score for t in result.trials)


def test_automl_bayes(synthetic_csv_code, tmp_path):
    pytest.importorskip("optuna")
    automl = CParaAutoML(eval_func_builder(synthetic_csv_code), SPACE, algo="bayes")
    result = automl.run(n_trials=3, output_path=str(tmp_path / "automl_bayes.jsonl"))
    assert len(result.trials) == 3
    for t in result.trials:
        assert SPACE["max_sl_rate"]["low"] <= t.para["max_sl_rate"] <= SPACE["max_sl_rate"]["high"]


def test_automl_pbt(synthetic_csv_code, tmp_path):
    automl = CParaAutoML(eval_func_builder(synthetic_csv_code), SPACE, algo="pbt")
    result = automl.run(n_trials=8, population=4, output_path=str(tmp_path / "automl_pbt.jsonl"))
    assert len(result.trials) >= 4


def test_parse_automl_result(synthetic_csv_code, tmp_path):
    yaml = pytest.importorskip("yaml")
    automl = CParaAutoML(eval_func_builder(synthetic_csv_code), SPACE, algo="grid")
    out = str(tmp_path / "automl.jsonl")
    result = automl.run(output_path=out, grid_num=2)
    yaml_path = str(tmp_path / "OpenConfig.yaml")
    parse_automl_result(out, yaml_path)
    assert os.path.exists(yaml_path)
    with open(yaml_path, encoding="utf-8") as f:
        conf = yaml.safe_load(f)
    assert conf["open_para"] == result.best.para
    assert "eval_summary" in conf and "automl_score" in conf


def test_automl_verify_and_multi_cycle(synthetic_csv_code, tmp_path):
    from ModelStrategy.parameterEvaluate.automl_verify import automl_verify
    from ModelStrategy.parameterEvaluate.multi_cycle_test import multi_cycle_test
    automl = CParaAutoML(eval_func_builder(synthetic_csv_code), SPACE, algo="grid")
    out = str(tmp_path / "automl.jsonl")
    automl.run(output_path=out, grid_num=2)
    report = automl_verify(out, eval_func_builder(synthetic_csv_code))
    assert "verify_eval" in report and report["verify_eval"]["trade_cnt"] > 0

    def builder(begin, end):
        def eval_func(para):
            conf = make_eval_conf(synthetic_csv_code, max_sl_rate=para.get("max_sl_rate"))
            conf.begin_time, conf.end_time = begin, end
            return eval_strategy(conf)
        return eval_func

    reports = multi_cycle_test({"max_sl_rate": 0.05}, builder, [("2020-01-01", "2021-06-30"), ("2021-07-01", "2022-12-31")])
    assert len(reports) == 2
