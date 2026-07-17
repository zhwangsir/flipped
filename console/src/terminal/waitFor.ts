/**
 * M136-C — headless 终端的事件驱动等待助手（ptyctl wait_for 的 Node 移植）。
 *
 * 零轮询：所有写入必须经 feed()（其 await term.write 回调 = 解析完成时刻），
 * 随后 notify() 唤醒所有 waiter 重新判定条件；stableMs 用一次性定时器判定
 * "屏面静默 N 毫秒"，同样不轮询。
 */
import type { Terminal } from '@xterm/headless';

export interface WaitCond {
  /** 屏面文本包含该子串 */
  text?: string;
  /** 屏面文本匹配该正则 */
  regex?: RegExp;
  /** 屏面文本不再包含该子串 */
  gone?: string;
  /** 条件满足后，屏面还需保持静默 N 毫秒才算数 */
  stableMs?: number;
}

type Listener = () => void;

const listeners = new WeakMap<Terminal, Set<Listener>>();
const rawFeeds = new WeakMap<Terminal, string[]>();

/** 手动触发一次条件重判（feed 之外直接 term.write 时由调用方补一发）。 */
export function notify(term: Terminal): void {
  for (const fn of listeners.get(term) ?? []) fn();
}

/** 写入并等待解析完成，然后唤醒 waiter。raw 数据留档供超时诊断。 */
export async function feed(term: Terminal, data: string | Uint8Array): Promise<void> {
  const buf = rawFeeds.get(term) ?? [];
  buf.push(typeof data === 'string' ? data : new TextDecoder().decode(data));
  rawFeeds.set(term, buf);
  await new Promise<void>((resolve) => term.write(data, resolve));
  notify(term);
}

/** 当前屏面（含 scrollback）转成纯文本，去掉行尾空白与尾部空行。 */
export function screenText(term: Terminal): string {
  const buf = term.buffer.active;
  const lines: string[] = [];
  for (let i = 0; i < buf.length; i++) {
    const line = buf.getLine(i);
    lines.push(line ? line.translateToString(true) : '');
  }
  return lines.join('\n').replace(/\s+$/g, '');
}

function describeCond(cond: WaitCond): string {
  return JSON.stringify({ ...cond, regex: cond.regex ? String(cond.regex) : undefined });
}

/**
 * 等待屏面满足条件，resolve 当前屏面文本；超时 reject 带诊断
 * （当前屏面全文 + 最近 ≤500 字节 raw 输入）。
 */
export function waitFor(term: Terminal, cond: WaitCond, timeoutMs = 5000): Promise<string> {
  if (!listeners.has(term)) listeners.set(term, new Set());
  const set = listeners.get(term)!;
  return new Promise<string>((resolve, reject) => {
    let done = false;
    let stableTimer: ReturnType<typeof setTimeout> | undefined;

    const matches = (): boolean => {
      const text = screenText(term);
      if (cond.text !== undefined && !text.includes(cond.text)) return false;
      if (cond.regex && !cond.regex.test(text)) return false;
      if (cond.gone !== undefined && text.includes(cond.gone)) return false;
      return true;
    };

    const cleanup = () => {
      clearTimeout(timeout);
      if (stableTimer) clearTimeout(stableTimer);
      set.delete(check);
    };

    const finish = () => {
      if (done) return;
      done = true;
      cleanup();
      resolve(screenText(term));
    };

    const check = () => {
      if (done || !matches()) {
        if (!done && stableTimer) {
          clearTimeout(stableTimer);
          stableTimer = undefined;
        }
        return;
      }
      if (!cond.stableMs) {
        finish();
        return;
      }
      // 静默判定：快照当前屏面，stableMs 后既未变且仍匹配 → 成交。
      // 期间任何写入都会触发 notify → check → 重新快照，等价于"变化即重置"。
      if (stableTimer) clearTimeout(stableTimer);
      const snapshot = screenText(term);
      stableTimer = setTimeout(() => {
        stableTimer = undefined;
        if (!done && screenText(term) === snapshot && matches()) finish();
      }, cond.stableMs);
    };

    const timeout = setTimeout(() => {
      if (done) return;
      done = true;
      cleanup();
      const raw = (rawFeeds.get(term) ?? []).join('').slice(-500);
      reject(
        new Error(
          `waitFor 超时 (${timeoutMs}ms)，条件=${describeCond(cond)}\n` +
          `--- 当前屏面 ---\n${screenText(term)}\n` +
          `--- 最近 raw 输入 (≤500B) ---\n${JSON.stringify(raw)}`,
        ),
      );
    }, timeoutMs);

    set.add(check);
    check(); // 条件可能早已满足
  });
}
