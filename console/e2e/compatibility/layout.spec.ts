/**
 * 跨浏览器兼容性 — 布局渲染
 *
 * 目标：在 chromium / firefox / webkit 三大引擎下，验证主壳三栏布局正常渲染、
 *      无元素重叠或溢出视口、关键 DOM 结构与 CSS 自定义属性都正确生效。
 *
 * 注意：本套件不依赖真实后端（用 mock-api.ts 把所有 fetch 拦截为空态），
 *      只断言前端布局本身。WebSocket 失败由前端 fail-open 处理，不影响渲染。
 */
import { test, expect } from '@playwright/test';
import { mockEmptyApi } from './mock-api';

test.use({ viewport: { width: 1280, height: 800 } });

test.beforeEach(async ({ page }) => {
  await mockEmptyApi(page);
});

test.describe('布局渲染 · 三栏结构（跨浏览器）', () => {
  test('app 容器挂载且带 topbar/body 类', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.app')).toBeVisible();
    await expect(page.locator('.topbar')).toBeVisible();
    await expect(page.locator('.body')).toBeVisible();
  });

  test('左侧 sidebar / 中间 view-assistant / 右侧 context 同时可见', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    // 默认 hash → Assistant 视图，中间栏用 .view-assistant（非 .center，.center 仅 factory 视图用）
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
    await expect(page.locator('.context')).toBeVisible();
  });

  test('sidebar 在左、context 在右、中间栏在中间（box.x 顺序）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    const sb = await page.locator('.sidebar').boundingBox();
    const ct = await page.locator('[data-testid="view-assistant"]').boundingBox();
    const cx = await page.locator('.context').boundingBox();
    expect(sb).not.toBeNull();
    expect(ct).not.toBeNull();
    expect(cx).not.toBeNull();
    // 左 → 中 → 右 顺序
    expect(sb!.x).toBeLessThan(ct!.x);
    expect(ct!.x).toBeLessThan(cx!.x);
  });

  test('无水平溢出（scrollWidth ≤ clientWidth + 1px 容差）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    const overflow = await page.evaluate(() => ({
      scrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
    }));
    expect(overflow.scrollW).toBeLessThanOrEqual(overflow.clientW + 1);
  });

  test('无垂直溢出（body 高度不超过视口）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    const overflow = await page.evaluate(() => ({
      scrollH: document.documentElement.scrollHeight,
      clientH: document.documentElement.clientHeight,
    }));
    expect(overflow.scrollH).toBeLessThanOrEqual(overflow.clientH + 1);
  });

  test('topbar 高度等于 CSS 变量 --topbar-h（取整后）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();
    const { topbarH, cssVar } = await page.evaluate(() => {
      const topbar = document.querySelector('.topbar') as HTMLElement;
      const cs = getComputedStyle(topbar);
      return {
        topbarH: Math.round(topbar.getBoundingClientRect().height),
        cssVar: parseInt(cs.getPropertyValue('--topbar-h') || '0', 10),
      };
    });
    // CSS 变量未设为 0 时校验；为 0 时退化为非 0 高度即可
    if (cssVar > 0) {
      expect(Math.abs(topbarH - cssVar)).toBeLessThanOrEqual(1);
    } else {
      expect(topbarH).toBeGreaterThan(0);
    }
  });
});

test.describe('布局渲染 · 侧栏导航项（跨浏览器）', () => {
  test('4 个主导航项可见：新对话/搜索/已安排/插件/工厂', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.side-nav-item:has-text("新对话")')).toBeVisible();
    await expect(page.locator('.side-nav-item:has-text("搜索")')).toBeVisible();
    await expect(page.locator('.side-nav-item:has-text("已安排")')).toBeVisible();
    await expect(page.locator('.side-nav-item:has-text("插件")')).toBeVisible();
    await expect(page.locator('.side-nav-item:has-text("工厂")')).toBeVisible();
  });

  test('底部设置区可见且含主题切换按钮', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.side-foot-item:has-text("设置")')).toBeVisible();
    // 主题切换按钮 aria-label 含「切换到」前缀
    await expect(page.locator('.side-theme[aria-label*="切换到"]')).toBeVisible();
  });

  test('topbar 含折叠侧栏 / 切换上下文面板 两个 icon-btn', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('button', { name: '折叠侧栏' })).toBeVisible();
    await expect(page.getByRole('button', { name: '切换上下文面板' })).toBeVisible();
  });
});

test.describe('布局渲染 · 主题与无重叠（跨浏览器）', () => {
  test('html 元素有 data-theme 属性（dark 或 light）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('html')).toHaveAttribute('data-theme', /(dark|light)/);
  });

  test('topbar 与 sidebar 不重叠（topbar 占满宽度，sidebar 在其下方）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();
    const tb = await page.locator('.topbar').boundingBox();
    const sb = await page.locator('.sidebar').boundingBox();
    expect(tb).not.toBeNull();
    expect(sb).not.toBeNull();
    // sidebar 顶部 ≥ topbar 底部（允许 1px 容差应对子像素）
    expect(sb!.y).toBeGreaterThanOrEqual(tb!.y + tb!.height - 1);
  });

  test('中间栏不与 sidebar 横向重叠', async ({ page }) => {
    await page.goto('/');
    const sb = await page.locator('.sidebar').boundingBox();
    const ct = await page.locator('[data-testid="view-assistant"]').boundingBox();
    expect(sb).not.toBeNull();
    expect(ct).not.toBeNull();
    expect(ct!.x).toBeGreaterThanOrEqual(sb!.x + sb!.width - 1);
  });
});
