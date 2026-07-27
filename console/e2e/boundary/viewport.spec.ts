/**
 * 边界条件测试 · 视口尺寸边界
 *
 * 目标：验证 UI 在极端视口尺寸下的健壮性：
 *   - 极小视口（320×240 / 240×400）→ 移动端布局不溢出
 *   - 极大视口（1920×1080 / 2560×1440）→ 桌面布局正常
 *   - 断点边界值（767 / 768 / 769）→ @media 切换正确
 *   - 0 宽高边界 → 不崩
 *
 * 设计原则（呼应 app.css @media (max-width: 768px)）：
 *   - 断点为 768px：≤768 走移动端分支，>768 走桌面端
 *   - 关键断言：无水平滚动条（scrollWidth ≤ clientWidth）
 *   - 主壳可见 = 不白屏
 */
import { test, expect } from '@playwright/test';
import { mockEmptyApi } from '../compatibility/mock-api';

test.beforeEach(async ({ page }) => {
  await mockEmptyApi(page);
});

test.describe('边界 · 极小视口', () => {
  test('320×568（iPhone SE）→ 移动端布局 + tabbar 可见 + sidebar 抽屉化', async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 568 });
    await page.goto('/');
    await expect(page.locator('.mobile-tabbar')).toBeVisible();
    // 移动端 sidebar 用 CSS transform 抽屉化（非 display:none），
    // 用 .app 无 mobile-sidebar-open 类判断"默认收起"（与 responsive.spec.ts 对齐）
    await expect(page.locator('.app')).not.toHaveClass(/mobile-sidebar-open/);
  });

  test('240×320（极小）→ 不崩，无水平溢出', async ({ page }) => {
    await page.setViewportSize({ width: 240, height: 320 });
    await page.goto('/');
    await expect(page.locator('.mobile-tabbar')).toBeVisible();
    const overflow = await page.evaluate(() => ({
      scrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
    }));
    expect(overflow.scrollW).toBeLessThanOrEqual(overflow.clientW + 2);
  });
});

test.describe('边界 · 极大视口', () => {
  test('1920×1080 → 桌面三栏布局正常', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    await expect(page.locator('.context')).toBeVisible();
    await expect(page.locator('.mobile-tabbar')).toBeHidden();
  });

  test('2560×1440 → 桌面布局无溢出', async ({ page }) => {
    await page.setViewportSize({ width: 2560, height: 1440 });
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    const overflow = await page.evaluate(() => ({
      scrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
    }));
    expect(overflow.scrollW).toBeLessThanOrEqual(overflow.clientW + 1);
  });
});

test.describe('边界 · 断点边界值（768px @media）', () => {
  test('769px（>768）→ 桌面端：三栏 + 无 tabbar', async ({ page }) => {
    await page.setViewportSize({ width: 769, height: 800 });
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    await expect(page.locator('.context')).toBeVisible();
    await expect(page.locator('.mobile-tabbar')).toBeHidden();
  });

  test('768px（≤768 含等号）→ 移动端：tabbar 可见', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 800 });
    await page.goto('/');
    await expect(page.locator('.mobile-tabbar')).toBeVisible();
  });

  test('767px（<768）→ 移动端：tabbar 可见', async ({ page }) => {
    await page.setViewportSize({ width: 767, height: 800 });
    await page.goto('/');
    await expect(page.locator('.mobile-tabbar')).toBeVisible();
  });

  test('断点跳变：768 → 769 切桌面，769 → 768 切移动', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 800 });
    await page.goto('/');
    await expect(page.locator('.mobile-tabbar')).toBeVisible();
    await page.setViewportSize({ width: 769, height: 800 });
    await page.waitForTimeout(300);
    await expect(page.locator('.mobile-tabbar')).toBeHidden();
    await expect(page.locator('.sidebar')).toBeVisible();
    await page.setViewportSize({ width: 768, height: 800 });
    await page.waitForTimeout(300);
    await expect(page.locator('.mobile-tabbar')).toBeVisible();
  });
});

test.describe('边界 · 动态 resize', () => {
  test('连续 resize 5 次 → 不崩，最终态正确', async ({ page }) => {
    await page.goto('/');
    const sizes = [
      { w: 1280, h: 800 },
      { w: 375, h: 812 },
      { w: 768, h: 1024 },
      { w: 1920, h: 1080 },
      { w: 320, h: 568 },
    ];
    for (const s of sizes) {
      await page.setViewportSize({ width: s.w, height: s.h });
      await page.waitForTimeout(150);
    }
    // 最终态：320×568 → 移动端
    await expect(page.locator('.mobile-tabbar')).toBeVisible();
  });
});
