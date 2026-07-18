#!/usr/bin/env bash
# M139-A 验收 — 崩溃恢复 E2E 硬化。
#
#   1) pytest 单测：mock orchestrator 模拟 running 中崩溃 → resume 安全重跑、副作用不重复
#   2) 真实 kill -9 E2E：子进程慢 orchestrator 跑 factory，SIGKILL 后用同 factory_id resume，
#      断言 marker/事件幂等键/completed 均无重复
#
# 一键复跑: scripts/verify_m139_crash_resume.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

# 隔离：所有 DB 副作用指向临时库，不触碰真实 data/
TMPD=$(mktemp -d)
trap 'rm -rf "$TMPD"' EXIT
export FLIPPED_DB="$TMPD/flipped.db"

echo "== M139-A-1 崩溃恢复单测（mock orchestrator，running task 安全重跑） =="
PYTHONPATH=src $PY -m pytest tests/test_factory_crash_recovery.py -q \
  && pass "test_factory_crash_recovery.py 全绿" || bad "test_factory_crash_recovery.py 失败"

echo "== M139-A-2 真实 kill -9 E2E（子进程 SIGKILL → 同 factory_id resume） =="
$PY scripts/e2e_crash_resume.py \
  && pass "e2e_crash_resume.py 通过（无重复副作用，状态收敛 done）" || bad "e2e_crash_resume.py 失败"

echo ""
if [ $fail -eq 0 ]; then echo "M139-A（崩溃恢复 E2E 硬化）验收：通过 ✅"; else echo "M139-A 验收：有未通过 ❌"; fi
exit $fail
