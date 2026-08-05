import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import type {
  Session,
  StreamItem,
  ApiEvent,
  SessionStatus,
  ApprovalInfo,
  ToolChild,
  TerminalBlock,
  BrowserView,
  ChangedFile,
  PlanState,
  Metrics,
  McpServer,
  McpToolInfo,
  McpCallResult,
  ContextTab,
  SidebarTab,
  ProjectContext,
  Project,
  FileNode,
  BrowserRender,
  GitDiffFile,
  AiReviewResult,
  ReviewHistoryEntry,
  CommitMessageResult,
  FactorySummary,
  FactoryDetail,
  FactoryRcaHistoryResponse,
  QualityTrendResponse,
  RcaInfo,
  VerifierVerdict,
  AssistantTurn,
  PendingImage,
  ScheduledTask,
} from './types';
import { eventToStreamItem, detectServerUrl } from './types';
import {
  fetchSessions,
  createSession as apiCreateSession,
  createTask as apiCreateTask,
  deleteSession as apiDeleteSession,
  cancelTask as apiCancelTask,
  fetchMetrics,
  getMcpServers,
  toggleMcpServer as apiToggleMcpServer,
  getMcpTools as apiGetMcpTools,
  callMcpTool as apiCallMcpTool,
  fetchProjectContext,
  fetchProjectFiles,
  fetchProjectFile,
  fetchProjectDiff,
  revertProjectFile as apiRevertProjectFile,
  revertProjectHunk as apiRevertProjectHunk,
  reviewProject as apiReviewProject,
  fetchProjectReviews as apiFetchProjectReviews,
  fetchProjectReview as apiFetchProjectReview,
  generateCommitMessage as apiGenerateCommitMessage,
  openProject as apiOpenProject,
  fetchProjects,
  createProject as apiCreateProject,
  renderBrowser as apiRenderBrowser,
  listFactories as apiListFactories,
  createFactory as apiCreateFactory,
  getFactoryDetail as apiGetFactoryDetail,
  resumeFactory as apiResumeFactory,
  pauseFactory as apiPauseFactory,
  fetchFactoryRcaHistory as apiFetchFactoryRcaHistory,
  fetchFactoryQualityTrend as apiFetchFactoryQualityTrend,
  fetchFailureCounter,
  connectEvents,
  createAssistantSession,
  sendAssistantMessage as apiSendAssistantMessage,
  startAssistantGoal as apiStartAssistantGoal,
  fetchAssistantHistory,
  approveAssistant as apiApproveAssistant,
  rejectAssistant as apiRejectAssistant,
  compactAssistant as apiCompactAssistant,
  undoAssistant as apiUndoAssistant,
  editAssistantMessage as apiEditAssistantMessage,
  undoEditTruncate as apiUndoEditTruncate,
  type UndoAssistantResponse,
  fetchTasks as apiFetchTasks,
  createScheduledTask as apiCreateScheduledTask,
  patchTask as apiPatchTask,
  deleteTask as apiDeleteTask,
  toggleTask as apiToggleTask,
  type CreateScheduledTaskRequest,
} from './api';

export type ConnectionState = 'idle' | 'connecting' | 'connected' | 'error';

interface AppState {
  sessions: Session[];
  selectedSessionId: string | null;
  stream: StreamItem[];
  connection: ConnectionState;
  error?: string;
  sessionStatus: SessionStatus | null;
  progress: number;
  errorCount: number;
  lastError: string | null;
  approvalPending: ApprovalInfo | null;
  terminalBlocks: TerminalBlock[];
  browserView: BrowserView | null;
  changedFiles: ChangedFile[];
  plan: PlanState | null;
  detectedServerUrl: string | null;
  metrics: Metrics | null;
  mcpServers: McpServer[];
  toggleMcpServer: (name: string, enabled: boolean) => Promise<void>;
  refreshMcpServers: () => void;
  // M170.2 — MCP 工具列表 + 调用(Plugins 面板)
  mcpTools: McpToolInfo[];
  refreshMcpTools: () => Promise<void>;
  callMcpTool: (name: string, args: Record<string, unknown>) => Promise<McpCallResult>;
  selectedModel: string;
  setModel: (m: string) => void;
  selectedMode: string;
  setMode: (m: string) => void;
  activeView: string;
  setActiveView: (v: string) => void;
  contextTab: ContextTab;
  setContextTab: (t: ContextTab) => void;
  sidebarTab: SidebarTab;
  setSidebarTab: (t: SidebarTab) => void;
  showContext: boolean;
  toggleContext: () => void;
  openContext: (t: ContextTab) => void;
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  paletteOpen: boolean;
  setPaletteOpen: (open: boolean) => void;
  settingsOpen: boolean;
  setSettingsOpen: (open: boolean) => void;
  pluginsOpen: boolean;
  setPluginsOpen: (open: boolean) => void;
  terminalOpen: boolean;
  toggleTerminal: () => void;
  composerPrefill: string;
  prefillComposer: (text: string) => void;
  projectContext: ProjectContext | null;
  projects: Project[];
  refreshProjects: () => Promise<void>;
  openProject: (path: string) => Promise<Project>;
  createProject: (name: string) => Promise<Project>;
  projectFiles: FileNode[];
  openedFile: { path: string; content: string; line?: number } | null;
  // M186.2 — line 为 findings 跳转目标行(打开后高亮+滚动居中);不传 = 纯打开
  openFile: (path: string, line?: number) => Promise<void>;
  closeFile: () => void;
  browserRender: BrowserRender | null;
  browserLoading: boolean;
  browserError: string | null;
  renderBrowser: (url: string) => Promise<void>;
  gitDiff: GitDiffFile[];
  gitDiffLoading: boolean;
  loadGitDiff: () => Promise<void>;
  revertGitDiffFile: (path: string) => Promise<{ ok: boolean; path: string; action: 'restored' | 'deleted' }>;
  // M193.2 — 拒绝单个 hunk(反向应用该段改动);错误原样上抛由视图兜底
  revertGitDiffHunk: (path: string, hunkIndex: number) => Promise<{ ok: boolean; path: string; hunk_index: number; action: string }>;
  // M179.2 — AI 代码评审(Review 面板一键 LLM 审查 diff → findings 行内渲染,只读)
  // M194.4 — 可选 model 透传(评审模型选择;缺省走后端默认模型)
  aiReview: { result: AiReviewResult | null; loading: boolean; error: string | null };
  runAiReview: (model?: string) => Promise<void>;
  clearAiReview: () => void;
  // M186.1 — 评审历史(列表载入 fail-open;openReview 拉详情回放进 aiReview.result,historical 标记)
  reviewHistory: ReviewHistoryEntry[];
  reviewHistoryLoading: boolean;
  loadReviewHistory: () => Promise<void>;
  openReview: (id: string) => Promise<void>;
  // M186.4 — AI commit message(LLM 按工作区 diff 生成提交信息,只读展示+复制)
  commitMessage: { result: CommitMessageResult | null; loading: boolean; error: string | null };
  generateCommit: () => Promise<void>;
  selectSession: (id: string) => void;
  createSession: (title?: string, mode?: string) => Promise<string>;
  deleteSession: (id: string) => Promise<void>;
  cancelTask: () => Promise<void>;
  sendTask: (description: string) => Promise<void>;
  sendApproval: (decision: string, reason?: string) => void;
  refreshSessions: () => Promise<void>;
  factories: FactorySummary[];
  factoryDetail: FactoryDetail | null;
  factoryOpen: boolean;
  setFactoryOpen: (open: boolean) => void;
  refreshFactories: () => Promise<void>;
  createFactory: (productGoal: string, cwd: string, maxTasks?: number) => Promise<string>;
  selectFactory: (id: string) => void;
  resumeFactory: (id: string) => Promise<void>;
  pauseFactory: (id: string) => Promise<void>;
  // M100 — 工厂级 RCA 历史聚合
  factoryRcaHistory: FactoryRcaHistoryResponse | null;
  loadFactoryRcaHistory: (id: string) => Promise<void>;
  // M135-B — 工厂质量趋势
  factoryQualityTrend: QualityTrendResponse | null;
  loadFactoryQualityTrend: (id: string) => Promise<void>;
  // M95 — RCA / verifier 可观测状态
  rcaHistory: RcaInfo[];
  lastVerifierVerdict: VerifierVerdict | null;
  failureCounter: Record<string, number>;
  clearRca: () => void;
  // M131 — 移动端适配：抽屉式侧栏和上下文面板
  mobileSidebarOpen: boolean;
  setMobileSidebarOpen: (open: boolean) => void;
  mobilePanelOpen: boolean;
  setMobilePanelOpen: (open: boolean) => void;
  // M151.4 · Assistant 视图状态
  assistantTurns: AssistantTurn[];
  assistantBusy: boolean;
  assistantError: string | null;
  // M166.3 — assistant token 级流式(chat/plan 直聊,transient 不落盘)
  assistantStream: { text: string; active: boolean };
  // M192 — images 为图像附件(仅 chat/plan);空/undefined 时请求体与 M192 前完全一致
  sendAssistantMessage: (text: string, mode?: string, images?: PendingImage[]) => Promise<void>;
  approveAssistant: (sessionId: string, scope?: 'once' | 'always') => Promise<void>;
  rejectAssistant: (sessionId: string) => Promise<void>;
  clearAssistantTurns: () => void;
  // M165.1a — slash 命令本地反馈 turn(不走后端)
  appendAssistantLocalTurn: (text: string) => void;
  // M165.1a — /compact 压缩上下文
  compactAssistant: (sessionId: string) => Promise<void>;
  // M168.2 — /undo 撤销最近一轮 agent 文件改动(成功返回结果供视图拼摘要;失败抛错由视图兜底)
  undoAssistant: (sessionId: string) => Promise<UndoAssistantResponse>;
  // M174 — 编辑 user 消息并重跑(成功后刷新历史;失败抛错由视图兜底)
  editAssistantMessage: (sessionId: string, eventId: string, text: string) => Promise<void>;
  // M190.1 — 编辑重跑截断可恢复:编辑成功后记 lastTruncated,banner 撤销/关闭;
  // 切换会话/新发送自动清除(409 = 截断点后已追加新事件,视图提示已被覆盖)
  lastTruncated: { sessionId: string; count: number } | null;
  undoEditTruncate: (sessionId: string) => Promise<number>;
  dismissTruncated: () => void;
  // M167.4 — assistant 消息排队与停止(opencode 交互:running 中 Enter 入队,Esc/停止键中断)
  assistantQueue: string[];
  enqueueAssistantMessage: (text: string) => void;
  removeAssistantQueued: (index: number) => void;
  stopAssistantTask: () => Promise<void>;
  // M176 — Goal 模式(目标驱动自循环):goalActive 由 goal 事件相位/history 重建驱动;
  // composerBusy = assistantBusy || goalActive,供 Composer/drain 使用
  // (goal 轮间隙 status done→running 闪烁,单看 assistantBusy 会让 drain 误发)
  goalActive: boolean;
  composerBusy: boolean;
  sendAssistantGoal: (objective: string) => Promise<void>;
  // M178.2 — 已安排任务(后台任务系统;动作失败原样上抛由视图兜底,同 revertGitDiffFile)
  tasks: ScheduledTask[];
  loadTasks: () => Promise<void>;
  addTask: (body: CreateScheduledTaskRequest) => Promise<void>;
  removeTask: (id: string) => Promise<void>;
  toggleTaskEnabled: (id: string, enabled: boolean) => Promise<void>;
  // M187.2 — 任务编辑(成功后回拉列表;失败原样上抛由视图兜底,同 addTask 惯例)
  editTask: (id: string, body: Partial<CreateScheduledTaskRequest>) => Promise<void>;
}

