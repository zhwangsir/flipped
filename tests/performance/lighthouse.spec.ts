/**
 * flipped · Lighthouse 前端性能基线测试（TEST_STRATEGY_OPTIMIZATION.md §2.3）.
 *
 * 用 lighthouse CLI 扫描前端 Core Web Vitals（LCP / FCP / CLS / TTFB / INP），
 * 断言性能基线，结果落盘到 reports/perf/ 供趋势对比。
 *
 * 设计选择：
 *   - 不用 `playwright-lighthouse` 插件（需要 puppeteer 与 playwright 同时存在，易冲突），
 *     改用 `lighthouse` CLI 作为子进程跑，结果落 JSON 后用 Node 解析断言。
 *   - 同时扫描 Assistant 视图（`#/`）与 Factory 视图（`#/factory`）。
 *   - 优先扫生产构建（`vite preview`，端口 5274）；若未起，回退到 dev server（5273），
 *     dev 模式阈值放宽（dev server 不做 bundle 优化，不应按产线基线卡）。
 *
 * 跑法：
 *   # 1. 起前端（二选一）
 *   cd console && npm run dev                       # dev server :5273
 *   cd console && npm run build && npx vite preview --port 5274  # 生产构建 :5274
 *   # 2. 起 mock 后端（assistant 视图会调 /api/v1/health 探活，需要后端可达）
 *   FLIPPED_MOCK_ORCHESTRATOR=1 ... uvicorn api.main:app --port 8011 &
 *   # 3. 跑测试
 *   npx playwright test tests/performance/lighthouse.spec.ts
 *   # 或直接用 mjs 脚本（不走 playwright runner）：
 *   node tests/performance/lighthouse.spec.mjs
 *
 * 阈值（产线基线，与 TEST_STRATEGY_OPTIMIZATION.md §2.4 对齐）：
 *   LCP < 2500ms | FCP < 1800ms | CLS < 0.1 | TTFB < 800ms
 *
 * 产物：
 *   reports/perf/lighthouse_<view>.report.json
 *   reports/perf/lighthouse_<view>.report.html
 */
// 用相对路径 import：tests/performance/ 不在 console/node_modules 的 resolve 路径里。
import { test, expect } from '../../console/node_modules/@playwright/test/index.mjs';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = join(__dirname, '..', '..');
const REPORT_DIR = join(ROOT, 'reports', 'perf');

// ---------- 配置 ----------

interface PerfThresholds {
  LCP_MS: number;       // Largest Contentful Paint
  FCP_MS: number;       // First Contentful Paint
  CLS: number;          // Cumulative Layout Shift
  TTFB_MS: number;      // Time to First Byte
  TBT_MS?: number;      // Total Blocking Time (optional, dev 模式常返回 null)
  SPEED_INDEX_MS?: number;
}

/** 产线基线（vite preview 走构建产物）。 */
const PROD_THRESHOLDS: PerfThresholds = {
  LCP_MS: 2500,
  FCP_MS: 1800,
  CLS: 0.1,
  TTFB_MS: 800,
  TBT_MS: 200,
  SPEED_INDEX_MS: 3000,
};

/** dev 模式放宽阈值（vite dev 不做 minify/split，HMR client 有开销）。 */
const DEV_THRESHOLDS: PerfThresholds = {
  LCP_MS: 8000,
  FCP_MS: 5000,
  CLS: 0.1,
  TTFB_MS: 800,
};

interface ViewSpec {
  name: string;
  /** 完整 URL（含 hash 路由）。 */
  url: string;
  /** 该视图的阈值覆盖（Factory 视图更重，放宽 LCP）。 */
  thresholds?: Partial<PerfThresholds>;
}

// ---------- 工具函数 ----------

function ensureReportDir(): void {
  if (!existsSync(REPORT_DIR)) mkdirSync(REPORT_DIR, { recursive: true });
}

