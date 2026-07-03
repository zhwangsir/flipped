/** Console ↔ orchestration-api HTTP + WebSocket 客户端。 */
import type { Session, ApiEvent, Metrics, McpServer, ProjectContext, FileNode, BrowserRender, GitDiffFile } from './types';

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://127.0.0.1:8001';
const API_PREFIX = '/api/v1';

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${API_PREFIX}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export function fetchSessions(): Promise<Session[]> {
  return api<Session[]>('/sessions');
}

export function createSession(title: string, mode = 'agent'): Promise<Session> {
  return api<Session>(
    `/sessions?title=${encodeURIComponent(title)}&mode=${encodeURIComponent(mode)}`,
    { method: 'POST' }
  );
}

export function createTask(
  sessionId: string,
  description: string,
  model?: string,
  mode?: string
): Promise<void> {
  const context: Record<string, string> = {};
  if (model) context.model = model;
  if (mode) context.mode = mode;
  return api(`/sessions/${sessionId}/tasks`, {
    method: 'POST',
    body: JSON.stringify({ description, context }),
  });
}

export function deleteSession(sessionId: string): Promise<{ ok: boolean }> {
  return api(`/sessions/${sessionId}`, { method: 'DELETE' });
}

export function cancelTask(sessionId: string): Promise<Session> {
  return api<Session>(`/sessions/${sessionId}/cancel`, { method: 'POST' });
}

export function fetchMetrics(): Promise<Metrics> {
  return api<Metrics>('/metrics');
}

export function getMcpServers(): Promise<McpServer[]> {
  return api<McpServer[]>('/mcp/servers');
}

export function fetchProjectContext(): Promise<ProjectContext> {
  return api<ProjectContext>('/project/context');
}

export function fetchProjectFiles(): Promise<{ root: string; tree: FileNode[] }> {
  return api<{ root: string; tree: FileNode[] }>('/project/files');
}

export function fetchProjectFile(path: string): Promise<{ path: string; content: string }> {
  return api<{ path: string; content: string }>(`/project/file?path=${encodeURIComponent(path)}`);
}

export function renderBrowser(url: string): Promise<BrowserRender> {
  return api<BrowserRender>('/browser/render', {
    method: 'POST',
    body: JSON.stringify({ url }),
  });
}

export function fetchProjectDiff(): Promise<{ files: GitDiffFile[] }> {
  return api<{ files: GitDiffFile[] }>('/project/diff');
}

export function toggleMcpServer(name: string, enabled: boolean): Promise<{ name: string; enabled: boolean }> {
  return api(`/mcp/servers/${encodeURIComponent(name)}/toggle?enabled=${enabled}`, { method: 'POST' });
}

export interface EventHandlers {
  onMessage: (event: ApiEvent) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
}

export function connectEvents(
  sessionId: string,
  handlers: EventHandlers
): { close: () => void; send: (msg: unknown) => void } {
  const wsUrl = `${API_BASE.replace(/^http/, 'ws')}${API_PREFIX}/sessions/${sessionId}/events`;
  const ws = new WebSocket(wsUrl);

  ws.onopen = () => handlers.onOpen?.();
  ws.onclose = () => handlers.onClose?.();
  ws.onerror = (e) => handlers.onError?.(e);
  ws.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data) as ApiEvent;
      handlers.onMessage(data);
    } catch {
      // 忽略无法解析的消息
    }
  };

  return {
    close: () => {
      try {
        ws.close();
      } catch {
        // ignore
      }
    },
    send: (msg) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(msg));
      }
    },
  };
}