const AppContext = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [stream, setStream] = useState<StreamItem[]>([]);
  const [connection, setConnection] = useState<ConnectionState>('idle');
  const [error, setError] = useState<string | undefined>();
  const [sessionStatus, setSessionStatus] = useState<SessionStatus | null>(null);
  const [progress, setProgress] = useState(0);
  const [errorCount, setErrorCount] = useState(0);
  const [lastError, setLastError] = useState<string | null>(null);
  const [approvalPending, setApprovalPending] = useState<ApprovalInfo | null>(null);
  const [terminalBlocks, setTerminalBlocks] = useState<TerminalBlock[]>([]);
  const [browserView, setBrowserView] = useState<BrowserView | null>(null);
  const [changedFiles, setChangedFiles] = useState<ChangedFile[]>([]);
  const [plan, setPlan] = useState<PlanState | null>(null);
  const [detectedServerUrl, setDetectedServerUrl] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [mcpTools, setMcpTools] = useState<McpToolInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState('coder');
  const [selectedMode, setSelectedMode] = useState('agent');
  const [activeView, setActiveView] = useState('assistant');
  const [contextTab, setContextTab] = useState<ContextTab>('files');
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>('chats');
  const [showContext, setShowContext] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [pluginsOpen, setPluginsOpen] = useState(false);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [composerPrefill, setComposerPrefill] = useState('');
  const [projectContext, setProjectContext] = useState<ProjectContext | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectFiles, setProjectFiles] = useState<FileNode[]>([]);
  const [openedFile, setOpenedFile] = useState<{ path: string; content: string; line?: number } | null>(null);
  const [browserRender, setBrowserRender] = useState<BrowserRender | null>(null);
  const [browserLoading, setBrowserLoading] = useState(false);
  const [browserError, setBrowserError] = useState<string | null>(null);
  const [gitDiff, setGitDiff] = useState<GitDiffFile[]>([]);
  const [gitDiffLoading, setGitDiffLoading] = useState(false);
  // M179.2 — AI 评审结果态(一次性请求-响应,不落盘)
  const [aiReview, setAiReview] = useState<{ result: AiReviewResult | null; loading: boolean; error: string | null }>({
    result: null,
    loading: false,
    error: null,
  });
  // M186.1 — 评审历史列表(审查面板「历史」下拉展开时拉取,fail-open)
  const [reviewHistory, setReviewHistory] = useState<ReviewHistoryEntry[]>([]);
  const [reviewHistoryLoading, setReviewHistoryLoading] = useState(false);
  // M186.4 — AI commit message 结果态(一次性请求-响应,与 aiReview 同款)
  const [commitMessage, setCommitMessage] = useState<{
    result: CommitMessageResult | null;
    loading: boolean;
    error: string | null;
  }>({ result: null, loading: false, error: null });
  const [factories, setFactories] = useState<FactorySummary[]>([]);
  const [factoryDetail, setFactoryDetail] = useState<FactoryDetail | null>(null);
  const [factoryOpen, setFactoryOpen] = useState(false);
  // M100 — 工厂级 RCA 历史聚合(选中工厂时拉取,切换工厂时清空)
  const [factoryRcaHistory, setFactoryRcaHistory] = useState<FactoryRcaHistoryResponse | null>(null);
  // M135-B — 工厂质量趋势(选中工厂时拉取,切换工厂时清空)
  const [factoryQualityTrend, setFactoryQualityTrend] = useState<QualityTrendResponse | null>(null);
  // M95 — RCA / verifier 可观测状态
  const [rcaHistory, setRcaHistory] = useState<RcaInfo[]>([]);
  const [lastVerifierVerdict, setLastVerifierVerdict] = useState<VerifierVerdict | null>(null);
  const [failureCounter, setFailureCounter] = useState<Record<string, number>>({});
  // M131 — 移动端适配
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [mobilePanelOpen, setMobilePanelOpen] = useState(false);
  // M151.4 · Assistant 视图状态
  const [assistantTurns, setAssistantTurns] = useState<AssistantTurn[]>([]);
  const [assistantBusy, setAssistantBusy] = useState(false);
  // M190.1 — 最近一次编辑重跑的截断记录(banner 撤销入口)
  const [lastTruncated, setLastTruncated] = useState<{ sessionId: string; count: number } | null>(null);
  const [assistantError, setAssistantError] = useState<string | null>(null);
  // M166.3 — assistant token 级流式累积态(done token / worker message / 会话切换时收敛)
  const [assistantStream, setAssistantStream] = useState<{ text: string; active: boolean }>({ text: '', active: false });
  // M167.4 — assistant 排队消息(ref 为 drain 循环的实时源,state 驱动 UI)
  const [assistantQueue, setAssistantQueueState] = useState<string[]>([]);
  const assistantQueueRef = useRef<string[]>([]);
  const setAssistantQueue = useCallback((q: string[]) => {
    assistantQueueRef.current = q;
    setAssistantQueueState(q);
  }, []);
  // M167.4 — drain 防重入锁
  const assistantDrainingRef = useRef(false);
  // M176 — goal 运行中标记(goal 事件相位 set/iter/judge→true;achieved/exhausted/stopped→false)
  const [goalActive, setGoalActive] = useState(false);
  // M178.2 — 已安排任务列表(仅「已安排」视图拉取/轮询,不随 Provider 挂载拉)
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  // M176 — 合成 busy:goal 轮间隙 status done→running 闪烁,单看 assistantBusy 会让
  // drain 误发/Composer 误以为空闲;composerBusy 供 drain effect 与 Composer busy prop 使用
  const composerBusy = assistantBusy || goalActive;
  const clearRca = useCallback(() => {
    setRcaHistory([]);
    setLastVerifierVerdict(null);
    setFailureCounter({});
  }, []);
  const toggleTerminal = useCallback(() => setTerminalOpen((v) => !v), []);
  const prefillComposer = useCallback((text: string) => setComposerPrefill(text), []);
  const wsRef = useRef<{ close: () => void; send: (msg: unknown) => void } | null>(null);
  const lastEventIdRef = useRef<string | null>(null);
  // M165.3 — 助手历史防抖刷新定时器(事件驱动,替代 2.5s 轮询)
  const assistantRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const toggleContext = useCallback(() => setShowContext((v) => !v), []);
  const openContext = useCallback((t: ContextTab) => {
    setContextTab(t);
    setShowContext(true);
  }, []);
  const toggleSidebar = useCallback(() => setSidebarCollapsed((v) => !v), []);

  const refreshSessions = useCallback(async () => {
    try {
      const list = await fetchSessions();
      // M163.1 防御：fetchSessions 已做 Array.isArray 兜底，此处二次守卫
      // 确保任何调用路径（含未来直接 setSessions 的改动）都不会让 Sidebar 的
      // sessions.filter 崩溃。呼应 e2e/error-handling/malformed-response.spec.ts:67。
      setSessions(Array.isArray(list) ? list : []);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  // F9 — 轮询会话列表:让所有并行线程(非仅选中会话)的状态实时鲜活
  useEffect(() => {
    refreshSessions();
    const id = setInterval(refreshSessions, 3000);
    return () => clearInterval(id);
  }, [refreshSessions]);

  // M6.3 — 轮询性能指标
  useEffect(() => {
    let alive = true;
    const tick = () =>
      fetchMetrics()
        .then((m) => alive && setMetrics(m))
        .catch(() => {});
    tick();
    const id = setInterval(tick, 4000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // M7.3 — 拉取真实 MCP 服务器列表(Plugins 页「刷新」按钮复用)
  const refreshMcpServers = useCallback(() => {
    getMcpServers()
      .then(setMcpServers)
      .catch(() => {});
  }, []);
  useEffect(() => {
    refreshMcpServers();
  }, [refreshMcpServers]);

  // M9 — 选中工厂时轮询详情
  useEffect(() => {
    if (!factoryDetail) return;
    const fid = factoryDetail.factory_id;
    // 只在 running 时轮询
    if (factoryDetail.status !== 'running') return;
    const id = setInterval(() => {
      apiGetFactoryDetail(fid)
        .then(setFactoryDetail)
        .catch(() => {});
    }, 3000);
    return () => clearInterval(id);
  }, [factoryDetail?.factory_id, factoryDetail?.status]);

  // Stage 3 — 项目上下文(项目名/真实 git 分支)。轮询保鲜:后端活动项目可能被
  // 其它入口(另一窗口/Tauri/API)切换,UI 冒烟实测一次性 fetch 会显示滞后。
  useEffect(() => {
    const tick = () =>
      fetchProjectContext()
        .then(setProjectContext)
        .catch(() => {});
    tick();
    const id = setInterval(tick, 5000);
    return () => clearInterval(id);
  }, []);

  // 阶段② — 拉取项目文件树（右侧「文件」）
  useEffect(() => {
    fetchProjectFiles()
      .then((r) => setProjectFiles(r.tree))
      .catch(() => {});
  }, []);

  // 项目导入 — 挂载时拉 ~/projects 项目列表
  useEffect(() => {
    fetchProjects()
      .then((r) => setProjects(r.projects))
      .catch(() => {});
  }, []);

  const refreshProjects = useCallback(async () => {
    try {
      const r = await fetchProjects();
      setProjects(r.projects);
    } catch {
      setProjects([]);
    }
  }, []);

  // 切换活动项目后刷新上下文/文件树/diff/项目列表(项目 = ~/projects/<名>,与工具本体分离)
  const refreshAfterSwitch = useCallback(async () => {
    setOpenedFile(null);
    await Promise.all([
      fetchProjectContext().then(setProjectContext).catch(() => {}),
      fetchProjectFiles().then((f) => setProjectFiles(f.tree)).catch(() => setProjectFiles([])),
      fetchProjectDiff().then((d) => setGitDiff(d.files)).catch(() => setGitDiff([])),
      refreshProjects(),
    ]);
  }, [refreshProjects]);

  // 选择/导入文件夹作为活动项目(外部文件夹后端会拷进 ~/projects)
  const openProject = useCallback(async (path: string) => {
    const r = await apiOpenProject(path);
    await refreshAfterSwitch();
    return r;
  }, [refreshAfterSwitch]);

  // 在 ~/projects 下新建空白项目并设为活动
  const createProject = useCallback(async (name: string) => {
    const r = await apiCreateProject(name);
    await refreshAfterSwitch();
    return r;
  }, [refreshAfterSwitch]);

  // 点击文件树 → 拉真实文件内容载入编辑器
  // M186.2 — 可带目标行号(findings 跳转):写入 openedFile.line 由编辑器高亮+居中
  const openFile = useCallback(async (path: string, line?: number) => {
    try {
      const r = await fetchProjectFile(path);
      setOpenedFile({ path: r.path, content: r.content, ...(line != null ? { line } : {}) });
      setContextTab('files');
    } catch {
      /* 二进制/超大/读失败：忽略 */
    }
  }, []);
  // 关闭当前打开的文件 → 返回文件树
  const closeFile = useCallback(() => setOpenedFile(null), []);

  // 阶段②b — 用真 Chromium 渲染 URL（右侧「浏览器」实时看效果 + 选中元素追踪）
  const renderBrowser = useCallback(async (url: string) => {
    setBrowserLoading(true);
    setBrowserError(null);
    try {
      const r = await apiRenderBrowser(url);
      setBrowserRender(r);
    } catch (e) {
      setBrowserError(e instanceof Error ? e.message : String(e));
    } finally {
      setBrowserLoading(false);
    }
  }, []);

  // 阶段②c — 拉工作区真实 git diff（审查面板）
  // M179.2 — diff 刷新后旧评审 findings 失效,清空 aiReview.result(保 error 供用户看到上次失败)
  // M186.4 — 同理清空 commitMessage.result(diff 变了旧提交信息失效)
  const loadGitDiff = useCallback(async () => {
    setGitDiffLoading(true);
    setAiReview((prev) => (prev.result ? { ...prev, result: null } : prev));
    setCommitMessage((prev) => (prev.result ? { ...prev, result: null } : prev));
    try {
      const r = await fetchProjectDiff();
      setGitDiff(r.files);
    } catch {
      setGitDiff([]);
    } finally {
      setGitDiffLoading(false);
    }
  }, []);

  // M177.2 — 撤销单文件变更,成功后刷新 diff 列表;错误原样上抛(组件本地管确认态与错误)
  const revertGitDiffFile = useCallback(
    async (path: string) => {
      const r = await apiRevertProjectFile(path);
      await loadGitDiff();
      return r;
    },
    [loadGitDiff]
  );

  // M193.2 — 拒绝单个 hunk,成功后刷新 diff 列表;错误原样上抛(组件本地管确认态与错误)
  const revertGitDiffHunk = useCallback(
    async (path: string, hunkIndex: number) => {
      const r = await apiRevertProjectHunk(path, hunkIndex);
      await loadGitDiff();
      return r;
    },
    [loadGitDiff]
  );

  // M179.2 — AI 评审:loading 置位 → 调后端 → 成功写 result/失败写 error,loading 必复位(只读)
  // M194.4 — model 可选透传(评审模型选择;undefined = 后端默认模型)
  const runAiReview = useCallback(async (model?: string) => {
    setAiReview({ result: null, loading: true, error: null });
    try {
      const r = await apiReviewProject(model);
      setAiReview({ result: r, loading: false, error: null });
    } catch (e) {
      setAiReview({ result: null, loading: false, error: e instanceof Error ? e.message : String(e) });
    }
  }, []);

  const clearAiReview = useCallback(() => {
    setAiReview({ result: null, loading: false, error: null });
  }, []);

  // M186.1 — 载入评审历史列表(fail-open:失败保持原列表,loading 必复位)
  const loadReviewHistory = useCallback(async () => {
    setReviewHistoryLoading(true);
    try {
      const r = await apiFetchProjectReviews();
      setReviewHistory(Array.isArray(r.reviews) ? r.reviews : []);
    } catch {
      /* fail-open:保持原列表 */
    } finally {
      setReviewHistoryLoading(false);
    }
  }, []);

  // M186.1 — 回放历史评审:拉详情填入 aiReview.result(historical 标记,前端字段);
  // 失败静默(aiReview 保持原状,与 openFile 同款)
  const openReview = useCallback(async (id: string) => {
    try {
      const d = await apiFetchProjectReview(id);
      setAiReview({
        result: {
          findings: d.findings,
          files_reviewed: d.files_reviewed,
          model: d.model,
          note: null,
          review_id: d.id,
          historical: true,
        },
        loading: false,
        error: null,
      });
    } catch {
      /* 失败静默:aiReview 保持原状 */
    }
  }, []);

  // M186.4 — AI commit message:loading 置位 → 调后端 → 成功写 result/失败写 error,loading 必复位
  const generateCommit = useCallback(async () => {
    setCommitMessage({ result: null, loading: true, error: null });
    try {
      const r = await apiGenerateCommitMessage();
      setCommitMessage({ result: r, loading: false, error: null });
    } catch (e) {
      setCommitMessage({ result: null, loading: false, error: e instanceof Error ? e.message : String(e) });
    }
  }, []);

  const toggleMcpServer = useCallback(async (name: string, enabled: boolean) => {
    // 乐观更新，失败回滚
    setMcpServers((prev) => prev.map((s) => (s.name === name ? { ...s, enabled } : s)));
    try {
      await apiToggleMcpServer(name, enabled);
    } catch {
      setMcpServers((prev) => prev.map((s) => (s.name === name ? { ...s, enabled: !enabled } : s)));
    }
  }, []);

  // M170.2 — 拉取 MCP 工具列表(Plugins 面板打开时触发,fail-open)
  const refreshMcpTools = useCallback(async () => {
    try {
      const r = await apiGetMcpTools();
      setMcpTools(Array.isArray(r.tools) ? r.tools : []);
    } catch {
      /* fail-open:保持原列表 */
    }
  }, []);

  // M170.2 — 调用 MCP 工具:长工具(后台异步跑)自动带当前会话 id,
  // 无会话时不发请求直接返回 no-session;网络/HTTP 异常归一为 ok:false 供组件渲染。
  const callMcpTool = useCallback(
    async (name: string, args: Record<string, unknown>): Promise<McpCallResult> => {
      const longTool = name === 'run_coding_task' || name === 'research_and_code';
      if (longTool && !selectedSessionId) {
        return { ok: false, tool: name, error: 'no-session' };
      }
      try {
        return await apiCallMcpTool(name, {
          arguments: args,
          ...(longTool && selectedSessionId ? { session_id: selectedSessionId } : {}),
        });
      } catch (e) {
        return { ok: false, tool: name, error: e instanceof Error ? e.message : String(e) };
      }
    },
    [selectedSessionId]
  );

  const selectSession = useCallback((id: string) => {
    setSelectedSessionId(id);
    // 会话绑定项目 → 选中会话时把活动项目切到它的项目(文件树/审查/终端/agent 都跟着走)
    const s = sessions.find((x) => x.id === id);
    if (s?.project && s.project !== projectContext?.path) {
      openProject(s.project).catch(() => {});
    }
  }, [sessions, projectContext, openProject]);

  const createSession = useCallback(async (title = '新任务', mode = selectedMode) => {
    const s = await apiCreateSession(title, mode);
    setSessions((prev) => [s, ...prev]);
    setSelectedSessionId(s.id);
    return s.id;
  }, [selectedMode]);

  const deleteSession = useCallback(async (id: string) => {
    await apiDeleteSession(id);
    setSessions((prev) => prev.filter((s) => s.id !== id));
    setSelectedSessionId((prev) => (prev === id ? null : prev));
  }, []);

  const cancelTask = useCallback(async () => {
    if (selectedSessionId) await apiCancelTask(selectedSessionId);
  }, [selectedSessionId]);

  const setModel = useCallback((m: string) => setSelectedModel(m), []);
  const setMode = useCallback((m: string) => setSelectedMode(m), []);

  // Stage 3/4 — Codex 快捷键：⌘B 折叠侧栏 / ⌘K 命令面板 / ⌘J 终端 / ⌘, 设置
  // E2E 补齐(此前宣传未绑定)：⌘N 新对话 / ⌘P 搜索文件 / ⌘T 浏览器 / ⌃⇧G 审查 / ⌘1-9 切换会话
  // 注：必须放在 createSession/selectSession 声明之后(deps 引用，避免 TDZ)。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey;
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'g') {
        e.preventDefault();
        openContext('diff');
      } else if (meta && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        setSidebarCollapsed((v) => !v);
      } else if (meta && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      } else if (meta && e.key.toLowerCase() === 'j') {
        e.preventDefault();
        setTerminalOpen((v) => !v);
      } else if (meta && e.key === ',') {
        // 命令面板/设置页宣传的 ⌘, —— 此前漏绑，E2E 发现后补齐
        e.preventDefault();
        setSettingsOpen((v) => !v);
      } else if (meta && e.key.toLowerCase() === 'n') {
        e.preventDefault();
        createSession('新对话');
      } else if (meta && e.key.toLowerCase() === 'p') {
        e.preventDefault();
        openContext('files');
      } else if (meta && e.key.toLowerCase() === 't') {
        e.preventDefault();
        openContext('browser');
      } else if (meta && /^[1-9]$/.test(e.key)) {
        e.preventDefault();
        const s = sessions[Number(e.key) - 1];
        if (s) selectSession(s.id);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [sessions, createSession, openContext, selectSession]);

  const sendTask = useCallback(
    async (description: string) => {
      let sid = selectedSessionId;
      if (!sid) {
        sid = await createSession();
      }
      await apiCreateTask(sid, description, selectedModel, selectedMode);
    },
    [selectedSessionId, createSession, selectedModel, selectedMode]
  );

  const sendApproval = useCallback((decision: string, reason = '') => {
    wsRef.current?.send({ type: 'approval_result', decision, reason });
  }, []);

  // M151.4 · Assistant 视图:对话式代码助手后端(http + 历史折叠)
  // 不复用 sendTask,因为后端有专门的 /assistant/sessions/{id}/messages 端点
  // (折叠成 user/assistant/tool/approval turns,适合对话流呈现)。
  const refreshAssistantHistory = useCallback(async (sid: string | null) => {
    if (!sid) {
      setAssistantTurns([]);
      setGoalActive(false);
      return;
    }
    try {
      const turns = await fetchAssistantHistory(sid);
      setAssistantTurns(turns);
      // M176 — 扫 goal turns 重建 goalActive(取最后一条 goal turn 的相位):
      // iter→true(运行中);achieved/exhausted/stopped→false(终态)。set/judge 不折 turn。
      let active = false;
      for (const t of turns) {
        if (t.role === 'goal' && t.goal) {
          active = t.goal.phase === 'iter';
        }
      }
      setGoalActive(active);
    } catch {
      // fail-open:历史拉取失败保持原状,不阻塞发消息
    }
  }, []);

  const sendAssistantMessageAction = useCallback(
    async (text: string, mode?: string, images?: PendingImage[]) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      let sid = selectedSessionId;
      setAssistantBusy(true);
      setAssistantError(null);
      try {
        if (!sid) {
          const s = await createAssistantSession({ mode: (mode as 'auto' | 'agent' | 'chat' | 'plan') || 'agent' });
          sid = s.id;
          setSessions((prev) => [s, ...prev]);
          setSelectedSessionId(s.id);
        }
        await apiSendAssistantMessage(sid, {
          text: trimmed,
          ...(mode ? { mode: mode as 'auto' | 'agent' | 'chat' | 'plan' } : {}),
          // M192 — images 非空才带字段(空/undefined → 请求体与现状零变化)
          ...(images && images.length > 0 ? { images } : {}),
        });
        // M190.1 — 新发送后旧截断批次不再可恢复(undo 会 409),提前清 banner
        setLastTruncated(null);
        // 步级流:发完后立刻拉一次历史,轮询会在下面接手
        await refreshAssistantHistory(sid);
      } catch (e) {
        setAssistantError(e instanceof Error ? e.message : String(e));
        throw e;
      } finally {
        setAssistantBusy(false);
      }
    },
    [selectedSessionId, refreshAssistantHistory]
  );

  // M178.2 — 拉取已安排任务列表(失败静默,与 refreshMcpTools 同款 fail-open:保持原列表)
  const loadTasks = useCallback(async () => {
    try {
      const list = await apiFetchTasks();
      setTasks(Array.isArray(list) ? list : []);
    } catch {
      /* fail-open:保持原列表 */
    }
  }, []);

  // M178.2 — 新建/删除/启停后统一回拉列表;错误原样上抛(视图本地管错误态,不产生未捕获 rejection)
  const addTask = useCallback(
    async (body: CreateScheduledTaskRequest) => {
      await apiCreateScheduledTask(body);
      await loadTasks();
    },
    [loadTasks]
  );

  const removeTask = useCallback(
    async (id: string) => {
      await apiDeleteTask(id);
      await loadTasks();
    },
    [loadTasks]
  );

  const toggleTaskEnabled = useCallback(
    async (id: string, enabled: boolean) => {
      await apiToggleTask(id, enabled);
      await loadTasks();
    },
    [loadTasks]
  );

  // M187.2 — 编辑任务:PATCH 成功后回拉列表;错误原样上抛(视图本地管错误态)
  const editTask = useCallback(
    async (id: string, body: Partial<CreateScheduledTaskRequest>) => {
      await apiPatchTask(id, body);
      await loadTasks();
    },
    [loadTasks]
  );

  // M176 — /goal 目标驱动自循环:与 sendAssistantMessage 同款 busy 守卫/会话兜底/错误通道;
  // 之后走 WS goal 事件 + 防抖刷新推进(goalActive 由事件相位/history 重建维护)
  const sendAssistantGoalAction = useCallback(
    async (objective: string) => {
      const trimmed = objective.trim();
      if (!trimmed) return;
      let sid = selectedSessionId;
      setAssistantBusy(true);
      setAssistantError(null);
      try {
        if (!sid) {
          const s = await createAssistantSession({ mode: (selectedMode as 'auto' | 'agent' | 'chat' | 'plan') || 'agent' });
          sid = s.id;
          setSessions((prev) => [s, ...prev]);
          setSelectedSessionId(s.id);
        }
        await apiStartAssistantGoal(sid, {
          objective: trimmed,
          mode: selectedMode,
          model: selectedModel,
        });
        // 发完立刻拉一次历史(goal set/user 消息已落盘),后续轮次走 WS/防抖刷新
        await refreshAssistantHistory(sid);
      } catch (e) {
        setAssistantError(e instanceof Error ? e.message : String(e));
        throw e;
      } finally {
        setAssistantBusy(false);
      }
    },
    [selectedSessionId, selectedMode, selectedModel, refreshAssistantHistory]
  );

  const approveAssistantAction = useCallback(
    async (sessionId: string, scope?: 'once' | 'always') => {
      setAssistantBusy(true);
      try {
        await apiApproveAssistant(sessionId, scope);
        await refreshAssistantHistory(sessionId);
      } catch (e) {
        setAssistantError(e instanceof Error ? e.message : String(e));
      } finally {
        setAssistantBusy(false);
      }
    },
    [refreshAssistantHistory]
  );

  const rejectAssistantAction = useCallback(
    async (sessionId: string) => {
      setAssistantBusy(true);
      try {
        await apiRejectAssistant(sessionId);
        await refreshAssistantHistory(sessionId);
      } catch (e) {
        setAssistantError(e instanceof Error ? e.message : String(e));
      } finally {
        setAssistantBusy(false);
      }
    },
    [refreshAssistantHistory]
  );

  const clearAssistantTurns = useCallback(() => setAssistantTurns([]), []);

  // M165.1a — 本地追加一条 assistant turn(slash 命令反馈,不走后端)
  const appendAssistantLocalTurn = useCallback((text: string) => {
    setAssistantTurns((prev) => [
      ...prev,
      { role: 'assistant', text, tools: [], created_at: new Date().toISOString() },
    ]);
  }, []);

  // M165.1a — /compact:调后端压缩上下文,成功刷新历史;失败(如 409 空历史)本地提示
  const compactAssistantAction = useCallback(
    async (sessionId: string) => {
      setAssistantBusy(true);
      try {
        await apiCompactAssistant(sessionId);
        await refreshAssistantHistory(sessionId);
      } catch (e) {
        appendAssistantLocalTurn(`压缩上下文失败:${e instanceof Error ? e.message : String(e)}`);
      } finally {
        setAssistantBusy(false);
      }
    },
    [refreshAssistantHistory, appendAssistantLocalTurn]
  );

  // M168.2 — /undo:调后端撤销最近一轮改动,成功刷新对话历史 + diff 面板;
  // 结果返回给视图拼摘要 turn;错误原样上抛(视图 .catch 后追加失败 turn,不产生未捕获 rejection)
  const undoAssistantAction = useCallback(
    async (sessionId: string) => {
      setAssistantBusy(true);
      try {
        const r = await apiUndoAssistant(sessionId);
        await refreshAssistantHistory(sessionId);
        await loadGitDiff();
        return r;
      } finally {
        setAssistantBusy(false);
      }
    },
    [refreshAssistantHistory, loadGitDiff]
  );

  // M174 — 编辑 user 消息重跑:调后端截断重跑,成功刷新对话历史(同 undo 写法);
  // 错误原样上抛(视图 .catch 兜底,不产生未捕获 rejection)
  // M190.1 — 编辑成功后记录截断条数,供 banner 撤销入口
  const editAssistantMessageAction = useCallback(
    async (sessionId: string, eventId: string, text: string) => {
      setAssistantBusy(true);
      try {
        const r = await apiEditAssistantMessage(sessionId, eventId, text);
        setLastTruncated(r.truncated > 0 ? { sessionId, count: r.truncated } : null);
        await refreshAssistantHistory(sessionId);
      } finally {
        setAssistantBusy(false);
      }
    },
    [refreshAssistantHistory]
  );

  // M190.1 — 撤销最近一次编辑重跑截断:成功刷新历史 + 清除记录,返回恢复条数;
  // 失败(404 无批次 / 409 已被新事件覆盖)原样上抛由视图兜底
  const undoEditTruncateAction = useCallback(
    async (sessionId: string) => {
      setAssistantBusy(true);
      try {
        const r = await apiUndoEditTruncate(sessionId);
        setLastTruncated(null);
        await refreshAssistantHistory(sessionId);
        return r.restored;
      } finally {
        setAssistantBusy(false);
      }
    },
    [refreshAssistantHistory]
  );

  const dismissTruncated = useCallback(() => setLastTruncated(null), []);

  // 选中会话变化 → 重拉助手历史(步级流,不是 token 流)
  // M190.1 — 切换会话同时清除截断 banner 记录
  useEffect(() => {
    setLastTruncated(null);
    refreshAssistantHistory(selectedSessionId);
  }, [selectedSessionId, refreshAssistantHistory]);

  // M167.4 — 排队消息操作
  const enqueueAssistantMessage = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      setAssistantQueue([...assistantQueueRef.current, trimmed]);
    },
    [setAssistantQueue]
  );

  const removeAssistantQueued = useCallback(
    (index: number) => {
      setAssistantQueue(assistantQueueRef.current.filter((_, i) => i !== index));
    },
    [setAssistantQueue]
  );

  // M167.4 — 停止当前生成:取消后端任务 + 清空排队 + 收敛流式态
  const stopAssistantTask = useCallback(async () => {
    setAssistantQueue([]);
    setAssistantStream({ text: '', active: false });
    await cancelTask();
  }, [cancelTask, setAssistantQueue]);

  // M167.4 — 排队自动发送:busy 落下且有选中会话时逐条 drain。
  // 防重入 = assistantDrainingRef 锁 + 发送中 composerBusy=true 天然阻断 effect 重入;
  // 队列以 ref 为源,发送中新入队的消息会被同一 drain 循环拾取;
  // 单条发送失败错误已写入 assistantError,继续 drain 后续消息(消息间相互独立)。
  // M176 — drain 用 composerBusy(goal 运行中不 drain);/goal 前缀消息分发给 sendAssistantGoal。
  useEffect(() => {
    if (composerBusy || assistantQueue.length === 0 || !selectedSessionId) return;
    if (assistantDrainingRef.current) return;
    assistantDrainingRef.current = true;
    void (async () => {
      try {
        while (assistantQueueRef.current.length > 0) {
          const [head, ...rest] = assistantQueueRef.current;
          setAssistantQueue(rest);
          try {
            // M176 — /goal <目标> 前缀分发(空参退化为普通消息)
            const goalMatch = /^\/goal\s+(.+)$/.exec(head);
            if (goalMatch && goalMatch[1].trim()) {
              await sendAssistantGoalAction(goalMatch[1].trim());
            } else {
              await sendAssistantMessageAction(head);
            }
          } catch {
            /* 错误已由 action 写入 assistantError */
          }
        }
      } finally {
        assistantDrainingRef.current = false;
      }
    })();
  }, [composerBusy, assistantQueue, selectedSessionId, sendAssistantMessageAction, sendAssistantGoalAction, setAssistantQueue]);

  // M9 — 工厂循环
  const refreshFactories = useCallback(async () => {
    try {
      const list = await apiListFactories();
      setFactories(list);
    } catch {
      setFactories([]);
    }
  }, []);

  // M9 — 轮询工厂列表
  useEffect(() => {
    refreshFactories();
    const id = setInterval(refreshFactories, 5000);
    return () => clearInterval(id);
  }, [refreshFactories]);

  // M95 — 轮询 RCA 失败计数(让面板在没有 rca 事件时也能显示累计计数)
  useEffect(() => {
    const tick = () =>
      fetchFailureCounter()
        .then((r) => setFailureCounter(r.counter || {}))
        .catch(() => {});
    tick();
    const id = setInterval(tick, 5000);
    return () => clearInterval(id);
  }, []);

  const createFactory = useCallback(async (productGoal: string, cwd: string, maxTasks = 10) => {
    // 端点返回 FactorySummary（无 roadmap/completed/failed），必须回拉 detail 再入 state（M146 P0）
    const s = await apiCreateFactory(productGoal, cwd, maxTasks);
    const d = await apiGetFactoryDetail(s.factory_id);
    setFactoryDetail(d);
    setFactoryOpen(true);
    refreshFactories().catch(() => {});
    return d.factory_id;
  }, [refreshFactories]);

  const selectFactory = useCallback((id: string) => {
    // M100 — 切换工厂时清空旧的 RCA 历史(避免显示上一个工厂的统计)
    setFactoryRcaHistory(null);
    // M135-B — 切换工厂时清空旧的质量趋势
    setFactoryQualityTrend(null);
    if (!id) {
      setFactoryDetail(null);
      return;
    }
    apiGetFactoryDetail(id)
      .then(setFactoryDetail)
      .catch(() => setFactoryDetail(null));
    setFactoryOpen(true);
    // 拉取工厂级 RCA 历史聚合(fail-open,失败时保持 null)
    apiFetchFactoryRcaHistory(id)
      .then(setFactoryRcaHistory)
      .catch(() => setFactoryRcaHistory(null));
    // M135-B — 拉取工厂质量趋势(fail-open)
    apiFetchFactoryQualityTrend(id)
      .then(setFactoryQualityTrend)
      .catch(() => setFactoryQualityTrend(null));
  }, []);

  const resumeFactory = useCallback(async (id: string) => {
    // 端点返回 FactorySummary，回拉 detail（M146 P0）
    await apiResumeFactory(id);
    const d = await apiGetFactoryDetail(id);
    setFactoryDetail(d);
  }, []);

  const pauseFactory = useCallback(async (id: string) => {
    // 端点返回 FactorySummary，回拉 detail（M146 P0）
    await apiPauseFactory(id);
    const d = await apiGetFactoryDetail(id);
    setFactoryDetail(d);
  }, []);

  // M100 — 主动加载工厂级 RCA 历史聚合(供 FactoryPanel 展开折叠区时刷新)
  const loadFactoryRcaHistory = useCallback(async (id: string) => {
    try {
      const r = await apiFetchFactoryRcaHistory(id);
      setFactoryRcaHistory(r);
    } catch {
      // fail-open:加载失败保持原状态,不抛错打断 UI
    }
  }, []);

  // M135-B — 主动加载工厂质量趋势(供 FactoryPanel 展开折叠区时刷新)
  const loadFactoryQualityTrend = useCallback(async (id: string) => {
    try {
      const r = await apiFetchFactoryQualityTrend(id);
      setFactoryQualityTrend(r);
    } catch {
      // fail-open:加载失败保持原状态,不抛错打断 UI
    }
  }, []);

  useEffect(() => {
    // M167.4 — 会话切换/取消选中 → 清空排队消息(不跨会话携带;drain 循环读 ref 随即退出)
    setAssistantQueue([]);
    if (!selectedSessionId) {
      setStream([]);
      setConnection('idle');
      setSessionStatus(null);
      setProgress(0);
      setErrorCount(0);
      setLastError(null);
      setApprovalPending(null);
      setTerminalBlocks([]);
      setBrowserView(null);
      setChangedFiles([]);
      setPlan(null);
      setDetectedServerUrl(null);
      setRcaHistory([]);
      setLastVerifierVerdict(null);
      lastEventIdRef.current = null;
      return;
    }

    setConnection('connecting');
    setStream([]);
    setError(undefined);
    setSessionStatus(null);
    setProgress(0);
    setErrorCount(0);
    setLastError(null);
    setApprovalPending(null);
    setTerminalBlocks([]);
    setBrowserView(null);
    setChangedFiles([]);
    setPlan(null);
    setDetectedServerUrl(null);
    setRcaHistory([]);
    setLastVerifierVerdict(null);
    // M166.3 — 会话切换/清空选中 → 重置 token 流式态
    setAssistantStream({ text: '', active: false });
    lastEventIdRef.current = null;

    // M165.3 — 事件驱动对话推进:300ms 防抖刷新助手历史(同一窗口多事件合并一次,
    // 替代旧的 2.5s 轮询)。refreshAssistantHistory 为稳定 useCallback,闭包安全;
    // selectedSessionId 取自本 effect 作用域,依赖数组不变、不引发 WS 重连。
    const scheduleAssistantRefresh = () => {
      if (assistantRefreshTimerRef.current) clearTimeout(assistantRefreshTimerRef.current);
      assistantRefreshTimerRef.current = setTimeout(() => {
        assistantRefreshTimerRef.current = null;
        refreshAssistantHistory(selectedSessionId);
      }, 300);
    };

    const appendEvent = (ev: ApiEvent) => {
      if (ev.id) lastEventIdRef.current = ev.id;
      // M165.3 — 命中助手对话相关事件 → 调度防抖刷新(放最前,早退分支也覆盖)
      // M169.2 — 'usage' 入集合:worker 收尾的 token 用量事件也驱动末端 history 刷新
      if (
        ev.session_id === selectedSessionId &&
        (ev.type === 'message' ||
          ev.type === 'tool_call' ||
          ev.type === 'tool_result' ||
          ev.type === 'approval_request' ||
          ev.type === 'approval_result' ||
          ev.type === 'usage')
      ) {
        scheduleAssistantRefresh();
      }
      // M176 — goal 事件:相位驱动 goalActive(set/iter/judge→true;achieved/exhausted/
      // stopped→false),并调度防抖历史刷新(iter/achieved/exhausted/stopped 折成
      // role='goal' turn 渲染 marker)。不进 stream、不走 token 流。
      if (ev.type === 'goal') {
        if (ev.session_id !== selectedSessionId) return;
        const phase = ev.payload?.phase as string | undefined;
        if (phase === 'set' || phase === 'iter' || phase === 'judge') {
          setGoalActive(true);
        } else if (phase === 'achieved' || phase === 'exhausted' || phase === 'stopped') {
          setGoalActive(false);
        }
        scheduleAssistantRefresh();
        return;
      }
      // M166.3 — token 级流式(chat/plan 直聊,transient 不落盘,id 为 null/空):
      // 只累积进 assistantStream,不进 stream、不触发上面的防抖 history 刷新。
      // seq 仅作日志/兜底,WS 保序不强制校验。done token → 清除(message 随后收敛)。
      if (ev.type === 'token') {
        if (ev.session_id !== selectedSessionId) return;
        if (ev.payload?.done) {
          setAssistantStream({ text: '', active: false });
        } else {
          const chunk = typeof ev.payload?.text === 'string' ? ev.payload.text : '';
          setAssistantStream((prev) => ({ text: prev.text + chunk, active: true }));
        }
        return;
      }
      // M166.3 — worker 完整 message 到达时必须收敛流式态(双保险:
      // 正常路径后端先发 done token 再发 message,message 到达即兜底清除)
      if (ev.type === 'message' && ev.agent === 'worker') {
        setAssistantStream((prev) => (prev.active ? { text: '', active: false } : prev));
      }
      // M6.1 — 从事件流派生 ContextPanel 的真实上下文数据
      if (ev.type === 'terminal') {
        setTerminalBlocks((prev) => [
          ...prev,
          { command: ev.payload.command || '', output: ev.payload.output || '', exit: ev.payload.exit_code },
        ]);
        // F9+ — 从 agent 终端输出探测 dev server URL,供浏览器面板一键实时预览
        const found = detectServerUrl(`${ev.payload.command || ''}\n${ev.payload.output || ''}`);
        if (found) setDetectedServerUrl(found);
      } else if (ev.type === 'browser') {
        setBrowserView({ url: ev.payload.url, title: ev.payload.title, screenshot: ev.payload.screenshot });
      } else if (ev.type === 'file_change') {
        setChangedFiles((prev) => {
          const existing = prev.find((f) => f.path === ev.payload.path);
          // 只接受字符串内容(历史事件可能把状态消息数组塞进 content，会导致 .split 崩溃)
          const incoming = typeof ev.payload.content === 'string' ? ev.payload.content : undefined;
          return [
            ...prev.filter((f) => f.path !== ev.payload.path),
            {
              path: ev.payload.path,
              change: ev.payload.change || existing?.change || 'mod',
              language: ev.payload.language || existing?.language,
              // ActionEvent 携带真实文件内容；Observation 无内容时保留已有内容
              content: incoming || existing?.content,
            },
          ];
        });
      }

      if (ev.type === 'plan') {
        // F4 — 自主循环计划清单快照(最新覆盖旧)
        setPlan({
          steps: Array.isArray(ev.payload.steps) ? ev.payload.steps : [],
          complete: !!ev.payload.complete,
        });
        return;
      }

      if (ev.type === 'status') {
        const st = ev.payload.status as SessionStatus;
        const pr = (ev.payload.progress as number) ?? 0;
        setSessionStatus(st);
        setProgress(pr);
        setSessions((prev) =>
          prev.map((s) => (s.id === ev.session_id ? { ...s, status: st } : s))
        );
        return;
      }
      if (ev.type === 'error') {
        setErrorCount((c) => c + 1);
        setLastError(ev.payload.message);
      }
      if (ev.type === 'approval_request') {
        setApprovalPending({
          id: ev.id,
          action: ev.payload.action,
          reason: ev.payload.reason,
          risk: ev.payload.risk,
        });
        return;
      }
      // M95 — RCA 事件:推入 rcaHistory(保留最近 10 条)+ 同步 failureCounter
      if (ev.type === 'rca') {
        const info: RcaInfo = {
          cause: String(ev.payload.cause || 'unknown'),
          confidence: Number(ev.payload.confidence || 0),
          detail: String(ev.payload.detail || ''),
          fix_suggestion: String(ev.payload.fix_suggestion || ''),
          history_hint: String(ev.payload.history_hint || ''),
          related_rules: Array.isArray(ev.payload.related_rules) ? ev.payload.related_rules : [],
          failure_counter:
            (ev.payload.failure_counter as Record<string, number>) || {},
        };
        setRcaHistory((prev) => [...prev, info].slice(-10));
        if (info.failure_counter && Object.keys(info.failure_counter).length > 0) {
          setFailureCounter(info.failure_counter);
        }
        return;
      }
      // M95 — verifier_verdict 事件:更新最近一次 GLM 验证判决
      if (ev.type === 'verifier_verdict') {
        setLastVerifierVerdict({
          severity: (ev.payload.severity as VerifierVerdict['severity']) || 'ok',
          checked: !!ev.payload.checked,
          issues: Array.isArray(ev.payload.issues) ? ev.payload.issues : [],
          suggestions: Array.isArray(ev.payload.suggestions) ? ev.payload.suggestions : [],
        });
        return;
      }
      if (ev.type === 'approval_result') {
        setApprovalPending(null);
        setStream((prev) => {
          const item = eventToStreamItem(ev);
          return item ? [...prev, item] : prev;
        });
        return;
      }
      if (ev.type === 'tool_result') {
        setStream((prev) => {
          const tool = ev.payload?.tool as string;
          for (let i = prev.length - 1; i >= 0; i--) {
            const item = prev[i];
            if (item.tools && item.tools.some((t) => t.tool === tool && t.status === 'running')) {
              const updated = [...prev];
              updated[i] = {
                ...item,
                tools: item.tools.map((t) =>
                  t.tool === tool
                    ? { ...t, status: ev.payload?.status || 'ok', detail: ev.payload?.summary || t.detail }
                    : t
                ),
              };
              return updated;
            }
          }
          const item = eventToStreamItem(ev);
          return item ? [...prev, item] : prev;
        });
        return;
      }
      if (ev.type === 'file_change' || ev.type === 'terminal' || ev.type === 'browser') {
        setStream((prev) => {
          for (let i = prev.length - 1; i >= 0; i--) {
            const item = prev[i];
            if (item.tools && item.tools.some((t) => t.status === 'running')) {
              const updated = [...prev];
              const toolIndex = item.tools.findIndex((t) => t.status === 'running');
              const tool = item.tools[toolIndex];
              const childText =
                ev.type === 'file_change'
                  ? `文件: ${ev.payload.path} (${ev.payload.change || 'mod'})`
                  : ev.type === 'terminal'
                  ? `$ ${ev.payload.command || ''}\n${ev.payload.output || ''}`
                  : `浏览器: ${ev.payload.url}${ev.payload.title ? ` (${ev.payload.title})` : ''}`;
              const child: ToolChild = { type: ev.type as ToolChild['type'], text: childText };
              const newTool = { ...tool, children: [...(tool.children || []), child] };
              updated[i] = { ...item, tools: item.tools.map((t, idx) => (idx === toolIndex ? newTool : t)) };
              return updated;
            }
          }
          const item = eventToStreamItem(ev);
          return item ? [...prev, item] : prev;
        });
        return;
      }
      setStream((prev) => {
        const item = eventToStreamItem(ev);
        return item ? [...prev, item] : prev;
      });
    };

    const ws = connectEvents(selectedSessionId, {
      onOpen: () => setConnection('connected'),
      onClose: () => setConnection('idle'),
      onError: () => {
        setConnection('error');
        setError('WebSocket 连接失败');
      },
      onMessage: appendEvent,
      getLastEventId: () => lastEventIdRef.current,
    });

    wsRef.current = ws;
    return () => {
      // M165.3 — 卸载/会话切换时清掉未触发的防抖刷新,避免刷新到旧会话
      if (assistantRefreshTimerRef.current) {
        clearTimeout(assistantRefreshTimerRef.current);
        assistantRefreshTimerRef.current = null;
      }
      ws.close();
      wsRef.current = null;
    };
  }, [selectedSessionId]);

  return (
    <AppContext.Provider
      value={{
        sessions,
        selectedSessionId,
        stream,
        connection,
        error,
        sessionStatus,
        progress,
        errorCount,
        lastError,
        approvalPending,
        terminalBlocks,
        browserView,
        changedFiles,
        plan,
        detectedServerUrl,
        metrics,
        mcpServers,
        toggleMcpServer,
        refreshMcpServers,
        mcpTools,
        refreshMcpTools,
        callMcpTool,
        selectedModel,
        setModel,
        selectedMode,
        setMode,
        activeView,
        setActiveView,
        contextTab,
        setContextTab,
        sidebarTab,
        setSidebarTab,
        showContext,
        toggleContext,
        openContext,
        sidebarCollapsed,
        toggleSidebar,
        paletteOpen,
        setPaletteOpen,
        settingsOpen,
        setSettingsOpen,
        pluginsOpen,
        setPluginsOpen,
        terminalOpen,
        toggleTerminal,
        composerPrefill,
        prefillComposer,
        projectContext,
        projects,
        refreshProjects,
        openProject,
        createProject,
        projectFiles,
        openedFile,
        openFile,
        closeFile,
        browserRender,
        browserLoading,
        browserError,
        renderBrowser,
        gitDiff,
        gitDiffLoading,
        loadGitDiff,
        revertGitDiffFile,
        revertGitDiffHunk,
        aiReview,
        runAiReview,
        clearAiReview,
        reviewHistory,
        reviewHistoryLoading,
        loadReviewHistory,
        openReview,
        commitMessage,
        generateCommit,
        selectSession,
        createSession,
        deleteSession,
        cancelTask,
        sendTask,
        sendApproval,
        refreshSessions,
        factories,
        factoryDetail,
        factoryOpen,
        setFactoryOpen,
        refreshFactories,
        createFactory,
        selectFactory,
        resumeFactory,
        pauseFactory,
        factoryRcaHistory,
        loadFactoryRcaHistory,
        factoryQualityTrend,
        loadFactoryQualityTrend,
        rcaHistory,
        lastVerifierVerdict,
        failureCounter,
        clearRca,
        mobileSidebarOpen,
        setMobileSidebarOpen,
        mobilePanelOpen,
        setMobilePanelOpen,
        assistantTurns,
        assistantBusy,
        assistantError,
        assistantStream,
        sendAssistantMessage: sendAssistantMessageAction,
        approveAssistant: approveAssistantAction,
        rejectAssistant: rejectAssistantAction,
        clearAssistantTurns,
        appendAssistantLocalTurn,
        compactAssistant: compactAssistantAction,
        undoAssistant: undoAssistantAction,
        editAssistantMessage: editAssistantMessageAction,
        lastTruncated,
        undoEditTruncate: undoEditTruncateAction,
        dismissTruncated,
        assistantQueue,
        enqueueAssistantMessage,
        removeAssistantQueued,
        stopAssistantTask,
        goalActive,
        composerBusy,
        sendAssistantGoal: sendAssistantGoalAction,
        tasks,
        loadTasks,
        addTask,
        removeTask,
        toggleTaskEnabled,
        editTask,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within <AppProvider>');
  return ctx;
}
