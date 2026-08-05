#!/usr/bin/env bash
# M193 验收 — 逐 hunk 拒绝（Review 面板），消化 L-M177-4（逐 hunk 接受/拒绝的拒绝侧）。
#
#   1) pytest 单测：tests/test_m193_hunk.py（split_patch_hunks 纯函数 / 契约校验 /
#      真 repo 端到端 2-hunk 逐个拒绝 / 越界 / 无变更 / 穿越 / 目录 / untracked /
#      staged 新文件 / FLIPPED_REVIEW=0 / git apply 失败→409 / 无项目→400）
#   2) 真实后端黑盒 E2E（真 uvicorn，无需假 LLM）：
#        a) git init 项目（30 行基线 commit），改第 3 行与第 27 行（2 个 hunk），
#           POST /project/open 设为活动项目
#        b) POST /project/revert-hunk {path, hunk_index:0} → 200 action=hunk_reverted；
#           hunk0 段回 HEAD、hunk1 段改动保留
#        c) GET /project/diff 重取 → 再拒剩余 hunk → 200；git diff HEAD 为空；
#           文件内容 == HEAD
#        d) hunk_index 越界 → 422（含「共 2 个 hunk」）/ 无变更文件 → 404 /
#           路径穿越 → 403 / untracked → 422（含「整文件回滚」）
#        e) GET /project/diff 契约回归：改动后 lines 含 type==hunk/add/del/ctx
#        f) 回归：整文件 POST /project/revert 对另一改动文件仍 200 action=restored
#
# 一键复跑: bash scripts/verify_m193.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8193}"
SRV_PID=""
cleanup() {
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
  rm -rf "$TMPD"
}
trap cleanup EXIT
export FLIPPED_PROJECTS_DIR="$TMPD/projects"
export FLIPPED_DB="$TMPD/flipped.db"
export FLIPPED_SESSION_STORE_PATH="$TMPD/sessions.json"
export FLIPPED_TASKS_PATH="$TMPD/scheduled_tasks.json"
export FLIPPED_WORKER_RULES_PATH="$TMPD/worker_rules.json"
export FLIPPED_DATA_DIR="$TMPD/data"

echo "== M193-1 单测（split_patch_hunks/契约/端到端/防护/409/400） =="
PYTHONPATH=src $PY -m pytest tests/test_m193_hunk.py -q \
  && pass "M193 单测全绿" || bad "M193 单测失败"

echo "== M193-2 真实后端黑盒 E2E（uvicorn :${PORT}） =="

# a 前置：在 FLIPPED_PROJECTS_DIR 下 git init 项目，30 行基线 commit
PROJ="$FLIPPED_PROJECTS_DIR/proj193"
mkdir -p "$PROJ"
PROJ="$(cd "$PROJ" && pwd -P)"  # /var → /private/var 符号链接归一（与 project_open resolve 对齐）
git -C "$PROJ" init -q
git -C "$PROJ" config user.email "m193@example.com"
git -C "$PROJ" config user.name "m193"
for i in $(seq 1 30); do printf 'line-%02d\n' "$i"; done > "$PROJ/file.txt"
echo "untouched" > "$PROJ/other.txt"
git -C "$PROJ" add . && git -C "$PROJ" commit -qm init

FLIPPED_USE_LOCAL_WORKER=1 \
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
  echo ""; echo "M193 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" \
FLIPPED_PROJ="$PROJ" \
${PY} - <<'PYEOF'
import json, os, subprocess, sys, urllib.request, urllib.error

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
PROJ = os.environ["FLIPPED_PROJ"]
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
        data = e.read()
        try:
            return e.code, json.loads(data or b"{}")
        except json.JSONDecodeError:
            return e.code, {"raw": data[:200].decode("utf-8", "replace")}

def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" ({detail})" if detail and not cond else ""))
    if not cond:
        fails.append(name)

def git(*args):
    return subprocess.run(["git", *args], cwd=PROJ, check=True,
                          capture_output=True, text=True).stdout

def read_lines(name):
    with open(os.path.join(PROJ, name)) as f:
        return f.read().splitlines()

def write_lines(name, lines):
    with open(os.path.join(PROJ, name), "w") as f:
        f.write("\n".join(lines) + "\n")

BASE_LINES = [f"line-{i:02d}" for i in range(1, 31)]

