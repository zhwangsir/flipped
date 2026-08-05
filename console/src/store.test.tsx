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
  getMcpTools: vi.fn(async () => ({
    tools: [
      { name: 'web_search', description: '联网搜索', inputSchema: { type: 'object' } },
      { name: 'run_coding_task', description: '跑编码任务', inputSchema: { type: 'object' } },
    ],
  })),
  callMcpTool: vi.fn(async () => ({ ok: true, tool: 'web_search', result: { answer: 42 } })),
  fetchProjectContext: vi.fn(async () => null),
  fetchProjectFiles: vi.fn(async () => []),
  fetchProjectFile: vi.fn(async () => ''),
  fetchProjectDiff: vi.fn(async () => []),
  revertProjectHunk: vi.fn(async (path: string, hunk_index: number) => ({
    ok: true,
    path,
    hunk_index,
    action: 'hunk_reverted',
  })),
  reviewProject: vi.fn(async () => ({ findings: [], files_reviewed: 0, model: 'coder' })),
  // M186.1 — 评审历史
  fetchProjectReviews: vi.fn(async () => ({ reviews: [] })),
  fetchProjectReview: vi.fn(async (id: string) => ({
    id,
    ts: '2026-08-05T10:30:00Z',
    project: 'p',
    model: 'glm-x',
    files_reviewed: 1,
    findings_count: 1,
    findings: [{ path: 'a.ts', line: 3, severity: 'high', message: '空指针' }],
  })),
  // M186.4 — AI commit message
  generateCommitMessage: vi.fn(async () => ({ message: 'feat: x', model: 'glm-x', files_count: 1, note: null })),
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
  // M176 — Goal 模式
  startAssistantGoal: vi.fn(async () => ({
    task_id: 'task-goal',
    session_id: 'asst-new',
    objective: 'obj',
    max_iterations: 5,
  })),
  fetchAssistantGoal: vi.fn(async () => null),
  fetchAssistantHistory: vi.fn(async () => []),
  approveAssistant: vi.fn(async () => ({ ok: true })),
  rejectAssistant: vi.fn(async () => ({ ok: true })),
  compactAssistant: vi.fn(async () => ({ ok: true, session_id: 'asst-1', summary: '摘要' })),
  // M178.2/M187.2 — 已安排任务
  fetchTasks: vi.fn(async () => []),
  createScheduledTask: vi.fn(async (body: Record<string, unknown>) => ({ id: 'task-new', ...body })),
  deleteTask: vi.fn(async () => ({ ok: true })),
  toggleTask: vi.fn(async () => ({})),
  patchTask: vi.fn(async (id: string, body: Record<string, unknown>) => ({ id, ...body })),
  editAssistantMessage: vi.fn(async () => ({
    ok: true,
    session_id: 'asst-1',
    task_id: 'task-edit',
    truncated: true,
    restored: true,
    deleted: [],
  })),
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

// M170.2 — Plugins 面板「MCP 工具调用」store 动作
describe('AppProvider · MCP 工具调用 (M170.2)', () => {
  it('refreshMcpTools: 拉取并填充 mcpTools state', async () => {
    const { getMcpTools } = await import('./api');
    renderProvider();
    await flush();
    expect(captured!.mcpTools).toEqual([]);
    await act(async () => {
      await captured!.refreshMcpTools();
    });
    expect(getMcpTools).toHaveBeenCalled();
    expect(captured!.mcpTools).toHaveLength(2);
    expect(captured!.mcpTools[0].name).toBe('web_search');
    expect(captured!.mcpTools[1].name).toBe('run_coding_task');
  });

  it('callMcpTool: 快工具透传后端响应(不带 session_id)', async () => {
    const { callMcpTool } = await import('./api');
    renderProvider();
    await flush();
    (callMcpTool as ReturnType<typeof vi.fn>).mockClear();
    let r: Awaited<ReturnType<AppState['callMcpTool']>> | null = null;
    await act(async () => {
      r = await captured!.callMcpTool('web_search', { query: 'mlx' });
    });
    expect(callMcpTool).toHaveBeenCalledWith('web_search', { arguments: { query: 'mlx' } });
    expect(r).toEqual({ ok: true, tool: 'web_search', result: { answer: 42 } });
  });

  it('callMcpTool: 长工具自动带 selectedSessionId', async () => {
    const { callMcpTool } = await import('./api');
    (callMcpTool as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      accepted: true,
      tool: 'run_coding_task',
      session_id: 'sess-new',
    });
    renderProvider();
    await flush();
    // createSession mock 返回 id='sess-new',createSession action 会把它设为选中会话
    await act(async () => {
      await captured!.createSession();
    });
    expect(captured!.selectedSessionId).toBe('sess-new');
    (callMcpTool as ReturnType<typeof vi.fn>).mockClear();
    let r: Awaited<ReturnType<AppState['callMcpTool']>> | null = null;
    await act(async () => {
      r = await captured!.callMcpTool('run_coding_task', { goal: '修 bug' });
    });
    expect(callMcpTool).toHaveBeenCalledWith('run_coding_task', {
      arguments: { goal: '修 bug' },
      session_id: 'sess-new',
    });
    expect(r!.accepted).toBe(true);
    expect(r!.session_id).toBe('sess-new');
  });

  it('callMcpTool: 无会话时长工具返回 no-session 且不发请求', async () => {
    const { callMcpTool } = await import('./api');
    renderProvider();
    await flush();
    expect(captured!.selectedSessionId).toBeNull();
    (callMcpTool as ReturnType<typeof vi.fn>).mockClear();
    let r: Awaited<ReturnType<AppState['callMcpTool']>> | null = null;
    await act(async () => {
      r = await captured!.callMcpTool('research_and_code', { research_query: 'q', coding_task: 'c' });
    });
    expect(r).toEqual({ ok: false, tool: 'research_and_code', error: 'no-session' });
    expect(callMcpTool).not.toHaveBeenCalled();
  });
});

