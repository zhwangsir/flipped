#!/bin/bash
# M8.T3 验收脚本：Tauri 原生终端面板
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== M8.T3 验证：Tauri portable-pty 终端面板 =="

echo "[1/4] Python 全量回归测试"
source .venv/bin/activate
PYTHONPATH=src python -m pytest tests/ -q

echo "[2/4] Console 生产构建"
cd console
npm run build
cd ..

echo "[3/4] Tauri Rust 构建"
cd console/src-tauri
cargo build
cd ../..

echo "[4/4] Tauri Rust 单元测试"
cd console/src-tauri
cargo test
cd ../..

echo "== M8.T3 验证通过 =="
