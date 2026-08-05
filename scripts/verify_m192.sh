#!/usr/bin/env bash
# M192 验收 — 图像附件接入（chat/plan 多模态），消化 L-M175-1（P1）。
#
#   1) pytest 单测：tests/test_m192_attachments.py（契约校验/落盘/parts 组装/
#      vision 路由/attachments 端点/_events_to_turns 透传）
#   2) 真实后端黑盒 E2E（真 uvicorn + 假 OpenAI server，记录每次请求的 model+messages）：
#        a) chat 带 2 张图 → 200；假 LLM 收到 parts 数组（text+2×image_url，
#           data URL 头正确、base64 与发送字节一致），model=vision alias；
#           user message 事件 payload.attachments 元数据正确（不含 base64）；
#           history user turn 透传 attachments
#        b) agent 带图 → 422「仅 chat/plan」，事件流零污染
#        c) 单张解码后 >2MB → 422（detail 含 name）
#        d) 第 5 张 → 422（FLIPPED_IMG_MAX_COUNT=4）
#        e) GET /assistant/attachments/{sid}/{fname} 字节一致取回；
#           未知 session 404；非法字符/穿越 404
#        f) 无图消息回归：model=worker alias（Kimi-K2.7-Code），content 为纯 str
#
# 一键复跑: scripts/verify_m192.sh
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
export FLIPPED_DATA_DIR="$TMPD/data"

echo "== M192-1 单测（attachments 契约/落盘/parts/路由/端点/透传） =="
PYTHONPATH=src $PY -m pytest tests/test_m192_attachments.py -q \
  && pass "M192 单测全绿" || bad "M192 单测失败"

echo "== M192-2 真实后端黑盒 E2E（uvicorn :${PORT} + 假 LLM :${FAKE_PORT}） =="