describe('AppProvider · Assistant 动作', () => {
  it('clearAssistantTurns: 清空 turns', async () => {
    renderProvider();
    await flush();
    act(() => captured!.clearAssistantTurns());
    expect(captured!.assistantTurns).toEqual([]);
  });

  // M165.1a — slash 命令本地反馈 turn
  it('appendAssistantLocalTurn: 追加一条本地 assistant turn', async () => {
    renderProvider();
    await flush();
    act(() => captured!.appendAssistantLocalTurn('本地提示'));
    const turns = captured!.assistantTurns;
    expect(turns.length).toBe(1);
    expect(turns[0].role).toBe('assistant');
    expect(turns[0].text).toBe('本地提示');
    expect(turns[0].tools).toEqual([]);
    expect(typeof turns[0].created_at).toBe('string');
  });

  // M165.1a — /compact 压缩上下文
  it('compactAssistant: 成功 → 调 API + 刷新历史', async () => {
    const { compactAssistant, fetchAssistantHistory } = await import('./api');
    renderProvider();
    await flush();
    const before = (fetchAssistantHistory as ReturnType<typeof vi.fn>).mock.calls.length;
    await act(async () => {
      await captured!.compactAssistant('asst-1');
    });
    expect(compactAssistant).toHaveBeenCalledWith('asst-1');
    const calls = (fetchAssistantHistory as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.length).toBeGreaterThan(before);
    expect(calls[calls.length - 1][0]).toBe('asst-1');
    expect(captured!.assistantBusy).toBe(false);
  });

  it('compactAssistant: API 失败(如 409 空历史) → 追加错误提示 turn + 不抛错', async () => {
    const { compactAssistant } = await import('./api');
    (compactAssistant as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('HTTP 409: empty history'));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.compactAssistant('asst-1');
    });
    const last = captured!.assistantTurns[captured!.assistantTurns.length - 1];
    expect(last?.role).toBe('assistant');
    expect(last?.text).toContain('409');
    expect(captured!.assistantBusy).toBe(false);
  });

  // M165.2a — Always 审批:scope 透传到 API 层
  it('approveAssistant: 带 scope=always → API 收到 scope', async () => {
    const { approveAssistant } = await import('./api');
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.approveAssistant('asst-1', 'always');
    });
    expect(approveAssistant).toHaveBeenCalledWith('asst-1', 'always');
    expect(captured!.assistantBusy).toBe(false);
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

  // M192 — 图像附件:images 第三参非空 → 请求体带 images 字段(与后端契约字段名一字不差)
  it('sendAssistantMessage: images 非空 → 请求体带 images 字段', async () => {
    const { sendAssistantMessage } = await import('./api');
    renderProvider();
    await flush();
    const images = [{ name: 'a.png', media_type: 'image/png', data_base64: 'QUJD' }];
    await act(async () => {
      await captured!.sendAssistantMessage('看图', 'chat', images);
    });
    expect(sendAssistantMessage).toHaveBeenCalledWith('asst-new', { text: '看图', mode: 'chat', images });
  });

  // M192 — 回归:无 images/空数组 → 请求体与现状完全一致(无 images 键)
  it('sendAssistantMessage: 无 images → 请求体无 images 键(回归零变化)', async () => {
    const { sendAssistantMessage } = await import('./api');
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.sendAssistantMessage('写一个 calc.py');
    });
    const body = (sendAssistantMessage as ReturnType<typeof vi.fn>).mock.calls[0][1] as Record<string, unknown>;
    expect('images' in body).toBe(false);
    await act(async () => {
      await captured!.sendAssistantMessage('空数组也等价无图', 'chat', []);
    });
    const body2 = (sendAssistantMessage as ReturnType<typeof vi.fn>).mock.calls[1][1] as Record<string, unknown>;
    expect('images' in body2).toBe(false);
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
    // M165.2a — scope 未传时透传 undefined(API 层此时不带 body)
    expect(approveAssistant).toHaveBeenCalledWith('asst-1', undefined);
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

  // M186.2 — findings 行号跳转:openFile(path, line) 把目标行写进 openedFile
  it('openFile: 带 line → openedFile 含 line(跳转目标行)', async () => {
    const { fetchProjectFile } = await import('./api');
    (fetchProjectFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ path: 'src/a.ts', content: 'x\ny\n' });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.openFile('src/a.ts', 2);
    });
    expect(fetchProjectFile).toHaveBeenCalledWith('src/a.ts');
    expect(captured!.openedFile).toEqual({ path: 'src/a.ts', content: 'x\ny\n', line: 2 });
    expect(captured!.contextTab).toBe('files');
  });

  it('openFile: 带 line 失败 → 静默（openedFile 保持 null）', async () => {
    const { fetchProjectFile } = await import('./api');
    (fetchProjectFile as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('is binary'));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.openFile('binary.png', 5);
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

  it('revertGitDiffHunk: 成功 → 调 api 并刷新 diff(M193.2)', async () => {
    const { revertProjectHunk, fetchProjectDiff } = await import('./api');
    renderProvider();
    await flush();
    vi.clearAllMocks();
    (fetchProjectDiff as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ files: [] });
    let r: unknown;
    await act(async () => {
      r = await captured!.revertGitDiffHunk('src/a.ts', 1);
    });
    expect(revertProjectHunk).toHaveBeenCalledWith('src/a.ts', 1);
    expect(fetchProjectDiff).toHaveBeenCalled();
    expect((r as { action: string }).action).toBe('hunk_reverted');
  });

  it('revertGitDiffHunk: 失败 → 错误原样上抛且不刷新', async () => {
    const { revertProjectHunk, fetchProjectDiff } = await import('./api');
    renderProvider();
    await flush();
    vi.clearAllMocks();
    (revertProjectHunk as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('HTTP 409: 漂移'));
    await expect(captured!.revertGitDiffHunk('src/a.ts', 0)).rejects.toThrow('HTTP 409');
    expect(fetchProjectDiff).not.toHaveBeenCalled();
  });
});

