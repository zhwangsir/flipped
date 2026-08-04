#!/usr/bin/env bash
# M179 验收 — AI 代码评审（Review 面板「AI 评审」：diff → LLM → 结构化 findings）。
#
#   1) pytest 单测：test_m179_review.py（20 例：prompt 组装 untracked/截断注记/
#      空 files/只输出 JSON 指令/fence 包裹；parse fence/裸 JSON/{"findings":[]}/
#      缺 path 跳过/severity 归一/line 非法/完全无 JSON 抛错/空 findings；
#      端点空 diff 短路/findings 结构/解析失败 502/LLM 异常 502/开关 404/无项目 400）
#   2) 真实后端黑盒 E2E：真 uvicorn（FLIPPED_USE_LOCAL_WORKER=1 + 假 OpenAI server，
#      不烧真 LLM），tmp 隔离（FLIPPED_PROJECTS_DIR/FLIPPED_DB）：
#        a. POST /projects 建项目 → git init + 初始 commit
#        b. 工作区干净 → POST /project/review → findings=[] 且 note 非空（不调 LLM）
#        c. 改 tracked + 加 untracked → POST /project/review →
#           findings 结构/path 对应/severity 非法归一为 medium/缺 path 项被跳过/
#           files_reviewed==2/model 非空（假 LLM 返回 fence 包裹 JSON 顺带验剥 fence）
#        d. 假 LLM 对含 PARSE_FAIL 路径的 prompt 返回垃圾 → 502
#        e. 第二实例 FLIPPED_AI_REVIEW=0 → POST /project/review → 404
#      （前端按钮/findings 行内渲染/清除/error 红字证据在 vitest ContextPanel.test.tsx）
#
# 一键复跑: scripts/verify_m179.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8181}"
PORT_OFF="${FLIPPED_VERIFY_PORT_OFF:-8182}"
FAKE_PORT="${FLIPPED_FAKE_LLM_PORT:-8183}"
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

echo "== M179-1 单测（20 例） =="
PYTHONPATH=src $PY -m pytest tests/test_m179_review.py -q \
  && pass "M179 单测全绿" || bad "M179 单测失败"

echo "== M179-2 真实后端黑盒 E2E（uvicorn :${PORT} + 假 LLM :${FAKE_PORT}） =="

# 假 OpenAI 兼容端点：POST /v1/chat/completions
#   prompt 含 "PARSE_FAIL" → 返回非 JSON 垃圾（验 502 解析失败通路）
#   否则 → 返回 ```json fence 包裹的 findings（含非法 severity/缺 path 项，验归一与跳过）
cat > "$TMPD/fake_llm.py" <<'FAKEEOF'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

FINDINGS = [
    {"path": "base.txt", "line": 3, "severity": "high",
     "message": "第三行追加未做边界校验", "suggestion": "加长度上限"},
    {"path": "base.txt", "line": 1, "severity": "CRITICAL",
     "message": "非法 severity 应归一为 medium"},
    {"line": 5, "severity": "low", "message": "缺 path 应被跳过"},
    {"path": "new_note.md", "severity": "low", "message": "标题层级建议"},
]

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        prompt = "\n".join(str(m.get("content", "")) for m in body.get("messages", []))
        if "PARSE_FAIL" in prompt:
            content = "这不是 JSON，评审员临时罢工了。"
        else:
            content = "```json\n" + json.dumps(FINDINGS, ensure_ascii=False) + "\n```"
        out = {"choices": [{"message": {"role": "assistant", "content": content}}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 8}}
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
PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!

# 第二实例：FLIPPED_AI_REVIEW=0（开关 404 通路）
FLIPPED_USE_LOCAL_WORKER=1 \
FLIPPED_MODEL_BASE_URL="http://127.0.0.1:${FAKE_PORT}/v1" \
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
  echo ""; echo "M179 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" \
