#!/usr/bin/env bash
# M194 验收 — P2 功能缺口批消化（goal @ 展开 / 规则预算 env 化 / history cap env 化）。
#
#   1) pytest 单测：tests/test_m194_goal_refs.py（goal @ 展开/refs 元数据/开关关闭/
#      resume 重建）+ tests/test_m194_rules_env.py（注入预算 env/显式优先/非法回落/
#      chat 独立 env/history cap env+clamp）
#   2) 真实后端黑盒 E2E（真 uvicorn + 假 OpenAI server，chat 通路保确定性）：
#        a) goal 带 @ 文件 → 200：响应 objective=原文；用户消息事件 refs 元数据正确；
#           goal set 事件 objective 含文件内容（展开生效）；judge 达成收尾
#        b) FLIPPED_WORKER_RULES_MAX_CHARS=40 起后端 → chat 注入预算生效：
#           假 LLM 捕获 system 含短规则 + 「略1条」截断注记、不含长规则
#           （默认 300 时长规则可装下，注记出现即证明 env 生效）；
#           应答 payload.worker_rules_injected=True
#        c) 回归：M175 普通消息 @ 展开不受影响（refs + LLM 收到展开文本）；
#           M193 POST /project/revert-hunk 端点 200 action=hunk_reverted
#
# 一键复跑: bash scripts/verify_m194.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8196}"
FAKE_PORT="${FLIPPED_FAKE_LLM_PORT:-8197}"
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
export FLIPPED_TASKS_PATH="$TMPD/scheduled_tasks.json"
export FLIPPED_WORKER_RULES_PATH="$TMPD/worker_rules.json"
export FLIPPED_DATA_DIR="$TMPD/data"

echo "== M194-1 单测（goal_refs + rules_env） =="
PYTHONPATH=src $PY -m pytest tests/test_m194_goal_refs.py tests/test_m194_rules_env.py -q \
  && pass "M194 单测全绿" || bad "M194 单测失败"

echo "== M194-2 真实后端黑盒 E2E（uvicorn :${PORT} + 假 LLM :${FAKE_PORT}） =="

# a/c 前置：git 项目，readme.md 带唯一标记（@ 展开断言），file.txt 30 行（hunk 回归）
PROJ="$FLIPPED_PROJECTS_DIR/proj194"
mkdir -p "$PROJ"
PROJ="$(cd "$PROJ" && pwd -P)"  # /var → /private/var 符号链接归一
echo "M194GoalMarker194 目标文件内容" > "$PROJ/readme.md"
for i in $(seq 1 30); do printf 'line-%02d\n' "$i"; done > "$PROJ/file.txt"
git -C "$PROJ" init -q
git -C "$PROJ" config user.email "m194@example.com"
git -C "$PROJ" config user.name "m194"
git -C "$PROJ" add . && git -C "$PROJ" commit -qm init

# 假 OpenAI 兼容端点（每次请求捕获 {system,user} → JSONL 落盘供断言）：
# - system 含 GOAL_JUDGE_V1 → 返回 {"achieved": true}（goal 一轮达成收尾）
# - 其余 chat → 即时回显 RE:<user>
cat > "$TMPD/fake_llm.py" <<'FAKEEOF'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

capture_path = sys.argv[2]

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        msgs = body.get("messages", [])
        system = ""
        user = ""
        for m in msgs:
            c = m.get("content", "")
            if not isinstance(c, str):
                c = json.dumps(c, ensure_ascii=False)
            if m.get("role") == "system":
                system += c + "\n"
            elif m.get("role") == "user":
                user = c
        with open(capture_path, "a") as f:
            f.write(json.dumps({"system": system, "user": user}, ensure_ascii=False) + "\n")
        if "GOAL_JUDGE_V1" in system:
            out = {"choices": [{"message": {"role": "assistant",
                                            "content": '{"achieved": true, "gap": ""}'}}],
                   "usage": {"prompt_tokens": 2, "completion_tokens": 1}}
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
$PY "$TMPD/fake_llm.py" "${FAKE_PORT}" "$TMPD/capture.jsonl" &
FAKE_PID=$!

