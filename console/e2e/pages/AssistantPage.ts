/**
 * Page Object Model — Assistant 视图（主对话区）。
 *
 * 封装 composer 输入框、发送按钮、模式/模型下拉、slash 命令菜单、消息列表等
 * 核心交互元素。选择器优先级：data-testid > role+name > text > css class。
 *
 * 与 console/src/views/Assistant.tsx 的 data-testid 命名对齐：
 *   - assistant-composer-input
 *   - assistant-send-btn
 *   - assistant-mode-sel
 *   - assistant-model-sel
 *   - slash-menu / slash-item
 */
import { Page, Locator, expect } from '@playwright/test';

export class AssistantPage {
  readonly page: Page;
  readonly view: Locator;
  readonly composerInput: Locator;
  readonly sendBtn: Locator;
  readonly modeSel: Locator;
  readonly modelSel: Locator;
  readonly slashMenu: Locator;
  readonly slashItems: Locator;
  readonly messages: Locator;

  constructor(page: Page) {
    this.page = page;
    this.view = page.locator('[data-testid="view-assistant"]');
    this.composerInput = page.locator('[data-testid="assistant-composer-input"]');
    this.sendBtn = page.locator('[data-testid="assistant-send-btn"]');
    this.modeSel = page.locator('[data-testid="assistant-mode-sel"]');
    this.modelSel = page.locator('[data-testid="assistant-model-sel"]');
    this.slashMenu = page.locator('[data-testid="slash-menu"]');
    this.slashItems = page.locator('[data-testid="slash-menu"] .slash-item');
    this.messages = page.locator('[data-testid="view-assistant"] .msg');
  }

  /** 导航到根路径并等待 Assistant 视图渲染 */
  async goto() {
    await this.page.goto('/');
    await expect(this.view).toBeVisible();
  }

  /** 填入文本（不提交） */
  async type(text: string) {
    await this.composerInput.fill(text);
  }

  /** 追加输入（模拟逐字输入） */
  async typeSlowly(text: string, delay = 20) {
    await this.composerInput.click();
    await this.page.keyboard.type(text, { delay });
  }

  /** 点击发送按钮 */
  async send() {
    await this.sendBtn.click();
  }

  /** 用 Enter 键提交 */
  async sendByEnter() {
    await this.composerInput.press('Enter');
  }

  /** 填入并提交 */
  async typeAndSend(text: string) {
    await this.type(text);
    await this.send();
  }

  /** 切换模式：agent / chat / plan */
  async switchMode(mode: 'agent' | 'chat' | 'plan') {
    await this.modeSel.selectOption(mode);
    await expect(this.modeSel).toHaveValue(mode);
  }

  /** 切换模型：coder / architect */
  async switchModel(model: 'coder' | 'architect') {
    await this.modelSel.selectOption(model);
    await expect(this.modelSel).toHaveValue(model);
  }

  /** 触发 slash 命令菜单（输入 /） */
  async openSlashMenu() {
    await this.composerInput.focus();
    await this.composerInput.fill('/');
    await expect(this.slashMenu).toBeVisible();
  }

  /** 选择第 n 个 slash 命令 */
  async selectSlashItem(index: number) {
    await this.slashItems.nth(index).click();
  }
}
