"""参数 AutoML:贝叶斯(optuna)/预算网格/种群参数扰动；pbt 只是兼容别名。

用法:
    space = {
        "max_sl_rate":     {"type": "float", "low": 0.01, "high": 0.10, "init": 0.05},
        "max_profit_rate": {"type": "float", "low": 0.03, "high": 0.30, "init": 0.10},
        "bsp_type_filter": {"type": "choice", "choices": ["1,1p", "1,1p,2", None]},
    }
    automl = CParaAutoML(eval_func, space, cal_score=lambda res: res.total_profit_rate, algo="bayes")
    result = automl.run(n_trials=20)

eval_func(para_dict) -> CEvalResult;cal_score(CEvalResult) -> float(越大越好)
"""
import copy
import hashlib
import itertools
import json
import math
import random
from pathlib import Path
from typing import Callable, Dict, List, Optional

from Common.ChanException import CChanException, ErrCode
from CustomBuySellPoint.Decision import canonical_bytes

from .artifact import write_once
from .eval_strategy import CEvalResult


def default_cal_score(res: CEvalResult) -> float:
    # 默认打分:总收益率,交易过少直接淘汰
    return float("-inf") if res.trade_cnt < 3 else res.total_profit_rate


class CTrial:
    def __init__(self, para: Dict, score: Optional[float], eval_summary: dict, reason=None):
        self.para = copy.deepcopy(para)
        self.score = score
        self.eval_summary = copy.deepcopy(eval_summary)
        self.reason = reason

    def to_dict(self):
        return {"para": self.para, "score": self.score, "eval": self.eval_summary,
                "status": "passed" if self.score is not None else "rejected", "reason": self.reason}


class CAutomlResult:
    def __init__(self, trials: List[CTrial], metadata=None):
        self.trials = copy.deepcopy(trials)
        self.metadata = copy.deepcopy(metadata or {})

    @property
    def best(self) -> CTrial:
        valid = [t for t in self.trials if type(t.score) in (int, float) and math.isfinite(t.score)]
        if not valid:
            raise CChanException("搜索无有效有限分数，不能生成部署建议", ErrCode.PARA_ERROR)
        return max(valid, key=lambda t: t.score)

    def save(self, path: str):
        best = self.best
        raw = b"".join(canonical_bytes({**t.to_dict(), "run": self.metadata})+b"\n" for t in self.trials)
        write_once(path, raw)
        print(f"[automl] {len(self.trials)} trials 已保存 → {path},best_score={best.score:.4f}")


