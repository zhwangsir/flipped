#!/usr/bin/env bash
# check_shell_lint.sh · 守卫：$VAR 后直接跟全角/非 ASCII 字节（M144-A 陷阱复发防护）。
#
# 背景：bash 在某些 locale 下会把 `$IDENT` 后的多字节字符（如中文全角括号
# `）`、全角逗号 `，`）当作变量名的一部分，导致 `set -u` 下报
# `PY_FAILED\xxx: unbound variable` 而非真正未定义。
# 修复一律 `${VAR}` 显式大括号（AGENTS.md M144-A 节陷阱警告）。
#
# 用法：
#   bash scripts/check_shell_lint.sh            # 扫 scripts/*.sh
#   bash scripts/check_shell_lint.sh file1 ...  # 扫指定文件
# 退出码：0=无陷阱 / 1=发现陷阱（含行号与建议修复）
set -uo pipefail
cd "$(dirname "$0")/.."

if [ $# -eq 0 ]; then
  TARGETS=(scripts/*.sh)
else
  TARGETS=("$@")
fi

# Python 正则：$IDENT 后紧跟非 ASCII 字节（0x80-0xFF）
FAIL=0
for f in "${TARGETS[@]}"; do
  [ -f "$f" ] || continue
  HIT=$(python3 - "$f" <<'PY'
import re, sys, pathlib
raw = pathlib.Path(sys.argv[1]).read_bytes()
pat = re.compile(rb'\$([A-Za-z_][A-Za-z0-9_]*)(?=[\x80-\xff])')
hits = []
for i, line in enumerate(raw.split(b'\n'), 1):
    for m in pat.finditer(line):
        var = m.group(1).decode()
        ctx = line.decode('utf-8', errors='replace').strip()[:120]
        hits.append(f"  L{i}: ${var} 后跟非 ASCII 字节 | {ctx}")
print('\n'.join(hits))
PY
)
  if [ -n "$HIT" ]; then
    echo "❌ $f 发现 \${VAR}<全角字符> 陷阱（应改用 \${VAR} 显式大括号）："
    echo "$HIT"
    FAIL=1
  fi
done

if [ $FAIL -eq 0 ]; then
  echo "✅ shell lint: 无 \$VAR<非 ASCII> 陷阱（${#TARGETS[@]} 文件扫描通过）"
fi
exit $FAIL
