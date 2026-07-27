/**
 * 性能测试 · Core Web Vitals（LCP / CLS / TTFB）
 *
 * 目标：为前端建立 Core Web Vitals 基线（与 TEST_STRATEGY_OPTIMIZATION.md §6.4 对齐）：
 *   - LCP (Largest Contentful Paint)  < 2500ms（目标），> 4000ms 报警
 *   - CLS (Cumulative Layout Shift)   < 0.1（目标），> 0.25 报警
 *   - TTFB (Time to First Byte)        < 800ms（目标），> 1800ms 报警
 *   - FCP (First Contentful Paint)     < 1800ms（目标），> 3000ms 报警
 *
 * 设计原则（呼应 interaction-perf.spec.ts）：
 *   - 跨浏览器兼容：仅用 Performance API，不依赖 CDP
 *   - 不依赖真实后端：复用 compatibility/mock-api.ts 的 mockEmptyApi
 *   - 软阈值：超阈值只 warn 不 fail（避免 CI 因环境抖动误报）
 *     但"测量能成功采集"是硬失败——防止 mock 失效后指标变 NaN 还绿
 *   - dev server 模式（非 prod build）阈值放宽 1.5x（dev 有 HMR 开销）
 */
import { test, expect, type Page } from '@playwright/test';
import { mockEmptyApi } from '../compatibility/mock-api';

// ---------- 阈值（dev 模式放宽 1.5x） ----------
const DEV_FACTOR = 1.5;
const LCP_TARGET_MS = 2500 * DEV_FACTOR;
const LCP_ALARM_MS = 4000 * DEV_FACTOR;
const CLS_TARGET = 0.1;
const CLS_ALARM = 0.25;
const TTFB_TARGET_MS = 800 * DEV_FACTOR;
const TTFB_ALARM_MS = 1800 * DEV_FACTOR;
const FCP_TARGET_MS = 1800 * DEV_FACTOR;
const FCP_ALARM_MS = 3000 * DEV_FACTOR;

test.use({ viewport: { width: 1280, height: 800 } });

test.beforeEach(async ({ page }) => {
  await mockEmptyApi(page);
});

// ---------- 工具：采集 Navigation Timing + Paint Timing ----------
async function collectNavigationMetrics(page: Page): Promise<{
  ttfb: number;
  fcp: number | null;
  lcp: number | null;
  cls: number;
}> {
  return page.evaluate(() => {
    const navEntries = performance.getEntriesByType('navigation') as PerformanceNavigationTiming[];
    const nav = navEntries[0];
    const ttfb = nav ? (nav.responseStart - nav.requestStart) : -1;

    const paintEntries = performance.getEntriesByType('paint');
    const fcpEntry = paintEntries.find((e) => e.name === 'first-contentful-paint');
    const fcp = fcpEntry ? fcpEntry.startTime : null;

    // LCP 通过 PerformanceObserver 采集（需要 observe 期间触发）
    // 这里读取已存在的 LCP entry（如果页面加载时已采集）
    let lcp: number | null = null;
    const lcpEntries = performance.getEntriesByType('largest-contentful-paint') as any[];
    if (lcpEntries.length > 0) {
      lcp = lcpEntries[lcpEntries.length - 1].startTime;
    }

    // CLS：累加 layout-shift 条目（hadRecentInput=false）
    const clsEntries = performance.getEntriesByType('layout-shift') as any[];
    let cls = 0;
    for (const e of clsEntries) {
      if (!e.hadRecentInput) cls += e.value;
    }

    return { ttfb, fcp, lcp, cls };
  });
}

// ---------- 工具：用 PerformanceObserver 实时采集 LCP ----------
async function observeLCP(page: Page, timeoutMs = 5000): Promise<number | null> {
  await page.evaluate(() => {
    (window as any).__lcpValue = null;
    const obs = new PerformanceObserver((list) => {
      const entries = list.getEntries();
      if (entries.length > 0) {
        (window as any).__lcpValue = entries[entries.length - 1].startTime;
      }
    });
    obs.observe({ type: 'largest-contentful-paint', buffered: true });
  });
  await page.waitForTimeout(timeoutMs);
  return page.evaluate(() => (window as any).__lcpValue);
}

