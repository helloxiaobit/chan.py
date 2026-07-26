#!/bin/bash
# 用法: ./train_all_model.sh [样本目录],默认 ./backtest_output
cd "$(dirname "$0")/../../.." || exit 1
python -m ModelStrategy.models.Xgboost.XGBTrainModelGenerator "${1:-./backtest_output}"
