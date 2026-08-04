#!/usr/bin/env bash
# M184 验收 — known_limitations 系统性分析与消化（注册表 + 分类 + 状态跟踪 +
# markdown 报告 + CI 一致性检查门禁）。
#
#   1) pytest 单测：test_m184_limitations.py（20 例：harvest 新建/幂等/保留人工字段/
#      源移除 wontfix；classify 六类关键词/不踩人工；check 齐全 exit 0/缺失 exit 1；
#      set-status 往返/未知 id；report 五节/矩阵/路线图；tmp+os.replace 原子写）
#   2) 真实数据流（对真 STATE.json + 真 data/limitations_registry.json）：
#        a. harvest：42 条全量登记（M171–M181），id 形如 L-M{n}-{i}，人工字段默认值齐
#        b. harvest 幂等：二次跑 0 added，条目数不变
#        c. classify：exit 0，registry 出现六类之一的关键词分类（不保证全覆盖）
#        d. set-status：L-M180-1 / L-M181-5 置 resolved（M183/M182 消化）+ 注记；
#           未知 id → exit 1
#        e. report：reports/limitations_analysis_<YYYYMMDD>.md 落盘，
#           五节标题齐 + 「已消化」含 L-M180-1 / L-M181-5
#        f. check 正例：真 STATE.json → exit 0
#        g. check 反例：篡改的 STATE 副本（多一条未登记限制）→ exit 1 且打印缺失 id
#
# 一键复跑: scripts/verify_m184.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
fail=0; pass(){ echo "  ✅ $1"; }; bad(){ echo "  ❌ $1"; fail=1; }

REG="data/limitations_registry.json"
REPORT="reports/limitations_analysis_$(date +%Y%m%d).md"
TMPD=$(mktemp -d)
trap 'rm -rf "$TMPD"' EXIT

echo "== M184-1 单测（20 例） =="
PYTHONPATH=src $PY -m pytest tests/test_m184_limitations.py -q \
  && pass "M184 单测全绿" || bad "M184 单测失败"

echo "== M184-2 真实数据流（STATE.json ×42 → registry → classify → set-status → report → check 正反例） =="

# ---------- a. harvest：42 条登记 ----------
OUT=$($PY scripts/limitations_report.py harvest --state STATE.json --registry "$REG" 2>&1)
echo "  $OUT"
echo "$OUT" | grep -qE "^harvested [0-9]+ limitations \([0-9]+ added, [0-9]+ stale\)$" \
  && pass "a1.harvest exit 0 且打印摘要格式正确" || bad "a1.harvest 摘要格式异常: $OUT"
$PY - "$REG" <<'PYEOF'
import json, re, sys
reg = json.load(open(sys.argv[1], encoding="utf-8"))
lims = reg["limitations"]
ok = (len(lims) == 42
      and all(re.fullmatch(r"L-M\d+-\d+", lim.get("id", "")) for lim in lims)
      and all(lim.get("status") in ("open", "in_progress", "resolved", "wontfix") for lim in lims)
      and all("category" in lim and "priority" in lim and "difficulty" in lim
              and "impact" in lim and "resolution_note" in lim and "target" in lim
              for lim in lims))
sys.exit(0 if ok else 1)
PYEOF
[ $? -eq 0 ] && pass "a2.registry 42 条：id 格式 L-M{n}-{i} + 人工字段齐" \
             || bad "a2.registry 条目数/字段异常"

# ---------- b. harvest 幂等 ----------
OUT=$($PY scripts/limitations_report.py harvest --state STATE.json --registry "$REG" 2>&1)
echo "$OUT" | grep -q "harvested 42 limitations (0 added, 0 stale)" \
  && pass "b.harvest 幂等：二次跑 0 added 0 stale" || bad "b.harvest 非幂等: $OUT"

# ---------- c. classify ----------
OUT=$($PY scripts/limitations_report.py classify --registry "$REG" 2>&1)
echo "  $OUT"
$PY - "$REG" <<'PYEOF'
import json, sys
reg = json.load(open(sys.argv[1], encoding="utf-8"))
cats = {lim.get("category") for lim in reg["limitations"]}
known = {"安全", "功能缺口", "性能", "测试覆盖", "数据一致性", "架构取舍"}
sys.exit(0 if cats & known else 1)
PYEOF
[ $? -eq 0 ] && pass "c.classify exit 0 且六类关键词至少一类命中" \
             || bad "c.classify 未命中任何已知分类"

# ---------- d. set-status：两条 resolved（M183/M182 消化）+ 未知 id 反例 ----------
OUT=$($PY scripts/limitations_report.py set-status L-M180-1 resolved \
  --note "M183 消化：worker 规则注入系统落地（agent 通路手动 CRUD + auto 通路自动生成 + 版本回滚 + 执行效果统计）" \
  --registry "$REG" 2>&1)
