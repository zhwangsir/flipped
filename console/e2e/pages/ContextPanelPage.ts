/**
 * Page Object Model — 上下文面板（ContextPanel）+ Launcher 窄栏。
 *
 * 封装 4 个 tab（审查/终端/浏览器/文件）、launcher 图标、面板切换按钮。
 * 与 console/src/components/ContextPanel.tsx + Launcher.tsx 的 .context/.launcher/.tab/.launcher-item 对齐。
 */
import { Page, Locator, expect } from '@playwright/test';

export class ContextPanelPage {
  readonly page: Page;
  readonly root: Locator;
  readonly launcher: Locator;
  readonly tabs: Locator;
  readonly activeTab: Locator;
  readonly toggleBtn: Locator;

  constructor(page: Page) {
    this.page = page;
    this.root = page.locator('.context');
    this.launcher = page.locator('.launcher');
    this.tabs = page.locator('.tab');
    this.activeTab = page.locator('.tab.active');
    this.toggleBtn = page.getByRole('button', { name: '切换上下文面板' });
  }

  async expectVisible() {
    await expect(this.root).toBeVisible();
  }

  async expectHidden() {
    await expect(this.root).toBeHidden();
  }

  /** 切换 context 显示/隐藏；状态变化后 launcher 互补显示 */
  async toggle() {
    await this.toggleBtn.click();
  }

  /** 激活指定名称的 tab（审查/终端/浏览器/文件） */
  async activateTab(name: '审查' | '终端' | '浏览器' | '文件') {
    await this.page.locator(`.tab:has-text("${name}")`).click();
    await expect(this.activeTab).toContainText(name);
  }

  /** 收起 context 后点 launcher 图标重开 */
  async reopenViaLauncher(icon: '审查' | '终端' | '浏览器' | '文件') {
    await this.page.locator(`.launcher-item[aria-label="${icon}"]`).click();
    await expect(this.root).toBeVisible();
    await expect(this.launcher).toBeHidden();
  }
}