// ---------- M179.2 · AI 代码评审 ----------

describe('AppProvider · M179.2 AI 评审', () => {
  it('runAiReview: 成功 → 写 result,loading 复位,error 清空', async () => {
    const { reviewProject } = await import('./api');
    (reviewProject as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      findings: [{ path: 'a.ts', line: 3, severity: 'high', message: '空指针', suggestion: '加判空' }],
      files_reviewed: 1,
      model: 'coder',
      note: null,
    });
    renderProvider();
    await flush();
    expect(captured!.aiReview).toEqual({ result: null, loading: false, error: null });
    await act(async () => {
      await captured!.runAiReview();
    });
    expect(captured!.aiReview.loading).toBe(false);
    expect(captured!.aiReview.error).toBeNull();
    expect(captured!.aiReview.result?.findings).toHaveLength(1);
    expect(captured!.aiReview.result?.model).toBe('coder');
  });

  it('runAiReview("architect") → 透传 model 给 apiReviewProject(M194.4)', async () => {
    const { reviewProject } = await import('./api');
    (reviewProject as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      findings: [],
      files_reviewed: 0,
      model: 'architect',
      note: null,
    });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.runAiReview('architect');
    });
    expect(reviewProject).toHaveBeenCalledWith('architect');
    expect(captured!.aiReview.result?.model).toBe('architect');
  });

  it('runAiReview() 无参 → apiReviewProject 不带 model(默认模型走后端)', async () => {
    const { reviewProject } = await import('./api');
    (reviewProject as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      findings: [],
      files_reviewed: 0,
      model: 'coder',
      note: null,
    });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.runAiReview();
    });
    expect(reviewProject).toHaveBeenCalledWith(undefined);
  });

  it('runAiReview: 失败 → 写 error(detail 字符串),loading 必复位', async () => {
    const { reviewProject } = await import('./api');
    (reviewProject as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('HTTP 502: LLM 解析失败'));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.runAiReview();
    });
    expect(captured!.aiReview.loading).toBe(false);
    expect(captured!.aiReview.result).toBeNull();
    expect(captured!.aiReview.error).toContain('502');
  });

  it('clearAiReview: 清空 result 与 error', async () => {
    const { reviewProject } = await import('./api');
    (reviewProject as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      findings: [{ path: 'a.ts', severity: 'low', message: 'x' }],
      files_reviewed: 1,
      model: 'm',
    });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.runAiReview();
    });
    expect(captured!.aiReview.result).not.toBeNull();
    act(() => {
      captured!.clearAiReview();
    });
    expect(captured!.aiReview).toEqual({ result: null, loading: false, error: null });
  });

  it('loadGitDiff 刷新 → 清空 aiReview.result(diff 变了旧 findings 失效)', async () => {
    const { reviewProject, fetchProjectDiff } = await import('./api');
    (reviewProject as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      findings: [{ path: 'a.ts', severity: 'low', message: 'x' }],
      files_reviewed: 1,
      model: 'm',
    });
    (fetchProjectDiff as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ files: [] });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.runAiReview();
    });
    expect(captured!.aiReview.result).not.toBeNull();
    await act(async () => {
      await captured!.loadGitDiff();
    });
    expect(captured!.aiReview.result).toBeNull();
    expect(captured!.aiReview.loading).toBe(false);
  });
});

// ---------- M186.1 评审历史 / M186.4 AI commit message ----------

