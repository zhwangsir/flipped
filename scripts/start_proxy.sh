#!/usr/bin/env bash
# 启动 LiteLLM 代理 (:4000)。
# 前置: .venv 已装 litellm[proxy] (uv pip install 'litellm[proxy]'); .env 已配(见 .env.example)。
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "缺少 .env — 复制 .env.example 为 .env 并填值"; exit 1; }
[ -x .venv/bin/litellm ] || { echo "缺少 .venv/bin/litellm — 先 uv venv && uv pip install 'litellm[proxy]'"; exit 1; }
set -a; . ./.env; set +a
# exo 上游在内网 IP，必须绕开本机 HTTP_PROXY/HTTPS_PROXY，否则 LiteLLM 的 httpx 会把
# 请求塞进本机代理(如 Clash :7890)导致 502。详见 DECISIONS.md D5 / TEST_LOG。
# M149: 加 .ts.net 后缀——config 已改用 MagicDNS 主机名 studio01-1（IP 会漂移，后缀匹配免疫）
export NO_PROXY="100.64.201.37,100.67.43.40,studio01-1,.ts.net,${NO_PROXY:-localhost,127.0.0.1,::1}"
export no_proxy="$NO_PROXY"
echo "启动 LiteLLM 代理 :4000 (M156 双模型: architect=GLM-5.2-fp8, coder=Kimi-K2.7-Code-4bit; NO_PROXY 已含 exo) ..."
# M149: --port 4000 在该 litellm 版本被吞(实测落到随机端口),改用 PORT env 传端口
PORT=4000 exec .venv/bin/litellm --config infra/litellm/config.yaml
