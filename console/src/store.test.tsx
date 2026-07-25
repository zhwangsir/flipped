/**
 * store.test.tsx · M153 前端覆盖率补强
 *
 * 目标：把 store.tsx 从 0% → 40%+，重点覆盖：
 * - UI 状态管理（toggleContext/toggleSidebar/setModel/setMode/setActiveView/...）
 * - 会话管理（selectSession/createSession/deleteSession）
 * - MCP toggle 乐观更新 + 失败回滚
 * - Assistant 动作（sendAssistantMessage/approve/reject/clearTurns）
 * - 键盘快捷键（⌘B/⌘K/⌘J/⌘N/⌘,/⌃⇧G）
 * - 错误处理
 *
 * 测试策略：
 * - 完整 mock ./api 模块（所有 API 函数返回 resolved promise）
 * - mock connectEvents 返回假 ws（避免真实 WS 连接）
 * - 用 StoreProbe 组件暴露 useApp() 状态，断言状态变化
 * - vi.useFakeTimers 控制轮询 effect
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, act } from '@testing-library/react';
import { AppProvider, useApp } from './store';

type AppState = ReturnType<typeof useApp>;

// ---------- mock api 模块 ----------
vi.mock('./api', () => ({
  fetchSessions: vi.fn(async () => []),
  createSession: vi.fn(async () => ({ id: 'sess-new', title: '新任务', mode: 'agent', status: 'idle' })),
  createTask: vi.fn(async () => ({})),
  deleteSession: vi.fn(async () => ({})),
  cancelTask: vi.fn(async () => ({})),
  fetchMetrics: vi.fn(async () => ({ uptime: 0, sessions: 0 })),
  getMcpServers: vi.fn(async () => [{ name: 'search', enabled: true }, { name: 'git', enabled: false }]),
  toggleMcpServer: vi.fn(async () => ({})),
  fetchProjectContext: vi.fn(async () => null),
  fetchProjectFiles: vi.fn(async () => []),
  fetchProjectFile: vi.fn(async () => ''),
  fetchProjectDiff: vi.fn(async () => []),
  openProject: vi.fn(async () => ({})),
  fetchProjects: vi.fn(async () => []),
  createProject: vi.fn(async () => ({})),
  renderBrowser: vi.fn(async () => null),
  listFactories: vi.fn(async () => []),
  createFactory: vi.fn(async () => ({ factory_id: 'fac-new', status: 'pending', tasks: [] })),
  getFactoryDetail: vi.fn(async () => ({ factory_id: 'fac-new', status: 'pending', tasks: [], roadmap: [], completed: [], failed: [] })),
  resumeFactory: vi.fn(async () => ({})),
  pauseFactory: vi.fn(async () => ({})),
  fetchFactoryRcaHistory: vi.fn(async () => ({ items: [] })),
  fetchFactoryQualityTrend: vi.fn(async () => ({ points: [] })),
  fetchFailureCounter: vi.fn(async () => ({})),
  connectEvents: vi.fn(() => ({
    close: vi.fn(),
    send: vi.fn(),
  })),
  createAssistantSession: vi.fn(async () => ({
    id: 'asst-new',
    title: '新对话',
    mode: 'agent',
    status: 'idle',
  })),
  sendAssistantMessage: vi.fn(async () => ({ task_id: 'task-1', session_id: 'asst-new' })),
  fetchAssistantHistory: vi.fn(async () => []),
  approveAssistant: vi.fn(async () => ({ ok: true })),
  rejectAssistant: vi.fn(async () => ({ ok: true })),
}));

// mock detectServerUrl（types.ts 里的，依赖 window.location）
vi.mock('./types', async (orig) => {
  const real = await orig<typeof import('./types')>();
  return {
    ...real,
    detectServerUrl: () => 'http://127.0.0.1:8011',
  };
});

// ---------- 测试 harness ----------
let captured: AppState | null = null;
function StoreProbe() {
  const state = useApp();
  captured = state;
  return null;
}

function renderProvider() {
  captured = null;
  return render(
    <AppProvider>
      <StoreProbe />
    </AppProvider>
  );
}

// 等待 React effects 完成（轮询/初始加载）
async function flush(ms = 0) {
  await act(async () => {
    if (ms > 0) await new Promise((r) => setTimeout(r, ms));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
  captured = null;
});

// ---------- 测试 ----------

describe('AppProvider · UI 状态管理', () => {
  it('初始状态：默认值正确', async () => {
    renderProvider();
    await flush();
    expect(captured).not.toBeNull();
    expect(captured!.connection).toBe('idle');
    expect(captured!.selectedModel).toBe('coder');
    expect(captured!.selectedMode).toBe('agent');
    expect(captured!.activeView).toBe('assistant');
    expect(captured!.contextTab).toBe('files');
    expect(captured!.sidebarTab).toBe('chats');
    expect(captured!.showContext).toBe(true);
    expect(captured!.sidebarCollapsed).toBe(false);
    expect(captured!.paletteOpen).toBe(false);
    expect(captured!.settingsOpen).toBe(false);
    expect(captured!.terminalOpen).toBe(false);
    expect(captured!.sessions).toEqual([]);
    expect(captured!.stream).toEqual([]);
    expect(captured!.approvalPending).toBeNull();
  });

  it('toggleContext: 切换 showContext', async () => {
    renderProvider();
    await flush();
    expect(captured!.showContext).toBe(true);
    act(() => captured!.toggleContext());
    expect(captured!.showContext).toBe(false);
    act(() => captured!.toggleContext());
    expect(captured!.showContext).toBe(true);
  });

  it('openContext: 设置 tab 并打开', async () => {
    renderProvider();
    await flush();
    act(() => captured!.openContext('diff'));
    expect(captured!.contextTab).toBe('diff');
    expect(captured!.showContext).toBe(true);
  });

  it('toggleSidebar: 切换折叠', async () => {
    renderProvider();
    await flush();
    expect(captured!.sidebarCollapsed).toBe(false);
    act(() => captured!.toggleSidebar());
    expect(captured!.sidebarCollapsed).toBe(true);
  });

  it('setModel/setMode/setActiveView/setContextTab/setSidebarTab', async () => {
    renderProvider();
    await flush();
    act(() => {
      captured!.setModel('architect');
      captured!.setMode('chat');
      captured!.setActiveView('factory');
      captured!.setContextTab('browser');
      captured!.setSidebarTab('files');
    });
    expect(captured!.selectedModel).toBe('architect');
    expect(captured!.selectedMode).toBe('chat');
    expect(captured!.activeView).toBe('factory');
    expect(captured!.contextTab).toBe('browser');
    expect(captured!.sidebarTab).toBe('files');
  });

  it('toggleTerminal: 切换终端开关', async () => {
    renderProvider();
    await flush();
    expect(captured!.terminalOpen).toBe(false);
    act(() => captured!.toggleTerminal());
    expect(captured!.terminalOpen).toBe(true);
  });

  it('prefillComposer: 设置预填文本', async () => {
    renderProvider();
    await flush();
    expect(captured!.composerPrefill).toBe('');
    act(() => captured!.prefillComposer('hello world'));
    expect(captured!.composerPrefill).toBe('hello world');
  });

  it('setPaletteOpen/setSettingsOpen/setPluginsOpen/setFactoryOpen', async () => {
    renderProvider();
    await flush();
    act(() => {
      captured!.setPaletteOpen(true);
      captured!.setSettingsOpen(true);
      captured!.setPluginsOpen(true);
      captured!.setFactoryOpen(true);
    });
    expect(captured!.paletteOpen).toBe(true);
    expect(captured!.settingsOpen).toBe(true);
    expect(captured!.pluginsOpen).toBe(true);
    expect(captured!.factoryOpen).toBe(true);
  });
});

describe('AppProvider · 会话管理', () => {
  it('createSession: 调 API + 添加到列表 + 选中', async () => {
    const { createSession } = await import('./api');
    renderProvider();
    await flush();
    let newId: string | undefined;
    await act(async () => {
      newId = await captured!.createSession('测试任务', 'agent');
    });
    expect(createSession).toHaveBeenCalledWith('测试任务', 'agent');
    expect(newId).toBe('sess-new');
    expect(captured!.sessions).toHaveLength(1);
    expect(captured!.sessions[0].id).toBe('sess-new');
    expect(captured!.selectedSessionId).toBe('sess-new');
  });

  it('deleteSession: 调 API + 从列表移除', async () => {
    const { deleteSession } = await import('./api');
    renderProvider();
    await flush();
    // 先创建一个会话
    await act(async () => {
      await captured!.createSession();
    });
    expect(captured!.sessions).toHaveLength(1);
    // 删除它
    await act(async () => {
      await captured!.deleteSession('sess-new');
    });
    expect(deleteSession).toHaveBeenCalledWith('sess-new');
    expect(captured!.sessions).toHaveLength(0);
    expect(captured!.selectedSessionId).toBeNull();
  });

  it('selectSession: 设置 selectedSessionId', async () => {
    renderProvider();
    await flush();
    // 手动注入会话（通过 createSession mock）
    await act(async () => {
      await captured!.createSession();
    });
    // 先取消选中
    await act(async () => {
      captured!.selectSession('sess-new');
    });
    expect(captured!.selectedSessionId).toBe('sess-new');
  });
});

describe('AppProvider · MCP 服务器', () => {
  it('初始加载 MCP 列表', async () => {
    const { getMcpServers } = await import('./api');
    renderProvider();
    await flush();
    expect(getMcpServers).toHaveBeenCalled();
    expect(captured!.mcpServers).toHaveLength(2);
    expect(captured!.mcpServers[0].name).toBe('search');
    expect(captured!.mcpServers[0].enabled).toBe(true);
    expect(captured!.mcpServers[1].enabled).toBe(false);
  });

  it('toggleMcpServer: 乐观更新（立即翻转 UI）', async () => {
    renderProvider();
    await flush();
    // search 初始 enabled=true
    expect(captured!.mcpServers.find((s: { name: string }) => s.name === 'search')!.enabled).toBe(true);
    // 翻转为 false
    await act(async () => {
      await captured!.toggleMcpServer('search', false);
    });
    expect(captured!.mcpServers.find((s: { name: string }) => s.name === 'search')!.enabled).toBe(false);
  });

  it('toggleMcpServer: API 失败 → 回滚到原值', async () => {
    const { toggleMcpServer } = await import('./api');
    (toggleMcpServer as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('network'));
    renderProvider();
    await flush();
    // git 初始 enabled=false，尝试开启
    expect(captured!.mcpServers.find((s: { name: string }) => s.name === 'git')!.enabled).toBe(false);
    await act(async () => {
      await captured!.toggleMcpServer('git', true);
    });
    // 回滚：应该还是 false
    expect(captured!.mcpServers.find((s: { name: string }) => s.name === 'git')!.enabled).toBe(false);
  });

  it('refreshMcpServers: 手动刷新', async () => {
    const { getMcpServers } = await import('./api');
    renderProvider();
    await flush();
    const initialCalls = (getMcpServers as ReturnType<typeof vi.fn>).mock.calls.length;
    act(() => captured!.refreshMcpServers());
    await flush(10);
    expect((getMcpServers as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(initialCalls);
  });
});

describe('AppProvider · Assistant 动作', () => {
  it('clearAssistantTurns: 清空 turns', async () => {
    renderProvider();
    await flush();
    act(() => captured!.clearAssistantTurns());
    expect(captured!.assistantTurns).toEqual([]);
  });

  it('sendAssistantMessage: 空文本 → 不调 API', async () => {
    const { sendAssistantMessage } = await import('./api');
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.sendAssistantMessage('   ');
    });
    expect(sendAssistantMessage).not.toHaveBeenCalled();
  });

  it('sendAssistantMessage: 有文本 + 无选中会话 → 创建会话 + 发消息', async () => {
    const { sendAssistantMessage, createAssistantSession } = await import('./api');
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.sendAssistantMessage('写一个 calc.py');
    });
    expect(createAssistantSession).toHaveBeenCalled();
    expect(sendAssistantMessage).toHaveBeenCalledWith('asst-new', { text: '写一个 calc.py' });
    expect(captured!.assistantBusy).toBe(false); // finally 后复位
  });

  it('sendAssistantMessage: API 失败 → 设置 assistantError + 重抛', async () => {
    const { sendAssistantMessage } = await import('./api');
    (sendAssistantMessage as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('model 503'));
    renderProvider();
    await flush();
    await act(async () => {
      try {
        await captured!.sendAssistantMessage('hi');
      } catch {
        // 预期重抛
      }
    });
    expect(captured!.assistantError).toBe('model 503');
    expect(captured!.assistantBusy).toBe(false); // finally 后复位
  });

  it('approveAssistant: 调 API + 刷新历史', async () => {
    const { approveAssistant } = await import('./api');
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.approveAssistant('asst-1');
    });
    expect(approveAssistant).toHaveBeenCalledWith('asst-1');
    expect(captured!.assistantBusy).toBe(false);
  });

  it('rejectAssistant: 调 API + 设置 busy', async () => {
    const { rejectAssistant } = await import('./api');
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.rejectAssistant('asst-1');
    });
    expect(rejectAssistant).toHaveBeenCalledWith('asst-1');
    expect(captured!.assistantBusy).toBe(false);
  });
});

describe('AppProvider · 工厂管理', () => {
  it('refreshFactories: 初始加载 + 手动刷新', async () => {
    const { listFactories } = await import('./api');
    renderProvider();
    await flush();
    expect(listFactories).toHaveBeenCalled();
    await act(async () => {
      await captured!.refreshFactories();
    });
    expect((listFactories as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it('createFactory: 调 API', async () => {
    const { createFactory } = await import('./api');
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.createFactory('goal: build calc', '/workspace');
    });
    expect(createFactory).toHaveBeenCalledWith('goal: build calc', '/workspace', 10);
  });

  it('pauseFactory / resumeFactory: 调 API', async () => {
    const { pauseFactory, resumeFactory } = await import('./api');
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.pauseFactory('fac-1');
    });
    expect(pauseFactory).toHaveBeenCalledWith('fac-1');
    await act(async () => {
      await captured!.resumeFactory('fac-1');
    });
    expect(resumeFactory).toHaveBeenCalledWith('fac-1');
  });
});

describe('AppProvider · RCA / verifier', () => {
  it('clearRca: 清空 RCA 三件套', async () => {
    renderProvider();
    await flush();
    act(() => captured!.clearRca());
    expect(captured!.rcaHistory).toEqual([]);
    expect(captured!.lastVerifierVerdict).toBeNull();
    expect(captured!.failureCounter).toEqual({});
  });
});

describe('AppProvider · useApp 守卫', () => {
  it('useApp 在 Provider 外调用 → 抛错', () => {
    // 捕获 console.error（React 会打印错误）
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<StoreProbe />)).toThrow('useApp must be used within <AppProvider>');
    spy.mockRestore();
  });
});

// ---------- 文件操作 + browser render + git diff ----------

describe('AppProvider · 项目文件操作', () => {
  it('refreshProjects: 调 API + 写入 projects', async () => {
    const { fetchProjects } = await import('./api');
    // 用 persistent mock（不只 Once），覆盖默认返回 []
    (fetchProjects as ReturnType<typeof vi.fn>).mockResolvedValue({
      projects: [{ name: 'app1', host: '/p/app1', sandbox: '/projects/app1' }],
    });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.refreshProjects();
    });
    expect(fetchProjects).toHaveBeenCalled();
    expect(captured!.projects?.length).toBeGreaterThanOrEqual(1);
  });

  it('refreshProjects: API 失败 → 清空 projects', async () => {
    const { fetchProjects } = await import('./api');
    (fetchProjects as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('net'));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.refreshProjects();
    });
    expect(captured!.projects).toEqual([]);
  });

  it('openProject: 调 API + 刷新上下文/文件树/diff/项目列表', async () => {
    const { openProject, fetchProjectContext, fetchProjectFiles, fetchProjectDiff, fetchProjects } = await import('./api');
    (openProject as ReturnType<typeof vi.fn>).mockResolvedValue({ name: 'p', host: '/p', sandbox: '/projects/p' });
    (fetchProjectContext as ReturnType<typeof vi.fn>).mockResolvedValue({ project: 'p', path: '/p', sandbox: null, branch: 'main', mode: 'agent' });
    (fetchProjectFiles as ReturnType<typeof vi.fn>).mockResolvedValue({ tree: [{ name: 'f.ts', path: 'f.ts', type: 'file' }] });
    (fetchProjectDiff as ReturnType<typeof vi.fn>).mockResolvedValue({ files: [{ path: 'f.ts', added: 1, removed: 0, lines: [] }] });
    (fetchProjects as ReturnType<typeof vi.fn>).mockResolvedValue({ projects: [] });
    renderProvider();
    await flush();
    let r: { name: string } | undefined;
    await act(async () => {
      r = await captured!.openProject('/path/to/proj');
    });
    await flush();
    expect(openProject).toHaveBeenCalledWith('/path/to/proj');
    expect(fetchProjectContext).toHaveBeenCalled();
    expect(fetchProjectFiles).toHaveBeenCalled();
    expect(fetchProjectDiff).toHaveBeenCalled();
    expect(fetchProjects).toHaveBeenCalled();
    expect(r).toEqual({ name: 'p', host: '/p', sandbox: '/projects/p' });
    // openProject 后切到该项目的文件树
    expect(captured!.projectFiles.length).toBeGreaterThanOrEqual(1);
  });

  it('openProject: 失败时抛错（refreshAfterSwitch 不会执行因为 openProject 在前）', async () => {
    const { openProject } = await import('./api');
    (openProject as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('bad path'));
    renderProvider();
    await flush();
    await act(async () => {
      try {
        await captured!.openProject('/bad');
      } catch {
        // 预期抛
      }
    });
    expect(openProject).toHaveBeenCalledWith('/bad');
  });

  it('createProject: 调 API + 刷新上下文', async () => {
    const { createProject, fetchProjectContext } = await import('./api');
    (createProject as ReturnType<typeof vi.fn>).mockResolvedValue({ name: 'new-app', host: '/p/new-app', sandbox: '/projects/new-app' });
    (fetchProjectContext as ReturnType<typeof vi.fn>).mockResolvedValue({ project: 'new-app', path: '/p/new-app', sandbox: null, branch: 'main', mode: 'agent' });
    renderProvider();
    await flush();
    let r: { name: string } | undefined;
    await act(async () => {
      r = await captured!.createProject('new-app');
    });
    await flush();
    expect(createProject).toHaveBeenCalledWith('new-app');
    expect(r).toEqual({ name: 'new-app', host: '/p/new-app', sandbox: '/projects/new-app' });
  });

  it('openFile: 成功 → 设置 openedFile + 切到 files tab', async () => {
    const { fetchProjectFile } = await import('./api');
    (fetchProjectFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ path: 'src/a.ts', content: 'export const x = 1;' });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.openFile('src/a.ts');
    });
    expect(fetchProjectFile).toHaveBeenCalledWith('src/a.ts');
    expect(captured!.openedFile).toEqual({ path: 'src/a.ts', content: 'export const x = 1;' });
    expect(captured!.contextTab).toBe('files');
  });

  it('openFile: 失败 → 静默（openedFile 保持 null）', async () => {
    const { fetchProjectFile } = await import('./api');
    (fetchProjectFile as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('is binary'));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.openFile('binary.png');
    });
    expect(captured!.openedFile).toBeNull();
  });

  it('closeFile: 清空 openedFile', async () => {
    const { fetchProjectFile } = await import('./api');
    (fetchProjectFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ path: 'src/a.ts', content: 'x' });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.openFile('src/a.ts');
    });
    expect(captured!.openedFile).not.toBeNull();
    act(() => captured!.closeFile());
    expect(captured!.openedFile).toBeNull();
  });
});

describe('AppProvider · browser render + git diff', () => {
  it('renderBrowser: 成功 → 设置 browserRender + 清空 error', async () => {
    const { renderBrowser } = await import('./api');
    const fakeRender = {
      url: 'http://localhost:3000',
      title: 'Home',
      screenshot: 'data:image/png;base64,xxx',
      elements: [],
      viewport: { width: 1280, height: 720 },
    };
    (renderBrowser as ReturnType<typeof vi.fn>).mockResolvedValueOnce(fakeRender);
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.renderBrowser('http://localhost:3000');
    });
    expect(captured!.browserRender).toEqual(fakeRender);
    expect(captured!.browserLoading).toBe(false);
    expect(captured!.browserError).toBeNull();
  });

  it('renderBrowser: 失败 → 设置 browserError + 清空 loading', async () => {
    const { renderBrowser } = await import('./api');
    (renderBrowser as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('navigate timeout'));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.renderBrowser('http://bad');
    });
    expect(captured!.browserRender).toBeNull();
    expect(captured!.browserError).toBe('navigate timeout');
    expect(captured!.browserLoading).toBe(false);
  });

  it('renderBrowser: 失败抛非 Error → 转字符串', async () => {
    const { renderBrowser } = await import('./api');
    (renderBrowser as ReturnType<typeof vi.fn>).mockRejectedValueOnce('oops');
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.renderBrowser('http://x');
    });
    expect(captured!.browserError).toBe('oops');
  });

  it('loadGitDiff: 成功 → 设置 gitDiff', async () => {
    const { fetchProjectDiff } = await import('./api');
    (fetchProjectDiff as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      files: [{ path: 'a.ts', added: 1, removed: 1, lines: [{ type: 'add', text: '+1' }] }],
    });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.loadGitDiff();
    });
    expect(captured!.gitDiff.length).toBe(1);
    expect(captured!.gitDiffLoading).toBe(false);
  });

  it('loadGitDiff: 失败 → gitDiff 清空', async () => {
    const { fetchProjectDiff } = await import('./api');
    (fetchProjectDiff as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('not a repo'));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.loadGitDiff();
    });
    expect(captured!.gitDiff).toEqual([]);
    expect(captured!.gitDiffLoading).toBe(false);
  });
});

// ---------- 工厂详情/RCA/质量/事件流 ----------

describe('AppProvider · 工厂详情/RCA/质量', () => {
  it('selectFactory(空) → 清空 detail/rca/quality', async () => {
    renderProvider();
    await flush();
    await act(async () => {
      captured!.selectFactory('');
    });
    expect(captured!.factoryDetail).toBeNull();
    expect(captured!.factoryRcaHistory).toBeNull();
    expect(captured!.factoryQualityTrend).toBeNull();
  });

  it('selectFactory(非空) → 拉取 detail/rca/quality + 打开 panel', async () => {
    const { getFactoryDetail, fetchFactoryRcaHistory, fetchFactoryQualityTrend } = await import('./api');
    const fakeDetail = {
      factory_id: 'fac-1', product_goal: 'g', cwd: '/tmp', status: 'running',
      roadmap: [], completed: [], failed: [], current_task_id: null,
      context_summary: '', iteration_count: 0, max_tasks: 5,
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
    (getFactoryDetail as ReturnType<typeof vi.fn>).mockResolvedValueOnce(fakeDetail);
    (fetchFactoryRcaHistory as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      factory_id: 'fac-1', rca_history: [], cause_stats: {},
    });
    (fetchFactoryQualityTrend as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      factory_id: 'fac-1', trend: { direction: 'stable', samples: 0 }, history: [],
    });
    renderProvider();
    await flush();
    await act(async () => {
      captured!.selectFactory('fac-1');
    });
    await flush();
    expect(getFactoryDetail).toHaveBeenCalledWith('fac-1');
    expect(fetchFactoryRcaHistory).toHaveBeenCalledWith('fac-1');
    expect(fetchFactoryQualityTrend).toHaveBeenCalledWith('fac-1');
    expect(captured!.factoryDetail?.factory_id).toBe('fac-1');
    expect(captured!.factoryOpen).toBe(true);
    expect(captured!.factoryRcaHistory?.factory_id).toBe('fac-1');
    expect(captured!.factoryQualityTrend?.factory_id).toBe('fac-1');
  });

  it('selectFactory: getFactoryDetail 失败 → setFactoryDetail(null) fail-open', async () => {
    const { getFactoryDetail, fetchFactoryRcaHistory, fetchFactoryQualityTrend } = await import('./api');
    (getFactoryDetail as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('404'));
    (fetchFactoryRcaHistory as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('net'));
    (fetchFactoryQualityTrend as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('net'));
    renderProvider();
    await flush();
    await act(async () => {
      captured!.selectFactory('fac-x');
    });
    await flush();
    expect(captured!.factoryDetail).toBeNull();
    expect(captured!.factoryRcaHistory).toBeNull();
    expect(captured!.factoryQualityTrend).toBeNull();
  });

  it('createFactory: 端点返回 summary → 回拉 detail + 打开 panel + 刷新列表', async () => {
    const { createFactory, getFactoryDetail, listFactories } = await import('./api');
    (createFactory as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      factory_id: 'fac-new', status: 'pending', max_tasks: 5,
    });
    const detail = {
      factory_id: 'fac-new', product_goal: 'g', cwd: '/tmp', status: 'pending',
      roadmap: [], completed: [], failed: [], current_task_id: null,
      context_summary: '', iteration_count: 0, max_tasks: 5,
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
    (getFactoryDetail as ReturnType<typeof vi.fn>).mockResolvedValueOnce(detail);
    renderProvider();
    await flush();
    let fid: string | undefined;
    await act(async () => {
      fid = await captured!.createFactory('build x', '/tmp', 7);
    });
    expect(createFactory).toHaveBeenCalledWith('build x', '/tmp', 7);
    expect(getFactoryDetail).toHaveBeenCalledWith('fac-new');
    expect(fid).toBe('fac-new');
    expect(captured!.factoryDetail?.factory_id).toBe('fac-new');
    expect(captured!.factoryOpen).toBe(true);
    expect(listFactories).toHaveBeenCalled();
  });

  it('resumeFactory: 端点成功 → 回拉 detail', async () => {
    const { resumeFactory, getFactoryDetail } = await import('./api');
    (resumeFactory as ReturnType<typeof vi.fn>).mockResolvedValueOnce({});
    const detail = {
      factory_id: 'fac-r', product_goal: 'g', cwd: '/tmp', status: 'running',
      roadmap: [], completed: [], failed: [], current_task_id: null,
      context_summary: '', iteration_count: 1, max_tasks: 5,
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
    (getFactoryDetail as ReturnType<typeof vi.fn>).mockResolvedValueOnce(detail);
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.resumeFactory('fac-r');
    });
    expect(resumeFactory).toHaveBeenCalledWith('fac-r');
    expect(getFactoryDetail).toHaveBeenCalledWith('fac-r');
    expect(captured!.factoryDetail?.status).toBe('running');
  });

  it('pauseFactory: 端点成功 → 回拉 detail', async () => {
    const { pauseFactory, getFactoryDetail } = await import('./api');
    (pauseFactory as ReturnType<typeof vi.fn>).mockResolvedValueOnce({});
    const detail = {
      factory_id: 'fac-p', product_goal: 'g', cwd: '/tmp', status: 'paused',
      roadmap: [], completed: [], failed: [], current_task_id: null,
      context_summary: '', iteration_count: 1, max_tasks: 5,
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
    (getFactoryDetail as ReturnType<typeof vi.fn>).mockResolvedValueOnce(detail);
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.pauseFactory('fac-p');
    });
    expect(pauseFactory).toHaveBeenCalledWith('fac-p');
    expect(captured!.factoryDetail?.status).toBe('paused');
  });

  it('loadFactoryRcaHistory: 成功 → 写入 state', async () => {
    const { fetchFactoryRcaHistory } = await import('./api');
    (fetchFactoryRcaHistory as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      factory_id: 'fac-1', rca_history: [{ cause: 'x', confidence: 0.5, fix_suggestion: '', history_hint: '', related_rules: [], task_index: 0, timestamp: new Date().toISOString() }], cause_stats: { x: 1 },
    });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.loadFactoryRcaHistory('fac-1');
    });
    expect(captured!.factoryRcaHistory?.rca_history.length).toBe(1);
  });

  it('loadFactoryRcaHistory: 失败 → fail-open（state 不变）', async () => {
    const { fetchFactoryRcaHistory } = await import('./api');
    (fetchFactoryRcaHistory as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('net'));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.loadFactoryRcaHistory('fac-1');
    });
    expect(captured!.factoryRcaHistory).toBeNull();
  });

  it('loadFactoryQualityTrend: 成功 → 写入 state', async () => {
    const { fetchFactoryQualityTrend } = await import('./api');
    (fetchFactoryQualityTrend as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      factory_id: 'fac-1', trend: { direction: 'stable', samples: 1 }, history: [],
    });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.loadFactoryQualityTrend('fac-1');
    });
    expect(captured!.factoryQualityTrend?.trend.direction).toBe('stable');
  });

  it('loadFactoryQualityTrend: 失败 → fail-open（state 不变）', async () => {
    const { fetchFactoryQualityTrend } = await import('./api');
    (fetchFactoryQualityTrend as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('net'));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.loadFactoryQualityTrend('fac-1');
    });
    expect(captured!.factoryQualityTrend).toBeNull();
  });

  it('M9 轮询：running 工厂 → 启动 setInterval 拉 detail', async () => {
    const { getFactoryDetail } = await import('./api');
    const detail = {
      factory_id: 'fac-poll', product_goal: 'g', cwd: '/tmp', status: 'running',
      roadmap: [], completed: [], failed: [], current_task_id: null,
      context_summary: '', iteration_count: 1, max_tasks: 5,
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
    (getFactoryDetail as ReturnType<typeof vi.fn>).mockResolvedValue(detail);
    renderProvider();
    await flush();
    await act(async () => {
      captured!.selectFactory('fac-poll');
    });
    await flush();
    expect(captured!.factoryDetail?.status).toBe('running');
    // 推进定时器 3s → 触发轮询
    const initialCalls = (getFactoryDetail as ReturnType<typeof vi.fn>).mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    expect((getFactoryDetail as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(initialCalls);
  });
});

// ---------- 会话切换 / sendTask / sendApproval / cancelTask ----------

describe('AppProvider · 会话切换与任务', () => {
  it('selectSession: 设置 selectedSessionId + 会话有 project 时切到该项目', async () => {
    const { createSession, openProject } = await import('./api');
    const s = { id: 'sess-1', title: 't', status: 'idle', model: 'coder', mode: 'agent', project: '/p/proj', project_name: 'proj', created_at: '', updated_at: '' };
    (createSession as ReturnType<typeof vi.fn>).mockResolvedValueOnce(s);
    (openProject as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ name: 'proj', host: '/p/proj', sandbox: '/projects/proj' });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.createSession();
    });
    // 现在有 sessions 列表，选中它（带 project 触发 openProject）
    await act(async () => {
      captured!.selectSession('sess-1');
    });
    expect(captured!.selectedSessionId).toBe('sess-1');
    // openProject 异步调用，flush 一下
    await flush();
    expect(openProject).toHaveBeenCalledWith('/p/proj');
  });

  it('selectSession: 会话 project === 当前项目路径 → 不重复 openProject', async () => {
    const { createSession, fetchProjectContext, openProject } = await import('./api');
    const s = { id: 'sess-2', title: 't', status: 'idle', model: 'coder', mode: 'agent', project: '/current', project_name: 'cur', created_at: '', updated_at: '' };
    (createSession as ReturnType<typeof vi.fn>).mockResolvedValueOnce(s);
    (fetchProjectContext as ReturnType<typeof vi.fn>).mockResolvedValue({ project: 'cur', path: '/current', sandbox: null, branch: 'main', mode: 'agent' });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.createSession();
    });
    const before = (openProject as ReturnType<typeof vi.fn>).mock.calls.length;
    await act(async () => {
      captured!.selectSession('sess-2');
    });
    await flush();
    // project '/current' 等于 projectContext.path → 不触发 openProject
    expect((openProject as ReturnType<typeof vi.fn>).mock.calls.length).toBe(before);
  });

  it('sendTask: 无 session → 先创建 + 调 createTask', async () => {
    const { createSession, createTask } = await import('./api');
    (createSession as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ id: 's1', title: 't', status: 'idle', model: 'coder', mode: 'agent', created_at: '', updated_at: '' });
    renderProvider();
    await flush();
    expect(captured!.selectedSessionId).toBeNull();
    await act(async () => {
      await captured!.sendTask('do something');
    });
    expect(createSession).toHaveBeenCalled();
    expect(createTask).toHaveBeenCalledWith('s1', 'do something', 'coder', 'agent');
  });

  it('sendTask: 有 session → 直接调 createTask', async () => {
    const { createSession, createTask } = await import('./api');
    (createSession as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ id: 's2', title: 't', status: 'idle', model: 'coder', mode: 'agent', created_at: '', updated_at: '' });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.createSession();
    });
    const before = (createSession as ReturnType<typeof vi.fn>).mock.calls.length;
    await act(async () => {
      await captured!.sendTask('next task');
    });
    expect((createSession as ReturnType<typeof vi.fn>).mock.calls.length).toBe(before);
    expect(createTask).toHaveBeenCalledWith('s2', 'next task', 'coder', 'agent');
  });

  it('cancelTask: 调 apiCancelTask(选中会话 id)', async () => {
    const { createSession, cancelTask } = await import('./api');
    (createSession as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ id: 's3', title: 't', status: 'idle', model: 'coder', mode: 'agent', created_at: '', updated_at: '' });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.createSession();
    });
    await act(async () => {
      await captured!.cancelTask();
    });
    expect(cancelTask).toHaveBeenCalledWith('s3');
  });

  it('cancelTask: 无选中会话 → 不调 API', async () => {
    const { cancelTask } = await import('./api');
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.cancelTask();
    });
    expect(cancelTask).not.toHaveBeenCalled();
  });

  it('sendApproval: 调 ws.send({type:"approval_result",decision,reason})', async () => {
    const { connectEvents } = await import('./api');
    const send = vi.fn();
    (connectEvents as ReturnType<typeof vi.fn>).mockReturnValueOnce({ close: vi.fn(), send });
    renderProvider();
    await flush();
    // 先选中一个会话才能让 connectEvents 被调用
    const { createSession } = await import('./api');
    (createSession as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ id: 's4', title: 't', status: 'idle', model: 'coder', mode: 'agent', created_at: '', updated_at: '' });
    await act(async () => {
      await captured!.createSession();
    });
    await flush();
    act(() => {
      captured!.sendApproval('approve', 'ok');
    });
    expect(send).toHaveBeenCalledWith({ type: 'approval_result', decision: 'approve', reason: 'ok' });
  });
});

// ---------- WebSocket 事件流 ----------

describe('AppProvider · WebSocket 事件流', () => {
  // 工具：渲染后注入一个会话并拿到 connectEvents 第 4 参数 (handlers)
  async function connectSession() {
    const { connectEvents, createSession } = await import('./api');
    const handlers: { onOpen?: () => void; onClose?: () => void; onError?: () => void; onMessage?: (ev: any) => void; getLastEventId?: () => string | null } = {};
    (connectEvents as ReturnType<typeof vi.fn>).mockImplementationOnce((_sid: string, h: any) => {
      Object.assign(handlers, h);
      return { close: vi.fn(), send: vi.fn() };
    });
    (createSession as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ id: 'ws-sess', title: 't', status: 'idle', model: 'coder', mode: 'agent', created_at: '', updated_at: '' });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.createSession();
    });
    await flush();
    return handlers;
  }

  it('onOpen → connection=connected', async () => {
    const h = await connectSession();
    act(() => h.onOpen?.());
    expect(captured!.connection).toBe('connected');
  });

  it('onClose → connection=idle', async () => {
    const h = await connectSession();
    act(() => h.onOpen?.());
    act(() => h.onClose?.());
    expect(captured!.connection).toBe('idle');
  });

  it('onError → connection=error + 设置 error', async () => {
    const h = await connectSession();
    act(() => h.onError?.());
    expect(captured!.connection).toBe('error');
    expect(captured!.error).toContain('WebSocket');
  });

  it('terminal 事件 → 追加 terminalBlocks + 检测 server URL', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: 'ev1', session_id: 'ws-sess', type: 'terminal', agent: 'worker',
      payload: { command: 'npm run dev', output: 'Server on http://localhost:3000', exit_code: 0 },
    }));
    expect(captured!.terminalBlocks.length).toBe(1);
    expect(captured!.terminalBlocks[0].command).toBe('npm run dev');
    expect(captured!.detectedServerUrl).toBeTruthy();
  });

  it('browser 事件 → 设置 browserView', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: 'ev2', session_id: 'ws-sess', type: 'browser', agent: 'worker',
      payload: { url: 'http://x', title: 'T', screenshot: 'data:...' },
    }));
    expect(captured!.browserView?.url).toBe('http://x');
  });

  it('file_change 事件 → 追加 changedFiles (含 content)', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: 'ev3', session_id: 'ws-sess', type: 'file_change', agent: 'worker',
      payload: { path: 'src/a.ts', change: 'add', language: 'typescript', content: 'export const x = 1;' },
    }));
    expect(captured!.changedFiles.find((f) => f.path === 'src/a.ts')?.content).toBe('export const x = 1;');
  });

  it('file_change 事件 content 非字符串 → 不写 content (现有保留)', async () => {
    const h = await connectSession();
    // 先入一条带 content 的
    act(() => h.onMessage?.({
      id: 'ev3a', session_id: 'ws-sess', type: 'file_change', agent: 'worker',
      payload: { path: 'src/b.ts', change: 'mod', language: 'typescript', content: 'old' },
    }));
    // 再入一条 content 是数组（脏数据）
    act(() => h.onMessage?.({
      id: 'ev3b', session_id: 'ws-sess', type: 'file_change', agent: 'worker',
      payload: { path: 'src/b.ts', change: 'mod', language: 'typescript', content: ['bad'] },
    }));
    const f = captured!.changedFiles.find((x) => x.path === 'src/b.ts');
    expect(f?.content).toBe('old'); // 保留原内容
  });

  it('plan 事件 → 设置 plan state', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: 'ev4', session_id: 'ws-sess', type: 'plan', agent: 'supervisor',
      payload: { steps: [{ index: 0, text: 's1', status: 'running' }], complete: false },
    }));
    expect(captured!.plan?.steps.length).toBe(1);
  });

  it('status 事件 → 更新 sessionStatus/progress + 同步 sessions', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: 'ev5', session_id: 'ws-sess', type: 'status', agent: 'system',
      payload: { status: 'running', progress: 50 },
    }));
    expect(captured!.sessionStatus).toBe('running');
    expect(captured!.progress).toBe(50);
    expect(captured!.sessions.find((s) => s.id === 'ws-sess')?.status).toBe('running');
  });

  it('error 事件 → 增加 errorCount + 设置 lastError', async () => {
    const h = await connectSession();
    const before = captured!.errorCount;
    act(() => h.onMessage?.({
      id: 'ev6', session_id: 'ws-sess', type: 'error', agent: 'system',
      payload: { message: 'boom' },
    }));
    expect(captured!.errorCount).toBe(before + 1);
    expect(captured!.lastError).toBe('boom');
  });

  it('approval_request 事件 → 设置 approvalPending', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: 'ev7', session_id: 'ws-sess', type: 'approval_request', agent: 'system',
      payload: { action: 'rm -rf', reason: '危险', risk: 'high' },
    }));
    expect(captured!.approvalPending?.action).toBe('rm -rf');
    expect(captured!.approvalPending?.risk).toBe('high');
  });

  it('rca 事件 → 追加 rcaHistory + 同步 failureCounter', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: 'ev8', session_id: 'ws-sess', type: 'rca', agent: 'verify',
      payload: {
        cause: 'syntax_error', confidence: 0.85, detail: 'd', fix_suggestion: 'fs',
        history_hint: 'hh', related_rules: ['r1'], failure_counter: { syntax_error: 3 },
      },
    }));
    expect(captured!.rcaHistory.length).toBe(1);
    expect(captured!.rcaHistory[0].cause).toBe('syntax_error');
    expect(captured!.failureCounter.syntax_error).toBe(3);
  });

  it('rca 事件无 failure_counter → 不覆盖现有 counter', async () => {
    const h = await connectSession();
    // 先有 rca 设置 counter
    act(() => h.onMessage?.({
      id: 'ev8a', session_id: 'ws-sess', type: 'rca', agent: 'verify',
      payload: { cause: 'a', confidence: 0.5, detail: '', fix_suggestion: '', history_hint: '', related_rules: [], failure_counter: { a: 1 } },
    }));
    expect(captured!.failureCounter.a).toBe(1);
    // 再来一个无 failure_counter → counter 不变
    act(() => h.onMessage?.({
      id: 'ev8b', session_id: 'ws-sess', type: 'rca', agent: 'verify',
      payload: { cause: 'b', confidence: 0.5, detail: '', fix_suggestion: '', history_hint: '', related_rules: [] },
    }));
    expect(captured!.failureCounter.a).toBe(1);
  });

  it('verifier_verdict 事件 → 设置 lastVerifierVerdict', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: 'ev9', session_id: 'ws-sess', type: 'verifier_verdict', agent: 'verify',
      payload: { severity: 'warning', checked: true, issues: ['i1'], suggestions: ['s1'] },
    }));
    expect(captured!.lastVerifierVerdict?.severity).toBe('warning');
    expect(captured!.lastVerifierVerdict?.issues.length).toBe(1);
  });

  it('approval_result 事件 → 清空 approvalPending + 推入 stream', async () => {
    const h = await connectSession();
    // 先发 approval_request
    act(() => h.onMessage?.({
      id: 'ev10a', session_id: 'ws-sess', type: 'approval_request', agent: 'system',
      payload: { action: 'x' },
    }));
    expect(captured!.approvalPending).not.toBeNull();
    // 发 approval_result（approve）
    act(() => h.onMessage?.({
      id: 'ev10b', session_id: 'ws-sess', type: 'approval_result', agent: 'user',
      payload: { decision: 'approve' },
    }));
    expect(captured!.approvalPending).toBeNull();
    expect(captured!.stream.length).toBeGreaterThanOrEqual(1);
    expect(captured!.stream[captured!.stream.length - 1].text).toContain('已放行');
  });

  it('approval_result reject → stream 显示「已否决」', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: 'ev10c', session_id: 'ws-sess', type: 'approval_result', agent: 'user',
      payload: { decision: 'reject' },
    }));
    expect(captured!.stream.some((s) => s.text?.includes('已否决'))).toBe(true);
  });

  it('tool_result 事件 → 更新 stream 中匹配的 running tool 状态', async () => {
    const h = await connectSession();
    // 先注入一个 tool_call running
    act(() => h.onMessage?.({
      id: 'ev11a', session_id: 'ws-sess', type: 'tool_call', agent: 'worker',
      payload: { tool: 'terminal', summary: 'ls', status: 'running' },
    }));
    expect(captured!.stream.length).toBe(1);
    expect(captured!.stream[0].tools?.[0].status).toBe('running');
    // tool_result → 更新为 ok
    act(() => h.onMessage?.({
      id: 'ev11b', session_id: 'ws-sess', type: 'tool_result', agent: 'worker',
      payload: { tool: 'terminal', summary: 'done', status: 'ok' },
    }));
    expect(captured!.stream[0].tools?.[0].status).toBe('ok');
    expect(captured!.stream[0].tools?.[0].detail).toBe('done');
  });

  it('tool_result 事件 无匹配 running tool → 作为新 item 推入', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: 'ev12', session_id: 'ws-sess', type: 'tool_result', agent: 'worker',
      payload: { tool: 'search', summary: 'done search', status: 'ok' },
    }));
    expect(captured!.stream.length).toBeGreaterThanOrEqual(1);
  });

  it('terminal/file_change/browser 事件 在 stream 中有 running tool → 追加 child', async () => {
    const h = await connectSession();
    // 先有 running tool_call
    act(() => h.onMessage?.({
      id: 'ev13a', session_id: 'ws-sess', type: 'tool_call', agent: 'worker',
      payload: { tool: 'terminal', summary: 'cmd', status: 'running' },
    }));
    // terminal 事件 → 追加为 child
    act(() => h.onMessage?.({
      id: 'ev13b', session_id: 'ws-sess', type: 'terminal', agent: 'worker',
      payload: { command: 'echo hi', output: 'hi', exit_code: 0 },
    }));
    const tool = captured!.stream[0].tools?.[0];
    expect(tool?.children?.length).toBe(1);
    expect(tool?.children?.[0].type).toBe('terminal');
    expect(tool?.children?.[0].text).toContain('echo hi');
  });

  it('file_change 事件 在 stream 中有 running tool → 追加 file child', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: 'ev14a', session_id: 'ws-sess', type: 'tool_call', agent: 'worker',
      payload: { tool: 'file_editor', summary: 'edit', status: 'running' },
    }));
    act(() => h.onMessage?.({
      id: 'ev14b', session_id: 'ws-sess', type: 'file_change', agent: 'worker',
      payload: { path: 'src/x.ts', change: 'mod' },
    }));
    const tool = captured!.stream[0].tools?.[0];
    expect(tool?.children?.[0].type).toBe('file_change');
  });

  it('browser 事件 在 stream 中有 running tool → 追加 browser child', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: 'ev15a', session_id: 'ws-sess', type: 'tool_call', agent: 'worker',
      payload: { tool: 'browser', summary: 'open', status: 'running' },
    }));
    act(() => h.onMessage?.({
      id: 'ev15b', session_id: 'ws-sess', type: 'browser', agent: 'worker',
      payload: { url: 'http://x', title: 'X' },
    }));
    const tool = captured!.stream[0].tools?.[0];
    expect(tool?.children?.[0].type).toBe('browser');
  });

  it('message 事件 → 推入 stream（system 角色被隐藏）', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: 'ev16a', session_id: 'ws-sess', type: 'message', agent: 'system',
      payload: { text: '机械 prompt' },
    }));
    // system 角色 message 不显示
    expect(captured!.stream.length).toBe(0);
    // worker 消息显示
    act(() => h.onMessage?.({
      id: 'ev16b', session_id: 'ws-sess', type: 'message', agent: 'worker',
      payload: { text: 'hello' },
    }));
    expect(captured!.stream.length).toBe(1);
  });

  it('unknown 事件类型 → 推入 stream 为 JSON 字符串', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: 'ev17', session_id: 'ws-sess', type: 'weird_event', agent: 'worker',
      payload: { foo: 'bar' },
    }));
    expect(captured!.stream.length).toBe(1);
    expect(captured!.stream[0].text).toContain('"foo"');
  });

  it('事件流带 id → 更新 lastEventId', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: 'ev-with-id-99', session_id: 'ws-sess', type: 'message', agent: 'worker',
      payload: { text: 'hi' },
    }));
    expect(h.getLastEventId?.()).toBe('ev-with-id-99');
  });

  it('rca 事件列表上限 10 条（slice -10）', async () => {
    const h = await connectSession();
    for (let i = 0; i < 12; i++) {
      act(() => h.onMessage?.({
        id: `ev-rca-${i}`, session_id: 'ws-sess', type: 'rca', agent: 'verify',
        payload: { cause: 'c', confidence: 0.1, detail: '', fix_suggestion: '', history_hint: '', related_rules: [] },
      }));
    }
    expect(captured!.rcaHistory.length).toBe(10);
  });
});

// ---------- mobileSidebarOpen / mobilePanelOpen ----------

describe('AppProvider · 移动端抽屉', () => {
  it('setMobileSidebarOpen 切换状态', async () => {
    renderProvider();
    await flush();
    expect(captured!.mobileSidebarOpen).toBe(false);
    act(() => captured!.setMobileSidebarOpen(true));
    expect(captured!.mobileSidebarOpen).toBe(true);
  });

  it('setMobilePanelOpen 切换状态', async () => {
    renderProvider();
    await flush();
    expect(captured!.mobilePanelOpen).toBe(false);
    act(() => captured!.setMobilePanelOpen(true));
    expect(captured!.mobilePanelOpen).toBe(true);
  });
});

// ---------- assistant 轮询历史 ----------

describe('AppProvider · Assistant 历史与轮询', () => {
  it('approveAssistant: API 失败 → 设置 assistantError + 不重抛', async () => {
    const { approveAssistant } = await import('./api');
    (approveAssistant as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('500'));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.approveAssistant('asst-x');
    });
    expect(captured!.assistantError).toBe('500');
    expect(captured!.assistantBusy).toBe(false);
  });

  it('rejectAssistant: API 失败 → 设置 assistantError + 不重抛', async () => {
    const { rejectAssistant } = await import('./api');
    (rejectAssistant as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('reject-fail'));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.rejectAssistant('asst-y');
    });
    expect(captured!.assistantError).toBe('reject-fail');
    expect(captured!.assistantBusy).toBe(false);
  });

  it('refreshAssistantHistory: 历史 API 失败 → fail-open（turns 保持空）', async () => {
    const { fetchAssistantHistory } = await import('./api');
    (fetchAssistantHistory as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('net'));
    renderProvider();
    await flush();
    // 选中一个会话 → 触发 refreshAssistantHistory
    const { createAssistantSession } = await import('./api');
    (createAssistantSession as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ id: 'asst-z', title: 't', mode: 'agent', status: 'idle' });
    await act(async () => {
      await captured!.sendAssistantMessage('hello');
    });
    // fail-open 不抛错
    expect(captured!.assistantTurns).toEqual([]);
  });
});
