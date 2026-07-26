# Windows 版训练调度: . 用法: pwsh train_all_model.ps1 [样本目录]
param([string]$SampleDir = "./backtest_output")
Set-Location (Join-Path $PSScriptRoot "../..")
python -m ModelStrategy.models.Xgboost.XGBTrainModelGenerator $SampleDir
python -m ModelStrategy.models.lightGBM.LGBMModelGenerator $SampleDir
python -m ModelStrategy.models.deepModel.MLPModelGenerator $SampleDir
