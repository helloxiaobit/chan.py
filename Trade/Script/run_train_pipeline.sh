#!/bin/bash
# 与 PowerShell 共用显式 spec 入口；不在 shell 内拼接训练代码或续用旧模型。
set -euo pipefail
if [[ $# -ne 1 || -z "$1" ]]; then
    echo "Usage: run_train_pipeline.sh <training-spec.json>" >&2
    exit 2
fi
TASK_SPEC=$1
case "$TASK_SPEC" in
    /*|[A-Za-z]:/*|[A-Za-z]:\\*) ;;
    *) TASK_SPEC="$PWD/$TASK_SPEC" ;;
esac
cd "$(dirname "$0")/../.."
exec python -m ModelStrategy.training_pipeline --spec "$TASK_SPEC"
