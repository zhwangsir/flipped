#!/usr/bin/env bash
# loop_test.sh · 系统性循环测试驱动（TEST_PLAN.md §4）。
#
# 多轮跑 quality_gate.sh，每轮采集指标 → 若失败则记录缺陷 → 修复 → 复跑。
# 连续 2 轮全绿 + 无新缺陷 → 提前收尾。单缺陷修 ≥3 次仍失败 → 熔断停止。
#
# 用法:
#   bash scripts/loop_test.sh              # 默认 3 轮
#   bash scripts/loop_test.sh 5            # 5 轮
#   bash scripts/loop_test.sh 3 --quick    # 快速模式（跳过全量 pytest）
#   bash scripts/loop_test.sh 3 --no-cov   # 跳过覆盖率
#
# 产出:
#   - quality_metrics_history.jsonl  每轮指标追加（趋势分析）
#   - DEFECT_LOG.md                  缺陷流水（手动/自动记录）
#   - TEST_LOG.md                     每轮证据追加
set -uo pipefail
cd "$(dirname "$0")/.."

MAX_ROUNDS=3
GATE_ARGS=()
for a in "$@"; do
  case "$a" in
    --quick) GATE_ARGS+=("--quick") ;;
    --no-cov) GATE_ARGS+=("--no-cov") ;;
    ''|*[0-9]*) MAX_ROUNDS="$a" ;;
  esac
done

HISTORY=quality_metrics_history.jsonl
DEFECT_LOG=DEFECT_LOG.md
TOUCH_TS=$(date +"%Y-%m-%d %H:%M:%S")

# 初始化缺陷日志（若不存在）
if [ ! -f "$DEFECT_LOG" ]; then
  cat > "$DEFECT_LOG" <<'EOF'
# flipped · 缺陷日志（DEFECT_LOG.md）

> 循环测试过程中发现的所有缺陷流水。格式见 TEST_PLAN.md §5。
> 每条缺陷结构化记录，便于趋势分析与复发检测。

| ID | 轮次 | 级别 | 类型 | 现象 | 根因 | 修复 | 验证 | 状态 | 复发 |
|---|---|---|---|---|---|---|---|---|---|

EOF
fi

echo "============================================================"
echo "  循环测试 · loop_test.sh（TEST_PLAN.md §4）"
echo "  最大轮次: $MAX_ROUNDS  门禁参数: ${GATE_ARGS[*]:-（无）}"
echo "  开始: $TOUCH_TS"
echo "============================================================"

consecutive_green=0
prev_py_passed=0

for round in $(seq 1 $MAX_ROUNDS); do
  echo ""
  echo "############################################################"
  echo "#  Round $round / $MAX_ROUNDS"
  echo "############################################################"

  # 跑门禁（${arr[@]+"${arr[@]}"} 避免 set -u 下空数组报错）
  bash scripts/quality_gate.sh ${GATE_ARGS[@]+"${GATE_ARGS[@]}"}
  GATE_EXIT=$?

  # 采集本轮指标
  if [ -f quality_metrics.json ]; then
    ROUND_TS=$(date +"%Y-%m-%dT%H:%M:%S")
    python3 -c "
import json, sys
m=json.load(open('quality_metrics.json'))
m['round']=$round
m['ts']='$ROUND_TS'
m['gate_pass']=1 if $GATE_EXIT==0 else 0
with open('$HISTORY','a') as f:
    f.write(json.dumps(m,ensure_ascii=False)+'\n')
print('  指标已追加到 $HISTORY')
"

    # 趋势对比
    CUR_PY=$(python3 -c "import json;print(json.load(open('quality_metrics.json')).get('py_passed',0))")
    if [ "$round" -gt 1 ] && [ "$prev_py_passed" -gt 0 ]; then
      if [ "$CUR_PY" -lt "$prev_py_passed" ]; then
        echo "  ⚠️  Python passed 数下降: $prev_py_passed → ${CUR_PY}（回归警告）"
      fi
    fi
    prev_py_passed=$CUR_PY
  fi

  if [ $GATE_EXIT -eq 0 ]; then
    consecutive_green=$((consecutive_green + 1))
    echo ""
    echo "  Round $round: 门禁全绿 ✅（连续 $consecutive_green 轮）"
    if [ $consecutive_green -ge 2 ]; then
      echo "  → 连续 2 轮全绿，提前收尾。"
      break
    fi
  else
    consecutive_green=0
    echo ""
    echo "  Round $round: 门禁未通过 ❌"
    echo "  → 请分析上方失败项，记录缺陷到 ${DEFECT_LOG}，修复后进入下一轮。"
    echo "  → 熔断规则：同一缺陷修 ≥3 次仍失败 → 停止上报（TEST_PLAN.md §4.3）。"
    # 不自动 break——给修复机会后继续下一轮。但若已达上限，自然退出。
  fi
done

echo ""
echo "============================================================"
echo "  循环测试结束: $(date +'%Y-%m-%d %H:%M:%S')"
echo "  历史指标: ${HISTORY}（每轮一行 JSON）"
echo "  缺陷日志: $DEFECT_LOG"
echo "============================================================"
echo ""
echo "  趋势汇总（最近 $MAX_ROUNDS 轮）:"
if [ -f "$HISTORY" ]; then
  python3 -c "
import json
rows=[json.loads(l) for l in open('$HISTORY') if l.strip()]
print(f\"  {'轮次':<6}{'门禁':<6}{'py_passed':<12}{'py_cov':<10}{'fe_passed':<10}{'fe_lines':<10}{'tsc':<6}{'build':<6}\")
for r in rows:
    print(f\"  {r.get('round','?'):<6}{'✅' if r.get('gate_pass') else '❌':<6}{r.get('py_passed','-'):<12}{str(r.get('py_coverage','-'))+'%':<10}{r.get('fe_passed','-'):<10}{str(r.get('fe_lines_cov','-'))+'%':<10}{r.get('tsc_errors','-'):<6}{r.get('build_ok','-'):<6}\")
"
fi

exit 0
