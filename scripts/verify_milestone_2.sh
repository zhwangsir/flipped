#!/usr/bin/env bash
# M2 一键验收：Cline(headless CLI, 与编辑器同一 agent core) 经 LiteLLM :4000 完成多文件改动任务。
# 前置：LiteLLM(:4000) 在跑 + exo 集群在服务 + cline CLI 已装(npm i -g cline)。
set -uo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; . ./.env; set +a; }
export PATH="$PATH:/opt/homebrew/bin"
export NO_PROXY="localhost,127.0.0.1,100.64.201.37,::1"; export no_proxy="$NO_PROXY"
DDIR="$PWD/.cline-data"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

command -v cline >/dev/null 2>&1 || { echo "  ❌ cline 未安装 (npm i -g cline)"; exit 1; }

echo "== M2.2 配置 Cline OpenAI-Compatible -> :4000 =="
cline auth openai-compatible -k "${LITELLM_MASTER_KEY:-}" -m coder -b http://localhost:4000/v1 --data-dir "$DDIR" >/dev/null 2>&1 \
  && pass "openai-compatible 已配置(coder/architect 共用)" || bad "cline auth 失败"

echo "== M2.3 architect(GLM) 经 :4000 可用(curl 直验, 快而稳) =="
# GLM 是推理模型, cline plan 模式 headless 太慢/易抖; 用 curl 证明 architect 别名经 :4000 路由到 GLM
# (cline 用的正是同一端点; coder/Kimi 的完整 agent loop 见 M2.4)
rc=$(curl -s -o /dev/null -w '%{http_code}' --max-time 90 http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY:-}" -H 'Content-Type: application/json' \
  -d '{"model":"architect","messages":[{"role":"user","content":"hi"}],"max_tokens":8}' || echo 000)
[ "$rc" = "200" ] && pass "architect/GLM 经 :4000 可用 (HTTP $rc)" || bad "architect 不可用 (HTTP $rc)"

echo "== M2.4 coder(Kimi) 多文件改动端到端(读->改->跑->自检) =="
F=$(mktemp -d)
printf 'def add(a, b):\n    return a - b\n' > "$F/mathlib.py"
printf 'from mathlib import add\n\n\ndef total():\n    return add(1, 2)\n' > "$F/app.py"
printf 'import mathlib, app\nassert mathlib.add(2,3)==5\nassert mathlib.multiply(2,3)==6\nassert app.total()==3\nassert app.product()==12\nprint("ALL PASS")\n' > "$F/test_math.py"
( cd "$F" && git init -q && git add -A && git -c user.name=t -c user.email=t@t commit -qm base )
cline --json --auto-approve true -P openai-compatible -m coder --data-dir "$DDIR" -c "$F" --timeout 280 \
  "Fix the add bug in mathlib.py, add multiply(a,b) to mathlib.py, and add product() returning multiply(3,4) to app.py, so that 'python3 test_math.py' prints ALL PASS. Run python3 test_math.py to confirm." >/dev/null 2>&1
if ( cd "$F" && python3 test_math.py >/dev/null 2>&1 ); then
  nf=$(cd "$F" && git -c user.name=t -c user.email=t@t diff --name-only | wc -l | tr -d ' ')
  [ "${nf:-0}" -ge 2 ] && pass "多文件改动通过(ALL PASS, 改动文件=$nf)" || bad "测试过但改动文件<2($nf)"
else
  bad "测试未通过(cline 未修复成功)"
fi
rm -rf "$F"

echo ""
[ $fail -eq 0 ] && echo "M2 验收：全部通过 ✅" || echo "M2 验收：有未通过项 ❌"
exit $fail
