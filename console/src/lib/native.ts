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
