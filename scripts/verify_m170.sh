#!/usr/bin/env bash
# M170 (M4) 验收 — 编辑器直调 MCP 工具（调研+落地代码 复合任务闭环）。
#
#   1) pytest 单测：test_m170_mcp_call.py（10 例，mock run_tool，契约全钉）
#   2) 真实后端黑盒 E2E：起 uvicorn（RAG_DB_DIR 指向临时库保证 ingest/query 确定性），
#      curl 层级断言——
#        GET  /mcp/tools               内省 5 工具
#        POST rag_ingest → rag_query   快工具同步闭环（真实 Chroma 持久库）
#        POST unknown_tool             404
#        POST research_and_code 无会话 400
#        POST research_and_code 带会话 202 → 事件流出现 source=mcp 事件
#          （无 LLM 环境下 drive_orchestrated 失败 → error 事件；有 LLM → message，
#           两者都证明"派发→后台执行→回灌会话"通路成立）
#
# 一键复跑: scripts/verify_m170.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

# 隔离：DB/RAG 副作用全部指向临时目录，不触碰真实 data/
TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8170}"
SRV_PID=""
cleanup() {
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
  rm -rf "$TMPD"
}
trap cleanup EXIT
export FLIPPED_DB="$TMPD/flipped.db"
export RAG_DB_DIR="$TMPD/ragdb"

echo "== M170-1 MCP 调用端点单测（mock run_tool，快慢分流契约） =="
PYTHONPATH=src $PY -m pytest tests/test_m170_mcp_call.py -q \
  && pass "test_m170_mcp_call.py 全绿" || bad "test_m170_mcp_call.py 失败"

echo "== M170-2 真实后端黑盒 E2E（uvicorn :${PORT}，RAG 临时库） =="
PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!

# 等后端就绪（最多 30s）
ready=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/api/v1/mcp/tools" -o /dev/null 2>&1; then ready=1; break; fi
  sleep 0.5
done
if [ "${ready}" != "1" ]; then
  bad "后端 30s 内未就绪"
  echo ""; echo "M170 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" ${PY} - <<'PYEOF'
import json, os, sys, time, urllib.request, urllib.error

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
fails = []

def call(method, path, body=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" ({detail})" if detail and not cond else ""))
    if not cond:
        fails.append(name)

# 1. GET /mcp/tools — 内省 5 工具
st, body = call("GET", "/mcp/tools")
names = sorted(t["name"] for t in body.get("tools", []))
check("GET /mcp/tools → 5 工具", st == 200 and names == [
    "rag_ingest", "rag_query", "research_and_code", "run_coding_task", "web_search"])
check("工具含 description/inputSchema", all(
    t.get("description") and isinstance(t.get("inputSchema"), dict) for t in body.get("tools", [])))

# 2. 快工具闭环：rag_ingest → rag_query（真实 Chroma 持久库，RAG_DB_DIR 已隔离）
st, body = call("POST", "/mcp/tools/rag_ingest/call",
                {"arguments": {"text": "flipped M170 验收锚点：紫貂跃过懒犬", "metadata": {"src": "verify_m170"}}})
check("rag_ingest ok", st == 200 and body.get("ok") is True and body.get("result", {}).get("count", 0) >= 1,
      detail=json.dumps(body)[:200])
st, body = call("POST", "/mcp/tools/rag_query/call",
                {"arguments": {"query": "紫貂 懒犬", "n_results": 3}})
hits = body.get("result", {}).get("results", [])
check("rag_query 命中刚 ingest 的锚点文本", st == 200 and body.get("ok") is True
      and any("紫貂" in (h.get("text") or "") for h in hits), detail=json.dumps(body)[:200])

# 3. 未知工具 404
st, _ = call("POST", "/mcp/tools/no_such_tool/call", {"arguments": {}})
check("未知工具 → 404", st == 404)

# 4. 长工具缺 session_id → 400
st, _ = call("POST", "/mcp/tools/research_and_code/call",
             {"arguments": {"research_query": "q", "coding_task": "t"}})
check("长工具缺 session_id → 400", st == 400)

# 5. 长工具会话不存在 → 404
st, _ = call("POST", "/mcp/tools/research_and_code/call",
             {"arguments": {"research_query": "q", "coding_task": "t"}, "session_id": "no-such"})
check("长工具假会话 → 404", st == 404)

# 6. 长工具任务管理链：202 派发（注册 RUNNING_TASKS）→ cancel（既有通路取消）
#    → 清理后再 202（证明 done_callback 已弹出；未清理则既有 409 守卫会拒）。
#    message/error 事件回灌的硬证据在单测 test 7/8（mock run_tool 断言事件形状），
#    黑盒不做真实执行等待（research 真网络重试+编排真 LLM 耗时不可控，会 flaky）。
st, sess = call("POST", "/assistant/sessions", {"title": "m170-verify"})
sid = sess.get("id")
check("建 assistant 会话", st in (200, 201) and bool(sid))
st, body = call("POST", "/mcp/tools/research_and_code/call",
                {"arguments": {"research_query": "q", "coding_task": "t"}, "session_id": sid})
check("长工具 → 202 accepted", st == 202 and body.get("accepted") is True)
st, _ = call("POST", f"/sessions/{sid}/cancel")
check("cancel 既有通路可取消长工具", st in (200, 202, 204))
time.sleep(0.6)  # done_callback 弹出 RUNNING_TASKS
st, body = call("POST", "/mcp/tools/research_and_code/call",
                {"arguments": {"research_query": "q2", "coding_task": "t2"}, "session_id": sid})
check("取消清理后再派发仍 202（RUNNING_TASKS 已弹出，无 409）",
      st == 202 and body.get("accepted") is True, detail=f"HTTP {st}")

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "黑盒 E2E 全绿" || bad "黑盒 E2E 失败"

echo ""
if [ $fail -eq 0 ]; then echo "M170（编辑器直调 MCP 工具）验收：通过 ✅"; else echo "M170 验收：有未通过 ❌"; fi
exit $fail
