/** Console ↔ orchestration-api HTTP + WebSocket 客户端。 */
import type { Session, ApiEvent, Metrics, McpServer, ProjectContext, Project, FileNode, BrowserRender, GitDiffFile, FactoryDetail, FactorySummary, FactoryRcaHistoryResponse, FailureCounterResponse, QualityTrendResponse } from './types';

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://127.0.0.1:8011';
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

export function openProject(path: string): Promise<Project> {
  return api<Project>('/project/open', {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
}

export function fetchProjects(): Promise<{ projects_dir: string; projects: Project[]; active: Project | null }> {
  return api<{ projects_dir: string; projects: Project[]; active: Project | null }>('/projects');
}

export function createProject(name: string): Promise<Project> {
  return api<Project>('/projects', { method: 'POST', body: JSON.stringify({ name }) });
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

export function revealProject(): Promise<{ ok: boolean }> {
  return api<{ ok: boolean }>('/project/reveal', { method: 'POST' });
}

export function toggleMcpServer(name: string, enabled: boolean): Promise<{ name: string; enabled: boolean }> {
  return api(`/mcp/servers/${encodeURIComponent(name)}/toggle?enabled=${enabled}`, { method: 'POST' });
}

// M95 — RCA 失败计数(后端 /rca/failure_counter 端点)

export function fetchFailureCounter(): Promise<FailureCounterResponse> {
  return api<FailureCounterResponse>('/rca/failure_counter');
}

// ---- Factory ----

export function listFactories(): Promise<FactorySummary[]> {
  return api<FactorySummary[]>('/factories');
}

export function createFactory(product_goal: string, cwd: string, max_tasks = 10): Promise<FactoryDetail> {
  return api<FactoryDetail>('/factories', {
    method: 'POST',
    body: JSON.stringify({ product_goal, cwd, max_tasks }),
  });
}

export function getFactoryDetail(factoryId: string): Promise<FactoryDetail> {
  return api<FactoryDetail>(`/factories/${encodeURIComponent(factoryId)}/detail`);
}

export function resumeFactory(factoryId: string): Promise<FactoryDetail> {
  return api<FactoryDetail>(`/factories/${encodeURIComponent(factoryId)}/resume`, { method: 'POST' });
}

export function pauseFactory(factoryId: string): Promise<FactoryDetail> {
  return api<FactoryDetail>(`/factories/${encodeURIComponent(factoryId)}/pause`, { method: 'POST' });
}

// M100 — 工厂级 RCA 历史聚合视图
export function fetchFactoryRcaHistory(factoryId: string): Promise<FactoryRcaHistoryResponse> {
  return api<FactoryRcaHistoryResponse>(`/factories/${encodeURIComponent(factoryId)}/rca_history`);
}

// M135-B — 工厂质量趋势视图(前端 FactoryPanel 画迷你曲线)
// 类型定义在 ./types 的 QualityTrendResponse
export function fetchFactoryQualityTrend(factoryId: string): Promise<QualityTrendResponse> {
  return api<QualityTrendResponse>(`/factories/${encodeURIComponent(factoryId)}/quality-trend`);
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
