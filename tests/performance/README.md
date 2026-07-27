# flipped · 性能测试套件

对应 TEST_STRATEGY_OPTIMIZATION.md §2（性能测试维度）。所有测试用 mock 模式跑，
不依赖真实 LLM / 集群，可在任何开发机上重复。

## 文件清单

| 文件 | 用途 | 跑法 |
|---|---|---|
| `locustfile.py` | Locust 并发压测（assistant API 全流程） | `.venv/bin/locust -f tests/performance/locustfile.py --host=http://localhost:8011 --headless -u 3 -r 1 -t 60s` |
| `lighthouse.spec.ts` | Lighthouse 前端 Core Web Vitals 基线 | `cd console && npx playwright test --config=../tests/performance/playwright.config.ts` |
| `playwright.config.ts` | 性能测试专用 Playwright config（testDir=.） | （由上一行调用） |

## 前置条件

### 1. mock 后端（端口 8011）

关闭真实后端，启 mock：

```bash
pkill -f 'uvicorn api.main:app' || true
FLIPPED_MOCK_ORCHESTRATOR=1 FLIPPED_MOCK_WORKER=1 \
  FLIPPED_SESSION_STORE_PATH=$PWD/.sessions.perf.json \
  PYTHONPATH=src .venv/bin/python -m uvicorn api.main:app \
  --host 127.0.0.1 --port 8011 --log-level warning &
```

mock 模式下 orchestrator 用确定性 mock 节点（不调 LLM），session store 走独立文件
不污染 `.sessions.json`。

### 2. 前端服务（端口 5273 dev / 5274 preview）

dev server（功能验证用，性能数字差）：

```bash
cd console && npm run dev
```

production preview（性能基线用，构建产物）：

```bash
cd console && npm run build && npx vite preview --port 5274 --host 127.0.0.1
```

Lighthouse 优先扫 preview（5274），未起则回退 dev（5273，阈值放宽）。

### 3. 工具依赖

```bash
.venv/bin/pip install locust        # 已加入 requirements-dev
cd console && npm install -D lighthouse
```

## 一键脚本

`scripts/perf_monitor.sh` 串起所有步骤：起 mock 后端 → 起 preview → 资源采样 →
locust 60s → lighthouse → 汇总到 `reports/perf/perf_monitor.json` + `.md`。

```bash
bash scripts/perf_monitor.sh 60   # 60 秒压测
```

## 阈值

### Locust（mock 模式）

| 端点 | P95 阈值 |
|---|---|
| POST /api/v1/assistant/sessions | < 100ms |
| POST /api/v1/assistant/sessions/{id}/messages | < 200ms |
| GET /api/v1/sessions/{id} (poll) | < 100ms |
| GET /api/v1/assistant/sessions/{id}/history | < 150ms |
| DELETE /api/v1/sessions/{id} | < 100ms |
| GET /api/v1/sessions | < 100ms |
| GET /api/v1/health | < 80ms |
| **整体失败率** | **< 1%** |

### Lighthouse（生产 preview）

| 指标 | 阈值 | 说明 |
|---|---|---|
| LCP | < 2500ms | Largest Contentful Paint |
| FCP | < 1800ms | First Contentful Paint |
| CLS | < 0.1 | Cumulative Layout Shift |
| TTFB | < 800ms | Time to First Byte |

Factory 视图因含 xterm 终端 + 多面板，阈值放宽：LCP < 4000ms, FCP < 2500ms。

## 已知基线问题

- **FCP 偏高（~2300ms）**：Geist 字体 woff2 加载阻塞首次绘制。改进方向：
  - 字体 `font-display: swap` 或 `optional`
  - 关键 CSS inline
  - 字体子集化（仅保留 latin）
- **PerfScore 返回 None**：lighthouse 在某些环境下 TBT 测量返回 null，导致
  performance 类别无法计算总分。LCP/FCP/CLS 仍可独立断言。
- **dev server 不适合做性能基线**：vite dev 不做 minify/split，HMR client 有开销，
  LCP/FCP 会比 preview 慢 5-10 倍。性能基线必须用 `vite preview` 跑。
