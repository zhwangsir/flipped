#!/usr/bin/env bash
# M3 驾驭层验收（随能力逐步增长）。当前覆盖：M3.2 可观测。
# 前置：LiteLLM(:4000) + exo 在服务 + cline CLI 已装。
set -uo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; . ./.env; set +a; }
export PATH="$PATH:/opt/homebrew/bin"
export NO_PROXY="localhost,127.0.0.1,100.64.201.37,::1"; export no_proxy="$NO_PROXY"
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
DDIR="$PWD/.cline-data"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

command -v cline >/dev/null 2>&1 || { echo "  ❌ cline 未安装"; exit 1; }

echo "== M3.2a observe 解析单测（纯函数） =="
$PY tests/test_observe.py >/dev/null 2>&1 && pass "observe 单测通过" || bad "observe 单测失败"

echo "== M3.2b 真实 cline 运行 → 结构化可观测轨迹 =="
F=$(mktemp -d); AUD="$F/audit.jsonl"
$PY -c "
import sys; sys.path.insert(0,'src')
from driving.observe import run_and_observe
r = run_and_observe('Create a file note.txt with content hi, then run: cat note.txt', '$F', data_dir='$DDIR', timeout=160, audit_path='$AUD')
print('   summary:', r['summary'])
import os
ok = r['ok'] and r['summary']['tool_calls'] >= 1 and r['summary']['tools_used'] and os.path.exists('$AUD')
sys.exit(0 if ok else 1)
" && pass "cline 运行被可观测（工具调用捕获 + 审计落盘）" || bad "可观测集成失败"
rm -rf "$F"

echo ""
if [ $fail -eq 0 ]; then echo "M3（当前 M3.2）验收：通过 ✅"; else echo "M3 验收：有未通过 ❌"; fi
exit $fail
