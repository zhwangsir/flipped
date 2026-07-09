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
  ContextTab,
  SidebarTab,
  ProjectContext,
  Project,
  FileNode,
  BrowserRender,
  GitDiffFile,
  FactorySummary,
  FactoryDetail,
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
  fetchProjectContext,
  fetchProjectFiles,
  fetchProjectFile,
  fetchProjectDiff,
  openProject as apiOpenProject,
  fetchProjects,
  createProject as apiCreateProject,
  renderBrowser as apiRenderBrowser,
  listFactories as apiListFactories,
  createFactory as apiCreateFactory,
  getFactoryDetail as apiGetFactoryDetail,
  resumeFactory as apiResumeFactory,
  pauseFactory as apiPauseFactory,
  connectEvents,
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
  openedFile: { path: string; content: string } | null;
  openFile: (path: string) => Promise<void>;
  closeFile: () => void;
  browserRender: BrowserRender | null;
  browserLoading: boolean;
  browserError: string | null;
  renderBrowser: (url: string) => Promise<void>;
  gitDiff: GitDiffFile[];
  gitDiffLoading: boolean;
  loadGitDiff: () => Promise<void>;
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
  const [selectedModel, setSelectedModel] = useState('coder');
  const [selectedMode, setSelectedMode] = useState('agent');
  const [activeView, setActiveView] = useState('agent');
  const [contextTab, setContextTab] = useState<ContextTab>('files');
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>('chats');
  const [showContext, setShowContext] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [pluginsOpen, setPluginsOpen] = useState(false);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [composerPrefill, setComposerPrefill] = useState('');
  const [projectContext, setProjectContext] = useState<ProjectContext | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectFiles, setProjectFiles] = useState<FileNode[]>([]);
  const [openedFile, setOpenedFile] = useState<{ path: string; content: string } | null>(null);
  const [browserRender, setBrowserRender] = useState<BrowserRender | null>(null);
  const [browserLoading, setBrowserLoading] = useState(false);
  const [browserError, setBrowserError] = useState<string | null>(null);
  const [gitDiff, setGitDiff] = useState<GitDiffFile[]>([]);
  const [gitDiffLoading, setGitDiffLoading] = useState(false);
  const [factories, setFactories] = useState<FactorySummary[]>([]);
  const [factoryDetail, setFactoryDetail] = useState<FactoryDetail | null>(null);
  const [factoryOpen, setFactoryOpen] = useState(false);
  const toggleTerminal = useCallback(() => setTerminalOpen((v) => !v), []);
  const prefillComposer = useCallback((text: string) => setComposerPrefill(text), []);
  const wsRef = useRef<{ close: () => void; send: (msg: unknown) => void } | null>(null);

  const toggleContext = useCallback(() => setShowContext((v) => !v), []);
  const openContext = useCallback((t: ContextTab) => {
    setContextTab(t);
    setShowContext(true);
  }, []);
  const toggleSidebar = useCallback(() => setSidebarCollapsed((v) => !v), []);

  const refreshSessions = useCallback(async () => {
    try {
      const list = await fetchSessions();
      setSessions(list);
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

  // M7.3 — 拉取真实 MCP 服务器列表
  useEffect(() => {
    getMcpServers()
      .then(setMcpServers)
      .catch(() => {});
  }, []);

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
  const openFile = useCallback(async (path: string) => {
    try {
      const r = await fetchProjectFile(path);
      setOpenedFile({ path: r.path, content: r.content });
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
  const loadGitDiff = useCallback(async () => {
    setGitDiffLoading(true);
    try {
      const r = await fetchProjectDiff();
      setGitDiff(r.files);
    } catch {
      setGitDiff([]);
    } finally {
      setGitDiffLoading(false);
    }
  }, []);

  // Stage 3/4 — Codex 快捷键：⌘B 折叠侧栏 / ⌘K 命令面板
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey;
      if (meta && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        setSidebarCollapsed((v) => !v);
      } else if (meta && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      } else if (meta && e.key.toLowerCase() === 'j') {
        e.preventDefault();
        setTerminalOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
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

  const createFactory = useCallback(async (productGoal: string, cwd: string, maxTasks = 10) => {
    const d = await apiCreateFactory(productGoal, cwd, maxTasks);
    setFactoryDetail(d);
    setFactoryOpen(true);
    refreshFactories().catch(() => {});
    return d.factory_id;
  }, [refreshFactories]);

  const selectFactory = useCallback((id: string) => {
    apiGetFactoryDetail(id)
      .then(setFactoryDetail)
      .catch(() => setFactoryDetail(null));
    setFactoryOpen(true);
  }, []);

  const resumeFactory = useCallback(async (id: string) => {
    const d = await apiResumeFactory(id);
    setFactoryDetail(d);
  }, []);

  const pauseFactory = useCallback(async (id: string) => {
    const d = await apiPauseFactory(id);
    setFactoryDetail(d);
  }, []);

  useEffect(() => {
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

    const appendEvent = (ev: ApiEvent) => {
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
    });

    wsRef.current = ws;
    return () => {
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
