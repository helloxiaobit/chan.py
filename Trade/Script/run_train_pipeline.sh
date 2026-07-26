#!/bin/bash
# 训练流水线:回测出样本 → 训练三套模型 → (可选)automl 搜索开仓参数
# 用法: ./run_train_pipeline.sh [样本输出目录]
cd "$(dirname "$0")/../.." || exit 1
SAMPLE_DIR=${1:-./backtest_output}

python -c "
from ModelStrategy.BacktestChanConfig import CBacktestConfig
from ModelStrategy.backtest import run_backtest
from Trade.Script.StaticsChanConfig import get_statics_chan_config, get_trade_conf
conf = get_trade_conf()
res = run_backtest(CBacktestConfig(
    code_list=conf['code_list'],
    data_src='custom:OfflineDataAPI.CStockFileReader',
    lv_list=[conf['lv']],
    chan_config=get_statics_chan_config({'mean_metrics': [5, 20, 60], 'trend_metrics': [10, 20], 'cal_rsi': True, 'cal_kdj': True, 'cal_demark': True}),
    output_dir='$SAMPLE_DIR',
))
print(f'样本: {len(res.samples)},特征: {res.feature_cnt}')
"
python -m ModelStrategy.models.Xgboost.XGBTrainModelGenerator "$SAMPLE_DIR"
python -m ModelStrategy.models.lightGBM.LGBMModelGenerator "$SAMPLE_DIR"
python -m ModelStrategy.models.deepModel.MLPModelGenerator "$SAMPLE_DIR"
