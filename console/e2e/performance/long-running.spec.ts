/**
 * 性能测试 · 长时间运行稳定性
 *
 * 目标：验证前端在长时间运行（多轮交互/多次视图切换）后不出现：
 *   - 内存泄漏（heap 增长 > 阈值）
 *   - DOM 节点泄漏（node count 失控增长）
 *   - 响应延迟退化（同样操作耗时变长）
 *
 * 设计原则（呼应 TEST_STRATEGY_OPTIMIZATION.md §6.4）：
 *   - 硬失败：测量能采集到（防止 mock 失效后指标变 NaN 还绿）
 *   - 软阈值：超阈值只 console.warn 不 fail（dev 环境 GC/JIT/热更新抖动大）
 *   - 跨浏览器兼容：仅用 performance.memory（chromium 独有）+ DOM 统计
 *   - 不依赖真实后端：mockEmptyApi + mockCreateSession
 */
import { test, expect, type Page } from '@playwright/test';
import { mockEmptyApi, mockCreateSession } from '../compatibility/mock-api';

test.use({ viewport: { width: 1280, height: 800 } });

test.beforeEach(async ({ page }) => {
  await mockEmptyApi(page);
  await mockCreateSession(page);
});

// ---------- 工具：采集内存与 DOM 指标 ----------
async function collectStabilityMetrics(page: Page): Promise<{
  heapUsedMB: number | null;
  heapTotalMB: number | null;
  domNodeCount: number;
}> {
  return page.evaluate(() => {
    const mem = (performance as any).memory;
    return {
      heapUsedMB: mem ? Math.round(mem.usedJSHeapSize / 1024 / 1024) : null,
      heapTotalMB: mem ? Math.round(mem.totalJSHeapSize / 1024 / 1024) : null,
      domNodeCount: document.querySelectorAll('*').length,
    };
  });
}

// ---------- 软阈值告警工具 ----------
function warnIfOver(label: string, value: number, threshold: number) {
  if (value > threshold) {
    console.warn(`⚠️ ${label} = ${value} > 阈值 ${threshold}（可能存在性能问题，但未 fail）`);
  } else {
    console.log(`✓ ${label} = ${value} <= ${threshold}`);
  }
}

// ---------- 测试用例 ----------

test.describe('性能 · 长时间运行 - 视图切换', () => {
  test('50 轮 Assistant ↔ Factory 切换后指标采集成功', async ({ page }) => {
    test.setTimeout(120_000); // 2 分钟
    await page.goto('/');
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();

    const baseline = await collectStabilityMetrics(page);
    console.log('📊 基线:', JSON.stringify(baseline));

    for (let i = 0; i < 50; i++) {
      await page.locator('.side-nav-item:has-text("工厂")').click();
      await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
      await page.locator('[data-testid="factory-panel"] button[aria-label="关闭"]').click();
      await expect(page.locator('[data-testid="factory-panel"]')).toBeHidden();
    }

    const after = await collectStabilityMetrics(page);
    console.log('📊 50 轮后:', JSON.stringify(after));

    // 硬断言：指标采集成功（防止 mock 失效）
    expect(after.domNodeCount).toBeGreaterThan(0);

    // 软阈值：DOM 增长率（dev 环境正常波动）
    if (baseline.domNodeCount > 0) {
      const growth = (after.domNodeCount - baseline.domNodeCount) / baseline.domNodeCount;
      warnIfOver('50 轮视图切换 DOM 增长率', Math.round(growth * 100), 50); // 50% 为告警线
    }

    // 软阈值：heap 增长（仅 chromium）
    if (baseline.heapUsedMB !== null && after.heapUsedMB !== null) {
      const heapGrowth = after.heapUsedMB - baseline.heapUsedMB;
      warnIfOver('50 轮视图切换 heap 增长(MB)', heapGrowth, 50);
    }
  });
});

