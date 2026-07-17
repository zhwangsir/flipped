/**
 * E2E — 桌面端布局：三栏结构、侧栏折叠、上下文面板 ↔ 窄图标栏切换。
 * 覆盖用户核心诉求："右侧应是一个侧边栏(窄图标栏)"。
 */
import { test, expect, type Page } from '@playwright/test';

async function collapseContextPanel(page: Page) {
  await page.goto('/');
  await expect(page.locator('.context')).toBeVisible();
  await page.getByRole('button', { name: '切换上下文面板' }).click();
  await expect(page.locator('.context')).toBeHidden();
  await expect(page.locator('.launcher')).toBeVisible();
}

test.describe('布局 · 三栏结构', () => {
  test('侧栏 / 对话区 / 上下文面板同时可见', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.sidebar')).toBeVisible();
    await expect(page.locator('.center')).toBeVisible();
    await expect(page.locator('.context')).toBeVisible();
  });

  test('无水平滚动条、无元素溢出视口', async ({ page }) => {
    await page.goto('/');
    const overflow = await page.evaluate(() => {
      return {
        scrollW: document.documentElement.scrollWidth,
        clientW: document.documentElement.clientWidth,
        scrollH: document.documentElement.scrollHeight,
        clientH: document.documentElement.clientHeight,
      };
    });
    expect(overflow.scrollW).toBeLessThanOrEqual(overflow.clientW + 1);
    expect(overflow.scrollH).toBeLessThanOrEqual(overflow.clientH + 1);
  });
});

test.describe('布局 · 侧栏折叠', () => {
  test('顶栏按钮折叠侧栏 → .app 带 sb-collapsed', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: '折叠侧栏' }).click();
    await expect(page.locator('.app')).toHaveClass(/sb-collapsed/);
  });

  test('⌘B 快捷键折叠/恢复侧栏', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.app')).not.toHaveClass(/sb-collapsed/);
    await page.keyboard.press('Meta+b');
    await expect(page.locator('.app')).toHaveClass(/sb-collapsed/);
    await page.keyboard.press('Meta+b');
    await expect(page.locator('.app')).not.toHaveClass(/sb-collapsed/);
  });
});

test.describe('Launcher · 窄图标侧边栏', () => {
  test.beforeEach(async ({ page }) => {
    await collapseContextPanel(page);
  });

  test('窄栏贴右边缘、宽度 52px、垂直居中', async ({ page }) => {
    const box = await page.locator('.launcher').boundingBox();
    expect(box).not.toBeNull();
    const vw = page.viewportSize()!.width;
    expect(box!.width).toBe(52);
    expect(Math.abs(box!.x + box!.width - vw)).toBeLessThanOrEqual(1);
  });

  test('4 个图标按钮：纯图标、无文字、无 kbd', async ({ page }) => {
    const items = page.locator('.launcher-item');
    await expect(items).toHaveCount(4);
    for (let i = 0; i < 4; i++) {
      const item = items.nth(i);
      expect(await item.innerText()).toBe('');
      await expect(item.locator('svg')).toBeVisible();
      await expect(item.locator('kbd')).toHaveCount(0);
      const box = await item.boundingBox();
      expect(box!.width).toBe(36);
      expect(box!.height).toBe(36);
    }
  });

  test('每个按钮有 aria-label 与 data-label(名称/快捷键)', async ({ page }) => {
    const expected: [string, string][] = [
      ['审查', '审查  ⌃⇧G'],
      ['终端', '终端'],
      ['浏览器', '浏览器  ⌘T'],
      ['文件', '文件  ⌘P'],
    ];
    const items = page.locator('.launcher-item');
    for (let i = 0; i < expected.length; i++) {
      await expect(items.nth(i)).toHaveAttribute('aria-label', expected[i][0]);
      await expect(items.nth(i)).toHaveAttribute('data-label', expected[i][1]);
    }
  });

  test('hover 按钮弹出 tooltip(::before 可见)', async ({ page }) => {
    const first = page.locator('.launcher-item').first();
    await first.hover();
    await page.waitForTimeout(300); // 等 transition
    const { opacity, content } = await first.evaluate((el) => {
      const cs = getComputedStyle(el, '::before');
      return { opacity: cs.opacity, content: cs.content };
    });
    expect(Number(opacity)).toBe(1);
    expect(content).toContain('审查');
  });

  test('容器带 toolbar 语义(role/aria-orientation)', async ({ page }) => {
    const launcher = page.locator('.launcher');
    await expect(launcher).toHaveAttribute('role', 'toolbar');
    await expect(launcher).toHaveAttribute('aria-orientation', 'vertical');
  });

  test('点击「文件」图标：面板重开且文件 tab 激活', async ({ page }) => {
    await page.locator('.launcher-item[aria-label="文件"]').click();
    await expect(page.locator('.context')).toBeVisible();
    await expect(page.locator('.launcher')).toBeHidden();
    await expect(page.locator('.tab.active')).toContainText('文件');
  });

  test('点击「审查」图标：面板重开且审查 tab 激活', async ({ page }) => {
    await page.locator('.launcher-item[aria-label="审查"]').click();
    await expect(page.locator('.tab.active')).toContainText('审查');
  });
});

test.describe('ContextPanel · tab 切换', () => {
  test('四个 tab 可依次激活(active 类跟随)', async ({ page }) => {
    await page.goto('/');
    for (const name of ['审查', '终端', '浏览器', '文件']) {
      await page.locator(`.tab:has-text("${name}")`).click();
      await expect(page.locator('.tab.active')).toContainText(name);
    }
  });
});
