#!/usr/bin/env bash
# M176 验收 — Goal 模式（/goal 目标驱动自循环 + 逐轮 judge 验证，对标 ZCode Goal Mode）。
#
#   1) pytest 单测：test_m176_goal.py（A 状态机 20 例）+ test_m176_goal_api.py（B 接线 13 例）
#   2) 真实后端黑盒 E2E：假 OpenAI server（http.server；judge 请求按 GOAL_JUDGE_V1 marker 分流，
#      脚本化 verdict）+ 真 uvicorn（FLIPPED_USE_LOCAL_WORKER=1 直连假端点，非流式，
#      RAG/地图注入关闭保确定性）。三场景：
#        a) 2 轮未达成后第 3 轮达成 → 相位序列 set→iter→judge→iter→judge→iter→judge→achieved，
#           user 消息仅 1 条，续跑 prompt 含上轮 gap，GET goal 重建 status=achieved
#        b) NEVERDONE + max_iterations=2 → exhausted reason=max_iter，恰 2 轮
#        c) SLOW（假 LLM sleep）+ cancel → goal stopped 事件
#      （前端 /goal 命令/marker 渲染/goalActive 证据在 vitest）
#
# 一键复跑: scripts/verify_m176.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8176}"
FAKE_PORT="${FLIPPED_FAKE_LLM_PORT:-8177}"
SRV_PID=""; FAKE_PID=""
cleanup() {
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
  [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null; wait "$FAKE_PID" 2>/dev/null
  rm -rf "$TMPD"
}
trap cleanup EXIT
export FLIPPED_PROJECTS_DIR="$TMPD/projects"
export FLIPPED_DB="$TMPD/flipped.db"

echo "== M176-1 goal 状态机 + 接线单测（33 例） =="
PYTHONPATH=src $PY -m pytest tests/test_m176_goal.py tests/test_m176_goal_api.py -q \
  && pass "M176 单测全绿" || bad "M176 单测失败"

echo "== M176-2 真实后端黑盒 E2E（uvicorn :${PORT} + 假 LLM :${FAKE_PORT}） =="

# 假 OpenAI 兼容端点：
# - judge 请求（任一 message 含 GOAL_JUDGE_V1）→ 脚本化 verdict：
#     含 NEVERDONE → 恒 {"achieved": false, "gap": "永远差一点"}
#     否则全局计数：第 1/2 次 false（gap 用不同非数字词防 no-progress 误熔断），第 3 次 true
# - 普通 chat：user 含 SLOW → sleep 4s（给 cancel 留窗口）；回显 RE:<user>
cat > "$TMPD/fake_llm.py" <<'FAKEEOF'
import json, sys, time
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
            if "NEVERDONE" in joined:
                verdict = {"achieved": False, "gap": "永远差一点"}
            else:
                judge_calls["n"] += 1
                if judge_calls["n"] >= 3:
                    verdict = {"achieved": True, "gap": ""}
                elif judge_calls["n"] == 2:
                    verdict = {"achieved": False, "gap": "还差乙"}
                else:
                    verdict = {"achieved": False, "gap": "还差甲"}
            out = {"choices": [{"message": {"role": "assistant",
                                            "content": json.dumps(verdict, ensure_ascii=False)}}],
                   "usage": {"prompt_tokens": 2, "completion_tokens": 1}}
        else:
            if "SLOW" in user:
                time.sleep(4)
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
  echo ""; echo "M176 验收：有未通过 ❌"; exit 1
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

def goal_events(sid):
    return [e for e in events(sid) if e.get("type") == "goal"]

def phases(sid):
    return [e["payload"].get("phase") for e in goal_events(sid)]

def wait_phase(sid, want, timeout=25):
    """等 goal 事件出现终态相位 want，返回相位序列。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        ph = phases(sid)
        if want in ph:
            return ph
        time.sleep(0.4)
    return phases(sid)

# ============ 场景 a：2 轮未达成 → 第 3 轮达成 ============
st, body = call("POST", "/assistant/sessions", {"title": "m176-achieve", "mode": "chat"})
sid_a = body.get("id", "")
check("a.建 chat 会话", st == 200 and sid_a, detail=f"HTTP {st}")

st, body = call("POST", f"/assistant/sessions/{sid_a}/goal", {"objective": "完成问候任务"})
check("a.POST goal 200 + max_iterations 缺省 5",
      st == 200 and body.get("max_iterations") == 5 and body.get("objective") == "完成问候任务",
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")

ph = wait_phase(sid_a, "achieved", timeout=30)
check("a.相位序列 set→iter→judge→iter→judge→iter→judge→achieved",
      ph == ["set", "iter", "judge", "iter", "judge", "iter", "judge", "achieved"],
      detail=f"phases={ph}")

ge = goal_events(sid_a)
iters = [e["payload"] for e in ge if e["payload"].get("phase") == "iter"]
check("a.恰 3 轮迭代", len(iters) == 3, detail=f"iters={len(iters)}")
check("a.第 2 轮续跑 prompt 含上轮 gap（还差甲）+ 轮次",
      len(iters) >= 2 and "还差甲" in iters[1].get("prompt", "") and "第 2/5 轮" in iters[1].get("prompt", ""),
      detail=(iters[1].get("prompt", "")[:80] if len(iters) >= 2 else "no iter2"))
check("a.第 1 轮 prompt = objective 原文", iters and iters[0].get("prompt") == "完成问候任务")

msgs = [e for e in events(sid_a) if e.get("type") == "message" and e.get("agent") == "user"]
check("a.user 消息仅 1 条且带 goal.started 标记",
      len(msgs) == 1 and (msgs[0]["payload"].get("goal") or {}).get("started") is True,
      detail=f"user msgs={len(msgs)}")

st, body = call("GET", f"/assistant/sessions/{sid_a}/goal")
check("a.GET goal 重建 status=achieved iteration=3",
      st == 200 and body.get("status") == "achieved" and body.get("iteration") == 3,
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")

st, hist = call("GET", f"/assistant/sessions/{sid_a}/history")
goal_turns = [t for t in hist if t.get("role") == "goal"] if st == 200 else []
check("a.history 含 goal turns（iter×3 + achieved，set/judge 不折）",
      len(goal_turns) == 4 and goal_turns[-1]["goal"].get("phase") == "achieved",
      detail=f"goal turns={len(goal_turns)}")

# ============ 场景 b：NEVERDONE + max_iter=2 → exhausted max_iter ============
st, body = call("POST", "/assistant/sessions", {"title": "m176-exhaust", "mode": "chat"})
sid_b = body.get("id", "")
st, body = call("POST", f"/assistant/sessions/{sid_b}/goal",
                {"objective": "NEVERDONE 任务", "max_iterations": 2})
check("b.POST goal 200 + max_iterations=2", st == 200 and body.get("max_iterations") == 2,
      detail=f"HTTP {st}")
ph_b = wait_phase(sid_b, "exhausted", timeout=25)
check("b.相位序列 set→iter→judge→iter→exhausted（末轮不 judge）",
      ph_b == ["set", "iter", "judge", "iter", "exhausted"], detail=f"phases={ph_b}")
exh = [e["payload"] for e in goal_events(sid_b) if e["payload"].get("phase") == "exhausted"]
check("b.exhausted reason=max_iter", exh and exh[0].get("reason") == "max_iter",
      detail=json.dumps(exh[0], ensure_ascii=False)[:100] if exh else "none")

# ============ 场景 c：SLOW + cancel → stopped ============
st, body = call("POST", "/assistant/sessions", {"title": "m176-cancel", "mode": "chat"})
sid_c = body.get("id", "")
st, body = call("POST", f"/assistant/sessions/{sid_c}/goal", {"objective": "SLOW 任务"})
check("c.POST goal 200", st == 200, detail=f"HTTP {st}")
time.sleep(1.2)  # 假 LLM sleep 4s，确保 cancel 落在首轮执行中
st, body = call("POST", f"/sessions/{sid_c}/cancel")
check("c.cancel 受理", st == 200, detail=f"HTTP {st}")
ph_c = wait_phase(sid_c, "stopped", timeout=15)
check("c.cancel 后 goal stopped 事件出现", "stopped" in ph_c, detail=f"phases={ph_c}")
check("c.未出现 achieved/exhausted（半途停止）",
      "achieved" not in ph_c and "exhausted" not in ph_c, detail=f"phases={ph_c}")

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "黑盒 E2E 全绿" || bad "黑盒 E2E 失败"

echo ""
if [ ${fail} -eq 0 ]; then echo "M176（Goal 模式）验收：通过 ✅"; else echo "M176 验收：有未通过 ❌"; fi
exit ${fail}
