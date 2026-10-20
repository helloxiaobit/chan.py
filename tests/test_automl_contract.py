"""C4 使用确定性评分 stub 验证预算/产物，不运行行情或收益搜索。"""
import json

import pytest

from Common.ChanException import CChanException
from ModelStrategy.parameterEvaluate.para_automl import CParaAutoML

SPACE = {"x": {"type": "int", "low": 1, "high": 5, "init": 3}}


class CEvaluation:
    trade_cnt = 3
    total_profit_rate = 1.0

    def __init__(self, value=1.0):
        self.value = value

    def to_dict(self):
        return {"fixture_score": self.value}


@pytest.mark.parametrize("algorithm", ["grid", "bayes", "pbt"])
@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_invalid_budget_fails_before_evaluation_or_publication(tmp_path, algorithm, budget):
    calls = []
    run = CParaAutoML(lambda p: calls.append(p) or CEvaluation(), SPACE, algo=algorithm)
    with pytest.raises(CChanException):
        run.run(n_trials=budget, output_path=str(tmp_path / "search.jsonl"))
    assert calls == [] and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("algorithm", ["grid", "bayes", "pbt"])
def test_budget_is_an_upper_bound_even_for_grid_and_initial_population(algorithm):
    calls = []
    run = CParaAutoML(lambda p: calls.append(p) or CEvaluation(), SPACE, algo=algorithm)
    result = run.run(n_trials=2, **({"population": 8} if algorithm == "pbt" else {}))
    assert len(calls) == len(result.trials) == 2
    assert result.metadata["trial_budget"] == 2
    assert result.metadata["seed"] == 42
    assert result.metadata["algorithm"] == ("population-perturbation" if algorithm == "pbt" else algorithm)


@pytest.mark.parametrize("grid_num", [0, 1, True, 1.5])
def test_invalid_grid_axis_count_has_no_calls(grid_num):
    calls = []
    with pytest.raises(CChanException):
        CParaAutoML(lambda p: calls.append(p) or CEvaluation(), SPACE, algo="grid").run(grid_num=grid_num)
    assert calls == []


def test_integer_grid_contains_both_bounds_once_and_never_float_parameters():
    calls = []
    result = CParaAutoML(lambda p: calls.append(p) or CEvaluation(),
        {"x": {"type": "int", "low": 1, "high": 3}}, algo="grid").run(grid_num=8)
    assert calls == [{"x": 1}, {"x": 2}, {"x": 3}]
    assert all(type(r.para["x"]) is int for r in result.trials)


@pytest.mark.parametrize("algorithm", ["grid", "bayes", "pbt"])
def test_repeating_an_instance_has_fresh_deterministic_trials(algorithm):
    run = CParaAutoML(lambda p: CEvaluation(float(p["x"])), SPACE,
                      cal_score=lambda res: res.value, algo=algorithm, seed=7)
    first = run.run(n_trials=3)
    second = run.run(n_trials=3)
    assert [r.to_dict() for r in first.trials] == [r.to_dict() for r in second.trials]
    assert len(first.trials) == len(second.trials) == 3


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_no_finite_score_means_no_result_file(tmp_path, value):
    run = CParaAutoML(lambda p: CEvaluation(), SPACE, cal_score=lambda _: value, algo="grid")
    with pytest.raises(CChanException):
        run.run(n_trials=2, output_path=str(tmp_path / "search.jsonl"))
    assert list(tmp_path.iterdir()) == []


def test_search_save_is_finite_write_once_and_preserves_existing_bytes(tmp_path):
    path = tmp_path / "search.jsonl"
    result = CParaAutoML(lambda p: CEvaluation(), SPACE, algo="grid").run(n_trials=2, output_path=str(path))
    before = path.read_bytes()
    records = [json.loads(line) for line in before.splitlines()]
    assert len(records) == 2 and all(r["run"] == result.metadata for r in records)
    with pytest.raises(CChanException):
        result.save(str(path))
    assert path.read_bytes() == before


@pytest.mark.parametrize("space", [
    {}, {"x": {"type": "choice", "choices": []}}, {"x": {"type": "float", "low": 5, "high": 1}},
    {"x": {"type": "int", "low": 1.5, "high": 5}}, {"x": {"type": "int", "low": 1, "high": 5, "init": 8}},
])
def test_invalid_allowed_space_fails_before_evaluation(space):
    calls = []
    with pytest.raises(CChanException):
        CParaAutoML(lambda p: calls.append(p) or CEvaluation(), space, algo="grid").run(n_trials=2)
    assert calls == []


