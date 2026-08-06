#!/usr/bin/env bash
# M196 验收 — 测试覆盖黑盒批 + 评审历史项目资产化。
#
#   1) pytest 单测：tests/test_m196_reviews_dir.py（12 例）
#        - _reviews_dir 三级解析（env > {root}/.flipped/reviews > data/reviews）
#        - migrate_legacy_reviews 一次性 move + 幂等 + fail-open
#        - 端点级：无 env 评审落项目资产位置 / legacy 迁移后列表可见
#        - RAG_EMBEDDING=mock 短路 SentenceTransformerEmbeddings
#   2) 真实后端黑盒 E2E（真 uvicorn cwd=$TMPD 隔离 data/ + 假 OpenAI server 记录请求体）：
#        e) 预置 legacy data/reviews/<proj>/old.json → GET /project/reviews →
#           旧记录可见且 legacy 目录被 move 消失（一次性迁移铁证）
#        a) agent 会话（MOCK_ORCHESTRATOR 确定性 done）→ snapshot 事件
#           hash 经 git cat-file -t == commit、head == HEAD → 手动改 file.txt →
#           编辑重跑 → 200 restored=true、file.txt 回 HEAD、truncated>=2、重跑再到 done
#        b) POST /tasks（mode=agent, once, now+2s, scan=1s）→ 新会话含 snapshot 事件
#           hash/head 经 git 校验 → 会话到终态
#        c) 预摄入 RAG marker（独立进程同 RAG_DB_DIR + RAG_EMBEDDING=mock）→
#           chat 问 marker → 假 LLM 捕获 system 含 RAG_CONTEXT_HEADER + marker 文本；
#           应答 payload.rag_chunks >= 1
#        d) 弄脏工作区 → POST /project/review → 200 review_id 非空 →
#           落盘 {proj}/.flipped/reviews/<name>/<id>.json；GET 列表/详情一致
#
# 一键复跑: bash scripts/verify_m196.sh
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PY="$([ -x .venv/bin/python ] && echo "$ROOT/.venv/bin/python" || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8196}"
FAKE_PORT="${FLIPPED_FAKE_LLM_PORT:-8197}"
SRV_PID=""; FAKE_PID=""
cleanup() {
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
  [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null; wait "$FAKE_PID" 2>/dev/null
  rm -rf "$TMPD"
}
trap cleanup EXIT

echo "== M196-1 单测（reviews_dir 三级解析 / 迁移 / RAG mock 开关） =="
PYTHONPATH=src $PY -m pytest tests/test_m196_reviews_dir.py -q \
  && pass "M196 单测全绿" || bad "M196 单测失败"

echo "== M196-2 真实后端黑盒 E2E（uvicorn :${PORT} + 假 LLM :${FAKE_PORT}） =="

# ---- 前置 1：tmp git 源仓库（open 时拷进 FLIPPED_PROJECTS_DIR）----
PROJ="m196proj"
SRC_REPO="$TMPD/src_repo/$PROJ"
mkdir -p "$SRC_REPO"
git -C "$SRC_REPO" init -q
git -C "$SRC_REPO" config user.email t@example.com
git -C "$SRC_REPO" config user.name t
echo "v1-m196" > "$SRC_REPO/file.txt"
git -C "$SRC_REPO" add .
git -C "$SRC_REPO" commit -qm init

# ---- 前置 2：RAG 预摄入（独立进程，同 RAG_DB_DIR，RAG_EMBEDDING=mock 保 hermetic）----
RAG_DB_DIR="$TMPD/ragdb" RAG_EMBEDDING=mock PYTHONPATH=src $PY - <<PYEOF
from rag.ingest import ingest_text
ids = ingest_text(
    "M196RagMarker196 是 M196 黑盒验收埋入的唯一标记片段，用于证明 chat RAG 真接线。",
    metadata={"project": "$PROJ", "source": "m196.md"})
assert ids, "ingest 应返回 id"
print("  预摄入完成", ids[0][:8])
PYEOF

# ---- 前置 3：legacy 评审记录（cwd=$TMPD 起服后 data/ 即 $TMPD/data）----
mkdir -p "$TMPD/data/reviews/$PROJ"
cat > "$TMPD/data/reviews/$PROJ/20260101T000000_legacy1.json" <<JSON
{"id": "20260101T000000_legacy1", "ts": "2026-01-01T00:00:00+00:00",
 "project": "$PROJ", "model": "legacy-model", "files_reviewed": 1,
 "findings_count": 0, "findings": []}
JSON

# ---- 假 OpenAI 兼容端点：记录全部请求到 $TMPD/llm_requests.jsonl ----
# - 含 ```diff（评审/commit prompt 特征）→ 返回 []（空 findings）
# - 其余 chat → 即时回显 RE:<user>
cat > "$TMPD/fake_llm.py" <<'FAKEEOF'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG = sys.argv[2]

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        msgs = body.get("messages", [])
        system = next((str(m.get("content", "")) for m in msgs if m.get("role") == "system"), "")
        user = next((m.get("content", "") for m in msgs if m.get("role") == "user"), "")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"system": system, "user": user if isinstance(user, str) else "PARTS"},
                               ensure_ascii=False) + "\n")
        joined = system + "\n" + (user if isinstance(user, str) else "")
        if "```diff" in joined:
            content = "[]"
        else:
            content = "RE:" + (user if isinstance(user, str) else "PARTS")[:200]
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
$PY "$TMPD/fake_llm.py" "${FAKE_PORT}" "$TMPD/llm_requests.jsonl" &
FAKE_PID=$!

