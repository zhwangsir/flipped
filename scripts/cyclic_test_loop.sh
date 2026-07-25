#!/usr/bin/env bash
# cyclic_test_loop.sh · 循环测试常态化驱动（M154.1）。
#
# 类似 heartbeat.py 的循环结构，但驱动 loop_test.sh 跑系统性循环测试。
# 默认每 6 小时跑一次（3 轮 --quick 模式），可设环境变量调整。
#
# 用法（后台运行）：
#   nohup bash scripts/cyclic_test_loop.sh >> reports/cyclic_test_loop.log 2>&1 &
#   disown
#
# 环境变量：
#   CYCLIC_INTERVAL_S    循环间隔秒数（默认 21600 = 6h）
#   CYCLIC_ROUNDS        每次循环跑几轮（默认 3）
#   CYCLIC_QUICK         1=--quick 模式（跳过全量 pytest），0=full 模式（默认 1）
#   CYCLIC_DELAY_S       启动延迟秒数（首次跑前等待，避开其他任务，默认 0）
set -uo pipefail
cd "$(dirname "$0")/.."

INTERVAL_S="${CYCLIC_INTERVAL_S:-21600}"      # 6h
ROUNDS="${CYCLIC_ROUNDS:-3}"
QUICK="${CYCLIC_QUICK:-1}"
DELAY_S="${CYCLIC_DELAY_S:-0}"

mkdir -p reports

echo "============================================================"
echo "  循环测试常态化驱动 · cyclic_test_loop.sh（M154.1）"
echo "  间隔: ${INTERVAL_S}s ($(($INTERVAL_S / 3600))h)"
echo "  每次轮数: ${ROUNDS}  模式: $([ $QUICK = 1 ] && echo quick || echo full)"
echo "  启动延迟: ${DELAY_S}s"
echo "  开始: $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"

# 启动延迟（避开其他正在跑的任务，如覆盖率深化）
if [ "$DELAY_S" -gt 0 ]; then
  echo "[$(date)] 等待 ${DELAY_S}s 后开始首次循环测试..."
  sleep "$DELAY_S"
fi

iteration=0
while true; do
  iteration=$((iteration + 1))
  iter_ts=$(date '+%Y-%m-%dT%H:%M:%S')
  echo ""
  echo "############################################################"
  echo "#  迭代 #$iteration · $iter_ts"
  echo "############################################################"

  GATE_ARGS=""
  if [ "$QUICK" = 1 ]; then
    GATE_ARGS="--quick"
  fi

  # 跑循环测试（3 轮 quick，连续 2 轮全绿提前收尾）
  bash scripts/loop_test.sh "$ROUNDS" $GATE_ARGS

  end_ts=$(date '+%Y-%m-%dT%H:%M:%S')
  echo ""
  echo "[$end_ts] 迭代 #$iteration 完成，${INTERVAL_S}s ($(($INTERVAL_S / 3600))h) 后进入下一次"
  echo ""

  # 写一行结构化摘要到 history
  python3 -c "
import json, os
from datetime import datetime
entry = {
    'iteration': $iteration,
    'ts': '$end_ts',
    'interval_s': $INTERVAL_S,
    'rounds': $ROUNDS,
    'mode': 'quick' if $QUICK == 1 else 'full',
}
with open('reports/cyclic_test_history.jsonl', 'a') as f:
    f.write(json.dumps(entry, ensure_ascii=False) + '\n')
" 2>/dev/null || true

  sleep "$INTERVAL_S"
done
