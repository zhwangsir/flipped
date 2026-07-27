/**
 * 跨浏览器兼容性 — Hash 路由
 *
 * 目标：验证极简 hash 路由（router.ts）在三大引擎下都按设计工作：
 *   - '#/'         → Assistant 视图（默认，含 [data-testid="view-assistant"]）
 *   - '#/factory'  → 工厂 shell（Conversation + FactoryPanel overlay）
 *   - 直接打开 URL / 编程式导航 / 浏览器后退 都能正确解析
 *
 * 不依赖后端：mockEmptyApi 把所有 fetch 拦截为空态。
 */
import { test, expect } from '@playwright/test';
import { mockEmptyApi } from './mock-api';

test.use({ viewport: { width: 1280, height: 800 } });

test.beforeEach(async ({ page }) => {
  await mockEmptyApi(page);
});

test.describe('Hash 路由 · 默认与直接打开（跨浏览器）', () => {
  test('根路径无 hash → 渲染 Assistant 视图', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
  });

  test('根路径带 #/ → 仍渲染 Assistant 视图', async ({ page }) => {
    await page.goto('/#/');
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
  });

  test('直接打开 #/factory → 渲染工厂 shell 且 FactoryPanel overlay 打开', async ({ page }) => {
    await page.goto('/#/factory');
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
  });

  test('未知 hash（#/anything）回退为 Assistant 视图', async ({ page }) => {
    await page.goto('/#/anything');
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
  });
});

test.describe('Hash 路由 · 编程式导航（跨浏览器）', () => {
  test('点击侧栏「工厂」→ hash 变 #/factory 且 overlay 打开', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
    await page.locator('.side-nav-item:has-text("工厂")').click();
    await expect(page).toHaveURL(/#\/factory/);
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
  });

  test('点击 FactoryPanel 关闭按钮 → hash 回 #/ 且 overlay 关闭', async ({ page }) => {
    await page.goto('/#/factory');
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
    await page.locator('[data-testid="factory-panel"] button[aria-label="关闭"]').click();
    await expect(page.locator('[data-testid="factory-panel"]')).toBeHidden();
    await expect(page).toHaveURL(/#\/$/);
  });

  test('hashchange 事件触发后 store 同步 activeView=factory', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
    // 编程式改 hash（模拟用户在地址栏或 navigate() 调用）
    await page.evaluate(() => {
      window.location.hash = '#/factory';
    });
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
    // 改回 Assistant
    await page.evaluate(() => {
      window.location.hash = '#/';
    });
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
  });
});

test.describe('Hash 路由 · 浏览器历史（跨浏览器）', () => {
  test('后退按钮能从 #/factory 回到 #/ Assistant 视图', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
    // 通过点击导航（产生历史记录）
    await page.locator('.side-nav-item:has-text("工厂")').click();
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
    // 后退
    await page.goBack();
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
  });

  test('前进按钮能从 #/ 重新进入 #/factory', async ({ page }) => {
    await page.goto('/');
    await page.locator('.side-nav-item:has-text("工厂")').click();
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
    await page.goBack();
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
    await page.goForward();
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
  });
});

test.describe('Hash 路由 · 刷新保持（跨浏览器）', () => {
  test('在 #/factory 下刷新页面后仍停留在工厂 shell', async ({ page }) => {
    await page.goto('/#/factory');
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
    await page.reload();
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
  });

  test('在 #/ 下刷新页面后仍停留在 Assistant', async ({ page }) => {
    await page.goto('/#/');
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
    await page.reload();
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
  });
});
