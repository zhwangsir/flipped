#!/usr/bin/env bash
# =============================================================================
# E2E 全量测试一键执行脚本（5 维度覆盖）
#
# 用途：运行 Playwright E2E 测试套件（功能/边界/异常/性能/兼容性），生成
#       HTML + JSON + Markdown 三种格式报告。
#
# 用法：
#   ./scripts/run_e2e_full.sh                  # 默认：chromium 浏览器，全量用例
#   ./scripts/run_e2e_full.sh --all-browsers   # 三浏览器（chromium/firefox/webkit）
#   ./scripts/run_e2e_full.sh --project=firefox # 指定单浏览器
#   ./scripts/run_e2e_full.sh --grep=boundary   # 只跑匹配的用例
#   ./scripts/run_e2e_full.sh --report-only     # 不跑测试，只重新生成报告
#
# 输出：
#   console/reports/e2e-html/index.html  — 人工查阅的 HTML 报告（含截图/trace）
#   console/reports/e2e-results.json     — 机器可读的 JSON 结果
#   console/reports/e2e-report.md        — 汇总 Markdown 报告（5 维度分类）
#   console/reports/e2e-artifacts/       — 失败截图/trace/视频
# =============================================================================
set -euo pipefail

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONSOLE_DIR="$PROJECT_ROOT/console"
REPORTS_DIR="$CONSOLE_DIR/reports"
RESULTS_JSON="$REPORTS_DIR/e2e-results.json"
REPORT_MD="$REPORTS_DIR/e2e-report.md"

# 参数解析
BROWSER_ARG=""
GREP_ARG=""
REPORT_ONLY=false
ALL_BROWSERS=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all-browsers)
      ALL_BROWSERS=true
      shift
      ;;
    --project=*)
      BROWSER_ARG="--project=${1#*=}"
      shift
      ;;
    --grep=*)
      GREP_ARG="--grep=${1#*=}"
      shift
      ;;
    --report-only)
      REPORT_ONLY=true
      shift
      ;;
    -h|--help)
      head -25 "$0" | tail -20
      exit 0
      ;;
    *)
      echo -e "${RED}未知参数: $1${NC}" >&2
      exit 1
      ;;
  esac
done

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}  E2E 全量测试 · run_e2e_full.sh${NC}"
echo -e "${BLUE}  时间: $(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo -e "${BLUE}============================================================${NC}"

# -----------------------------------------------------------------------------
# 0. 仅生成报告模式
# -----------------------------------------------------------------------------
if [[ "$REPORT_ONLY" == "true" ]]; then
  echo -e "${YELLOW}→ 跳过测试，仅重新生成报告${NC}"
  if [[ ! -f "$RESULTS_JSON" ]]; then
    echo -e "${RED}✗ 找不到 ${RESULTS_JSON}，请先跑测试${NC}" >&2
    exit 1
  fi
  python3 "$SCRIPT_DIR/gen_e2e_report.py" "$RESULTS_JSON" "$REPORT_MD"
  echo -e "${GREEN}✓ 报告已生成: $REPORT_MD${NC}"
  exit 0
fi

# -----------------------------------------------------------------------------
# 1. 前置检查：dev server 是否在 5273 端口运行
# -----------------------------------------------------------------------------
echo -e "${YELLOW}→ [1/4] 检查 dev server (5273)...${NC}"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5273/ --max-time 3 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" != "200" ]]; then
  echo -e "${RED}✗ dev server 未运行（HTTP ${HTTP_CODE}）${NC}"
  echo -e "${YELLOW}  请先在另一个终端启动: cd console && npm run dev${NC}"
  echo -e "${YELLOW}  Playwright 配置了 webServer.reuseExistingServer=true，${NC}"
  echo -e "${YELLOW}  若不手动启动，Playwright 会尝试自动启动（耗时 60s）。${NC}"
  echo -e "${YELLOW}  继续执行，依赖 Playwright 自动启动...${NC}"
else
  echo -e "${GREEN}✓ dev server 在线 (HTTP 200)${NC}"
fi

