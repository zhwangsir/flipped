#!/usr/bin/env bash
# quality_gate.sh · 系统性循环测试的质量门禁（TEST_PLAN.md §3）。
#
# 跑全量测试 + 覆盖率 + 类型 + 构建，任一门禁未过 → 退出码 1。
# 产出 JSON 指标到 quality_metrics.json，供 loop_test.sh 采集趋势。
#
# 用法:
#   bash scripts/quality_gate.sh           # 跑全部门禁
#   bash scripts/quality_gate.sh --quick   # 跳过全量 pytest（只跑前端+类型+构建，快速反馈）
#   bash scripts/quality_gate.sh --no-cov  # 跳过覆盖率（更快，但无 coverage 指标）
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"

QUICK=0; NOCOV=0
for a in "$@"; do
  case "$a" in
    --quick) QUICK=1 ;;
    --no-cov) NOCOV=1 ;;
  esac
done

fail=0
pass(){ echo "  ✅ $1"; }
bad(){ echo "  ❌ $1"; fail=1; }

# ---------- M157.10 · 结构化失败信号配置 ----------
# 阈值环境变量（可被外部覆盖，测试/调试用）
PY_COV_FLOOR="${FLIPPED_PY_COV_FLOOR:-80}"        # Python 覆盖率下限（.coveragerc fail_under=80）
FE_COV_FLOOR="${FLIPPED_FE_COV_FLOOR:-28}"        # 前端行覆盖率下限（vitest threshold）
# findings.jsonl 路径（测试可重定向到 tmp_path，避免污染仓库 reports/）
FINDINGS_PATH="${FLIPPED_FINDINGS_PATH:-reports/findings.jsonl}"

# emit_finding：往 findings.jsonl 追加一行结构化 JSON（rule 白名单见 _emit_finding.py）
# 用法：emit_finding <RULE> <LOCATION> <EXPECTED> <ACTUAL> <SUGGESTED_FIX> <RETRYABLE>
emit_finding(){
  FLIPPED_FINDINGS_PATH="$FINDINGS_PATH" python3 scripts/_emit_finding.py \
    --rule "$1" \
    --location "$2" \
    --expected "$3" \
    --actual "$4" \
    --suggested-fix "$5" \
    --retryable "$6" \
    || echo "  ⚠️ _emit_finding 写入失败（rule=$1）" >&2
}

# 测试/调试用失败注入钩子：设 FLIPPED_QG_INJECT_FAILURE=<RULE> 强制 emit 对应 finding 并 fail
# 仅用于自动化测试，不破坏真实代码（生产环境不设此变量）
INJECT_FAILURE="${FLIPPED_QG_INJECT_FAILURE:-}"

# 每次运行开头清空 findings.jsonl（只反映本次运行；mkdir -p 容错 reports/ 不存在）
# 放在 INJECT_FAILURE emit 之前，保证注入的 finding 是本次运行的第一条
mkdir -p "$(dirname "$FINDINGS_PATH")" 2>/dev/null || true
: > "$FINDINGS_PATH" 2>/dev/null || true

if [ -n "$INJECT_FAILURE" ]; then
  echo "  ⚠️ 检测到 FLIPPED_QG_INJECT_FAILURE=${INJECT_FAILURE}（测试钩子，强制失败）" >&2
  emit_finding "$INJECT_FAILURE" \
    "injected:FLIPPED_QG_INJECT_FAILURE" \
    "no injection (unset FLIPPED_QG_INJECT_FAILURE)" \
    "injected failure ($INJECT_FAILURE)" \
    "unset FLIPPED_QG_INJECT_FAILURE and rerun quality_gate.sh" \
    "true"
  fail=1
fi

