# 例行(Windows 版):更新离线数据 → 计算信号 → 检查突破开仓 → 实时跟踪
Set-Location (Join-Path $PSScriptRoot "../..")

python -m OfflineData.ccxt_update BTC/USDT K_4H K_60M K_15M
python -m OfflineData.ccxt_update ETH/USDT K_4H K_60M K_15M
python -m Trade.Script.SignalMonitor
python -m Trade.Script.MakeOpenTrade
python -m Trade.Script.CheckOpenScore
python -m Trade.Script.ClosePreErrorOpen
python -m Trade.Script.RealTimeTracker
python -m Trade.Script.RetradeCoverOrder
