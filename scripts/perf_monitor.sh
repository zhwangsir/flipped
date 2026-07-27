#!/usr/bin/env bash
# flipped · 并发性能 + 前端基线 + 资源监控一体脚本（TEST_STRATEGY_OPTIMIZATION.md §2.3）。
#
# 流程：
#   1. 启动 mock 后端（FLIPPED_MOCK_ORCHESTRATOR=1，独立 session store，避免污染 .sessions.json）
#   2. 启动 vite preview（生产构建，端口 5274；若已跑则复用）
#   3. 后台采样后端 + 前端进程的 CPU/内存（每 2 秒一次）
#   4. 跑 locust 60 秒（3 用户，spawn 1/s）
#   5. 跑 lighthouse（Assistant + Factory 视图）
#   6. 汇总资源峰值 + 性能数据 → reports/perf/perf_monitor.json
#
# 用法：
#   bash scripts/perf_monitor.sh [run_time_sec]
#   # 默认 60 秒；自定义：bash scripts/perf_monitor.sh 30
#
# 前置：
#   - .venv 已安装 locust（pip install locust）
#   - console/ 已 npm i -D lighthouse
#   - console/dist/ 存在（首次需先 npm run build）
#
# 产物：
#   reports/perf/locust_stats.json         locust 原始 stats
#   reports/perf/locust.html               locust HTML 报告
#   reports/perf/lighthouse_prod_*.json    lighthouse 各视图 JSON
#   reports/perf/perf_monitor.json         一体化汇总（机器可读）
#   reports/perf/perf_monitor.md           一体化汇总（人读）
set -uo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
BACKEND_PORT="${FLIPPED_BACKEND_PORT:-8011}"
PREVIEW_PORT="${FLIPPED_PREVIEW_PORT:-5274}"
RUN_TIME="${1:-60}"
PERF_DIR="$ROOT/reports/perf"
mkdir -p "$PERF_DIR"

# 导出到子进程（Python heredoc 需要读）
export ROOT RUN_TIME BACKEND_PORT PREVIEW_PORT PERF_DIR

# mock 后端用的独立 session store，避免污染真实 .sessions.json
MOCK_SESSIONS="$ROOT/.sessions.perf.json"

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
up() { curl -sf -o /dev/null -m 3 "$1" 2>/dev/null; }

# ---------- 1. 启动 mock 后端 ----------

say "1) 启动 mock 后端 (port $BACKEND_PORT)"
BACKEND_PID=""
if up "http://127.0.0.1:$BACKEND_PORT/api/v1/health"; then
  echo "  ✓ 后端已在运行（复用）"
  BACKEND_PID=$(pgrep -f "uvicorn api.main:app.*--port $BACKEND_PORT" | head -1)
else
  rm -f "$MOCK_SESSIONS"
  FLIPPED_MOCK_ORCHESTRATOR=1 FLIPPED_MOCK_WORKER=1 \
    FLIPPED_SESSION_STORE_PATH="$MOCK_SESSIONS" \
    PYTHONPATH=src nohup .venv/bin/python -m uvicorn api.main:app \
    --host 127.0.0.1 --port "$BACKEND_PORT" --log-level warning \
    > "$PERF_DIR/backend.log" 2>&1 &
  BACKEND_PID=$!
  echo "  · pid $BACKEND_PID → $PERF_DIR/backend.log"
  i=0; until up "http://127.0.0.1:$BACKEND_PORT/api/v1/health"; do
    i=$((i+1)); [ "$i" -gt 30 ] && { echo "  ✗ 后端启动超时"; exit 1; }; sleep 1
  done
  echo "  ✓ 后端就绪"
fi
echo "  backend_pid=$BACKEND_PID"

# ---------- 2. 启动 vite preview ----------

say "2) 启动 vite preview (port $PREVIEW_PORT)"
PREVIEW_PID=""
if up "http://127.0.0.1:$PREVIEW_PORT"; then
  echo "  ✓ preview 已在运行（复用）"
  PREVIEW_PID=$(pgrep -f "vite preview.*--port $PREVIEW_PORT" | head -1)
