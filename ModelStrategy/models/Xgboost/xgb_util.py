"""XGB 训练工具:默认参数与通用封装(懒加载 xgboost)"""

DEFAULT_XGB_PARAMS = {
    "max_depth": 4,
    "eta": 0.1,
    "objective": "binary:logistic",
    "eval_metric": "auc",
    "subsample": 0.9,
    "colsample_bytree": 0.9,
    "min_child_weight": 2,
}
DEFAULT_NUM_BOOST_ROUND = 50


def xgb_train(params, dtrain, dtest=None, num_boost_round=DEFAULT_NUM_BOOST_ROUND, verbose_eval=True):
    import xgboost as xgb  # 懒加载
    evals = [(dtrain, "train")]
    if dtest is not None and dtest.num_row() > 0:
        evals.append((dtest, "test"))
    evals_result = {}
    return xgb.train(
        params,
        dtrain=dtrain,
        num_boost_round=num_boost_round,
        evals=evals,
        evals_result=evals_result,
        verbose_eval=verbose_eval,
    )
