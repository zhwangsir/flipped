#!/usr/bin/env bash
# M143 · 真实 IDE 桥运行时验收（M141/M142 已知限制收口）
#
# 验收对象：ide-extension（VS Code 扩展，127.0.0.1:39217 POST /tool，9 工具）
#           + src/driving/ide_tools.py governed_ide_call 五级管线 + factory_events 审计。
# 形态：隔离 VS Code 实例（--user-data-dir/--extensions-dir 全隔离，不碰用户真实 VS Code）
#       + --extensionDevelopmentPath 加载开发版扩展 → Extension Development Host 自动激活起桥
#       → Python 验证矩阵（scripts/verify_m143_ide_bridge.py）真实调桥。
#
# 注意：
#   1. macOS 无真 headless VS Code——会闪一个 Extension Development Host 窗口，脚本结束自动关闭。
#   2. 39217 端口冲突保护：占用时先尝试只杀 dev-host 形态残留，仍占用则拒绝起跑（防误连真实实例）。
#   3. trap 清理兜底：无论成败都杀隔离实例 + 删临时工作区，不残留窗口。
#
# 退出码：0 = CORE 全绿；1 = 有失败。
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

fail=0
pass(){ echo "  ✅ $1"; }
bad(){ echo "  ❌ $1"; fail=1; }
warn(){ echo "  ⚠️  $1"; }
info(){ echo "  ℹ️  $1"; }

PORT="${M143_BRIDGE_PORT:-39217}"
BRIDGE="http://127.0.0.1:${PORT}"
WS=""

cleanup() {
  if [ -n "$WS" ] && [ -d "$WS" ]; then
    pkill -f "$WS/user-data" >/dev/null 2>&1
    sleep 1
    pkill -9 -f "$WS/user-data" >/dev/null 2>&1
    rm -rf "$WS"
  fi
}
trap cleanup EXIT

echo "== [0/5] 前置检查 =="
command -v code >/dev/null 2>&1 && pass "code CLI $(code --version | head -1)" || { bad "code CLI 缺失（VS Code 未安装或未入 PATH）"; exit 1; }

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  warn "端口 $PORT 被占用，尝试清理 dev-host 残留…"
  pkill -f "extensionDevelopmentPath=.*ide-extension" >/dev/null 2>&1
  sleep 2
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    bad "端口 $PORT 仍被非 dev-host 进程占用，拒绝起跑（防误连真实实例）：$(lsof -nP -iTCP:$PORT -sTCP:LISTEN | tail -1)"
    exit 1
  fi
  pass "dev-host 残留已清理"
else
  pass "端口 $PORT 空闲"
fi

echo "== [1/5] 编译 ide-extension =="
if [ ! -d ide-extension/node_modules ]; then
  info "node_modules 缺失，npm ci（npmmirror）…"
  (cd ide-extension && npm ci --registry=https://registry.npmmirror.com >/dev/null 2>&1) || { bad "npm ci 失败"; exit 1; }
fi
if (cd ide-extension && npm run compile >/tmp/m143_tsc.log 2>&1); then
  pass "tsc 编译成功"
else
  bad "tsc 编译失败："; tail -5 /tmp/m143_tsc.log; exit 1
fi

echo "== [2/5] 准备隔离验收工作区 =="
WS="$(mktemp -d /tmp/m143-ide-bridge.XXXXXX)"
mkdir -p "$WS/.vscode"
cat > "$WS/.vscode/settings.json" <<'EOF'
{ "editor.fontSize": 13 }
EOF
cat > "$WS/.vscode/tasks.json" <<'EOF'
{
  "version": "2.0.0",
  "tasks": [
    { "label": "m144-echo", "type": "shell", "command": "echo m144-ok", "problemMatcher": [] }
  ]
}
EOF
pass "workspace: ${WS}（标记值 editor.fontSize=13 + tasks.json 任务 m144-echo）"

echo "== [3/5] 启动隔离 Extension Development Host（窗口会闪现，结束自动关闭）=="
code --no-sandbox --disable-gpu --disable-crash-reporter \
     --user-data-dir="$WS/user-data" --extensions-dir="$WS/exts" \
     --extensionDevelopmentPath="$ROOT/ide-extension" \
     --disable-workspace-trust --skip-welcome --skip-release-notes \
     "$WS" > "$WS/code.log" 2>&1 &
CODE_PID=$!
info "code 启动 pid=${CODE_PID}，等待桥就绪（≤90s）…"

ready=0
for i in $(seq 1 45); do
  RESP=$(curl -s -m 2 -X POST "$BRIDGE/tool" -H 'Content-Type: application/json' \
         -d '{"name":"ide.getSetting","args":{"section":"editor.fontSize"}}' 2>/dev/null)
  if echo "$RESP" | grep -q '"ok":true'; then
    ready=1
    pass "桥就绪（第 ${i} 次探测）：$RESP"
    break
  fi
  # code CLI 立即退出但宿主没起来 → 提前失败
  if ! kill -0 "$CODE_PID" 2>/dev/null && ! pgrep -f "$WS/user-data" >/dev/null 2>&1; then
    bad "VS Code 进程已退出，桥未就绪。code.log 尾："; tail -8 "$WS/code.log"
    exit 1
  fi
  sleep 2
done
if [ "$ready" != "1" ]; then
  bad "90s 内桥未就绪。code.log 尾："; tail -8 "$WS/code.log"
  exit 1
fi

echo "== [4/5] Python 验证矩阵（governed 五级管线 × 真实桥）=="
if .venv/bin/python scripts/verify_m143_ide_bridge.py --db "$WS/audit.db" --base-url "$BRIDGE" --ws "$WS"; then
  pass "验证矩阵全绿"
else
  bad "验证矩阵有未通过项"
fi

echo "== [5/5] 清理（trap 兜底：杀隔离实例 + 删临时工作区）=="
info "隔离实例 user-data=$WS/user-data 将被精确清理"

echo ""
if [ $fail -eq 0 ]; then echo "M143 真实 IDE 桥运行时验收 CORE：通过 ✅"; else echo "M143 真实 IDE 桥运行时验收：有未通过 ❌"; fi
exit $fail
