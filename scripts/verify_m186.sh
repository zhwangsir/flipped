#!/usr/bin/env bash
# M186 验收 — Review 面板增强（评审持久化 + findings 跳转 + 仅变更过滤 + AI commit message）。
#
#   1) pytest 单测：test_m186_review_persist.py（38 例：save/list/load/cap 删旧/坏文件跳过/
#      id 穿越防护/原子写/build_commit_prompt 预算/parse_commit_reply 边界/端点落盘与 404）
#   2) 前端定向 vitest：store.test.tsx + ContextPanel.test.tsx（历史载入回放/commit 生成复制/
#      review-jump 跳转/line-target 高亮/filterTreeByPaths/仅变更 toggle）
#   3) 真实后端黑盒：真 uvicorn ×2（:PORT 正常 + :PORT_OFF 置 FLIPPED_AI_REVIEW=0）
#      + 假 OpenAI server（按 user prompt 路由：含「审查」→ findings JSON；含「commit」→ 提交文本）：
#        a. 建项目 → git init + 基线 commit + 造变更 → POST /project/review
#           → 200 + review_id 非空 + findings 来自假 LLM + reviews 目录落盘
#        b. GET /project/reviews 列表含该 id（无 findings 全文）；
#           GET /project/reviews/{id} 完整 findings；未知 id → 404
#        c. POST /project/commit_message → 假 LLM 文本原样返回；
#           commit 掉变更后（干净工作区）→ message="" + note="工作区干净"
#        d. FLIPPED_AI_REVIEW=0 实例：review/reviews/reviews/{id}/commit_message 全 404
#
# 一键复跑: scripts/verify_m186.sh
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
export FLIPPED_REVIEWS_DIR="$TMPD/reviews"

echo "== M186-1 单测（38 例） =="
PYTHONPATH=src $PY -m pytest tests/test_m186_review_persist.py -q \
  && pass "M186 单测全绿" || bad "M186 单测失败"

echo "== M186-2 前端定向 vitest =="
(cd console && npx vitest run src/store.test.tsx src/components/ContextPanel.test.tsx --reporter=dot >/dev/null 2>&1) \
  && pass "前端 store+ContextPanel 定向全绿" || bad "前端定向测试失败"

echo "== M186-3 真实后端黑盒 E2E（uvicorn :${PORT} + 开关实例 :${PORT_OFF} + 假 LLM :${FAKE_PORT}） =="

# 假 OpenAI 兼容端点：按 user prompt 路由——含「审查」→ findings JSON；含「commit」→ 提交文本
cat > "$TMPD/fake_llm.py" <<'FAKEEOF'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