class CParaAutoML:
    def __init__(
        self,
        eval_func: Callable[[Dict], CEvalResult],
        space: Dict[str, Dict],
        cal_score: Optional[Callable[[CEvalResult], float]] = None,
        algo: str = "bayes",  # bayes / grid / pbt
        seed: int = 42,
    ):
        self.eval_func = eval_func
        self.space = copy.deepcopy(space)
        self.cal_score = cal_score or default_cal_score
        self.algo = algo
        self.seed = seed
        self.rnd = random.Random(seed)
        self.trials: List[CTrial] = []

    def _do_trial(self, para: Dict) -> Optional[float]:
        res = self.eval_func(dict(para))
        score = self.cal_score(res)
        summary = res.to_dict()
        reason = None
        if type(score) not in (int, float) or not math.isfinite(score):
            reason = "non_finite_score"
        try:
            canonical_bytes(summary)
        except CChanException:
            summary, reason = {}, "non_finite_evaluation"
        self.trials.append(CTrial(para, float(score) if reason is None else None, summary, reason))
        return self.trials[-1].score

    def _validate_space(self):
        if type(self.seed) is not int or not isinstance(self.space, dict) or not self.space:
            raise CChanException("seed 必须为整数且允许参数空间不能为空", ErrCode.PARA_ERROR)
        for name, spec in self.space.items():
            if not isinstance(name, str) or not name or not isinstance(spec, dict):
                raise CChanException("参数名称/定义无效", ErrCode.PARA_ERROR)
            kind = spec.get("type")
            if kind == "choice":
                choices = spec.get("choices")
                if (not isinstance(choices, list) or not choices
                        or len({canonical_bytes(c) for c in choices}) != len(choices)
                        or ("init" in spec and spec["init"] not in choices)):
                    raise CChanException("choice 必须有唯一有限候选且 init 在其中", ErrCode.PARA_ERROR)
            elif kind in {"int", "float"}:
                low, high = spec.get("low"), spec.get("high")
                values = [low, high] + ([spec["init"]] if "init" in spec else [])
                if (any(type(v) not in ((int,) if kind == "int" else (int, float)) or not math.isfinite(v) for v in values)
                        or low > high or ("init" in spec and not low <= spec["init"] <= high)):
                    raise CChanException("参数上下界或 init 无效", ErrCode.PARA_ERROR)
            else:
                raise CChanException("未知参数类型", ErrCode.PARA_ERROR)
        canonical_bytes(self.space)

    def _validate_parameters(self, parameters):
        if not isinstance(parameters, dict) or set(parameters) != set(self.space):
            raise CChanException("trial 参数与冻结空间不一致", ErrCode.PARA_ERROR)
        for name, spec in self.space.items():
            value = parameters[name]
            if spec["type"] == "choice":
                valid = canonical_bytes(value) in [canonical_bytes(c) for c in spec["choices"]]
            else:
                valid = (type(value) in ((int,) if spec["type"] == "int" else (int, float))
                         and math.isfinite(value) and spec["low"] <= value <= spec["high"])
            if not valid:
                raise CChanException("trial 参数超出冻结空间", ErrCode.PARA_ERROR)

    def _sample_para(self) -> Dict:
        para = {}
        for name, spec in self.space.items():
            if spec["type"] == "float":
                para[name] = self.rnd.uniform(spec["low"], spec["high"])
            elif spec["type"] == "int":
                para[name] = self.rnd.randint(spec["low"], spec["high"])
            elif spec["type"] == "choice":
                para[name] = self.rnd.choice(spec["choices"])
            else:
                raise CChanException(f"未知参数类型 {spec['type']}", ErrCode.PARA_ERROR)
        return para

    def _init_para(self) -> Dict:
        para = {}
        for name, spec in self.space.items():
            if "init" in spec:
                para[name] = spec["init"]
            elif spec["type"] == "choice":
                para[name] = spec["choices"][0]
            else:
                value = (spec["low"] + spec["high"]) / 2
                para[name] = int(value) if spec["type"] == "int" else value
        return para

    def run(self, n_trials: int = 20, output_path: Optional[str] = None, **algo_para) -> CAutomlResult:
        if type(n_trials) is not int or n_trials <= 0:
            raise CChanException("trial budget 必须是正整数", ErrCode.PARA_ERROR)
        self._validate_space()
        if self.algo not in {"bayes", "grid", "pbt", "population-perturbation"}:
            raise CChanException(f"未知automl算法 {self.algo}", ErrCode.PARA_ERROR)
        self.trials, self.rnd = [], random.Random(self.seed)
        if self.algo == "bayes":
            if algo_para:
                raise CChanException("bayes 不接受未声明参数", ErrCode.PARA_ERROR)
            self._run_bayes(n_trials)
        elif self.algo == "grid":
            self._run_grid(n_trials, **algo_para)
        else:
            self._run_pbt(n_trials, **algo_para)
        metadata = {"schema": "chan-parameter-search-v1", "algorithm":
                    "population-perturbation" if self.algo == "pbt" else self.algo,
                    "seed": self.seed, "trial_budget": n_trials, "allowed_space": self.space,
                    "algorithm_parameters": algo_para, "candidate_authorized": False,
                    "code_sha256": hashlib.sha256(Path(__file__).read_text(encoding="utf-8").replace("\r\n", "\n").encode()).hexdigest()}
        result = CAutomlResult(self.trials, metadata)
        result.best  # 所有 trial 无效时，输出目录和文件都不能先创建。
        if output_path:
            result.save(output_path)
        return result

    # ===== 贝叶斯(optuna)=====
    def _run_bayes(self, n_trials: int):
        import optuna  # 懒加载
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        def objective(trial: "optuna.Trial"):
            para = {}
            for name, spec in self.space.items():
                if spec["type"] == "float":
                    para[name] = trial.suggest_float(name, spec["low"], spec["high"])
                elif spec["type"] == "int":
                    para[name] = trial.suggest_int(name, spec["low"], spec["high"])
                elif spec["type"] == "choice":
                    para[name] = trial.suggest_categorical(name, spec["choices"])
            score = self._do_trial(para)
            if score is None:
                raise optuna.TrialPruned(self.trials[-1].reason)
            return score

        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=self.rnd.randint(0, 2**31)),
        )
        study.enqueue_trial(self._init_para())
        study.optimize(objective, n_trials=n_trials, n_jobs=1)

    # ===== 暴力网格 =====
    def _run_grid(self, n_trials: int, grid_num: int = 3):
        if type(grid_num) is not int or grid_num < 2:
            raise CChanException("grid_num 必须是至少 2 的整数", ErrCode.PARA_ERROR)
        axes = []
        for name, spec in self.space.items():
            if spec["type"] == "float":
                low, high = spec["low"], spec["high"]
                values = sorted(set(low + (high-low)*i/(grid_num-1) for i in range(min(grid_num, n_trials))))
                axes.append([(name, v) for v in values])
            elif spec["type"] == "int":
                low, high = spec["low"], spec["high"]
                if grid_num >= high-low+1:
                    values = [low+i for i in range(min(high-low+1, n_trials))]
                else:
                    values = [low+(high-low)*i//(grid_num-1) for i in range(min(grid_num, n_trials))]
                axes.append([(name, v) for v in values])
            else:
                axes.append([(name, c) for c in spec["choices"]])
        for combo in itertools.islice(itertools.product(*axes), n_trials):
            self._do_trial(dict(combo))

    # ===== 种群参数扰动：没有模型 checkpoint 继承 =====
    def _run_pbt(self, n_trials: int, population: int = 4):
        if type(population) is not int or population < 1:
            raise CChanException("population 必须为正整数", ErrCode.PARA_ERROR)
        population = min(population, n_trials)
        pop = [self._init_para()] + [self._sample_para() for _ in range(population - 1)]
        scores = [self._do_trial(p) for p in pop]
        while len(self.trials) < n_trials:
            order = sorted(range(population), key=lambda i: scores[i] if scores[i] is not None else -math.inf, reverse=True)
            half = max(1, population // 2)
            for loser_rank in range(half if population > 1 else 0, population):
                if len(self.trials) >= n_trials:
                    break
                src = pop[order[loser_rank % half]]  # 输家复制赢家参数并扰动
                pop[order[loser_rank]] = self._perturb(src)
                scores[order[loser_rank]] = self._do_trial(pop[order[loser_rank]])

    def _perturb(self, para: Dict) -> Dict:
        new_para = dict(para)
        for name, spec in self.space.items():
            if spec["type"] == "float":
                v = new_para[name] * self.rnd.choice([0.8, 1.2])
                new_para[name] = min(max(v, spec["low"]), spec["high"])
            elif spec["type"] == "int":
                v = new_para[name] + self.rnd.choice([-1, 1])
                new_para[name] = min(max(v, spec["low"]), spec["high"])
            elif spec["type"] == "choice" and self.rnd.random() < 0.3:
                new_para[name] = self.rnd.choice(spec["choices"])
        return new_para


def read_search_result(path):
    """独立重读有限 canonical trial；未版本化旧文件不能默认为已验证建议。"""
    try:
        raw = Path(path).read_bytes()
        records = [json.loads(line) for line in raw.splitlines()]
        if not records or b"".join(canonical_bytes(r)+b"\n" for r in records) != raw:
            raise CChanException("搜索产物缺少 canonical 行", ErrCode.CONFIG_ERROR)
        run = records[0]["run"]
        if (set(run) != {"schema", "algorithm", "seed", "trial_budget", "allowed_space", "algorithm_parameters", "candidate_authorized", "code_sha256"}
                or run["schema"] != "chan-parameter-search-v1" or run["candidate_authorized"] is not False
                or run["algorithm"] not in {"grid", "bayes", "population-perturbation"}
                or type(run["trial_budget"]) is not int or not 0 < len(records) <= run["trial_budget"]
                or run["code_sha256"] != hashlib.sha256(Path(__file__).read_text(encoding="utf-8").replace("\r\n", "\n").encode()).hexdigest()):
            raise CChanException("搜索版本/预算/代码身份不完整", ErrCode.CONFIG_ERROR)
        checker = CParaAutoML(None, run["allowed_space"], algo=run["algorithm"], seed=run["seed"])
        checker._validate_space()
        trials = []
        for record in records:
            if set(record) != {"para", "score", "eval", "status", "reason", "run"} or record["run"] != run:
                raise CChanException("搜索行身份不一致", ErrCode.CONFIG_ERROR)
            checker._validate_parameters(record["para"])
            score, status = record["score"], record["status"]
            if (not isinstance(record["eval"], dict) or status not in {"passed", "rejected"}
                    or (status == "passed" and (type(score) not in (int, float) or not math.isfinite(score) or record["reason"] is not None))
                    or (status == "rejected" and (score is not None or not isinstance(record["reason"], str) or not record["reason"]))):
                raise CChanException("搜索行分数/状态无效", ErrCode.CONFIG_ERROR)
            trials.append(CTrial(record["para"], score, record["eval"], record["reason"]))
        result = CAutomlResult(trials, run)
        result.best
        return result, hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise CChanException("无法读取完整版本化搜索产物", ErrCode.CONFIG_ERROR) from error
