#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== M4 依赖检查 =="
.venv/bin/python -c "import mcp, chromadb; print('mcp', getattr(mcp, '__version__', 'n/a'), 'chromadb', chromadb.__version__)"

echo "== M4 单元测试 (RAG + MCP + Researcher) =="
PYTHONPATH=src .venv/bin/python -m pytest tests/test_rag.py tests/test_researcher.py tests/test_mcp_server.py -q

echo "== 全量回归 =="
PYTHONPATH=src .venv/bin/python -m pytest tests/ -q

echo "== M4 验收完成 =="