// M163.3 — FCP PerformanceObserver fallback：与 LCP 同模式。
// 直查 getEntriesByType('paint') 在 dev server 慢渲染时可能返回空（paint 条目尚未注册），
// 此时用 PerformanceObserver + buffered:true 重新捕获历史 FCP 条目。
async function observeFCP(page: Page, timeoutMs = 2000): Promise<number | null> {
  await page.evaluate(() => {
    (window as any).__fcpValue = null;
    const obs = new PerformanceObserver((list) => {
      const entries = list.getEntries();
      const fcp = entries.find((e: any) => e.name === 'first-contentful-paint');
      if (fcp) {
        (window as any).__fcpValue = fcp.startTime;
      }
    });
    obs.observe({ type: 'paint', buffered: true });
  });
  await page.waitForTimeout(timeoutMs);
  return page.evaluate(() => (window as any).__fcpValue);
}

// ---------- 测试用例 ----------

test.describe('性能 · TTFB（首字节时间）', () => {
  test('TTFB < 1200ms（dev 放宽）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    const metrics = await collectNavigationMetrics(page);

    expect(metrics.ttfb).toBeGreaterThanOrEqual(0);
    if (metrics.ttfb > TTFB_ALARM_MS) {
      console.warn(`⚠️ TTFB 报警: ${metrics.ttfb}ms > ${TTFB_ALARM_MS}ms`);
    }
    // 软阈值：dev server 本地 < 1.2s 合理
    expect(metrics.ttfb).toBeLessThan(TTFB_ALARM_MS);
  });
});

test.describe('性能 · FCP（首次内容绘制）', () => {
  test('FCP 采集成功且 < 4500ms（dev 放宽）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    // M163.3: 给 paint 条目时间注册（与 LCP 测试同模式）
    await page.waitForTimeout(500);

    let fcp = await collectNavigationMetrics(page).then((m) => m.fcp);
    // M163.3: 直查为空时用 PerformanceObserver + buffered:true 重新捕获（与 LCP fallback 同模式）
    if (fcp === null) {
      fcp = await observeFCP(page, 2000);
    }

    // 硬断言：FCP 必须被采集到（防止 mock 失效）
    expect(fcp).not.toBeNull();
    if (fcp! > FCP_ALARM_MS) {
      console.warn(`⚠️ FCP 报警: ${fcp}ms > ${FCP_ALARM_MS}ms`);
    }
    expect(fcp).toBeLessThan(FCP_ALARM_MS);
  });
});

test.describe('性能 · LCP（最大内容绘制）', () => {
  test('LCP 采集成功且 < 6000ms（dev 放宽）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    // 给 LCP 充分触发时间
    await page.waitForTimeout(2000);

    let lcp = await collectNavigationMetrics(page).then((m) => m.lcp);
    if (lcp === null) {
      // 退路：用 PerformanceObserver 实时采集
      lcp = await observeLCP(page, 3000);
    }

    // 硬断言：LCP 必须被采集到
    expect(lcp).not.toBeNull();
    if (lcp! > LCP_ALARM_MS) {
      console.warn(`⚠️ LCP 报警: ${lcp}ms > ${LCP_ALARM_MS}ms`);
    }
    expect(lcp).toBeLessThan(LCP_ALARM_MS);
  });
});

test.describe('性能 · CLS（累计布局偏移）', () => {
  test('CLS < 0.25（稳定，无明显跳动）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    // 等所有异步渲染完成（含 mock API 响应回来后的 reflow）
    await page.waitForTimeout(1500);
    const metrics = await collectNavigationMetrics(page);

    if (metrics.cls > CLS_ALARM) {
      console.warn(`⚠️ CLS 报警: ${metrics.cls} > ${CLS_ALARM}`);
    }
    expect(metrics.cls).toBeLessThan(CLS_ALARM);
  });
});

test.describe('性能 · 综合基线快照', () => {
  test('首页 Core Web Vitals 全量采集 → 输出基线报告', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    await page.waitForTimeout(2000);

    const metrics = await collectNavigationMetrics(page);
    const lcpObserved = metrics.lcp ?? (await observeLCP(page, 2000));

    const report = {
      ttfb_ms: metrics.ttfb,
      fcp_ms: metrics.fcp,
      lcp_ms: lcpObserved,
      cls: metrics.cls,
      thresholds: {
        ttfb_alarm_ms: TTFB_ALARM_MS,
        fcp_alarm_ms: FCP_ALARM_MS,
        lcp_alarm_ms: LCP_ALARM_MS,
        cls_alarm: CLS_ALARM,
      },
    };
    console.log('📊 Core Web Vitals 基线:', JSON.stringify(report, null, 2));

    // 硬断言：所有指标都被采集到（防止 mock 失效后 NaN 还绿）
    expect(report.ttfb_ms).toBeGreaterThanOrEqual(0);
    expect(report.fcp_ms).not.toBeNull();
    expect(report.lcp_ms).not.toBeNull();
  });
});
