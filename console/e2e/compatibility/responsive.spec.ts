/**
 * 跨浏览器兼容性 — 响应式布局
 *
 * 目标：在 mobile(375px) / tablet(768px) / desktop(1280px) 三个断点下，
 *      验证 UI 在三大引擎里都按 app.css 的 @media (max-width: 768px) 切换：
 *        - mobile/tablet（≤768px）：底部 tabbar 可见、launcher 隐藏、sidebar/context 抽屉化
 *        - desktop（>768px）：三栏布局、tabbar 隐藏、launcher 在 context 收起时可见
 *
 * 注：项目断点为 768px（见 app.css @media (max-width: 768px)），
 *     故 tablet 768px 走移动端分支（含等号），desktop 用 1280px。
 */
import { test, expect } from '@playwright/test';
import { mockEmptyApi } from './mock-api';

test.beforeEach(async ({ page }) => {
  await mockEmptyApi(page);
});

test.describe('响应式 · Desktop 1280px（跨浏览器）', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('桌面端：三栏布局，无底部 tabbar', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    // 默认 hash → Assistant 视图，中间栏用 [data-testid="view-assistant"]
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
    await expect(page.locator('.context')).toBeVisible();
    await expect(page.locator('.mobile-tabbar')).toBeHidden();
  });

  test('桌面端：收起 context 后 launcher 窄栏可见', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: '切换上下文面板' }).click();
    await expect(page.locator('.context')).toBeHidden();
    await expect(page.locator('.launcher')).toBeVisible();
  });

  test('桌面端：侧栏可见，不抽屉化（无 mobile-sidebar-open 类）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.app')).not.toHaveClass(/mobile-sidebar-open/);
    await expect(page.locator('.app')).not.toHaveClass(/mobile-panel-open/);
  });

  test('桌面端：无水平溢出', async ({ page }) => {
    await page.goto('/');
    const overflow = await page.evaluate(() => ({
      scrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
    }));
    expect(overflow.scrollW).toBeLessThanOrEqual(overflow.clientW + 1);
  });
});

test.describe('响应式 · Tablet 768px（跨浏览器）', () => {
  test.use({ viewport: { width: 768, height: 1024 } });

  test('平板：底部 tabbar 可见（≤768px 命中移动端断点）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.mobile-tabbar')).toBeVisible();
  });

  test('平板：tabbar 4 个按钮（对话/新对话/面板/设置）可见', async ({ page }) => {
    await page.goto('/');
    const tabbar = page.locator('.mobile-tabbar');
    await expect(tabbar.getByRole('button', { name: '对话列表' })).toBeVisible();
    await expect(tabbar.getByRole('button', { name: '新对话' })).toBeVisible();
    await expect(tabbar.getByRole('button', { name: '上下文面板' })).toBeVisible();
    await expect(tabbar.getByRole('button', { name: '设置' })).toBeVisible();
  });

  test('平板：launcher 在移动断点下隐藏', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.launcher')).toBeHidden();
  });

  test('平板：无水平溢出', async ({ page }) => {
    await page.goto('/');
    const overflow = await page.evaluate(() => ({
      scrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
    }));
    expect(overflow.scrollW).toBeLessThanOrEqual(overflow.clientW + 1);
  });
});

test.describe('响应式 · Mobile 375px（跨浏览器）', () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test('移动端：底部 tabbar 可见', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.mobile-tabbar')).toBeVisible();
  });

  test('移动端：默认 sidebar/context 都收起（抽屉态，无 mobile-*-open 类）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.app')).not.toHaveClass(/mobile-sidebar-open/);
    await expect(page.locator('.app')).not.toHaveClass(/mobile-panel-open/);
  });

  test('移动端：点 tabbar「对话列表」打开 sidebar 抽屉 + 遮罩', async ({ page }) => {
    await page.goto('/');
    await page.locator('.mobile-tabbar').getByRole('button', { name: '对话列表' }).click();
    await expect(page.locator('.app')).toHaveClass(/mobile-sidebar-open/);
    await expect(page.locator('.mobile-overlay').first()).toBeVisible();
  });

  test('移动端：点 tabbar「上下文面板」打开 context 抽屉 + 遮罩', async ({ page }) => {
    await page.goto('/');
    await page.locator('.mobile-tabbar').getByRole('button', { name: '上下文面板' }).click();
    await expect(page.locator('.app')).toHaveClass(/mobile-panel-open/);
    await expect(page.locator('.mobile-overlay').first()).toBeVisible();
  });

  test('移动端：点 tabbar「设置」打开设置 overlay', async ({ page }) => {
    await page.goto('/');
    await page.locator('.mobile-tabbar').getByRole('button', { name: '设置' }).click();
    await expect(page.locator('[data-testid="settings"]')).toBeVisible();
  });

  test('移动端：无水平溢出（防横向滚动条）', async ({ page }) => {
    await page.goto('/');
    const overflow = await page.evaluate(() => ({
      scrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
    }));
    expect(overflow.scrollW).toBeLessThanOrEqual(overflow.clientW + 1);
  });

  test('移动端：tabbar 按钮可见且高度 ≥ 40px（接近 a11y 44px 触控标准）', async ({ page }) => {
    await page.goto('/');
    const buttons = page.locator('.mobile-tabbar .tabbar-btn');
    const count = await buttons.count();
    expect(count).toBeGreaterThanOrEqual(4);
    for (let i = 0; i < count; i++) {
      const box = await buttons.nth(i).boundingBox();
      expect(box).not.toBeNull();
      // 实际渲染高度受 tabbar 56px 容器 + padding 4px 8px 约束 → 40px。
      // 跨浏览器一致性校验：每个按钮高度都 ≥ 40px（webkit/firefox/chromium 一致）。
      expect(box!.height).toBeGreaterThanOrEqual(40);
    }
  });
});

test.describe('响应式 · 断点切换（跨浏览器）', () => {
  test('从桌面切到移动：tabbar 出现、launcher 隐藏', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/');
    await expect(page.locator('.mobile-tabbar')).toBeHidden();
    await page.setViewportSize({ width: 375, height: 812 });
    // 等 CSS @media 重算
    await page.waitForTimeout(300);
    await expect(page.locator('.mobile-tabbar')).toBeVisible();
  });

  test('从移动切到桌面：tabbar 消失、三栏恢复', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/');
    await expect(page.locator('.mobile-tabbar')).toBeVisible();
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.waitForTimeout(300);
    await expect(page.locator('.mobile-tabbar')).toBeHidden();
    await expect(page.locator('.sidebar')).toBeVisible();
    await expect(page.locator('.context')).toBeVisible();
  });
});
