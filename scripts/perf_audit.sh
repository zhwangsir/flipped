#!/usr/bin/env bash
# perf_audit.sh · 前端性能审计脚本（TEST_STRATEGY_OPTIMIZATION.md §2.3 step 3）
#
# 跑 Lighthouse 审计 + Playwright 交互流畅度基准，产出：
#   - reports/lighthouse-{timestamp}.json  （Lighthouse 完整报告）
#   - reports/perf-audit-{timestamp}.log   （本次审计控制台输出）
#   - PERF_LOG.md 追加一行趋势记录          （人类可读指标摘要）
#
# 阈值（与 TEST_STRATEGY_OPTIMIZATION.md §2.4 对齐）：
#   LCP  < 2500ms   > 4000ms 报警
#   FCP  < 1800ms   > 3000ms 报警
#   CLS  < 0.1      > 0.25 报警
#   TTFB < 800ms    > 1800ms 报警
#
# 用法:
#   bash scripts/perf_audit.sh              # 跑 Lighthouse + Playwright perf
#   bash scripts/perf_audit.sh --lighthouse # 只跑 Lighthouse
#   bash scripts/perf_audit.sh --playwright # 只跑 Playwright 交互流畅度
#   bash scripts/perf_audit.sh --ci         # CI 模式：超阈值退出码 1
set -uo pipefail
cd "$(dirname "$0")/.."

# ---------- 参数 ----------
MODE="all"
CI_MODE=0
PROD_MODE=0
for a in "$@"; do
  case "$a" in
    --lighthouse) MODE="lighthouse" ;;
    --playwright) MODE="playwright" ;;
    --ci) CI_MODE=1 ;;
    --prod) PROD_MODE=1 ;;
  esac
done

# ---------- 阈值（与 TEST_STRATEGY_OPTIMIZATION.md §2.4 对齐） ----------
LCP_TARGET=2500;  LCP_ALARM=4000
FCP_TARGET=1800;  FCP_ALARM=3000
CLS_TARGET=100;   CLS_ALARM=250   # ×1000（CLS 是小数，乘 1000 转整数比较）
TTFB_TARGET=800;  TTFB_ALARM=1800

DEV_PORT=5273
DEV_URL="http://127.0.0.1:${DEV_PORT}/"
TS=$(date +%Y%m%d-%H%M%S)
REPORTS_DIR="reports"
mkdir -p "$REPORTS_DIR" 2>/dev/null || true

# ---------- 辅助 ----------
fail=0
pass(){ echo "  ✅ $1"; }
bad(){ echo "  ❌ $1"; fail=1; }
warn(){ echo "  ⚠️  $1"; }

echo "============================================================"
echo "  前端性能审计 · perf_audit.sh（TEST_STRATEGY_OPTIMIZATION.md §2）"
echo "  模式: $MODE  $([ $CI_MODE = 1 ] && echo 'ci(超阈值失败)' || echo 'soft(超阈值仅告警)')  $([ $PROD_MODE = 1 ] && echo 'prod(preview构建)' || echo 'dev(开发服务器)')"
echo "  时间: $TS"
echo "============================================================"

