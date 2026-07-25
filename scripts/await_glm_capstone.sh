#!/usr/bin/env bash
# 等 architect(GLM) 就绪 → 自动跑多Agent监督编排 capstone(多文件任务) → 落日志。
# 只读探针(不改集群/配置)。每 180s 探一次，最多 30 次(90min)。
set -uo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; . ./.env; set +a; }
export PATH="$PATH:/opt/homebrew/bin"
export NO_PROXY="localhost,127.0.0.1,100.64.201.37,::1"; export no_proxy="$NO_PROXY"
export LITELLM_BASE_URL="http://localhost:4000/v1"
mkdir -p logs; LOG=logs/capstone-await.log
PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"
say(){ echo "$(date '+%H:%M:%S') $1" | tee -a "$LOG"; }

say "等待 architect(GLM) 就绪（每 180s 探针, 上限 90min）..."
ready=0
for i in $(seq 1 30); do
  rc=$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 http://localhost:4000/v1/chat/completions \
    -H "Authorization: Bearer ${LITELLM_MASTER_KEY:-}" -H 'Content-Type: application/json' \
    -d '{"model":"architect","messages":[{"role":"user","content":"hi"}],"max_tokens":4}' 2>/dev/null || echo 000)
  if [ "$rc" = "200" ]; then ready=1; say "✅ architect 就绪(第 $i 次探针)"; break; fi
  say "  第 $i 次 architect=${rc}，180s 后重试"
  sleep 180
done
[ "$ready" = "1" ] || { say "❌ 90min 内 GLM 仍未就绪，退出（请确认 exo 上 GLM-5.2-fp8 加载完成）。"; exit 1; }

say "===== 跑 capstone：多Agent监督编排 / 多文件任务 ====="
F=$(mktemp -d)
printf 'import calc, main\nassert calc.add(2,3)==5\nassert calc.sub(5,1)==4\nassert main.run()==11, main.run()\nprint("OK")\n' > "$F/test_calc.py"
( cd "$F" && git init -q && git add -A && git -c user.name=t -c user.email=t@t commit -qm base )
"$PY" - "$F" >> "$LOG" 2>&1 <<'PYEOF'
import sys, os
sys.path.insert(0, "src")
from driving.orchestrator import drive_orchestrated
F = sys.argv[1]
final = drive_orchestrated(
    goal="在工作目录创建 calc.py(含 add(a,b) 返回 a+b 和 sub(a,b) 返回 a-b) 和 main.py(含 run() 返回 calc.add(2,3)+calc.sub(10,4))，使 'python3 test_calc.py' 打印 OK 且退出 0。",
    cwd=F, verify_cmd=["python3", "test_calc.py"], max_iterations=4,
    data_dir=os.path.abspath(".cline-data"), db_path=os.path.join(F, "cap.sqlite"), thread_id="capstone-await")
print("RESULT verified:", final.get("verified"), "| stop_reason:", final.get("stop_reason"), "| iterations:", final.get("iteration"))
for h in final.get("history", []):
    s = h.get("step")
    if s == "supervisor": print("  [GLM 调度]", str(h.get("subtask"))[:80])
    elif s == "worker": print("  [Kimi 执行]", h.get("summary"))
    elif s == "overseer":
        v = h.get("verdict", {}); print("  [GLM 监督] action=%s eff=%s dir=%s" % (v.get("action"), v.get("efficiency"), v.get("direction")))
    elif s == "verify": print("  [强制验证] ok=%s it=%s" % (h.get("ok"), h.get("iteration")))
# M146：退出码契约——编排未通过验证必须 exit 非 0，CI/调度器才能判失败（此前恒 exit 0）
sys.exit(0 if final.get("verified") else 1)
PYEOF
rc=$?
say "终态测试: $(cd "$F" && python3 test_calc.py 2>&1 | tail -1)"
rm -rf "$F"
if [ "$rc" -ne 0 ]; then
  say "❌ capstone 未通过(verified=false, exit $rc)"
  exit "$rc"
fi
say "===== capstone 完成（详见本日志上方 RESULT/轨迹）====="
