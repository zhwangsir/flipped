#!/usr/bin/env bash
# M189 验收 — 索引与地图新鲜度增强（chunk 残留清理 + git 指纹深层变更感知）。
#
#   1) pytest 单测：test_m189_rag_stale_cleanup.py（12 例）+ test_m189_map_fingerprint.py（11 例）
#   2) 真实后端黑盒 E2E（真 uvicorn，RAG_DB_DIR/项目目录全隔离）：
#        a) RAG chunk 残留清理：ingest 长文件（多 chunk）→ 改短重 ingest →
#           rag_query 命中只剩新 content_hash，旧 hash 零残留，旧文本标记检索不到
#        b) 项目地图 git 指纹：临时 git 项目建缓存 → 深层文件内容编辑 →
#           GET /project/map stale=True → regenerate → stale=False → 无变更再 GET 仍 False
#
# 一键复跑: scripts/verify_m189.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8188}"
SRV_PID=""
cleanup() {
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
  rm -rf "$TMPD"
}
trap cleanup EXIT
export FLIPPED_PROJECTS_DIR="$TMPD/projects"
export FLIPPED_DB="$TMPD/flipped.db"
export FLIPPED_SESSION_STORE_PATH="$TMPD/sessions.json"
export RAG_DB_DIR="$TMPD/ragdb"
# 地图缓存默认落仓库 data/project_maps（按项目名 keyed），不隔离会被上一轮残留污染 → 指到 TMPD
export FLIPPED_MAP_CACHE_DIR="$TMPD/mapcache"

echo "== M189-1 单测（stale cleanup 12 例 + map fingerprint 11 例） =="
PYTHONPATH=src $PY -m pytest tests/test_m189_rag_stale_cleanup.py tests/test_m189_map_fingerprint.py -q \
  && pass "M189 单测全绿" || bad "M189 单测失败"

echo "== M189-2 真实后端黑盒 E2E（uvicorn :${PORT}） =="

FLIPPED_USE_LOCAL_WORKER=1 \
FLIPPED_RAG_AUTO=0 FLIPPED_MAP_AUTO=0 \
PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!
ready=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/api/v1/health" -o /dev/null 2>&1; then ready=1; break; fi
  sleep 0.5
done
if [ "${ready}" != "1" ]; then
  bad "后端 30s 内未就绪"
  echo ""; echo "M189 验收：有未通过 ❌"; exit 1
fi

# ---------- 场景 a：RAG chunk 残留清理 ----------
FLIPPED_BASE="http://127.0.0.1:${PORT}" TMPD="$TMPD" ${PY} - <<'PYEOF'
import json, os, sys, urllib.request, urllib.error

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
TMPD = os.environ["TMPD"]
fails = []

def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}"); fails.append(name)

def call_tool(name, arguments):
    req = urllib.request.Request(
        f"{BASE}/mcp/tools/{name}/call",
        data=json.dumps({"arguments": arguments}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())

# 长文本：>1600 字符，结构化分块产出多 chunk；含旧文本唯一标记 OLDMARK
long_text = ("# 旧版本\nOLDMARK " + "甲乙丙丁戊己庚辛壬癸" * 120 + "\n\n# 第二节\n" + "子丑寅卯辰巳午未申酉" * 60)
short_text = "# 新版本\nNEWMARK 简短内容。"

docdir = os.path.join(TMPD, "docs")
os.makedirs(docdir, exist_ok=True)
doc = os.path.join(docdir, "a.md")

with open(doc, "w", encoding="utf-8") as f:
    f.write(long_text)
r1 = call_tool("rag_ingest", {"paths": [docdir], "project": "m189"})
ids1 = (r1.get("result") or {}).get("ingested_ids") or []
check("a1. 首次 ingest 多 chunk（>=2）", r1.get("ok") and len(ids1) >= 2, f"count={len(ids1)}")
hash1 = ids1[0].split(":")[0] if ids1 else ""

# 改短重 ingest → 旧 hash chunk 应全清
with open(doc, "w", encoding="utf-8") as f:
    f.write(short_text)
r2 = call_tool("rag_ingest", {"paths": [docdir], "project": "m189"})
ids2 = (r2.get("result") or {}).get("ingested_ids") or []
check("a2. 重 ingest 成功（1 chunk）", r2.get("ok") and len(ids2) == 1, f"count={len(ids2)}")

q = call_tool("rag_query", {"query": "内容", "n_results": 20, "project": "m189"})
results = (q.get("result") or {}).get("results") or []
hashes = {((it.get("metadata") or {}).get("content_hash")) for it in results}
texts = " ".join(str(it.get("text", "")) for it in results)
check("a3. 检索结果不含旧 content_hash", hash1 not in hashes, f"old={hash1} in {hashes}")
check("a4. 旧文本标记 OLDMARK 检索不到", "OLDMARK" not in texts)
check("a5. 新文本标记 NEWMARK 可检索", "NEWMARK" in texts)

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "场景 a（chunk 残留清理）全绿" || bad "场景 a（chunk 残留清理）有失败"

# ---------- 场景 b：项目地图 git 指纹深层变更感知 ----------
FLIPPED_BASE="http://127.0.0.1:${PORT}" TMPD="$TMPD" ${PY} - <<'PYEOF'
import json, os, subprocess, sys, time, urllib.request

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
TMPD = os.environ["TMPD"]
fails = []

def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} {detail}"); fails.append(name)

def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())

# 建项目（FLIPPED_PROJECTS_DIR 下）→ git init + 深层文件 + commit
name = "m189map"
r = post("/projects", {"name": name})
root = os.path.join(TMPD, "projects", name)
check("b1. 项目创建并成为活动项目", r.get("name") == name, json.dumps(r)[:200])

def git(*args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=10)

git("init", "-q")
os.makedirs(os.path.join(root, "src", "deep"), exist_ok=True)
with open(os.path.join(root, "src", "deep", "mod.py"), "w") as f:
    f.write("X = 1\n")
with open(os.path.join(root, "README.md"), "w") as f:
    f.write("# m189map\n")
git("add", "-A")
git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")

m1 = get("/project/map")["map"]
check("b2. 首次 GET 建缓存（from_cache=False, stale=False）",
      m1 is not None and m1["from_cache"] is False and m1["stale"] is False, json.dumps(m1)[:200] if m1 else "None")

m2 = get("/project/map")["map"]
check("b3. 二次 GET 命中缓存且不 stale", m2["from_cache"] is True and m2["stale"] is False)

# 深层文件内容编辑（顶层 mtime 不冒泡）→ git 指纹应判 stale
time.sleep(0.05)
with open(os.path.join(root, "src", "deep", "mod.py"), "w") as f:
    f.write("X = 2  # 深层内容编辑\n")
m3 = get("/project/map")["map"]
check("b4. 深层内容编辑 → stale=True（git 指纹感知）", m3["from_cache"] is True and m3["stale"] is True)

m4 = post("/project/map/regenerate", {})["map"]
check("b5. regenerate → stale=False", m4["stale"] is False and m4["from_cache"] is False)

m5 = get("/project/map")["map"]
check("b6. regenerate 后无变更 → 缓存命中 stale=False", m5["from_cache"] is True and m5["stale"] is False)

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "场景 b（git 指纹深层感知）全绿" || bad "场景 b（git 指纹深层感知）有失败"

echo ""
if [ $fail -eq 0 ]; then echo "M189 验收：全部通过 ✅"; else echo "M189 验收：有未通过 ❌"; exit 1; fi
