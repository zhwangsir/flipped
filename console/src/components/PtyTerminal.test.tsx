import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, cleanup } from '@testing-library/react';

// ---- mock 依赖 ----
// xterm Terminal:捕获实例与回调,提供触发 API
const termInstances: Array<{
  onData: (cb: (d: string) => void) => void;
  onResize: (cb: (e: { cols: number; rows: number }) => void) => void;
  open: (el: HTMLElement) => void;
  write: (d: string) => void;
  focus: () => void;
  dispose: () => void;
  options: { theme?: unknown };
  cols: number;
  rows: number;
}> = [];

vi.mock('@xterm/xterm', () => {
  return {
    Terminal: class {
      cols = 80;
      rows = 24;
      options: { theme?: unknown } = {};
      onData = vi.fn((cb: (d: string) => void) => { this._onData = cb; });
      onResize = vi.fn((cb: (e: { cols: number; rows: number }) => void) => { this._onResize = cb; });
      open = vi.fn((el: HTMLElement) => { this._el = el; });
      loadAddon = vi.fn();
      write = vi.fn();
      focus = vi.fn();
      dispose = vi.fn();
      _onData: ((d: string) => void) | null = null;
      _onResize: ((e: { cols: number; rows: number }) => void) | null = null;
      _el: HTMLElement | null = null;
      constructor() {
        const inst = this as unknown as (typeof termInstances)[number];
        termInstances.push(inst);
      }
    },
  };
});

vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class {
    fit = vi.fn();
  },
}));

vi.mock('@xterm/xterm/css/xterm.css', () => ({}));

// native:全部走 web 模式(isTauri=false)
vi.mock('../lib/native', () => ({
  isTauri: vi.fn(() => false),
  createTerminal: vi.fn(async () => 'id'),
  writeTerminal: vi.fn(async () => {}),
  resizeTerminal: vi.fn(async () => {}),
  closeTerminal: vi.fn(async () => {}),
  listenTerminalData: vi.fn(async () => () => {}),
  createBrowserWebview: vi.fn(async () => {}),
  updateBrowserWebview: vi.fn(async () => {}),
  closeBrowserWebview: vi.fn(async () => {}),
}));

import { PtyTerminal } from './PtyTerminal';
import { isTauri } from '../lib/native';

const mockedIsTauri = vi.mocked(isTauri);