FLIPPED_BASE_OFF="http://127.0.0.1:${PORT_OFF}" \
PROJ_DIR="$TMPD/projects/m179demo" ${PY} - <<'PYEOF'
import json, os, subprocess, sys, urllib.request, urllib.error

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
BASE_OFF = os.environ["FLIPPED_BASE_OFF"] + "/api/v1"
PROJ = os.environ["PROJ_DIR"]
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

def git(*args):
    r = subprocess.run(["git", *args], cwd=PROJ, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout

# a. 建项目并设为活动
st, body = call("POST", "/projects", {"name": "m179demo"})
check("a.POST /projects 建项目并设为活动",
      st in (200, 201) and body.get("name") == "m179demo",
      detail=f"HTTP {st} {json.dumps(body)[:120]}")

# git init + 初始 commit
git("init")
git("config", "user.email", "m179@test.local")
git("config", "user.name", "m179")
with open(os.path.join(PROJ, "base.txt"), "w") as fh:
    fh.write("line1\nline2\n")
git("add", ".")
git("commit", "-m", "init")

# b. 工作区干净 → findings=[] 且 note 非空（短路不调 LLM）
st, body = call("POST", "/project/review", {})
check("b.空 diff → 200 findings=[] 且 note 非空",
      st == 200 and body.get("findings") == [] and bool(body.get("note"))
      and body.get("files_reviewed") == 0,
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:160]}")

# 造变更：改 tracked + 新 untracked
with open(os.path.join(PROJ, "base.txt"), "w") as fh:
    fh.write("line1\nline2\nline3-modified\n")
with open(os.path.join(PROJ, "new_note.md"), "w") as fh:
    fh.write("# 新文件\nalpha\nbeta\n")

# c. POST /project/review → findings 结构 / severity 归一 / 缺 path 跳过 / files_reviewed
st, body = call("POST", "/project/review", {})
findings = body.get("findings", [])
check("c1.有 diff → 200 且 files_reviewed==2 且 model 非空",
      st == 200 and body.get("files_reviewed") == 2 and bool(body.get("model")),
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:200]}")
check("c2.缺 path 项被跳过 → 4 条假 findings 收敛为 3 条",
      len(findings) == 3,
      detail=f"findings={json.dumps(findings, ensure_ascii=False)[:200]}")
high = [f for f in findings if f.get("severity") == "high"]
med = [f for f in findings if f.get("severity") == "medium"]
check("c3.severity 规范化：high 保留 1 条，CRITICAL 归一为 medium 1 条",
      len(high) == 1 and len(med) == 1,
      detail=f"findings={json.dumps(findings, ensure_ascii=False)[:200]}")
check("c4.path 对应 diff 文件且字段完整（line/message/suggestion）",
      all(f.get("path") in ("base.txt", "new_note.md") for f in findings)
      and high and high[0].get("line") == 3 and bool(high[0].get("message"))
      and high[0].get("suggestion") == "加长度上限",
      detail=f"findings={json.dumps(findings, ensure_ascii=False)[:200]}")

# d. 假 LLM 返回垃圾 → 502（新建 PARSE_FAIL 路径触发）
with open(os.path.join(PROJ, "PARSE_FAIL.txt"), "w") as fh:
    fh.write("trigger\n")
st, body = call("POST", "/project/review", {})
check("d.解析失败 → 502 且 detail 非空（绝不伪造 findings）",
      st == 502 and bool(body.get("detail")),
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:160]}")

# e. FLIPPED_AI_REVIEW=0 实例 → 404
st, body = call("POST", "/project/review", {}, base=BASE_OFF)
check("e.FLIPPED_AI_REVIEW=0 → 404", st == 404, detail=f"HTTP {st}")

print("")
if fails:
    print("M179 黑盒失败项: " + ", ".join(fails))
    sys.exit(1)
print("  ✅ 黑盒 E2E 全绿")
PYEOF
[ $? -eq 0 ] && pass "黑盒 E2E 全绿" || bad "黑盒 E2E 有失败"

echo ""
if [ $fail -eq 0 ]; then
  echo "M179（AI 代码评审）验收：通过 ✅"
else
  echo "M179 验收：有未通过 ❌"
fi
exit $fail