describe('AppProvider · M186.1 评审历史', () => {
  it('loadReviewHistory: 成功 → 写入列表,loading 复位', async () => {
    const { fetchProjectReviews } = await import('./api');
    (fetchProjectReviews as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      reviews: [
        { id: 'r1', ts: '2026-08-05T10:30:00Z', project: 'p', model: 'glm-x', files_reviewed: 2, findings_count: 3 },
        { id: 'r2', ts: '2026-08-04T09:00:00Z', project: 'p', model: 'coder', files_reviewed: 1, findings_count: 0 },
      ],
    });
    renderProvider();
    await flush();
    expect(captured!.reviewHistory).toEqual([]);
    expect(captured!.reviewHistoryLoading).toBe(false);
    await act(async () => {
      await captured!.loadReviewHistory();
    });
    expect(captured!.reviewHistoryLoading).toBe(false);
    expect(captured!.reviewHistory).toHaveLength(2);
    expect(captured!.reviewHistory[0].id).toBe('r1');
    expect(captured!.reviewHistory[1].model).toBe('coder');
  });

  it('loadReviewHistory: 失败 → 静默(列表保持空,loading 复位,不抛错)', async () => {
    const { fetchProjectReviews } = await import('./api');
    (fetchProjectReviews as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('HTTP 500'));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.loadReviewHistory();
    });
    expect(captured!.reviewHistoryLoading).toBe(false);
    expect(captured!.reviewHistory).toEqual([]);
  });

  it('openReview: 成功 → aiReview.result 回放该次评审(findings + historical=true + review_id)', async () => {
    const { fetchProjectReview } = await import('./api');
    (fetchProjectReview as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 'r1',
      ts: '2026-08-05T10:30:00Z',
      project: 'p',
      model: 'glm-x',
      files_reviewed: 2,
      findings_count: 1,
      findings: [{ path: 'a.ts', line: 3, severity: 'high', message: '空指针', suggestion: '加判空' }],
    });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.openReview('r1');
    });
    expect(fetchProjectReview).toHaveBeenCalledWith('r1');
    const r = captured!.aiReview.result;
    expect(r).not.toBeNull();
    expect(r!.historical).toBe(true);
    expect(r!.review_id).toBe('r1');
    expect(r!.findings).toHaveLength(1);
    expect(r!.files_reviewed).toBe(2);
    expect(r!.model).toBe('glm-x');
    expect(captured!.aiReview.loading).toBe(false);
    expect(captured!.aiReview.error).toBeNull();
  });

  it('openReview: 失败 → 静默(aiReview 保持原状,不抛错)', async () => {
    const { fetchProjectReview } = await import('./api');
    (fetchProjectReview as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('HTTP 404'));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.openReview('gone');
    });
    expect(captured!.aiReview).toEqual({ result: null, loading: false, error: null });
  });
});

describe('AppProvider · M186.4 AI commit message', () => {
  it('generateCommit: 成功 → 写 result,loading 复位,error 清空', async () => {
    const { generateCommitMessage } = await import('./api');
    (generateCommitMessage as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      message: 'feat: 增加评审历史',
      model: 'glm-x',
      files_count: 2,
      note: null,
    });
    renderProvider();
    await flush();
    expect(captured!.commitMessage).toEqual({ result: null, loading: false, error: null });
    await act(async () => {
      await captured!.generateCommit();
    });
    expect(captured!.commitMessage.loading).toBe(false);
    expect(captured!.commitMessage.error).toBeNull();
    expect(captured!.commitMessage.result?.message).toBe('feat: 增加评审历史');
    expect(captured!.commitMessage.result?.model).toBe('glm-x');
    expect(captured!.commitMessage.result?.files_count).toBe(2);
  });

  it('generateCommit: 失败 → 写 error,loading 必复位', async () => {
    const { generateCommitMessage } = await import('./api');
    (generateCommitMessage as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('HTTP 502: LLM 超时'));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.generateCommit();
    });
    expect(captured!.commitMessage.loading).toBe(false);
    expect(captured!.commitMessage.result).toBeNull();
    expect(captured!.commitMessage.error).toContain('502');
  });

  it('loadGitDiff 刷新 → 清空 commitMessage.result(diff 变了旧提交信息失效)', async () => {
    const { generateCommitMessage, fetchProjectDiff } = await import('./api');
    (generateCommitMessage as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      message: 'fix: y',
      model: 'm',
      files_count: 1,
      note: null,
    });
    (fetchProjectDiff as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ files: [] });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.generateCommit();
    });
    expect(captured!.commitMessage.result).not.toBeNull();
    await act(async () => {
      await captured!.loadGitDiff();
    });
    expect(captured!.commitMessage.result).toBeNull();
    expect(captured!.commitMessage.loading).toBe(false);
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

  // M165.3 — 事件驱动对话渲染:助手相关事件 → 300ms 防抖刷新历史(替代 2.5s 轮询)
  it('message/tool 事件 → 300ms 防抖后刷新助手历史(同窗多事件合并为一次)', async () => {
    const { fetchAssistantHistory } = await import('./api');
    const h = await connectSession();
    const before = (fetchAssistantHistory as ReturnType<typeof vi.fn>).mock.calls.length;
    // 同一防抖窗口内连发 3 个助手相关事件
    act(() => h.onMessage?.({
      id: 'ev-d1', session_id: 'ws-sess', type: 'message', agent: 'worker',
      payload: { text: 'a' },
    }));
    act(() => h.onMessage?.({
      id: 'ev-d2', session_id: 'ws-sess', type: 'tool_call', agent: 'worker',
      payload: { tool: 'terminal', summary: 'ls', status: 'running' },
    }));
    act(() => h.onMessage?.({
      id: 'ev-d3', session_id: 'ws-sess', type: 'tool_result', agent: 'worker',
      payload: { tool: 'terminal', summary: 'done', status: 'ok' },
    }));
    // 防抖窗口内不立即刷新
    expect((fetchAssistantHistory as ReturnType<typeof vi.fn>).mock.calls.length).toBe(before);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(350);
    });
    // 300ms 后合并为恰好一次刷新,目标是当前会话
    const calls = (fetchAssistantHistory as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.length).toBe(before + 1);
    expect(calls[calls.length - 1][0]).toBe('ws-sess');
  });

  it('approval_request 事件 → 防抖后同样刷新助手历史', async () => {
    const { fetchAssistantHistory } = await import('./api');
    const h = await connectSession();
    const before = (fetchAssistantHistory as ReturnType<typeof vi.fn>).mock.calls.length;
    act(() => h.onMessage?.({
      id: 'ev-d4', session_id: 'ws-sess', type: 'approval_request', agent: 'system',
      payload: { action: 'rm -rf', risk: 'high' },
    }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(350);
    });
    expect((fetchAssistantHistory as ReturnType<typeof vi.fn>).mock.calls.length).toBe(before + 1);
  });

  // M169.2 — usage 事件(worker 回复收尾):纳入防抖刷新集合,驱动末端 history 刷新以渲染 token 用量
  it('usage 事件 → 防抖后刷新助手历史', async () => {
    const { fetchAssistantHistory } = await import('./api');
    const h = await connectSession();
    const before = (fetchAssistantHistory as ReturnType<typeof vi.fn>).mock.calls.length;
    act(() => h.onMessage?.({
      id: 'ev-u1', session_id: 'ws-sess', type: 'usage', agent: 'worker',
      payload: { prompt: 12345, completion: 3420, calls: 1 },
    }));
    // 防抖窗口内不立即刷新
    expect((fetchAssistantHistory as ReturnType<typeof vi.fn>).mock.calls.length).toBe(before);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(350);
    });
    expect((fetchAssistantHistory as ReturnType<typeof vi.fn>).mock.calls.length).toBe(before + 1);
  });

  it('无 WS 事件推进 10s → 不发起 history 请求(running 状态下 2.5s 轮询已删)', async () => {
    const { fetchAssistantHistory } = await import('./api');
    const h = await connectSession();
    // 让会话进入 running —— 旧 2.5s 轮询的触发条件
    act(() => h.onMessage?.({
      id: 'ev-st', session_id: 'ws-sess', type: 'status', agent: 'system',
      payload: { status: 'running', progress: 10 },
    }));
    expect(captured!.sessionStatus).toBe('running');
    const before = (fetchAssistantHistory as ReturnType<typeof vi.fn>).mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    // status 事件不属于防抖刷新集合,且轮询已删 → 10s 内零 history 请求
    expect((fetchAssistantHistory as ReturnType<typeof vi.fn>).mock.calls.length).toBe(before);
  });
});

