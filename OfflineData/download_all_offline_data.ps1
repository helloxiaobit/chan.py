# 全量离线数据更新示例(Windows 版,按需修改symbol/code列表)
Set-Location (Join-Path $PSScriptRoot "..")

# 加密货币(实盘主场景)
python -m OfflineData.ccxt_update BTC/USDT K_60M K_DAY
python -m OfflineData.ccxt_update ETH/USDT K_60M K_DAY

# A股(研究用)
python -m OfflineData.bao_update