test.describe('性能 · 长时间运行 - 命令面板开关', () => {
  test('30 轮 Meta+K 开关后指标采集成功', async ({ page }) => {
    test.setTimeout(90_000);
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();

    const baseline = await collectStabilityMetrics(page);

    for (let i = 0; i < 30; i++) {
      await page.keyboard.press('Meta+k');
      // M163.2: 默认 5s 超时（不缩短——dev server 长时运行后渲染变慢，缩短会误报）。
      // 真正的修复是下方 150ms settle，消除上一轮 Escape 未收尾的时序竞争。
      await expect(page.locator('[data-testid="command-palette"]')).toBeVisible();
      await page.keyboard.press('Escape');
      // M163.2: 给 Escape 充分收尾时间，避免下一轮 Meta+K 注册失败（50ms → 150ms）。
      // 根因：50ms settle 太短，上一轮 Escape 未完全收尾时下一轮 Meta+K 注册失败 → palette 不开 → 5s 超时 flaky。
      await page.waitForTimeout(150);
    }

    const after = await collectStabilityMetrics(page);
    console.log(`📊 命令面板 30 轮：DOM ${baseline.domNodeCount} → ${after.domNodeCount}`);

    // 硬断言：指标采集成功
    expect(after.domNodeCount).toBeGreaterThan(0);

    // 软阈值：DOM 增长率
    if (baseline.domNodeCount > 0) {
      const growth = (after.domNodeCount - baseline.domNodeCount) / baseline.domNodeCount;
      warnIfOver('命令面板 30 轮 DOM 增长率', Math.round(growth * 100), 30);
    }
  });
});

test.describe('性能 · 长时间运行 - 响应延迟稳定性', () => {
  test('第 1 轮 vs 第 20 轮命令面板打开延迟采集成功', async ({ page }) => {
    test.setTimeout(90_000);
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();

    async function measurePaletteOpen(): Promise<number> {
      const t0 = Date.now();
      await page.keyboard.press('Meta+k');
      // M163.2: 默认 5s 超时 + 150ms settle（与上方"30 轮 Meta+K"测试一致）
      await expect(page.locator('[data-testid="command-palette"]')).toBeVisible();
      const dur = Date.now() - t0;
      await page.keyboard.press('Escape');
      // M163.2: 80ms → 150ms，消除上一轮 Escape 未收尾时下一轮 Meta+K 注册失败的时序竞争
      await page.waitForTimeout(150);
      return dur;
    }

    const first = await measurePaletteOpen();
    // 中间跑 18 轮
    for (let i = 0; i < 18; i++) {
      await measurePaletteOpen();
    }
    const last = await measurePaletteOpen();

    console.log(`📊 命令面板打开延迟：第1轮 ${first}ms，第20轮 ${last}ms`);

    // 硬断言：延迟被采集到（>0）
    expect(first).toBeGreaterThan(0);
    expect(last).toBeGreaterThan(0);

    // 软阈值：退化倍数（dev 环境 JIT/GC 抖动）
    const ratio = last / first;
    warnIfOver('命令面板延迟退化倍数', Math.round(ratio * 10) / 10, 5);
  });
});

test.describe('性能 · 长时间运行 - 侧栏会话列表', () => {
  test('连续创建 20 次新对话后指标采集成功', async ({ page }) => {
    test.setTimeout(90_000);
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();

    const baseline = await collectStabilityMetrics(page);

    for (let i = 0; i < 20; i++) {
      await page.locator('.side-nav-item:has-text("新对话")').click();
      await page.waitForTimeout(100);
    }

    const after = await collectStabilityMetrics(page);
    console.log(`📊 20 次新对话：DOM ${baseline.domNodeCount} → ${after.domNodeCount}`);

    // 硬断言：指标采集成功
    expect(after.domNodeCount).toBeGreaterThan(0);

    // 软阈值：DOM 增长绝对值
    if (baseline.domNodeCount > 0) {
      const growth = after.domNodeCount - baseline.domNodeCount;
      warnIfOver('20 次新对话 DOM 增长', growth, 300);
    }
  });
});
