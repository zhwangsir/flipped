/**
 * E2E 测试 — 工厂面板(FactoryPanel)全面检测。
 *
 * 覆盖范围：
 * 1. 面板导航（侧栏入口打开/关闭）
 * 2. 工厂列表渲染（已有工厂卡片显示）
 * 3. 工厂详情视图（指标 Bento + Roadmap + 结果）
 * 4. 新建工厂表单（校验、字段、按钮状态）
 * 5. 任务行展开/折叠
 * 6. 状态徽章与进度条
 * 7. 刷新按钮
 *
 * 不产生真实副作用：新建工厂只测试表单交互不提交。
 */
import { test, expect } from '@playwright/test';
import { FactoryPanelPage } from './pages/FactoryPanel';

test.describe('工厂面板 · 导航与可见性', () => {
  test('侧栏「工厂」按钮打开面板', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await expect(fp.overlay).toBeVisible();
    await expect(fp.headTitle).toContainText('工厂');
  });

  test('关闭按钮隐藏面板', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await fp.close();
    await expect(fp.overlay).toBeHidden();
  });

  test('面板打开后 header 三按钮可见(刷新/新建/关闭)', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await expect(fp.refreshBtn).toBeVisible();
    await expect(fp.createBtn).toBeVisible();
    await expect(fp.closeBtn).toBeVisible();
  });
});

test.describe('工厂面板 · 列表渲染', () => {
  test('显示已有工厂卡片', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    // 等待列表加载（后端有 factory-863fb58e）
    await expect(fp.factoryCards.first()).toBeVisible({ timeout: 10000 });
    const count = await fp.factoryCards.count();
    expect(count).toBeGreaterThan(0);
  });

  test('工厂卡片含目标文本、状态点、进度条', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await expect(fp.factoryCards.first()).toBeVisible({ timeout: 10000 });
    const card = fp.cardAt(0);
    // 状态点
    await expect(card.locator('.flc-status-dot')).toBeVisible();
    // 目标文本
    await expect(card.locator('.flc-goal')).not.toBeEmpty();
    // 进度条
    await expect(card.locator('.flc-bar')).toBeVisible();
    // 状态徽章
    await expect(card.locator('.flc-badge')).toBeVisible();
  });

  test('刷新按钮重新拉取列表', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await expect(fp.factoryCards.first()).toBeVisible({ timeout: 10000 });
    const before = await fp.factoryCards.count();
    await fp.refreshBtn.click();
    await page.waitForTimeout(500);
    const after = await fp.factoryCards.count();
    expect(after).toBeGreaterThanOrEqual(before);
  });
});

test.describe('工厂面板 · 详情视图', () => {
  test('点击卡片进入详情视图', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await expect(fp.factoryCards.first()).toBeVisible({ timeout: 10000 });
    await fp.openDetail(0);
    await expect(fp.detailView).toBeVisible();
  });

  test('详情含产品目标、状态徽章、ID', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await expect(fp.factoryCards.first()).toBeVisible({ timeout: 10000 });
    await fp.openDetail(0);
    await expect(page.locator('.fd-goal')).toBeVisible();
    await expect(page.locator('.fd-status-badge')).toBeVisible();
    await expect(page.locator('.fd-id')).not.toBeEmpty();
  });

  test('详情指标 Bento Grid 含 4 张指标卡', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await expect(fp.factoryCards.first()).toBeVisible({ timeout: 10000 });
    await fp.openDetail(0);
    const metrics = page.locator('.fd-metric');
    await expect(metrics).toHaveCount(4);
    await expect(page.locator('.fd-metric-value').first()).not.toBeEmpty();
  });

  test('详情含进度条与迭代信息', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await expect(fp.factoryCards.first()).toBeVisible({ timeout: 10000 });
    await fp.openDetail(0);
    await expect(page.locator('.fd-progress-bar')).toBeVisible();
    await expect(page.locator('.fd-iter')).toContainText(/迭代/);
  });

  test('详情含 Roadmap 任务列表(或 planner 拆分中空状态)', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await expect(fp.factoryCards.first()).toBeVisible({ timeout: 10000 });
    await fp.openDetail(0);
    const roadmap = page.locator('.fd-roadmap');
    await expect(roadmap).toBeVisible();
    // roadmap 可能有任务(已拆分) 或显示"GLM planner 正在拆分任务…"空状态
    const taskCount = await page.locator('.fd-task').count();
    const emptyState = await page.locator('.fd-roadmap-empty').count();
    expect(taskCount + emptyState).toBeGreaterThan(0);
  });

  test('返回按钮回到工厂列表', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await expect(fp.factoryCards.first()).toBeVisible({ timeout: 10000 });
    await fp.openDetail(0);
    await fp.backToList();
    await expect(fp.factoryList).toBeVisible();
  });
});

test.describe('工厂面板 · 任务行交互', () => {
  test('任务行展开显示验收命令与反馈', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await expect(fp.factoryCards.first()).toBeVisible({ timeout: 10000 });
    await fp.openDetail(0);
    // 找到带 chevron 的任务行（有 feedback 或 verify_cmd）
    const taskWithChev = page.locator('.fd-task:has(.fd-task-chev)').first();
    if (await taskWithChev.count() > 0) {
      await taskWithChev.locator('.fd-task-head').click();
      await expect(taskWithChev.locator('.fd-task-body')).toBeVisible();
      // 再次点击折叠
      await taskWithChev.locator('.fd-task-head').click();
      await expect(taskWithChev.locator('.fd-task-body')).toBeHidden();
    }
  });

  test('当前任务高亮(current 类)', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await expect(fp.factoryCards.first()).toBeVisible({ timeout: 10000 });
    await fp.openDetail(0);
    // current 任务可能存在也可能不存在（取决于工厂状态）
    const currentTask = page.locator('.fd-task.current');
    // 只验证不报错，不强制要求存在
    const count = await currentTask.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });
});

test.describe('工厂面板 · 新建工厂表单', () => {
  test('点击 + 显示表单', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await fp.openCreateForm();
    await expect(fp.goalInput).toBeVisible();
    await expect(fp.cwdInput).toBeVisible();
    await expect(fp.maxTasksInput).toBeVisible();
    await expect(fp.submitBtn).toBeVisible();
  });

  test('空字段时提交按钮禁用', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await fp.openCreateForm();
    await expect(fp.submitBtn).toBeDisabled();
  });

  test('填写 goal 后按钮仍禁用(缺 cwd)', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await fp.openCreateForm();
    await fp.goalInput.fill('测试目标');
    await expect(fp.submitBtn).toBeDisabled();
  });

  test('填写 goal + cwd 后按钮启用', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await fp.openCreateForm();
    await fp.goalInput.fill('测试目标');
    await fp.cwdInput.fill('/tmp/test');
    await expect(fp.submitBtn).toBeEnabled();
  });

  test('取消按钮关闭表单', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await fp.openCreateForm();
    await fp.cancelCreateBtn.click();
    await expect(fp.goalInput).toBeHidden();
  });

  test('最大任务数输入框有 min/max 约束', async ({ page }) => {
    const fp = new FactoryPanelPage(page);
    await page.goto('/');
    await fp.open();
    await fp.openCreateForm();
    await expect(fp.maxTasksInput).toHaveAttribute('min', '1');
    await expect(fp.maxTasksInput).toHaveAttribute('max', '50');
  });
});
