#!/usr/bin/env bash
# M172 验收 — chat/plan 自动 RAG 上下文注入（codebase awareness 体验落地）。
#
#   1) pytest 单测：test_m172_rag_context.py（A 检索模块 13 例）+
#      test_m172_chat_rag.py（B _run_chat 接线 9 例）
#   2) 真检索黑盒：临时 Chroma 持久库（RAG_DB_DIR 隔离），
#      真实 ingest（M171 通路）→ 真实 build_rag_context（store=None 走真 Chroma），
#      确定性断言——
#        project 过滤命中 projA 来源
#        project 无结果时无过滤兜底重查（projC 不存在仍召回 projA/projB 内容）
#        max_chars 截断总长不超
#        空库返回 ("", 0)
#      不碰 LLM/网络（接线层 system 注入/rag_chunks 证据在单测，黑盒不烧模型）。
#
# 一键复跑: scripts/verify_m172.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

# 隔离：RAG 副作用全部指向临时目录，不触碰真实 data/
TMPD=$(mktemp -d)
trap 'rm -rf "${TMPD}"' EXIT
export RAG_DB_DIR="${TMPD}/ragdb"

echo "== M172-1 检索模块 + 接线单测（22 例） =="
PYTHONPATH=src ${PY} -m pytest tests/test_m172_rag_context.py tests/test_m172_chat_rag.py -q \
  && pass "M172 单测全绿" || bad "M172 单测失败"

echo "== M172-2 真检索黑盒（临时 Chroma 库，真实 ingest → build_rag_context） =="
PROJA="${TMPD}/projA"
PROJB="${TMPD}/projB"
mkdir -p "${PROJA}" "${PROJB}"
printf 'zebra anchor: striped equine roams the savanna at dawn\n' > "${PROJA}/zebra.md"
printf 'quokka anchor: smiling marsupial on rottnest island\n' > "${PROJB}/quokka.md"
PROJA="${PROJA}" PROJB="${PROJB}" PYTHONPATH=src ${PY} - <<'PYEOF'
import os, sys

fails = []

def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" ({detail})" if detail and not cond else ""))
    if not cond:
        fails.append(name)

# 真实摄入（M171 通路，project 元数据落库）
from rag.ingest import ingest_directory
from rag.vector_store import ChromaVectorStore
from api.rag_context import RAG_CONTEXT_HEADER, build_rag_context

store = ChromaVectorStore()  # RAG_DB_DIR 临时持久库
ids_a = ingest_directory(os.environ["PROJA"], store=store, project="projA")
ids_b = ingest_directory(os.environ["PROJB"], store=store, project="projB")
check("摄入 projA+projB 各 1 chunk", len(ids_a) == 1 and len(ids_b) == 1,
      detail=f"a={len(ids_a)} b={len(ids_b)}")

# 1. project 过滤：命中 projA 来源
ctx, k = build_rag_context("zebra savanna", project="projA", store=store)
check("project=projA 注入文本含头部与 projA 来源",
      k >= 1 and ctx.startswith(RAG_CONTEXT_HEADER) and "zebra.md" in ctx,
      detail=f"k={k} ctx={ctx[:120]!r}")

# 2. 兜底重查：projC 不存在 → 无过滤重查仍召回
ctx2, k2 = build_rag_context("zebra savanna", project="projC", store=store)
check("project=projC（无数据）兜底无过滤重查仍召回", k2 >= 1 and "zebra" in ctx2,
      detail=f"k={k2}")

# 3. max_chars 截断：总长不超
ctx3, k3 = build_rag_context("zebra quokka anchor", max_chars=200, store=store)
check("max_chars=200 截断总长 ≤ 200 且至少装入 1 条",
      0 < len(ctx3) <= 200 and k3 >= 1,
      detail=f"len={len(ctx3)} k={k3}")

# 4. 空库 → ("", 0)
import tempfile
os.environ["RAG_DB_DIR"] = tempfile.mkdtemp()
empty_store = ChromaVectorStore()
ctx4, k4 = build_rag_context("anything", store=empty_store)
check("空库返回 (\"\", 0)", ctx4 == "" and k4 == 0, detail=f"k={k4}")

# 5. fail-open：store.query 抛异常 → ("", 0)
class BoomStore:
    def query(self, *a, **kw):
        raise RuntimeError("boom")
ctx5, k5 = build_rag_context("zebra", store=BoomStore())
check("store 异常 fail-open (\"\", 0)", ctx5 == "" and k5 == 0)

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "真检索黑盒全绿" || bad "真检索黑盒失败"

echo ""
if [ ${fail} -eq 0 ]; then echo "M172（chat/plan 自动 RAG 上下文注入）验收：通过 ✅"; else echo "M172 验收：有未通过 ❌"; fi
exit ${fail}