FINDINGS = json.dumps([
    {"path": "app.py", "line": 2, "severity": "high",
     "message": "可能除零", "suggestion": "加判零保护"},
    {"path": "app.py", "line": None, "severity": "low",
     "message": "缺模块文档", "suggestion": None},
])
COMMIT = "feat(app): 新增除法入口\n\n- app.py 增加 div 函数"

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        user = ""
        for m in body.get("messages", []):
            if m.get("role") == "user":
                user = str(m.get("content", ""))
        content = COMMIT if "commit" in user else FINDINGS
        out = {"choices": [{"message": {"role": "assistant", "content": content}}],
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
FLIPPED_CHAT_STREAM=0 FLIPPED_RAG_AUTO=0 FLIPPED_MAP_AUTO=0 \
PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!

FLIPPED_USE_LOCAL_WORKER=1 \
FLIPPED_MODEL_BASE_URL="http://127.0.0.1:${FAKE_PORT}/v1" \
FLIPPED_CHAT_STREAM=0 FLIPPED_RAG_AUTO=0 FLIPPED_MAP_AUTO=0 \
FLIPPED_AI_REVIEW=0 \
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
  echo ""; echo "M186 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" \
FLIPPED_BASE_OFF="http://127.0.0.1:${PORT_OFF}" \
PROJ_DIR="$TMPD/projects/m186demo" \
REVIEWS_DIR="$TMPD/reviews" ${PY} - <<'PYEOF'
import json, os, subprocess, sys, urllib.request, urllib.error

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
BASE_OFF = os.environ["FLIPPED_BASE_OFF"] + "/api/v1"
PROJ = os.environ["PROJ_DIR"]
RDIR = os.environ["REVIEWS_DIR"]
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

# a. 建项目 + git 基线 + 造变更
st, body = call("POST", "/projects", {"name": "m186demo"})
assert st in (200, 201), f"建项目 HTTP {st}: {json.dumps(body)[:160]}"

def git(*args):
    r = subprocess.run(["git", *args], cwd=PROJ, capture_output=True, text=True)
    assert r.returncode == 0, f"git {args}: {r.stderr[:120]}"

git("init"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
git("add", "-A"); git("commit", "-m", "baseline", "--allow-empty")
with open(os.path.join(PROJ, "app.py"), "w") as fh:
    fh.write("def div(a, b):\n    return a / b\n")
git("add", "app.py"); git("commit", "-m", "add div")
with open(os.path.join(PROJ, "app.py"), "a") as fh:
    fh.write("\nPI = 3\n")   # 未提交变更 → git diff HEAD 非空

# a1. POST /project/review → 200 + review_id + findings 来自假 LLM + 落盘
st, body = call("POST", "/project/review", {})
check("a1. review 200 + review_id 非空 + findings 两条",
      st == 200 and body.get("review_id") and len(body.get("findings", [])) == 2,
      f"HTTP {st}: {json.dumps(body, ensure_ascii=False)[:200]}")
rid = body.get("review_id") or ""
proj_slug = body.get("review_id") and "m186demo" or "m186demo"
rfile = os.path.join(RDIR, proj_slug, f"{rid}.json") if rid else ""
check("a2. reviews 目录落盘文件存在", bool(rfile) and os.path.isfile(rfile), rfile)

# b1. GET /project/reviews 列表含该 id（轻量无 findings）
st, body = call("GET", "/project/reviews")
entries = body.get("reviews", [])
hit = [e for e in entries if e.get("id") == rid]
check("b1. 列表含该 id 且轻量（无 findings 全文）",
      st == 200 and len(hit) == 1 and "findings" not in hit[0]
      and hit[0].get("findings_count") == 2,
      f"HTTP {st}: {json.dumps(body, ensure_ascii=False)[:200]}")
# b2. 详情完整 findings
st, body = call("GET", f"/project/reviews/{rid}")
check("b2. 详情含完整 findings（可能除零/high/app.py:2）",
      st == 200 and body.get("id") == rid
      and any(f.get("message") == "可能除零" and f.get("line") == 2
              for f in body.get("findings", [])),
      f"HTTP {st}: {json.dumps(body, ensure_ascii=False)[:200]}")
# b3. 未知 id → 404
st, _ = call("GET", "/project/reviews/20990101T000000_deadbeef")
check("b3. 未知 id → 404", st == 404, f"HTTP {st}")

# c1. POST /project/commit_message → 假 LLM 文本原样
st, body = call("POST", "/project/commit_message", {})
check("c1. commit_message 200 + conventional 文本 + files_count=1",
      st == 200 and body.get("message", "").startswith("feat(app):")
      and body.get("files_count") == 1,
      f"HTTP {st}: {json.dumps(body, ensure_ascii=False)[:200]}")
# c2. commit 掉变更 → 干净工作区 → note
git("add", "-A"); git("commit", "-m", "wip")
st, body = call("POST", "/project/commit_message", {})
check("c2. 干净工作区 → message=\"\" + note=工作区干净",
      st == 200 and body.get("message") == "" and body.get("note") == "工作区干净",
      f"HTTP {st}: {json.dumps(body, ensure_ascii=False)[:200]}")
# c3. 干净工作区 review → findings=[] review_id=None
st, body = call("POST", "/project/review", {})
check("c3. 干净工作区 review → findings=[] review_id=None",
      st == 200 and body.get("findings") == [] and body.get("review_id") is None,
      f"HTTP {st}: {json.dumps(body, ensure_ascii=False)[:200]}")

# d. FLIPPED_AI_REVIEW=0 实例四端点全 404
for name, method, path in [
    ("review", "POST", "/project/review"),
    ("reviews 列表", "GET", "/project/reviews"),
    ("reviews 详情", "GET", f"/project/reviews/{rid}"),
    ("commit_message", "POST", "/project/commit_message"),
]:
    st, _ = call(method, path, {} if method == "POST" else None, base=BASE_OFF)
    check(f"d. 开关关闭实例 {name} → 404", st == 404, f"HTTP {st}")

if fails:
    print("\n黑盒失败项: " + ", ".join(fails))
    sys.exit(1)
print("\n黑盒全部通过 ✅")
PYEOF
[ $? -eq 0 ] && pass "真实后端黑盒全过" || bad "真实后端黑盒失败"

echo ""
if [ $fail -eq 0 ]; then echo "M186 验收：全部通过 ✅"; else echo "M186 验收：有未通过 ❌"; exit 1; fi
