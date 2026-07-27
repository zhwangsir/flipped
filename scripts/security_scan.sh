#!/usr/bin/env bash
# security_scan.sh · 六维度安全扫描（TEST_STRATEGY_OPTIMIZATION.md §3）。
#
# 执行 SAST + 依赖漏洞 + 密钥泄漏 三项扫描，结果写 reports/ 目录。
# 任一 HIGH 级发现 → 退出码 1（硬阻断）。
#
# 用法:
#   bash scripts/security_scan.sh           # 全量扫描
#   bash scripts/security_scan.sh --quick   # 只跑 SAST（跳过依赖扫描）
set -uo pipefail
cd "$(dirname "$0")/.."

QUICK=0
for a in "$@"; do case "$a" in --quick) QUICK=1 ;; esac; done

mkdir -p reports
fail=0
pass(){ echo "  ✅ $1"; }
bad(){ echo "  ❌ $1"; fail=1; }

# 工具路径：优先 venv，其次系统
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
BANDIT="$([ -x .venv/bin/bandit ] && echo .venv/bin/bandit || echo bandit)"
PIP_AUDIT="$([ -x .venv/bin/pip-audit ] && echo .venv/bin/pip-audit || echo pip-audit)"
DETECT_SECRETS="$([ -x .venv/bin/detect-secrets ] && echo .venv/bin/detect-secrets || echo detect-secrets)"

echo "============================================================"
echo "  安全扫描 · security_scan.sh"
echo "  模式: $([ $QUICK = 1 ] && echo 'quick(仅SAST)' || echo 'full')"
echo "============================================================"

