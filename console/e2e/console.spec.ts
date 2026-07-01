import { test, expect } from '@playwright/test';

test.describe('Console approval flow', () => {
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
