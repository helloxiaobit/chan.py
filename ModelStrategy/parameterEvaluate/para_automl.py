"""参数 AutoML:贝叶斯(optuna)/暴力网格/PBT 三种搜索算法

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
import json
import random
from typing import Callable, Dict, List, Optional

from Common.ChanException import CChanException, ErrCode

from .eval_strategy import CEvalResult


def default_cal_score(res: CEvalResult) -> float:
    # 默认打分:总收益率,交易过少直接淘汰
    return float("-inf") if res.trade_cnt < 3 else res.total_profit_rate


class CTrial:
    def __init__(self, para: Dict, score: float, eval_summary: dict):
        self.para = para
        self.score = score
        self.eval_summary = eval_summary

    def to_dict(self):
        return {"para": self.para, "score": self.score, "eval": self.eval_summary}


class CAutomlResult:
    def __init__(self, trials: List[CTrial]):
        self.trials = trials

    @property
    def best(self) -> CTrial:
        return max(self.trials, key=lambda t: t.score)

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            for t in self.trials:
                f.write(json.dumps(t.to_dict(), ensure_ascii=False, default=str) + "\n")
        print(f"[automl] {len(self.trials)} trials 已保存 → {path},best_score={self.best.score:.4f}")


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
        self.space = space
        self.cal_score = cal_score or default_cal_score
        self.algo = algo
        self.rnd = random.Random(seed)
        self.trials: List[CTrial] = []

    def _do_trial(self, para: Dict) -> float:
        res = self.eval_func(dict(para))
        score = self.cal_score(res)
        self.trials.append(CTrial(dict(para), score, res.to_dict()))
        return score

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
                para[name] = (spec["low"] + spec["high"]) / 2
        return para

    def run(self, n_trials: int = 20, output_path: Optional[str] = None, **algo_para) -> CAutomlResult:
        if self.algo == "bayes":
            self._run_bayes(n_trials)
        elif self.algo == "grid":
            self._run_grid(**algo_para)
        elif self.algo == "pbt":
            self._run_pbt(n_trials, **algo_para)
        else:
            raise CChanException(f"未知automl算法 {self.algo}", ErrCode.PARA_ERROR)
        result = CAutomlResult(self.trials)
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
            return self._do_trial(para)

        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=self.rnd.randint(0, 2**31)),
        )
        init = self._init_para()
        try:  # 初始值入队(choice 为 None 时 optuna 也支持)
            study.enqueue_trial(init)
        except Exception:
            pass
        study.optimize(objective, n_trials=n_trials)

    # ===== 暴力网格 =====
    def _run_grid(self, grid_num: int = 3):
        import itertools
        axes = []
        for name, spec in self.space.items():
            if spec["type"] == "float":
                low, high = spec["low"], spec["high"]
                axes.append([(name, low + (high - low) * i / (grid_num - 1)) for i in range(grid_num)])
            elif spec["type"] == "int":
                low, high = spec["low"], spec["high"]
                step = max(1, (high - low) // (grid_num - 1))
                axes.append([(name, v) for v in range(low, high + 1, step)])
            else:
                axes.append([(name, c) for c in spec["choices"]])
        for combo in itertools.product(*axes):
            self._do_trial(dict(combo))

    # ===== PBT(种群训练)=====
    def _run_pbt(self, n_trials: int, population: int = 4):
        pop = [self._init_para()] + [self._sample_para() for _ in range(population - 1)]
        scores = [self._do_trial(p) for p in pop]
        rounds = max(0, (n_trials - population) // population)
        for _ in range(rounds):
            order = sorted(range(population), key=lambda i: scores[i], reverse=True)
            half = max(1, population // 2)
            for loser_rank in range(half, population):
                src = pop[order[loser_rank % half]]  # 输家复制赢家参数并扰动
                pop[order[loser_rank]] = self._perturb(src)
            for i in order[half:]:
                scores[i] = self._do_trial(pop[i])

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
