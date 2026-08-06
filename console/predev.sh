#!/usr/bin/env bash
# Tauri beforeDevCommand:一条命令拉起全栈。
# 后端(orchestration-api :8011)未起则后台拉起,前端(vite :5273)前台跑(Tauri 等 devUrl)。
# 由 `cd console && cargo tauri dev` 触发。自定位,不依赖调用目录。
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # console/
ROOT="$(cd "$HERE/.." && pwd)"                          # repo root
BACKEND_PORT="${FLIPPED_BACKEND_PORT:-8011}"
BACKEND_HEALTH="http://127.0.0.1:${BACKEND_PORT}/api/v1/sessions"

# M197.5（消化 L-M181-4）：FLIPPED_BIND_ALL=1 一键局域网模式——绑 0.0.0.0 手机可达
BIND_HOST="127.0.0.1"
[ "${FLIPPED_BIND_ALL:-0}" = "1" ] && BIND_HOST="0.0.0.0"

if curl -sf -o /dev/null "$BACKEND_HEALTH" 2>/dev/null; then
  echo "[predev] 后端 :$BACKEND_PORT 已在运行,跳过"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  echo "[predev] 起 orchestration-api :$BACKEND_PORT (host=$BIND_HOST)"
  mkdir -p "$ROOT/logs"
  ( cd "$ROOT" \
    && NO_PROXY="100.64.201.37,localhost,127.0.0.1,::1" no_proxy="100.64.201.37,localhost,127.0.0.1,::1" \
       PYTHONPATH=src EXO_API_KEY="${EXO_API_KEY:-dummy}" \
       nohup .venv/bin/python -m uvicorn api.main:app --host "$BIND_HOST" --port "$BACKEND_PORT" \
       > "$ROOT/logs/tauri-backend.log" 2>&1 & )
else
  echo "[predev] ⚠ 未找到 .venv;跳过后端自启(请手动起后端 :$BACKEND_PORT)"
fi

# 前端(前台;Tauri 等 devUrl=:5273)。api.ts 默认已指向 8011,这里显式传更稳。
cd "$HERE"
exec env VITE_API_BASE_URL="http://127.0.0.1:${BACKEND_PORT}" npm run dev