function detectServer(): { origin: string; mode: 'prod' | 'dev'; thresholds: PerfThresholds } {
  // 优先 prod preview (:5274)，回退 dev server (:5273)
  const candidates: Array<{ port: number; mode: 'prod' | 'dev' }> = [
    { port: 5274, mode: 'prod' },
    { port: 5273, mode: 'dev' },
  ];
  for (const c of candidates) {
    const origin = `http://127.0.0.1:${c.port}`;
    try {
      execFileSync('curl', ['-sf', '-o', '/dev/null', '-m', '2', origin], { stdio: 'ignore' });
      return { origin, mode: c.mode, thresholds: c.mode === 'prod' ? PROD_THRESHOLDS : DEV_THRESHOLDS };
    } catch {
      // 继续试下一个
    }
  }
  throw new Error(
    '前端服务未运行：请先 `cd console && npm run dev` 或 `npx vite preview --port 5274`'
  );
}

function runLighthouse(url: string, outputPathBasename: string): Record<string, any> {
  ensureReportDir();
  const jsonPath = join(REPORT_DIR, `${outputPathBasename}.report.json`);
  const htmlPath = join(REPORT_DIR, `${outputPathBasename}.report.html`);
  const args = [
    url,
    '--output=json',
    '--output=html',
    `--output-path=${join(REPORT_DIR, outputPathBasename)}`,
    '--chrome-flags=--headless --no-sandbox --disable-gpu',
    '--max-wait-for-load=60000',
    '--throttling-method=devtools',
    '--quiet',
  ];
  // npx 在 console 目录里能找到 lighthouse（已 npm i -D）
  execFileSync('npx', ['lighthouse', ...args], {
    cwd: join(ROOT, 'console'),
    stdio: 'inherit',
    timeout: 120_000,
  });
  if (!existsSync(jsonPath)) {
    throw new Error(`lighthouse 未生成 JSON 报告：${jsonPath}`);
  }
  return JSON.parse(readFileSync(jsonPath, 'utf8'));
}

interface CoreWebVitals {
  LCP: number;     // ms
  FCP: number;     // ms
  CLS: number;     // unitless
  TTFB: number;    // ms
  TBT: number | null;
  speedIndex: number | null;
  perfScore: number | null;
}

function extractMetrics(report: Record<string, any>): CoreWebVitals {
  const a = report.audits || {};
  const num = (key: string): number | null => {
    const v = a[key]?.numericValue;
    return typeof v === 'number' ? v : null;
  };
  return {
    LCP: num('largest-contentful-paint') ?? -1,
    FCP: num('first-contentful-paint') ?? -1,
    CLS: num('cumulative-layout-shift') ?? -1,
    TTFB: num('server-response-time') ?? -1,
    TBT: num('total-blocking-time'),
    speedIndex: num('speed-index'),
    perfScore: report.categories?.performance?.score ?? null,
  };
}

function formatMs(ms: number | null): string {
  if (ms === null) return 'N/A';
  return `${ms.toFixed(0)}ms`;
}

