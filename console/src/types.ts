/** flipped Console 领域模型与后端事件转换。 */

export type SessionStatus = 'idle' | 'running' | 'done' | 'review' | 'error';

export type Role = 'user' | 'supervisor' | 'worker' | 'overseer' | 'verify' | 'system';

export type ToolName = 'terminal' | 'file_editor' | 'browser' | 'search';

export interface ToolChild {
  type: 'file_change' | 'terminal' | 'browser' | 'output';
  text: string;
}

export interface ToolCall {
  tool: ToolName;
  summary: string;
  detail?: string;
  status: 'ok' | 'running' | 'error';
  children?: ToolChild[];
}

export interface ApprovalInfo {
  id: string;
  action?: string;
  reason?: string;
  risk?: string;
}

export interface StreamItem {
  id: string;
  role: Role;
  model?: string;
  text?: string;
  tools?: ToolCall[];
  verdict?: { efficiency: number; direction: number; action: string; note: string };
  ok?: boolean;
}

/** 自主循环实时计划清单（F4 · 可见脊柱）。 */
export type PlanStepStatus = 'running' | 'done' | 'retry' | 'aborted';
export interface PlanStep {
  index: number;
  text: string;
  status: PlanStepStatus;
}
export interface PlanState {
  steps: PlanStep[];
  complete: boolean;
}

export interface Session {
  id: string;
  title: string;
  status: SessionStatus;
  model: string;
  mode?: string; // agent(项目) | plan(项目) | chat(对话)
  project?: string | null;       // 所属项目 host 路径
  project_name?: string | null;  // 项目名
  goal?: string | null;
  created_at: string;
  updated_at: string;
}

/** M178.2 — 已安排任务(镜像后端 ScheduledTask,snake_case 原样透传,与 Session 惯例一致)。 */
export interface ScheduledTask {
  id: string;
  title: string;
  prompt: string;
  mode: 'chat' | 'plan' | 'agent' | 'auto';
  model: string;
  kind: 'once' | 'interval';
  run_at: string | null;
  every_minutes: number | null;
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: 'done' | 'failed' | 'skipped' | null;
  last_session_id: string | null;
  run_count: number;
  created_at: string;
}

/** ContextPanel 从事件流派生的真实上下文数据（M6.1）。 */
export interface TerminalBlock {
  command: string;
  output: string;
  exit?: number;
}
export interface BrowserView {
  url: string;
  title?: string;
  screenshot?: string;
}
export interface ChangedFile {
  path: string;
  change: string;
  language?: string;
  content?: string;
}

/** /metrics 返回的性能指标（M6.3）。 */
export interface Metrics {
  llm: Record<string, number>;
  context: Record<string, number>;
}

/** M95 — RCA 事件 payload(verify 失败时后端 emit EventType.rca)。 */
export interface RcaInfo {
  cause: string;              // 根因分类(reasoning_overflow/syntax_error/...)
  confidence: number;         // 0.0-1.0
  detail: string;
  fix_suggestion: string;
  history_hint: string;       // Gold Memory 历史类似失败提示
  related_rules: string[];
  failure_counter: Record<string, number>;  // 连续失败计数
}

/** M95 — verifier_verdict 事件 payload(GLM 验证判决回调)。 */
export interface VerifierVerdict {
  severity: 'blocker' | 'warning' | 'ok';
  checked: boolean;
  issues: string[];
  suggestions: string[];
}

/** M95 — /rca/failure_counter 端点返回。 */
export interface FailureCounterResponse {
  counter: Record<string, number>;
}

/** 项目文件树节点（阶段② — 右侧「文件」）。 */
export interface FileNode {
  name: string;
  path: string;
  type: 'file' | 'dir';
  children?: FileNode[];
}

/** 工作区真实 git diff（阶段②c — 审查面板）。 */
export interface GitDiffLine {
  type: 'add' | 'del' | 'ctx' | 'hunk';
  text: string;
}
export interface GitDiffFile {
  path: string;
  added: number;
  removed: number;
  lines: GitDiffLine[];
  /** M177.2 — untracked 新文件(lines 为空数组) */
  untracked?: boolean;
  /** M177.2 — 二进制文件(不显示 diff) */
  binary?: boolean;
}

