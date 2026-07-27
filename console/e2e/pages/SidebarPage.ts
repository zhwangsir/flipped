/**
 * Page Object Model — 侧栏（Sidebar）。
 *
 * 封装侧栏导航项（新对话/插件/工厂/搜索）、底部设置、会话列表（threads）。
 * 选择器与 console/src/components/Sidebar.tsx 的 .side-nav-item / .side-foot-item / .thread 对齐。
 */
import { Page, Locator, expect } from '@playwright/test';

export class SidebarPage {
  readonly page: Page;
  readonly root: Locator;
  readonly newItem: Locator;
  readonly pluginsItem: Locator;
  readonly factoryItem: Locator;
  readonly searchItem: Locator;
  readonly settingsItem: Locator;
  readonly threads: Locator;

  constructor(page: Page) {
    this.page = page;
    this.root = page.locator('.sidebar');
    this.newItem = page.locator('.side-nav-item:has-text("新对话")');
    this.pluginsItem = page.locator('.side-nav-item:has-text("插件")');
    this.factoryItem = page.locator('.side-nav-item:has-text("工厂")');
    this.searchItem = page.locator('.side-nav-item:has-text("搜索")');
    this.settingsItem = page.locator('.side-foot-item:has-text("设置")');
    this.threads = page.locator('.thread');
  }

  async expectVisible() {
    await expect(this.root).toBeVisible();
  }

  /** 点击「新对话」按钮 */
  async clickNew() {
    await this.newItem.click();
  }

  /** 点击「插件」打开 Plugins overlay */
  async clickPlugins() {
    await this.pluginsItem.click();
    await expect(this.page.locator('[data-testid="plugins"]')).toBeVisible();
  }

  /** 点击「工厂」打开 FactoryPanel overlay */
  async clickFactory() {
    await this.factoryItem.click();
    await expect(this.page.locator('[data-testid="factory-panel"]')).toBeVisible();
  }

  /** 点击「搜索」打开命令面板 */
  async clickSearch() {
    await this.searchItem.click();
    await expect(this.page.locator('[data-testid="command-palette"]')).toBeVisible();
  }

  /** 点击底部「设置」 */
  async clickSettings() {
    await this.settingsItem.click();
    await expect(this.page.locator('[data-testid="settings"]')).toBeVisible();
  }

  /** 按 title 模糊匹配会话条目 */
  threadByTitle(title: string): Locator {
    return this.threads.filter({ hasText: title });
  }
}
