#!/usr/bin/env bash
# M195 验收 — P2 功能缺口批消化第二波（fence 豁免 / report 增强 / 模型 alias 动态化）。
#
#   1) pytest 单测：tests/test_m195_p2_batch.py
#        - _split_markdown fenced code block 豁免（```/~~~ 内行首 # 不当标题，未闭合保守不切）
#        - check target 存在性校验（M 格式指向不存在里程碑 → 失败；自由文本跳过）
#        - report 索引 index.md 维护（去重更新不追加）
#        - GET /models/aliases 端点契约（alias→model 映射清单）
#   2) CLI 黑盒（limitations_report.py，tmp STATE/registry 隔离）：
#        a) target=M12345 不存在 → check 退出 1 且输出含 id（M195.2 校验生效）
#        b) report 两次生成同名报告 → index.md 该文件名只 1 行（去重铁证）
#        c) 回归：真实 registry + STATE.json check ok（增强校验不炸既有 82 条）
#   3) 真实后端黑盒 HTTP（真 uvicorn，aliases 端点不调 LLM 无需假 server）：
#        d) GET /models/aliases → 200，含 coder/architect/supervisor/overseer/monitor 5 alias，
#           coder 默认 mlx-community/GLM-5.2-fp8（单模型模式）
#        e) 启动 env FLIPPED_CODER_MODEL=m195-override-coder → 响应 coder 反映覆盖值
#
# 一键复跑: bash scripts/verify_m195.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

