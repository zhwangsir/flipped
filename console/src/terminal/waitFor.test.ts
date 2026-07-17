// @vitest-environment node
/**
 * M136-C — waitFor 自身的单元测试：text/regex/gone/stableMs/超时诊断。
 */
import { describe, expect, it } from 'vitest';
import { Terminal } from '@xterm/headless';
import { feed, screenText, waitFor } from './waitFor';

function makeTerm(): Terminal {
  return new Terminal({ cols: 80, rows: 24, scrollback: 200, allowProposedApi: true });
}

describe('waitFor · text', () => {
  it('屏面出现目标子串即 resolve，返回屏面文本', async () => {
    const term = makeTerm();
    const p = waitFor(term, { text: 'hello world' });
    await feed(term, 'hello world\r\n');
    const screen = await p;
    expect(screen).toContain('hello world');
  });

  it('条件早已满足时立即 resolve（不必等新写入）', async () => {
    const term = makeTerm();
    await feed(term, 'already here\r\n');
    const screen = await waitFor(term, { text: 'already here' });
    expect(screen).toContain('already here');
  });
});

describe('waitFor · regex', () => {
  it('正则匹配屏面', async () => {
    const term = makeTerm();
    const p = waitFor(term, { regex: /MARKER-009/ });
    for (let i = 0; i < 10; i++) {
      // 分批写入，验证跨 chunk 的匹配
      await feed(term, `MARKER-00${i}\r\n`);
    }
    const screen = await p;
    expect(screen).toMatch(/MARKER-009/);
  });
});

describe('waitFor · gone', () => {
  it('目标子串从屏面消失后 resolve', async () => {
    const term = makeTerm();
    await feed(term, 'loading...\r\n');
    const p = waitFor(term, { gone: 'loading...' });
    // 清屏 + 光标归位 + 新内容作为一次原子写入（避免中间态提前成交）
    await feed(term, '\x1b[2J\x1b[Hdone\r\n');
    const screen = await p;
    expect(screen).not.toContain('loading...');
    expect(screen).toContain('done');
  });
});

describe('waitFor · stableMs', () => {
  it('屏面静默 N 毫秒后才 resolve', async () => {
    const term = makeTerm();
    const t0 = Date.now();
    const p = waitFor(term, { text: 'steady', stableMs: 120 });
    await feed(term, 'steady\r\n');
    const screen = await p;
    const elapsed = Date.now() - t0;
    expect(screen).toContain('steady');
    expect(elapsed).toBeGreaterThanOrEqual(110); // 允许定时器少量误差
  });

  it('静默期内有新写入则重新计时', async () => {
    const term = makeTerm();
    const t0 = Date.now();
    const p = waitFor(term, { text: 'burst', stableMs: 150 });
    await feed(term, 'burst-1\r\n');
    // 静默期内又来一发：屏面变化 → stableMs 重算
    await new Promise((r) => setTimeout(r, 60));
    await feed(term, 'burst-2\r\n');
    const screen = await p;
    const elapsed = Date.now() - t0;
    expect(screen).toContain('burst-2');
    expect(elapsed).toBeGreaterThanOrEqual(200); // 60ms + 150ms 静默
  });
});

describe('waitFor · 超时诊断', () => {
  it('reject 信息含当前屏面与最近 raw 输入', async () => {
    const term = makeTerm();
    await feed(term, 'some visible output\r\n');
    await expect(waitFor(term, { text: 'never-appears' }, 200)).rejects.toThrow(
      /waitFor 超时[\s\S]*some visible output[\s\S]*some visible output/,
    );
  });

  it('raw 留档只保留最近 500 字节', async () => {
    const term = makeTerm();
    await feed(term, 'X'.repeat(2000));
    try {
      await waitFor(term, { text: 'nope' }, 150);
      expect.unreachable('应当超时');
    } catch (e) {
      const msg = (e as Error).message;
      const rawSection = msg.split('最近 raw 输入 (≤500B) ---\n')[1] ?? '';
      expect(rawSection.length).toBeLessThanOrEqual(510); // 500B + JSON 引号
    }
  });
});

describe('screenText', () => {
  it('返回去尾部空白的屏面文本', async () => {
    const term = makeTerm();
    await feed(term, 'line1\r\nline2\r\n');
    expect(screenText(term)).toBe('line1\nline2');
  });
});
