#!/usr/bin/env bash
# M180 验收 — 项目规则系统（rules：项目级规则文件 → chat/plan 注入 + 规则面板）。
#
#   1) pytest 单测：test_m180_rules.py（24 例：load 无文件/root None/单文件/三文件
#      优先级/非 utf8 跳过/空白不命中/截断注记；raw/write；端点 needs_project/
#      PUT 400/PUT 后 GET 反映/超 64KB 422；注入 chat/plan/env=0/空规则/fail-open）
#   2) 真实后端黑盒 E2E：真 uvicorn ×2（:PORT 正常 + :PORT_OFF 置 FLIPPED_RULES_AUTO=0）
#      + 假 OpenAI server（记录每次请求的 system 到 capture 文件，回显 "RE:<user>"）：
#        a. POST /projects 建项目 → 写 AGENTS.md（唯一标记文本）
#        b. GET /project/rules → files==["AGENTS.md"] 且 markdown 含标记，
#           rules_content==""（.flipped/rules.md 不存在）
#        c. PUT /project/rules 写 .flipped/rules.md → files 双命中且 rules_content 回显
#        d. 正常实例发 chat 消息 → 假 LLM capture 的 system 含两处规则标记（注入生效）
#        e. FLIPPED_RULES_AUTO=0 实例发 chat 消息 → system 不含规则标记（开关关闭）
#      （前端 RulesPanel 查看/编辑/保存证据在 vitest RulesPanel.test.tsx）
#
# 一键复跑: scripts/verify_m180.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8184}"
PORT_OFF="${FLIPPED_VERIFY_PORT_OFF:-8185}"
FAKE_PORT="${FLIPPED_FAKE_LLM_PORT:-8186}"
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

echo "== M180-1 单测（24 例） =="
PYTHONPATH=src $PY -m pytest tests/test_m180_rules.py -q \
  && pass "M180 单测全绿" || bad "M180 单测失败"

echo "== M180-2 真实后端黑盒 E2E（uvicorn :${PORT} + 开关实例 :${PORT_OFF} + 假 LLM :${FAKE_PORT}） =="

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
FLIPPED_RULES_AUTO=0 \
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
  echo ""; echo "M180 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" \
FLIPPED_BASE_OFF="http://127.0.0.1:${PORT_OFF}" \
PROJ_DIR="$TMPD/projects/m180demo" \
CAPTURE_PATH="$TMPD/captured_system.txt" ${PY} - <<'PYEOF'
import json, os, sys, time, urllib.request, urllib.error

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
BASE_OFF = os.environ["FLIPPED_BASE_OFF"] + "/api/v1"
PROJ = os.environ["PROJ_DIR"]
CAPTURE = os.environ["CAPTURE_PATH"]
MARK_AGENTS = "RULEMARKER_AGENTS_必须遵守"
MARK_FLIPPED = "RULEMARKER_FLIPPED_代码风格"
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
    """建 chat 会话 → 发消息 → 轮询 history 直到 assistant 回复到达。"""
    st, body = call("POST", "/assistant/sessions", {"title": "rules-e2e", "mode": "chat"}, base=base)
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
                return True
    return False

# a. 建项目并设为活动 + 写 AGENTS.md
st, body = call("POST", "/projects", {"name": "m180demo"})
check("a.POST /projects 建项目并设为活动",
      st in (200, 201) and body.get("name") == "m180demo",
      detail=f"HTTP {st} {json.dumps(body)[:120]}")
with open(os.path.join(PROJ, "AGENTS.md"), "w") as fh:
    fh.write("# 项目约定\n\n- " + MARK_AGENTS + "\n")

# b. GET /project/rules：单文件命中，rules_content 为空
st, body = call("GET", "/project/rules")
check("b.GET /project/rules → files==[AGENTS.md] 且 markdown 含标记 且 rules_content 为空",
      st == 200 and body.get("files") == ["AGENTS.md"]
      and MARK_AGENTS in body.get("markdown", "")
      and body.get("rules_content") == "" and body.get("needs_project") is False,
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:200]}")

# c. PUT 写 .flipped/rules.md → 双文件命中 + rules_content 回显
st, body = call("PUT", "/project/rules", {"content": "- " + MARK_FLIPPED + "\n"})
check("c.PUT /project/rules → files 双命中（.flipped 优先）且 rules_content 回显",
      st == 200 and body.get("files") == [".flipped/rules.md", "AGENTS.md"]
      and body.get("rules_content") == "- " + MARK_FLIPPED + "\n"
      and MARK_FLIPPED in body.get("markdown", "") and MARK_AGENTS in body.get("markdown", ""),
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:240]}")
# 文件系统事实核对
with open(os.path.join(PROJ, ".flipped", "rules.md")) as fh:
    on_disk = fh.read()
check("c2..flipped/rules.md 落盘内容正确", on_disk == "- " + MARK_FLIPPED + "\n",
      detail=repr(on_disk[:80]))

# d. 正常实例 chat：system 含两处规则标记
ok = chat_roundtrip(BASE, "规则注入测试")
with open(CAPTURE) as fh:
    captured = fh.read()
check("d.chat 消息跑通且 system 含 AGENTS + .flipped 双规则标记",
      ok and MARK_AGENTS in captured and MARK_FLIPPED in captured,
      detail=f"roundtrip={ok} captured[:160]={captured[:160]!r}")

# e. FLIPPED_RULES_AUTO=0 实例：system 不含规则标记
st, body = call("GET", "/project/rules", base=BASE_OFF)
if body.get("needs_project"):
    call("POST", "/projects", {"name": "m180demo"}, base=BASE_OFF)
ok = chat_roundtrip(BASE_OFF, "开关关闭测试")
with open(CAPTURE) as fh:
    captured = fh.read()
check("e.FLIPPED_RULES_AUTO=0 实例 chat 跑通且 system 不含规则标记",
      ok and MARK_AGENTS not in captured and MARK_FLIPPED not in captured,
      detail=f"roundtrip={ok} captured[:160]={captured[:160]!r}")

print("")
if fails:
    print("M180 黑盒失败项: " + ", ".join(fails))
    sys.exit(1)
print("  ✅ 黑盒 E2E 全绿")
PYEOF
[ $? -eq 0 ] && pass "黑盒 E2E 全绿" || bad "黑盒 E2E 有失败"

echo ""
if [ $fail -eq 0 ]; then
  echo "M180（项目规则系统）验收：通过 ✅"
else
  echo "M180 验收：有未通过 ❌"
fi
exit $fail
