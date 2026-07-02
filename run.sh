#!/bin/bash
# 运行 quant-marketing-daily 管道（自动使用 venv）
set -e
cd "$(dirname "$0")"
./venv/bin/python -m src.fetch "$@"