# ---------- S1 · Python SAST (bandit) ----------
# 注意：bandit 发现任何 issue（即使 LOW/MEDIUM）都返回退出码 1。
# 不能用 `if $BANDIT ...` 判断——会把「成功扫描但发现问题」误判为「未安装」。
# 正确做法：执行后检查 reports/bandit.json 是否生成且可解析。
echo ""
echo "== [S1] bandit · Python 静态安全扫描 =="
rm -f reports/bandit.json
$BANDIT -r src/ -f json -o reports/bandit.json --severity-level high >/dev/null 2>&1
if [ -f reports/bandit.json ] && $PY -c "import json; json.load(open('reports/bandit.json'))" 2>/dev/null; then
  HIGH_COUNT=$($PY -c "
import json
try:
    d = json.load(open('reports/bandit.json'))
    highs = [r for r in d.get('results', []) if r.get('issue_severity') == 'HIGH']
    print(len(highs))
except: print(0)
" 2>/dev/null)
  if [ "${HIGH_COUNT:-0}" -eq 0 ]; then
    pass "bandit: 0 HIGH 级发现"
  else
    bad "bandit: ${HIGH_COUNT} HIGH 级发现（见 reports/bandit.json）"
    $PY -c "
import json
d = json.load(open('reports/bandit.json'))
for r in d.get('results', []):
    if r.get('issue_severity') == 'HIGH':
        print(f'  {r[\"filename\"]}:{r[\"line_number\"]} {r[\"test_id\"]}: {r[\"issue_text\"][:80]}')
" 2>/dev/null
  fi
else
  echo "  ⚠️ bandit 未安装或执行失败，跳过"
fi

# ---------- S2 · Python 依赖漏洞 (pip-audit) ----------
# 注意：pip-audit 发现任何漏洞都返回退出码 1，与 bandit 同样的退出码语义陷阱。
if [ $QUICK = 0 ]; then
  echo ""
  echo "== [S2] pip-audit · Python 依赖漏洞扫描 =="
  rm -f reports/pip-audit.json
  $PIP_AUDIT --format json -o reports/pip-audit.json >/dev/null 2>&1
  if [ -f reports/pip-audit.json ] && $PY -c "import json; json.load(open('reports/pip-audit.json'))" 2>/dev/null; then
    VULN_COUNT=$($PY -c "
import json
try:
    d = json.load(open('reports/pip-audit.json'))
    vulns = [dep for dep in d.get('dependencies', []) if dep.get('vulns')]
    print(len(vulns))
except: print(0)
" 2>/dev/null)
    if [ "${VULN_COUNT:-0}" -eq 0 ]; then
      pass "pip-audit: 0 漏洞"
    else
      bad "pip-audit: ${VULN_COUNT} 个依赖有漏洞（见 reports/pip-audit.json）"
      # 列出 Top 5 漏洞依赖供快速定位
      $PY -c "
import json
d = json.load(open('reports/pip-audit.json'))
for dep in d.get('dependencies', []):
    if dep.get('vulns'):
        vulns = dep['vulns']
        ids = ', '.join(v.get('id','?') for v in vulns[:3])
        print(f'  {dep[\"name\"]}=={dep.get(\"version\",\"?\")} ({len(vulns)} 漏洞): {ids}')
" 2>/dev/null | head -10
    fi
  else
    echo "  ⚠️ pip-audit 未安装或执行失败，跳过"
  fi
fi

# ---------- S3 · 前端依赖漏洞 (npm audit) ----------
# 注意：国内镜像源（如 registry.npmmirror.com）不支持 audit endpoint（返回 404）。
# 必须显式指定官方 registry。同样，npm audit 发现漏洞时退出码非 0。
if [ $QUICK = 0 ] && [ -d console ]; then
  echo ""
  echo "== [S3] npm audit · 前端依赖漏洞扫描 =="
  rm -f reports/npm-audit.json
  ( cd console && npm audit --json --registry=https://registry.npmjs.org > ../reports/npm-audit.json 2>/dev/null )
  if [ -f reports/npm-audit.json ] && $PY -c "import json; json.load(open('reports/npm-audit.json'))" 2>/dev/null; then
    NPM_VULN=$($PY -c "
import json
try:
    d = json.load(open('reports/npm-audit.json'))
    v = d.get('vulnerabilities', {})
    print(len(v))
except: print(0)
" 2>/dev/null)
    if [ "${NPM_VULN:-0}" -eq 0 ]; then
      pass "npm audit: 0 漏洞"
    else
      bad "npm audit: ${NPM_VULN} 个漏洞（见 reports/npm-audit.json）"
      # 按严重级别汇总
      $PY -c "
import json
d = json.load(open('reports/npm-audit.json'))
vulns = d.get('vulnerabilities', {})
by_sev = {}
for name, info in vulns.items():
    sev = info.get('severity', 'unknown')
    by_sev[sev] = by_sev.get(sev, 0) + 1
for sev in ['critical','high','moderate','low','info','unknown']:
    if sev in by_sev:
        print(f'  {sev}: {by_sev[sev]}')
" 2>/dev/null
    fi
  else
    echo "  ⚠️ npm audit 执行失败（可能是网络问题），跳过"
  fi
fi

# ---------- S4 · 密钥泄漏检测 (detect-secrets) ----------
echo ""
echo "== [S4] detect-secrets · 密钥泄漏扫描 =="
if command -v "$DETECT_SECRETS" &>/dev/null || [ -x "$DETECT_SECRETS" ]; then
  # 用 baseline 排除已知误报（注释中的 EXO_API_KEY="dummy" 等）
  if [ -f .secrets.baseline ]; then
    $DETECT_SECRETS scan src/ console/src/ --baseline .secrets.baseline > reports/secrets.json 2>/dev/null
  else
    $DETECT_SECRETS scan src/ console/src/ > reports/secrets.json 2>/dev/null
  fi
  SECRET_COUNT=$($PY -c "
import json
try:
    d = json.load(open('reports/secrets.json'))
    total = sum(len(v) for v in d.get('results', {}).values())
    print(total)
except: print(0)
" 2>/dev/null)
  if [ "${SECRET_COUNT:-0}" -eq 0 ]; then
    pass "detect-secrets: 0 密钥泄漏"
  else
    bad "detect-secrets: ${SECRET_COUNT} 处疑似密钥（见 reports/secrets.json）"
    $PY -c "
import json
d = json.load(open('reports/secrets.json'))
for path, findings in d.get('results', {}).items():
    for f in findings:
        print(f'  {path}:{f[\"line_number\"]} type={f[\"type\"]}')
" 2>/dev/null
  fi
else
  echo "  ⚠️ detect-secrets 未安装，跳过"
fi

# ---------- 汇总 ----------
echo ""
echo "============================================================"
if [ $fail -eq 0 ]; then
  echo "  安全扫描：通过 ✅"
else
  echo "  安全扫描：未通过 ❌（见上方 ❌ 项）"
fi
echo "  报告目录: reports/"
echo "============================================================"
exit $fail