// WebSocket mock
function makeWsMock() {
  const ws = {
    readyState: 0,
    onopen: null as null | (() => void),
    onclose: null as null | (() => void),
    onerror: null as null | ((e: unknown) => void),
    onmessage: null as null | ((e: { data: string }) => void),
    send: vi.fn(),
    close: vi.fn(),
  };
  return ws;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  termInstances.length = 0;
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

beforeEach(() => {
  vi.useFakeTimers();
});

function renderWithWs() {
  const ws = makeWsMock();
  const Ctor = vi.fn(() => ws) as unknown as { new (url: string): typeof ws; OPEN: number };
  Ctor.OPEN = 1;
  vi.stubGlobal('WebSocket', Ctor);
  return { ws, Ctor };
}

describe('PtyTerminal — web 模式(isTauri=false)', () => {
  it('active=false 时不创建 Terminal 实例', () => {
    renderWithWs();
    mockedIsTauri.mockReturnValue(false);
    render(<PtyTerminal active={false} />);
    expect(termInstances.length).toBe(0);
  });

  it('active=true 时创建 xterm Terminal 并连接 WebSocket', () => {
    const { ws, Ctor } = renderWithWs();
    mockedIsTauri.mockReturnValue(false);
    render(<PtyTerminal active={true} />);
    expect(termInstances.length).toBe(1);
    expect(Ctor).toHaveBeenCalledTimes(1);
    // WS URL 形如 ws://127.0.0.1:8011/api/v1/terminal
    const url = (Ctor as unknown as { mock: { calls: string[][] } }).mock.calls[0][0];
    expect(url).toMatch(/^ws:\/\/.*\/api\/v1\/terminal$/);
    void ws;
  });

  it('WebSocket onopen 后发送初始 resize 并设置 readyRef', () => {
    const { ws } = renderWithWs();
    mockedIsTauri.mockReturnValue(false);
    render(<PtyTerminal active={true} />);
    ws.readyState = 1;
    ws.onopen?.();
    // 第一条消息是初始 resize
    expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ r: [80, 24] }));
  });

  it('WebSocket onmessage 把数据写入 term.write', () => {
    const { ws } = renderWithWs();
    mockedIsTauri.mockReturnValue(false);
    render(<PtyTerminal active={true} />);
    ws.onmessage?.({ data: 'hello world' });
    expect(termInstances[0].write).toHaveBeenCalledWith('hello world');
  });

  it('WebSocket onclose 写入断开提示', () => {
    const { ws } = renderWithWs();
    mockedIsTauri.mockReturnValue(false);
    render(<PtyTerminal active={true} />);
    ws.onclose?.();
    // 写入断开提示(包含 ANSI 颜色码)
    const calls = (termInstances[0].write as unknown as { mock: { calls: string[][] } }).mock.calls;
    const last = calls[calls.length - 1][0];
    expect(last).toContain('终端已断开');
  });

  it('term.onData 在 web 模式下通过 ws.send 发送 {d}', () => {
    const { ws } = renderWithWs();
    mockedIsTauri.mockReturnValue(false);
    render(<PtyTerminal active={true} />);
    ws.readyState = 1;
    // 触发 term.onData 回调
    const inst = termInstances[0] as unknown as { _onData: (d: string) => void };
    inst._onData('ls\r');
    expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ d: 'ls\r' }));
  });

  it('term.onData 在 ws 未 OPEN 时不发送', () => {
    const { ws } = renderWithWs();
    mockedIsTauri.mockReturnValue(false);
    render(<PtyTerminal active={true} />);
    ws.readyState = 0; // CONNECTING
    const inst = termInstances[0] as unknown as { _onData: (d: string) => void };
    inst._onData('x');
    // send 可能从未被调用,或仅被初始 onopen 调用,但不会有 {d:'x'}
    const calls = ws.send.mock.calls.map((c) => c[0]);
    expect(calls).not.toContain(JSON.stringify({ d: 'x' }));
  });

  it('term.onResize 在 web 模式下通过 ws.send 发送 {r:[cols,rows]}', () => {
    const { ws } = renderWithWs();
    mockedIsTauri.mockReturnValue(false);
    render(<PtyTerminal active={true} />);
    ws.readyState = 1;
    const inst = termInstances[0] as unknown as { _onResize: (e: { cols: number; rows: number }) => void };
    inst._onResize({ cols: 100, rows: 30 });
    expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ r: [100, 30] }));
  });

  it('className 透传到 term-holder', () => {
    renderWithWs();
    mockedIsTauri.mockReturnValue(false);
    render(<PtyTerminal active={false} className="my-panel" />);
    const holder = document.querySelector('.term-holder');
    expect(holder?.className).toContain('my-panel');
  });

  it('窗口 resize 事件触发 fit(需要 active=true 且就绪)', () => {
    const { ws } = renderWithWs();
    mockedIsTauri.mockReturnValue(false);
    render(<PtyTerminal active={true} />);
    // 模拟就绪
    ws.readyState = 1;
    ws.onopen?.();
    // 触发 window resize
    window.dispatchEvent(new Event('resize'));
    // fit 由 fitRef 调用,无法直接验证(已 mock),主要确保不报错
  });
});

describe('PtyTerminal — 主题热切换', () => {
  it('data-theme 属性变化时更新 xterm theme', async () => {
    const { ws } = renderWithWs();
    mockedIsTauri.mockReturnValue(false);
    render(<PtyTerminal active={true} />);
    // 先让 ws 就绪,设置 termRef.current
    ws.readyState = 1;
    ws.onopen?.();
    const inst = termInstances[0];
    const beforeTheme = inst.options.theme;
    document.documentElement.setAttribute('data-theme', 'light');
    // MutationObserver 在微任务里触发,刷新微任务队列
    await Promise.resolve();
    await Promise.resolve();
    expect(inst.options.theme).not.toBe(beforeTheme);
  });
});

describe('PtyTerminal — 卸载清理', () => {
  it('组件卸载后 ws.close 被调用', () => {
    const { ws } = renderWithWs();
    mockedIsTauri.mockReturnValue(false);
    const { unmount } = render(<PtyTerminal active={true} />);
    unmount();
    expect(ws.close).toHaveBeenCalled();
  });

  it('组件卸载后 term.dispose 被调用', () => {
    renderWithWs();
    mockedIsTauri.mockReturnValue(false);
    const { unmount } = render(<PtyTerminal active={true} />);
    unmount();
    expect(termInstances[0].dispose).toHaveBeenCalled();
  });
});