function assertThresholds(
  view: string,
  m: CoreWebVitals,
  thresholds: PerfThresholds
): void {
  const failures: string[] = [];
  if (m.LCP > thresholds.LCP_MS) {
    failures.push(`LCP=${formatMs(m.LCP)} > ${thresholds.LCP_MS}ms`);
  }
  if (m.FCP > thresholds.FCP_MS) {
    failures.push(`FCP=${formatMs(m.FCP)} > ${thresholds.FCP_MS}ms`);
  }
  if (m.CLS > thresholds.CLS) {
    failures.push(`CLS=${m.CLS.toFixed(3)} > ${thresholds.CLS}`);
  }
  if (m.TTFB > thresholds.TTFB_MS) {
    failures.push(`TTFB=${formatMs(m.TTFB)} > ${thresholds.TTFB_MS}ms`);
  }
  if (thresholds.TBT_MS && m.TBT !== null && m.TBT > thresholds.TBT_MS) {
    failures.push(`TBT=${formatMs(m.TBT)} > ${thresholds.TBT_MS}ms`);
  }
  if (thresholds.SPEED_INDEX_MS && m.speedIndex !== null && m.speedIndex > thresholds.SPEED_INDEX_MS) {
    failures.push(`SpeedIndex=${formatMs(m.speedIndex)} > ${thresholds.SPEED_INDEX_MS}ms`);
  }

  // 输出汇总（无论成败，便于 TEST_LOG 留痕）
  const lines = [
    `\n[Lighthouse] ${view}`,
    `  LCP         ${formatMs(m.LCP)}  (阈值 < ${thresholds.LCP_MS}ms)`,
    `  FCP         ${formatMs(m.FCP)}  (阈值 < ${thresholds.FCP_MS}ms)`,
    `  CLS         ${m.CLS.toFixed(3)}  (阈值 < ${thresholds.CLS})`,
    `  TTFB        ${formatMs(m.TTFB)}  (阈值 < ${thresholds.TTFB_MS}ms)`,
    `  TBT         ${formatMs(m.TBT)}  ${thresholds.TBT_MS ? `(阈值 < ${thresholds.TBT_MS}ms)` : ''}`,
    `  SpeedIndex  ${formatMs(m.speedIndex)}`,
    `  PerfScore   ${m.perfScore !== null ? m.perfScore.toFixed(2) : 'N/A'}`,
  ];
  console.log(lines.join('\n'));

  if (failures.length > 0) {
    throw new Error(`[${view}] 性能基线未达标：\n  - ${failures.join('\n  - ')}`);
  }
}

// ---------- 测试用例 ----------

const VIEWS: ViewSpec[] = [
  { name: 'assistant', url: '', thresholds: {} },                  // #/ (默认)
  { name: 'factory', url: '#/factory', thresholds: { LCP_MS: 4000, FCP_MS: 2500, SPEED_INDEX_MS: 4000 } },
];

test.describe('Lighthouse 前端性能基线', () => {
  test.skip(({ browserName }) => browserName !== 'chromium', 'lighthouse 仅在 chromium 下运行');

  test('扫描 Assistant + Factory 视图 Core Web Vitals', async () => {
    const { origin, mode, thresholds } = detectServer();
    console.log(`[Lighthouse] 模式=${mode} origin=${origin}`);

    const allMetrics: Array<{ view: string; metrics: CoreWebVitals }> = [];
    const allFailures: string[] = [];

    for (const view of VIEWS) {
      const url = view.url ? `${origin}/${view.url}` : `${origin}/`;
      const report = runLighthouse(url, `lighthouse_${mode}_${view.name}`);
      const metrics = extractMetrics(report);
      allMetrics.push({ view: view.name, metrics });
      const effectiveThresholds = { ...thresholds, ...(view.thresholds || {}) };
      // 收集失败项，不立即 throw——保证两个视图都跑完，拿到完整 baseline
      try {
        assertThresholds(`${view.name} view (${mode})`, metrics, effectiveThresholds);
      } catch (e) {
        allFailures.push((e as Error).message);
      }
    }

    // 汇总落盘（机器可读，便于 trend 对比）
    const summaryPath = join(REPORT_DIR, `lighthouse_${mode}_summary.json`);
    writeFileSync(
      summaryPath,
      JSON.stringify({
        mode,
        timestamp: new Date().toISOString(),
        views: allMetrics,
        failures: allFailures,
      }, null, 2)
    );
    console.log(`[Lighthouse] 汇总写入 ${summaryPath}`);

    // 所有视图跑完后，若有失败统一抛出（Playwright 捕获为 test failure）
    if (allFailures.length > 0) {
      throw new Error(
        `性能基线未达标（${allFailures.length} 项）：\n\n${allFailures.join('\n\n')}`
      );
    }
  });
});
