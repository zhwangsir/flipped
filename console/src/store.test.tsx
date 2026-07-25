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