FLIPPED_USE_LOCAL_WORKER=1 \
FLIPPED_MODEL_BASE_URL="http://127.0.0.1:${FAKE_PORT}/v1" \
FLIPPED_CHAT_STREAM=0 FLIPPED_RAG_AUTO=0 FLIPPED_MAP_AUTO=0 FLIPPED_RULES_AUTO=0 \
FLIPPED_WORKER_RULES_MAX_CHARS=40 \
PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!
ready=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/api/v1/health" -o /dev/null 2>&1; then ready=1; break; fi
  sleep 0.5
done
if [ "${ready}" != "1" ]; then
  bad "后端 30s 内未就绪"
  echo ""; echo "M194 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" \
FLIPPED_PROJ="$PROJ" \
FLIPPED_CAPTURE="$TMPD/capture.jsonl" \
${PY} - <<'PYEOF'
import json, os, sys, time, urllib.request, urllib.error

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
PROJ = os.environ["FLIPPED_PROJ"]
CAPTURE = os.environ["FLIPPED_CAPTURE"]
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
        data = e.read()
        try:
            return e.code, json.loads(data or b"{}")
        except json.JSONDecodeError:
            return e.code, {"raw": data[:200].decode("utf-8", "replace")}

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

def captures():
    """假 LLM 捕获的 {system,user} 清单（judge 调用除外）。"""
    if not os.path.exists(CAPTURE):
        return []
    out = []
    with open(CAPTURE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            if "GOAL_JUDGE_V1" not in c.get("system", ""):
                out.append(c)
    return out

# ============ 场景 a：goal 带 @ 文件 → 展开 + refs 元数据 ============
st, body = call("POST", "/project/open", {"path": PROJ})
check("a.POST /project/open 设为活动项目", st == 200,
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")

st, body = call("POST", "/assistant/sessions", {"title": "m194-goal", "mode": "chat"})
sid_a = body.get("id", "")
check("a.建 chat 会话", st == 200 and sid_a, detail=f"HTTP {st}")

OBJECTIVE = "请阅读 @readme.md 并总结"
st, body = call("POST", f"/assistant/sessions/{sid_a}/goal",
                {"objective": OBJECTIVE, "max_iterations": 3})
check("a.POST goal 200 且响应 objective 保持原文",
      st == 200 and body.get("objective") == OBJECTIVE,
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:160]}")

evs = events(sid_a)
user_evs = [e for e in evs if e.get("type") == "message" and e.get("agent") == "user"]
goal_set = [e for e in evs if e.get("type") == "goal"
            and e.get("payload", {}).get("phase") == "set"]
u = user_evs[-1].get("payload", {}) if user_evs else {}
check("a.用户消息事件 text=原文 且 goal.started 标记在",
      u.get("text") == OBJECTIVE and u.get("goal", {}).get("started") is True,
      detail=json.dumps(u, ensure_ascii=False)[:160])
refs = u.get("refs") or []
check("a.用户消息事件 refs 元数据正确（path=readme.md）",
      len(refs) == 1 and refs[0].get("path") == "readme.md",
      detail=json.dumps(refs, ensure_ascii=False)[:160])
check("a.goal set 事件 objective 含文件内容（展开生效）",
      len(goal_set) == 1
      and "M194GoalMarker194" in goal_set[0].get("payload", {}).get("objective", ""),
      detail=json.dumps(goal_set[0].get("payload", {}), ensure_ascii=False)[:160] if goal_set else "no set")

check("a.goal 跑完（假 judge 一轮达成）", wait_done(sid_a) == "done")
ga = [e for e in events(sid_a) if e.get("type") == "goal"
      and e.get("payload", {}).get("phase") == "achieved"]
check("a.goal achieved 终态事件落盘", len(ga) == 1)

# ============ 场景 b：FLIPPED_WORKER_RULES_MAX_CHARS=40 → 注入预算生效 ============
st, _ = call("POST", "/worker/rules",
             {"text": "先复现再修复", "scope": "all", "priority": 50})
check("b.建短规则（scope=all）201", st == 201, detail=f"HTTP {st}")
st, _ = call("POST", "/worker/rules",
             {"text": "B" * 50, "scope": "all", "priority": 10})
check("b.建长规则（52 字符行，预算 40 装不下）201", st == 201, detail=f"HTTP {st}")

st, body = call("POST", "/assistant/sessions", {"title": "m194-budget", "mode": "chat"})
sid_b = body.get("id", "")
st, _ = call("POST", f"/assistant/sessions/{sid_b}/messages", {"text": "预算探针"})
check("b.发送探针消息 200", st == 200, detail=f"HTTP {st}")
check("b.探针消息跑完", wait_done(sid_b) == "done")

caps = [c for c in captures() if "预算探针" in c.get("user", "")]
sysp = caps[-1]["system"] if caps else ""
check("b.假 LLM 收到注入头「以下是全局工作规则」",
      "以下是全局工作规则" in sysp, detail=sysp[:120])
check("b.system 含短规则「先复现再修复」", "先复现再修复" in sysp)
check("b.system 不含 50B 长规则（被预算丢弃）", "B" * 50 not in sysp)
check("b.system 含截断注记「略1条」（默认 300 不出现，env 生效铁证）",
      "略1条" in sysp, detail=sysp[-120:])
wr_flag = [e for e in events(sid_b) if e.get("type") == "message"
           and e.get("payload", {}).get("worker_rules_injected")]
check("b.应答 payload.worker_rules_injected=True", len(wr_flag) == 1)

# ============ 场景 c1：M175 普通消息 @ 展开回归 ============
st, body = call("POST", "/assistant/sessions", {"title": "m194-m175", "mode": "chat"})
sid_c = body.get("id", "")
st, _ = call("POST", f"/assistant/sessions/{sid_c}/messages", {"text": "总结 @readme.md"})
check("c1.普通 @ 消息 200", st == 200, detail=f"HTTP {st}")
check("c1.消息跑完", wait_done(sid_c) == "done")
evs_c = events(sid_c)
u_c = [e.get("payload", {}) for e in evs_c
       if e.get("type") == "message" and e.get("agent") == "user"]
refs_c = u_c[-1].get("refs") if u_c else None
check("c1.用户消息 refs 元数据在（M175 行为不变）",
      bool(refs_c) and refs_c[0].get("path") == "readme.md",
      detail=json.dumps(refs_c, ensure_ascii=False)[:120] if refs_c else "no refs")
caps_c = [c for c in captures() if "总结" in c.get("user", "")]
check("c1.LLM 收到展开文本（含 M194GoalMarker194）",
      bool(caps_c) and "M194GoalMarker194" in caps_c[-1].get("user", ""))

# ============ 场景 c2：M193 revert-hunk 端点回归 ============
with open(os.path.join(PROJ, "file.txt")) as f:
    lines = f.read().splitlines()
lines[2] = "line-03-modified"
with open(os.path.join(PROJ, "file.txt"), "w") as f:
    f.write("\n".join(lines) + "\n")
st, body = call("POST", "/project/revert-hunk", {"path": "file.txt", "hunk_index": 0})
check("c2.POST /project/revert-hunk → 200 action=hunk_reverted",
      st == 200 and body.get("action") == "hunk_reverted",
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:160]}")
with open(os.path.join(PROJ, "file.txt")) as f:
    cur = f.read().splitlines()
check("c2.文件已回 HEAD", cur[2] == "line-03", detail=cur[2])

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "黑盒场景 a-c 全绿" || bad "黑盒场景有失败"

echo ""
if [ ${fail} -eq 0 ]; then echo "M194 验收：全部通过 ✅"; else echo "M194 验收：有未通过 ❌"; exit 1; fi
