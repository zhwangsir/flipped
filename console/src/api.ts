/** Console ↔ orchestration-api HTTP + WebSocket 客户端。 */
import type { Session, ApiEvent, Metrics, McpServer, McpToolInfo, McpCallResult, ProjectContext, Project, FileNode, BrowserRender, GitDiffFile, AiReviewResult, ReviewHistoryEntry, ReviewHistoryDetail, CommitMessageResult, FactoryDetail, FactorySummary, FactoryRcaHistoryResponse, FailureCounterResponse, QualityTrendResponse, AssistantTurn, EditMessageResponse, ProjectMapInfo, ProjectRulesInfo, ScheduledTask, RemoteSessionInfo, BotChannelInfo, WorkerRule, WorkerRulesInfo, WorkerRuleVersion, WorkerRuleStatsData, PendingImage } from './types';

// M181.2 — RemoteModal 拼接 qr_url(相对路径)需要绝对基址,导出既有常量
export const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://127.0.0.1:8011';
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
  // M163.1 纵深防御：后端畸形响应（非数组，如 {} / null）不应让 UI 白屏。
  // api() 仅做 TS 类型断言、无运行时校验，故在此显式兜底。
  // 呼应 e2e/error-handling/malformed-response.spec.ts:67（store 应兜底）。
  return api<Session[]>('/sessions').then((data) =>
    Array.isArray(data) ? data : []
  );
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

// M177.2 — 撤销单文件变更:tracked 还原到 HEAD(action=restored),untracked 新文件删除(action=deleted)
export function revertProjectFile(path: string): Promise<{ ok: boolean; path: string; action: 'restored' | 'deleted' }> {
  return api(`/project/revert`, { method: 'POST', body: JSON.stringify({ path }) });
}

// M193.2 — 拒绝单个 hunk:把该 hunk 改动反向应用(git apply --reverse),工作区该段回 HEAD
export function revertProjectHunk(
  path: string,
  hunkIndex: number
): Promise<{ ok: boolean; path: string; hunk_index: number; action: string }> {
  return api('/project/revert-hunk', { method: 'POST', body: JSON.stringify({ path, hunk_index: hunkIndex }) });
}

// M179.2 — AI 代码评审:POST /project/review,LLM 审查当前工作区 diff → 结构化 findings(只读)
export function reviewProject(model?: string): Promise<AiReviewResult> {
  return api<AiReviewResult>('/project/review', {
    method: 'POST',
    body: JSON.stringify(model ? { model } : {}),
  });
}

// M195.3 — 模型 alias 清单:GET /models/aliases,评审模型下拉动态选项(替代硬编码)
export function listModelAliases(): Promise<{ aliases: { alias: string; model: string }[] }> {
  return api<{ aliases: { alias: string; model: string }[] }>('/models/aliases');
}

// M186.1 — 评审历史:GET /project/reviews 列表(ts desc,无 findings) / GET /project/reviews/{id} 详情
export function fetchProjectReviews(): Promise<{ reviews: ReviewHistoryEntry[] }> {
  return api<{ reviews: ReviewHistoryEntry[] }>('/project/reviews');
}

export function fetchProjectReview(id: string): Promise<ReviewHistoryDetail> {
  return api<ReviewHistoryDetail>(`/project/reviews/${encodeURIComponent(id)}`);
}

// M186.4 — AI commit message:POST /project/commit_message,LLM 根据工作区 diff 生成提交信息
export function generateCommitMessage(model?: string): Promise<CommitMessageResult> {
  return api<CommitMessageResult>('/project/commit_message', {
    method: 'POST',
    body: JSON.stringify(model ? { model } : {}),
  });
}

// M173 — 项目地图(对标 ZCode Zread;B 队契约:GET /project/map,POST /project/map/regenerate 强制重建)

export function fetchProjectMap(): Promise<{ map: ProjectMapInfo | null; needs_project: boolean }> {
  return api<{ map: ProjectMapInfo | null; needs_project: boolean }>('/project/map');
}

export function regenerateProjectMap(): Promise<{ map: ProjectMapInfo | null; needs_project: boolean }> {
  return api<{ map: ProjectMapInfo | null; needs_project: boolean }>('/project/map/regenerate', { method: 'POST' });
}

// M180 — 项目规则(对标 ZCode 规则系统;B 队契约:GET/PUT /project/rules,PUT 只写 .flipped/rules.md)

export function fetchProjectRules(): Promise<ProjectRulesInfo> {
  return api<ProjectRulesInfo>('/project/rules');
}

export function saveProjectRules(content: string): Promise<ProjectRulesInfo> {
  return api<ProjectRulesInfo>('/project/rules', { method: 'PUT', body: JSON.stringify({ content }) });
}

export function revealProject(): Promise<{ ok: boolean }> {
  return api<{ ok: boolean }>('/project/reveal', { method: 'POST' });
}

