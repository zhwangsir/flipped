/**
 * E2E — 移动端(≤768px)：底部 tabbar、抽屉式侧栏/面板、Launcher 隐藏。
 */
import { test, expect } from '@playwright/test';

test.use({ viewport: { width: 390, height: 844 } }); // iPhone 14 尺寸

test.describe('移动端 · 布局', () => {
  test('底部 tabbar 可见，含 对话/新对话/面板/设置', async ({ page }) => {
    await page.goto('/');
    const tabbar = page.locator('.mobile-tabbar');
    await expect(tabbar).toBeVisible();
    await expect(tabbar.getByRole('button', { name: '对话列表' })).toBeVisible();
    await expect(tabbar.getByRole('button', { name: '新对话' })).toBeVisible();
    await expect(tabbar.getByRole('button', { name: '上下文面板' })).toBeVisible();
    await expect(tabbar.getByRole('button', { name: '设置' })).toBeVisible();
  });

  test('窄图标栏在移动端隐藏(由 tabbar 替代)', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.launcher')).toBeHidden();
  });

  test('无水平溢出', async ({ page }) => {
    await page.goto('/');
    const overflow = await page.evaluate(() => ({
      scrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
    }));
    expect(overflow.scrollW).toBeLessThanOrEqual(overflow.clientW + 1);
  });
});

test.describe('移动端 · 抽屉交互', () => {
  test('tabbar「对话」打开侧栏抽屉 + 遮罩，点遮罩关闭', async ({ page }) => {
    await page.goto('/');
    await page.locator('.mobile-tabbar').getByRole('button', { name: '对话列表' }).click();
    await expect(page.locator('.app')).toHaveClass(/mobile-sidebar-open/);
    await expect(page.locator('.mobile-overlay').first()).toBeVisible();
    // 抽屉(260px)覆盖视口左侧，须点右侧未被覆盖的遮罩区(390 视口，x=340)
    await page.locator('.mobile-overlay').first().click({ position: { x: 340, y: 422 } });
    await expect(page.locator('.app')).not.toHaveClass(/mobile-sidebar-open/);
  });

  test('tabbar「面板」打开上下文抽屉 + 遮罩', async ({ page }) => {
    await page.goto('/');
    await page.locator('.mobile-tabbar').getByRole('button', { name: '上下文面板' }).click();
    await expect(page.locator('.app')).toHaveClass(/mobile-panel-open/);
    await expect(page.locator('.mobile-overlay').first()).toBeVisible();
    // 底部面板高 75dvh(覆盖视口下 3/4)，须点顶部未被覆盖的遮罩区
    await page.locator('.mobile-overlay').first().click({ position: { x: 195, y: 100 } });
    await expect(page.locator('.app')).not.toHaveClass(/mobile-panel-open/);
  });

  test('tabbar「设置」打开设置页', async ({ page }) => {
    await page.goto('/');
    await page.locator('.mobile-tabbar').getByRole('button', { name: '设置' }).click();
    await expect(page.locator('[data-testid="settings"]')).toBeVisible();
  });

  test('顶栏汉堡按钮在移动端打开抽屉而非折叠侧栏', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: '折叠侧栏' }).click();
    // 移动端应为抽屉打开，而非桌面端 sb-collapsed
    await expect(page.locator('.app')).toHaveClass(/mobile-sidebar-open/);
    await expect(page.locator('.app')).not.toHaveClass(/sb-collapsed/);
  });
});