# ---- 起服（cwd=${TMPD}：data/reviews 指向 $TMPD/data，不碰真仓库）----
cd "$TMPD"
FLIPPED_PROJECTS_DIR="$TMPD/projects" \
FLIPPED_DB="$TMPD/flipped.db" \
FLIPPED_SESSION_STORE_PATH="$TMPD/sessions.json" \
FLIPPED_TASKS_PATH="$TMPD/scheduled_tasks.json" \
FLIPPED_WORKER_RULES_PATH="$TMPD/worker_rules.json" \
FLIPPED_MOCK_ORCHESTRATOR=1 \
FLIPPED_USE_LOCAL_WORKER=1 \
FLIPPED_MODEL_BASE_URL="http://127.0.0.1:${FAKE_PORT}/v1" \
FLIPPED_CHAT_STREAM=0 FLIPPED_MAP_AUTO=0 \
FLIPPED_RAG_AUTO=1 RAG_DB_DIR="$TMPD/ragdb" RAG_EMBEDDING=mock \
FLIPPED_TASKS_SCAN_S=1 \
PYTHONPATH="$ROOT/src" ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!
cd "$ROOT"
ready=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/api/v1/health" -o /dev/null 2>&1; then ready=1; break; fi
  sleep 0.5
done
if [ "${ready}" != "1" ]; then
  bad "后端 30s 内未就绪"
  echo ""; echo "M196 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" \
FLIPPED_TMPD="$TMPD" FLIPPED_PROJ="$PROJ" FLIPPED_SRC_REPO="$SRC_REPO" \
${PY} - <<'PYEOF'
import json, os, subprocess, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
TMPD = Path(os.environ["FLIPPED_TMPD"])
PROJ = os.environ["FLIPPED_PROJ"]
LEGACY = TMPD / "data" / "reviews" / PROJ
RAG_HEADER = "以下是用户项目知识库的检索结果"
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

def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True)

def events(sid):
    st, body = call("GET", f"/sessions/{sid}/events")
    return body if st == 200 else []

