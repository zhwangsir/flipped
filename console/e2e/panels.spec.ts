/**
 * E2E — 覆盖层与快捷键：Settings / CommandPalette / TerminalDrawer / Plugins。
 */
import { test, expect } from '@playwright/test';

test.describe('Settings · 设置页', () => {
  test('侧栏底部「设置」打开全屏设置页', async ({ page }) => {
    await page.goto('/');
    await page.locator('.side-foot-item:has-text("设置")').click();
    await expect(page.locator('[data-testid="settings"]')).toBeVisible();
    await expect(page.locator('.settings-title').first()).toBeVisible();
  });

  test('设置页返回按钮关闭', async ({ page }) => {
    await page.goto('/');
    await page.locator('.side-foot-item:has-text("设置")').click();
    await expect(page.locator('[data-testid="settings"]')).toBeVisible();
    await page.locator('.settings-back').click();
    await expect(page.locator('[data-testid="settings"]')).toBeHidden();
  });

  test('设置页导航分组可切换(常规/外观/配置)', async ({ page }) => {
    await page.goto('/');
    await page.locator('.side-foot-item:has-text("设置")').click();
    const nav = page.locator('.settings-nav');
    await expect(nav.locator('.settings-navlabel').first()).toBeVisible();
    // 切到「外观」
    await nav.locator('button:has-text("外观")').click();
    await expect(page.locator('.settings-title')).toContainText('外观');
  });

  test('⌘, 快捷键打开设置(与面板展示一致)', async ({ page }) => {
    await page.goto('/');
    // 等 React mount 完成(keydown 监听绑定后再按键，避免时序 flaky)
    await expect(page.locator('.topbar')).toBeVisible();
    await page.keyboard.press('Meta+,');
    await expect(page.locator('[data-testid="settings"]')).toBeVisible();
  });
});

test.describe('CommandPalette · 命令面板', () => {
  test('⌘K 打开 / 再按关闭', async ({ page }) => {
    await page.goto('/');
    // 等 React mount 完成(keydown 监听绑定后再按键，避免时序 flaky)
    await expect(page.locator('.topbar')).toBeVisible();
    await page.keyboard.press('Meta+k');
    await expect(page.locator('[data-testid="command-palette"]')).toBeVisible();
    await page.keyboard.press('Meta+k');
    await expect(page.locator('[data-testid="command-palette"]')).toBeHidden();
  });

  test('Esc 关闭面板', async ({ page }) => {
    await page.goto('/');
    // 等 React mount 完成(keydown 监听绑定后再按键，避免时序 flaky)
    await expect(page.locator('.topbar')).toBeVisible();
    await page.keyboard.press('Meta+k');
    await expect(page.locator('[data-testid="command-palette"]')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('[data-testid="command-palette"]')).toBeHidden();
  });

  test('输入过滤命令列表', async ({ page }) => {
    await page.goto('/');
    // 等 React mount 完成(keydown 监听绑定后再按键，避免时序 flaky)
    await expect(page.locator('.topbar')).toBeVisible();
    await page.keyboard.press('Meta+k');
    const input = page.locator('.palette-search input');
    await expect(input).toBeFocused();
    await input.fill('设置');
    const items = page.locator('.palette-item');
    const count = await items.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i++) {
      await expect(items.nth(i).locator('.palette-label')).toContainText('设置');
    }
  });

  test('无匹配时显示空状态', async ({ page }) => {
    await page.goto('/');
    // 等 React mount 完成(keydown 监听绑定后再按键，避免时序 flaky)
    await expect(page.locator('.topbar')).toBeVisible();
    await page.keyboard.press('Meta+k');
    await page.locator('.palette-search input').fill('zzz-no-such-cmd-zzz');
    await expect(page.locator('.palette-empty')).toBeVisible();
  });

  test('执行「设置」命令 → 打开设置页并关闭面板', async ({ page }) => {
    await page.goto('/');
    // 等 React mount 完成(keydown 监听绑定后再按键，避免时序 flaky)
    await expect(page.locator('.topbar')).toBeVisible();
    await page.keyboard.press('Meta+k');
    await page.locator('.palette-search input').fill('设置');
    await page.locator('.palette-item').first().click();
    await expect(page.locator('[data-testid="command-palette"]')).toBeHidden();
    await expect(page.locator('[data-testid="settings"]')).toBeVisible();
  });

  test('点击遮罩关闭面板', async ({ page }) => {
    await page.goto('/');
    // 等 React mount 完成(keydown 监听绑定后再按键，避免时序 flaky)
    await expect(page.locator('.topbar')).toBeVisible();
    await page.keyboard.press('Meta+k');
    await expect(page.locator('[data-testid="command-palette"]')).toBeVisible();
    // overlay 左上角点击(避开 .palette 本体)
    await page.locator('[data-testid="command-palette"]').click({ position: { x: 10, y: 10 } });
    await expect(page.locator('[data-testid="command-palette"]')).toBeHidden();
  });
});

test.describe('TerminalDrawer · 终端抽屉', () => {
  test('⌘J 打开抽屉、关闭按钮收起', async ({ page }) => {
    await page.goto('/');
    // 等 React mount 完成(keydown 监听绑定后再按键，避免时序 flaky)
    await expect(page.locator('.topbar')).toBeVisible();
    await page.keyboard.press('Meta+j');
    await expect(page.locator('.term-drawer')).toHaveClass(/open/);
    await page.locator('.term-drawer-close').click();
    await expect(page.locator('.term-drawer')).not.toHaveClass(/open/);
  });

  test('抽屉含 pty 标题与关闭按钮 aria', async ({ page }) => {
    await page.goto('/');
    // 等 React mount 完成(keydown 监听绑定后再按键，避免时序 flaky)
    await expect(page.locator('.topbar')).toBeVisible();
    await page.keyboard.press('Meta+j');
    await expect(page.locator('.term-drawer-title')).toContainText('终端');
    await expect(page.locator('.term-drawer-close')).toHaveAttribute('aria-label', /关闭终端/);
  });
});

test.describe('快捷键 · 全局', () => {
  test('⌘B / ⌘K / ⌘J 互不干扰', async ({ page }) => {
    await page.goto('/');
    // 等 React mount 完成(keydown 监听绑定后再按键，避免时序 flaky)
    await expect(page.locator('.topbar')).toBeVisible();
    await page.keyboard.press('Meta+k'); // 开面板
    await expect(page.locator('[data-testid="command-palette"]')).toBeVisible();
    await page.keyboard.press('Escape');
    await page.keyboard.press('Meta+j'); // 开终端
    await expect(page.locator('.term-drawer')).toHaveClass(/open/);
    await page.keyboard.press('Meta+b'); // 折侧栏
    await expect(page.locator('.app')).toHaveClass(/sb-collapsed/);
    // 状态互不污染
    await expect(page.locator('.term-drawer')).toHaveClass(/open/);
    await expect(page.locator('[data-testid="command-palette"]')).toBeHidden();
  });
});
