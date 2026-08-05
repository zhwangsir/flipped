#!/usr/bin/env bash
# M191 验收 — Goal 审批暂停续跑 + judge 熔断结构化 + cron 全语法 + stale watchdog。
#
#   1) pytest 单测：test_m191_judge_error_field.py + test_m191_goal_pause_resume.py
#      + test_m191_cron_names.py + test_m191_watchdog.py
#   2) 真实后端黑盒 E2E（真 uvicorn + 假 OpenAI server）：
#        a) cron 全语法：@daily → 201 且 next_run_at=次日 00:00；0 9 * * MON-FRI → 201；
#           @biweekly → 422；0 9 * * FUNDAY → 422（非法宏/未知名均被 validate_cron 拦）
#        b) goal chat 模式假 LLM judge 连续废文 → judge 事件 error=true、gap="judge 失败"；
#           连续 2 次 → exhausted reason=judge_errors（结构化 error 字段生效）
#        c) goal agent 模式真 orchestrator + 假 LLM（supervisor/overseer 走纯文本 JSON）：
#           高危子任务 git push → approval_request + goal paused + wrapper 停派（仅 1 轮 iter）；
#           approve → 该轮 resume 跑完 → 续跑钩子 judge_first 直判 → achieved 全链
#        d) watchdog 黑盒不可达（同进程协程，外部无法造 stale）→ 单测覆盖，此处仅注明
#
# 一键复跑: scripts/verify_m191.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8191}"
FAKE_PORT="${FLIPPED_FAKE_LLM_PORT:-8192}"
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

echo "== M191-1 单测（judge_error_field + goal_pause_resume + cron_names + watchdog） =="
PYTHONPATH=src $PY -m pytest \
  tests/test_m191_judge_error_field.py tests/test_m191_goal_pause_resume.py \
  tests/test_m191_cron_names.py tests/test_m191_watchdog.py -q \
  && pass "M191 单测全绿" || bad "M191 单测失败"

echo "== M191-2 真实后端黑盒 E2E（uvicorn :${PORT} + 假 LLM :${FAKE_PORT}） =="

# 假 OpenAI 兼容端点（纯文本 JSON 模式，对齐 _direct_glm_tool_call 解析路径）：
# - judge（GOAL_JUDGE_V1）：JUDGEBREAK → 无 JSON 废文（触发 JudgeParseError→None）；
#     APPROVEFLOW → achieved=true；其余 → false（gap 不同防 no-progress 误熔断）
# - supervisor（prompt 含 Plan schema 的 believe_done 键）：APPROVEFLOW 时——
#     首轮（无「子任务「」完成反馈）→ 高危 subtask「git push 模拟高危写入」；
#     放行后轮（verify 反馈含 子任务「」）→ believe_done=true（直进 verify 收尾）
# - overseer（prompt 含 Verdict schema 的 efficiency 键）→ continue 放行
# - 其余 chat → 即时回显 RE:<user>
cat > "$TMPD/fake_llm.py" <<'FAKEEOF'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

