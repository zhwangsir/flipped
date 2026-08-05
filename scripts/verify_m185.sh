#!/usr/bin/env bash
# M185 验收 — P0 限制消化（L-M183-1 / L-M183-3 / L-M183-6 / L-M184-2）。
#
#   1) pytest 单测：test_m185_p0_limitations.py（20 例：build scopes 参数化 /
#      snapshot semantics+success_rate 派生 / 落盘无派生字段 / check 增强十例）
#   2) 前端 vitest：WorkerRulesPanel.test.tsx（22 例：成功率 success/(success+failure)
#      新公式 / 零 outcome 不渲染 bar / 语义注记 semantics 渲染与兜底）
#   3) 真实后端黑盒 E2E：真 uvicorn ×2（:PORT 正常 + :PORT_OFF 置
#      FLIPPED_WORKER_RULES_CHAT=0）+ 假 OpenAI server（记录 system 到 capture，回显
#      "RE:<user>"）；worker rules 两实例共享同一 FLIPPED_WORKER_RULES_PATH：
#        a. POST 建 scope=all（唯一标记 A）+ scope=worker（唯一标记 W）各一条
#        b. 正常实例 chat → capture 的 system 含 A 且不含 W（worker-only 不进对话）
#        c. events 端点 assistant message 事件 payload.worker_rules_injected==true
#           （payload 标记只在事件层，与 M173 map_injected 同设计；history turn 不折叠）
#        d. FLIPPED_WORKER_RULES_CHAT=0 实例 chat → system 不含 A（开关关闭）
#           且 events payload 无 worker_rules_injected
#        e. GET /worker/rules 缺省=全量插入序（D20 回归）；?enabled=true 过滤停用；
#           ?enabled=false 只留停用；?sort=priority → priority desc
#        f. GET /worker/rules/stats（预置 stats 文件）→ semantics 非空 +
#           entry.success_rate==0.5（派生字段）
#   4) 存量 58 条 registry 跑增强 check → exit 0（真实性校验对现状数据零误报）
#
# 一键复跑: scripts/verify_m185.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8190}"
PORT_OFF="${FLIPPED_VERIFY_PORT_OFF:-8191}"
FAKE_PORT="${FLIPPED_FAKE_LLM_PORT:-8192}"
SRV_PID=""; SRV_OFF_PID=""; FAKE_PID=""
cleanup() {
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
  [ -n "$SRV_OFF_PID" ] && kill "$SRV_OFF_PID" 2>/dev/null; wait "$SRV_OFF_PID" 2>/dev/null
  [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null; wait "$FAKE_PID" 2>/dev/null
  rm -rf "$TMPD"
}
trap cleanup EXIT
export FLIPPED_PROJECTS_DIR="$TMPD/projects"
export FLIPPED_DB="$TMPD/flipped.db"
export FLIPPED_SESSION_STORE_PATH="$TMPD/.sessions.json"
export FLIPPED_WORKER_RULES_PATH="$TMPD/worker_rules.json"
export FLIPPED_WORKER_RULE_STATS_PATH="$TMPD/worker_rule_stats.json"

echo "== M185-1 单测（20 例） =="
PYTHONPATH=src $PY -m pytest tests/test_m185_p0_limitations.py -q \
  && pass "M185 单测全绿" || bad "M185 单测失败"

echo "== M185-2 前端 vitest（WorkerRulesPanel） =="
( cd console && npx vitest run src/components/WorkerRulesPanel.test.tsx >/dev/null 2>&1 ) \
  && pass "前端 vitest 全绿" || bad "前端 vitest 失败"

echo "== M185-3 真实后端黑盒 E2E（uvicorn :${PORT} + 开关实例 :${PORT_OFF} + 假 LLM :${FAKE_PORT}） =="

# 假 OpenAI 兼容端点：记录 system 到 ${CAPTURE_PATH} 文件，回显 "RE:<user 文本>"
cat > "$TMPD/fake_llm.py" <<'FAKEEOF'
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

CAPTURE = os.environ["CAPTURE_PATH"]

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        system, user = "", ""
        for m in body.get("messages", []):
            if m.get("role") == "system":
                system += str(m.get("content", ""))
            if m.get("role") == "user":
                user = str(m.get("content", ""))
        with open(CAPTURE, "w") as fh:
            fh.write(system)
        out = {"choices": [{"message": {"role": "assistant", "content": "RE:" + user}}],
               "usage": {"prompt_tokens": 5, "completion_tokens": 3}}
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
CAPTURE_PATH="$TMPD/captured_system.txt" $PY "$TMPD/fake_llm.py" "${FAKE_PORT}" &
FAKE_PID=$!

FLIPPED_USE_LOCAL_WORKER=1 \
FLIPPED_MODEL_BASE_URL="http://127.0.0.1:${FAKE_PORT}/v1" \
FLIPPED_CHAT_STREAM=0 FLIPPED_RAG_AUTO=0 FLIPPED_MAP_AUTO=0 \
PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!

FLIPPED_USE_LOCAL_WORKER=1 \
FLIPPED_MODEL_BASE_URL="http://127.0.0.1:${FAKE_PORT}/v1" \
FLIPPED_CHAT_STREAM=0 FLIPPED_RAG_AUTO=0 FLIPPED_MAP_AUTO=0 \
FLIPPED_WORKER_RULES_CHAT=0 \
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
  echo ""; echo "M185 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" \
FLIPPED_BASE_OFF="http://127.0.0.1:${PORT_OFF}" \
CAPTURE_PATH="$TMPD/captured_system.txt" \
STATS_PATH="$FLIPPED_WORKER_RULE_STATS_PATH" ${PY} - <<'PYEOF'
import json, os, sys, time, urllib.request, urllib.error

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
BASE_OFF = os.environ["FLIPPED_BASE_OFF"] + "/api/v1"
CAPTURE = os.environ["CAPTURE_PATH"]
STATS = os.environ["STATS_PATH"]
MARK_ALL = "WRMARKER_ALL_全域规则必须遵守"
MARK_WORKER = "WRMARKER_WORKER_仅执行者可见"
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

def chat_roundtrip(base, text):
    """建 chat 会话 → 发消息 → 轮询 history 直到 assistant 回复到达；返回 session_id。"""
    st, body = call("POST", "/assistant/sessions", {"title": "m185-e2e", "mode": "chat"}, base=base)
    assert st in (200, 201), f"建会话 HTTP {st}: {json.dumps(body)[:160]}"
    sid = body["id"]
    st, body = call("POST", f"/assistant/sessions/{sid}/messages", {"text": text}, base=base)
    assert st in (200, 201, 202), f"发消息 HTTP {st}: {json.dumps(body)[:160]}"
    for _ in range(40):
        time.sleep(0.5)
        st, body = call("GET", f"/assistant/sessions/{sid}/history", base=base)
        turns = body if isinstance(body, list) else body.get("turns", [])
        for t in turns:
            if t.get("role") == "assistant" and (t.get("text") or "").startswith("RE:"):
                return sid
    return sid

def last_wr_injected(base, sid):
    """events 端点查最近 assistant message 事件的 worker_rules_injected 标记。"""
    st, events = call("GET", f"/sessions/{sid}/events", base=base)
    assert st == 200, f"events HTTP {st}"
    injected = None
    for ev in events:
        if ev.get("type") == "message" and ev.get("agent") == "worker":
            injected = (ev.get("payload") or {}).get("worker_rules_injected")
    return injected

# a. 建 scope=all + scope=worker 规则各一条（唯一标记；两实例共享 rules 文件）
st, body = call("POST", "/worker/rules", {"text": MARK_ALL, "scope": "all", "priority": 10})
check("a1.POST scope=all 规则 → 201", st == 201 and body.get("scope") == "all",
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")
st, body = call("POST", "/worker/rules", {"text": MARK_WORKER, "scope": "worker", "priority": 90})
check("a2.POST scope=worker 规则 → 201", st == 201 and body.get("scope") == "worker",
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")

# b. 正常实例 chat：system 含 all 标记、不含 worker-only 标记
sid = chat_roundtrip(BASE, "worker 规则注入测试")
with open(CAPTURE) as fh:
    captured = fh.read()
check("b.chat system 含 scope=all 标记且不含 worker-only 标记",
      MARK_ALL in captured and MARK_WORKER not in captured,
      detail=f"captured[:200]={captured[:200]!r}")

# c. events 端点：assistant message payload.worker_rules_injected==true
injected = last_wr_injected(BASE, sid)
check("c.events assistant message payload.worker_rules_injected==true",
      injected is True, detail=f"worker_rules_injected={injected!r}")

# d. FLIPPED_WORKER_RULES_CHAT=0 实例：system 不含 all 标记且无注入标记
sid_off = chat_roundtrip(BASE_OFF, "开关关闭测试")
with open(CAPTURE) as fh:
    captured_off = fh.read()
injected_off = last_wr_injected(BASE_OFF, sid_off)
check("d.开关实例 system 不含 all 标记且 payload 无 worker_rules_injected",
      MARK_ALL not in captured_off and injected_off is None,
      detail=f"captured[:120]={captured_off[:120]!r} injected={injected_off!r}")

# e. GET /worker/rules：缺省插入序 / enabled 过滤 / sort=priority
st, body = call("GET", "/worker/rules")
rules = body.get("rules", [])
ids_insertion = [r["text"] for r in rules]
check("e1.缺省=全量插入序（先 all 后 worker，D20 回归）",
      st == 200 and ids_insertion == [MARK_ALL, MARK_WORKER],
      detail=f"{ids_insertion!r}")
st, body = call("GET", "/worker/rules?sort=priority")
ids_prio = [r["text"] for r in body.get("rules", [])]
check("e2.?sort=priority → priority desc（worker(90) 在 all(10) 前）",
      st == 200 and ids_prio == [MARK_WORKER, MARK_ALL],
      detail=f"{ids_prio!r}")
# 停用 all 规则后过滤
st, rules_all = call("GET", "/worker/rules")
all_id = [r["id"] for r in rules_all["rules"] if r["text"] == MARK_ALL][0]
call("POST", f"/worker/rules/{all_id}/toggle", {"enabled": False})
st, body = call("GET", "/worker/rules?enabled=true")
texts_en = [r["text"] for r in body.get("rules", [])]
check("e3.?enabled=true 过滤停用（只剩 worker 规则）",
      st == 200 and texts_en == [MARK_WORKER], detail=f"{texts_en!r}")
st, body = call("GET", "/worker/rules?enabled=false")
texts_dis = [r["text"] for r in body.get("rules", [])]
check("e4.?enabled=false 只留停用（只剩 all 规则）",
      st == 200 and texts_dis == [MARK_ALL], detail=f"{texts_dis!r}")
# 复启（不影响后续用例；d 项已完成不受影响）
call("POST", f"/worker/rules/{all_id}/toggle", {"enabled": True})

# f. GET /worker/rules/stats：预置 stats 文件 → semantics 非空 + success_rate 派生
with open(STATS, "w") as fh:
    json.dump({"stats": {"wr-x": {"applied": 2, "success": 1, "failure": 1}},
               "total_runs": 2}, fh)
st, body = call("GET", "/worker/rules/stats")
entry = (body.get("stats") or {}).get("wr-x", {})
check("f.GET /stats → semantics 非空且 entry.success_rate==0.5（派生不落盘）",
      st == 200 and bool(body.get("semantics"))
      and entry.get("success_rate") == 0.5,
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:200]}")

print("")
if fails:
    print("M185 黑盒失败项: " + ", ".join(fails))
    sys.exit(1)
print("  ✅ 黑盒 E2E 全绿")
PYEOF
[ $? -eq 0 ] && pass "黑盒 E2E 全绿" || bad "黑盒 E2E 有失败"

echo "== M185-4 存量 registry 增强 check（58 条零误报） =="
$PY scripts/limitations_report.py check --state STATE.json --registry data/limitations_registry.json \
  && pass "存量 registry 过增强 check" || bad "存量 registry 未过增强 check"

echo ""
if [ $fail -eq 0 ]; then
  echo "M185（P0 限制消化）验收：通过 ✅"
else
  echo "M185 验收：有未通过 ❌"
fi
exit $fail