export function toggleMcpServer(name: string, enabled: boolean): Promise<{ name: string; enabled: boolean }> {
  return api(`/mcp/servers/${encodeURIComponent(name)}/toggle?enabled=${enabled}`, { method: 'POST' });
}

// M170.2 — MCP 工具列表/调用(Plugins 面板「MCP 工具调用」;长工具 202 属 2xx 不抛错)

export function getMcpTools(): Promise<{ tools: McpToolInfo[] }> {
  return api<{ tools: McpToolInfo[] }>('/mcp/tools');
}

export function callMcpTool(
  name: string,
  args: { arguments: Record<string, unknown>; session_id?: string }
): Promise<McpCallResult> {
  return api<McpCallResult>(`/mcp/tools/${encodeURIComponent(name)}/call`, {
    method: 'POST',
    body: JSON.stringify(args),
  });
}

// M95 — RCA 失败计数(后端 /rca/failure_counter 端点)

export function fetchFailureCounter(): Promise<FailureCounterResponse> {
  return api<FailureCounterResponse>('/rca/failure_counter');
}

// ---- Factory ----

export function listFactories(): Promise<FactorySummary[]> {
  return api<FactorySummary[]>('/factories');
}

export function createFactory(product_goal: string, cwd: string, max_tasks = 10): Promise<FactorySummary> {
  return api<FactorySummary>('/factories', {
    method: 'POST',
    body: JSON.stringify({ product_goal, cwd, max_tasks }),
  });
}

export function getFactoryDetail(factoryId: string): Promise<FactoryDetail> {
  return api<FactoryDetail>(`/factories/${encodeURIComponent(factoryId)}/detail`);
}

export function resumeFactory(factoryId: string): Promise<FactorySummary> {
  return api<FactorySummary>(`/factories/${encodeURIComponent(factoryId)}/resume`, { method: 'POST' });
}

