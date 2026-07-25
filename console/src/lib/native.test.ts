import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import {
  isTauri,
  pickFolder,
  createBrowserWebview,
  updateBrowserWebview,
  closeBrowserWebview,
  createTerminal,
  writeTerminal,
  resizeTerminal,
  closeTerminal,
  listenTerminalData,
} from './native';

afterEach(() => {
  vi.restoreAllMocks();
  vi.resetModules();
});

beforeEach(() => {
  delete (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
});

describe('native — 浏览器模式(非 Tauri)', () => {
  it('isTauri() 返回 false', () => {
    expect(isTauri()).toBe(false);
  });

  it('pickFolder 返回 null(不抛错)', async () => {
    const result = await pickFolder();
    expect(result).toBeNull();
  });

  it('createBrowserWebview 直接返回 undefined(无副作用)', async () => {
    await expect(createBrowserWebview('l', 'http://x', 0, 0, 100, 100)).resolves.toBeUndefined();
  });

  it('updateBrowserWebview 直接返回 undefined', async () => {
    await expect(updateBrowserWebview('l', 0, 0, 100, 100)).resolves.toBeUndefined();
  });

  it('closeBrowserWebview 直接返回 undefined', async () => {
    await expect(closeBrowserWebview('l')).resolves.toBeUndefined();
  });

  it('createTerminal 返回空字符串', async () => {
    await expect(createTerminal(80, 24)).resolves.toBe('');
  });

  it('writeTerminal 直接返回 undefined', async () => {
    await expect(writeTerminal('id', 'data')).resolves.toBeUndefined();
  });

  it('resizeTerminal 直接返回 undefined', async () => {
    await expect(resizeTerminal('id', 80, 24)).resolves.toBeUndefined();
  });

  it('closeTerminal 直接返回 undefined', async () => {
    await expect(closeTerminal('id')).resolves.toBeUndefined();
  });

  it('listenTerminalData 返回无操作 unlisten 函数', async () => {
    const cb = vi.fn();
    const unlisten = await listenTerminalData(cb);
    expect(typeof unlisten).toBe('function');
    expect(cb).not.toHaveBeenCalled();
    expect(() => unlisten()).not.toThrow();
  });
});

describe('native — Tauri 模式', () => {
  beforeEach(() => {
    (window as unknown as { __TAURI_INTERNALS__: unknown }).__TAURI_INTERNALS__ = {};
  });

  it('isTauri() 返回 true', () => {
    expect(isTauri()).toBe(true);
  });

  it('pickFolder 调用 @tauri-apps/plugin-dialog open 并返回字符串路径', async () => {
    vi.doMock('@tauri-apps/plugin-dialog', () => ({
      open: vi.fn(async () => '/home/user/proj'),
    }));
    const result = await pickFolder('选择');
    expect(result).toBe('/home/user/proj');
  });

  it('pickFolder open 返回非字符串(取消)时返回 null', async () => {
    vi.doMock('@tauri-apps/plugin-dialog', () => ({
      open: vi.fn(async () => null),
    }));
    const result = await pickFolder();
    expect(result).toBeNull();
  });

  it('pickFolder 自定义 title 透传给 open', async () => {
    const openMock = vi.fn(async () => '/x');
    vi.doMock('@tauri-apps/plugin-dialog', () => ({ open: openMock }));
    await pickFolder('我的标题');
    expect(openMock).toHaveBeenCalledWith(expect.objectContaining({ title: '我的标题', directory: true, multiple: false }));
  });

  it('createTerminal 调用 invoke("create_terminal")', async () => {
    vi.doMock('@tauri-apps/api/core', () => ({
      invoke: vi.fn(async () => 'term-id-1'),
    }));
    const id = await createTerminal(80, 24);
    expect(id).toBe('term-id-1');
  });

  it('writeTerminal 调用 invoke("write_terminal")', async () => {
    const invokeMock = vi.fn(async () => undefined);
    vi.doMock('@tauri-apps/api/core', () => ({ invoke: invokeMock }));
    await writeTerminal('id1', 'hello');
    expect(invokeMock).toHaveBeenCalledWith('write_terminal', { id: 'id1', data: 'hello' });
  });

  it('resizeTerminal 调用 invoke("resize_terminal")', async () => {
    const invokeMock = vi.fn(async () => undefined);
    vi.doMock('@tauri-apps/api/core', () => ({ invoke: invokeMock }));
    await resizeTerminal('id1', 100, 30);
    expect(invokeMock).toHaveBeenCalledWith('resize_terminal', { id: 'id1', cols: 100, rows: 30 });
  });

  it('closeTerminal 调用 invoke("close_terminal")', async () => {
    const invokeMock = vi.fn(async () => undefined);
    vi.doMock('@tauri-apps/api/core', () => ({ invoke: invokeMock }));
    await closeTerminal('id1');
    expect(invokeMock).toHaveBeenCalledWith('close_terminal', { id: 'id1' });
  });

  it('createBrowserWebview 调用 invoke("create_browser_webview")', async () => {
    const invokeMock = vi.fn(async () => undefined);
    vi.doMock('@tauri-apps/api/core', () => ({ invoke: invokeMock }));
    await createBrowserWebview('label1', 'http://x', 1, 2, 3, 4);
    expect(invokeMock).toHaveBeenCalledWith('create_browser_webview', {
      label: 'label1', url: 'http://x', x: 1, y: 2, width: 3, height: 4,
    });
  });

  it('updateBrowserWebview 调用 invoke("update_browser_webview")', async () => {
    const invokeMock = vi.fn(async () => undefined);
    vi.doMock('@tauri-apps/api/core', () => ({ invoke: invokeMock }));
    await updateBrowserWebview('label1', 5, 6, 7, 8);
    expect(invokeMock).toHaveBeenCalledWith('update_browser_webview', {
      label: 'label1', x: 5, y: 6, width: 7, height: 8,
    });
  });

  it('closeBrowserWebview 调用 invoke("close_browser_webview")', async () => {
    const invokeMock = vi.fn(async () => undefined);
    vi.doMock('@tauri-apps/api/core', () => ({ invoke: invokeMock }));
    await closeBrowserWebview('label1');
    expect(invokeMock).toHaveBeenCalledWith('close_browser_webview', { label: 'label1' });
  });

  it('listenTerminalData 注册监听并返回 unlisten', async () => {
    const unlistenMock = vi.fn();
    const listenMock = vi.fn(async () => unlistenMock);
    vi.doMock('@tauri-apps/api/event', () => ({ listen: listenMock }));
    const cb = vi.fn();
    const unlisten = await listenTerminalData(cb);
    expect(listenMock).toHaveBeenCalledWith('terminal-data', expect.any(Function));
    // 触发一次事件 payload,验证回调被转发
    const payload = { id: 't1', data: 'hello' };
    // @ts-expect-error - 取出 listen 的回调参数进行手动触发
    listenMock.mock.calls[0][1]({ payload });
    expect(cb).toHaveBeenCalledWith('t1', 'hello');
    expect(typeof unlisten).toBe('function');
    unlisten();
    expect(unlistenMock).toHaveBeenCalled();
  });
});
