#!/usr/bin/env bash
# M178 验收 — 后台任务系统（「已安排」落地，对标 ZCode 任务侧栏）。
#
#   1) pytest 单测：test_m178_tasks.py（纯函数/Registry/端点/dispatch 27 例）
#   2) 真实后端黑盒 E2E：真 uvicorn（FLIPPED_TASKS_SCAN_S=1 加速扫描，
#      FLIPPED_USE_LOCAL_WORKER=1 + 假 OpenAI server 回显，chat 模式不烧真 LLM），
#      tmp 隔离（FLIPPED_TASKS_PATH/FLIPPED_PROJECTS_DIR/FLIPPED_DB）：
#        a. POST /tasks（once，run_at=now+2s）→ 201 且 next_run_at 非空
#        b. 8s 内轮询：自动建会话（标题=任务标题）+ user 消息落库 + 假 LLM 回显到达
#        c. GET /tasks：last_status==done、enabled==false（once 跑完即停）、
#           run_count==1、last_session_id==新会话 id
#        d. POST /tasks（interval every_minutes=1）→ next_run_at 在未来且 ≤61s
#        e. toggle enabled=false → next_run_at==None；超过触发窗口 3s 后不新建会话
#        f. 校验 422：once 缺 run_at / interval every_minutes=0
#        g. DELETE 未知 id → 404
#
# 一键复跑: scripts/verify_m178.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8179}"
FAKE_PORT="${FLIPPED_FAKE_LLM_PORT:-8180}"
SRV_PID=""; FAKE_PID=""
cleanup() {
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
  [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null; wait "$FAKE_PID" 2>/dev/null
  rm -rf "$TMPD"
}
trap cleanup EXIT
export FLIPPED_PROJECTS_DIR="$TMPD/projects"
export FLIPPED_DB="$TMPD/flipped.db"
export FLIPPED_TASKS_PATH="$TMPD/scheduled_tasks.json"
export FLIPPED_SESSION_STORE_PATH="$TMPD/.sessions.json"

echo "== M178-1 单测（27 例） =="
PYTHONPATH=src $PY -m pytest tests/test_m178_tasks.py -q \
  && pass "M178 单测全绿" || bad "M178 单测失败"

echo "== M178-2 真实后端黑盒 E2E（uvicorn :${PORT} + 假 LLM :${FAKE_PORT}，scan=1s） =="

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

FLIPPED_USE_LOCAL_WORKER=1 \
FLIPPED_MODEL_BASE_URL="http://127.0.0.1:${FAKE_PORT}/v1" \
FLIPPED_CHAT_STREAM=0 FLIPPED_RAG_AUTO=0 FLIPPED_MAP_AUTO=0 \
FLIPPED_TASKS_SCAN_S=1 \
PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!

ready=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/api/v1/health" -o /dev/null 2>&1; then ready=1; break; fi
  sleep 0.5
done
if [ "${ready}" != "1" ]; then
  bad "后端 30s 内未就绪"
  echo ""; echo "M178 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" ${PY} - <<'PYEOF'
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

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

# 基线：当前会话数
st, sessions0 = call("GET", "/sessions")
check("GET /sessions 基线 200", st == 200, detail=f"HTTP {st}")
n0 = len(sessions0) if isinstance(sessions0, list) else 0

# a. once 任务，run_at = now+2s
run_at = (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()
st, task = call("POST", "/tasks", {
    "title": "m178-巡检锚点", "prompt": "M178_ANCHOR 定时触发了吗",
    "mode": "chat", "kind": "once", "run_at": run_at})
check("a. POST /tasks once → 201 且 id/next_run_at 非空",
      st == 201 and bool(task.get("id")) and bool(task.get("next_run_at")),
      detail=f"HTTP {st} {json.dumps(task)[:160]}")
tid = task.get("id", "")

# b. 8s 内轮询：自动建会话 + user 消息落库 + 假 LLM 回显
found_sid, echoed = None, False
t0 = time.time()
while time.time() - t0 < 12:
    st, sessions = call("GET", "/sessions")
    if st == 200 and isinstance(sessions, list):
        new = [s for s in sessions if s.get("title") == "m178-巡检锚点"]
        if new:
            found_sid = new[0]["id"]
            st2, hist = call("GET", f"/assistant/sessions/{found_sid}/history")
            if st2 == 200 and len(hist) >= 2:
                user_t = hist[0]
                asst_t = hist[-1]
                if user_t.get("text") == "M178_ANCHOR 定时触发了吗" and \
                   "M178_ANCHOR" in (asst_t.get("text") or ""):
                    echoed = True
                    break
    time.sleep(0.5)
check("b1. scheduler 自动建会话（标题=任务标题）", bool(found_sid))
check("b2. user 消息原文落库 + 假 LLM 回显到达（任务真实跑通）", echoed)

# c. GET /tasks 校验收尾状态
st, tasks = call("GET", "/tasks")
done_task = next((t for t in (tasks or []) if t.get("id") == tid), None)
check("c1. once 跑完 last_status==done", bool(done_task) and done_task.get("last_status") == "done",
      detail=json.dumps(done_task)[:200] if done_task else "task not found")
check("c2. once 跑完 enabled==false 且 next_run_at 为空",
      bool(done_task) and done_task.get("enabled") is False and done_task.get("next_run_at") is None)
check("c3. run_count==1 且 last_session_id 指向新会话",
      bool(done_task) and done_task.get("run_count") == 1
      and done_task.get("last_session_id") == found_sid)

# d. interval 任务：next_run 在未来且 ≤61s
st, task2 = call("POST", "/tasks", {
    "title": "m178-间隔任务", "prompt": "interval probe",
    "mode": "chat", "kind": "interval", "every_minutes": 1})
nr = task2.get("next_run_at")
ok_interval = False
if st == 201 and nr:
    delta = (datetime.fromisoformat(nr.replace("Z", "+00:00"))
             - datetime.now(timezone.utc)).total_seconds()
    ok_interval = 0 < delta <= 61
check("d. POST /tasks interval → next_run_at 在未来且 ≤61s", ok_interval,
      detail=f"HTTP {st} next_run_at={nr}")
tid2 = task2.get("id", "")

# e. toggle off → next_run_at None；等 3s 超窗口不新建会话
st, toggled = call("POST", f"/tasks/{tid2}/toggle?enabled=false")
check("e1. toggle off → enabled==false 且 next_run_at==None",
      st == 200 and toggled.get("enabled") is False and toggled.get("next_run_at") is None,
      detail=f"HTTP {st} {json.dumps(toggled)[:160]}")
st, sessions_pre = call("GET", "/sessions")
n_pre = len(sessions_pre) if isinstance(sessions_pre, list) else 0
time.sleep(3)
st, sessions_post = call("GET", "/sessions")
n_post = len(sessions_post) if isinstance(sessions_post, list) else 0
check("e2. toggle off 后 3s 内不新建会话（scheduler 尊重停用）", n_post == n_pre,
      detail=f"{n_pre} → {n_post}")

# f. 校验 422
st, _ = call("POST", "/tasks", {"title": "x", "prompt": "y", "kind": "once"})
check("f1. once 缺 run_at → 422", st == 422, detail=f"HTTP {st}")
st, _ = call("POST", "/tasks", {"title": "x", "prompt": "y", "kind": "interval", "every_minutes": 0})
check("f2. interval every_minutes=0 → 422", st == 422, detail=f"HTTP {st}")

# g. DELETE 未知 id → 404
st, _ = call("DELETE", "/tasks/task-deadbeef")
check("g. DELETE 未知 id → 404", st == 404, detail=f"HTTP {st}")

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "黑盒 E2E 全绿" || bad "黑盒 E2E 失败"

echo ""
if [ ${fail} -eq 0 ]; then echo "M178（后台任务系统）验收：通过 ✅"; else echo "M178 验收：有未通过 ❌"; fi
exit ${fail}
