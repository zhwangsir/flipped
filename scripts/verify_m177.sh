#!/usr/bin/env bash
# M177 验收 — Review 面板强化（逐文件 diff 审查 + 逐文件回滚，对标 ZCode Review/rewind）。
#
#   1) pytest 单测：test_m177_review.py（12 例：diff 含 untracked/行数/二进制/gitignore、
#      revert tracked 改动还原/tracked 删除恢复/untracked 删除/穿越 403/目录 422/
#      未知 404/FLIPPED_REVIEW=0 404/staging area 不被触碰）
#   2) 真实后端黑盒 E2E：真 uvicorn（本里程碑不碰 LLM，无需假 server），
#      POST /projects 建项目后 git init + 初始 commit → 改 tracked + 加 untracked 文本/
#      二进制/gitignore 排除文件 → GET /project/diff 断言四类可见性 →
#      POST /project/revert 逐文件回滚断言 restored/deleted 与文件系统事实 →
#      路径穿越 403、未知文件 404。
#      （前端徽标/占位/行内确认撤销证据在 vitest ContextPanel.test.tsx）
#
# 一键复跑: scripts/verify_m177.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8178}"
SRV_PID=""
cleanup() {
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
  rm -rf "$TMPD"
}
trap cleanup EXIT
export FLIPPED_PROJECTS_DIR="$TMPD/projects"
export FLIPPED_DB="$TMPD/flipped.db"

echo "== M177-1 单测（12 例） =="
PYTHONPATH=src $PY -m pytest tests/test_m177_review.py -q \
  && pass "M177 单测全绿" || bad "M177 单测失败"

echo "== M177-2 真实后端黑盒 E2E（uvicorn :${PORT}，无 LLM 依赖） =="

PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!

ready=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/api/v1/health" -o /dev/null 2>&1; then ready=1; break; fi
  sleep 0.5
done
if [ "${ready}" != "1" ]; then
  bad "后端 30s 内未就绪"
  echo ""; echo "M177 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" PROJ_DIR="$TMPD/projects/m177demo" ${PY} - <<'PYEOF'
import json, os, subprocess, sys, urllib.request, urllib.error

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

def git(*args):
    r = subprocess.run(["git", *args], cwd=PROJ, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout

# 1. 建项目并设为活动
st, body = call("POST", "/projects", {"name": "m177demo"})
check("a.POST /projects 建项目并设为活动", st in (200, 201) and body.get("name") == "m177demo",
      detail=f"HTTP {st} {json.dumps(body)[:120]}")

# 2. git init + 初始 commit（tracked 文件 base.txt）
git("init")
git("config", "user.email", "m177@test.local")
git("config", "user.name", "m177")
with open(os.path.join(PROJ, "base.txt"), "w") as fh:
    fh.write("line1\nline2\n")
with open(os.path.join(PROJ, ".gitignore"), "w") as fh:
    fh.write("ignored.txt\n")
git("add", ".")
git("commit", "-m", "init")

# 3. 造变更：改 tracked / 删 tracked 另建 / 新 untracked 文本 / 新二进制 / gitignore 排除
with open(os.path.join(PROJ, "base.txt"), "w") as fh:
    fh.write("line1\nline2\nline3-modified\n")
with open(os.path.join(PROJ, "new_note.md"), "w") as fh:
    fh.write("# 新文件\nalpha\nbeta\n")
with open(os.path.join(PROJ, "blob.bin"), "wb") as fh:
    fh.write(b"\x00\x01\x02binary")
with open(os.path.join(PROJ, "ignored.txt"), "w") as fh:
    fh.write("不应出现\n")

# 4. GET /project/diff：四类可见性
st, body = call("GET", "/project/diff")
check("b.GET /project/diff 200", st == 200, detail=f"HTTP {st}")
files = {f["path"]: f for f in body.get("files", [])}
check("c.tracked 修改 base.txt 在列且有 diff 行",
      "base.txt" in files and len(files["base.txt"].get("lines", [])) > 0
      and not files["base.txt"].get("untracked"),
      detail=json.dumps(body)[:200])
check("d.untracked 文本 new_note.md 在列：untracked=True 且 added==3",
      files.get("new_note.md", {}).get("untracked") is True
      and files["new_note.md"].get("added") == 3,
      detail=json.dumps(files.get("new_note.md"))[:160])
check("e.untracked 二进制 blob.bin：binary=True 且 added==0",
      files.get("blob.bin", {}).get("binary") is True
      and files["blob.bin"].get("added") == 0,
      detail=json.dumps(files.get("blob.bin"))[:160])
check("f.gitignore 排除的 ignored.txt 不在列", "ignored.txt" not in files)

# 5. revert tracked modified → restored + 内容回 HEAD
st, body = call("POST", "/project/revert", {"path": "base.txt"})
with open(os.path.join(PROJ, "base.txt")) as fh:
    content = fh.read()
check("g.revert tracked modified → restored 且内容回 HEAD",
      st == 200 and body.get("action") == "restored" and content == "line1\nline2\n",
      detail=f"HTTP {st} {json.dumps(body)[:120]} content={content!r}")

# 6. 删 tracked 文件 → revert → restored + 文件恢复
os.remove(os.path.join(PROJ, "base.txt"))
st, body = call("POST", "/project/revert", {"path": "base.txt"})
check("h.revert tracked deleted → restored 且文件恢复",
      st == 200 and body.get("action") == "restored"
      and os.path.isfile(os.path.join(PROJ, "base.txt")),
      detail=f"HTTP {st} {json.dumps(body)[:120]}")

# 7. revert untracked → deleted + 文件消失
st, body = call("POST", "/project/revert", {"path": "new_note.md"})
check("i.revert untracked → deleted 且文件消失",
      st == 200 and body.get("action") == "deleted"
      and not os.path.exists(os.path.join(PROJ, "new_note.md")),
      detail=f"HTTP {st} {json.dumps(body)[:120]}")

# 8. 路径穿越 → 403
st, body = call("POST", "/project/revert", {"path": "../outside.txt"})
check("j.revert 路径穿越 → 403", st == 403, detail=f"HTTP {st}")

# 9. 未知文件 → 404
st, body = call("POST", "/project/revert", {"path": "ghost.txt"})
check("k.revert 未知文件 → 404", st == 404, detail=f"HTTP {st}")

# 10. revert 后 diff 不再含已处理文件（blob.bin 仍在列）
st, body = call("GET", "/project/diff")
paths = [f["path"] for f in body.get("files", [])]
check("l.revert 后 diff：base.txt/new_note.md 消失，blob.bin 仍在",
      "base.txt" not in paths and "new_note.md" not in paths and "blob.bin" in paths,
      detail=json.dumps(paths)[:160])

print("")
if fails:
    print("M177 黑盒失败项: " + ", ".join(fails))
    sys.exit(1)
print("  ✅ 黑盒 E2E 全绿")
PYEOF
[ $? -eq 0 ] && pass "黑盒 E2E 全绿" || bad "黑盒 E2E 有失败"

echo ""
if [ $fail -eq 0 ]; then
  echo "M177（Review 面板强化）验收：通过 ✅"
else
  echo "M177 验收：有未通过 ❌"
fi
exit $fail
