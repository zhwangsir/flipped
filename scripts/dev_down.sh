#!/usr/bin/env bash
# 停 flipped 全栈(M6.7)。默认停后端 + Console;--all 连 OpenHands 沙盒容器一起停。
set -uo pipefail
BACKEND_PORT="${FLIPPED_BACKEND_PORT:-8011}"
CONSOLE_PORT="${FLIPPED_CONSOLE_PORT:-5273}"

echo "停 orchestration-api (:$BACKEND_PORT)"
pkill -f "uvicorn api.main:app --host 127.0.0.1 --port $BACKEND_PORT" 2>/dev/null && echo "  ✓ 后端已停" || echo "  · 后端未在跑"

echo "停 Console 前端 (:$CONSOLE_PORT)"
# M146：按监听端口精确杀——旧版 `pkill -f "vite"` 会误杀本机所有 vite 项目
pids=$(lsof -ti tcp:"$CONSOLE_PORT" -sTCP:LISTEN 2>/dev/null || true)
if [ -n "$pids" ]; then
  echo "$pids" | xargs kill 2>/dev/null && echo "  ✓ Console 已停" || echo "  · Console 停止失败"
else
  echo "  · Console 未在跑"
fi

if [ "${1:-}" = "--all" ]; then
  echo "停 OpenHands 沙盒容器"
  docker stop flipped-oh-canvas >/dev/null 2>&1 && echo "  ✓ 容器已停" || echo "  · 容器未在跑"
fi
echo "完成。(OpenHands 容器默认保留;加 --all 一并停)"
