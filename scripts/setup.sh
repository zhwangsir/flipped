#!/usr/bin/env bash
# flipped 一键环境配置。前置：uv、node/npm、docker、openssl。
set -euo pipefail
cd "$(dirname "$0")/.."
PYPI="https://pypi.tuna.tsinghua.edu.cn/simple"   # 中国网络镜像(D7)；海外可去掉 --index-url
NPM="https://registry.npmmirror.com"

echo "== 1) Python venv + 驾驭层依赖 =="
[ -d .venv ] || uv venv --python 3.11 .venv
uv pip install -r requirements.txt --index-url "$PYPI"

echo "== 2) .env =="
if [ ! -f .env ]; then
  cp .env.example .env
  MK="sk-$(openssl rand -hex 24)"
  # 注入随机 master key（EXO_API_KEY 默认 dummy，exo 内网通常无鉴权）
  python3 -c "import re,sys;p='.env';s=open(p).read();open(p,'w').write(re.sub(r'LITELLM_MASTER_KEY=.*','LITELLM_MASTER_KEY=$MK',s))"
  echo "  ✓ 已生成 .env（master key 随机；按需改 EXO_API_KEY / 端点）"
fi

echo "== 3) SearXNG 配置 =="
if [ ! -f infra/searxng/settings.yml ]; then
  cp infra/searxng/settings.yml.example infra/searxng/settings.yml
  SK="$(openssl rand -hex 32)"
  python3 -c "import re;p='infra/searxng/settings.yml';s=open(p).read();open(p,'w').write(s.replace('ultrasecretkey','$SK'))"
  echo "  ✓ 已生成 SearXNG settings.yml（secret 随机）"
fi

echo "== 4) IDE 控制面扩展依赖 + 编译 =="
( cd ide-extension && npm install --registry "$NPM" && npm run compile )

echo "== 5) Cline CLI =="
command -v cline >/dev/null 2>&1 || npm i -g cline   # 平台二进制走官方 registry

cat <<'TIP'

✅ 配置完成。启动与验收：
  bash scripts/start_proxy.sh &                                                   # LiteLLM :4000
  docker compose -f infra/searxng/docker-compose.yml --project-directory infra/searxng up -d  # SearXNG :8080
  cline auth openai-compatible -b http://localhost:4000/v1 -m coder --data-dir .cline-data
  # （exo 集群需先在其 Web UI LAUNCH architect/coder 两个模型）
  bash scripts/verify_milestone_0.sh && bash scripts/verify_milestone_3.sh
TIP
