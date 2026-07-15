#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${NORMALIZE_PROXY_PORT:-4001}"
UPSTREAM="${NORMALIZE_PROXY_UPSTREAM:-http://localhost:4000}"
echo "Starting OpenAI normalize proxy on port $PORT, upstream $UPSTREAM"
exec .venv/bin/uvicorn src.proxy.openai_normalize_proxy:app --host 127.0.0.1 --port "$PORT"

