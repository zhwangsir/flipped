#!/usr/bin/env bash
# M174 验收 — 消息级编辑重跑（edit & rerun，对标 ZCode 编辑历史对话 / opencode revert）。
#
#   1) pytest 单测：test_m174_truncate.py（A 截断原语 7 例）+
#      test_m174_edit_rerun.py（B 端点+turns event_id 12 例）
#   2) 真实后端黑盒 E2E：假 OpenAI server（http.server 回显 RE:<user>，非流式）+
#      真 uvicorn（FLIPPED_USE_LOCAL_WORKER=1 直连假端点，RAG/地图注入关闭保确定性），
#      chat 会话发 3 条消息 → 编辑第 2 条 → 断言截断 4 事件 + 重跑新回复 +
#      旧第 3 条消息/回复从对话中消失。
#      （agent 模式 git restore 证据在单测 mock 层，黑盒不碰真实 git；
#        前端编辑 UX 证据在 vitest Assistant.test.tsx）
#
# 一键复跑: scripts/verify_m174.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8174}"
FAKE_PORT="${FLIPPED_FAKE_LLM_PORT:-8175}"
SRV_PID=""; FAKE_PID=""
cleanup() {
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
  [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null; wait "$FAKE_PID" 2>/dev/null
  rm -rf "$TMPD"
}
trap cleanup EXIT
export FLIPPED_PROJECTS_DIR="$TMPD/projects"
export FLIPPED_DB="$TMPD/flipped.db"

echo "== M174-1 截断原语 + 编辑重跑端点单测（19 例） =="
PYTHONPATH=src $PY -m pytest tests/test_m174_truncate.py tests/test_m174_edit_rerun.py -q \
  && pass "M174 单测全绿" || bad "M174 单测失败"

echo "== M174-2 真实后端黑盒 E2E（uvicorn :${PORT} + 假 LLM :${FAKE_PORT}） =="

# 假 OpenAI 兼容端点：POST /v1/chat/completions → 固定回显 "RE:<user 文本>"
cat > "$TMPD/fake_llm.py" <<'FAKEEOF'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        user = ""
        for m in body.get("messages", []):
            if m.get("role") == "user":
                user = m.get("content", "")
        out = {"choices": [{"message": {"role": "assistant", "content": "RE:" + user}}],
               "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
        data = json.dumps(out).encode()
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

# 真后端：直连假 LLM（跳过 LiteLLM/exo 健康检查），非流式，RAG/地图注入关闭
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
  echo ""; echo "M174 验收：有未通过 ❌"; exit 1
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

def history(sid):
    st, body = call("GET", f"/assistant/sessions/{sid}/history")
    return body if st == 200 else []

def wait_turns(sid, n, timeout=20):
    """等 history 长到 n 个 turn（假 LLM 秒回，正常 < 2s）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = history(sid)
        if len(h) >= n:
            return h
        time.sleep(0.3)
    return history(sid)

# 1. 建 chat 会话
st, body = call("POST", "/assistant/sessions", {"title": "m174-e2e", "mode": "chat"})
sid = body.get("id", "")
check("POST /assistant/sessions 建 chat 会话", st == 200 and sid, detail=f"HTTP {st}")

# 2. 顺序发 3 条消息，各自等回（并发守卫：上条未完下条 409）
ok_all = True
for i in (1, 2, 3):
    st, body = call("POST", f"/assistant/sessions/{sid}/messages", {"text": f"msg-{i}", "mode": "chat"})
    if st != 200:
        ok_all = False
        break
    h = wait_turns(sid, i * 2)
    if len(h) < i * 2 or (h[i*2-1].get("text") or "") != f"RE:msg-{i}":
        ok_all = False
        break
check("3 条消息均获假 LLM 回显（RE:msg-N）", ok_all)

h = wait_turns(sid, 6)
check("history 6 turns（3 user + 3 assistant）", len(h) == 6, detail=f"len={len(h)}")
users = [t for t in h if t.get("role") == "user"]
check("user turns 均带 event_id（编辑锚点）",
      len(users) == 3 and all(t.get("event_id") for t in users))

# 3. 编辑第 2 条 user 消息 → 截断重跑
# 期望 truncated 精确推导：抓原始事件流（含 status/usage 等非 turn 事件），
# 目标事件 idx 起全删 → expected = len(events) - idx（自校准，不靠硬编码事件数）
eid = users[1].get("event_id") if len(users) == 3 else None
st, raw_events = call("GET", f"/sessions/{sid}/events")
expected_trunc = -1
if st == 200:
    idx = next((i for i, e in enumerate(raw_events) if e.get("id") == eid), None)
    if idx is not None:
        expected_trunc = len(raw_events) - idx
st, body = call("POST", f"/assistant/sessions/{sid}/messages/{eid}/edit",
                {"text": "msg-2-edited"})
check(f"edit 200 + truncated 精确等于事件流推导值（{expected_trunc}）",
      st == 200 and expected_trunc >= 4 and body.get("truncated") == expected_trunc,
      detail=f"HTTP {st} {json.dumps(body)[:140]}")
check("chat 模式 restored==False（不碰 git）", body.get("restored") is False)

# 4. 等重跑完成 → 历史收敛为 4 turns，旧第 3 条消失
h2 = wait_turns(sid, 4)
# 重跑完成标志：末尾出现 RE:msg-2-edited
t0 = time.time()
while time.time() - t0 < 20 and (not h2 or (h2[-1].get("text") or "") != "RE:msg-2-edited"):
    time.sleep(0.3)
    h2 = history(sid)
texts = [t.get("text") or "" for t in h2]
check("重跑后 4 turns（user1/asst1/编辑后 user2/新 asst2）", len(h2) == 4,
      detail=f"len={len(h2)} texts={texts}")
check("编辑后消息文本生效", "msg-2-edited" in texts)
check("新回复来自重跑（RE:msg-2-edited）", "RE:msg-2-edited" in texts)
check("旧第 2/3 条及回复已消失（msg-2/msg-3/RE:msg-3 不在）",
      "msg-3" not in texts and "RE:msg-3" not in texts and "RE:msg-2" not in texts)
check("第 1 轮对话完好保留", texts[:2] == ["msg-1", "RE:msg-1"])

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "黑盒 E2E 全绿" || bad "黑盒 E2E 失败"

echo ""
if [ ${fail} -eq 0 ]; then echo "M174（消息级编辑重跑）验收：通过 ✅"; else echo "M174 验收：有未通过 ❌"; fi
exit ${fail}
