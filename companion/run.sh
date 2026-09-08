#!/usr/bin/env bash
# aipassport 统一运行入口
# 为什么需要它：macOS 没有 `python` 命令，且本项目所有依赖
# （bleak / whisper-cpp-python / sounddevice / Quartz…）都装在
# fork 专用 venv 里，系统 python3 缺包会直接报错。
#
# 用法（在 companion/ 目录下）：
#   ./run.sh probe_gatt.py 03C18CD7-85B8-52D7-F9CA-D375531D5474
#   ./run.sh scan_ble.py 20
#   ./run.sh mic_relay.py --no-inject
#   ./run.sh relay.py
set -euo pipefail

PY="/Users/Zhuanz/.workbuddy/binaries/python/envs/default/bin/python"

if [ ! -x "$PY" ]; then
  echo "[run.sh] 找不到 venv python: $PY" >&2
  echo "         请确认 /Users/Zhuanz/.workbuddy/binaries/python/envs/default 存在" >&2
  exit 127
fi

cd "$(dirname "$0")"
exec "$PY" "$@"
