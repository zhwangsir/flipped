#!/usr/bin/env bash
# M175 验收 — @ 文件引用（file mention，对标 ZCode 多类型附件 / opencode @file）。
#
#   1) pytest 单测：test_m175_file_refs.py（A 展开模块 18 例）+
#      test_m175_refs_api.py（B 接线+turns refs 9 例）
#   2) 真实后端黑盒 E2E：假 OpenAI server（http.server 回显 RE:<user>，非流式）+
#      真 uvicorn（FLIPPED_USE_LOCAL_WORKER=1 直连假端点，RAG/地图注入关闭保确定性），
#      临时项目写含锚点串的 hello.py → chat 会话发 "看下 @hello.py" → 断言：
#        user turn refs 元数据 ok/bytes>0、user 原文不被展开污染、
#        假 LLM 回显（=模型实际收到的 user 输入）含锚点串与 REFS_HEADER
#        ——证明文件内容真实到达模型；
#      再发 "@nofile.py" → refs[0].status==missing + 回显含中文状态注释。
#      （前端 @ 补全/引用行证据在 vitest composer.test.tsx / Assistant.test.tsx）
#
# 一键复跑: scripts/verify_m175.sh
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

echo "== M175-1 展开模块 + 接线单测（27 例） =="
PYTHONPATH=src $PY -m pytest tests/test_m175_file_refs.py tests/test_m175_refs_api.py -q \
  && pass "M175 单测全绿" || bad "M175 单测失败"

echo "== M175-2 真实后端黑盒 E2E（uvicorn :${PORT} + 假 LLM :${FAKE_PORT}） =="

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
  echo ""; echo "M175 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" PROJ_DIR="$TMPD/projects/m175demo" ${PY} - <<'PYEOF'
import json, os, sys, time, urllib.request, urllib.error

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
PROJ = os.environ["PROJ_DIR"]
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
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = history(sid)
        if len(h) >= n:
            return h
        time.sleep(0.3)
    return history(sid)

# 1. 建项目并设为活动（顺序不可反：先 POST 建空目录，再往里写文件）
st, body = call("POST", "/projects", {"name": "m175demo"})
check("POST /projects 建项目并设为活动", st in (200, 201) and body.get("name") == "m175demo",
      detail=f"HTTP {st} {json.dumps(body)[:120]}")

# 2. 写入含锚点串的真实文件
os.makedirs(os.path.join(PROJ, "src"), exist_ok=True)
with open(os.path.join(PROJ, "src", "hello.py"), "w") as fh:
    fh.write('# ZETA_ANCHOR_175 独特锚点串\nprint("zeta")\n')

# 3. 建 chat 会话
st, body = call("POST", "/assistant/sessions", {"title": "m175-e2e", "mode": "chat"})
sid = body.get("id", "")
check("POST /assistant/sessions 建 chat 会话", st == 200 and bool(sid), detail=f"HTTP {st}")

# 4. 发送带 @ 引用的消息
st, body = call("POST", f"/assistant/sessions/{sid}/messages",
                {"text": "看下 @src/hello.py", "mode": "chat"})
check("发送 @src/hello.py 消息 200", st == 200, detail=f"HTTP {st} {json.dumps(body)[:140]}")

h = wait_turns(sid, 2)
check("history 2 turns（user + assistant）", len(h) == 2, detail=f"len={len(h)}")
if len(h) >= 2:
    user_t, asst_t = h[0], h[1]
    # 4a. user turn refs 元数据
    refs = user_t.get("refs") or []
    check("user turn refs 含 src/hello.py 且 status=ok、bytes>0",
          len(refs) == 1 and refs[0].get("path") == "src/hello.py"
          and refs[0].get("status") == "ok" and int(refs[0].get("bytes") or 0) > 0,
          detail=json.dumps(refs)[:200])
    # 4b. user 原文不被展开污染
    check("user turn text 保持原文（@token 可见，未注入文件内容）",
          user_t.get("text") == "看下 @src/hello.py")
    # 4c. 回显含锚点（=文件内容真实到达模型）与 REFS_HEADER
    reply = asst_t.get("text") or ""
    check("假 LLM 回显含锚点串 ZETA_ANCHOR_175（文件内容确到模型）",
          "ZETA_ANCHOR_175" in reply, detail=reply[:160])
    check("回显含 REFS_HEADER（以下是用户通过 @ 显式引用）",
          "以下是用户通过 @ 显式引用的项目文件内容" in reply)
    check("回显含 fence 分节 ### @src/hello.py",
          "### @src/hello.py" in reply and "```py" in reply)

# 5. 再发 missing 引用 → refs 状态 + 回显中文状态注释
st, body = call("POST", f"/assistant/sessions/{sid}/messages",
                {"text": "@nofile.py 在吗", "mode": "chat"})
check("发送 @nofile.py 消息 200", st == 200, detail=f"HTTP {st}")
h = wait_turns(sid, 4)
if len(h) >= 4:
    refs2 = h[2].get("refs") or []
    reply2 = h[3].get("text") or ""
    check("missing 引用 refs[0].status==missing",
          len(refs2) == 1 and refs2[0].get("status") == "missing",
          detail=json.dumps(refs2)[:160])
    check("missing 回显含中文状态注释（文件不存在或不可读）",
          "文件不存在或不可读" in reply2, detail=reply2[-200:])
else:
    check("missing 消息 history 收敛到 4 turns", False, detail=f"len={len(h)}")

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "黑盒 E2E 全绿" || bad "黑盒 E2E 失败"

echo ""
if [ ${fail} -eq 0 ]; then echo "M175（@ 文件引用）验收：通过 ✅"; else echo "M175 验收：有未通过 ❌"; fi
exit ${fail}
