#!/usr/bin/env bash
# M173 验收 — Zread 式项目地图（项目知识库可视化 + chat/plan 全局结构注入）。
#
#   1) pytest 单测：test_m173_project_map.py（A 地图模块 23 例）+
#      test_m173_map_api.py（B 端点+注入 13 例）
#   2) 真实后端黑盒 E2E：起 uvicorn（FLIPPED_PROJECTS_DIR / FLIPPED_MAP_CACHE_DIR
#      全部指向临时目录，零污染），造含 package.json+README+requirements.txt 的
#      真实项目，curl 层级断言——
#        POST /projects 建项目并设为活动
#        GET  /project/map           五字段 + 分节（技术栈/依赖/README 摘要）+ from_cache=False
#        GET  /project/map（再）     from_cache=True（缓存命中）
#        文件 mtime 调新后 GET       stale=True（不自动重建）
#        POST /project/map/regenerate 强制重建 stale=False
#      （chat/plan 注入层的 system/payload 证据在单测 mock 层，黑盒不烧模型；
#        前端面板证据在 vitest ProjectMapPanel.test.tsx）
#
# 一键复跑: scripts/verify_m173.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

# 隔离：项目主目录/地图缓存/DB 全部指向临时目录，不触碰真实 ~/projects 与 data/
TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8173}"
SRV_PID=""
cleanup() {
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
  rm -rf "$TMPD"
}
trap cleanup EXIT
export FLIPPED_PROJECTS_DIR="$TMPD/projects"
export FLIPPED_MAP_CACHE_DIR="$TMPD/mapcache"
export FLIPPED_DB="$TMPD/flipped.db"

echo "== M173-1 地图模块 + 端点/注入单测（36 例） =="
PYTHONPATH=src $PY -m pytest tests/test_m173_project_map.py tests/test_m173_map_api.py -q \
  && pass "M173 单测全绿" || bad "M173 单测失败"

echo "== M173-2 真实后端黑盒 E2E（uvicorn :${PORT}，临时项目+临时缓存） =="
PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!

ready=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/api/v1/health" -o /dev/null 2>&1; then ready=1; break; fi
  sleep 0.5
done
if [ "${ready}" != "1" ]; then
  bad "后端 30s 内未就绪"
  echo ""; echo "M173 验收：有未通过 ❌"; exit 1
fi

# 真实项目骨架：先由后端 POST /projects 建空目录并设为活动，黑盒再往里面写文件
# （顺序不可反——目录已存在会让 POST /projects 409，活动项目设不上）
PROJ="$TMPD/projects/m173demo"

FLIPPED_BASE="http://127.0.0.1:${PORT}" PROJ_DIR="$PROJ" ${PY} - <<'PYEOF'
import json, os, sys, urllib.request, urllib.error

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

# 1. 建项目并设为活动
st, body = call("POST", "/projects", {"name": "m173demo"})
check("POST /projects 建项目并设为活动", st in (200, 201) and body.get("name") == "m173demo",
      detail=f"HTTP {st} {json.dumps(body)[:120]}")

# 2. 往空项目里写真实文件（package.json/README/requirements/src/tests）
os.makedirs(os.path.join(PROJ, "src"), exist_ok=True)
os.makedirs(os.path.join(PROJ, "tests"), exist_ok=True)
with open(os.path.join(PROJ, "package.json"), "w") as fh:
    json.dump({"name": "m173demo",
               "dependencies": {"react": "^19.0.0", "zustand": "^5.0.0"},
               "devDependencies": {"vitest": "^3.0.0"}}, fh)
with open(os.path.join(PROJ, "requirements.txt"), "w") as fh:
    fh.write("fastapi>=0.110\nuvicorn\n")
with open(os.path.join(PROJ, "README.md"), "w") as fh:
    fh.write("# m173demo\n\n![badge](https://shields.io/badge/x)\n\n"
             "Zeta anchor project: deterministic map verification harness.\n")
with open(os.path.join(PROJ, "src", "main.py"), "w") as fh:
    fh.write('print("zeta anchor")\n')
with open(os.path.join(PROJ, "tests", "test_anchor.py"), "w") as fh:
    fh.write("def test_anchor():\n    assert True\n")

# 3. 首次 GET /project/map → 现建，五字段齐全，分节命中
st, body = call("GET", "/project/map")
m = body.get("map") or {}
md = m.get("markdown") or ""
check("GET /project/map 200 + needs_project=False", st == 200 and body.get("needs_project") is False,
      detail=f"HTTP {st}")
check("五字段齐全（markdown/generated_at/stale/from_cache/stack）",
      all(k in m for k in ("markdown", "generated_at", "stale", "from_cache", "stack")))
check("首建 from_cache=False 且 stale=False",
      m.get("from_cache") is False and m.get("stale") is False)
check("markdown 含标题与分节（技术栈/依赖清单/README 摘要/代码统计）",
      "# 项目地图：m173demo" in md and "## 技术栈" in md and "## 依赖清单" in md
      and "## README 摘要" in md and "## 代码统计" in md,
      detail=md[:200])
check("技术栈识别 Node/JS + Python", "Node/JS" in m.get("stack", []) and "Python" in m.get("stack", []),
      detail=str(m.get("stack")))
check("依赖清单含 react 与 fastapi；README 摘要含锚点文本",
      "react" in md and "fastapi" in md and "Zeta anchor project" in md)

# 3. 再 GET → 缓存命中
st, body = call("GET", "/project/map")
m2 = body.get("map") or {}
check("二次 GET from_cache=True（缓存命中）", st == 200 and m2.get("from_cache") is True)

# 5. 顶层文件 mtime 调新 → stale=True（不自动重建；深层文件编辑不触发，属已知设计）
f = os.path.join(PROJ, "README.md")
st_atime = os.path.getatime(f)
os.utime(f, (st_atime, os.path.getmtime(f) + 100))
st, body = call("GET", "/project/map")
m3 = body.get("map") or {}
check("项目文件变更后 stale=True 且仍走缓存",
      m3.get("stale") is True and m3.get("from_cache") is True,
      detail=f"stale={m3.get('stale')} from_cache={m3.get('from_cache')}")

# 6. POST regenerate → 强制重建 stale=False
st, body = call("POST", "/project/map/regenerate")
m4 = body.get("map") or {}
check("regenerate 200 + stale=False + from_cache=False",
      st == 200 and m4.get("stale") is False and m4.get("from_cache") is False,
      detail=f"HTTP {st}")

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "黑盒 E2E 全绿" || bad "黑盒 E2E 失败"

echo ""
if [ ${fail} -eq 0 ]; then echo "M173（Zread 式项目地图）验收：通过 ✅"; else echo "M173 验收：有未通过 ❌"; fi
exit ${fail}
