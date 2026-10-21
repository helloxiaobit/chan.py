#!/bin/bash
# 与 PS1 共用同一串行入口，不在 shell 拼装第二套阶段/交易逻辑。
set -euo pipefail
if [[ $# -ne 2 || -z "$1" || -z "$2" ]]; then
    echo "Usage: update_data_signal.sh <config.yaml> <new-report.jsonl>" >&2
    exit 2
fi
TASK_CYCLE_CONFIG=$1
TASK_CYCLE_REPORT=$2
case "$TASK_CYCLE_CONFIG" in
    /*|[A-Za-z]:/*|[A-Za-z]:\\*) ;;
    *) TASK_CYCLE_CONFIG="$PWD/$TASK_CYCLE_CONFIG" ;;
esac
case "$TASK_CYCLE_REPORT" in
    /*|[A-Za-z]:/*|[A-Za-z]:\\*) ;;
    *) TASK_CYCLE_REPORT="$PWD/$TASK_CYCLE_REPORT" ;;
esac
cd "$(dirname "$0")/../.."
exec python -m Trade.Script.RunTradeCycle --config "$TASK_CYCLE_CONFIG" --report "$TASK_CYCLE_REPORT"
