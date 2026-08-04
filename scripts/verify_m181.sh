#!/usr/bin/env bash
# M181 验收 — 移动远程控制（手机扫码 → 远程查看进度/补需求/审批确认，对标 ZCode 远程控制）。
#
#   1) pytest 单测：test_m181_remote.py（24 例：registry issue/单活/未知/过期 purge/
#      revoke/持久化往返/坏文件；detect_lan_ip；qr_svg；mobile_page_html；
#      端点 无会话 400/指定 404/issue ok/state/无效 token/message 转发/decision 409/
#      页面 200+404/qr.svg/revoke 后 404/幂等 DELETE）
#   2) 真实后端黑盒 E2E：真 uvicorn（:${PORT}）+ 假 OpenAI server（回显 "RE:<user>"）：
#        a. 无会话 POST /remote/sessions → 400
#        b. 建 chat 会话 → POST /remote/sessions → 200 字段齐（token/url/qr_url/expires_at）
#        c. GET /remote/{token} 页面 → 200 且含 token（无效 token → 404 含「链接已失效」）
#        d. GET state → 200（turns/pending_approval 键齐）
#        e. POST /remote/{token}/message 发消息 → 假 LLM 回显 "RE:..." 到达 state turns
#        f. POST decision 无 pending approval → 409 透传
#        g. GET qr.svg → 200 且 content-type image/svg+xml 且 body 以 <svg 开头
#        h. DELETE /remote/{token} → 200；再 GET state → 404；重复 DELETE 仍 200（幂等）
#      （前端 RemoteModal 证据在 vitest RemoteModal.test.tsx / Assistant.test.tsx）
#
# 一键复跑: scripts/verify_m181.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8187}"
FAKE_PORT="${FLIPPED_FAKE_LLM_PORT:-8188}"
SRV_PID=""; FAKE_PID=""
cleanup() {
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
  [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null; wait "$FAKE_PID" 2>/dev/null
  rm -rf "$TMPD"
}
trap cleanup EXIT
export FLIPPED_PROJECTS_DIR="$TMPD/projects"
export FLIPPED_DB="$TMPD/flipped.db"
export FLIPPED_SESSION_STORE_PATH="$TMPD/.sessions.json"
export FLIPPED_REMOTE_DB="$TMPD/remote_tokens.json"

echo "== M181-1 单测（24 例） =="
PYTHONPATH=src $PY -m pytest tests/test_m181_remote.py -q \
  && pass "M181 单测全绿" || bad "M181 单测失败"

echo "== M181-2 真实后端黑盒 E2E（uvicorn :${PORT} + 假 LLM :${FAKE_PORT}） =="

# 假 OpenAI 兼容端点：回显 "RE:<user 文本>"（chat 通路，与 verify_m180.sh 同款）
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
                user = str(m.get("content", ""))
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
$PY "$TMPD/fake_llm.py" "${FAKE_PORT}" &
FAKE_PID=$!

FLIPPED_USE_LOCAL_WORKER=1 \
FLIPPED_MODEL_BASE_URL="http://127.0.0.1:${FAKE_PORT}/v1" \
FLIPPED_CHAT_STREAM=0 FLIPPED_RAG_AUTO=0 FLIPPED_MAP_AUTO=0 FLIPPED_RULES_AUTO=0 \
FLIPPED_TASKS=0 \
PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!

ready=0
for _ in $(seq 1 60); do
  ok1=$(curl -sf "http://127.0.0.1:${PORT}/api/v1/health" -o /dev/null 2>&1 && echo 1)
  if [ "${ok1}" = "1" ]; then ready=1; break; fi
  sleep 0.5
done
if [ "${ready}" != "1" ]; then
  bad "后端 30s 内未就绪"
  echo ""; echo "M181 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" \
PAGE_BASE="http://127.0.0.1:${PORT}" ${PY} - <<'PYEOF'
import json, os, sys, time, urllib.request, urllib.error

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
PAGE = os.environ["PAGE_BASE"]
fails = []

def call(method, path, body=None, raw=False, full_url=None):
    url = full_url if full_url else BASE + path
    req = urllib.request.Request(
        url, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
            ctype = r.headers.get("Content-Type", "")
            return r.status, (data if raw else json.loads(data or b"{}")), ctype
    except urllib.error.HTTPError as e:
        data = e.read()
        try:
            return e.code, (data if raw else json.loads(data or b"{}")), e.headers.get("Content-Type", "")
        except json.JSONDecodeError:
            return e.code, data, e.headers.get("Content-Type", "")

def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" ({detail})" if detail and not cond else ""))
    if not cond:
        fails.append(name)

# a. 无会话 → POST /remote/sessions 400
st, body, _ = call("POST", "/remote/sessions", {})
check("a.无会话 POST /remote/sessions → 400",
      st == 400, detail=f"HTTP {st} {json.dumps(body)[:160] if isinstance(body, dict) else body[:160]}")