# ---------- 0. 确保 server 运行 ----------
echo ""
echo "== [G0] server 检查 =="
if [ $PROD_MODE = 1 ]; then
  # 生产模式：先 build 再起 preview（端口 4173，需改 DEV_URL/DEV_PORT）
  DEV_PORT=4173
  DEV_URL="http://127.0.0.1:${DEV_PORT}/"
  echo "  ℹ️  prod 模式：先构建..."
  # 用 npm --prefix 避免 cd 子 shell（某些钩子环境会干扰子 shell 重定向）
  if ! npm --prefix console run build >"$REPORTS_DIR/build-$TS.log" 2>&1; then
    bad "vite build 失败，见 $REPORTS_DIR/build-$TS.log"
    tail -5 "$REPORTS_DIR/build-$TS.log" >&2
    exit 1
  fi
  pass "vite build 成功"
  # 启动 preview（必须在 console 目录跑，读 vite.config.ts）
  # 用 bash -c + exec 避免子 shell 钩子干扰，& 后台运行
  bash -c "cd console && exec npx vite preview --port $DEV_PORT --strictPort" >"$REPORTS_DIR/preview-$TS.log" 2>&1 &
  DEV_PID=$!
  echo "  ℹ️  等待 preview server 就绪 (最多 15s)..."
  for i in $(seq 1 15); do
    if curl -sf "$DEV_URL" >/dev/null 2>&1; then
      pass "preview server 已就绪 (pid=$DEV_PID, port=$DEV_PORT)"
      break
    fi
    sleep 1
  done
  if ! curl -sf "$DEV_URL" >/dev/null 2>&1; then
    bad "preview server 15s 内未就绪，见 $REPORTS_DIR/preview-$TS.log"
    tail -5 "$REPORTS_DIR/preview-$TS.log" >&2
    exit 1
  fi
else
  # dev 模式：复用或启动 dev server
  if curl -sf "$DEV_URL" >/dev/null 2>&1; then
    pass "dev server 已运行 ($DEV_URL)"
  else
    echo "  ℹ️  dev server 未运行，尝试启动..."
    bash -c "cd console && exec npm run dev" >"$REPORTS_DIR/dev-server-$TS.log" 2>&1 &
    DEV_PID=$!
    echo "  ℹ️  等待 dev server 就绪 (最多 30s)..."
    for i in $(seq 1 30); do
      if curl -sf "$DEV_URL" >/dev/null 2>&1; then
        pass "dev server 已就绪 (pid=$DEV_PID)"
        break
      fi
      sleep 1
    done
    if ! curl -sf "$DEV_URL" >/dev/null 2>&1; then
      bad "dev server 30s 内未就绪，见 $REPORTS_DIR/dev-server-$TS.log"
      echo "  ℹ️  请手动启动: cd console && npm run dev"
      exit 1
    fi
  fi
fi

