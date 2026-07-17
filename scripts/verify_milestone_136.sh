#!/usr/bin/env bash
# M136 验收 — API 契约治理(B) + 终端数据通路测试(C)。
#
#   B1  OpenAPI 快照漂移检测 + 新路由命名 response_model 覆盖
#   B2  事件 WS ack 语义（ack→ack_ok、垃圾帧容错、既有消息流回归）
#   B3  零依赖 openapi→TS 类型生成器：实时后端重生成，与已提交 api-types.d.ts 逐字节比对 + tsc
#   C   waitFor 事件驱动等待单测 + 终端 WS 数据通路集成测试（真实 uvicorn+pty+headless xterm）
#
# 一键复跑: scripts/verify_milestone_136.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

echo "== M136-B1/B2 API 契约 pytest（快照漂移 + response_model 覆盖 + WS ack） =="
PYTHONPATH=src $PY -m pytest tests/test_api_contract.py -q && pass "test_api_contract.py 全绿" || bad "test_api_contract.py 失败"

echo "== M136-C1 waitFor 事件驱动等待 单测 =="
( cd console && npx vitest run src/terminal/waitFor.test.ts ) && pass "waitFor 单测通过" || bad "waitFor 单测失败"

echo "== M136-C2 终端 WS 数据通路 集成测试（spawn 真实 uvicorn+pty） =="
( cd console && npx vitest run src/terminal/terminal.ws.test.ts ) && pass "终端 WS 数据通路通过" || bad "终端 WS 数据通路失败"

echo "== M136-B3a 前端类型检查 tsc --noEmit（含生成的 api-types.d.ts） =="
( cd console && npx tsc --noEmit ) && pass "tsc 无错误" || bad "tsc 报错"

echo "== M136-B3b codegen 实跑 + 提交版类型与实时契约漂移比对 =="
PORT=8136
TMPD=$(mktemp -d)
PYTHONPATH=src $PY -m uvicorn api.main:app --host 127.0.0.1 --port $PORT >"$TMPD/uvicorn.log" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null; rm -rf "$TMPD"' EXIT
up=0
for _ in $(seq 1 40); do curl -sf "http://127.0.0.1:$PORT/api/v1/health" >/dev/null 2>&1 && { up=1; break; }; sleep 0.5; done
if [ "$up" = "1" ]; then
  ( cd console && FLIPPED_API_URL="http://127.0.0.1:$PORT" FLIPPED_API_TYPES_OUT="$TMPD/fresh.d.ts" node scripts/gen-api-types.mjs ) \
    && pass "codegen 对实时后端实跑成功" || bad "codegen 实跑失败"
  # 已提交类型必须 == 实时契约重生成（忽略 banner 中端口差异，只比类型主体）
  if diff <(grep -v '^ \* 来源' console/src/api-types.d.ts) <(grep -v '^ \* 来源' "$TMPD/fresh.d.ts") >/dev/null; then
    pass "已提交 api-types.d.ts 与实时契约一致（无漂移）"
  else
    bad "api-types.d.ts 与实时契约漂移 → 重跑: (cd console && npm run gen:api-types)"
  fi
else
  bad "验收用后端未能启动（日志: $TMPD/uvicorn.log）"; cat "$TMPD/uvicorn.log" | tail -5
fi

echo ""
if [ $fail -eq 0 ]; then echo "M136（API 契约治理 + 终端数据通路测试）验收：通过 ✅"; else echo "M136 验收：有未通过 ❌"; fi
exit $fail