else
  if [ ! -d "$ROOT/console/dist" ]; then
    echo "  · dist/ 不存在，先 npm run build..."
    ( cd console && npm run build ) || { echo "  ✗ build 失败"; exit 1; }
  fi
  ( cd console && nohup npx vite preview --port "$PREVIEW_PORT" --host 127.0.0.1 \
    > "$PERF_DIR/preview.log" 2>&1 & )
  i=0; until up "http://127.0.0.1:$PREVIEW_PORT"; do
    i=$((i+1)); [ "$i" -gt 30 ] && { echo "  ✗ preview 启动超时"; exit 1; }; sleep 1
  done
  PREVIEW_PID=$(pgrep -f "vite preview.*--port $PREVIEW_PORT" | head -1)
  echo "  ✓ preview 就绪 (pid $PREVIEW_PID)"
fi

# ---------- 3. 资源采样（后台） ----------

say "3) 启动资源采样（每 2s 一次，覆盖整个压测周期）"
SAMPLES_FILE="$PERF_DIR/resource_samples.csv"
echo "timestamp,backend_cpu,backend_rss_mb,preview_cpu,preview_rss_mb" > "$SAMPLES_FILE"

sample_loop() {
  local end_ts=$(( $(date +%s) + RUN_TIME + 30 ))  # 多采 30s 覆盖 lighthouse 阶段
  while [ "$(date +%s)" -lt "$end_ts" ]; do
    local ts cpu rss
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    # 后端
    if [ -n "$BACKEND_PID" ] && ps -p "$BACKEND_PID" > /dev/null 2>&1; then
      read -r cpu rss _ < <(ps -p "$BACKEND_PID" -o %cpu=,rss=,comm= | head -1)
      rss=$(( ${rss:-0} / 1024 ))
    else
      cpu="0.0"; rss=0
    fi
    local b_cpu="$cpu" b_rss="$rss"
    # 前端 preview
    if [ -n "$PREVIEW_PID" ] && ps -p "$PREVIEW_PID" > /dev/null 2>&1; then
      read -r cpu rss _ < <(ps -p "$PREVIEW_PID" -o %cpu=,rss=,comm= | head -1)
      rss=$(( ${rss:-0} / 1024 ))
    else
      cpu="0.0"; rss=0
    fi
    echo "$ts,$b_cpu,$b_rss,$cpu,$rss" >> "$SAMPLES_FILE"
    sleep 2
  done
}
sample_loop &
SAMPLER_PID=$!
echo "  · sampler pid=$SAMPLER_PID → $SAMPLES_FILE"

# ---------- 4. Locust 压测 ----------

say "4) Locust 压测 ${RUN_TIME}s（3 用户，spawn 1/s）"
LOUST_STATS="$PERF_DIR/locust_stats.json"
.venv/bin/locust -f tests/performance/locustfile.py \
  --host="http://127.0.0.1:$BACKEND_PORT" \
  --headless -u 3 -r 1 -t "${RUN_TIME}s" \
  --html="$PERF_DIR/locust.html" \
  --csv="$PERF_DIR/locust" \
  --skip-log-setup 2>&1 | tee "$PERF_DIR/locust_console.log" | tail -30
LOCAST_EXIT=$?
echo "  · locust exit=$LOCAST_EXIT"

# ---------- 5. Lighthouse ----------

say "5) Lighthouse 前端性能基线（Assistant + Factory）"
( cd console && npx lighthouse "http://127.0.0.1:$PREVIEW_PORT/" \
  --output=json --output=html \
  --output-path="$PERF_DIR/lighthouse_prod_assistant" \
  --chrome-flags="--headless --no-sandbox" \
  --max-wait-for-load=60000 --throttling-method=devtools --quiet ) 2>&1 | tail -3

( cd console && npx lighthouse "http://127.0.0.1:$PREVIEW_PORT/#/factory" \
  --output=json --output=html \
  --output-path="$PERF_DIR/lighthouse_prod_factory" \
  --chrome-flags="--headless --no-sandbox" \
  --max-wait-for-load=60000 --throttling-method=devtools --quiet ) 2>&1 | tail -3

# ---------- 6. 等采样结束 + 汇总 ----------

say "6) 等待资源采样收尾"
wait "$SAMPLER_PID" 2>/dev/null || true

