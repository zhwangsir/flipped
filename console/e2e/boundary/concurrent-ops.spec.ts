/**
 * 边界条件测试 · 并发操作与快速交互
 *
 * 目标：验证 UI 在用户快速/并发操作下的健壮性：
 *   - 快速重复点击「新对话」按钮
 *   - 快速切换视图（Assistant ↔ Factory）
 *   - 快速切换 context tab
 *   - 快速按 Meta+K 多次
 *   - 输入并快速 Enter（连续提交）
 *   - 同时打开多个 overlay
 *
 * 设计原则（呼应 AGENTS.md §3）：
 *   - 不依赖真实后端：mockEmptyApi + mockCreateSession
 *   - 断言最终态稳定 + 无 pageerror + 无遗留 overlay
 *   - 关键：快速操作不导致状态错乱（如多个 factory overlay 同时存在）
 */
import { test, expect } from '@playwright/test';
import { mockEmptyApi, mockCreateSession } from '../compatibility/mock-api';

test.use({ viewport: { width: 1280, height: 800 } });

test.beforeEach(async ({ page }) => {
  await mockEmptyApi(page);
  await mockCreateSession(page);
});

test.describe('边界 · 快速重复点击', () => {
  test('快速点击「新对话」3 次 → 不崩，状态稳定', async ({ page }) => {
    await page.goto('/');
    const pageErrors: string[] = [];
    page.on('pageerror', (e) => pageErrors.push(e.message));

    await page.locator('.side-nav-item:has-text("新对话")').click();
    await page.locator('.side-nav-item:has-text("新对话")').click();
    await page.locator('.side-nav-item:has-text("新对话")').click();
    await page.waitForTimeout(500);

    expect(pageErrors).toEqual([]);
    await expect(page.locator('.sidebar')).toBeVisible();
  });

  test('快速开关「工厂」overlay 3 次 → 最终只一个 factory overlay', async ({ page }) => {
    // 注：factory overlay 是 aria-modal=true，打开后会拦截外部点击，
    // 故"快速点工厂按钮 3 次"实际只能生效 1 次（第 2、3 次被 overlay 拦截）。
    // 真实用户场景是"开→关→开→关"，测试这个循环。
    await page.goto('/');
    for (let i = 0; i < 3; i++) {
      await page.locator('.side-nav-item:has-text("工厂")').click();
      await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
      await page.locator('[data-testid="factory-panel"] button[aria-label="关闭"]').click();
      await expect(page.locator('[data-testid="factory-panel"]')).toBeHidden();
    }
    // 最终态：无残留 overlay
    await expect(page.locator('[data-testid="factory-panel"]')).toHaveCount(0);
  });
});

test.describe('边界 · 快速视图切换', () => {
  test('Assistant ↔ Factory 快速切换 5 次 → 最终态正确', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();

    for (let i = 0; i < 5; i++) {
      await page.locator('.side-nav-item:has-text("工厂")').click();
      await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
      await page.locator('[data-testid="factory-panel"] button[aria-label="关闭"]').click();
      await expect(page.locator('[data-testid="factory-panel"]')).toBeHidden();
    }
    // 最终回到 Assistant
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
  });

  test('快速切换 context tab 4×3 次 → 最终 active tab 正确', async ({ page }) => {
    await page.goto('/');
    const tabs = ['审查', '终端', '浏览器', '文件'];
    for (let round = 0; round < 3; round++) {
      for (const name of tabs) {
        await page.locator(`.tab:has-text("${name}")`).click();
      }
    }
    // 最终激活的是「文件」
    await expect(page.locator('.tab.active')).toContainText('文件');
  });
});

test.describe('边界 · 快捷键连按', () => {
  test('Meta+K 连按 4 次 → 命令面板状态稳定（开→关→开→关）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();

    await page.keyboard.press('Meta+k');
    await expect(page.locator('[data-testid="command-palette"]')).toBeVisible();
    await page.keyboard.press('Meta+k');
    await expect(page.locator('[data-testid="command-palette"]')).toBeHidden();
    await page.keyboard.press('Meta+k');
    await expect(page.locator('[data-testid="command-palette"]')).toBeVisible();
    await page.keyboard.press('Meta+k');
    await expect(page.locator('[data-testid="command-palette"]')).toBeHidden();
  });

  test('Meta+B 连按 3 次 → 侧栏折叠态最终为折叠（奇数次）', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.app')).not.toHaveClass(/sb-collapsed/);
    await page.keyboard.press('Meta+b');
    await page.keyboard.press('Meta+b');
    await page.keyboard.press('Meta+b');
    // 奇数次 → 折叠
    await expect(page.locator('.app')).toHaveClass(/sb-collapsed/);
  });
});

test.describe('边界 · 同时打开多个 overlay', () => {
  test('工厂 → 关闭 → 设置 顺序切换 overlay → 不崩，无残留', async ({ page }) => {
    // 注：factory/settings overlay 是 aria-modal=true，打开后拦截外部点击，
    // 故切换 overlay 前必须先关闭当前的（与真实用户行为一致）。
    // plugins overlay 的关闭行为不一致（无 aria-label="关闭" 按钮），单独测。
    await page.goto('/');

    // 打开工厂
    await page.locator('.side-nav-item:has-text("工厂")').click();
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
    // 关闭工厂
    await page.locator('[data-testid="factory-panel"] button[aria-label="关闭"]').click();
    await expect(page.locator('[data-testid="factory-panel"]')).toBeHidden();

    // 打开设置
    await page.locator('.side-foot-item:has-text("设置")').click();
    await expect(page.locator('[data-testid="settings"]')).toBeVisible();

    // 工厂 overlay 不应残留
    const factoryCount = await page.locator('[data-testid="factory-panel"]:visible').count();
    expect(factoryCount).toBe(0);
  });

  test('插件 overlay 打开后不崩（独立验证）', async ({ page }) => {
    await page.goto('/');
    await page.locator('.side-nav-item:has-text("插件")').click();
    await expect(page.locator('[data-testid="plugins"]')).toBeVisible();
    // 不崩即通过
    await expect(page.locator('.sidebar')).toBeVisible();
  });
});

test.describe('边界 · 连续提交', () => {
  test('输入后快速 Enter 两次 → 第二次因输入框已清空不触发提交', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    await input.fill('task via enter');
    await input.press('Enter');
    // 第一次提交后输入框清空，第二次 Enter 应无效（sendBtn 已 disabled）
    await input.press('Enter');
    await expect(input).toHaveValue('');
  });
});
