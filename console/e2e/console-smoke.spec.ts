/**
 * E2E 烟雾测试 — Console 主壳层基础可用性。
 *
 * 验证主布局渲染、侧栏导航、顶栏、主题切换等基础功能，
 * 确保工厂面板集成未破坏既有 Console 结构。
 */
import { test, expect } from '@playwright/test';
import { mockEmptyApi } from './compatibility/mock-api';

// 拦截 :8011 API 返回空态，让主壳层（含 .center 中栏）在无后端时也能完整渲染。
// 不加 mock 时 sessions 拉取失败 → 中栏不渲染 → "主体三列布局渲染" 用例失败。
test.beforeEach(async ({ page }) => {
  await mockEmptyApi(page);
});

test.describe('Console 主壳 · 基础渲染', () => {
  test('页面加载且标题可见', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/flipped/i);
  });

  test('侧栏可见且含导航项', async ({ page }) => {
    await page.goto('/');
    const sidebar = page.locator('.sidebar');
    await expect(sidebar).toBeVisible();
    await expect(page.locator('.side-nav-item:has-text("新对话")')).toBeVisible();
    await expect(page.locator('.side-nav-item:has-text("搜索")')).toBeVisible();
    await expect(page.locator('.side-nav-item:has-text("工厂")')).toBeVisible();
  });

  test('顶栏可见', async ({ page }) => {
    await page.goto('/');
    const topbar = page.locator('.topbar');
    await expect(topbar).toBeVisible();
  });

  test('主体三列布局渲染', async ({ page }) => {
    // .center 只在 factory 路由（Conversation）渲染；'/' 默认路由渲染 Assistant（无 .center）。
    // M151.5 引入 hash 路由后，3 列 shell 移至 #/factory，故导航到此路由测三列布局。
    await page.goto('/#/factory');
    await expect(page.locator('.sidebar')).toBeVisible();
    await expect(page.locator('.center')).toBeVisible();
  });
});

test.describe('Console 主壳 · 侧栏导航', () => {
  test('工厂导航项存在且可点击', async ({ page }) => {
    await page.goto('/');
    const factoryNav = page.locator('.side-nav-item:has-text("工厂")');
    await expect(factoryNav).toBeVisible();
    await factoryNav.click();
    // 点击后应打开工厂面板 overlay
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
  });

  test('插件导航项存在且可点击', async ({ page }) => {
    await page.goto('/');
    const pluginsNav = page.locator('.side-nav-item:has-text("插件")');
    await expect(pluginsNav).toBeVisible();
    await pluginsNav.click();
    await expect(page.locator('[data-testid="plugins"]')).toBeVisible();
  });

  test('工厂与插件面板互不冲突(各自独立 overlay)', async ({ page }) => {
    await page.goto('/');
    // 打开工厂
    await page.locator('.side-nav-item:has-text("工厂")').click();
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
    // 关闭工厂
    await page.locator('[data-testid="factory-panel"] button[aria-label="关闭"]').click();
    await expect(page.locator('[data-testid="factory-panel"]')).toBeHidden();
    // 打开插件
    await page.locator('.side-nav-item:has-text("插件")').click();
    await expect(page.locator('[data-testid="plugins"]')).toBeVisible();
    // 插件打开时工厂仍隐藏
    await expect(page.locator('[data-testid="factory-panel"]')).toBeHidden();
  });
});

test.describe('Console 主壳 · 主题', () => {
  test('默认主题渲染(data-theme 属性)', async ({ page }) => {
    await page.goto('/');
    const html = page.locator('html');
    await expect(html).toHaveAttribute('data-theme', /(dark|light)/);
  });
});

test.describe('Console 主壳 · 性能', () => {
  test('首屏加载 < 3s', async ({ page }) => {
    const start = Date.now();
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    const loadTime = Date.now() - start;
    expect(loadTime).toBeLessThan(3000);
  });
});
