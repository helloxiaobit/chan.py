# 调度脚本读取配置用法: . Config/config.ps1; Get-ChanConfig db.type
$script:ChanConfigDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Get-ChanConfig {
    param([Parameter(Mandatory = $true)][string]$Key)
    python (Join-Path $script:ChanConfigDir "EnvConfig.py") $Key
}
