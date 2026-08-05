#!/usr/bin/env bash
# M188 验收 — Goal 系统增强（verify_cmd 确定性校验 + 断点续跑）。
#
#   1) pytest 单测：test_m188_goal_verify.py（23 例）+ test_m188_goal_resume.py（15 例）
#   2) 真实后端黑盒 E2E（真 uvicorn + 假 OpenAI server，chat 通路保确定性）：
#        a) 显式 verify_cmd exit 0 → 1 轮即 achieved，judge source=verify_cmd，
#           假 LLM judge 计数 = 0（LLM judge 未被调用）
#        b) 显式 verify_cmd exit 1（带输出 TAILMARK）+ max_iter=2 → exhausted
#           reason=max_iter，judge gap 含命令输出尾部，source=verify_cmd
#        c) 断点续跑：第 2 轮 dispatch 中 kill -9 → 同 store 重启 → 无任何新 POST，
#           goal 自行从第 2 轮重跑至 achieved；续跑中 POST goal → 409（防重入）；
#           终态后 GET /goal status=achieved iteration=2
#
# 一键复跑: scripts/verify_m188.sh
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

echo "== M188-1 单测（verify 23 例 + resume 15 例） =="
PYTHONPATH=src $PY -m pytest tests/test_m188_goal_verify.py tests/test_m188_goal_resume.py -q \
  && pass "M188 单测全绿" || bad "M188 单测失败"

echo "== M188-2 真实后端黑盒 E2E（uvicorn :${PORT} + 假 LLM :${FAKE_PORT}） =="

# 假 OpenAI 兼容端点：
# - judge 请求（含 GOAL_JUDGE_V1 marker）→ 追加一行到 ${JUDGE_LOG}（LLM judge 计数凭据）：
#     第 1 次 {"achieved": false, "gap": "还差甲"}；第 ≥2 次 {"achieved": true, "gap": ""}
# - 普通 chat：user 含「第 2/」（续跑轮标记）→ 第 1 次 sleep 30（kill 窗口），
#     第 2 次起 sleep 2（重启后 409 窗口）；其余即时回显 RE:<user>
cat > "$TMPD/fake_llm.py" <<'FAKEEOF'
import json, os, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer

judge_calls = {"n": 0}
slow2_calls = {"n": 0}
JUDGE_LOG = os.environ.get("JUDGE_LOG", "/dev/null")

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
        if "GOAL_JUDGE_V1" in joined:
            judge_calls["n"] += 1
            with open(JUDGE_LOG, "a") as f:
                f.write(f"judge{judge_calls['n']}\n")
            verdict = {"achieved": False, "gap": "还差甲"} if judge_calls["n"] == 1 \
                else {"achieved": True, "gap": ""}
            out = {"choices": [{"message": {"role": "assistant",
                                            "content": json.dumps(verdict, ensure_ascii=False)}}],
                   "usage": {"prompt_tokens": 2, "completion_tokens": 1}}
        else:
            if "第 2/" in user:
                slow2_calls["n"] += 1
                time.sleep(30 if slow2_calls["n"] == 1 else 2)
            out = {"choices": [{"message": {"role": "assistant", "content": "RE:" + user[:200]}}],
                   "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
        data = json.dumps(out, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # 对端（uvicorn）可能已被 kill -9
    def log_message(self, *a):
        pass

HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
FAKEEOF
JUDGE_LOG="$TMPD/judge.log" $PY "$TMPD/fake_llm.py" "${FAKE_PORT}" &
FAKE_PID=$!

start_backend() {
  FLIPPED_USE_LOCAL_WORKER=1 \
  FLIPPED_MODEL_BASE_URL="http://127.0.0.1:${FAKE_PORT}/v1" \
  FLIPPED_CHAT_STREAM=0 FLIPPED_RAG_AUTO=0 FLIPPED_MAP_AUTO=0 \
  PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
  SRV_PID=$!
  local ready=0
  for _ in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:${PORT}/api/v1/health" -o /dev/null 2>&1; then ready=1; break; fi
    sleep 0.5
  done
  [ "${ready}" = "1" ]
}

if ! start_backend; then
  bad "后端 30s 内未就绪"
  echo ""; echo "M188 验收：有未通过 ❌"; exit 1
fi

# ---------- 场景 a/b：verify_cmd 确定性校验 ----------
FLIPPED_BASE="http://127.0.0.1:${PORT}" TMPD="$TMPD" ${PY} - <<'PYEOF'
import json, os, sys, time, urllib.request, urllib.error

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
TMPD = os.environ["TMPD"]
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

def goal_events(sid):
    return [e for e in events(sid) if e.get("type") == "goal"]

def phases(sid):
    return [e["payload"].get("phase") for e in goal_events(sid)]

def wait_phase(sid, want, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        ph = phases(sid)
        if want in ph:
            return ph
        time.sleep(0.4)
    return phases(sid)

# ============ 场景 a：verify_cmd exit 0 → 1 轮确定性达成 ============
st, body = call("POST", "/assistant/sessions", {"title": "m188-verify-ok", "mode": "chat"})
sid_a = body.get("id", "")
check("a.建 chat 会话", st == 200 and sid_a, detail=f"HTTP {st}")

st, body = call("POST", f"/assistant/sessions/{sid_a}/goal",
                {"objective": "确定性验收", "verify_cmd": ["bash", "-c", "exit 0"]})
check("a.POST goal 200", st == 200, detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")

ph = wait_phase(sid_a, "achieved", timeout=30)
check("a.相位序列 set→iter→judge→achieved（1 轮即达）",
      ph == ["set", "iter", "judge", "achieved"], detail=f"phases={ph}")
judges = [e["payload"] for e in goal_events(sid_a) if e["payload"].get("phase") == "judge"]
check("a.judge achieved=True source=verify_cmd",
      len(judges) == 1 and judges[0].get("achieved") is True
      and judges[0].get("source") == "verify_cmd",
      detail=json.dumps(judges[0], ensure_ascii=False)[:120] if judges else "none")
judge_log = os.path.join(TMPD, "judge.log")
n_llm_judge = sum(1 for _ in open(judge_log)) if os.path.exists(judge_log) else 0
check("a.假 LLM judge 计数 = 0（LLM judge 未被调用）", n_llm_judge == 0,
      detail=f"judge_log={n_llm_judge} 行")
st, sess = call("GET", f"/sessions/{sid_a}")
check("a.verify_cmd 已落盘到会话",
      st == 200 and sess.get("verify_cmd") == ["bash", "-c", "exit 0"],
      detail=f"HTTP {st} verify_cmd={sess.get('verify_cmd')}")

# ============ 场景 b：verify_cmd exit 1 + max_iter=2 → exhausted max_iter ============
st, body = call("POST", "/assistant/sessions", {"title": "m188-verify-fail", "mode": "chat"})
sid_b = body.get("id", "")
st, body = call("POST", f"/assistant/sessions/{sid_b}/goal",
                {"objective": "恒失败验收", "max_iterations": 2,
                 "verify_cmd": ["bash", "-c", "echo TAILMARK_m188; exit 1"]})
check("b.POST goal 200", st == 200, detail=f"HTTP {st}")
ph_b = wait_phase(sid_b, "exhausted", timeout=30)
check("b.相位序列 set→iter→judge→iter→exhausted（末轮不 judge）",
      ph_b == ["set", "iter", "judge", "iter", "exhausted"], detail=f"phases={ph_b}")
judges_b = [e["payload"] for e in goal_events(sid_b) if e["payload"].get("phase") == "judge"]
check("b.judge source=verify_cmd 且 gap 含输出尾部 TAILMARK_m188",
      len(judges_b) == 1 and judges_b[0].get("source") == "verify_cmd"
      and "TAILMARK_m188" in (judges_b[0].get("gap") or ""),
      detail=json.dumps(judges_b[0], ensure_ascii=False)[:140] if judges_b else "none")
exh = [e["payload"] for e in goal_events(sid_b) if e["payload"].get("phase") == "exhausted"]
check("b.exhausted reason=max_iter", exh and exh[0].get("reason") == "max_iter",
      detail=json.dumps(exh[0], ensure_ascii=False)[:100] if exh else "none")

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "场景 a/b（verify_cmd 确定性校验）全绿" || bad "场景 a/b 失败"

# ---------- 场景 c：断点续跑（kill -9 → 同 store 重启自行续跑） ----------
FLIPPED_BASE="http://127.0.0.1:${PORT}" ${PY} - <<'PYEOF'
import json, os, sys, time, urllib.request, urllib.error

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"

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
    except Exception:
        return -1, {}

def goal_events(sid):
    st, body = call("GET", f"/sessions/{sid}/events")
    if st != 200:
        return []
    return [e for e in body if e.get("type") == "goal"]

# 建 goal：第 1 轮 chat 即时回 → judge#1 false（还差甲）→ 第 2 轮 chat sleep 30
st, body = call("POST", "/assistant/sessions", {"title": "m188-resume", "mode": "chat"})
sid = body.get("id", "")
if st != 200 or not sid:
    print(f"  ❌ c.建会话失败 HTTP {st}"); sys.exit(1)
st, body = call("POST", f"/assistant/sessions/{sid}/goal",
                {"objective": "断点续跑目标", "max_iterations": 5})
if st != 200:
    print(f"  ❌ c.POST goal 失败 HTTP {st}"); sys.exit(1)
print(f"  · 会话 {sid}：等第 2 轮 iter 出现（dispatch 中 kill 窗口）")
t0 = time.time()
iters = []
while time.time() - t0 < 30:
    iters = [e["payload"] for e in goal_events(sid) if e["payload"].get("phase") == "iter"]
    if len(iters) >= 2:
        break
    time.sleep(0.3)
if len(iters) < 2:
    print(f"  ❌ c.30s 内未进入第 2 轮: iters={len(iters)}"); sys.exit(1)
print(f"  · 第 2 轮 dispatch 中（假 LLM sleep 30s），可 kill")
print(f"SID_FILE_MARKER:{sid}")
PYEOF
[ $? -eq 0 ] || bad "场景 c 前置（进入第 2 轮）失败"

# kill -9 后端（模拟进程崩溃），随后同 store 重启
kill -9 "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
SRV_PID=""
sleep 0.5
if ! start_backend; then
  bad "重启后端 30s 内未就绪"
else
FLIPPED_BASE="http://127.0.0.1:${PORT}" ${PY} - <<'PYEOF'
import json, os, re, sys, time, urllib.request, urllib.error

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
    except Exception:
        return -1, {}

def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" ({detail})" if detail and not cond else ""))
    if not cond:
        fails.append(name)

def events(sid):
    st, body = call("GET", f"/sessions/{sid}/events")
    return body if st == 200 else []

def goal_events(sid):
    return [e for e in events(sid) if e.get("type") == "goal"]

# 从 store 文件找到 running goal 会话（本脚本只建过一个未终态 goal）
st, sessions = call("GET", "/sessions")
sid = ""
if st == 200:
    for s in sessions if isinstance(sessions, list) else sessions.get("sessions", []):
        if s.get("title") == "m188-resume":
            sid = s.get("id", "")
check("c.重启后同 store 找回会话", bool(sid), detail=f"HTTP {st}")
if not sid:
    sys.exit(1)

# 等续跑出现第 3 个 iter 事件（set,iter1,judge1,iter2(死前),iter2(重跑)）
t0 = time.time()
re_itered = False
while time.time() - t0 < 20:
    iters = [e["payload"] for e in goal_events(sid) if e["payload"].get("phase") == "iter"]
    if len(iters) >= 3:
        re_itered = True
        break
    time.sleep(0.3)
check("c.重启后无任何新 POST，goal 自行从第 2 轮重跑（iter 重出现）", re_itered,
      detail=f"iters={len(iters)}")

# 续跑中（假 LLM sleep 2s 窗口内）POST goal → 409
st, body = call("POST", f"/assistant/sessions/{sid}/goal", {"objective": "重入"})
check("c.续跑中 POST goal → 409 防重入", st == 409, detail=f"HTTP {st}")

# 等 achieved（第 2 轮重跑完成 → judge#2 true）
t0 = time.time()
done = False
while time.time() - t0 < 30:
    ph = [e["payload"].get("phase") for e in goal_events(sid)]
    if "achieved" in ph:
        done = True
        break
    time.sleep(0.4)
check("c.续跑推进到 achieved 终态", done, detail=f"phases={ph}")

st, body = call("GET", f"/assistant/sessions/{sid}/goal")
check("c.GET /goal status=achieved iteration=2",
      st == 200 and body.get("status") == "achieved" and body.get("iteration") == 2,
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")

# 断点续跑 status 事件留痕
status_evs = [e for e in events(sid) if e.get("type") == "status"]
check("c.有「断点续跑」status 事件",
      any("断点续跑" in json.dumps(e.get("payload") or {}, ensure_ascii=False) for e in status_evs),
      detail=f"status evs={len(status_evs)}")

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "场景 c（断点续跑）全绿" || bad "场景 c 失败"
fi

echo ""
if [ ${fail} -eq 0 ]; then echo "M188（Goal 系统增强）验收：通过 ✅"; else echo "M188 验收：有未通过 ❌"; fi
exit ${fail}