# 用 python 聚合所有结果（locust csv + lighthouse json + resource samples）
.venv/bin/python - <<'PYEOF'
import csv
import json
import os
import statistics
from pathlib import Path

ROOT = Path(os.environ.get("ROOT", "."))
PERF_DIR = ROOT / "reports" / "perf"

def load_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception as e:
        return {"_error": str(e)}

# ---------- locust ----------
# locust 2.x 的 _stats.csv 含 Aggregated 行；优先取它，没有就回退解析 console.log
locust_summary = {}
stats_csv = PERF_DIR / "locust_stats.csv"
if stats_csv.exists():
    rows = list(csv.DictReader(stats_csv.open()))
    # 找 Aggregated 行
    for r in rows:
        if r.get("Name") == "Aggregated":
            locust_summary = {
                "requests_per_sec": float(r.get("Requests/s", 0)),
                "failures_per_sec": float(r.get("Failures/s", 0)),
                "avg_ms": float(r.get("Average", 0)),
                "min_ms": float(r.get("Min", 0)),
                "max_ms": float(r.get("Max", 0)),
                "p50_ms": float(r.get("50%", 0)),
                "p95_ms": float(r.get("95%", 0)),
                "p99_ms": float(r.get("99%", 0)),
                "total_reqs": int(float(r.get("Request Count", 0))),
                "total_fails": int(float(r.get("Failure Count", 0))),
            }
            break
    # 每个端点的明细
    per_endpoint = []
    for r in rows:
        if r.get("Name") and r["Name"] != "Aggregated":
            # locust 的 Name 字段在我们 locustfile 里已含 "METHOD /path" 前缀，
            # 再前缀 Type(=method) 会变成 "DELETE DELETE /..."，故只取 Name
            per_endpoint.append({
                "name": r["Name"],
                "method": r.get("Type", ""),
                "reqs": int(float(r.get("Request Count", 0))),
                "fails": int(float(r.get("Failure Count", 0))),
                "p50_ms": float(r.get("50%", 0)),
                "p95_ms": float(r.get("95%", 0)),
                "p99_ms": float(r.get("99%", 0)),
            })
    locust_summary["per_endpoint"] = per_endpoint

# ---------- lighthouse ----------
def extract_lh(name):
    p = PERF_DIR / f"lighthouse_prod_{name}.report.json"
    if not p.exists():
        return None
    d = load_json(p)
    if "_error" in d:
        return d
    a = d.get("audits", {})
    def num(k):
        v = a.get(k, {}).get("numericValue")
        return v if isinstance(v, (int, float)) else None
    return {
        "lcp_ms": num("largest-contentful-paint"),
        "fcp_ms": num("first-contentful-paint"),
        "cls": num("cumulative-layout-shift"),
        "ttfb_ms": num("server-response-time"),
        "tbt_ms": num("total-blocking-time"),
        "speed_index_ms": num("speed-index"),
        "perf_score": d.get("categories", {}).get("performance", {}).get("score"),
        "a11y_score": d.get("categories", {}).get("accessibility", {}).get("score"),
        "bp_score": d.get("categories", {}).get("best-practices", {}).get("score"),
    }

# ---------- resource samples ----------
samples_csv = PERF_DIR / "resource_samples.csv"
resource = {"samples": 0, "backend": {}, "preview": {}}
if samples_csv.exists():
    b_cpu, b_rss, p_cpu, p_rss = [], [], [], []
    with samples_csv.open() as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                b_cpu.append(float(r["backend_cpu"]))
                b_rss.append(int(r["backend_rss_mb"]))
                p_cpu.append(float(r["preview_cpu"]))
                p_rss.append(int(r["preview_rss_mb"]))
            except (KeyError, ValueError):
                continue
    resource["samples"] = len(b_cpu)
    def peak_stats(arr):
        if not arr:
            return {}
        return {
            "peak": max(arr),
            "avg": round(statistics.mean(arr), 2),
            "p95": sorted(arr)[int(len(arr) * 0.95)] if len(arr) > 1 else arr[0],
        }
    resource["backend"] = {"cpu_pct": peak_stats(b_cpu), "rss_mb": peak_stats(b_rss)}
    resource["preview"] = {"cpu_pct": peak_stats(p_cpu), "rss_mb": peak_stats(p_rss)}

