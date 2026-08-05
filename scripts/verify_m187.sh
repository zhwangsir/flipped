#!/usr/bin/env bash
# M187 验收 — 任务系统增强（cron 表达式 + 任务编辑 PATCH + 重启安全）。
#
#   1) pytest 单测：test_m187_cron.py（46 例：validate 合法/非法/边界 + cron_next
#      确定性/闰年/永不触发/dom-dow OR/naive-aware 对齐 + compute_next_run 分支
#      + 端点创建校验）+ test_m187_task_patch.py（19 例：update 白名单/合并校验/
#      重算语义 + PATCH 端点 + lifespan stale running 恢复）
#   2) 真实后端黑盒 E2E：真 uvicorn ×2（:PORT 正常 + :PORT_OFF 置 FLIPPED_TASKS=0）：
#        a. POST /tasks kind=cron '* * * * *' → 201 且 cron 回显且 next_run_at ≤60s 内
#        b. kind=cron 非法表达式 → 422；kind=once 带 cron → 422
#        c. PATCH 改 title → 200 且 next_run_at 原值不变；PATCH 改 cron → 重算变化
#        d. PATCH 未知 id → 404；空 body → 422；合并非法（kind=once 无 run_at）→ 422
#        e. 重启安全：预置 .sessions.json（running 无 checkpoint 假会话 + paused 假会话）
#           → 启动后 running 者 status==error，paused 者不动
#        f. FLIPPED_TASKS=0 实例：POST cron / PATCH 全 404
#      （前端 cron 选项/编辑表单证据在 vitest ScheduledView.test.tsx + store.test.tsx）
#
# 一键复跑: scripts/verify_m187.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8187}"
PORT_OFF="${FLIPPED_VERIFY_PORT_OFF:-8188}"
SRV_PID=""; SRV_OFF_PID=""
cleanup() {
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
  [ -n "$SRV_OFF_PID" ] && kill "$SRV_OFF_PID" 2>/dev/null; wait "$SRV_OFF_PID" 2>/dev/null
  rm -rf "$TMPD"
}
trap cleanup EXIT
export FLIPPED_PROJECTS_DIR="$TMPD/projects"
export FLIPPED_DB="$TMPD/flipped.db"
export FLIPPED_TASKS_PATH="$TMPD/scheduled_tasks.json"
export FLIPPED_TASKS_SCAN_S=3600  # 黑盒不触发真实派发，只验计算/编辑/恢复

echo "== M187-1 单测（65 例） =="
PYTHONPATH=src $PY -m pytest tests/test_m187_cron.py tests/test_m187_task_patch.py -q \
  && pass "M187 单测全绿" || bad "M187 单测失败"

echo "== M187-2 真实后端黑盒 E2E（uvicorn :${PORT} + 开关实例 :${PORT_OFF}） =="

# e 前置：预置会话仓——running 无 checkpoint（stale，应被标 error）+ paused 无 checkpoint（不动）
export FLIPPED_SESSION_STORE_PATH="$TMPD/.sessions.json"
cat > "$FLIPPED_SESSION_STORE_PATH" <<'SEEDEOF'
{
  "sessions": [
    {"id": "sess-stale001", "title": "stale-chat", "status": "running",
     "model": "coder", "mode": "chat", "checkpoint_db_path": null,
     "created_at": "2026-08-05T00:00:00+00:00", "updated_at": "2026-08-05T00:00:00+00:00"},
    {"id": "sess-paused01", "title": "paused-chat", "status": "paused",
     "model": "coder", "mode": "chat", "checkpoint_db_path": null,
     "created_at": "2026-08-05T00:00:00+00:00", "updated_at": "2026-08-05T00:00:00+00:00"}
  ],
  "events": {}
}
SEEDEOF

PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!

FLIPPED_TASKS=0 FLIPPED_SESSION_STORE_PATH="$TMPD/.sessions_off.json" \
PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT_OFF}" --log-level warning &
SRV_OFF_PID=$!

ready=0
for _ in $(seq 1 60); do
  ok1=$(curl -sf "http://127.0.0.1:${PORT}/api/v1/health" -o /dev/null 2>&1 && echo 1)
  ok2=$(curl -sf "http://127.0.0.1:${PORT_OFF}/api/v1/health" -o /dev/null 2>&1 && echo 1)
  if [ "${ok1}" = "1" ] && [ "${ok2}" = "1" ]; then ready=1; break; fi
  sleep 0.5
done
if [ "${ready}" != "1" ]; then
  bad "后端 30s 内未就绪"
  echo ""; echo "M187 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" \
FLIPPED_BASE_OFF="http://127.0.0.1:${PORT_OFF}" ${PY} - <<'PYEOF'
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
BASE_OFF = os.environ["FLIPPED_BASE_OFF"] + "/api/v1"
fails = []

