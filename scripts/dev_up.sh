#!/usr/bin/env bash
# flipped 一键起全栈(M6.7)。幂等:已在跑的服务会跳过。
# 组件:OpenHands agent-server 沙盒(:8000)→ orchestration-api 真实后端(:8011)→ Console(:5273)。
# 模型:LiteLLM :4000 健康则走它,否则 exo 直连(model_router 自动,M6.6)。
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LOGDIR="${FLIPPED_LOGDIR:-$ROOT/.devlogs}"
mkdir -p "$LOGDIR"

BACKEND_PORT="${FLIPPED_BACKEND_PORT:-8011}"
CONSOLE_PORT="${FLIPPED_CONSOLE_PORT:-5273}"
OH_PORT="${FLIPPED_OH_PORT:-8000}"
OH_IMAGE="ghcr.io/openhands/agent-canvas:1.0.0-rc.11"
EXO="${FLIPPED_MODEL_BASE_URL:-http://100.64.201.37:52415/v1}"
export NO_PROXY="${EXO#http://}"; NO_PROXY="100.64.201.37,localhost,127.0.0.1,::1"
export no_proxy="$NO_PROXY"

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
up() { curl -sf -o /dev/null -m 3 "$1" 2>/dev/null; }
waitfor() { local i=0; until up "$1"; do i=$((i+1)); [ "$i" -gt "${3:-60}" ] && return 1; sleep 1; done; echo "  ✓ $2"; }

say "1) 前置检查"
docker info >/dev/null 2>&1 && echo "  ✓ Docker" || { echo "  ✗ Docker 未运行,请先启动 Docker Desktop"; exit 1; }
if curl -sf -o /dev/null -m4 "$EXO/models" 2>/dev/null; then echo "  ✓ exo 模型端点可达 ($EXO)"; else echo "  ⚠ exo 端点不可达 —— 真实任务会失败,请确认 exo 集群已 LAUNCH 模型"; fi
[ -d .venv ] || { echo "  ✗ 缺 .venv,请先 bash scripts/setup.sh"; exit 1; }

say "2) OpenHands 沙盒 agent-server (:$OH_PORT)"
if up "http://localhost:$OH_PORT/alive"; then
  echo "  ✓ 已在运行"
elif docker ps -a --format '{{.Names}}' | grep -q '^flipped-oh-canvas$'; then
  docker start flipped-oh-canvas >/dev/null && waitfor "http://localhost:$OH_PORT/alive" "agent-server 就绪" 60 || echo "  ⚠ 启动超时,看 docker logs flipped-oh-canvas"
else
  echo "  · 首次创建容器(镜像 $OH_IMAGE)"
  mkdir -p "$HOME/.openhands" "$HOME/projects"
  docker run -d --name flipped-oh-canvas -p "$OH_PORT:8000" \
    --add-host host.docker.internal:host-gateway \
    -v "$HOME/.openhands:/home/openhands/.openhands" \
    -v "$HOME/projects:/projects" "$OH_IMAGE" >/dev/null
  waitfor "http://localhost:$OH_PORT/alive" "agent-server 就绪" 90 || echo "  ⚠ 启动超时"
fi

say "3) orchestration-api 真实后端 (:$BACKEND_PORT)"
if up "http://127.0.0.1:$BACKEND_PORT/api/v1/sessions"; then
  echo "  ✓ 已在运行"
else
  PYTHONPATH=src EXO_API_KEY="${EXO_API_KEY:-dummy}" \
    OPENHANDS_AGENT_HOST="http://localhost:$OH_PORT" \
    FLIPPED_MODEL_BASE_URL="$EXO" \
    FLIPPED_ARCHITECT_MODEL="${FLIPPED_ARCHITECT_MODEL:-mlx-community/GLM-5.2-fp8}" \
    FLIPPED_SESSION_STORE_PATH="${FLIPPED_SESSION_STORE_PATH:-$ROOT/.sessions.json}" \
    nohup .venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port "$BACKEND_PORT" \
    > "$LOGDIR/backend.log" 2>&1 &
  echo "  · pid $! → $LOGDIR/backend.log"
  waitfor "http://127.0.0.1:$BACKEND_PORT/api/v1/sessions" "后端就绪" 40 || echo "  ⚠ 后端启动超时,看 $LOGDIR/backend.log"
fi

say "4) Console 前端 (:$CONSOLE_PORT)"
if up "http://127.0.0.1:$CONSOLE_PORT"; then
  echo "  ✓ 已在运行"
else
  ( cd console && [ -d node_modules ] || npm install >/dev/null 2>&1
    VITE_API_BASE_URL="http://127.0.0.1:$BACKEND_PORT" nohup npm run dev > "$LOGDIR/console.log" 2>&1 & )
  echo "  · → $LOGDIR/console.log"
  waitfor "http://127.0.0.1:$CONSOLE_PORT" "Console 就绪" 40 || echo "  ⚠ Console 启动超时"
fi

say "全栈就绪"
cat <<EOF
  Console      http://127.0.0.1:$CONSOLE_PORT
  后端 API     http://127.0.0.1:$BACKEND_PORT/api/v1
  沙盒 server  http://localhost:$OH_PORT
  日志         $LOGDIR/
  停止         bash scripts/dev_down.sh
在 Console 里发任务即真跑沙盒(真实 Kimi via ${EXO})。
EOF