summary = {
    "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    "run_time_sec": int(os.environ.get("RUN_TIME", 60)),
    "locust": locust_summary,
    "lighthouse": {
        "assistant": extract_lh("assistant"),
        "factory": extract_lh("factory"),
    },
    "resource": resource,
}

out_json = PERF_DIR / "perf_monitor.json"
out_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\n✓ 汇总 JSON: {out_json}")

# 人读 markdown
md = []
md.append(f"# 性能监控汇总 ({summary['timestamp']})\n")
md.append(f"压测时长：{summary['run_time_sec']}s\n")
md.append("\n## Locust 并发压测\n")
if locust_summary:
    md.append(f"- 总请求：{locust_summary.get('total_reqs', 0)}")
    md.append(f"- 总失败：{locust_summary.get('total_fails', 0)}")
    md.append(f"- 整体 RPS：{locust_summary.get('requests_per_sec', 0):.2f}")
    md.append(f"- P50/P95/P99：{locust_summary.get('p50_ms', 0):.0f} / "
              f"{locust_summary.get('p95_ms', 0):.0f} / "
              f"{locust_summary.get('p99_ms', 0):.0f} ms\n")
    md.append("\n### 端点明细\n")
    md.append("| 端点 | reqs | fails | P50 | P95 | P99 |")
    md.append("|---|---|---|---|---|---|")
    for e in locust_summary.get("per_endpoint", []):
        # name 已含 "METHOD /path" 前缀，不再加 method
        md.append(f"| {e['name']} | {e['reqs']} | {e['fails']} | "
                  f"{e['p50_ms']:.0f} | {e['p95_ms']:.0f} | {e['p99_ms']:.0f} |")
md.append("\n## Lighthouse 前端基线\n")
for view in ("assistant", "factory"):
    lh = summary["lighthouse"].get(view)
    if not lh:
        continue
    md.append(f"### {view}\n")
    if lh.get("lcp_ms") is not None:
        md.append(f"- LCP: {lh['lcp_ms']:.0f}ms")
    if lh.get("fcp_ms") is not None:
        md.append(f"- FCP: {lh['fcp_ms']:.0f}ms")
    if lh.get("cls") is not None:
        md.append(f"- CLS: {lh['cls']:.3f}")
    if lh.get("ttfb_ms") is not None:
        md.append(f"- TTFB: {lh['ttfb_ms']:.0f}ms")
    if lh.get("tbt_ms") is not None:
        md.append(f"- TBT: {lh['tbt_ms']:.0f}ms")
    if lh.get("speed_index_ms") is not None:
        md.append(f"- SpeedIndex: {lh['speed_index_ms']:.0f}ms")
    if lh.get("perf_score") is not None:
        md.append(f"- PerfScore: {lh['perf_score']:.2f}")
    md.append("")

md.append("\n## 资源占用峰值\n")
md.append(f"- 采样数：{resource['samples']}")
if resource["backend"]:
    b = resource["backend"]
    md.append(f"- 后端 CPU: peak={b['cpu_pct']['peak']:.1f}% avg={b['cpu_pct']['avg']:.1f}% | "
              f"RSS peak={b['rss_mb']['peak']}MB avg={b['rss_mb']['avg']}MB")
if resource["preview"]:
    p = resource["preview"]
    md.append(f"- 前端 CPU: peak={p['cpu_pct']['peak']:.1f}% avg={p['cpu_pct']['avg']:.1f}% | "
              f"RSS peak={p['rss_mb']['peak']}MB avg={p['rss_mb']['avg']}MB")

out_md = PERF_DIR / "perf_monitor.md"
out_md.write_text("\n".join(md), encoding="utf-8")
print(f"✓ 汇总 MD: {out_md}")
PYEOF

say "完成"
echo "  产物目录: $PERF_DIR"
echo "  - perf_monitor.json   机器可读汇总"
echo "  - perf_monitor.md     人读汇总"
echo "  - locust.html         locust 详细报告"
echo "  - lighthouse_prod_*.report.html  lighthouse 详细报告"
echo "  - resource_samples.csv  资源采样原始数据"
