#!/usr/bin/env bash
# M190 验收 — 编辑重跑可恢复（trash undo）+ auto 规则数据源扩展（多源汇聚 + LLM 兜底）。
#
#   1) pytest 单测：test_m190_edit_undo.py + test_m190_auto_rules.py
#   2) 真实后端黑盒 E2E（真 uvicorn + 假 OpenAI server，chat 通路保确定性）：
#        a) 编辑重跑 → undo → 200：重跑产物被丢弃、原事件按原 id 恢复、status 留痕
#        b) 编辑重跑后再发真实新消息 → undo → 409（new events appended）
#        c) 无截断会话 → undo → 404（no truncated events）
#        d) 显式 failure_texts 命中模板 → llm_used=false，added 为模板规则
#        e) 显式 failure_texts 无模板命中 → LLM 兜底 → llm_used=true，规则入库
#        f) 无 body：事件流 error 文本（先发 LLM500 触发 error 事件）经多源汇聚
#           → 模板未命中 → LLM 兜底 → llm_used=true（证明 error 事件源生效）
#
# 一键复跑: scripts/verify_m190.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8188}"
FAKE_PORT="${FLIPPED_FAKE_LLM_PORT:-8189}"
SRV_PID=""; FAKE_PID=""
cleanup() {
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
  [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null; wait "$FAKE_PID" 2>/dev/null
  rm -rf "$TMPD"
}
trap cleanup EXIT
export FLIPPED_PROJECTS_DIR="$TMPD/projects"
export FLIPPED_DB="$TMPD/flipped.db"
export FLIPPED_SESSION_STORE_PATH="$TMPD/sessions.json"
export FLIPPED_WORKER_RULES_PATH="$TMPD/worker_rules.json"

echo "== M190-1 单测（edit_undo + auto_rules） =="
PYTHONPATH=src $PY -m pytest tests/test_m190_edit_undo.py tests/test_m190_auto_rules.py -q \
  && pass "M190 单测全绿" || bad "M190 单测失败"

echo "== M190-2 真实后端黑盒 E2E（uvicorn :${PORT} + 假 LLM :${FAKE_PORT}） =="

# 假 OpenAI 兼容端点：
# - rules 兜底（含「你是软件工程导师」marker）→ 第 N 次返回 ["黑盒兜底规则N：先复现再修复"]
# - user 含 LLM500 → HTTP 500（制造事件流 error 事件，供场景 f 多源汇聚）
# - 其余 chat → 即时回显 RE:<user>
cat > "$TMPD/fake_llm.py" <<'FAKEEOF'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

rules_calls = {"n": 0}

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        msgs = body.get("messages", [])
        joined = "\n".join(str(m.get("content", "")) for m in msgs)
        user = ""
        for m in msgs:
            if m.get("role") == "user":
                user = m.get("content", "")
        if "你是软件工程导师" in joined:
            rules_calls["n"] += 1
            rule = f"黑盒兜底规则{rules_calls['n']}：先复现再修复"
            out = {"choices": [{"message": {"role": "assistant",
                                            "content": json.dumps([rule], ensure_ascii=False)}}],
                   "usage": {"prompt_tokens": 2, "completion_tokens": 1}}
        elif "LLM500" in user:
            data = json.dumps({"error": "boom"}, ensure_ascii=False).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        else:
            out = {"choices": [{"message": {"role": "assistant", "content": "RE:" + user[:200]}}],
                   "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
        data = json.dumps(out, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def log_message(self, *a):
        pass

HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
FAKEEOF
$PY "$TMPD/fake_llm.py" "${FAKE_PORT}" &
FAKE_PID=$!

FLIPPED_USE_LOCAL_WORKER=1 \
FLIPPED_MODEL_BASE_URL="http://127.0.0.1:${FAKE_PORT}/v1" \
FLIPPED_CHAT_STREAM=0 FLIPPED_RAG_AUTO=0 FLIPPED_MAP_AUTO=0 \
PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!
ready=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/api/v1/health" -o /dev/null 2>&1; then ready=1; break; fi
  sleep 0.5
done
if [ "${ready}" != "1" ]; then
  bad "后端 30s 内未就绪"
  echo ""; echo "M190 验收：有未通过 ❌"; exit 1
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

def events(sid):
    st, body = call("GET", f"/sessions/{sid}/events")
    return body if st == 200 else []

def wait_done(sid, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st, sess = call("GET", f"/sessions/{sid}")
        if st == 200 and sess.get("status") in ("done", "error"):
            return sess.get("status")
        time.sleep(0.4)
    return "timeout"

def first_user_msg_id(sid):
    for e in events(sid):
        if e.get("type") == "message" and e.get("agent") == "user":
            return e["id"]
    return ""

def texts(sid):
    return [str(e.get("payload", {}).get("text", "")) for e in events(sid)
            if e.get("type") == "message"]

# ============ 场景 a：编辑重跑 → undo 200 恢复 ============
st, body = call("POST", "/assistant/sessions", {"title": "m190-undo", "mode": "chat"})
sid = body.get("id", "")
check("a.建 chat 会话", st == 200 and sid, detail=f"HTTP {st}")

st, _ = call("POST", f"/assistant/sessions/{sid}/messages", {"text": "原始文本"})
check("a.发送原始消息 200", st == 200, detail=f"HTTP {st}")
check("a.首轮跑完", wait_done(sid) == "done")

uid = first_user_msg_id(sid)
st, body = call("POST", f"/assistant/sessions/{sid}/messages/{uid}/edit",
                {"text": "改后文本"})
truncated = body.get("truncated", 0)
check("a.编辑重跑 200 且 truncated>=2（user+应答）",
      st == 200 and truncated >= 2, detail=f"HTTP {st} truncated={truncated}")
check("a.重跑跑完", wait_done(sid) == "done")
check("a.重跑产物在场（edited 消息 + RE:改后文本）",
      "改后文本" in texts(sid) and any("RE:改后文本" in t for t in texts(sid)))

st, body = call("POST", f"/assistant/sessions/{sid}/edit/undo")
check("a.undo 200 且 restored == truncated",
      st == 200 and body.get("restored") == truncated,
      detail=f"HTTP {st} body={json.dumps(body, ensure_ascii=False)[:120]}")
ts = texts(sid)
check("a.撤销后原消息与原版应答回来、重跑产物被丢弃",
      "原始文本" in ts and any("RE:原始文本" in t for t in ts)
      and "改后文本" not in ts and not any("RE:改后文本" in t for t in ts),
      detail=f"texts={ts[:6]}")
edited_left = [e for e in events(sid) if e.get("payload", {}).get("edited")]
check("a.edited 标记事件已清零", not edited_left, detail=f"left={len(edited_left)}")
notes = [str(e.get("payload", {}).get("note", "")) for e in events(sid)
         if e.get("type") == "status"]
check("a.status 留痕「编辑重跑已撤销」",
      any("编辑重跑已撤销" in n for n in notes), detail=f"notes={notes[-3:]}")

# ============ 场景 b：编辑重跑后再发真实新消息 → undo 409 ============
uid2 = first_user_msg_id(sid)
st, body = call("POST", f"/assistant/sessions/{sid}/messages/{uid2}/edit",
                {"text": "二次改后"})
check("b.二次编辑重跑 200", st == 200, detail=f"HTTP {st}")
check("b.二次重跑跑完", wait_done(sid) == "done")
st, _ = call("POST", f"/assistant/sessions/{sid}/messages", {"text": "全新输入"})
check("b.真实新消息 200", st == 200, detail=f"HTTP {st}")
check("b.新消息跑完", wait_done(sid) == "done")
st, body = call("POST", f"/assistant/sessions/{sid}/edit/undo")
check("b.undo → 409 new events appended（真实新 user 消息护住）",
      st == 409 and "new events appended" in str(body.get("detail", "")),
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")

# ============ 场景 c：无截断会话 → undo 404 ============
st, body = call("POST", "/assistant/sessions", {"title": "m190-no-trash", "mode": "chat"})
sid_c = body.get("id", "")
st, body = call("POST", f"/assistant/sessions/{sid_c}/edit/undo")
check("c.空 trash → 404 no truncated events",
      st == 404 and "no truncated events" in str(body.get("detail", "")),
      detail=f"HTTP {st}")

# ============ 场景 d：模板命中 → llm_used=false ============
st, body = call("POST", "/worker/rules/auto-generate",
                {"failure_texts": ["构建 timeout 超时了"]})
added = [a.get("text", "") for a in body.get("added", [])]
check("d.模板命中 → added 含模板规则且 llm_used=false",
      st == 200 and body.get("llm_used") is False
      and any("300 行" in t for t in added),
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:160]}")

# ============ 场景 e：模板未命中 → LLM 兜底 → llm_used=true ============
st, body = call("POST", "/worker/rules/auto-generate",
                {"failure_texts": ["诡异的闪退无任何日志输出"]})
added = [a.get("text", "") for a in body.get("added", [])]
check("e.LLM 兜底 → llm_used=true 且 added 含「黑盒兜底规则1」",
      st == 200 and body.get("llm_used") is True
      and any("黑盒兜底规则1" in t for t in added),
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:160]}")

# ============ 场景 f：无 body → 事件流 error 源 → LLM 兜底 ============
st, body = call("POST", "/assistant/sessions", {"title": "m190-err-src", "mode": "chat"})
sid_f = body.get("id", "")
st, _ = call("POST", f"/assistant/sessions/{sid_f}/messages", {"text": "LLM500 触发错误"})
check("f.触发假 LLM 500 的消息 200", st == 200, detail=f"HTTP {st}")
check("f.任务以 error 收尾", wait_done(sid_f) == "error")
err_evs = [e for e in events(sid_f) if e.get("type") == "error"]
check("f.error 事件已落事件流", len(err_evs) >= 1, detail=f"error evs={len(err_evs)}")

st, body = call("POST", "/worker/rules/auto-generate")
added = [a.get("text", "") for a in body.get("added", [])]
check("f.无 body 多源汇聚 → LLM 兜底 llm_used=true 且含「黑盒兜底规则2」",
      st == 200 and body.get("llm_used") is True
      and any("黑盒兜底规则2" in t for t in added),
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:160]}")

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "黑盒场景 a-f 全绿" || bad "黑盒场景有失败"

echo ""
if [ ${fail} -eq 0 ]; then echo "M190 验收：全部通过 ✅"; else echo "M190 验收：有未通过 ❌"; exit 1; fi
