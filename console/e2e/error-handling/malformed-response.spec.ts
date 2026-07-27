/**
 * 异常处理测试 · 后端返回畸形/非法响应
 *
 * 目标：验证前端对各种畸形响应（非 JSON、空 body、字段缺失、类型错误）的健壮性。
 *      呼应 store.tsx 的 try/catch + fail-open 设计，确保任意畸形响应都不导致白屏。
 *
 * 覆盖场景：
 *   - 非 JSON 响应（Content-Type=text/html, body="<html>..."）
 *   - 空 body（Content-Type=application/json, body=""）
 *   - 合法 JSON 但结构不符（sessions 返回 {} 而非 []）
 *   - 字段类型错误（sessions[0].id 是数字而非字符串）
 *   - 部分字段缺失（sessions[0] 无 status 字段）
 *   - 嵌套字段为 null（projects.projects = null）
 *
 * 设计原则：
 *   - 不依赖真实后端：所有畸形响应用 page.route 注入
 *   - 断言主壳可见 + 关键元素存在，不断言数据正确性
 *   - 每个 case 独立 mock，互不影响
 */
import { test, expect } from '@playwright/test';

test.use({ viewport: { width: 1280, height: 800 } });

test.describe('异常处理 · 非 JSON 响应', () => {
  test('sessions 返回 HTML 而非 JSON → 主壳不崩', async ({ page }) => {
    await page.route('**/api/v1/sessions', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'text/html',
        body: '<html><body>Not JSON</body></html>',
      }),
    );
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
  });

  test('sessions 返回纯文本 → 主壳不崩', async ({ page }) => {
    await page.route('**/api/v1/sessions', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'text/plain',
        body: 'this is not json',
      }),
    );
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
  });
});

test.describe('异常处理 · 空 body', () => {
  test('sessions 返回空 body（Content-Type=application/json）→ 主壳不崩', async ({ page }) => {
    await page.route('**/api/v1/sessions', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: '',
      }),
    );
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
  });
});

test.describe('异常处理 · JSON 结构不符', () => {
  test('sessions 返回对象而非数组 → 主壳不崩（store 应兜底）', async ({ page }) => {
    await page.route('**/api/v1/sessions', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ not: 'an array' }),
      }),
    );
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    await expect(page.locator('[data-testid="view-assistant"]')).toBeVisible();
  });

  test('metrics 返回数组而非对象 → usage chip 不崩', async ({ page }) => {
    await page.route('**/api/v1/metrics', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([1, 2, 3]),
      }),
    );
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();
  });

  test('projects 返回裸数组而非 {projects_dir, projects, active} → 主壳不崩', async ({ page }) => {
    await page.route('**/api/v1/projects', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{ name: 'bare-array-project' }]),
      }),
    );
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
  });

  test('project/files 的 tree 字段为对象而非数组 → ContextPanel 不崩', async ({ page }) => {
    await page.route('**/api/v1/project/files', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ root: '/tmp', tree: { not: 'array' } }),
      }),
    );
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
  });
});

test.describe('异常处理 · 字段类型错误', () => {
  test('session.id 为数字而非字符串 → 列表仍渲染', async ({ page }) => {
    await page.route('**/api/v1/sessions', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 12345, title: '数字 id 会话', status: 'idle', mode: 'agent' },
        ]),
      }),
    );
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    // 数字 id 会被 String() 转换，会话条目仍应渲染
    await expect(page.locator('.thread').filter({ hasText: '数字 id 会话' })).toBeVisible();
  });

  test('session.status 为 null → 不抛错', async ({ page }) => {
    await page.route('**/api/v1/sessions', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'null-status', title: 'null status', status: null, mode: 'agent' },
        ]),
      }),
    );
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
  });
});

test.describe('异常处理 · 字段缺失', () => {
  test('session 缺失 status 字段 → 列表仍渲染', async ({ page }) => {
    await page.route('**/api/v1/sessions', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'no-status', title: '无 status 字段', mode: 'agent' },
        ]),
      }),
    );
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    await expect(page.locator('.thread').filter({ hasText: '无 status 字段' })).toBeVisible();
  });

  test('session 缺失 mode 字段 → 列表仍渲染', async ({ page }) => {
    await page.route('**/api/v1/sessions', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'no-mode', title: '无 mode 字段', status: 'idle' },
        ]),
      }),
    );
    await page.goto('/');
    await expect(page.locator('.thread').filter({ hasText: '无 mode 字段' })).toBeVisible();
  });

  test('metrics.llm 缺失 → topbar 不崩', async ({ page }) => {
    await page.route('**/api/v1/metrics', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ /* 缺失 llm 字段 */ }),
      }),
    );
    await page.goto('/');
    await expect(page.locator('.topbar')).toBeVisible();
  });
});

test.describe('异常处理 · 嵌套字段为 null', () => {
  test('projects.projects 为 null → 主壳不崩', async ({ page }) => {
    await page.route('**/api/v1/projects', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ projects_dir: '/tmp', projects: null, active: null }),
      }),
    );
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
  });

  test('project/files.tree 为 null → ContextPanel 不崩', async ({ page }) => {
    await page.route('**/api/v1/project/files', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ root: '/tmp', tree: null }),
      }),
    );
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
  });
});