TMPD=$(mktemp -d)
PORT="${FLIPPED_VERIFY_PORT:-8198}"
SRV_PID=""
cleanup() {
  [ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
  rm -rf "$TMPD"
}
trap cleanup EXIT

echo "== M195-1 单测（fence 豁免 / target 校验 / 索引 / aliases 端点） =="
PYTHONPATH=src $PY -m pytest tests/test_m195_p2_batch.py -q \
  && pass "M195 单测全绿" || bad "M195 单测失败"

echo "== M195-2 CLI 黑盒（limitations_report.py tmp 隔离） =="
# a/b 前置：tmp STATE.json 只含 M999；registry 一条 target 指向不存在的 M12345
mkdir -p "$TMPD/reports"
cat > "$TMPD/STATE.json" <<'JSON'
{"milestones": {"M999": {"title": "t", "status": "done"}}}
JSON
cat > "$TMPD/reg_bad.json" <<'JSON'
{"version": 1, "updated_at": "2026-08-06T00:00:00", "limitations": [
  {"id": "L-M999-1", "milestone": "M999", "text": "x", "category": "功能缺口",
   "impact": "", "priority": "P2", "difficulty": "低", "status": "open",
   "resolution_note": "", "target": "M12345"}
]}
JSON

# a) target 指向不存在里程碑 → check 失败
out=$($PY scripts/limitations_report.py check --state "$TMPD/STATE.json" --registry "$TMPD/reg_bad.json" 2>&1)
rc=$?
if [ $rc -eq 1 ] && echo "$out" | grep -q "L-M999-1" && echo "$out" | grep -q "M12345"; then
  pass "a.target 指向不存在里程碑 → check 退出 1 且点名 L-M999-1/M12345"
else
  bad "a.target 存在性校验未生效（rc=${rc} out=${out}）"
fi

# b) report 两次生成 → index.md 去重（该文件名只 1 行）
cat > "$TMPD/reg_ok.json" <<'JSON'
{"version": 1, "updated_at": "2026-08-06T00:00:00", "limitations": [
  {"id": "L-M999-1", "milestone": "M999", "text": "x", "category": "功能缺口",
   "impact": "", "priority": "P2", "difficulty": "低", "status": "open",
   "resolution_note": "", "target": "后续里程碑"}
]}
JSON
$PY scripts/limitations_report.py report --registry "$TMPD/reg_ok.json" \
  --out "$TMPD/reports/limitations_analysis_20260806.md" >/dev/null 2>&1
$PY scripts/limitations_report.py report --registry "$TMPD/reg_ok.json" \
  --out "$TMPD/reports/limitations_analysis_20260806.md" >/dev/null 2>&1
if [ -f "$TMPD/reports/index.md" ]; then
  n=$(grep -c "limitations_analysis_20260806" "$TMPD/reports/index.md")
  if [ "$n" -eq 1 ]; then
    pass "b.report 重复生成 → index.md 去重（同名只 1 行）"
  else
    bad "b.index.md 同名报告 $n 行（应为 1）"
  fi
else
  bad "b.index.md 未生成"
fi

# c) 回归：真实 registry + STATE.json check ok（target 校验不炸既有条目）
$PY scripts/limitations_report.py check >/dev/null 2>&1 \
  && pass "c.真实 registry check ok（82 条过增强校验）" || bad "c.真实 registry check 失败"

echo "== M195-3 真实后端黑盒 HTTP（uvicorn :${PORT}） =="
export FLIPPED_PROJECTS_DIR="$TMPD/projects"
export FLIPPED_DB="$TMPD/flipped.db"
export FLIPPED_SESSION_STORE_PATH="$TMPD/sessions.json"
export FLIPPED_TASKS_PATH="$TMPD/scheduled_tasks.json"
export FLIPPED_WORKER_RULES_PATH="$TMPD/worker_rules.json"
export FLIPPED_DATA_DIR="$TMPD/data"
# e 前置：启动 env 覆盖 coder 模型
FLIPPED_CODER_MODEL="m195-override-coder" \
PYTHONPATH=src ${PY} -m uvicorn api.main:app --port "${PORT}" --log-level warning &
SRV_PID=$!
ready=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/api/v1/health" -o /dev/null 2>&1; then ready=1; break; fi
  sleep 0.5
done
if [ "${ready}" != "1" ]; then
  bad "后端 30s 内未就绪"
  echo ""; echo "M195 验收：有未通过 ❌"; exit 1
fi

FLIPPED_BASE="http://127.0.0.1:${PORT}" ${PY} - <<'PYEOF'
import json, os, sys, urllib.request, urllib.error

BASE = os.environ["FLIPPED_BASE"] + "/api/v1"
fails = []

def call(method, path):
    req = urllib.request.Request(BASE + path, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"raw": e.read()[:200].decode("utf-8", "replace")}

def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" ({detail})" if detail and not cond else ""))
    if not cond:
        fails.append(name)

# ============ 场景 d/e：GET /models/aliases ============
st, body = call("GET", "/models/aliases")
aliases = body.get("aliases") if isinstance(body, dict) else None
by_alias = {a.get("alias"): a.get("model") for a in aliases} if isinstance(aliases, list) else {}
check("d.GET /models/aliases → 200 且 aliases 为 5 项清单",
      st == 200 and len(by_alias) == 5,
      detail=f"HTTP {st} {json.dumps(body, ensure_ascii=False)[:160]}")
check("d.5 个 alias 齐全（coder/architect/supervisor/overseer/monitor）",
      set(by_alias) == {"coder", "architect", "supervisor", "overseer", "monitor"},
      detail=str(sorted(by_alias)))
check("d.architect 默认 GLM-5.2-fp8（缺省映射未被 env 影响）",
      by_alias.get("architect") == "mlx-community/GLM-5.2-fp8",
      detail=str(by_alias.get("architect")))
check("e.启动 env FLIPPED_CODER_MODEL=m195-override-coder → coder 反映覆盖值",
      by_alias.get("coder") == "m195-override-coder",
      detail=str(by_alias.get("coder")))

sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] && pass "黑盒场景 d/e 全绿" || bad "黑盒场景有失败"

echo ""
if [ ${fail} -eq 0 ]; then echo "M195 验收：全部通过 ✅"; else echo "M195 验收：有未通过 ❌"; exit 1; fi