echo "  $OUT"
echo "$OUT" | grep -q "L-M180-1: .* → resolved" \
  && pass "d1.L-M180-1 → resolved（M183 消化）" || bad "d1.set-status L-M180-1 失败: $OUT"
OUT=$($PY scripts/limitations_report.py set-status L-M181-5 resolved \
  --note "M182 消化：Bot Channel 多平台接入落地（Telegram webhook + 企业微信回调 + 统一消息接口 + 状态监控）" \
  --registry "$REG" 2>&1)
echo "  $OUT"
echo "$OUT" | grep -q "L-M181-5: .* → resolved" \
  && pass "d2.L-M181-5 → resolved（M182 消化）" || bad "d2.set-status L-M181-5 失败: $OUT"
$PY scripts/limitations_report.py set-status L-M999-9 resolved --registry "$REG" >/dev/null 2>&1
[ $? -eq 1 ] && pass "d3.set-status 未知 id → exit 1" || bad "d3.set-status 未知 id 未返回 1"
$PY - "$REG" <<'PYEOF'
import json, sys
reg = json.load(open(sys.argv[1], encoding="utf-8"))
by_id = {lim["id"]: lim for lim in reg["limitations"]}
ok = (by_id.get("L-M180-1", {}).get("status") == "resolved"
      and "M183" in by_id["L-M180-1"].get("resolution_note", "")
      and by_id.get("L-M181-5", {}).get("status") == "resolved"
      and "M182" in by_id["L-M181-5"].get("resolution_note", ""))
sys.exit(0 if ok else 1)
PYEOF
[ $? -eq 0 ] && pass "d4.registry 落盘：两条 resolved + 注记含 M183/M182" \
             || bad "d4.registry resolved 状态/注记异常"

# ---------- e. report：五节标题 + 已消化含两条 ----------
OUT=$($PY scripts/limitations_report.py report --registry "$REG" --out "$REPORT" 2>&1)
echo "  $OUT"
[ -f "$REPORT" ] \
  && grep -q "## 1. 总览" "$REPORT" \
  && grep -q "## 2. 全量明细" "$REPORT" \
  && grep -q "## 3. 优先级×难度矩阵" "$REPORT" \
  && grep -q "## 4. 分阶段路线图" "$REPORT" \
  && grep -q "## 5. 跟踪机制说明" "$REPORT" \
  && pass "e1.report 落盘且五节标题齐（${REPORT}）" || bad "e1.report 缺节或未落盘"
grep -q "L-M180-1" "$REPORT" && grep -q "L-M181-5" "$REPORT" \
  && grep -q "总数：42" "$REPORT" \
  && pass "e2.report 含全部关键 id 与总数 42" || bad "e2.report 缺 id/总数"
awk '/### 已消化/,/### 当前迭代 P0/' "$REPORT" | grep -q "L-M180-1" \
  && awk '/### 已消化/,/### 当前迭代 P0/' "$REPORT" | grep -q "L-M181-5" \
  && pass "e3.「已消化」节含 L-M180-1 / L-M181-5" || bad "e3.「已消化」节缺已消化条目"

# ---------- f. check 正例 ----------
OUT=$($PY scripts/limitations_report.py check --state STATE.json --registry "$REG" 2>&1)
RC=$?
echo "  $OUT"
[ $RC -eq 0 ] && echo "$OUT" | grep -q "check ok: 42 limitations registered" \
  && pass "f.check 正例：exit 0 + 42 条登记" || bad "f.check 正例失败: rc=$RC $OUT"

# ---------- g. check 反例：篡改 STATE 副本多一条未登记 ----------
$PY - "$TMPD/state_tampered.json" <<'PYEOF'
import json, sys
state = json.load(open("STATE.json", encoding="utf-8"))
state["milestones"]["M171"]["known_limitations"].append("M184反例假限制：未登记进registry")
json.dump(state, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False)
PYEOF
OUT=$($PY scripts/limitations_report.py check --state "$TMPD/state_tampered.json" --registry "$REG" 2>&1)
RC=$?
[ $RC -eq 1 ] && echo "$OUT" | grep -q "missing limitations in registry" \
  && echo "$OUT" | grep -q "L-M171-4" \
  && pass "g.check 反例：exit 1 + 打印缺失 id L-M171-4" || bad "g.check 反例失败: rc=$RC $OUT"

echo ""
if [ $fail -eq 0 ]; then
  echo "M184（known_limitations 系统性分析与消化）验收：通过 ✅"
else
  echo "M184 验收：有未通过 ❌"
fi
exit $fail
