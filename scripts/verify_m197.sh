#!/usr/bin/env bash
# M197 验收 — registry P2 批消化（性能三连 + 安全闸 + 局域网一键 + classify 升级）。
#
#   1) pytest 单测：tests/test_m197_p2_batch.py（19 例）
#   2) 场景 a（M197.1 消化 L-M171-2）：monorepo 子目录摄入——
#      _git_files 经真 git 进程只列 sub/ 内文件（pathspec 作用域端到端结果证据）
#   3) 场景 c（M197.3 消化 L-M189-1）：假 git shim 让 status --untracked-files=all
#      真超时（sleep>5s）→ 降级 normal 重试出指纹（计时 >=5s 铁证）；
#      FLIPPED_FP_UNTRACKED=normal 快路径直出指纹（计时 <5s 证明未碰 all）
#   4) 场景 f（M197.6 消化 L-M184-1）：临时 registry 跑 classify --stats——
#      打分制多命中者胜（「性能 超时…验证」归性能而非安全）+ 未命中率输出
#   5) 真后端黑盒 E2E（uvicorn cwd=$TMPD + 假 OpenAI server 记录请求体）：
#      b)（M197.2 消化 L-M172-3）并发 3 chat 会话 RAG 注入回归——
#         假 LLM 捕获 system 含 RAG header + marker；rag_chunks>=1
#      d)（M197.4 消化 L-M188-2）goal chat 模式 verify_cmd=python3 dump 脚本——
#         子进程 env 不含后端敏感变量 FLIPPED_FAKE_SECRET（白名单净化铁证），
#         PATH 保留；goal judge 事件 source=verify_cmd 且 achieved
#   6) 场景 e（M197.5 消化 L-M181-4）：BIND_HOST=0.0.0.0 起真后端 →
#      curl LAN IP /api/v1/health 200（局域网可达铁证；无 LAN 则跳过不 fail）
#
# 一键复跑: bash scripts/verify_m197.sh
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PY="$([ -x .venv/bin/python ] && echo "$ROOT/.venv/bin/python" || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8198}"
FAKE_PORT="${FLIPPED_FAKE_LLM_PORT:-8199}"
LAN_PORT="${FLIPPED_LAN_PORT:-8297}"
SRV_PID=""; FAKE_PID=""; LAN_PID=""
cleanup() {
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
  [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null; wait "$FAKE_PID" 2>/dev/null
  [ -n "$LAN_PID" ] && kill "$LAN_PID" 2>/dev/null; wait "$LAN_PID" 2>/dev/null
  if [ "${FLIPPED_KEEP_TMPD:-0}" = "1" ]; then
    echo "  · 现场保留: $TMPD"
  else
    rm -rf "$TMPD"
  fi
}
trap cleanup EXIT

echo "== M197-1 单测（19 例：pathspec/to_thread/指纹降级/rlimit+env/BIND_ALL/classify） =="
PYTHONPATH=src $PY -m pytest tests/test_m197_p2_batch.py -q \
  && pass "M197 单测全绿" || bad "M197 单测失败"

# ====================================================================
echo "== M197-2 场景 a：_git_files 子目录 pathspec 端到端（真 git 进程） =="
MONO="$TMPD/mono"
mkdir -p "$MONO/sub/deep" "$MONO/other"
git -C "$MONO" init -q
git -C "$MONO" config user.email t@example.com
git -C "$MONO" config user.name t
echo "x=1" > "$MONO/a.py"
echo "# b" > "$MONO/sub/b.md"
echo "# c" > "$MONO/sub/deep/c.md"
echo "# d" > "$MONO/other/d.md"
git -C "$MONO" add . && git -C "$MONO" commit -qm init
FLIPPED_MONO="$MONO" PYTHONPATH=src $PY - <<'PYEOF'
import os, sys
from pathlib import Path
from rag.ingest import _git_files
# macOS /var → /private/var symlink：_git_files 内 resolve，断言侧同步 resolve 保前缀一致
mono = Path(os.environ["FLIPPED_MONO"]).resolve()
files = _git_files(mono / "sub", {".md"})
assert files is not None, "git repo 内不应回退 None"
names = sorted(p.relative_to(mono).as_posix() for p in files)
assert names == ["sub/b.md", "sub/deep/c.md"], f"只列 sub/ 内文件（含深层）: {names}"
top = _git_files(mono, {".md", ".py"})
assert top is not None
top_names = sorted(p.relative_to(mono).as_posix() for p in top)
assert top_names == ["a.py", "other/d.md", "sub/b.md", "sub/deep/c.md"], top_names
print("  子目录:", names, " topless:", len(top_names), "文件")
PYEOF
[ $? -eq 0 ] && pass "场景 a：子目录只列 sub/ 内文件，toplevel 全量语义不变" \
             || bad "场景 a 失败"

# ====================================================================
echo "== M197-3 场景 c：_git_fingerprint all 超时降级 normal（假 git shim 真超时） =="
REAL_GIT="$(command -v git)"
mkdir -p "$TMPD/bin"
cat > "$TMPD/bin/git" <<SHIM
#!/usr/bin/env bash
# 假 git：参数含 --untracked-files=all 时 sleep 10s（调用方 timeout=5 必超时）
for a in "\$@"; do
  [ "\$a" = "--untracked-files=all" ] && sleep 10
done
exec "$REAL_GIT" "\$@"
SHIM
chmod +x "$TMPD/bin/git"
FLIPPED_MONO="$MONO" FLIPPED_SHIM_BIN="$TMPD/bin" PYTHONPATH=src $PY - <<'PYEOF'
import os, time
from pathlib import Path
os.environ["PATH"] = os.environ["FLIPPED_SHIM_BIN"] + os.pathsep + os.environ["PATH"]
from api import project_map
mono = Path(os.environ["FLIPPED_MONO"])

# 默认 all 首试：shim sleep 10 > timeout 5 → 降级 normal 重试成功
os.environ.pop("FLIPPED_FP_UNTRACKED", None)
t0 = time.time()
fp = project_map._git_fingerprint(mono)
dt = time.time() - t0
assert fp is not None and len(fp) == 16, f"降级重试应出指纹: {fp}"
assert dt >= 5.0, f"应经历 all 真超时（>=5s）: {dt:.1f}s"
print(f"  降级路径: 指纹 {fp} 耗时 {dt:.1f}s（all 超时→normal 成功）")

# env 快路径：normal 直出，不碰 all（<5s 证明未走 shim sleep）
os.environ["FLIPPED_FP_UNTRACKED"] = "normal"
t0 = time.time()
fp2 = project_map._git_fingerprint(mono)
dt2 = time.time() - t0
assert fp2 is not None and len(fp2) == 16, f"normal 快路径应出指纹: {fp2}"
assert dt2 < 5.0, f"快路径不应碰 all（<5s）: {dt2:.1f}s"
print(f"  快路径: 指纹 {fp2} 耗时 {dt2:.1f}s（未碰 all）")
PYEOF
[ $? -eq 0 ] && pass "场景 c：all 超时降级 normal 出指纹；env 快路径不碰 all" \
             || bad "场景 c 失败"

# ====================================================================
echo "== M197-4 场景 f：classify 打分制 + --stats 未命中率 =="
cat > "$TMPD/reg.json" <<'JSON'
{"version": 1, "updated_at": "", "limitations": [
  {"id": "L-M999-1", "milestone": "M999",
   "text": "性能 超时 问题，需要 验证 才能关闭", "category": "未分类",
   "impact": "", "priority": "P2", "difficulty": "中",
   "status": "open", "resolution_note": "", "target": ""},
  {"id": "L-M999-2", "milestone": "M999",
   "text": "zzyyxx 无任何规则关键词的表述", "category": "未分类",
   "impact": "", "priority": "P2", "difficulty": "中",
   "status": "open", "resolution_note": "", "target": ""}
]}
JSON
OUT=$($PY scripts/limitations_report.py classify --registry "$TMPD/reg.json" --stats 2>&1)
echo "$OUT" | grep -q "classified 1 entries" \
  && echo "$OUT" | grep -q "未命中率 50.0%" \
  && pass "场景 f：--stats 输出未命中率（1 命中/1 未命中=50%）" \
  || bad "场景 f：--stats 输出异常: $OUT"
FLIPPED_REG="$TMPD/reg.json" $PY - <<'PYEOF'
import json, os
reg = json.load(open(os.environ["FLIPPED_REG"], encoding="utf-8"))
lims = {l["id"]: l for l in reg["limitations"]}
# 打分制铁证：「安全」命中 1 词（验证），「性能」命中 2 词（性能/超时）→ 多命中者胜。
# 旧「按序首命中即停」逻辑会误判为「安全」（规则表安全在性能前）。
assert lims["L-M999-1"]["category"] == "性能", \
    f"打分制应多命中者胜（性能 2 > 安全 1）: {lims['L-M999-1']['category']}"
assert lims["L-M999-2"]["category"] == "未分类", "无命中应保持未分类"
print("  打分制: L-M999-1 →", lims["L-M999-1"]["category"],
      "| L-M999-2 →", lims["L-M999-2"]["category"])
PYEOF
[ $? -eq 0 ] && pass "场景 f：打分制多命中者胜（性能>安全），无命中保持未分类" \
             || bad "场景 f：打分制断言失败"

# ====================================================================
echo "== M197-5 真后端黑盒 E2E（uvicorn :${PORT} + 假 LLM :${FAKE_PORT}） =="

# ---- 前置 1：RAG 预摄入 marker（独立进程同 RAG_DB_DIR，mock embedding 保 hermetic）----
RAG_DB_DIR="$TMPD/ragdb" RAG_EMBEDDING=mock PYTHONPATH=src $PY - <<PYEOF
from rag.ingest import ingest_text
ids = ingest_text(
    "M197RagMarker197 是 M197 黑盒验收埋入的唯一标记片段，用于证明 to_thread 化后 RAG 注入不破。",
    metadata={"project": "m197proj", "source": "m197.md"})
assert ids, "ingest 应返回 id"
print("  预摄入完成", ids[0][:8])
PYEOF

# ---- 前置 2：verify_cmd dump 脚本（场景 d：子进程 env 落盘）----
cat > "$TMPD/dump_env.py" <<'PYEOF'
import json, os, sys
json.dump(dict(os.environ), open(sys.argv[1], "w", encoding="utf-8"))
PYEOF

# ---- 端口占用预检：残留进程会让健康检查假通过打到旧后端（2026-08-06 实测踩过）----
for p in "${PORT}" "${FAKE_PORT}" "${LAN_PORT}"; do
  if nc -z 127.0.0.1 "${p}" 2>/dev/null; then
    echo "  ✗ 端口 ${p} 已被占用（疑似残留/他项目进程）——先清理或 FLIPPED_VERIFY_PORT/FLIPPED_FAKE_LLM_PORT/FLIPPED_LAN_PORT 换端口"
    exit 1
  fi
done

# ---- 前置 3：假 OpenAI 兼容端点（记录全部请求到 llm_requests.jsonl）----
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

# ---- 起服（cwd=${TMPD}；FLIPPED_FAKE_SECRET 为场景 d 敏感变量探针）----
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
FLIPPED_RAG_DEBUG="${FLIPPED_RAG_DEBUG:-0}" \
FLIPPED_TASKS_SCAN_S=1 \
FLIPPED_FAKE_SECRET="topsecret-m197" \
AWS_SECRET_ACCESS_KEY="fake-aws-m197" \
PYTHONPATH="$ROOT/src" ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning \
  > "$TMPD/backend.log" 2>&1 &
SRV_PID=$!
cd "$ROOT"
ready=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/api/v1/health" -o /dev/null 2>&1; then ready=1; break; fi
  sleep 0.5
done
if [ "${ready}" != "1" ]; then
  bad "后端 30s 内未就绪"
  echo ""; echo "M197 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" \
FLIPPED_TMPD="$TMPD" \
${PY} - <<'PYEOF'
import json, os, sys, threading, time, urllib.request, urllib.error
from pathlib import Path

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
TMPD = Path(os.environ["FLIPPED_TMPD"])
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

def events(sid):
    st, body = call("GET", f"/sessions/{sid}/events")
    return body if st == 200 else []

def wait_terminal(sid, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st, sess = call("GET", f"/sessions/{sid}")
        if st == 200 and sess.get("status") in ("done", "error", "review"):
            return sess.get("status")
        time.sleep(0.4)
    return "timeout"

# ============ 场景 b：并发 3 chat 会话 RAG 注入回归（to_thread 化后功能不破） ============
sids = []
for i in range(3):
    st, body = call("POST", "/assistant/sessions", {"title": f"m197-rag-{i}", "mode": "chat"})
    sids.append(body.get("id", "") if st == 200 else "")
check("b.建 3 个 chat 会话", all(sids), detail=f"sids={sids}")

send_errs = []
def _send(sid, i):
    try:
        st, _ = call("POST", f"/assistant/sessions/{sid}/messages",
                     {"text": f"M197RagMarker197 是什么（并发{i}）"})
        if st != 200:
            send_errs.append(f"sid{i} HTTP {st}")
    except Exception as e:  # noqa: BLE001
        send_errs.append(f"sid{i} {e}")

threads = [threading.Thread(target=_send, args=(sid, i)) for i, sid in enumerate(sids)]
t0 = time.time()
for t in threads:
    t.start()
for t in threads:
    t.join()
check("b.3 会话并发发送均 200", not send_errs, detail=";".join(send_errs))
statuses = [wait_terminal(sid) for sid in sids]
dt = time.time() - t0
check("b.3 会话并发跑完 done（event loop 未被 RAG IO 卡死）",
      all(s == "done" for s in statuses), detail=f"statuses={statuses} dt={dt:.1f}s")
rag_ks = []
for sid in sids:
    ks = [e.get("payload", {}).get("rag_chunks", 0) for e in events(sid)
          if e.get("type") == "message" and e.get("agent") == "worker"]
    rag_ks.append(max(ks, default=0))
check("b.每会话应答 rag_chunks >= 1", all(k >= 1 for k in rag_ks),
      detail=f"rag_chunks={rag_ks}")
log = TMPD / "llm_requests.jsonl"
reqs = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] \
    if log.is_file() else []
hits = [r for r in reqs if "M197RagMarker197 是什么" in r.get("user", "")]
check("b.假 LLM 捕获 3 条提问请求", len(hits) >= 3, detail=f"hits={len(hits)}")
sys_ok = sum(1 for r in hits
             if RAG_HEADER in r.get("system", "")
             and "M197RagMarker197 是 M197 黑盒验收埋入的唯一标记片段" in r.get("system", ""))
check("b.每条 system 含 RAG header + marker（to_thread 化后注入语义不变）",
      sys_ok >= 3, detail=f"sys_ok={sys_ok}/3")

# ============ 场景 d：goal chat 模式 verify_cmd host env 净化 ============
st, body = call("POST", "/assistant/sessions", {"title": "m197-verify", "mode": "chat"})
sid_d = body.get("id", "") if st == 200 else ""
check("d.建 chat 会话", bool(sid_d), detail=f"HTTP {st}")
env_out = TMPD / "verify_env.json"
verify_cmd = ["python3", str(TMPD / "dump_env.py"), str(env_out)]
st, body = call("POST", f"/assistant/sessions/{sid_d}/goal", {
    "objective": "m197 verify_cmd env 净化黑盒",
    "max_iterations": 2,  # i==max_iter 会提前 exhausted 不跑 verify，须 >=2
    "verify_cmd": verify_cmd})
check("d. POST /goal（显式 verify_cmd 过安全闸）→ 200",
      st == 200, detail=f"HTTP {st} body={json.dumps(body, ensure_ascii=False)[:160]}")
check("d. goal 跑完 done（verify exit 0 → achieved）",
      wait_terminal(sid_d) == "done")
goal_judges = [e for e in events(sid_d)
               if e.get("type") == "goal" and e.get("payload", {}).get("phase") == "judge"]
src = goal_judges[-1].get("payload", {}).get("source") if goal_judges else None
achieved = goal_judges[-1].get("payload", {}).get("achieved") if goal_judges else None
check("d. judge 事件 source=verify_cmd 且 achieved=true",
      src == "verify_cmd" and achieved is True,
      detail=f"source={src} achieved={achieved}")
if env_out.is_file():
    env_d = json.loads(env_out.read_text(encoding="utf-8"))
    check("d. 子进程 env 不含 FLIPPED_FAKE_SECRET / AWS_SECRET_ACCESS_KEY（净化铁证）",
          "FLIPPED_FAKE_SECRET" not in env_d and "AWS_SECRET_ACCESS_KEY" not in env_d,
          detail=f"keys={len(env_d)}")
    check("d. 子进程 env 保留 PATH（白名单基础项）", bool(env_d.get("PATH")))
else:
    check("d. verify_cmd 子进程 env 落盘文件存在", False, detail=str(env_out))

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "黑盒场景 b/d 全绿" \
  || { bad "黑盒场景有失败"; echo "--- backend.log 尾 50 行 ---"; tail -50 "$TMPD/backend.log"; }

# ====================================================================
echo "== M197-6 场景 e：BIND_HOST=0.0.0.0 → LAN IP 可达（消化 L-M181-4） =="
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
if [ -z "$LAN_IP" ]; then
  echo "  · 无 LAN IP（en0 离线），跳过不 fail"
else
  # 黑盒目的：验证「绑 0.0.0.0 则 LAN 可达」这一网络事实。
  # 脚本的 FLIPPED_BIND_ALL 条件求值逻辑已由单测文本断言覆盖，这里直接显式 0.0.0.0。
  cd "$TMPD"
  FLIPPED_PROJECTS_DIR="$TMPD/projects-lan" \
  FLIPPED_DB="$TMPD/flipped-lan.db" \
  FLIPPED_SESSION_STORE_PATH="$TMPD/sessions-lan.json" \
  FLIPPED_TASKS_PATH="$TMPD/tasks-lan.json" \
  FLIPPED_WORKER_RULES_PATH="$TMPD/rules-lan.json" \
  FLIPPED_MOCK_ORCHESTRATOR=1 \
  FLIPPED_MODEL_BASE_URL="http://127.0.0.1:${FAKE_PORT}/v1" \
  FLIPPED_LAN_PORT="${LAN_PORT}" \
  PYTHONPATH="$ROOT/src" ${PY} - <<'PYEOF' &
import os, uvicorn
uvicorn.run("api.main:app", host="0.0.0.0",
            port=int(os.environ.get("FLIPPED_LAN_PORT", "8200")), log_level="warning")
PYEOF
  LAN_PID=$!
  cd "$ROOT"
  lan_ready=0
  for _ in $(seq 1 40); do
    if curl -sf "http://127.0.0.1:${LAN_PORT}/api/v1/health" -o /dev/null 2>&1; then lan_ready=1; break; fi
    sleep 0.5
  done
  if [ "$lan_ready" != "1" ]; then
    bad "场景 e：LAN 后端 20s 内未就绪"
  elif curl -sf -m 5 "http://${LAN_IP}:${LAN_PORT}/api/v1/health" -o /dev/null 2>&1; then
    pass "场景 e：绑 0.0.0.0 后 LAN IP ${LAN_IP}:${LAN_PORT} /health 可达（局域网铁证）"
  else
    bad "场景 e：LAN IP ${LAN_IP}:${LAN_PORT} 不可达"
  fi
fi

echo ""
if [ ${fail} -eq 0 ]; then echo "M197 验收：全部通过 ✅"; else echo "M197 验收：有未通过 ❌"; exit 1; fi