// ---------- M166.3 — assistant token 级流式(chat/plan 直聊) ----------

describe('AppProvider · M166.3 assistant token 流', () => {
  // 与 WebSocket 事件流 describe 相同的 harness:渲染 + 注入会话 + 捕获 handlers
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

  it('初始 assistantStream = {text:"",active:false}', async () => {
    renderProvider();
    await flush();
    expect(captured!.assistantStream).toEqual({ text: '', active: false });
  });

  it('token 事件累积:连发 3 个 → text 拼接 + active=true', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: null, session_id: 'ws-sess', type: 'token', agent: 'worker',
      payload: { text: '你好', seq: 1, done: false },
    }));
    act(() => h.onMessage?.({
      id: null, session_id: 'ws-sess', type: 'token', agent: 'worker',
      payload: { text: ',世界', seq: 2, done: false },
    }));
    act(() => h.onMessage?.({
      id: null, session_id: 'ws-sess', type: 'token', agent: 'worker',
      payload: { text: '!', seq: 3, done: false },
    }));
    expect(captured!.assistantStream).toEqual({ text: '你好,世界!', active: true });
  });

  it('done token → 清除流式态(message 事件随后收敛)', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: null, session_id: 'ws-sess', type: 'token', agent: 'worker',
      payload: { text: '部分输出', seq: 1, done: false },
    }));
    expect(captured!.assistantStream.active).toBe(true);
    act(() => h.onMessage?.({
      id: null, session_id: 'ws-sess', type: 'token', agent: 'worker',
      payload: { text: '', seq: 2, done: true },
    }));
    expect(captured!.assistantStream).toEqual({ text: '', active: false });
  });

  it('token 事件排除在防抖刷新集合外:推进 10s 零 history 请求(防回归)', async () => {
    const { fetchAssistantHistory } = await import('./api');
    const h = await connectSession();
    const before = (fetchAssistantHistory as ReturnType<typeof vi.fn>).mock.calls.length;
    // 连发多个 token —— 若 token 误入防抖集合,300ms 后会触发 fetch
    for (let i = 1; i <= 5; i++) {
      act(() => h.onMessage?.({
        id: null, session_id: 'ws-sess', type: 'token', agent: 'worker',
        payload: { text: `t${i}`, seq: i, done: false },
      }));
    }
    expect(captured!.assistantStream.active).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect((fetchAssistantHistory as ReturnType<typeof vi.fn>).mock.calls.length).toBe(before);
  });

  it('worker message 事件 → 清除 active 流式态(双保险收敛)', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: null, session_id: 'ws-sess', type: 'token', agent: 'worker',
      payload: { text: '流式片段', seq: 1, done: false },
    }));
    expect(captured!.assistantStream.active).toBe(true);
    // 完整 reply 落盘 message 到达(正常路径 done token 先到,但 message 必须兜底收敛)
    act(() => h.onMessage?.({
      id: 'ev-msg-1', session_id: 'ws-sess', type: 'message', agent: 'worker',
      payload: { text: '流式片段完整版' },
    }));
    expect(captured!.assistantStream).toEqual({ text: '', active: false });
  });

  it('切换会话 → assistantStream 重置', async () => {
    const h = await connectSession();
    act(() => h.onMessage?.({
      id: null, session_id: 'ws-sess', type: 'token', agent: 'worker',
      payload: { text: '未完成的流', seq: 1, done: false },
    }));
    expect(captured!.assistantStream.active).toBe(true);
    await act(async () => {
      captured!.selectSession('other-sess');
    });
    expect(captured!.assistantStream).toEqual({ text: '', active: false });
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

  // M174-C — 编辑 user 消息并重跑:成功刷新历史;失败抛错由视图兜底
  it('editAssistantMessage: 成功 → 调 API + 触发历史刷新', async () => {
    const { editAssistantMessage, fetchAssistantHistory } = await import('./api');
    renderProvider();
    await flush();
    const before = (fetchAssistantHistory as ReturnType<typeof vi.fn>).mock.calls.length;
    await act(async () => {
      await captured!.editAssistantMessage('asst-1', 'evt-1', '改后的文本');
    });
    expect(editAssistantMessage).toHaveBeenCalledWith('asst-1', 'evt-1', '改后的文本');
    const calls = (fetchAssistantHistory as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.length).toBeGreaterThan(before);
    expect(calls[calls.length - 1][0]).toBe('asst-1');
    expect(captured!.assistantBusy).toBe(false);
  });

  it('editAssistantMessage: API 失败 → 抛错 + busy 复位', async () => {
    const { editAssistantMessage } = await import('./api');
    (editAssistantMessage as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('HTTP 409: running'));
    renderProvider();
    await flush();
    await act(async () => {
      await expect(captured!.editAssistantMessage('asst-1', 'evt-1', 'x')).rejects.toThrow('409');
    });
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

// ---------- M167.4 — assistant 消息排队 / 自动 drain / 停止 ----------

describe('AppProvider · M167.4 assistant 消息排队与停止', () => {
  it('enqueueAssistantMessage: 非空入队(trim),空白不入队', async () => {
    renderProvider();
    await flush();
    // 无选中会话 → 自动发送 effect 不触发,队列保持
    act(() => captured!.enqueueAssistantMessage('  帮我写测试  '));
    expect(captured!.assistantQueue).toEqual(['帮我写测试']);
    act(() => captured!.enqueueAssistantMessage('   '));
    expect(captured!.assistantQueue).toEqual(['帮我写测试']);
  });

  it('removeAssistantQueued: 按 index 移除指定排队项', async () => {
    renderProvider();
    await flush();
    act(() => {
      captured!.enqueueAssistantMessage('a');
      captured!.enqueueAssistantMessage('b');
      captured!.enqueueAssistantMessage('c');
    });
    expect(captured!.assistantQueue).toEqual(['a', 'b', 'c']);
    act(() => captured!.removeAssistantQueued(1));
    expect(captured!.assistantQueue).toEqual(['a', 'c']);
  });

  it('非 busy + 有选中会话 → 入队即自动发送队首,发送后队列减一', async () => {
    const { sendAssistantMessage } = await import('./api');
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.createSession();
    });
    await flush();
    act(() => captured!.enqueueAssistantMessage('queued msg'));
    await flush();
    expect(sendAssistantMessage).toHaveBeenCalledWith('sess-new', { text: 'queued msg' });
    expect(captured!.assistantQueue).toEqual([]);
  });

  it('发送中(busy)入队不立即发送;上一条完成后依序 drain,不重复触发(防重入)', async () => {
    const { sendAssistantMessage } = await import('./api');
    const releases: Array<() => void> = [];
    (sendAssistantMessage as ReturnType<typeof vi.fn>).mockImplementation(
      () => new Promise<{ task_id: string }>((resolve) => releases.push(() => resolve({ task_id: 't' })))
    );
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.createSession();
    });
    await flush();
    // 手动发起第一条 → busy=true 且 API 挂起(模拟 running)
    await act(async () => {
      void captured!.sendAssistantMessage('第一条');
    });
    expect(captured!.assistantBusy).toBe(true);
    act(() => {
      captured!.enqueueAssistantMessage('排队1');
      captured!.enqueueAssistantMessage('排队2');
    });
    await flush();
    // busy 中:不进入发送通道
    expect((sendAssistantMessage as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
    expect(captured!.assistantQueue).toEqual(['排队1', '排队2']);
    // 第一条完成 → 自动 drain 队首
    await act(async () => {
      releases[0]();
    });
    await flush();
    let calls = (sendAssistantMessage as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.length).toBe(2);
    expect(calls[1][1]).toEqual({ text: '排队1' });
    expect(captured!.assistantQueue).toEqual(['排队2']);
    // 第二条完成 → 继续 drain 完,无重复触发
    await act(async () => {
      releases[1]();
    });
    await flush();
    calls = (sendAssistantMessage as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.length).toBe(3);
    expect(calls[2][1]).toEqual({ text: '排队2' });
    expect(captured!.assistantQueue).toEqual([]);
  });

  it('stopAssistantTask: 调 cancelTask(选中会话) + 清空队列 + 重置流式态', async () => {
    const { connectEvents, createSession, cancelTask, sendAssistantMessage } = await import('./api');
    const handlers: { onMessage?: (ev: any) => void } = {};
    (connectEvents as ReturnType<typeof vi.fn>).mockImplementationOnce((_sid: string, h: any) => {
      Object.assign(handlers, h);
      return { close: vi.fn(), send: vi.fn() };
    });
    (createSession as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ id: 's-stop', title: 't', status: 'idle', model: 'coder', mode: 'agent', created_at: '', updated_at: '' });
    // 发送永不 resolve → busy 一直保持(模拟 running 中点停止)
    (sendAssistantMessage as ReturnType<typeof vi.fn>).mockImplementation(() => new Promise(() => {}));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.createSession();
    });
    await flush();
    await act(async () => {
      void captured!.sendAssistantMessage('run');
    });
    act(() => captured!.enqueueAssistantMessage('排队中'));
    expect(captured!.assistantQueue).toEqual(['排队中']);
    act(() => handlers.onMessage?.({ id: null, session_id: 's-stop', type: 'token', agent: 'worker', payload: { text: '流式片段', seq: 1, done: false } }));
    expect(captured!.assistantStream.active).toBe(true);
    await act(async () => {
      await captured!.stopAssistantTask();
    });
    expect(cancelTask).toHaveBeenCalledWith('s-stop');
    expect(captured!.assistantQueue).toEqual([]);
    expect(captured!.assistantStream).toEqual({ text: '', active: false });
  });

  it('切换会话 → 清空排队(不跨会话携带)', async () => {
    const { sendAssistantMessage } = await import('./api');
    (sendAssistantMessage as ReturnType<typeof vi.fn>).mockImplementation(() => new Promise(() => {}));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.createSession();
    });
    await flush();
    await act(async () => {
      void captured!.sendAssistantMessage('run');
    });
    act(() => captured!.enqueueAssistantMessage('遗留'));
    expect(captured!.assistantQueue).toEqual(['遗留']);
    await act(async () => {
      captured!.selectSession('other-sess');
    });
    await flush();
    expect(captured!.assistantQueue).toEqual([]);
  });
});

