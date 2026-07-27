/**
 * Page Object Model — 命令面板（CommandPalette）。
 *
 * 封装搜索框、命令列表、激活项、关闭行为。
 * 与 console/src/components/CommandPalette.tsx 的 [data-testid="command-palette"] /
 * .palette-search input / .palette-item / .palette-item.active 对齐。
 */
import { Page, Locator, expect } from '@playwright/test';

export class CommandPalettePage {
  readonly page: Page;
  readonly root: Locator;
  readonly searchInput: Locator;
  readonly items: Locator;
  readonly activeItem: Locator;

  constructor(page: Page) {
    this.page = page;
    this.root = page.locator('[data-testid="command-palette"]');
    this.searchInput = page.locator('.palette-search input');
    this.items = page.locator('.palette-item');
    this.activeItem = page.locator('.palette-item.active');
  }

  /** 用 Meta+K 打开命令面板 */
  async openViaHotkey() {
    await this.page.keyboard.press('Meta+k');
    await expect(this.root).toBeVisible();
  }

  /** 用 Escape 关闭 */
  async closeViaEscape() {
    await this.page.keyboard.press('Escape');
    await expect(this.root).toBeHidden();
  }

  /** 输入过滤关键字 */
  async search(keyword: string) {
    await this.searchInput.fill(keyword);
  }

  /** 选择第 n 项 */
  async selectItem(index: number) {
    await this.items.nth(index).click();
  }
}