# 假 OpenAI 兼容端点：
# - GET  /v1/models → 列出 vision 模型（让 resolve_vision_model_config 的 proxy 探测命中本假端点）
# - POST /v1/chat/completions → 逐条记录 {model, messages} 到 llm_log.jsonl，回显 RE:<文本>
VISION_MODEL="mlx-community/Qwen3-VL-4B-Instruct-4bit"
cat > "$TMPD/fake_llm.py" <<'FAKEEOF'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(sys.argv[1]); LOG = sys.argv[2]; VISION = sys.argv[3]

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            data = json.dumps({"object": "list", "data": [
                {"id": VISION, "object": "model"},
                {"id": "mlx-community/Kimi-K2.7-Code-4bit", "object": "model"},
            ]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data)
        else:
            self.send_response(404); self.end_headers()
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        with open(LOG, "a") as f:
            f.write(json.dumps({"model": body.get("model"),
                                "messages": body.get("messages", [])},
                               ensure_ascii=False) + "\n")
        user = ""
        for m in body.get("messages", []):
            if m.get("role") == "user":
                c = m.get("content", "")
                user = c if isinstance(c, str) else " ".join(
                    p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
        out = {"choices": [{"message": {"role": "assistant", "content": "RE:" + user[:200]}}],
               "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
        data = json.dumps(out, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)
    def log_message(self, *a):
        pass

HTTPServer(("127.0.0.1", PORT), H).serve_forever()
FAKEEOF
$PY "$TMPD/fake_llm.py" "${FAKE_PORT}" "$TMPD/llm_log.jsonl" "${VISION_MODEL}" &
FAKE_PID=$!

FLIPPED_USE_LOCAL_WORKER=1 \
LITELLM_BASE_URL="http://127.0.0.1:${FAKE_PORT}/v1" \
FLIPPED_MODEL_BASE_URL="http://127.0.0.1:${FAKE_PORT}/v1" \
FLIPPED_VISION_MODEL="${VISION_MODEL}" \
FLIPPED_CHAT_STREAM=0 FLIPPED_RAG_AUTO=0 FLIPPED_MAP_AUTO=0 FLIPPED_RULES_AUTO=0 \
PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!
ready=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/api/v1/health" -o /dev/null 2>&1; then ready=1; break; fi
  sleep 0.5
done
if [ "${ready}" != "1" ]; then
  bad "后端 30s 内未就绪"
  echo ""; echo "M192 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" \
FLIPPED_LLM_LOG="$TMPD/llm_log.jsonl" \
FLIPPED_VISION_MODEL_EXPECT="${VISION_MODEL}" \
${PY} - <<'PYEOF'
import base64, json, os, struct, sys, time, urllib.request, urllib.error, zlib

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
LOG = os.environ["FLIPPED_LLM_LOG"]
VISION = os.environ["FLIPPED_VISION_MODEL_EXPECT"]
WORKER = "mlx-community/Kimi-K2.7-Code-4bit"
fails = []

def call(method, path, body=None, raw=False):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
            return r.status, (data if raw else json.loads(data))
    except urllib.error.HTTPError as e:
        data = e.read()
        if raw:
            return e.code, data
        try:
            return e.code, json.loads(data or b"{}")
        except json.JSONDecodeError:
            return e.code, {"raw": data[:200].decode("utf-8", "replace")}

def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" ({detail})" if detail and not cond else ""))
    if not cond:
        fails.append(name)

def make_png(w, h, rgb):
    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

def llm_records():
    if not os.path.exists(LOG):
        return []
    with open(LOG) as f:
        return [json.loads(line) for line in f if line.strip()]

def wait_record(pred, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        for r in llm_records():
            if pred(r):
                return r
        time.sleep(0.4)
    return None

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
    return None

# ============ 场景 a：chat 带 2 张图 → 多模态 parts + vision 路由 ============
st, body = call("POST", "/assistant/sessions", {"title": "m192-img", "mode": "chat"})
sid_a = body.get("id", "")
check("a.建 chat 会话", st == 200 and sid_a, detail=f"HTTP {st}")

img_red = make_png(8, 8, (255, 0, 0))
img_blue = make_png(8, 8, (0, 0, 255))
b_red = base64.b64encode(img_red).decode()
b_blue = base64.b64encode(img_blue).decode()
st, body = call("POST", f"/assistant/sessions/{sid_a}/messages", {
    "text": "M192A 看图回答", "mode": "chat",
    "images": [
        {"name": "red.png", "media_type": "image/png", "data_base64": b_red},
        {"name": "blue.png", "media_type": "image/png", "data_base64": b_blue},
    ]})
check("a.带 2 图消息 200 + task_id", st == 200 and body.get("task_id"), detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")

rec = wait_record(lambda r: r.get("model") == VISION)
check("a.假 LLM 收到 vision model 请求（vision 路由生效）", rec is not None,
      detail=f"models={[r.get('model') for r in llm_records()]}")
if rec:
    contents = [m.get("content") for m in rec["messages"] if m.get("role") == "user"]
    content = contents[-1] if contents else None
    ok_struct = (isinstance(content, list) and len(content) == 3
                 and content[0].get("type") == "text" and "M192A 看图回答" in content[0].get("text", "")
                 and content[1].get("type") == "image_url" and content[2].get("type") == "image_url")
    check("a.user content 为 parts 数组 [text, image_url, image_url]", ok_struct,
          detail=json.dumps(content, ensure_ascii=False)[:160] if content else "none")
    if ok_struct:
        u1 = content[1]["image_url"]["url"]; u2 = content[2]["image_url"]["url"]
        check("a.image_url data URL 头正确且 base64 与发送字节一致",
              u1 == f"data:image/png;base64,{b_red}" and u2 == f"data:image/png;base64,{b_blue}",
              detail=f"u1[:60]={u1[:60]}")

st_final = wait_done(sid_a)
check("a.会话终态 done", st_final == "done", detail=f"status={st_final}")

user_ev = [e for e in events(sid_a)
           if e.get("type") == "message" and e.get("payload", {}).get("attachments")]
atts = user_ev[0]["payload"]["attachments"] if user_ev else []
check("a.user message 事件 payload.attachments 2 条元数据（name/media_type/path/bytes，无 base64）",
      len(atts) == 2
      and all(set(a.keys()) == {"name", "media_type", "path", "bytes"} for a in atts)
      and all(a["path"].startswith(sid_a + "/") for a in atts)
      and atts[0]["bytes"] == len(img_red) and atts[1]["bytes"] == len(img_blue),
      detail=json.dumps(atts, ensure_ascii=False)[:200])

st, hist = call("GET", f"/assistant/sessions/{sid_a}/history")
u_turn = [t for t in hist if t.get("role") == "user"] if st == 200 else []
check("a.history user turn 透传 attachments",
      bool(u_turn) and u_turn[0].get("attachments") and u_turn[0]["attachments"][0]["path"] == atts[0]["path"],
      detail=f"HTTP {st} turns={len(hist) if isinstance(hist, list) else 'n/a'}")

# ============ 场景 e：attachments 端点取回 + 防护 ============
if atts:
    fname0 = atts[0]["path"].split("/")[-1]
    st, data = call("GET", f"/assistant/attachments/{sid_a}/{fname0}", raw=True)
    check("e.GET attachments 200 且字节与发送一致", st == 200 and data == img_red,
          detail=f"HTTP {st} bytes={len(data) if isinstance(data, bytes) else 'n/a'}")
    st, _ = call("GET", "/assistant/attachments/no-such-session/x.png")
    check("e.未知 session → 404", st == 404, detail=f"HTTP {st}")
    st, _ = call("GET", f"/assistant/attachments/{sid_a}/bad%20name.png")
    check("e.非法字符文件名 → 404", st == 404, detail=f"HTTP {st}")
    st, _ = call("GET", f"/assistant/attachments/{sid_a}/..%2F..%2Fsecret")
    check("e.路径穿越 → 404", st == 404, detail=f"HTTP {st}")
else:
    check("e.前置 attachments 缺失，跳过取回断言", False, detail="atts 为空")

# ============ 场景 b：agent 带图 → 422 且事件流零污染 ============
st, body = call("POST", "/assistant/sessions", {"title": "m192-agent", "mode": "agent"})
sid_b = body.get("id", "")
st, body = call("POST", f"/assistant/sessions/{sid_b}/messages", {
    "text": "agent 带图", "mode": "agent",
    "images": [{"name": "red.png", "media_type": "image/png", "data_base64": b_red}]})
check("b.agent 带图 → 422「仅 chat/plan」",
      st == 422 and "chat/plan" in str(body.get("detail", "")),
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")
polluted = [e for e in events(sid_b) if e.get("type") == "message"]
check("b.422 时事件流零污染（无 user message 事件）", len(polluted) == 0,
      detail=f"message events={len(polluted)}")

# ============ 场景 c：单张超 2MB → 422（detail 含 name） ============
st, body = call("POST", "/assistant/sessions", {"title": "m192-big", "mode": "chat"})
sid_c = body.get("id", "")
big_b64 = base64.b64encode(b"\x00" * (2 * 1024 * 1024 + 16)).decode()
st, body = call("POST", f"/assistant/sessions/{sid_c}/messages", {
    "text": "超大图", "mode": "chat",
    "images": [{"name": "huge.png", "media_type": "image/png", "data_base64": big_b64}]})
check("c.单张 >2MB → 422 且 detail 含 name",
      st == 422 and "huge.png" in str(body.get("detail", "")),
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:140]}")

# ============ 场景 d：第 5 张 → 422 ============
st, body = call("POST", "/assistant/sessions", {"title": "m192-5img", "mode": "chat"})
sid_d = body.get("id", "")
five = [{"name": f"p{i}.png", "media_type": "image/png", "data_base64": b_red} for i in range(5)]
st, body = call("POST", f"/assistant/sessions/{sid_d}/messages", {
    "text": "五张图", "mode": "chat", "images": five})
check("d.第 5 张 → 422", st == 422,
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:140]}")

# ============ 场景 f：无图消息回归（worker 路由 + 纯 str content） ============
st, body = call("POST", "/assistant/sessions", {"title": "m192-plain", "mode": "chat"})
sid_f = body.get("id", "")
st, body = call("POST", f"/assistant/sessions/{sid_f}/messages", {
    "text": "M192F 纯文本回归", "mode": "chat"})
check("f.无图消息 200", st == 200 and body.get("task_id"), detail=f"HTTP {st}")
rec_f = wait_record(lambda r: r.get("model") == WORKER)
check("f.假 LLM 收到 worker model 请求（无图不走 vision 路由）", rec_f is not None,
      detail=f"models={[r.get('model') for r in llm_records()]}")
if rec_f:
    contents_f = [m.get("content") for m in rec_f["messages"] if m.get("role") == "user"]
    check("f.user content 为纯 str（原路径零变化）",
          bool(contents_f) and isinstance(contents_f[-1], str) and "M192F 纯文本回归" in contents_f[-1],
          detail=repr(contents_f[-1])[:120] if contents_f else "none")
check("f.会话终态 done", wait_done(sid_f) == "done")

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "黑盒场景 a-f 全绿" || bad "黑盒场景有失败"

echo ""
if [ ${fail} -eq 0 ]; then echo "M192 验收：全部通过 ✅"; else echo "M192 验收：有未通过 ❌"; exit 1; fi
