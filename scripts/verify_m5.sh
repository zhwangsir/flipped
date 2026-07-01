#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== M5.1 性能可观测单测 =="
PYTHONPATH=src .venv/bin/python -m pytest tests/test_metrics.py -q

echo "== M5.5 安全单测 =="
PYTHONPATH=src .venv/bin/python -m pytest tests/test_safety.py -q

echo "== M5 全量回归 =="
PYTHONPATH=src .venv/bin/python -m pytest tests/ -q

echo "== Console 构建 =="
cd console
npm run build
cd ..

echo "== M5 验收完成 =="
