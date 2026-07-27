/**
 * Page Object Model — 顶栏（Topbar）。
 *
 * 封装顶栏元素：上下文面板切换按钮、主题切换、usage chip、模型指示器等。
 * 与 console/src/components/Topbar.tsx 的 .topbar / 切换上下文面板 / data-theme 对齐。
 */
import { Page, Locator, expect } from '@playwright/test';

export class TopbarPage {
  readonly page: Page;
  readonly root: Locator;
  readonly toggleContextBtn: Locator;
  readonly usageChip: Locator;
  readonly themeAttr: Locator;

  constructor(page: Page) {
    this.page = page;
    this.root = page.locator('.topbar');
    this.toggleContextBtn = page.getByRole('button', { name: '切换上下文面板' });
    this.usageChip = page.locator('.usage-chip');
    this.themeAttr = page.locator('html');
  }

  async expectVisible() {
    await expect(this.root).toBeVisible();
  }

  /** 切换上下文面板显示/隐藏 */
  async toggleContext() {
    await this.toggleContextBtn.click();
  }

  /** 读取当前 data-theme 值 */
  async currentTheme(): Promise<string | null> {
    return await this.themeAttr.getAttribute('data-theme');
  }
}
