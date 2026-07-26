#!/bin/bash
# 调度脚本读取配置用法: source Config/config.sh && chan_config_get db.type
# Windows 下请用同目录 config.ps1

CHAN_CONFIG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

chan_config_get() {
    python "${CHAN_CONFIG_DIR}/EnvConfig.py" "$1"
}
