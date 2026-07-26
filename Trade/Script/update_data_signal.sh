#!/bin/bash
# 例行:更新离线数据 → 计算信号 → 检查突破开仓 → 实时跟踪(crypto 7×24,可放 crontab 每小时)
cd "$(dirname "$0")/../.." || exit 1

python -m OfflineData.ccxt_update BTC/USDT K_60M
python -m OfflineData.ccxt_update ETH/USDT K_60M
python -m Trade.Script.SignalMonitor
python -m Trade.Script.MakeOpenTrade
python -m Trade.Script.CheckOpenScore
python -m Trade.Script.ClosePreErrorOpen
python -m Trade.Script.RealTimeTracker
python -m Trade.Script.RetradeCoverOrder