# -----------------------------------------------------------------------------
# 2. 清理旧报告
# -----------------------------------------------------------------------------
echo -e "${YELLOW}→ [2/4] 清理旧报告...${NC}"
mkdir -p "$REPORTS_DIR"
rm -rf "$REPORTS_DIR/e2e-html" "$REPORTS_DIR/e2e-artifacts"
rm -f "$RESULTS_JSON" "$REPORT_MD"
echo -e "${GREEN}✓ 旧报告已清理${NC}"

# -----------------------------------------------------------------------------
# 3. 运行 Playwright 测试
# -----------------------------------------------------------------------------
echo -e "${YELLOW}→ [3/4] 运行 Playwright E2E 测试...${NC}"
cd "$CONSOLE_DIR"

PW_ARGS=()
if [[ "$ALL_BROWSERS" == "true" ]]; then
  echo -e "${BLUE}  浏览器矩阵: chromium + firefox + webkit${NC}"
else
  if [[ -n "$BROWSER_ARG" ]]; then
    PW_ARGS+=("$BROWSER_ARG")
    echo -e "${BLUE}  浏览器: ${BROWSER_ARG#--project=}${NC}"
  else
    PW_ARGS+=("--project=chromium")
    echo -e "${BLUE}  浏览器: chromium（默认；--all-browsers 跑三引擎）${NC}"
  fi
fi
if [[ -n "$GREP_ARG" ]]; then
  PW_ARGS+=("$GREP_ARG")
  echo -e "${BLUE}  用例过滤: ${GREP_ARG#--grep=}${NC}"
fi

# 不用 set -e 期间跑 playwright（失败正常，要继续生成报告）
set +e
npx playwright test "${PW_ARGS[@]}" 2>&1 | tee "$REPORTS_DIR/e2e-raw-output.log"
PW_EXIT=${PIPESTATUS[0]}
set -e

if [[ $PW_EXIT -eq 0 ]]; then
  echo -e "${GREEN}✓ Playwright 测试全部通过${NC}"
else
  echo -e "${YELLOW}⚠ Playwright 有用例失败（exit ${PW_EXIT}），继续生成报告${NC}"
fi

# -----------------------------------------------------------------------------
# 4. 生成 Markdown 报告
# -----------------------------------------------------------------------------
echo -e "${YELLOW}→ [4/4] 生成 Markdown 报告...${NC}"
if [[ ! -f "$RESULTS_JSON" ]]; then
  echo -e "${RED}✗ 找不到 $RESULTS_JSON — JSON reporter 未生效？${NC}" >&2
  exit 1
fi

python3 "$SCRIPT_DIR/gen_e2e_report.py" "$RESULTS_JSON" "$REPORT_MD"

# -----------------------------------------------------------------------------
# 汇总
# -----------------------------------------------------------------------------
echo ""
echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}  E2E 测试完成 · 报告输出${NC}"
echo -e "${BLUE}============================================================${NC}"
echo -e "${GREEN}  HTML 报告:    $REPORTS_DIR/e2e-html/index.html${NC}"
echo -e "${GREEN}  JSON 结果:    $RESULTS_JSON${NC}"
echo -e "${GREEN}  Markdown 汇总: $REPORT_MD${NC}"
echo -e "${GREEN}  失败 artifacts: $REPORTS_DIR/e2e-artifacts/${NC}"
echo ""
echo -e "${YELLOW}  查看 HTML 报告: open $REPORTS_DIR/e2e-html/index.html${NC}"
echo ""

# 用 Python 快速汇总通过率
python3 - "$RESULTS_JSON" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
stats = {"passed": 0, "failed": 0, "flaky": 0, "skipped": 0}
for s in data.get("stats", []):
    k = s.get("status")
    if k in stats:
        stats[k] = s.get("count", 0)
total = sum(stats.values())
if total > 0:
    rate = (stats["passed"] + stats["flaky"]) / total * 100
    print(f"  通过率: {rate:.1f}% ({stats['passed']} passed, {stats['flaky']} flaky, {stats['failed']} failed, {stats['skipped']} skipped, {total} total)")
PYEOF

exit $PW_EXIT