def wait_terminal(sid, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st, sess = call("GET", f"/sessions/{sid}")
        if st == 200 and sess.get("status") in ("done", "error", "review"):
            return sess.get("status")
        time.sleep(0.4)
    return "timeout"

def snapshot_events(sid):
    return [e for e in events(sid) if e.get("type") == "snapshot"]

def assert_snapshot_valid(sid, root, tag):
    snaps = snapshot_events(sid)
    check(f"{tag}.事件流含 snapshot 事件", len(snaps) >= 1, detail=f"n={len(snaps)}")
    if not snaps:
        return
    snap, head = snaps[0]["payload"].get("snapshot"), snaps[0]["payload"].get("head")
    t = git(root, "cat-file", "-t", snap or "")
    check(f"{tag}.snapshot hash 经 git cat-file -t == commit",
          t.returncode == 0 and t.stdout.strip() == "commit",
          detail=f"hash={snap} out={t.stdout.strip()}{t.stderr.strip()}")
    real_head = git(root, "rev-parse", "HEAD").stdout.strip()
    check(f"{tag}.snapshot.head == rev-parse HEAD", head == real_head,
          detail=f"{head} vs {real_head}")

# ============ 打开项目（后续所有场景前提） ============
st, proj = call("POST", "/project/open", {"path": os.environ["FLIPPED_SRC_REPO"]})
HOST = Path(proj.get("host", "")) if st == 200 else Path("/nonexistent")
check("open. POST /project/open → 200 且拷入项目主目录",
      st == 200 and HOST.is_dir() and HOST.name == PROJ,
      detail=f"HTTP {st} host={proj.get('host')}")

# ============ 场景 e：legacy 评审一次性迁移 ============
st, body = call("GET", "/project/reviews")
ids = [r.get("id") for r in body.get("reviews", [])] if st == 200 else []
check("e. GET /project/reviews → 200 且 legacy 旧记录可见",
      st == 200 and "20260101T000000_legacy1" in ids,
      detail=f"HTTP {st} ids={ids}")
migrated = HOST / ".flipped" / "reviews" / PROJ / "20260101T000000_legacy1.json"
check("e. legacy 目录已 move 消失且记录落项目资产位置",
      not LEGACY.exists() and migrated.is_file(),
      detail=f"legacy_exists={LEGACY.exists()} migrated={migrated.is_file()}")
st, body = call("GET", "/project/reviews")  # 二次调用幂等不炸
check("e. 二次 GET 幂等（记录仍在，不重复迁移）",
      st == 200 and "20260101T000000_legacy1" in [r.get("id") for r in body.get("reviews", [])])

# ============ 场景 a：agent 编辑重跑 git restore 真实黑盒 ============
st, body = call("POST", "/assistant/sessions", {"title": "m196-agent", "mode": "agent"})
sid_a = body.get("id", "")
check("a.建 agent 会话", st == 200 and sid_a, detail=f"HTTP {st}")
st, _ = call("POST", f"/assistant/sessions/{sid_a}/messages", {"text": "m196 agent 首轮"})
check("a.发送首轮消息 200", st == 200, detail=f"HTTP {st}")
check("a.首轮跑完 done（mock orchestrator 确定性）",
      wait_terminal(sid_a) == "done")
assert_snapshot_valid(sid_a, HOST, "a")

uid = next((e["id"] for e in events(sid_a)
            if e.get("type") == "message" and e.get("agent") == "user"), "")
(HOST / "file.txt").write_text("worker-dirty\n")  # 模拟 worker 改动
st, body = call("POST", f"/assistant/sessions/{sid_a}/messages/{uid}/edit",
                {"text": "m196 改后重跑"})
check("a.编辑重跑 200 且 restored=true 且 truncated>=2",
      st == 200 and body.get("restored") is True and body.get("truncated", 0) >= 2,
      detail=f"HTTP {st} body={json.dumps(body, ensure_ascii=False)[:160]}")
content = (HOST / "file.txt").read_text().strip()
check("a.编辑后 file.txt 回滚到 HEAD 内容", content == "v1-m196",
      detail=f"content={content!r}")
check("a.重跑再到终态 done", wait_terminal(sid_a) == "done")

# ============ 场景 b：定时任务 agent 模式 git snapshot 黑盒 ============
run_at = (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()
st, task = call("POST", "/tasks", {
    "title": "m196-定时agent", "prompt": "m196 cron agent 快照探测",
    "mode": "agent", "kind": "once", "run_at": run_at})
check("b. POST /tasks mode=agent → 201", st == 201 and bool(task.get("id")),
      detail=f"HTTP {st}")
sid_b = ""
t0 = time.time()
while time.time() - t0 < 15:
    st, sessions = call("GET", "/sessions")
    if st == 200 and isinstance(sessions, list):
        hit = [s for s in sessions if s.get("title") == "m196-定时agent"]
        if hit:
            sid_b = hit[0]["id"]
            break
    time.sleep(0.5)
check("b. 15s 内 scheduler 自动建会话（标题=任务标题）", bool(sid_b))
if sid_b:
    assert_snapshot_valid(sid_b, HOST, "b")
    check("b. 会话到终态", wait_terminal(sid_b) in ("done", "error", "review"),
          detail=f"status={wait_terminal(sid_b, 1)}")

# ============ 场景 c：chat RAG 注入真接线黑盒 ============
st, body = call("POST", "/assistant/sessions", {"title": "m196-rag", "mode": "chat"})
sid_c = body.get("id", "")
check("c.建 chat 会话", st == 200 and sid_c, detail=f"HTTP {st}")
st, _ = call("POST", f"/assistant/sessions/{sid_c}/messages",
             {"text": "M196RagMarker196 是什么"})
check("c.发送 RAG 提问 200", st == 200, detail=f"HTTP {st}")
check("c.提问跑完 done", wait_terminal(sid_c) == "done")
assistant_msgs = [e for e in events(sid_c)
                  if e.get("type") == "message" and e.get("agent") == "worker"]
rag_k = max((e.get("payload", {}).get("rag_chunks", 0) for e in assistant_msgs), default=0)
check("c.应答 payload.rag_chunks >= 1", rag_k >= 1, detail=f"rag_chunks={rag_k}")
log = TMPD / "llm_requests.jsonl"
reqs = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] \
    if log.is_file() else []
hit = [r for r in reqs if "M196RagMarker196 是什么" in r.get("user", "")]
check("c.假 LLM 捕获到该提问请求", len(hit) >= 1, detail=f"reqs={len(reqs)}")
sys_hit = hit[-1]["system"] if hit else ""
check("c.system 含 RAG_CONTEXT_HEADER + marker 检索文本（真接线铁证）",
      RAG_HEADER in sys_hit and "M196RagMarker196 是 M196 黑盒验收埋入的唯一标记片段" in sys_hit,
      detail=f"system[:200]={sys_hit[:200]!r}")

# ============ 场景 d：评审历史项目资产化落盘 ============
(HOST / "file.txt").write_text("v2-review\n")  # 弄脏工作区
st, body = call("POST", "/project/review", {})
rid = body.get("review_id") if st == 200 else None
check("d. POST /project/review → 200 且 review_id 非空",
      st == 200 and isinstance(rid, str) and bool(rid),
      detail=f"HTTP {st} body={json.dumps(body, ensure_ascii=False)[:160]}")
if rid:
    f = HOST / ".flipped" / "reviews" / PROJ / f"{rid}.json"
    check("d. 评审记录落项目资产位置 {proj}/.flipped/reviews/<name>/<id>.json",
          f.is_file(), detail=str(f))
    st, lst = call("GET", "/project/reviews")
    ids = [r.get("id") for r in lst.get("reviews", [])] if st == 200 else []
    check("d. GET 列表含新评审（ts desc 首位）",
          st == 200 and ids and ids[0] == rid, detail=f"ids={ids[:3]}")
    st, detail_rec = call("GET", f"/project/reviews/{rid}")
    check("d. GET 详情与落盘一致（project/model/findings）",
          st == 200 and detail_rec.get("id") == rid
          and detail_rec.get("project") == PROJ
          and detail_rec.get("findings") == [],
          detail=f"HTTP {st}")

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "黑盒场景 a-e 全绿" || bad "黑盒场景有失败"

echo ""
if [ ${fail} -eq 0 ]; then echo "M196 验收：全部通过 ✅"; else echo "M196 验收：有未通过 ❌"; exit 1; fi
