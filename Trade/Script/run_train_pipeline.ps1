# 显式 spec 的单一有界入口；无默认行情、旧模型重用或下单授权。
param([string]$SpecPath)
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($SpecPath)) {
    Write-Error "Usage: run_train_pipeline.ps1 <training-spec.json>"
    exit 2
}
$taskSpecPath = (Resolve-Path -LiteralPath $SpecPath).Path
Set-Location (Join-Path $PSScriptRoot "../..")
python -m ModelStrategy.training_pipeline --spec $taskSpecPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
