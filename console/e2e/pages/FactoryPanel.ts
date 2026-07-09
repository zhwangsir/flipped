/**
 * Page Object Model — 工厂面板(FactoryPanel)页面对象。
 *
 * 封装工厂面板的所有交互元素与操作，遵循 POM 模式让测试用例保持声明式。
 * 选择器优先级：data-testid > role+name > text > css class。
 */
import { Page, Locator, expect } from '@playwright/test';

export class FactoryPanelPage {
  readonly page: Page;
  readonly overlay: Locator;
  readonly headTitle: Locator;
  readonly refreshBtn: Locator;
  readonly createBtn: Locator;
  readonly closeBtn: Locator;
  readonly factoryList: Locator;
  readonly factoryCards: Locator;
  readonly emptyState: Locator;
  readonly backBtn: Locator;
  readonly goalInput: Locator;
  readonly cwdInput: Locator;
  readonly maxTasksInput: Locator;
  readonly submitBtn: Locator;
  readonly cancelCreateBtn: Locator;
  readonly detailView: Locator;

  constructor(page: Page) {
    this.page = page;
    this.overlay = page.locator('[data-testid="factory-panel"]');
    this.headTitle = page.locator('.factory-head-title span');
    this.refreshBtn = page.locator('.factory-head button[title="刷新"]');
    this.createBtn = page.locator('.factory-head button[title="新建工厂"]');
    this.closeBtn = page.locator('.factory-head button[aria-label="关闭"]');
    this.factoryList = page.locator('.factory-list');
    this.factoryCards = page.locator('.factory-list-card');
    this.emptyState = page.locator('.factory-empty');
    this.backBtn = page.locator('.fd-header .btn-ghost:has-text("返回")');
    this.goalInput = page.locator('.factory-create textarea');
    this.cwdInput = page.locator('.factory-create input[type="text"], .factory-create input:not([type])').first();
    this.maxTasksInput = page.locator('.factory-create input[type="number"]');
    this.submitBtn = page.locator('.factory-create .btn-primary:has-text("启动工厂")');
    this.cancelCreateBtn = page.locator('.factory-create .btn-ghost:has-text("取消")');
    this.detailView = page.locator('.factory-detail');
  }

  /** 从侧栏打开工厂面板 */
  async open() {
    await this.page.locator('.side-nav-item:has-text("工厂")').click();
    await expect(this.overlay).toBeVisible();
  }

  /** 关闭面板 */
  async close() {
    await this.closeBtn.click();
    await expect(this.overlay).toBeHidden();
  }

  /** 获取第 n 张工厂卡片 */
  cardAt(index: number) {
    return this.factoryCards.nth(index);
  }

  /** 打开新建工厂表单 */
  async openCreateForm() {
    await this.createBtn.click();
    await expect(this.goalInput).toBeVisible();
  }

  /** 填写并提交新建工厂（会产生真实副作用，慎用） */
  async fillAndSubmit(goal: string, cwd: string, maxTasks = 3) {
    await this.goalInput.fill(goal);
    await this.cwdInput.fill(cwd);
    await this.maxTasksInput.fill(String(maxTasks));
    await this.submitBtn.click();
  }

  /** 进入详情视图（点击第 n 张卡片） */
  async openDetail(index = 0) {
    await this.factoryCards.nth(index).click();
    await expect(this.detailView).toBeVisible();
  }

  /** 从详情返回列表 */
  async backToList() {
    await this.backBtn.click();
    await expect(this.factoryList).toBeVisible();
  }
}
