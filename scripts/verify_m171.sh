#!/usr/bin/env bash
# M171 验收 — RAG 项目摄入强化（gitignore 过滤 / 幂等 upsert / 结构化分块 / project 过滤）。
#
#   1) pytest 单测：test_m171_rag_ingest.py（A 摄入层 8 例）+
#      test_m171_mcp_rag_project.py（B 工具层 8 例）
#   2) 真实后端黑盒 E2E：起 uvicorn（RAG_DB_DIR 临时库），造临时 git repo
#      （含 .gitignore + node_modules）与临时普通目录，curl 层级断言——
#        gitignore 生效：ignored.md / node_modules/x.md 不被摄入（count 精确 = 2）
#        幂等复摄入：同目录二次 rag_ingest count 不变、库内 chunk 不翻倍
#        project 过滤：projA 过滤查询只命中 projA；无过滤两 project 都在
#        元数据五字段：source/ext/chunk/project/content_hash 齐全
#
# 一键复跑: scripts/verify_m171.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

# 隔离：DB/RAG/git repo 副作用全部指向临时目录，不触碰真实 data/ 与仓库
TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8172}"
SRV_PID=""
cleanup() {
  [ -n "${SRV_PID}" ] && kill "${SRV_PID}" 2>/dev/null; wait "${SRV_PID}" 2>/dev/null
  rm -rf "${TMPD}"
}
trap cleanup EXIT
export FLIPPED_DB="${TMPD}/flipped.db"
export RAG_DB_DIR="${TMPD}/ragdb"

echo "== M171-1 摄入层 + 工具层单测（16 例） =="
PYTHONPATH=src ${PY} -m pytest tests/test_m171_rag_ingest.py tests/test_m171_mcp_rag_project.py -q \
  && pass "M171 单测全绿" || bad "M171 单测失败"

echo "== M171-2 黑盒 E2E（uvicorn :${PORT}，临时 git repo + 临时 Chroma 库） =="

# 造 projA：git repo（.gitignore 忽略 ignored.md 与 node_modules/）
PROJA="${TMPD}/projA"
mkdir -p "${PROJA}/sub" "${PROJA}/node_modules"
git -C "${TMPD}" init -q projA
printf 'ignored.md\nnode_modules/\n' > "${PROJA}/.gitignore"
printf 'zebra anchor: striped equine roams the savanna\n' > "${PROJA}/keep.md"
printf 'def savanna():\n    return "zebra habitat"\n' > "${PROJA}/sub/keep2.py"
printf 'phantomtoken should never be ingested\n' > "${PROJA}/ignored.md"
printf 'phantomtoken in node_modules\n' > "${PROJA}/node_modules/x.md"

# 造 projB：普通目录（非 repo，回退 rglob）
PROJB="${TMPD}/projB"
mkdir -p "${PROJB}"
printf 'quokka anchor: smiling marsupial on rottnest island\n' > "${PROJB}/b.md"

PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!

# 等后端就绪（最多 30s）
ready=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/api/v1/mcp/tools" -o /dev/null 2>&1; then ready=1; break; fi
  sleep 0.5
done
if [ "${ready}" != "1" ]; then
  bad "后端 30s 内未就绪"
  echo ""; echo "M171 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" PROJA="${PROJA}" PROJB="${PROJB}" ${PY} - <<'PYEOF'
import json, os, sys, urllib.request, urllib.error

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
PROJA, PROJB = os.environ["PROJA"], os.environ["PROJB"]
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

def rag_ingest(paths, project):
    return call("POST", "/mcp/tools/rag_ingest/call",
                {"arguments": {"paths": paths, "project": project}})

def rag_query(query, project=None, n=10):
    args = {"query": query, "n_results": n}
    if project:
        args["project"] = project
    return call("POST", "/mcp/tools/rag_query/call", {"arguments": args})

# 1. gitignore 生效：projA 只摄入 keep.md + sub/keep2.py（ignored.md/node_modules 被排除）
st, body = rag_ingest([PROJA], "projA")
count_a = body.get("result", {}).get("count", -1)
check("projA 摄入 count == 2（gitignore 排除 ignored.md 与 node_modules/x.md）",
      st == 200 and body.get("ok") is True and count_a == 2,
      detail=f"count={count_a} body={json.dumps(body)[:200]}")

# 2. projB 普通目录回退 rglob
st, body = rag_ingest([PROJB], "projB")
check("projB 摄入 count == 1（非 repo 回退 rglob）",
      st == 200 and body.get("ok") is True and body.get("result", {}).get("count") == 1)

# 3. 幂等复摄入：同目录二次 count 相同，库内 chunk 不翻倍
st, body = rag_ingest([PROJA], "projA")
count_a2 = body.get("result", {}).get("count", -1)
st, body = rag_query("zebra savanna", project="projA", n=10)
hits = body.get("result", {}).get("results", [])
uniq_ids = {h.get("id") for h in hits}
check("二次摄入 count 不变（确定性 id upsert）", count_a2 == 2, detail=f"count={count_a2}")
check("复摄入后库内 projA chunk 不翻倍（唯一 id == 2）",
      st == 200 and len(hits) == 2 and len(uniq_ids) == 2,
      detail=f"hits={len(hits)} uniq={len(uniq_ids)}")

# 4. project 过滤：过滤 projA 只命中 projA；无过滤两 project 都在
st, body = rag_query("zebra quokka anchor", project="projA", n=10)
hits = body.get("result", {}).get("results", [])
projs = {h.get("metadata", {}).get("project") for h in hits}
check("project=projA 过滤只命中 projA",
      st == 200 and len(hits) >= 1 and projs == {"projA"}, detail=f"projs={projs}")
st, body = rag_query("zebra quokka anchor", n=10)
hits = body.get("result", {}).get("results", [])
projs = {h.get("metadata", {}).get("project") for h in hits}
check("无过滤查询两 project 都在", st == 200 and projs == {"projA", "projB"},
      detail=f"projs={projs}")

# 5. 被忽略文件的内容绝不入库（全库扫描无任何 ignored 来源）
st, body = rag_query("phantomtoken", n=10)
hits = body.get("result", {}).get("results", [])
srcs = [h.get("metadata", {}).get("source", "") for h in hits]
texts = [h.get("text", "") for h in hits]
check("ignored.md / node_modules 内容不入库",
      st == 200 and not any("ignored.md" in s or "node_modules" in s for s in srcs)
      and not any("phantomtoken" in t for t in texts),
      detail=f"srcs={srcs}")

# 6. 元数据五字段齐全
st, body = rag_query("zebra savanna", project="projA", n=1)
hits = body.get("result", {}).get("results", [])
md = (hits[0].get("metadata") or {}) if hits else {}
need = {"source", "ext", "chunk", "project", "content_hash"}
check("元数据五字段齐全（source/ext/chunk/project/content_hash）",
      bool(hits) and need <= set(md) and md.get("project") == "projA",
      detail=f"metadata={json.dumps(md)[:200]}")

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "黑盒 E2E 全绿" || bad "黑盒 E2E 失败"

echo ""
if [ ${fail} -eq 0 ]; then echo "M171（RAG 项目摄入强化）验收：通过 ✅"; else echo "M171 验收：有未通过 ❌"; fi
exit ${fail}