// ---------- M187.2 — 已安排任务编辑 editTask ----------

describe('AppProvider · M187.2 任务编辑 editTask', () => {
  it('editTask: 成功 → 调 patchTask + loadTasks 回拉刷新列表', async () => {
    const { patchTask, fetchTasks } = await import('./api');
    (fetchTasks as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: 't1', title: '新标题', kind: 'cron', cron: '0 9 * * 1-5' },
    ]);
    renderProvider();
    await flush();
    const before = (fetchTasks as ReturnType<typeof vi.fn>).mock.calls.length;
    await act(async () => {
      await captured!.editTask('t1', { title: '新标题' });
    });
    expect(patchTask).toHaveBeenCalledWith('t1', { title: '新标题' });
    const calls = (fetchTasks as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.length).toBe(before + 1);
    // loadTasks 结果写入 tasks state
    expect(captured!.tasks).toHaveLength(1);
    expect(captured!.tasks[0].title).toBe('新标题');
  });

  it('editTask: API 失败 → 原样上抛(视图兜底)且不刷新列表', async () => {
    const { patchTask, fetchTasks } = await import('./api');
    (patchTask as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('HTTP 422: cron 非法'));
    renderProvider();
    await flush();
    const before = (fetchTasks as ReturnType<typeof vi.fn>).mock.calls.length;
    await act(async () => {
      await expect(captured!.editTask('t1', { cron: 'bad' })).rejects.toThrow('422');
    });
    expect(patchTask).toHaveBeenCalledWith('t1', { cron: 'bad' });
    expect((fetchTasks as ReturnType<typeof vi.fn>).mock.calls.length).toBe(before);
  });
});

