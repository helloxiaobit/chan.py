# 训练流水线(Windows 版):回测出样本 → 训练三套模型
param([string]$SampleDir = "./backtest_output")
Set-Location (Join-Path $PSScriptRoot "../..")

$py = @"
from ModelStrategy.BacktestChanConfig import CBacktestConfig
from ModelStrategy.backtest import run_backtest
from Trade.Script.StaticsChanConfig import get_statics_chan_config, get_trade_conf
conf = get_trade_conf()
res = run_backtest(CBacktestConfig(
    code_list=conf['code_list'],
    data_src='custom:OfflineDataAPI.CStockFileReader',
    lv_list=[conf['lv']],
    chan_config=get_statics_chan_config({'mean_metrics': [5, 20, 60], 'trend_metrics': [10, 20], 'cal_rsi': True, 'cal_kdj': True, 'cal_demark': True}),
    output_dir='$SampleDir',
))
print(f'样本: {len(res.samples)},特征: {res.feature_cnt}')
"@
python -c $py
python -m ModelStrategy.models.Xgboost.XGBTrainModelGenerator $SampleDir
python -m ModelStrategy.models.lightGBM.LGBMModelGenerator $SampleDir
python -m ModelStrategy.models.deepModel.MLPModelGenerator $SampleDir
