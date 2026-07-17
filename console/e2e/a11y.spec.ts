/**
 * E2E — 可访问性：axe-core 扫描主壳与各覆盖层。
 * 违规会逐条打印，便于定位修复。
 */
import { test, expect, type Page } from '@playwright/test';
import { AxeBuilder } from '@axe-core/playwright';

async function scan(page: Page, label: string, include?: string) {
  let builder = new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']);
  if (include) builder = builder.include(include);
  const results = await builder.analyze();
  if (results.violations.length > 0) {
    const summary = results.violations.map((v) => {
      const nodes = v.nodes.slice(0, 5).map((n) => `    - ${n.target.join(' ')} :: ${n.failureSummary?.split('\n')[0] ?? ''}`).join('\n');
      return `  [${v.impact}] ${v.id}: ${v.description} (${v.nodes.length} 处)\n${nodes}`;
    }).join('\n');
    console.log(`\n[a11y:${label}] ${results.violations.length} 类违规:\n${summary}\n`);
  }
  return results.violations;
}

test.describe('可访问性 · axe 扫描', () => {
  // reduced-motion: 禁用入场动画,避免 axe 在 opacity 过渡中扫描产生对比度误报
  // (同时验证 global.css 的 prefers-reduced-motion 规则真实生效)
  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
  });

  test('主壳(三栏)无 A/AA 级违规', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    const violations = await scan(page, '主壳');
    expect(violations).toEqual([]);
  });

  test('窄图标栏状态无 A/AA 级违规', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: '切换上下文面板' }).click();
    await expect(page.locator('.launcher')).toBeVisible();
    const violations = await scan(page, '窄图标栏');
    expect(violations).toEqual([]);
  });

  test('设置页无 A/AA 级违规', async ({ page }) => {
    await page.goto('/');
    await page.locator('.side-foot-item:has-text("设置")').click();
    await expect(page.locator('[data-testid="settings"]')).toBeVisible();
    const violations = await scan(page, '设置页', '[data-testid="settings"]');
    expect(violations).toEqual([]);
  });

  test('命令面板无 A/AA 级违规', async ({ page }) => {
    await page.goto('/');
    // 等 React mount 完成(keydown 监听绑定后再按键,避免时序 flaky)
    await expect(page.locator('.topbar')).toBeVisible();
    await page.keyboard.press('Meta+k');
    await expect(page.locator('[data-testid="command-palette"]')).toBeVisible();
    const violations = await scan(page, '命令面板', '[data-testid="command-palette"]');
    expect(violations).toEqual([]);
  });

  test('工厂面板无 A/AA 级违规', async ({ page }) => {
    await page.goto('/');
    await page.locator('.side-nav-item:has-text("工厂")').click();
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
    const violations = await scan(page, '工厂面板', '[data-testid="factory-panel"]');
    expect(violations).toEqual([]);
  });

  test('移动端视口主壳无 A/AA 级违规', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    await expect(page.locator('.mobile-tabbar')).toBeVisible();
    const violations = await scan(page, '移动端主壳');
    expect(violations).toEqual([]);
  });

  test('深色主题主壳无 A/AA 级违规', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: '切换到暗色' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    const violations = await scan(page, '深色主壳');
    expect(violations).toEqual([]);
  });

  test('深色主题设置页无 A/AA 级违规', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: '切换到暗色' }).click();
    await page.locator('.side-foot-item:has-text("设置")').click();
    await expect(page.locator('[data-testid="settings"]')).toBeVisible();
    const violations = await scan(page, '深色设置页', '[data-testid="settings"]');
    expect(violations).toEqual([]);
  });
});