# ---------- 1. Lighthouse 审计 ----------
if [ "$MODE" = "all" ] || [ "$MODE" = "lighthouse" ]; then
  echo ""
  echo "== [G1] Lighthouse 审计 (LCP/FCP/CLS/TTFB) =="
  LH_REPORT="$REPORTS_DIR/lighthouse-$TS.json"
  LH_TMP=$(mktemp)

  # 跑 Lighthouse（headless Chrome，只采集性能指标，quiet 模式）
  ( cd console && npx lighthouse "$DEV_URL" \
      --output=json \
      --output-path="../$LH_REPORT" \
      --chrome-flags="--headless=new --no-sandbox" \
      --only-categories=performance \
      --throttling-method=simulate \
      --quiet 2>"$LH_TMP" )
  LH_EXIT=$?

  if [ $LH_EXIT -ne 0 ] || [ ! -f "$LH_REPORT" ]; then
    bad "Lighthouse 运行失败（exit=$LH_EXIT）"
    cat "$LH_TMP" >&2
    rm -f "$LH_TMP"
  else
    rm -f "$LH_TMP"
    # 提取关键指标
    LH_METRICS=$(python3 -c "
import json
d = json.load(open('$LH_REPORT'))
audits = d.get('audits', {})
def n(name):
    a = audits.get(name, {})
    return a.get('numericValue', 0)
lcp = n('largest-contentful-paint')
fcp = n('first-contentful-paint')
cls = n('cumulative-layout-shift') * 1000  # ×1000 转整数
ttfb = n('server-response-time')
si = n('speed-index')
tbt = n('total-blocking-time')
score = d.get('categories', {}).get('performance', {}).get('score', 0) * 100
print(f'{lcp:.0f} {fcp:.0f} {cls:.0f} {ttfb:.0f} {si:.0f} {tbt:.0f} {score:.0f}')
" 2>/dev/null || echo "0 0 0 0 0 0 0")

    set -- $LH_METRICS
    LCP="${1:-0}"; FCP="${2:-0}"; CLS="${3:-0}"; TTFB="${4:-0}"; SI="${5:-0}"; TBT="${6:-0}"; SCORE="${7:-0}"

    echo "  Lighthouse 性能指标:"
    echo "    Performance Score: ${SCORE}/100"
    echo "    LCP  (Largest Contentful Paint): ${LCP}ms  (目标 <${LCP_TARGET}, 报警 >${LCP_ALARM})"
    echo "    FCP  (First Contentful Paint):   ${FCP}ms  (目标 <${FCP_TARGET}, 报警 >${FCP_ALARM})"
    echo "    CLS  (Cumulative Layout Shift):  $(python3 -c "print(f'{$CLS/1000:.3f}')")  (目标 <$(python3 -c "print(f'{$CLS_TARGET/1000:.3f}')"), 报警 >$(python3 -c "print(f'{$CLS_ALARM/1000:.3f}')"))"
    echo "    TTFB (Time to First Byte):       ${TTFB}ms  (目标 <${TTFB_TARGET}, 报警 >${TTFB_ALARM})"
    echo "    SI   (Speed Index):              ${SI}ms"
    echo "    TBT  (Total Blocking Time):      ${TBT}ms"

    # 阈值检查
    [ "${LCP%.*}" -le "$LCP_TARGET" ] && pass "LCP ${LCP}ms ≤ ${LCP_TARGET}ms" || { [ $CI_MODE = 1 ] && bad "LCP ${LCP}ms > ${LCP_TARGET}ms" || warn "LCP ${LCP}ms > ${LCP_TARGET}ms（软告警）"; }
    [ "${FCP%.*}" -le "$FCP_TARGET" ] && pass "FCP ${FCP}ms ≤ ${FCP_TARGET}ms" || { [ $CI_MODE = 1 ] && bad "FCP ${FCP}ms > ${FCP_TARGET}ms" || warn "FCP ${FCP}ms > ${FCP_TARGET}ms（软告警）"; }
    [ "${CLS%.*}" -le "$CLS_TARGET" ] && pass "CLS ≤ 0.${CLS_TARGET}" || { [ $CI_MODE = 1 ] && bad "CLS > 0.${CLS_TARGET}" || warn "CLS > 0.${CLS_TARGET}（软告警）"; }
    [ "${TTFB%.*}" -le "$TTFB_TARGET" ] && pass "TTFB ${TTFB}ms ≤ ${TTFB_TARGET}ms" || { [ $CI_MODE = 1 ] && bad "TTFB ${TTFB}ms > ${TTFB_TARGET}ms" || warn "TTFB ${TTFB}ms > ${TTFB_TARGET}ms（软告警）"; }
  fi
fi

# ---------- 2. Playwright 交互流畅度基准 ----------
if [ "$MODE" = "all" ] || [ "$MODE" = "playwright" ]; then
  echo ""
  echo "== [G2] Playwright 交互流畅度基准 (FID/INP/FPS) =="
  PERF_LOG="$REPORTS_DIR/perf-playwright-$TS.log"

  ( cd console && npx playwright test performance/ \
      --project=chromium \
      --reporter=list 2>&1 ) | tee "$PERF_LOG" | grep -E "(✓|✘|passed|failed|FID|INP|FPS|✅|⚠️)" || true

  # grep -c 总会输出数字（即使无匹配=0），但退出码非 0 会触发 || echo "0" 导致双输出
  # 改用 ${:-0} 兜底空值，避免整数比较报 "integer expression expected"
  PW_PASS=$(grep -cE "✓" "$PERF_LOG" 2>/dev/null); PW_PASS="${PW_PASS:-0}"
  PW_FAIL=$(grep -cE "✘" "$PERF_LOG" 2>/dev/null); PW_FAIL="${PW_FAIL:-0}"
  # 去除可能的换行/空白
  PW_PASS=$(echo "$PW_PASS" | tr -d '[:space:]')
  PW_FAIL=$(echo "$PW_FAIL" | tr -d '[:space:]')
  echo "  Playwright 交互流畅度: passed=$PW_PASS failed=$PW_FAIL"

  if [ "${PW_FAIL:-0}" -gt 0 ]; then
    [ $CI_MODE = 1 ] && bad "Playwright perf 有 $PW_FAIL 个失败" || warn "Playwright perf 有 $PW_FAIL 个失败（软告警，见 $PERF_LOG）"
  else
    pass "Playwright 交互流畅度全部通过"
  fi
fi

# ---------- 3. 追加 PERF_LOG.md 趋势记录 ----------
echo ""
echo "== [G3] 追加 PERF_LOG.md 趋势记录 =="
PERF_LOG_MD="PERF_LOG.md"
if [ ! -f "$PERF_LOG_MD" ]; then
  echo "# flipped · 性能基准趋势日志（PERF_LOG.md）" > "$PERF_LOG_MD"
  echo "" >> "$PERF_LOG_MD"
  echo "| 时间 | LCP | FCP | CLS | TTFB | Perf Score | FID | INP P95 | FPS | 来源 |" >> "$PERF_LOG_MD"
  echo "|------|-----|-----|-----|------|-----------|-----|---------|-----|------|" >> "$PERF_LOG_MD"
fi

# 从 Playwright 日志提取 FID/INP/FPS
# 注意：INP P95=0.60ms 里有两个数字（95 和 0.60），grep -oE "[0-9.]+" 会匹配两个
# 改用 sed 精确提取 = 和 ms 之间的数值
PW_FID=$(grep -oE "FID=[0-9.]+ms" "$REPORTS_DIR/perf-playwright-$TS.log" 2>/dev/null | head -1 | sed 's/FID=\([0-9.]*\)ms/\1/' || echo "N/A")
PW_INP=$(grep -oE "INP P95=[0-9.]+ms" "$REPORTS_DIR/perf-playwright-$TS.log" 2>/dev/null | head -1 | sed 's/INP P95=\([0-9.]*\)ms/\1/' || echo "N/A")
PW_FPS=$(grep -oE "空闲 FPS: [0-9.]+" "$REPORTS_DIR/perf-playwright-$TS.log" 2>/dev/null | head -1 | sed 's/空闲 FPS: \([0-9.]*\)/\1/' || echo "N/A")
PW_FID="${PW_FID:-N/A}"; PW_INP="${PW_INP:-N/A}"; PW_FPS="${PW_FPS:-N/A}"

# 追加一行（来源含 dev/prod 模式标记，便于趋势对比）
LH_LCP="${LCP:-N/A}"; LH_FCP="${FCP:-N/A}"; LH_CLS="${CLS:-N/A}"; LH_TTFB="${TTFB:-N/A}"; LH_SCORE="${SCORE:-N/A}"
SRC_TAG=$([ $PROD_MODE = 1 ] && echo "prod" || echo "dev")
echo "| $TS | ${LH_LCP}ms | ${LH_FCP}ms | $(echo "$LH_CLS" | python3 -c "import sys; v=float(sys.stdin.read()); print(f'{v/1000:.3f}')" 2>/dev/null || echo "N/A") | ${LH_TTFB}ms | ${LH_SCORE}/100 | ${PW_FID}ms | ${PW_INP}ms | ${PW_FPS} | lighthouse+playwright($SRC_TAG) |" >> "$PERF_LOG_MD"

pass "趋势已追加到 $PERF_LOG_MD"

# ---------- 汇总 ----------
echo ""
echo "============================================================"
echo "  产出物:"
echo "    - Lighthouse 报告: $LH_REPORT"
echo "    - Playwright 日志: $REPORTS_DIR/perf-playwright-$TS.log"
echo "    - 趋势记录:       $PERF_LOG_MD"
echo "============================================================"
if [ $fail -eq 0 ]; then
  echo "  性能审计: 通过 ✅"
else
  echo "  性能审计: 未通过 ❌（见上方 ❌ 项）"
fi
echo "============================================================"
exit $fail