# ============ 场景 a：设活动项目 + 造 2 个 hunk 的改动 ============
st, body = call("POST", "/project/open", {"path": PROJ})
check("a.POST /project/open 设为活动项目", st == 200 and body.get("host") == PROJ,
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")

lines = BASE_LINES.copy()
lines[2] = "line-03-modified"    # 第 3 行
lines[26] = "line-27-modified"   # 第 27 行（远隔 → 2 个 hunk）
write_lines("file.txt", lines)
diff_out = git("diff", "HEAD", "--no-color", "--", "file.txt")
# 注意：hunk 头可能带 funcname 尾巴（"@@ ... @@ line-22"），必须按行首计数
hunk_n = sum(1 for l in diff_out.splitlines() if l.startswith("@@ "))
check("a.改动产出 2 个 hunk", hunk_n == 2, detail=f"hunks={hunk_n}")

# ============ 场景 d（先做非破坏性防护断言，此时为 2-hunk 状态） ============
st, body = call("POST", "/project/revert-hunk", {"path": "file.txt", "hunk_index": 99})
check("d.hunk_index=99 越界 → 422 且含「共 2 个 hunk」",
      st == 422 and "共 2 个 hunk" in str(body.get("detail", "")),
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")

st, body = call("POST", "/project/revert-hunk", {"path": "other.txt", "hunk_index": 0})
check("d.无变更 tracked 文件 → 404", st == 404,
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")

st, body = call("POST", "/project/revert-hunk", {"path": "../x", "hunk_index": 0})
check("d.路径穿越 → 403", st == 403,
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")

with open(os.path.join(PROJ, "untracked.txt"), "w") as f:
    f.write("new\n")
st, body = call("POST", "/project/revert-hunk", {"path": "untracked.txt", "hunk_index": 0})
check("d.untracked 文件 → 422 且含「整文件回滚」",
      st == 422 and "整文件回滚" in str(body.get("detail", "")),
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:120]}")
os.remove(os.path.join(PROJ, "untracked.txt"))

# ============ 场景 b：拒 hunk0 → hunk0 段回 HEAD、hunk1 段保留 ============
st, body = call("POST", "/project/revert-hunk", {"path": "file.txt", "hunk_index": 0})
check("b.POST revert-hunk hunk_index=0 → 200 action=hunk_reverted",
      st == 200 and body.get("action") == "hunk_reverted"
      and body.get("path") == "file.txt" and body.get("hunk_index") == 0
      and body.get("ok") is True,
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:160]}")
cur = read_lines("file.txt")
check("b.hunk0 段（第 3 行）已回 HEAD", cur[2] == "line-03", detail=cur[2])
check("b.hunk1 段（第 27 行）改动保留", cur[26] == "line-27-modified", detail=cur[26])

# ============ 场景 c：重取 diff → 再拒剩余 hunk → 工作区干净 ============
st, body = call("GET", "/project/diff")
check("c.GET /project/diff 重取 200", st == 200, detail=f"HTTP {st}")
st, body = call("POST", "/project/revert-hunk", {"path": "file.txt", "hunk_index": 0})
check("c.再拒剩余 hunk → 200 action=hunk_reverted",
      st == 200 and body.get("action") == "hunk_reverted",
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:160]}")
check("c.git diff HEAD 为空", git("diff", "HEAD").strip() == "",
      detail=git("diff", "HEAD")[:120])
check("c.文件内容 == HEAD", read_lines("file.txt") == BASE_LINES)

# ============ 场景 e：/project/diff 契约回归（hunk/add/del/ctx 四类行） ============
lines = BASE_LINES.copy()
lines[9] = "line-10-modified"    # 改第 10 行 → 单 hunk 含 del+add+ctx
write_lines("file.txt", lines)
st, body = call("GET", "/project/diff")
types = set()
if st == 200:
    for f in body.get("files", []):
        if f.get("path") == "file.txt":
            types = {l.get("type") for l in f.get("lines", [])}
check("e.GET /project/diff 契约回归：lines 含 hunk/add/del/ctx",
      st == 200 and {"hunk", "add", "del", "ctx"} <= types,
      detail=f"HTTP {st} types={sorted(types)}")

# ============ 场景 f：整文件 /project/revert 回归仍 200 restored ============
st, body = call("POST", "/project/revert", {"path": "file.txt"})
check("f.整文件 POST /project/revert → 200 action=restored",
      st == 200 and body.get("action") == "restored",
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:160]}")
check("f.revert 后文件 == HEAD 且 diff 为空",
      read_lines("file.txt") == BASE_LINES and git("diff", "HEAD").strip() == "")

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "黑盒场景 a-f 全绿" || bad "黑盒场景有失败"

echo ""
if [ ${fail} -eq 0 ]; then echo "M193 验收：全部通过 ✅"; else echo "M193 验收：有未通过 ❌"; exit 1; fi