# 指标收集（写 quality_metrics.json）
METRICS_TMP=$(mktemp)
echo "{}" > "$METRICS_TMP"
record(){ python3 -c "
import json,sys
m=json.load(open('$METRICS_TMP'))
m[sys.argv[1]]=sys.argv[2]
json.dump(m,open('$METRICS_TMP','w'))
" "$1" "$2"; }

echo "============================================================"
echo "  质量门禁 · quality_gate.sh（TEST_PLAN.md §3）"
echo "  模式: $([ $QUICK = 1 ] && echo 'quick(跳过全量pytest)' || echo 'full')  $([ $NOCOV = 1 ] && echo 'no-cov' || echo 'with-cov')"
echo "============================================================"

# ---------- G0 · shell lint 守卫（M144-A 陷阱复发防护） ----------
echo ""
echo "== [G0] shell lint · 守卫 \$VAR<全角字符> 陷阱 =="
if bash scripts/check_shell_lint.sh >&2; then
  pass "shell lint 无陷阱"
  record shell_lint "1"
else
  bad "shell lint 发现 \$VAR<非 ASCII> 陷阱（见上方）"
  record shell_lint "0"
  emit_finding "QG_SHELL_LINT_FAILED" \
    "scripts/check_shell_lint.sh" \
    "no \$VAR<non-ascii> traps" \
    "shell lint exit non-zero (见上方 stderr)" \
    "见上方 shell lint 输出，按提示修复 \$VAR<全角字符> 陷阱（变量加引号/用 \${VAR:-default}）" \
    "true"
fi

# ---------- G1 · Python pytest（全量或快速子集） ----------
echo ""
if [ $QUICK = 1 ]; then
  echo "== [G1] pytest · 快速子集（assistant + contract + orchestrator） =="
  PYTEST_TARGETS="tests/test_assistant_api.py tests/test_assistant_approval_resume.py tests/test_assistant_single_model.py tests/test_assistant_tui.py tests/test_api_contract.py tests/test_orchestrator.py tests/test_model_router.py"
else
  echo "== [G1] pytest · 全量回归 =="
  PYTEST_TARGETS="tests/"
fi

# 跑 pytest，输出存临时文件（避免 tee 管道干扰 PIPESTATUS 捕获）
# --quick 模式跑子集，覆盖率本就无意义（子集 < 全量），自动跳过 --cov
# 避免 .coveragerc fail_under=80 误判 pytest 退出码非 0。
PYTEST_TMP=$(mktemp)
if [ $NOCOV = 1 ] || [ $QUICK = 1 ]; then
  PYTHONPATH=src $PY -m pytest $PYTEST_TARGETS -q >"$PYTEST_TMP" 2>&1
else
  PYTHONPATH=src $PY -m pytest $PYTEST_TARGETS --cov=src --cov-report=term --cov-report=json:coverage.json -q >"$PYTEST_TMP" 2>&1
fi
PYTEST_EXIT=$?
# 回放输出到 stderr 供人看
cat "$PYTEST_TMP" >&2
PYTEST_OUT=$(cat "$PYTEST_TMP")
rm -f "$PYTEST_TMP"

# 解析 passed/skipped/failed（Python 正则提取，set -- 拆词，避免 set -u 下管道脆弱性）
PY_STATS_LINE=$(printf '%s\n' "$PYTEST_OUT" | python3 -c "
import sys, re
t=sys.stdin.read()
def n(pat):
    m=re.search(r'([0-9]+) '+pat, t)
    return m.group(1) if m else '0'
print(n('passed'), n('failed'), n('skipped'))
" 2>/dev/null || echo "0 0 0")
# PY_STATS_LINE = "1639 0 7"；用 set -- 拆词（对空串安全）
set -- $PY_STATS_LINE
PY_PASSED="${1:-0}"; PY_FAILED="${2:-0}"; PY_SKIPPED="${3:-0}"
record py_passed "$PY_PASSED"
record py_failed "$PY_FAILED"
record py_skipped "$PY_SKIPPED"

if [ "$PYTEST_EXIT" -eq 0 ]; then
  pass "pytest 通过（passed=$PY_PASSED skipped=$PY_SKIPPED failed=${PY_FAILED}）"
else
  bad "pytest 失败（passed=$PY_PASSED failed=${PY_FAILED}）"
  emit_finding "QG_PYTEST_FAILED" \
    "tests/" \
    "pytest exit 0" \
    "exit=${PYTEST_EXIT} passed=${PY_PASSED} failed=${PY_FAILED} skipped=${PY_SKIPPED}" \
    "见上方 pytest 输出，定位 FAILED 用例并修复（先读 traceback，再改实现，禁止 --skip/注释测试）" \
    "true"
fi

# ---------- G2 · Python 覆盖率（fail_under=80 由 .coveragerc 强制） ----------
# --quick 模式跑子集不生成 coverage.json；即便磁盘有陈旧 coverage.json 也不应采信。
if [ $NOCOV = 0 ] && [ $QUICK = 0 ] && [ -f coverage.json ]; then
  PY_COV=$(python3 -c "import json; d=json.load(open('coverage.json')); print(round(d['totals']['percent_covered'],2))" 2>/dev/null || echo "0")
  record py_coverage "$PY_COV"
  # .coveragerc fail_under=80 已让 pytest 退出码非 0，这里只做阈值报告
  PY_COV_INT=${PY_COV%.*}
  if [ "${PY_COV_INT:-0}" -ge "${PY_COV_FLOOR}" ]; then
    pass "Python 覆盖率 ${PY_COV}%（≥ ${PY_COV_FLOOR}% floor）"
  else
    bad "Python 覆盖率 ${PY_COV}%（< ${PY_COV_FLOOR}% floor）"
    emit_finding "QG_PY_COVERAGE_BELOW_FLOOR" \
      "src/" \
      ">= ${PY_COV_FLOOR}% (FLIPPED_PY_COV_FLOOR)" \
      "${PY_COV}%" \
      "见 coverage.json uncovered lines，补测试到低覆盖模块（当前最低：failure_kb.py/knowledge_graph.py）；或调低 FLIPPED_PY_COV_FLOOR（不建议）" \
      "true"
  fi
fi

# ---------- G3 · 前端 vitest + 覆盖率 ----------
echo ""
echo "== [G3] vitest · 前端全量 + 覆盖率（thresholds: lines≥28%） =="
VITEST_TMP=$(mktemp)
( cd console && npx vitest run $([ $NOCOV = 0 ] && echo --coverage) ) >"$VITEST_TMP" 2>&1
VITEST_EXIT=$?
cat "$VITEST_TMP" >&2
VITEST_OUT=$(cat "$VITEST_TMP")
rm -f "$VITEST_TMP"
V_STATS_LINE=$(printf '%s\n' "$VITEST_OUT" | python3 -c "
import sys, re
t=sys.stdin.read()
# vitest 输出含 ANSI 颜色码（\x1b[2m/\x1b[32m 等），先剥离再解析。
t=re.sub(r'\x1b\[[0-9;]*m','',t)
# vitest 输出两行：'Test Files N passed' 与 'Tests N passed'。
# 取 Tests 行（用例数，而非文件数），更准确反映测试通过情况。
def tests_n(pat):
    m=re.search(r'Tests\s+(\d+)\s+'+pat, t)
    if m: return m.group(1)
    m=re.search(r'(\d+)\s+'+pat, t)
    return m.group(1) if m else '0'
print(tests_n('passed'), tests_n('failed'))
" 2>/dev/null || echo "0 0")
set -- $V_STATS_LINE
V_PASSED="${1:-0}"; V_FAILED="${2:-0}"
record fe_passed "$V_PASSED"
record fe_failed "$V_FAILED"

# 前端覆盖率（从 json-summary 读）
FE_LINES=""
if [ $NOCOV = 0 ] && [ -f console/coverage/coverage-summary.json ]; then
  FE_LINES=$(python3 -c "import json; d=json.load(open('console/coverage/coverage-summary.json'))['total']; print(round(d['lines']['pct'],2))" 2>/dev/null || echo "0")
  record fe_lines_cov "$FE_LINES"
fi

if [ "$VITEST_EXIT" -eq 0 ]; then
  pass "vitest 通过（passed=$V_PASSED failed=${V_FAILED}）"
else
  bad "vitest 失败（passed=$V_PASSED failed=${V_FAILED}）"
  emit_finding "QG_VITEST_FAILED" \
    "console/" \
    "vitest exit 0" \
    "exit=${VITEST_EXIT} passed=${V_PASSED} failed=${V_FAILED}" \
    "见上方 vitest 输出，定位 failed 用例并修复（先读断言差异，再改组件/handler）" \
    "true"
fi

# 前端覆盖率阈值检查（独立于 vitest 通过与否；coverage-summary.json 可能来自上次运行）
if [ -n "$FE_LINES" ]; then
  FE_LINES_INT="${FE_LINES%.*}"
  if [ "${FE_LINES_INT:-0}" -ge "${FE_COV_FLOOR}" ]; then
    pass "前端行覆盖率 ${FE_LINES}%（≥ ${FE_COV_FLOOR}% floor）"
  else
    bad "前端行覆盖率 ${FE_LINES}%（< ${FE_COV_FLOOR}% floor）"
    emit_finding "QG_FE_COVERAGE_BELOW_FLOOR" \
      "console/src/" \
      ">= ${FE_COV_FLOOR}% (FLIPPED_FE_COV_FLOOR)" \
      "${FE_LINES}%" \
      "见 console/coverage/ 未覆盖文件，补组件测试；或调低 FLIPPED_FE_COV_FLOOR（不建议）" \
      "true"
  fi
fi

# ---------- G4 · TypeScript 类型检查 ----------
echo ""
echo "== [G4] tsc --noEmit · 类型检查 =="
if ( cd console && npx tsc --noEmit ) 2>&1 | tee /dev/stderr; then
  pass "tsc 无错误"
  record tsc_errors "0"
else
  bad "tsc 报错"
  record tsc_errors "1"
  emit_finding "QG_TSC_ERRORS" \
    "console/src/" \
    "0 tsc errors" \
    "tsc exit non-zero (见上方 stderr)" \
    "见上方 tsc 输出，按 TS2322/TS2345 等错误码修类型注解；先读报错行号定位文件" \
    "true"
fi

# ---------- G5 · vite build ----------
echo ""
echo "== [G5] vite build · 产物可生成 =="
if ( cd console && npm run build ) >/tmp/quality_gate_build.log 2>&1; then
  pass "vite build 成功"
  record build_ok "1"
else
  bad "vite build 失败（见 /tmp/quality_gate_build.log）"
  tail -5 /tmp/quality_gate_build.log >&2
  record build_ok "0"
  emit_finding "QG_BUILD_FAILED" \
    "console/" \
    "vite build exit 0" \
    "build exit non-zero (见 /tmp/quality_gate_build.log 末尾)" \
    "读 /tmp/quality_gate_build.log 全文定位错误（常见：import 路径错/未安装依赖/语法错误）；先修第一个错误再重跑" \
    "true"
fi

# ---------- 汇总 ----------
echo ""
echo "============================================================"
# 写最终指标
cp "$METRICS_TMP" quality_metrics.json
rm -f "$METRICS_TMP"

python3 -c "
import json
m=json.load(open('quality_metrics.json'))
print('  指标快照:')
for k in ['shell_lint','py_passed','py_failed','py_skipped','py_coverage','fe_passed','fe_failed','fe_lines_cov','tsc_errors','build_ok']:
    if k in m: print(f'    {k}: {m[k]}')
"

# M157.10 · 结构化失败信号汇总（机器可读 findings.jsonl + 人类可读 rule 列表）
if [ -f "$FINDINGS_PATH" ]; then
  # grep -c 总会输出数字（即使退出码 1=无匹配）；|| echo 会双输出 "0\n0"，故只用 ${:-0} 兜底空值
  FINDING_COUNT=$(grep -c . "$FINDINGS_PATH" 2>/dev/null)
  FINDING_COUNT="${FINDING_COUNT:-0}"
  if [ "${FINDING_COUNT:-0}" -gt 0 ]; then
    echo "  结构化失败信号 ($FINDINGS_PATH, $FINDING_COUNT 条):"
    python3 -c "
import json,sys
for ln in open('$FINDINGS_PATH'):
    ln=ln.strip()
    if not ln: continue
    o=json.loads(ln)
    print(f'    - [{o[\"rule\"]}] {o[\"location\"]}  expected={o[\"expected\"]!r} actual={o[\"actual\"]!r} retryable={o[\"retryable\"]}')
    print(f'      fix: {o[\"suggested_fix\"]}')
" 2>/dev/null || echo "    (findings.jsonl 解析失败，见原始文件)"
  fi
fi

if [ $fail -eq 0 ]; then
  echo "  质量门禁：通过 ✅"
else
  echo "  质量门禁：未通过 ❌（见上方 ❌ 项 + $FINDINGS_PATH 结构化信号）"
fi
echo "============================================================"
exit $fail
