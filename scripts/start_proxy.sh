#!/usr/bin/env bash
# 启动 LiteLLM 代理 (:4000)。
# 前置: .venv 已装 litellm[proxy] (uv pip install 'litellm[proxy]'); .env 已配(见 .env.example)。
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "缺少 .env — 复制 .env.example 为 .env 并填值"; exit 1; }
[ -x .venv/bin/litellm ] || { echo "缺少 .venv/bin/litellm — 先 uv venv && uv pip install 'litellm[proxy]'"; exit 1; }
set -a; . ./.env; set +a
echo "启动 LiteLLM 代理 :4000 (别名 architect=GLM-5.2 / coder=Kimi-K2.7-Code) ..."
exec .venv/bin/litellm --config infra/litellm/config.yaml --port 4000
