import { test, expect } from '@playwright/test';

// 本用例验证「人工审批流」状态机：approval_request → 前端审批卡 → approval_result。
// 审批事件仅在后端 mock 审批模式（FLIPPED_MOCK_APPROVAL=1）或 orchestrator require_approval
// 配置下产生；真实 dev 全栈（agent 模式直派 OpenHands 沙盒）不经过审批门。
// 因此本用例只在 mock 后端下运行——由 scripts/verify_b5.sh 以 E2E_MOCK_APPROVAL=1 触发；
// 真实全栈跑全量套件时显式 skip（环境门控，非放宽断言，与网络不可达 skip 同一先例）。
const MOCK_APPROVAL = process.env.E2E_MOCK_APPROVAL === '1';

test.describe('Console approval flow', () => {
  test.skip(!MOCK_APPROVAL, '审批流仅存在于 mock 审批后端；真实全栈见 verify_b5.sh');

  test('send task, approve, and complete', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="composer-input"]')).toBeVisible();

    await page.fill('[data-testid="composer-input"]', 'create app.py and test it');
    await page.click('[data-testid="send-button"]');

    await expect(page.locator('[data-testid="approval-card"]')).toBeVisible({ timeout: 15000 });
    await page.click('[data-testid="approve-button"]');

    await expect(page.locator('[data-testid="status-banner"]')).toContainText('任务已完成', { timeout: 30000 });
    await expect(page.locator('.tool-status.ok').first()).toBeVisible();
  });
});
