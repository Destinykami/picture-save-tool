#!/usr/bin/env bash
# 一键启动开发服务器：./run.sh
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  uv venv .venv
  uv pip install -r requirements.txt --python .venv/bin/python
fi

export XHS_COOKIE="${XHS_COOKIE:-}"
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" "$@"