def test_default_export_never_creates_an_active_open_config(tmp_path, monkeypatch):
    from ModelStrategy.parameterEvaluate import parse_automl_result as exporter
    path = tmp_path / "search.jsonl"
    CParaAutoML(lambda p: CEvaluation(), SPACE, algo="grid").run(n_trials=2, output_path=str(path))
    # 旧实现若落入默认路径也只会写临时仓库，绝不触碰用户活动配置。
    monkeypatch.setattr(exporter, "__file__", str(tmp_path / "sandbox" / "ModelStrategy" / "parameterEvaluate" / "parse.py"))
    with pytest.raises(CChanException):
        exporter.parse_automl_result(str(path))
    assert not (tmp_path / "sandbox").exists()


def test_explicit_proposal_export_is_write_once_not_an_active_configuration(tmp_path):
    from ModelStrategy.parameterEvaluate.parse_automl_result import parse_automl_result
    path, target = tmp_path / "search.jsonl", tmp_path / "proposal.yaml"
    CParaAutoML(lambda p: CEvaluation(), SPACE, algo="grid").run(n_trials=2, output_path=str(path))
    parse_automl_result(str(path), str(target))
    import yaml
    proposal = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert proposal["status"] == "unvalidated_parameter_proposal"
    assert proposal["search_sha256"] and proposal["run"]["candidate_authorized"] is False
    before = target.read_bytes()
    with pytest.raises(CChanException):
        parse_automl_result(str(path), str(target))
    assert target.read_bytes() == before


@pytest.mark.parametrize("change", ["noncanonical", "budget", "score", "parameter", "run"])
def test_search_reader_rejects_corrupted_or_inconsistent_records(tmp_path, change):
    from CustomBuySellPoint.Decision import canonical_bytes
    from ModelStrategy.parameterEvaluate.parse_automl_result import parse_automl_result
    path = tmp_path / "search.jsonl"
    CParaAutoML(lambda p: CEvaluation(), SPACE, algo="grid").run(n_trials=2, output_path=str(path))
    records = [json.loads(line) for line in path.read_bytes().splitlines()]
    if change == "noncanonical":
        path.write_text("\n".join(json.dumps(r, indent=2) for r in records))
    else:
        if change == "budget":
            records[0]["run"]["trial_budget"] = 1
            records[1]["run"]["trial_budget"] = 1
        elif change == "score":
            records[0]["score"] = None
        elif change == "parameter":
            records[0]["para"]["x"] = 100
        else:
            records[1]["run"]["seed"] = 21
        path.write_bytes(b"".join(canonical_bytes(r)+b"\n" for r in records))
    with pytest.raises(CChanException):
        parse_automl_result(str(path), str(tmp_path / "proposal.yaml"))
    assert not (tmp_path / "proposal.yaml").exists()


def test_trade_percentage_statistics_have_explicit_finite_units():
    from types import SimpleNamespace
    from ModelStrategy.parameterEvaluate.eval_strategy import CEvalResult
    result = CEvalResult([SimpleNamespace(profit_rate=2.0, open_ts=0, close_ts=1, code="fixture")])
    payload = result.to_dict()
    assert result.total_profit_rate == 2.0  # 保留逐笔兼容属性，不冒称账户收益。
    assert payload["profit_loss_ratio"] is None and payload["profit_loss_ratio_infinite"] is True
    assert payload["units"]["total_profit_rate"] == "summed_trade_percentage_points"
    json.dumps(payload, allow_nan=False)


def test_grid_materialization_is_bounded_by_trial_budget(monkeypatch):
    from ModelStrategy.parameterEvaluate import para_automl
    calls = []
    def checked_range(*args):
        values = range(*args)
        assert len(values) <= 2, "axis materialization exceeded the trial budget"
        return values
    monkeypatch.setattr(para_automl, "range", checked_range, raising=False)
    result = CParaAutoML(lambda p: calls.append(p) or CEvaluation(),
        {"x": {"type": "float", "low": 0, "high": 1}, "y": {"type": "int", "low": 1, "high": 3}},
        algo="grid").run(n_trials=2, grid_num=10**12)
    assert len(result.trials) == len(calls) == 2
