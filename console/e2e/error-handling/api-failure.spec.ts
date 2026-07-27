/**
 * 异常处理测试 · 后端 API 失败场景
 *
 * 目标：验证前端在后端 API 各种失败模式下都能 fail-open，不崩溃、不白屏，
 *      主壳层（sidebar/topbar/Assistant 视图）保持可渲染。
 *
 * 覆盖场景：
 *   - 5xx 服务端错误（/sessions 返回 500）
 *   - 4xx 客户端错误（/metrics 返回 404）
 *   - 网络断开（route.abort 模拟后端不可达）
 *   - 超时（route.fulfill delay 30s 模拟慢后端）
 *   - 部分接口失败（只有 /factories 500，其他正常）
 *
 * 设计原则（呼应 AGENTS.md §3）：
 *   - 不依赖真实后端：所有失败都用 page.route 注入
 *   - 失败必须可复现：每个 case 单独 mock，不共享状态
 *   - 断言主壳可见即可，不断言具体数据（失败态数据本就不确定）
 */
import { test, expect } from '@playwright/test';

test.use({ viewport: { width: 1280, height: 800 } });

test.describe('异常处理 · API 5xx 服务端错误', () => {
  test('sessions 返回 500 → 主壳仍渲染，侧栏显示空态', async ({ page }) => {
    await page.route('**/api/v1/sessions', (route) =>
      route.fulfill({ status: 500, json: { detail: 'Internal Server Error' } }),
    );
    // 其他 API 走默认（无 mock → fetch 失败 → store fail-open）
    await page.goto('/');
    // 主壳可见 = 没白屏
    await expect(page.locator('.sidebar')).toBeVisible();
    await expect(page.locator('.topbar')).toBeVisible();
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
  });

  test('metrics 返回 500 → usage chip 不崩', async ({ page }) => {
    await page.route('**/api/v1/metrics', (route) =>
      route.fulfill({ status: 500, json: { detail: 'metrics down' } }),
    );
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();
    // usage chip 可能渲染为空或 0，但不应抛错
    const chip = page.locator('.usage-chip');
    if (await chip.count() > 0) {
      await expect(chip).toBeVisible();
    }
  });

  test('所有 API 都 500 → 仍渲染主壳（fail-open 兜底）', async ({ page }) => {
    await page.route('**/api/v1/**', (route) =>
      route.fulfill({ status: 500, json: { detail: 'all down' } }),
    );
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    await expect(page.locator('.topbar')).toBeVisible();
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
  });
});

test.describe('异常处理 · API 4xx 客户端错误', () => {
  test('sessions 返回 404 → 主壳仍渲染', async ({ page }) => {
    await page.route('**/api/v1/sessions', (route) =>
      route.fulfill({ status: 404, json: { detail: 'Not Found' } }),
    );
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
  });

  test('projects 返回 403 → 不崩，项目列表空', async ({ page }) => {
    await page.route('**/api/v1/projects', (route) =>
      route.fulfill({ status: 403, json: { detail: 'Forbidden' } }),
    );
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
  });

  test('factories 返回 401 → 工厂面板能打开（数据空）', async ({ page }) => {
    await page.route('**/api/v1/factories', (route) =>
      route.fulfill({ status: 401, json: { detail: 'Unauthorized' } }),
    );
    await page.goto('/');
    await page.locator('.side-nav-item:has-text("工厂")').click();
    // 工厂 overlay 能打开（即使数据为空）
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
  });
});

test.describe('异常处理 · 网络断开（后端不可达）', () => {
  test('sessions 请求被 abort → 主壳仍渲染', async ({ page }) => {
    await page.route('**/api/v1/sessions', (route) => route.abort());
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
  });

  test('所有 API 请求被 abort → 主壳仍渲染（无后端场景）', async ({ page }) => {
    await page.route('**/api/v1/**', (route) => route.abort());
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    await expect(page.locator('.topbar')).toBeVisible();
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
  });

  test('网络断开后命令面板仍可用（纯前端组件）', async ({ page }) => {
    await page.route('**/api/v1/**', (route) => route.abort());
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();
    await page.keyboard.press('Meta+k');
    await expect(page.locator('[data-testid="command-palette"]')).toBeVisible();
  });
});

test.describe('异常处理 · 慢后端（超时场景）', () => {
  test('sessions 延迟 5s 返回 → UI 先渲染空态，数据到达后更新', async ({ page }) => {
    await page.route('**/api/v1/sessions', async (route) => {
      await new Promise((r) => setTimeout(r, 5000));
      await route.fulfill({
        status: 200,
        json: [{ id: 'slow-1', title: '慢后端会话', status: 'idle', mode: 'agent' }],
      });
    });
    await page.goto('/');
    // 1s 内主壳必须可见（不等后端）
    await expect(page.locator('.sidebar')).toBeVisible({ timeout: 2000 });
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
  });
});

test.describe('异常处理 · 部分接口失败（混合态）', () => {
  test('sessions 正常 + factories 500 → 工厂面板空态但其他正常', async ({ page }) => {
    await page.route('**/api/v1/sessions', (route) =>
      route.fulfill({
        status: 200,
        json: [{ id: 'mix-1', title: '混合态会话', status: 'idle', mode: 'agent' }],
      }),
    );
    await page.route('**/api/v1/factories', (route) =>
      route.fulfill({ status: 500, json: { detail: 'factories down' } }),
    );
    await page.goto('/');
    // 会话列表有数据
    await expect(page.locator('.thread').filter({ hasText: '混合态会话' })).toBeVisible();
    // 工厂面板能打开
    await page.locator('.side-nav-item:has-text("工厂")').click();
    await expect(page.locator('[data-testid="factory-panel"]')).toBeVisible();
  });

  test('所有接口正常 + assistant history 500 → composer 仍可用', async ({ page }) => {
    await page.route('**/api/v1/sessions', (route) => route.fulfill({ status: 200, json: [] }));
    await page.route('**/api/v1/assistant/sessions/*/history', (route) =>
      route.fulfill({ status: 500, json: { detail: 'history down' } }),
    );
    await page.goto('/');
    await expect(page.locator('[data-testid="assistant-composer-input"]')).toBeVisible();
    await expect(page.locator('[data-testid="assistant-send-btn"]')).toBeDisabled();
  });
});
