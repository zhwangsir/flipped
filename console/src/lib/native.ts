/**
 * 原生桥(Tauri 桌面壳)。浏览器里这些能力不可用,函数返回 null / false,
 * 前端据此回退到 web 行为(如粘贴路径)。
 */

export function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

/** 原生文件夹选择框(仅 Tauri)。返回选中的绝对路径,取消或非 Tauri 返回 null。 */
export async function pickFolder(title = '选择项目文件夹'): Promise<string | null> {
  if (!isTauri()) return null;
  const { open } = await import('@tauri-apps/plugin-dialog');
  const result = await open({ directory: true, multiple: false, title });
  return typeof result === 'string' ? result : null;
}


export async function createBrowserWebview(
  label: string,
  url: string,
  x: number,
  y: number,
  width: number,
  height: number,
): Promise<void> {
  if (!isTauri()) return;
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke('create_browser_webview', { label, url, x, y, width, height });
}

export async function updateBrowserWebview(
  label: string,
  x: number,
  y: number,
  width: number,
  height: number,
): Promise<void> {
  if (!isTauri()) return;
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke('update_browser_webview', { label, x, y, width, height });
}

export async function closeBrowserWebview(label: string): Promise<void> {
  if (!isTauri()) return;
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke('close_browser_webview', { label });
}

export async function createTerminal(cols: number, rows: number): Promise<string> {
  if (!isTauri()) return '';
  const { invoke } = await import('@tauri-apps/api/core');
  return await invoke('create_terminal', { cols, rows });
}

export async function writeTerminal(id: string, data: string): Promise<void> {
  if (!isTauri()) return;
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke('write_terminal', { id, data });
}

export async function resizeTerminal(id: string, cols: number, rows: number): Promise<void> {
  if (!isTauri()) return;
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke('resize_terminal', { id, cols, rows });
}

export async function closeTerminal(id: string): Promise<void> {
  if (!isTauri()) return;
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke('close_terminal', { id });
}

export async function listenTerminalData(
  callback: (id: string, data: string) => void,
): Promise<() => void> {
  if (!isTauri()) return () => {};
  const { listen } = await import('@tauri-apps/api/event');
  const unlisten = await listen<{ id: string; data: string }>('terminal-data', (event) => {
    callback(event.payload.id, event.payload.data);
  });
  return unlisten;
}