# b. 建 chat 会话 → issue 200 字段齐
st, body, _ = call("POST", "/assistant/sessions", {"title": "m181-e2e", "mode": "chat"})
assert st in (200, 201), f"建会话 HTTP {st}: {json.dumps(body)[:160]}"
sid = body["id"]
st, body, _ = call("POST", "/remote/sessions", {})
check("b.建会话后 POST /remote/sessions → 200 字段齐",
      st == 200 and body.get("session_id") == sid and len(body.get("token", "")) >= 24
      and "/remote/" in body.get("url", "") and body.get("qr_url", "").startswith("/api/v1/remote/")
      and body.get("expires_at", 0) > time.time() and "host_note" in body,
      detail=f"HTTP {st} {json.dumps(body)[:200]}")
token = body.get("token", "")

# c. 移动页 200 含 token；无效 token 404 含「链接已失效」
st, page, ctype = call("GET", "", raw=True, full_url=f"{PAGE}/remote/{token}")
page_txt = page.decode("utf-8", "replace")
check("c.GET /remote/{token} → 200 且页面含 token",
      st == 200 and token in page_txt and "text/html" in ctype,
      detail=f"HTTP {st} ctype={ctype}")
st, page, _ = call("GET", "", raw=True, full_url=f"{PAGE}/remote/not-a-real-token-xyz")
check("c2.无效 token 页面 → 404 含「链接已失效」",
      st == 404 and "链接已失效" in page.decode("utf-8", "replace"),
      detail=f"HTTP {st}")

# d. state 200 键齐
st, body, _ = call("GET", f"/remote/{token}/state")
check("d.GET state → 200（turns/pending_approval/mode/status 键齐）",
      st == 200 and body.get("session_id") == sid and body.get("mode") == "chat"
      and isinstance(body.get("turns"), list) and "pending_approval" in body,
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:200]}")

# e. 远程发消息 → 假 LLM 回显到达 state turns
MARK = "M181MOBILE_手机补需求"
st, body, _ = call("POST", f"/remote/{token}/message", {"text": MARK})
check("e1.POST /remote/{token}/message → 200 返回 task_id",
      st == 200 and bool(body.get("task_id")),
      detail=f"HTTP {st} {json.dumps(body)[:160]}")
seen_user = seen_asst = False
for _ in range(40):
    time.sleep(0.5)
    st, body, _ = call("GET", f"/remote/{token}/state")
    if st != 200:
        continue
    for t in body.get("turns", []):
        if t.get("role") == "user" and MARK in (t.get("text") or ""):
            seen_user = True
        if t.get("role") == "assistant" and (t.get("text") or "").startswith("RE:") and MARK in (t.get("text") or ""):
            seen_asst = True
    if seen_user and seen_asst:
        break
check("e2.假 LLM 回显 RE: 到达 state turns（user+assistant 双到）",
      seen_user and seen_asst, detail=f"user={seen_user} asst={seen_asst}")

# f. decision 无 pending approval → 409 透传
st, body, _ = call("POST", f"/remote/{token}/decision", {"decision": "approve"})
check("f.POST decision 无 pending approval → 409 透传",
      st == 409, detail=f"HTTP {st} {json.dumps(body)[:160] if isinstance(body, dict) else body[:160]}")

# g. qr.svg 200 image/svg+xml 以 <svg 开头
st, svg, ctype = call("GET", f"/remote/{token}/qr.svg", raw=True)
check("g.GET qr.svg → 200 image/svg+xml 且 body 以 <svg 开头",
      st == 200 and "image/svg+xml" in ctype and svg.decode("utf-8", "replace").lstrip().startswith("<svg"),
      detail=f"HTTP {st} ctype={ctype} head={svg[:40]!r}")

# h. DELETE → state 404；重复 DELETE 幂等 200
st, body, _ = call("DELETE", f"/remote/{token}")
ok_del = st == 200 and isinstance(body, dict) and body.get("ok") is True
st2, _, _ = call("GET", f"/remote/{token}/state")
st3, body3, _ = call("DELETE", f"/remote/{token}")
check("h.DELETE 撤销 → state 404；重复 DELETE 仍 200（幂等）",
      ok_del and st2 == 404 and st3 == 200,
      detail=f"del={st} state={st2} del2={st3}")

print("")
if fails:
    print("M181 黑盒失败项: " + ", ".join(fails))
    sys.exit(1)
print("  ✅ 黑盒 E2E 全绿")
PYEOF
[ $? -eq 0 ] && pass "黑盒 E2E 全绿" || bad "黑盒 E2E 有失败"

echo ""
if [ $fail -eq 0 ]; then
  echo "M181（移动远程控制）验收：通过 ✅"
else
  echo "M181 验收：有未通过 ❌"
fi
exit $fail
