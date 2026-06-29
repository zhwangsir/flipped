#!/usr/bin/env bash
# M1 一键验收（AGENTS.md §3/§8）。前置：SearXNG(:8080) + LiteLLM(:4000) 在跑。
set -uo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; . ./.env; set +a; }
export NO_PROXY="100.64.201.37,localhost,127.0.0.1,::1,.local"; export no_proxy="$NO_PROXY"
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

echo "== M1.1 SearXNG JSON 搜索(引擎经 Clash 易抖, 多 query 重试) =="
n=0
for q in LangGraph "model+context+protocol" python wikipedia; do
  n=$(curl -s --max-time 45 "http://localhost:8080/search?q=${q}&format=json" | $PY -c "import sys,json;print(len(json.load(sys.stdin).get('results',[])))" 2>/dev/null || echo 0)
  [ "${n:-0}" -ge 1 ] && break
done
[ "${n:-0}" -ge 1 ] && pass "SearXNG 返回 $n 条结果" || bad "SearXNG 无结果(容器在跑? 引擎超时?)"

echo "== M1.2 web_search 工具单测 =="
$PY tests/test_web_search.py && pass "web_search 单测通过" || bad "web_search 单测失败"

echo "== M1.3 agent loop 端到端(自主搜索 + 有来源) =="
$PY -c "
import sys; sys.path.insert(0,'src')
from agent.loop import run_query
out=run_query('搜索 Model Context Protocol 是什么, 用中文简述并给出来源 URL')
ok = out['searched'] and ('http' in out['answer'])
print('    searched=%s | 答案含URL=%s | 消息数=%s' % (out['searched'], 'http' in out['answer'], out['n_messages']))
sys.exit(0 if ok else 1)
" && pass "agent 自主搜索并给出有来源答案" || bad "agent loop 未达标"

echo ""
if [ $fail -eq 0 ]; then echo "M1 验收：全部通过 ✅"; else echo "M1 验收：有未通过项 ❌"; fi
exit $fail