def call(method, path, body=None, base=BASE):
    req = urllib.request.Request(
        base + path, method=method,
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

# a. 创建 cron 任务：'* * * * *' → 201 + cron 回显 + next_run_at 在 60s 内
st, body = call("POST", "/tasks", {
    "title": "cron巡检", "prompt": "每分钟巡检", "kind": "cron", "cron": "* * * * *"})
tid = body.get("id", "")
nxt = body.get("next_run_at")
delta = None
if nxt:
    delta = (datetime.fromisoformat(nxt) - datetime.now(timezone.utc)).total_seconds()
check("a.POST kind=cron → 201 + cron 回显 + next_run_at ≤60s",
      st == 201 and body.get("cron") == "* * * * *" and body.get("kind") == "cron"
      and delta is not None and 0 < delta <= 60,
      detail=f"HTTP {st} delta={delta} {json.dumps(body, ensure_ascii=False)[:200]}")

# b1. cron 非法表达式 → 422
st, body = call("POST", "/tasks", {
    "title": "bad", "prompt": "p", "kind": "cron", "cron": "99 * * * *"})
check("b1.kind=cron 非法表达式 → 422", st == 422, detail=f"HTTP {st}")

# b2. kind=once 带 cron → 422
st, body = call("POST", "/tasks", {
    "title": "bad2", "prompt": "p", "kind": "once",
    "run_at": "2099-01-01T00:00:00+00:00", "cron": "* * * * *"})
check("b2.kind=once 带 cron → 422", st == 422, detail=f"HTTP {st}")

# c1. PATCH 改 title → 200 且 next_run_at 原值不变
st, before = call("GET", "/tasks")
task0 = next((t for t in before if t.get("id") == tid), {})
st, body = call("PATCH", f"/tasks/{tid}", {"title": "改名巡检"})
check("c1.PATCH 改 title → 200 且 next_run_at 不变",
      st == 200 and body.get("title") == "改名巡检"
      and body.get("next_run_at") == task0.get("next_run_at"),
      detail=f"HTTP {st} before={task0.get('next_run_at')} after={body.get('next_run_at')}")

# c2. PATCH 改 cron → 200 且 next_run_at 重算变化
st, body = call("PATCH", f"/tasks/{tid}", {"cron": "0 9 * * 1-5"})
check("c2.PATCH 改 cron → 200 且 next_run_at 重算变化",
      st == 200 and body.get("cron") == "0 9 * * 1-5"
      and body.get("next_run_at") != task0.get("next_run_at")
      and body.get("next_run_at") is not None,
      detail=f"HTTP {st} before={task0.get('next_run_at')} after={body.get('next_run_at')}")

# d1. PATCH 未知 id → 404
st, body = call("PATCH", "/tasks/task-00000000", {"title": "x"})
check("d1.PATCH 未知 id → 404", st == 404, detail=f"HTTP {st}")

# d2. PATCH 空 body → 422
st, body = call("PATCH", f"/tasks/{tid}", {})
check("d2.PATCH 空 body → 422", st == 422, detail=f"HTTP {st}")

# d3. PATCH 后合并非法（kind=once 无 run_at）→ 422
st, body = call("PATCH", f"/tasks/{tid}", {"kind": "once"})
check("d3.PATCH kind=once 缺 run_at（合并非法）→ 422", st == 422, detail=f"HTTP {st}")

# e. 重启安全：stale running 无 checkpoint → error；paused 不动
st, sessions = call("GET", "/sessions")
by_id = {s.get("id"): s for s in sessions}
stale = by_id.get("sess-stale001", {})
paused = by_id.get("sess-paused01", {})
check("e.stale running 无 checkpoint → error；paused 不动",
      stale.get("status") == "error" and paused.get("status") == "paused",
      detail=f"stale={stale.get('status')} paused={paused.get('status')}")

# f. FLIPPED_TASKS=0 实例：POST cron / PATCH 全 404
st1, _ = call("POST", "/tasks", {
    "title": "x", "prompt": "p", "kind": "cron", "cron": "* * * * *"}, base=BASE_OFF)
st2, _ = call("PATCH", "/tasks/task-whatever", {"title": "x"}, base=BASE_OFF)
check("f.FLIPPED_TASKS=0 实例 POST/PATCH 全 404", st1 == 404 and st2 == 404,
      detail=f"POST={st1} PATCH={st2}")

print("")
if fails:
    print("M187 黑盒失败项: " + ", ".join(fails))
    sys.exit(1)
print("  ✅ 黑盒 E2E 全绿")
PYEOF
[ $? -eq 0 ] && pass "黑盒 E2E 全绿" || bad "黑盒 E2E 有失败"

echo ""
if [ $fail -eq 0 ]; then
  echo "M187（任务系统增强）验收：通过 ✅"
else
  echo "M187 验收：有未通过 ❌"
fi
exit $fail