/** M179.2 — AI 代码评审(POST /project/review):LLM 审查工作区 diff 的结构化 finding。 */
export interface ReviewFinding {
  path: string;
  line?: number | null;
  severity: 'high' | 'medium' | 'low';
  message: string;
  suggestion?: string | null;
}
export interface AiReviewResult {
  findings: ReviewFinding[];
  files_reviewed: number;
  model: string;
  note?: string | null;
}

/** 浏览器真内核渲染结果（阶段②b — 选中元素追踪）。 */
export interface BrowserElement {
  tag: string;
  selector: string;
  text: string;
  box: { x: number; y: number; w: number; h: number };
}
export interface BrowserRender {
  url: string;
  title: string;
  screenshot: string;
  elements: BrowserElement[];
  viewport: { width: number; height: number };
}

/** 共享 UI 导航状态（M7.5 — 让 ActivityBar/TopBar/composer 真正驱动面板）。 */
export type ContextTab = 'editor' | 'diff' | 'term' | 'browser' | 'files' | 'problems' | 'mcp' | 'map' | 'rules' | 'bot' | 'worker';

/** M173 — GET/POST /project/map(/regenerate) 返回的项目地图(对标 ZCode Zread 可视化)。 */
export interface ProjectMapInfo {
  markdown: string;
  generated_at: string;
  stale: boolean;       // 项目已变更,地图可能过期
  from_cache: boolean;  // 缓存 | 新建
  stack: string[];      // 技术栈标签
}

/** M180 — GET/PUT /project/rules 返回的项目规则(对标 ZCode 规则系统)。 */
export interface ProjectRulesInfo {
  files: string[];        // 命中的规则文件相对路径(如 .flipped/rules.md / AGENTS.md)
  markdown: string;       // 拼接渲染好的规则文档(查看态展示)
  total_chars: number;    // 未截断前总长
  rules_content: string;  // .flipped/rules.md 原始文本(编辑态初值,不存在→"")
  needs_project: boolean; // 无活动项目时其余字段全空
}
export type SidebarTab = 'chats' | 'files';

/** /project/context 返回的项目上下文（Stage 3 — composer 上下文行 / 状态栏）。 */
export interface ProjectContext {
  project: string | null;
  path?: string | null;
  sandbox?: string | null;
  branch: string | null;
  mode: string;
}

/** ~/projects 下的一个项目(host 路径 ↔ 沙盒 /projects/<名>)。 */
export interface Project {
  name: string;
  host: string;
  sandbox: string;
}

/** /mcp/servers 返回的真实 MCP 服务器（M7.3）。 */
export interface McpServer {
  name: string;
  description: string;
  transport: string;
  enabled: boolean;
  tools: string[];
  tool_count: number;
}