judge_calls = {"n": 0}

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
            if "JUDGEBREAK" in joined:
                content = "judge 临时不可用，稍后再试"  # 无大括号 → JudgeParseError → None
            elif "APPROVEFLOW" in joined:
                content = json.dumps({"achieved": True, "gap": ""}, ensure_ascii=False)
            else:
                judge_calls["n"] += 1
                gap = "还差甲" if judge_calls["n"] % 2 else "还差乙"
                content = json.dumps({"achieved": False, "gap": gap}, ensure_ascii=False)
        elif "believe_done" in joined:  # supervisor Plan schema
            if "APPROVEFLOW" in joined and "子任务「" not in joined:
                plan = {"believe_done": False, "subtask": "git push 模拟高危写入",
                        "rationale": "高危子任务需审批", "test_cases": []}
            else:
                plan = {"believe_done": True, "subtask": "",
                        "rationale": "目标已达成", "test_cases": []}
            content = json.dumps(plan, ensure_ascii=False)
        elif "efficiency" in joined:  # overseer Verdict schema
            content = json.dumps({"efficiency": 0.9, "direction": 0.9, "action": "continue",
                                  "issues": [], "rationale": "方向正确"}, ensure_ascii=False)
        else:
            content = "RE:" + user[:200]
        out = {"choices": [{"message": {"role": "assistant", "content": content}}],
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
  echo ""; echo "M191 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" ${PY} - <<'PYEOF'
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime

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

def goal_events(sid):
    return [e for e in events(sid) if e.get("type") == "goal"]

def phases(sid):
    return [e["payload"].get("phase") for e in goal_events(sid)]

def wait_phase(sid, want, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        ph = phases(sid)
        if want in ph:
            return ph
        time.sleep(0.4)
    return phases(sid)

# ============ 场景 a：cron 英文名 + 宏（POST /tasks 契约） ============
st, body = call("POST", "/tasks",
                {"title": "a-daily", "prompt": "p", "mode": "chat",
                 "kind": "cron", "cron": "@daily"})
nxt = body.get("next_run_at") or ""
ok_daily = False
if st == 201 and nxt:
    dt = datetime.fromisoformat(nxt)
    ok_daily = dt.hour == 0 and dt.minute == 0 and dt.timestamp() > time.time()
check("a.@daily → 201 且 next_run_at=次日 00:00（本地时区）",
      ok_daily, detail=f"HTTP {st} next_run_at={nxt}")

st, body = call("POST", "/tasks",
                {"title": "a-monfri", "prompt": "p", "mode": "chat",
                 "kind": "cron", "cron": "0 9 * * MON-FRI"})
nxt2 = body.get("next_run_at") or ""
ok_mf = False
if st == 201 and nxt2:
    dt2 = datetime.fromisoformat(nxt2)
    ok_mf = dt2.hour == 9 and dt2.minute == 0 and dt2.weekday() < 5
check("a.0 9 * * MON-FRI → 201 且 next_run_at 为工作日 09:00",
      ok_mf, detail=f"HTTP {st} next_run_at={nxt2}")

st, body = call("POST", "/tasks",
                {"title": "a-badmacro", "prompt": "p", "mode": "chat",
                 "kind": "cron", "cron": "@biweekly"})
check("a.@biweekly 非法宏 → 422",
      st == 422 and "cron" in str(body.get("detail", "")),
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")

st, body = call("POST", "/tasks",
                {"title": "a-badname", "prompt": "p", "mode": "chat",
                 "kind": "cron", "cron": "0 9 * * FUNDAY"})
check("a.FUNDAY 未知周名 → 422", st == 422,
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")

# ============ 场景 b：judge 连续废文 → error=true → exhausted_judge_errors ============
st, body = call("POST", "/assistant/sessions", {"title": "m191-judgefail", "mode": "chat"})
sid_b = body.get("id", "")
check("b.建 chat 会话", st == 200 and sid_b, detail=f"HTTP {st}")
st, body = call("POST", f"/assistant/sessions/{sid_b}/goal",
                {"objective": "JUDGEBREAK 任务"})
check("b.POST goal 200", st == 200, detail=f"HTTP {st}")

ph_b = wait_phase(sid_b, "exhausted", timeout=30)
check("b.相位 set→iter→judge→iter→judge→exhausted（2 次废文触发熔断）",
      ph_b == ["set", "iter", "judge", "iter", "judge", "exhausted"],
      detail=f"phases={ph_b}")
judges_b = [e["payload"] for e in goal_events(sid_b) if e["payload"].get("phase") == "judge"]
check("b.judge 事件 error=true 且 gap=judge 失败（结构化字段）",
      len(judges_b) == 2 and all(j.get("error") is True and j.get("gap") == "judge 失败"
                                 for j in judges_b),
      detail=f"judges={json.dumps(judges_b, ensure_ascii=False)[:200]}")
exh_b = [e["payload"] for e in goal_events(sid_b) if e["payload"].get("phase") == "exhausted"]
check("b.exhausted reason=judge_errors",
      exh_b and exh_b[0].get("reason") == "judge_errors",
      detail=json.dumps(exh_b[0], ensure_ascii=False)[:120] if exh_b else "none")

# ============ 场景 c：agent 模式审批暂停 → approve → judge_first 续跑 achieved ============
st, body = call("POST", "/assistant/sessions", {"title": "m191-approval", "mode": "agent"})
sid_c = body.get("id", "")
check("c.建 agent 会话", st == 200 and sid_c, detail=f"HTTP {st}")
st, body = call("POST", f"/assistant/sessions/{sid_c}/goal",
                {"objective": "APPROVEFLOW 审批暂停续跑全流程"})
check("c.POST goal 200", st == 200, detail=f"HTTP {st}")

ph_c = wait_phase(sid_c, "paused", timeout=30)
check("c.高危子任务触发 goal paused", "paused" in ph_c, detail=f"phases={ph_c}")
appr = [e for e in events(sid_c) if e.get("type") == "approval_request"]
check("c.approval_request 事件在场且 action 含 git push",
      len(appr) == 1 and "git push" in str(appr[0].get("payload", {}).get("action", "")),
      detail=f"approval_request={len(appr)}")
iters_c = [e["payload"] for e in goal_events(sid_c) if e["payload"].get("phase") == "iter"]
check("c.wrapper 停派：仅 1 轮 iter（无第 2 轮）", len(iters_c) == 1,
      detail=f"iters={len(iters_c)}")

st, body = call("GET", f"/assistant/sessions/{sid_c}/goal")
check("c.GET goal 重建 status=paused（summarize paused 语义）",
      st == 200 and body.get("status") == "paused",
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")

st, body = call("POST", f"/assistant/sessions/{sid_c}/approve")
check("c.approve 受理 200", st == 200 and body.get("ok") is True,
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")

ph_c2 = wait_phase(sid_c, "achieved", timeout=60)
check("c.全链相位 set→iter→paused→judge→achieved",
      ph_c2 == ["set", "iter", "paused", "judge", "achieved"],
      detail=f"phases={ph_c2}")
notes = [str(e.get("payload", {}).get("note", "")) for e in events(sid_c)
         if e.get("type") == "status"]
check("c.status 留痕「goal 审批续跑」", any("goal 审批续跑" in n for n in notes),
      detail=f"notes={notes[-3:]}")
judges_c = [e["payload"] for e in goal_events(sid_c) if e["payload"].get("phase") == "judge"]
check("c.续跑 judge error=false 且 achieved=true（judge_first 直判）",
      len(judges_c) == 1 and judges_c[0].get("error") is False
      and judges_c[0].get("achieved") is True,
      detail=f"judges={json.dumps(judges_c, ensure_ascii=False)[:160]}")

st, sess = call("GET", f"/sessions/{sid_c}")
check("c.会话终态 done", st == 200 and sess.get("status") == "done",
      detail=f"HTTP {st} status={sess.get('status')}")

# ============ 场景 d：watchdog 黑盒说明 ============
print("  ℹ️  d.watchdog 为同进程协程，外部无法注入 stale 状态 → 单测覆盖（test_m191_watchdog.py 6 例）")

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "黑盒场景 a-c 全绿" || bad "黑盒场景有失败"

echo ""
if [ ${fail} -eq 0 ]; then echo "M191 验收：全部通过 ✅"; else echo "M191 验收：有未通过 ❌"; exit 1; fi
