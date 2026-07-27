/**
 * 跨浏览器兼容性 — 核心交互
 *
 * 目标：验证主要交互在 chromium/firefox/webkit 三引擎下都能正常工作：
 *   - 输入框：textarea 接收键盘输入、字符计数警告
 *   - 按钮：发送按钮 disabled 联动、模式/模型下拉切换
 *   - 会话切换：侧栏「新对话」按钮触发 createSession API（mock 返回后选中）
 *   - 快捷键：⌘B 折叠侧栏 / ⌘K 命令面板（在 firefox/webkit 用 Meta 对应键）
 *
 * 不依赖真实后端：所有 fetch 拦截为 mock 响应。
 */
import { test, expect } from '@playwright/test';
import { mockEmptyApi } from './mock-api';

test.use({ viewport: { width: 1280, height: 800 } });

test.beforeEach(async ({ page }) => {
  await mockEmptyApi(page);
});

test.describe('交互 · Composer 输入框（跨浏览器）', () => {
  test('Assistant 视图 composer 可见且可输入', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    await expect(input).toBeVisible();
    await input.fill('hello from playwright');
    await expect(input).toHaveValue('hello from playwright');
  });

  test('空输入时发送按钮禁用，有内容时启用', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    const sendBtn = page.locator('[data-testid="assistant-send-btn"]');
    await expect(sendBtn).toBeDisabled();
    await input.fill('一个真实任务');
    await expect(sendBtn).toBeEnabled();
    await input.fill('');
    await expect(sendBtn).toBeDisabled();
  });

  test('键盘 Enter 不换行直接触发提交（输入框被清空）', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    await input.fill('task via enter');
    await expect(page.locator('[data-testid="assistant-send-btn"]')).toBeEnabled();
    await input.press('Enter');
    // 提交后 textarea 应清空
    await expect(input).toHaveValue('');
  });

  test('Shift+Enter 换行不触发提交', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    await input.fill('line1');
    await input.press('Shift+Enter');
    await expect(input).toHaveValue('line1\n');
  });

  test('模式 select 可切换：agent → chat → plan', async ({ page }) => {
    await page.goto('/');
    const modeSel = page.locator('[data-testid="assistant-mode-sel"]');
    await expect(modeSel).toBeVisible();
    await expect(modeSel).toHaveValue('agent');
    await modeSel.selectOption('chat');
    await expect(modeSel).toHaveValue('chat');
    await modeSel.selectOption('plan');
    await expect(modeSel).toHaveValue('plan');
  });

  test('模型 select 可切换：coder → architect', async ({ page }) => {
    await page.goto('/');
    const modelSel = page.locator('[data-testid="assistant-model-sel"]');
    await expect(modelSel).toBeVisible();
    await expect(modelSel).toHaveValue('coder');
    await modelSel.selectOption('architect');
    await expect(modelSel).toHaveValue('architect');
  });
});

test.describe('交互 · 侧栏导航按钮（跨浏览器）', () => {
  test('点击「新对话」按钮发起 POST /sessions（mock 拦截）', async ({ page }) => {
    // 在 mockEmptyApi 之上再补一条专门 mock POST /sessions 返回单 session
    await page.route('http://127.0.0.1:8011/api/v1/sessions*', (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({
          status: 200,
          json: { id: 'sess-new-1', title: '新对话', status: 'idle', mode: 'agent' },
        });
      }
      return route.fulfill({ status: 200, json: [] });
    });

    await page.goto('/');
    await page.locator('.side-nav-item:has-text("新对话")').click();
    // mock 返回后侧栏应渲染新会话条目（thread 类）
    await expect(page.locator('.thread').filter({ hasText: '新对话' })).toBeVisible({ timeout: 5000 });
  });

  test('点击「插件」按钮打开 Plugins overlay', async ({ page }) => {
    await page.goto('/');
    await page.locator('.side-nav-item:has-text("插件")').click();
    await expect(page.locator('[data-testid="plugins"]')).toBeVisible();
  });

  test('点击「工厂」按钮打开 FactoryPanel overlay 且 hash 变 #/factory', async ({ page }) => {
    await page.goto('/');
    await page.locator('.side-nav-item:has-text("工厂")').click();
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
    await expect(page).toHaveURL(/#\/factory/);
  });

  test('点击「搜索」按钮打开命令面板', async ({ page }) => {
    await page.goto('/');
    await page.locator('.side-nav-item:has-text("搜索")').click();
    await expect(page.locator('[data-testid="command-palette"]')).toBeVisible();
  });

  test('点击底部「设置」打开设置 overlay', async ({ page }) => {
    await page.goto('/');
    await page.locator('.side-foot-item:has-text("设置")').click();
    await expect(page.locator('[data-testid="settings"]')).toBeVisible();
  });
});