/** GET /mcp/tools 返回的工具描述（M170.2）。 */
export interface McpToolInfo {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

/**
 * POST /mcp/tools/{name}/call 响应（M170.2）。
 * 快工具 → {ok:true, tool, result} | {ok:false, tool, error}
 * 长工具(202) → {ok:true, accepted:true, tool, session_id}
 * store 侧无会话拦截 → {ok:false, tool, error:'no-session'}
 */
export interface McpCallResult {
  ok: boolean;
  tool?: string;
  result?: unknown;
  error?: string;
  accepted?: boolean;
  session_id?: string;
}

/** 工厂任务状态 */
export type FactoryTaskStatus = 'pending' | 'running' | 'done' | 'failed';
export type FactoryStatus = 'pending' | 'running' | 'paused' | 'done' | 'error';

export interface FactoryTask {
  id: string;
  description: string;
  verify_cmd: string[];
  status: FactoryTaskStatus;
  attempts: number;
  feedback: string;
  depends_on: string[];
  artifacts: string[];
}

export interface TaskResult {
  task: FactoryTask;
  verified: boolean;
  stop_reason: string;
  iteration: number;
  summary: string;
}

export interface FactoryDetail {
  factory_id: string;
  product_goal: string;
  cwd: string;
  status: FactoryStatus;
  roadmap: FactoryTask[];
  completed: TaskResult[];
  failed: TaskResult[];
  current_task_id: string | null;
  context_summary: string;
  iteration_count: number;
  max_tasks: number;
  created_at: string;
  updated_at: string;
}

export interface FactorySummary {
  factory_id: string;
  product_goal: string;
  status: FactoryStatus;
  iteration_count: number;
  max_tasks: number;
  created_at: string;
  updated_at: string;
}

/** M100 — 工厂级 RCA 历史条目(对应后端 FactoryRcaEntry)。 */
export interface FactoryRcaEntry {
  cause: string;              // 根因分类(syntax_error/verify_mismatch/...)
  confidence: number;         // 0.0-1.0
  fix_suggestion: string;
  history_hint: string;
  related_rules: string[];
  task_index: number;         // 失败任务在 roadmap 中的 0-based 索引,-1 表示未知
  timestamp: string;          // ISO8601 UTC
}

/** M100 — /factories/{id}/rca_history 端点返回结构。 */
export interface FactoryRcaHistoryResponse {
  factory_id: string;
  rca_history: FactoryRcaEntry[];
  cause_stats: Record<string, number>;
}

// M135-B — 工厂质量趋势视图(前端 FactoryPanel 画迷你曲线)
export interface QualityTrendResponse {
  factory_id: string;
  trend: {
    direction: 'improving' | 'stable' | 'degrading' | 'insufficient_data' | 'unknown';
    improvement_rate?: number;
    delta?: number;
    message?: string;
    samples?: number;
    latest_overall?: number;
    latest_grade?: 'S' | 'A' | 'B' | 'C';
  };
  history: Array<{
    task_id: string;
    timestamp: string;
    score: {
      functionality: number;
      code_quality: number;
      design: number;
      maintainability: number;
      performance: number;
      grade: 'S' | 'A' | 'B' | 'C';
      overall: number;
    };
  }>;
}

/** M151.4 — AssistantTurn:后端 /api/v1/assistant/sessions/{id}/history 折叠视图。 */
export interface AssistantTool {
  tool: string;
  args?: Record<string, unknown>;
  status: 'running' | 'ok' | 'error';
  summary?: string;
  output?: string;
}
/** M175 — user 消息 @ 文件引用元数据(后端展开文件内容后透传)。 */
export interface FileRefInfo {
  token: string;      // 原始 token(含 @ 前缀)
  path: string;       // 项目相对路径
  status: string;     // "ok"|"missing"|"binary"|"outside_root"|"skipped"
  bytes: number;
  truncated: boolean;
}

/** M176 — goal 事件相位 payload(iter/achieved/exhausted/stopped 折成 role='goal' turn)。 */
export interface GoalInfo {
  phase: string;
  objective: string;
  iteration: number;
  max_iterations: number;
  prompt?: string;
  gap?: string;
  achieved?: boolean;
  reason?: string;
}

export interface AssistantTurn {
  role: 'user' | 'assistant' | 'tool' | 'approval' | 'goal';
  text?: string;
  tools: AssistantTool[];
  /** M176 — 仅 role==='goal' 有值:goal 事件相位 payload。 */
  goal?: GoalInfo | null;
  verdict?: Record<string, unknown>;
  approval?: { action?: string; reason?: string; risk?: string } & Record<string, unknown>;
  /** M169 — 单轮 token 用量(与 api-types.d.ts AssistantTurn.usage 对齐)。 */
  usage?: { prompt: number; completion: number; calls: number } | null;
  /** M174 — 后端事件 id(仅 role==='user' 有值),「编辑并重跑」定位用。 */
  event_id?: string;
  /** M175 — user turn 的 @ 文件引用列表(后端 history 透传)。 */
  refs?: FileRefInfo[] | null;
  created_at: string;
}

/** M174 — POST /assistant/sessions/{sid}/messages/{event_id}/edit 响应。 */
export interface EditMessageResponse {
  ok: boolean;
  session_id: string;
  task_id: string;
  truncated: boolean;
  restored: boolean;
  deleted: string[];
}

/** orchestration-api 发过来的原始事件（与 src/api/schemas.py 对齐）。 */
export interface ApiEvent {
  id: string;
  session_id: string;
  type: string;
  agent: Role | null;
  payload: Record<string, any>;
  parent_id?: string | null;
  created_at?: string;
}

/** 把后端事件转成 StreamItem；无法展示的事件返回 null。 */
export function eventToStreamItem(ev: ApiEvent): StreamItem | null {
  const role = ev.agent || 'system';
  const p = ev.payload;
  switch (ev.type) {
    case 'message':
      // 隐藏机械 system prompt
      if (role === 'system') return null;
      return { id: ev.id, role, text: p.text };
    case 'tool_call':
      return {
        id: ev.id,
        role,
        tools: [{ tool: p.tool as ToolName, summary: p.summary || p.tool, status: p.status || 'running' }],
      };
    case 'tool_result':
      return {
        id: ev.id,
        role,
        tools: [{ tool: p.tool as ToolName, summary: p.summary || p.tool, status: p.status || 'ok' }],
      };
    case 'terminal':
      return { id: ev.id, role, text: `$ ${p.command || ''}\n${p.output || ''}` };
    case 'file_change':
      return { id: ev.id, role, text: `文件变更: ${p.path} (${p.change || 'mod'})` };
    case 'browser':
      return { id: ev.id, role, text: `浏览器: ${p.url}${p.title ? ` (${p.title})` : ''}` };
    case 'error':
      return { id: ev.id, role: 'system', text: p.message };
    case 'approval_result': {
      const approved = ['approve', 'approved', '同意', '放行'].includes(p.decision);
      return { id: ev.id, role: 'user', text: approved ? '审批：已放行' : '审批：已否决' };
    }
    case 'status':
    case 'checkpoint':
    case 'approval_request':
    case 'plan': // 计划清单单独渲染成卡片，不进消息流
    case 'rca':              // M95 — RCA 由 FailurePanel 单独渲染
    case 'verifier_verdict': // M95 — verifier 判决由 FailurePanel 单独渲染
      return null;
    default:
      return { id: ev.id, role, text: JSON.stringify(p) };
  }
}

/** 从终端输出探测本地 dev server URL(Windsurf 式实时预览)。无则 null。 */
const SERVER_URL_RE = /https?:\/\/(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?(?:\/[^\s'"]*)?/i;
export function detectServerUrl(text: string): string | null {
  if (!text) return null;
  const m = text.match(SERVER_URL_RE);
  if (!m) return null;
  return m[0].replace('0.0.0.0', 'localhost').replace(/\/+$/, '');
}

/** 简单的相对时间，用于会话列表。 */
export function formatWhen(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const sec = Math.max(0, Math.floor((now - then) / 1000));
  if (sec < 60) return '刚刚';
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小时前`;
  const day = Math.floor(sec / 86400);
  if (day === 1) return '昨天';
  if (day < 7) return `${day} 天前`;
  if (day < 30) return `${Math.floor(day / 7)} 周前`;
  return new Date(iso).toLocaleDateString();
}

/** M181 — 移动远程控制会话信息（POST /remote/sessions 响应）。 */
export interface RemoteSessionInfo {
  token: string;
  url: string;
  qr_url: string;
  session_id: string;
  session_title: string;
  expires_at: number;
  host_note: string;
}

/** 相对未来时间(已安排任务下次运行,M178.2)。 */
export function formatFuture(iso: string): string {
  const then = new Date(iso).getTime();
  const sec = Math.floor((then - Date.now()) / 1000);
  if (sec <= 0) return '即将运行';
  if (sec < 60) return `${sec} 秒后`;
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟后`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小时后`;
  const day = Math.floor(sec / 86400);
  if (day < 7) return `${day} 天后`;
  return new Date(iso).toLocaleString();
}

/** M182 — Bot 通道状态(GET /bot/channels;snake_case 原样透传,与既有惯例一致)。 */
export interface BotChannelInfo {
  platform: string;
  enabled: boolean;
  configured: boolean;
  inbound_count: number;
  outbound_count: number;
  error_count: number;
  last_inbound_at: number | null;
  last_outbound_at: number | null;
  last_error: string;
}

/** M183 — Worker 规则(学习系统;GET/POST/PUT /worker/rules 系列端点)。 */
export interface WorkerRule {
  id: string;
  text: string;
  scope: string;
  source: string;
  enabled: boolean;
  priority: number;
  created_at: number;
}
export interface WorkerRulesInfo {
  version: number;
  rules: WorkerRule[];
}
export interface WorkerRuleVersion {
  version: number;
  ts: number;
  action: string;
  detail: string;
  rule_count: number;
}
export interface WorkerRuleStatsData {
  stats: Record<string, { applied: number; success: number; failure: number }>;
  total_runs: number;
}
