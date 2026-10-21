# 显式配置的唯一串行入口；Python 负责失败阻断与独立已有仓位管理。
param([string]$ConfigPath, [string]$ReportPath)
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ConfigPath) -or [string]::IsNullOrWhiteSpace($ReportPath)) {
    [Console]::Error.WriteLine("Usage: update_data_signal.ps1 <config.yaml> <new-report.jsonl>")
    exit 2
}
$taskCycleConfig = (Resolve-Path -LiteralPath $ConfigPath).Path
$taskCycleReport = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ReportPath)
Set-Location (Join-Path $PSScriptRoot "../..")
python -m Trade.Script.RunTradeCycle --config $taskCycleConfig --report $taskCycleReport
exit $LASTEXITCODE