export function pauseFactory(factoryId: string): Promise<FactorySummary> {
  return api<FactorySummary>(`/factories/${encodeURIComponent(factoryId)}/pause`, { method: 'POST' });
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

// ---- M151.4 · Assistant ----

export interface CreateAssistantSessionRequest {
  title?: string;
  mode?: 'auto' | 'agent' | 'chat' | 'plan';
  cwd?: string;
  model_alias?: string;
}

export function createAssistantSession(req: CreateAssistantSessionRequest = {}): Promise<Session> {
  return api<Session>('/assistant/sessions', {
    method: 'POST',
    body: JSON.stringify({
      title: req.title ?? '新对话',
      mode: req.mode ?? 'agent',
      model_alias: req.model_alias ?? 'coder',
      ...(req.cwd ? { cwd: req.cwd } : {}),
    }),
  });
}

export interface SendAssistantMessageRequest {
  text: string;
  mode?: 'auto' | 'agent' | 'chat' | 'plan';
  model?: string;
  orchestrator?: Record<string, unknown>;
  /** M192 — 图像附件(仅 chat/plan;字段名与后端契约一致,api-types.d.ts 快照重生前的本地扩展)。 */
  images?: PendingImage[] | null;
}

export interface SendAssistantMessageResponse {
  task_id: string;
  session_id: string;
}

export function sendAssistantMessage(
  sessionId: string,
  req: SendAssistantMessageRequest
): Promise<SendAssistantMessageResponse> {
  return api<SendAssistantMessageResponse>(`/assistant/sessions/${encodeURIComponent(sessionId)}/messages`, {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export function fetchAssistantHistory(sessionId: string): Promise<AssistantTurn[]> {
  return api<AssistantTurn[]>(`/assistant/sessions/${encodeURIComponent(sessionId)}/history`);
}

// M176 — /goal:目标驱动自循环(POST 建立派发;GET 查询最新 goal 状态,404 无 goal → null)

export interface StartAssistantGoalRequest {
  objective: string;
  mode?: string;
  model?: string;
  max_iterations?: number;
}

export interface StartAssistantGoalResponse {
  task_id: string;
  session_id: string;
  objective: string;
  max_iterations: number;
}

export function startAssistantGoal(
  sessionId: string,
  req: StartAssistantGoalRequest
): Promise<StartAssistantGoalResponse> {
  return api<StartAssistantGoalResponse>(`/assistant/sessions/${encodeURIComponent(sessionId)}/goal`, {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export interface AssistantGoalStatus {
  objective: string;
  status: string;
  iteration: number;
  max_iterations: number;
  gap?: string;
}

export async function fetchAssistantGoal(sessionId: string): Promise<AssistantGoalStatus | null> {
  const res = await fetch(
    `${API_BASE}${API_PREFIX}/assistant/sessions/${encodeURIComponent(sessionId)}/goal`,
    { headers: { 'Content-Type': 'application/json' } }
  );
  if (res.status === 404) return null; // 无 goal
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json() as Promise<AssistantGoalStatus>;
}

// M165.2a — scope: 'once'(默认,无 body) | 'always'(本会话同类动作不再询问)
export function approveAssistant(
  sessionId: string,
  scope?: 'once' | 'always'
): Promise<{ ok: boolean; session_id: string; decision: string }> {
  return api(`/assistant/sessions/${encodeURIComponent(sessionId)}/approve`, {
    method: 'POST',
    ...(scope ? { body: JSON.stringify({ scope }) } : {}),
  });
}

export function rejectAssistant(sessionId: string): Promise<{ ok: boolean; session_id: string; decision: string }> {
  return api(`/assistant/sessions/${encodeURIComponent(sessionId)}/reject`, { method: 'POST' });
}

// M165.1a — /compact:压缩会话上下文(404 无会话 / 409 空历史)
export function compactAssistant(sessionId: string): Promise<{ ok: boolean; session_id: string; summary: string }> {
  return api(`/assistant/sessions/${encodeURIComponent(sessionId)}/compact`, { method: 'POST' });
}

// M168.2 — /undo:撤销最近一轮 agent 文件改动(对标 opencode /undo)
// 404 无会话 / 409 运行中或无可撤销改动 / 400/501 非 git 工作区
export interface UndoAssistantResponse {
  ok: boolean;
  session_id: string;
  restored: boolean;
  deleted: string[];
}

export function undoAssistant(sessionId: string): Promise<UndoAssistantResponse> {
  return api<UndoAssistantResponse>(`/assistant/sessions/${encodeURIComponent(sessionId)}/undo`, { method: 'POST' });
}

// M174 — 编辑 user 消息并重跑:截断该事件后的历史,默认恢复文件快照(restore_files)
// 404 无会话/事件 / 409 运行中;响应 EditMessageResponse 定义在 ./types
export function editAssistantMessage(
  sessionId: string,
  eventId: string,
  text: string,
  restoreFiles = true
): Promise<EditMessageResponse> {
  return api<EditMessageResponse>(
    `/assistant/sessions/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(eventId)}/edit`,
    { method: 'POST', body: JSON.stringify({ text, restore_files: restoreFiles }) }
  );
}

// M190.1 — /edit/undo:撤销最近一次编辑重跑截断,恢复被截事件
// 404 无会话或无截断批次 / 409 运行中或截断点后已追加新事件
export interface EditUndoResponse {
  ok: boolean;
  session_id: string;
  restored: number;
}

export function undoEditTruncate(sessionId: string): Promise<EditUndoResponse> {
  return api<EditUndoResponse>(
    `/assistant/sessions/${encodeURIComponent(sessionId)}/edit/undo`,
    { method: 'POST' }
  );
}

// ---- M178.2 · 已安排任务(后台任务系统;新建函数命名 createScheduledTask 以避开既有 createTask 会话任务) ----

export function fetchTasks(): Promise<ScheduledTask[]> {
  // 与 fetchSessions 同款纵深防御：非数组响应兜底为 []
  return api<ScheduledTask[]>('/tasks').then((data) =>
    Array.isArray(data) ? data : []
  );
}

export interface CreateScheduledTaskRequest {
  title: string;
  prompt: string;
  mode?: string;
  model?: string;
  kind?: 'once' | 'interval' | 'cron'; // M187.1 — 加 cron
  run_at?: string | null;
  every_minutes?: number | null;
  cron?: string | null; // M187.1 — kind=cron 时必填,其余 kind 传 null
}

export function createScheduledTask(body: CreateScheduledTaskRequest): Promise<ScheduledTask> {
  return api<ScheduledTask>('/tasks', { method: 'POST', body: JSON.stringify(body) });
}

// M187.2 — 任务编辑:PATCH /tasks/{id},错误处理同 createScheduledTask(非 2xx 抛 HTTP status+text)
export function patchTask(id: string, body: Partial<CreateScheduledTaskRequest>): Promise<ScheduledTask> {
  return api<ScheduledTask>(`/tasks/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(body) });
}

export function deleteTask(id: string): Promise<{ ok: boolean }> {
  return api(`/tasks/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function toggleTask(id: string, enabled: boolean): Promise<ScheduledTask> {
  return api<ScheduledTask>(`/tasks/${encodeURIComponent(id)}/toggle?enabled=${enabled}`, { method: 'POST' });
}

// ---- M181.2 · 移动远程控制(扫码在手机浏览器接管会话;token 限时有效、可撤销) ----

export function createRemoteSession(sessionId?: string): Promise<RemoteSessionInfo> {
  return api<RemoteSessionInfo>('/remote/sessions', {
    method: 'POST',
    body: JSON.stringify(sessionId ? { session_id: sessionId } : {}),
  });
}

export function revokeRemoteToken(token: string): Promise<{ ok: boolean }> {
  return api(`/remote/${encodeURIComponent(token)}`, { method: 'DELETE' });
}

// ---- M182 · Bot 通道(多平台消息接入:telegram/wecom;状态 + 发测试消息) ----

export function fetchBotChannels(): Promise<BotChannelInfo[]> {
  return api<{ channels: BotChannelInfo[] }>('/bot/channels').then((data) =>
    Array.isArray(data?.channels) ? data.channels : []
  );
}

export function testBotChannel(platform: string, text: string): Promise<{ ok: boolean; error?: string }> {
  return api<{ ok: boolean; error?: string }>(`/bot/channels/${encodeURIComponent(platform)}/test`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}

// ---- M183 · Worker 规则(学习系统:CRUD + 版本史/回滚 + 自动生成 + 执行统计) ----

// M194.7 — 列表支持服务端排序/过滤:sort=priority(与注入层同序 priority desc → id asc),
// enabled=true/false 服务端过滤;无参 = D20 契约(全量插入序),保持向后兼容
export function fetchWorkerRules(params?: {
  sort?: 'insertion' | 'priority';
  enabled?: boolean;
}): Promise<WorkerRulesInfo> {
  const q = new URLSearchParams();
  if (params?.sort) q.set('sort', params.sort);
  if (params?.enabled !== undefined) q.set('enabled', String(params.enabled));
  const qs = q.toString();
  return api<WorkerRulesInfo>(`/worker/rules${qs ? `?${qs}` : ''}`);
}

export function createWorkerRule(text: string, scope = 'worker', priority?: number): Promise<WorkerRule> {
  return api<WorkerRule>('/worker/rules', {
    method: 'POST',
    body: JSON.stringify({ text, scope, ...(priority !== undefined ? { priority } : {}) }),
  });
}

export function updateWorkerRule(
  id: string,
  patch: { text?: string; priority?: number; scope?: string }
): Promise<WorkerRule> {
  return api<WorkerRule>(`/worker/rules/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
  });
}

export function deleteWorkerRule(id: string): Promise<{ ok: boolean }> {
  return api(`/worker/rules/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function toggleWorkerRule(id: string, enabled: boolean): Promise<WorkerRule> {
  return api<WorkerRule>(`/worker/rules/${encodeURIComponent(id)}/toggle`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  });
}

export function fetchWorkerRuleVersions(): Promise<WorkerRuleVersion[]> {
  return api<{ versions: WorkerRuleVersion[] }>('/worker/rules/versions').then((data) =>
    Array.isArray(data?.versions) ? data.versions : []
  );
}

export function rollbackWorkerRules(version: number): Promise<{ ok: boolean; version: number }> {
  return api<{ ok: boolean; version: number }>('/worker/rules/rollback', {
    method: 'POST',
    body: JSON.stringify({ version }),
  });
}

export function autoGenerateWorkerRules(): Promise<{ added: WorkerRule[]; candidates: number }> {
  return api<{ added: WorkerRule[]; candidates: number }>('/worker/rules/auto-generate', {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

export function fetchWorkerRuleStats(): Promise<WorkerRuleStatsData> {
  return api<WorkerRuleStatsData>('/worker/rules/stats');
}

export interface EventHandlers {
  onMessage: (event: ApiEvent) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
  /** 重连时携带 ?last_event_id= 断点续传（M146 P1） */
  getLastEventId?: () => string | null;
}

export function connectEvents(
  sessionId: string,
  handlers: EventHandlers
): { close: () => void; send: (msg: unknown) => void } {
  let ws: WebSocket | null = null;
  let closedByClient = false;
  let attempts = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const connect = () => {
    const last = handlers.getLastEventId?.();
    const qs = last ? `?last_event_id=${encodeURIComponent(last)}` : '';
    const wsUrl = `${API_BASE.replace(/^http/, 'ws')}${API_PREFIX}/sessions/${sessionId}/events${qs}`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      attempts = 0; // 连接成功即重置退避
      handlers.onOpen?.();
    };
    ws.onclose = () => {
      handlers.onClose?.();
      if (closedByClient) return;
      // 断线自动重连：指数退避 1s→2s→4s→…→上限 10s
      const delay = Math.min(1000 * 2 ** attempts, 10000);
      attempts += 1;
      timer = setTimeout(connect, delay);
    };
    ws.onerror = (e) => handlers.onError?.(e);
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data) as ApiEvent;
        handlers.onMessage(data);
      } catch {
        // 忽略无法解析的消息
      }
    };
  };

  connect();

  return {
    close: () => {
      closedByClient = true; // 主动关闭不触发重连
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      try {
        ws?.close();
      } catch {
        // ignore
      }
    },
    send: (msg) => {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(msg));
      }
    },
  };
}