test.describe('交互 · 全局快捷键（跨浏览器）', () => {
  test('Meta+B 折叠/展开侧栏（.app 切换 sb-collapsed）', async ({ page }) => {
    await page.goto('/');
    // 等 React mount + keydown 监听绑定
    await expect(page.locator('.topbar')).toBeVisible();
    await expect(page.locator('.app')).not.toHaveClass(/sb-collapsed/);
    await page.keyboard.press('Meta+b');
    await expect(page.locator('.app')).toHaveClass(/sb-collapsed/);
    await page.keyboard.press('Meta+b');
    await expect(page.locator('.app')).not.toHaveClass(/sb-collapsed/);
  });

  test('Meta+K 打开/关闭命令面板', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();
    await page.keyboard.press('Meta+k');
    await expect(page.locator('[data-testid="command-palette"]')).toBeVisible();
    await page.keyboard.press('Meta+k');
    await expect(page.locator('[data-testid="command-palette"]')).toBeHidden();
  });

  test('Meta+J 打开终端抽屉', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();
    await page.keyboard.press('Meta+j');
    await expect(page.locator('.term-drawer')).toHaveClass(/open/);
  });

  test('Escape 关闭命令面板', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();
    await page.keyboard.press('Meta+k');
    await expect(page.locator('[data-testid="command-palette"]')).toBeVisible();
    // 等 rAF 聚焦完成
    await expect(page.locator('.palette-search input')).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(page.locator('[data-testid="command-palette"]')).toBeHidden();
  });
});

test.describe('交互 · Slash 命令补全（跨浏览器）', () => {
  test('输入 / 弹出 slash 菜单且含 5 个命令', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    await input.fill('/');
    await expect(page.locator('[data-testid="slash-menu"]')).toBeVisible();
    const items = page.locator('[data-testid="slash-menu"] .slash-item');
    await expect(items).toHaveCount(5);
  });

  test('输入 /clear 后 Enter 触发清空（输入框被清空）', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    await input.fill('/clear');
    await input.press('Enter');
    // /clear 走 onSlash 回调，输入框应被清空
    await expect(input).toHaveValue('');
  });

  test('ArrowDown/ArrowUp 在 slash 菜单中移动 active 项', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    await input.focus();
    await input.fill('/');
    await expect(page.locator('[data-testid="slash-menu"]')).toBeVisible();
    // 默认第 0 项 active
    await expect(page.locator('[data-testid="slash-menu"] .slash-item').first()).toHaveClass(/active/);
    // 按 ArrowDown 后第 1 项 active
    await input.press('ArrowDown');
    await expect(page.locator('[data-testid="slash-menu"] .slash-item').nth(1)).toHaveClass(/active/);
  });

  test('Escape 关闭 slash 菜单但保留输入框焦点', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    await input.fill('/');
    await expect(page.locator('[data-testid="slash-menu"]')).toBeVisible();
    await input.press('Escape');
    await expect(page.locator('[data-testid="slash-menu"]')).toBeHidden();
    await expect(input).toBeFocused();
  });
});

test.describe('交互 · 上下文面板切换（跨浏览器）', () => {
  test('切换 context 显示/隐藏 → launcher 窄栏出现/消失', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.context')).toBeVisible();
    await expect(page.locator('.launcher')).toBeHidden();
    await page.getByRole('button', { name: '切换上下文面板' }).click();
    await expect(page.locator('.context')).toBeHidden();
    await expect(page.locator('.launcher')).toBeVisible();
    await page.getByRole('button', { name: '切换上下文面板' }).click();
    await expect(page.locator('.context')).toBeVisible();
    await expect(page.locator('.launcher')).toBeHidden();
  });

  test('context panel 4 个 tab 可依次激活', async ({ page }) => {
    await page.goto('/');
    for (const name of ['审查', '终端', '浏览器', '文件']) {
      await page.locator(`.tab:has-text("${name}")`).click();
      await expect(page.locator('.tab.active')).toContainText(name);
    }
  });

  test('收起 context 后点 launcher「文件」图标重开且文件 tab 激活', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: '切换上下文面板' }).click();
    await expect(page.locator('.launcher')).toBeVisible();
    await page.locator('.launcher-item[aria-label="文件"]').click();
    await expect(page.locator('.context')).toBeVisible();
    await expect(page.locator('.launcher')).toBeHidden();
    await expect(page.locator('.tab.active')).toContainText('文件');
  });
});
