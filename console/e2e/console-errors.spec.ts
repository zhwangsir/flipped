/**
 * E2E — 控制台健康：遍历主要交互路径，捕获 console.error / pageerror。
 * 目标：零 React 警告(如 key 重复)、零未捕获异常。
 */
import { test, expect, type Page } from '@playwright/test';
import { mockBackend } from './accessibility/helpers';

// 拦截 :8011 HTTP API，让前端 fetch 不再产生 net::ERR_CONNECTION_REFUSED 噪音。
// 这样 console.error 断言才能真正捕获 React 警告/未捕获异常等被测代码的问题，
// 而不是被后端不可达的环境噪音淹没。WS 连接仍会失败，由下方 IGNORE_PATTERNS 兜底。
test.beforeEach(async ({ page }) => {
  await mockBackend(page);
});

/** 已知无害噪音(按需扩充,每条需注明原因) */
const IGNORE_PATTERNS: RegExp[] = [
  /Download the React DevTools/i, // React 开发提示
  /favicon/i, // favicon 404
  /WebSocket.*(failed|closed|reconnect)/i, // 后端 WS 未连接时的重试噪音(本地无后端场景)
  /vite.*hmr/i, // Vite HMR 日志
  /Failed to load resource.*8011/i, // dev 无后端时 WS upgrade 到 :8011 的连接失败噪音
  /net::ERR_CONNECTION_REFUSED/i, // 同上兜底：WS 重建时 :8011 不可达的网络错误
];

interface Collected {
  kind: 'console.error' | 'pageerror';
  text: string;
}

function watch(page: Page, bag: Collected[]) {
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return;
    const text = msg.text();
    if (IGNORE_PATTERNS.some((p) => p.test(text))) return;
    bag.push({ kind: 'console.error', text });
  });
  page.on('pageerror', (err) => {
    const text = String(err);
    if (IGNORE_PATTERNS.some((p) => p.test(text))) return;
    bag.push({ kind: 'pageerror', text });
  });
}

test.describe('控制台健康 · 无错误无警告', () => {
  test('首屏加载无 console.error / pageerror', async ({ page }) => {
    const errors: Collected[] = [];
    watch(page, errors);
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    await page.waitForTimeout(2000); // 等异步渲染/WS
    expect(errors).toEqual([]);
  });

  test('主要交互遍历(面板/设置/命令板/终端/tab/折叠)无错误', async ({ page }) => {
    const errors: Collected[] = [];
    watch(page, errors);
    await page.goto('/');

    // 1. 上下文面板 tab 全切一遍
    for (const name of ['审查', '终端', '浏览器', '文件']) {
      await page.locator(`.tab:has-text("${name}")`).click();
      await page.waitForTimeout(200);
    }
    // 2. 收起面板 → 窄图标栏 → 逐个图标点开
    await page.getByRole('button', { name: '切换上下文面板' }).click();
    await expect(page.locator('.launcher')).toBeVisible();
    for (const label of ['审查', '终端', '浏览器', '文件']) {
      await page.locator(`.launcher-item[aria-label="${label}"]`).click();
      await page.waitForTimeout(150);
      await page.getByRole('button', { name: '切换上下文面板' }).click();
      await page.waitForTimeout(150);
    }
    // 从窄栏状态恢复面板
    await page.locator('.launcher-item[aria-label="文件"]').click();

    // 3. 命令面板
    await page.keyboard.press('Meta+k');
    await page.locator('.palette-search input').fill('设置');
    await page.keyboard.press('Escape');

    // 4. 设置页
    await page.locator('.side-foot-item:has-text("设置")').click();
    await expect(page.locator('[data-testid="settings"]')).toBeVisible();
    await page.locator('.settings-back').click();

    // 5. 终端抽屉
    await page.keyboard.press('Meta+j');
    await page.locator('.term-drawer-close').click();

    // 6. 侧栏折叠/恢复
    await page.keyboard.press('Meta+b');
    await page.keyboard.press('Meta+b');

    // 7. 工厂面板开/关
    await page.locator('.side-nav-item:has-text("工厂")').click();
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
    await page.locator('[data-testid="factory-panel"] button[aria-label="关闭"]').click();

    // 8. 插件面板开/关
    await page.locator('.side-nav-item:has-text("插件")').click();
    await expect(page.locator('[data-testid="plugins"]')).toBeVisible();
    await page.keyboard.press('Escape');

    await page.waitForTimeout(1000);
    expect(errors).toEqual([]);
  });

  test('移动端交互遍历无错误', async ({ page }) => {
    const errors: Collected[] = [];
    watch(page, errors);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');

    await page.locator('.mobile-tabbar').getByRole('button', { name: '对话列表' }).click();
    await page.locator('.mobile-overlay').first().click();
    await page.locator('.mobile-tabbar').getByRole('button', { name: '上下文面板' }).click();
    await page.locator('.mobile-overlay').first().click();
    await page.locator('.mobile-tabbar').getByRole('button', { name: '设置' }).click();
    await expect(page.locator('[data-testid="settings"]')).toBeVisible();
    await page.locator('.settings-back').click();

    await page.waitForTimeout(1000);
    expect(errors).toEqual([]);
  });
});
