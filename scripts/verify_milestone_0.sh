#!/usr/bin/env bash
# M0 一键验收（AGENTS.md §3/§8）。任何必需步骤失败 -> 退出码非 0。
# 诚实反映当前状态：集群未恢复(502)时 M0.4/M0.5 会 FAIL，这是事实而非脚本错误。
set -uo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; . ./.env; set +a; }
# 绕开本机 HTTP_PROXY，否则 curl(小写 http_proxy 未设故 OK)外的 python 请求会被代理劫持成 502
export NO_PROXY="100.64.201.37,localhost,127.0.0.1,::1,.local"
export no_proxy="$NO_PROXY"

EXO="http://100.64.201.37:52415"
PROXY="http://localhost:4000"
GLM="mlx-community/GLM-5.2-DQ4plus-q8"
KIMI="mlx-community/Kimi-K2.7-Code-4bit"
PY="$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3 )"
fail=0
pass(){ echo "  ✅ $1"; }
bad(){ echo "  ❌ $1"; fail=1; }

echo "== M0.2 exo 集群目录 =="
models=$(curl -s --max-time 10 "$EXO/v1/models" || true)
echo "$models" | grep -q "GLM-5.2-DQ4plus-q8" && pass "GLM-5.2 在目录" || bad "GLM-5.2 不在目录"
echo "$models" | grep -q "Kimi-K2.7-Code-4bit" && pass "Kimi-K2.7-Code 在目录" || bad "Kimi-K2.7-Code 不在目录"

echo "== M0.3 LiteLLM 代理别名 =="
pm=$(curl -s --max-time 10 "$PROXY/v1/models" -H "Authorization: Bearer ${LITELLM_MASTER_KEY:-}" || true)
echo "$pm" | grep -q '"architect"' && pass "architect 别名暴露" || bad "architect 别名缺失(代理未起? 跑 scripts/start_proxy.sh)"
echo "$pm" | grep -q '"coder"' && pass "coder 别名暴露" || bad "coder 别名缺失"

echo "== M0.4 工具调用解析(经 exo 直连, 命根子) =="
"$PY" scripts/toolcall_test.py "$GLM" "$EXO/v1/chat/completions" && pass "GLM-5.2 工具调用解析" || bad "GLM-5.2 工具调用(集群 502 或解析失败)"
"$PY" scripts/toolcall_test.py "$KIMI" "$EXO/v1/chat/completions" && pass "Kimi 工具调用解析" || bad "Kimi 工具调用(集群 502 或解析失败)"

echo "== M0.5 经代理别名路由 =="
rc=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$PROXY/v1/chat/completions" \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY:-}" -H 'Content-Type: application/json' \
  -d '{"model":"architect","messages":[{"role":"user","content":"hi"}],"max_tokens":4}' || echo 000)
[ "$rc" = "200" ] && pass "architect 经代理路由 200" || bad "architect 经代理路由 HTTP $rc (上游 502 或降级耗尽)"

echo ""
if [ $fail -eq 0 ]; then echo "M0 验收：全部通过 ✅"; else echo "M0 验收：有未通过项 ❌（集群恢复后重跑此脚本）"; fi
exit $fail
