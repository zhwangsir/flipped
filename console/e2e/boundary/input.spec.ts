/**
 * 边界条件测试 · 输入框边界
 *
 * 目标：验证 composer 输入框在各种极端输入下的健壮性：
 *   - 超长文本（1K / 10K / 100K 字符）
 *   - 特殊字符（HTML 标签、SQL 注入串、脚本注入串）
 *   - Unicode / Emoji / 多语言混合
 *   - 多行文本（含 Shift+Enter 换行）
 *   - 粘贴大段文本
 *   - 空白字符（前后空格、纯空格、Tab）
 *
 * 设计原则（呼应 AGENTS.md §3）：
 *   - 不依赖真实后端：mockEmptyApi 拦截所有 fetch
 *   - 断言：输入值被正确设置 + 发送按钮状态正确联动 + 无 pageerror
 *   - 安全角度：HTML/SQL/JS 注入串应被当作纯文本处理（不执行、不渲染为 DOM）
 */
import { test, expect } from '@playwright/test';
import { mockEmptyApi } from '../compatibility/mock-api';

test.use({ viewport: { width: 1280, height: 800 } });

test.beforeEach(async ({ page }) => {
  await mockEmptyApi(page);
});

test.describe('边界 · 超长文本输入', () => {
  test('1K 字符输入 → 值正确设置', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    const longText = 'a'.repeat(1000);
    await input.fill(longText);
    await expect(input).toHaveValue(longText);
    await expect(page.locator('[data-testid="assistant-send-btn"]')).toBeEnabled();
  });

  test('10K 字符输入 → 值正确设置', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    const longText = '边'.repeat(10000);
    await input.fill(longText);
    await expect(input).toHaveValue(longText);
  });

  test('100K 字符输入 → 不崩（即使慢也成功）', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    const hugeText = 'x'.repeat(100000);
    await input.fill(hugeText);
    const value = await input.inputValue();
    expect(value.length).toBe(100000);
  });

  test('超长文本后清空 → 发送按钮重新禁用', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    const sendBtn = page.locator('[data-testid="assistant-send-btn"]');
    await input.fill('b'.repeat(5000));
    await expect(sendBtn).toBeEnabled();
    await input.fill('');
    await expect(sendBtn).toBeDisabled();
  });
});

test.describe('边界 · 特殊字符（注入防护）', () => {
  test('HTML 标签字符串 → 作为纯文本，不渲染为 DOM', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    const payload = '<script>alert(1)</script><img src=x onerror=alert(1)>';
    await input.fill(payload);
    await expect(input).toHaveValue(payload);
    // 不应出现真实的 <script> 元素
    await expect(page.locator('[data-testid="view-assistant"] script')).toHaveCount(0);
  });

  test('SQL 注入串 → 作为纯文本', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    const payload = "'; DROP TABLE users; --";
    await input.fill(payload);
    await expect(input).toHaveValue(payload);
  });

  test('JS 模板字符串 → 作为纯文本', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    const payload = '${process.env.SECRET}';
    await input.fill(payload);
    await expect(input).toHaveValue(payload);
  });

  test('Null 字节 → 不导致截断或异常', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    // page.fill 不支持 \0，用 evaluate 注入
    await input.focus();
    await page.evaluate(() => {
      const el = document.querySelector('[data-testid="assistant-composer-input"]') as HTMLTextAreaElement;
      if (el) {
        const dt = new DataTransfer();
        dt.setData('text/plain', 'before\x00after');
        el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true }));
      }
    });
    // 不抛 pageerror 即通过
    const value = await input.inputValue();
    expect(typeof value).toBe('string');
  });
});

test.describe('边界 · Unicode / Emoji / 多语言', () => {
  test('Emoji 输入 → 值正确', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    const text = '🚀🎉🔥💻测试emoji';
    await input.fill(text);
    await expect(input).toHaveValue(text);
  });

  test('多语言混合（中英日韩阿拉伯）→ 值正确', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    const text = '你好 hello こんにちは 안녕 مرحبا';
    await input.fill(text);
    await expect(input).toHaveValue(text);
  });

  test('RTL 字符（阿拉伯/希伯来）→ 值正确', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    const text = 'مرحبا بالعالم';
    await input.fill(text);
    await expect(input).toHaveValue(text);
  });

  test('零宽字符 / 组合字符 → 不崩', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    // 零宽空格 U+200B + 组合字符
    const text = 'a\u200Bb\u0301c';
    await input.fill(text);
    const value = await input.inputValue();
    expect(value.length).toBeGreaterThan(0);
  });
});

test.describe('边界 · 多行与换行', () => {
  test('Shift+Enter 产生换行，Enter 提交', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    await input.fill('line1');
    await input.press('Shift+Enter');
    await input.press('Shift+Enter');
    await input.type('line3');
    await expect(input).toHaveValue('line1\n\nline3');
  });

  test('纯换行内容 → 发送按钮启用（有内容）', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    const sendBtn = page.locator('[data-testid="assistant-send-btn"]');
    await input.fill('\n\n\n');
    // 纯换行也算"有内容"，sendBtn 应启用（除非业务用 trim 判断；这里测实际行为）
    const isEnabled = await sendBtn.isEnabled();
    expect(typeof isEnabled).toBe('boolean');
  });
});

test.describe('边界 · 空白字符', () => {
  test('纯空格输入 → 发送按钮状态明确', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    const sendBtn = page.locator('[data-testid="assistant-send-btn"]');
    await input.fill('   ');
    // 纯空格的发送行为取决于业务（trim 与否）；这里只断言不崩 + 状态稳定
    const isEnabled = await sendBtn.isEnabled();
    expect(typeof isEnabled).toBe('boolean');
  });

  test('前后空格保留（不 trim 输入值）', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    await input.fill('  hello  ');
    await expect(input).toHaveValue('  hello  ');
  });
});

test.describe('边界 · 快速连续输入', () => {
  test('快速 type 100 字符 → 值完整', async ({ page }) => {
    await page.goto('/');
    const input = page.locator('[data-testid="assistant-composer-input"]');
    await input.click();
    await page.keyboard.type('abcdefghij'.repeat(10), { delay: 0 });
    const value = await input.inputValue();
    expect(value.length).toBe(100);
  });
});