// ---------- M176 — Goal 模式:goalActive 合成 busy / sendAssistantGoal / drain 分发 / history 重建 ----------

describe('AppProvider · M176 Goal 模式', () => {
  // 工具:渲染 + 注入会话 + 捕获 WS handlers(复用 WebSocket 事件流段的写法)
  async function connectGoalSession(sid = 'g-sess') {
    const { connectEvents, createSession } = await import('./api');
    const handlers: { onMessage?: (ev: any) => void } = {};
    (connectEvents as ReturnType<typeof vi.fn>).mockImplementationOnce((_sid: string, h: any) => {
      Object.assign(handlers, h);
      return { close: vi.fn(), send: vi.fn() };
    });
    (createSession as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: sid,
      title: 't',
      status: 'idle',
      model: 'coder',
      mode: 'agent',
      created_at: '',
      updated_at: '',
    });
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.createSession();
    });
    await flush();
    return handlers;
  }

  it('sendAssistantGoal: 空目标 → 不调 API', async () => {
    const { startAssistantGoal } = await import('./api');
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.sendAssistantGoal('   ');
    });
    expect(startAssistantGoal).not.toHaveBeenCalled();
  });

  it('sendAssistantGoal: 无会话 → 创建 assistant 会话 + POST goal(带 mode/model)', async () => {
    const { startAssistantGoal, createAssistantSession } = await import('./api');
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.sendAssistantGoal('修复所有 TS 错误');
    });
    expect(createAssistantSession).toHaveBeenCalledWith({ mode: 'agent' });
    expect(startAssistantGoal).toHaveBeenCalledWith('asst-new', {
      objective: '修复所有 TS 错误',
      mode: 'agent',
      model: 'coder',
    });
    expect(captured!.selectedSessionId).toBe('asst-new');
  });

  it('sendAssistantGoal: API 失败 → 设置 assistantError + 重抛 + busy 复位', async () => {
    const { startAssistantGoal } = await import('./api');
    (startAssistantGoal as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('409 busy'));
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.createSession();
    });
    await flush();
    await act(async () => {
      await expect(captured!.sendAssistantGoal('目标')).rejects.toThrow('409 busy');
    });
    expect(captured!.assistantError).toContain('409 busy');
    expect(captured!.assistantBusy).toBe(false);
    expect(captured!.composerBusy).toBe(false);
  });

  it('WS goal 事件:iter → goalActive/composerBusy=true;achieved → 复位', async () => {
    const h = await connectGoalSession();
    expect(captured!.goalActive).toBe(false);
    expect(captured!.composerBusy).toBe(false);
    act(() =>
      h.onMessage?.({
        id: 'g1',
        session_id: 'g-sess',
        type: 'goal',
        agent: 'system',
        payload: { phase: 'iter', objective: 'obj', iteration: 1, max_iterations: 5, prompt: 'obj' },
      })
    );
    expect(captured!.goalActive).toBe(true);
    expect(captured!.composerBusy).toBe(true);
    act(() =>
      h.onMessage?.({
        id: 'g2',
        session_id: 'g-sess',
        type: 'goal',
        agent: 'system',
        payload: { phase: 'achieved', objective: 'obj', iteration: 2, max_iterations: 5 },
      })
    );
    expect(captured!.goalActive).toBe(false);
    expect(captured!.composerBusy).toBe(false);
  });

  it('goalActive 合成 busy 阻塞 drain;终态后恢复 drain(M176 防轮间隙误发)', async () => {
    const { sendAssistantMessage } = await import('./api');
    const h = await connectGoalSession();
    // goal iter 事件 → goalActive=true(assistantBusy 为 false,模拟轮间隙)
    act(() =>
      h.onMessage?.({
        id: 'g1',
        session_id: 'g-sess',
        type: 'goal',
        agent: 'system',
        payload: { phase: 'iter', objective: 'obj', iteration: 1, max_iterations: 5, prompt: 'obj' },
      })
    );
    expect(captured!.composerBusy).toBe(true);
    // 入队消息 → 不 drain
    act(() => captured!.enqueueAssistantMessage('排队中'));
    await flush();
    expect(sendAssistantMessage).not.toHaveBeenCalled();
    expect(captured!.assistantQueue).toEqual(['排队中']);
    // exhausted 终态 → composerBusy 落下 → 自动 drain
    act(() =>
      h.onMessage?.({
        id: 'g2',
        session_id: 'g-sess',
        type: 'goal',
        agent: 'system',
        payload: { phase: 'exhausted', objective: 'obj', iteration: 5, max_iterations: 5, reason: 'max_iter' },
      })
    );
    await flush();
    expect(captured!.goalActive).toBe(false);
    expect(sendAssistantMessage).toHaveBeenCalledWith('g-sess', { text: '排队中' });
    expect(captured!.assistantQueue).toEqual([]);
  });

  it('其他会话的 goal 事件 → 不影响本会话 goalActive', async () => {
    const h = await connectGoalSession();
    act(() =>
      h.onMessage?.({
        id: 'g1',
        session_id: 'other-sess',
        type: 'goal',
        agent: 'system',
        payload: { phase: 'iter', objective: 'obj', iteration: 1, max_iterations: 5 },
      })
    );
    expect(captured!.goalActive).toBe(false);
  });

  it('drain 前缀分发:/goal 排队消息 → startAssistantGoal;普通消息 → sendAssistantMessage', async () => {
    const { startAssistantGoal, sendAssistantMessage } = await import('./api');
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.createSession();
    });
    await flush();
    act(() => {
      captured!.enqueueAssistantMessage('/goal 修复 bug');
      captured!.enqueueAssistantMessage('普通消息');
    });
    await flush();
    expect(startAssistantGoal).toHaveBeenCalledWith('sess-new', {
      objective: '修复 bug',
      mode: 'agent',
      model: 'coder',
    });
    expect(sendAssistantMessage).toHaveBeenCalledWith('sess-new', { text: '普通消息' });
    expect(captured!.assistantQueue).toEqual([]);
  });

  it('history 重建 goalActive:iter turn → true;切会话后 achieved turn → false', async () => {
    const { fetchAssistantHistory, createSession } = await import('./api');
    (createSession as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 'h-sess',
      title: 't',
      status: 'idle',
      model: 'coder',
      mode: 'agent',
      created_at: '',
      updated_at: '',
    });
    (fetchAssistantHistory as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { role: 'user', text: 'obj', tools: [], created_at: '2026-08-04T00:00:00Z' },
      {
        role: 'goal',
        tools: [],
        goal: { phase: 'iter', objective: 'obj', iteration: 2, max_iterations: 5, gap: '还差 3 处' },
        created_at: '2026-08-04T00:01:00Z',
      },
    ]);
    renderProvider();
    await flush();
    await act(async () => {
      await captured!.createSession();
    });
    await flush();
    expect(captured!.goalActive).toBe(true);
    expect(captured!.composerBusy).toBe(true);
    // 切到另一会话,历史含 achieved 终态 → goalActive=false
    (fetchAssistantHistory as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { role: 'user', text: 'obj', tools: [], created_at: '2026-08-04T00:00:00Z' },
      {
        role: 'goal',
        tools: [],
        goal: { phase: 'achieved', objective: 'obj', iteration: 3, max_iterations: 5 },
        created_at: '2026-08-04T00:02:00Z',
      },
    ]);
    await act(async () => {
      captured!.selectSession('sess-2');
    });
    await flush();
    expect(captured!.goalActive).toBe(false);
    expect(captured!.composerBusy).toBe(false);
  });
});
