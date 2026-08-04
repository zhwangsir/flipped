import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import { Sidebar } from './Sidebar';

// 与 Conversation.test.tsx 一致的打薄模式：mock store / 重型依赖 / 路由 / 主题
vi.mock('../store', () => ({ useApp: vi.fn() }));
vi.mock('../router', () => ({ navigate: vi.fn() }));
vi.mock('../hooks/useTheme', () => ({
  useTheme: vi.fn(() => ({ theme: 'dark', toggle: vi.fn() })),
}));
vi.mock('../api', () => ({ revealProject: vi.fn(async () => ({ ok: true })) }));

import { useApp } from '../store';
import { navigate } from '../router';
import { useTheme } from '../hooks/useTheme';
import { revealProject } from '../api';
import type { Session, ScheduledTask } from '../types';

const mockedUseApp = vi.mocked(useApp);
const mockedNavigate = vi.mocked(navigate);
const mockedUseTheme = vi.mocked(useTheme);
const mockedRevealProject = vi.mocked(revealProject);

// 构造一组复用会话：覆盖 chat / agent(项目内) / unassigned(无 project_name) / running 四类
function makeSession(partial: Partial<Session> & { id: string }): Session {
  return {
    title: partial.title ?? 'T',
    status: partial.status ?? 'idle',
    model: partial.model ?? 'coder',
    mode: partial.mode ?? 'agent',
    project: partial.project ?? null,
    project_name: partial.project_name ?? null,
    goal: partial.goal ?? null,
    created_at: partial.created_at ?? new Date(Date.now() - 60_000).toISOString(),
    updated_at: partial.updated_at ?? new Date(Date.now() - 60_000).toISOString(),
    id: partial.id,
  };
}

const baseState = {
  sessions: [] as Session[],
  selectedSessionId: null as string | null,
  selectSession: vi.fn(),
  createSession: vi.fn(async () => 'new-id'),
  deleteSession: vi.fn(async () => {}),
  setPaletteOpen: vi.fn(),
  setSettingsOpen: vi.fn(),
  setPluginsOpen: vi.fn(),
  setFactoryOpen: vi.fn(),
  projectContext: null,
  projects: [] as { name: string; host: string; sandbox: string }[],
  openProject: vi.fn(async () => ({})),
  // M178.2 — 已安排任务视图
  tasks: [] as ScheduledTask[],
  loadTasks: vi.fn(async () => {}),
  addTask: vi.fn(async () => {}),
  removeTask: vi.fn(async () => {}),
  toggleTaskEnabled: vi.fn(async () => {}),
};

// M178.2 — 构造已安排任务
function makeTask(partial: Partial<ScheduledTask> & { id: string }): ScheduledTask {
  return {
    title: partial.title ?? '任务',
    prompt: partial.prompt ?? '做点事',
    mode: partial.mode ?? 'agent',
    model: partial.model ?? 'coder',
    kind: partial.kind ?? 'once',
    run_at: partial.run_at ?? null,
    every_minutes: partial.every_minutes ?? null,
    enabled: partial.enabled ?? true,
    next_run_at: partial.next_run_at ?? null,
    last_run_at: partial.last_run_at ?? null,
    last_status: partial.last_status ?? null,
    last_session_id: partial.last_session_id ?? null,
    run_count: partial.run_count ?? 0,
    created_at: partial.created_at ?? new Date(Date.now() - 60_000).toISOString(),
    id: partial.id,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  mockedUseApp.mockReturnValue({ ...baseState } as never);
  mockedUseTheme.mockReturnValue({ theme: 'dark', toggle: vi.fn() });
});

describe('Sidebar — 会话列表渲染', () => {
  it('chat 会话渲染到「对话」分组', () => {
    const chat = makeSession({ id: 'c1', title: '闲聊一下', mode: 'chat' });
    mockedUseApp.mockReturnValue({ ...baseState, sessions: [chat] } as never);
    render(<Sidebar />);

    expect(screen.getByText('闲聊一下')).toBeTruthy();
    // 对话区空态不应出现
    expect(screen.queryByText('暂无聊天')).toBeNull();
  });

  it('agent 会话按 project_name 归到对应项目组', () => {
    const s = makeSession({
      id: 'a1',
      title: '修个 bug',
      mode: 'agent',
      project_name: 'alpha',
      project: '/p/alpha',
    });
    mockedUseApp.mockReturnValue({
      ...baseState,
      sessions: [s],
      projects: [{ name: 'alpha', host: '/p/alpha', sandbox: '/projects/alpha' }],
    } as never);
    render(<Sidebar />);

    expect(screen.getByText('alpha')).toBeTruthy();
    expect(screen.getByText('修个 bug')).toBeTruthy();
  });

  it('无 project_name 的 agent 会话归到「未分配」', () => {
    const s = makeSession({ id: 'u1', title: '游离任务', mode: 'agent', project_name: '' });
    mockedUseApp.mockReturnValue({ ...baseState, sessions: [s] } as never);
    render(<Sidebar />);

    expect(screen.getByText('未分配')).toBeTruthy();
    expect(screen.getByText('游离任务')).toBeTruthy();
  });

  it('空项目显示「暂无线程」占位', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      projects: [{ name: 'empty-proj', host: '/p/empty', sandbox: '/projects/empty' }],
    } as never);
    render(<Sidebar />);

    expect(screen.getByText('empty-proj')).toBeTruthy();
    expect(screen.getByText('暂无线程')).toBeTruthy();
  });

  it('无项目时显示引导提示', () => {
    render(<Sidebar />);
    expect(screen.getByText(/~\/projects 暂无项目/)).toBeTruthy();
  });
});

describe('Sidebar — 选中会话', () => {
  it('点击会话行调用 selectSession(id)', () => {
    const selectSession = vi.fn();
    const s = makeSession({ id: 'click-1', title: '点我', mode: 'chat' });
    mockedUseApp.mockReturnValue({
      ...baseState,
      sessions: [s],
      selectSession,
    } as never);
    render(<Sidebar />);

    fireEvent.click(screen.getByText('点我'));
    expect(selectSession).toHaveBeenCalledWith('click-1');
    expect(selectSession).toHaveBeenCalledTimes(1);
  });

  it('selectedSessionId 对应行带 active 类', () => {
    const s = makeSession({ id: 'sel-1', title: '被选中', mode: 'chat' });
    mockedUseApp.mockReturnValue({
      ...baseState,
      sessions: [s],
      selectedSessionId: 'sel-1',
    } as never);
    render(<Sidebar />);

    const row = screen.getByText('被选中').closest('.thread');
    expect(row?.classList.contains('active')).toBe(true);
  });
});

describe('Sidebar — 新对话按钮', () => {
  it('点击「新对话」调用 createSession', () => {
    const createSession = vi.fn(async () => 'sid');
    mockedUseApp.mockReturnValue({ ...baseState, createSession } as never);
    render(<Sidebar />);

    fireEvent.click(screen.getByText('新对话'));
    expect(createSession).toHaveBeenCalledWith('新对话');
    expect(createSession).toHaveBeenCalledTimes(1);
  });

  it('createSession 失败时静默不抛 unhandled rejection（M146）', async () => {
    const createSession = vi.fn(async () => {
      throw new Error('boom');
    });
    mockedUseApp.mockReturnValue({ ...baseState, createSession } as never);
    render(<Sidebar />);

    // 不应抛出
    fireEvent.click(screen.getByText('新对话'));
    // 给 .catch 一拍
    await new Promise((r) => setTimeout(r, 0));
    expect(createSession).toHaveBeenCalledTimes(1);
  });
});

describe('Sidebar — 删除会话', () => {
  it('点击删除按钮调用 deleteSession(id) 且不冒泡到 selectSession', () => {
    const deleteSession = vi.fn(async () => {});
    const selectSession = vi.fn();
    const s = makeSession({ id: 'del-1', title: '要删的', mode: 'chat' });
    mockedUseApp.mockReturnValue({
      ...baseState,
      sessions: [s],
      deleteSession,
      selectSession,
    } as never);
    render(<Sidebar />);

    const delBtn = screen.getByLabelText('删除对话');
    fireEvent.click(delBtn);

    expect(deleteSession).toHaveBeenCalledWith('del-1');
    // stopPropagation：不应触发外层 selectSession
    expect(selectSession).not.toHaveBeenCalled();
  });

  it('deleteSession 失败静默（M146：会话仍在列表，不假装删掉）', async () => {
    const deleteSession = vi.fn(async () => {
      throw new Error('forbidden');
    });
    const s = makeSession({ id: 'del-err', title: '删不掉', mode: 'chat' });
    mockedUseApp.mockReturnValue({
      ...baseState,
      sessions: [s],
      deleteSession,
    } as never);
    render(<Sidebar />);

    fireEvent.click(screen.getByLabelText('删除对话'));
    await new Promise((r) => setTimeout(r, 0));
    expect(deleteSession).toHaveBeenCalledTimes(1);
  });
});

describe('Sidebar — 项目分组（M146 ghost/unassigned）', () => {
  it('sessions 里出现但 projects 列表里没有的项目作为 ghost 组显示', () => {
    const ghost = makeSession({
      id: 'g1',
      title: '幽灵任务',
      mode: 'agent',
      project_name: 'ghost-proj',
      project: '/somewhere/ghost',
    });
    mockedUseApp.mockReturnValue({
      ...baseState,
      sessions: [ghost],
      projects: [], // projects 为空 → ghost-proj 不在列表里
    } as never);
    render(<Sidebar />);

    expect(screen.getByText('ghost-proj')).toBeTruthy();
    expect(screen.getByText('幽灵任务')).toBeTruthy();
  });

  it('点击项目主行：未激活时调用 openProject(host) 并切换折叠', () => {
    const openProject = vi.fn(async () => ({}));
    mockedUseApp.mockReturnValue({
      ...baseState,
      projects: [{ name: 'alpha', host: '/p/alpha', sandbox: '/projects/alpha' }],
      openProject,
    } as never);
    render(<Sidebar />);

    const mainBtn = screen.getByText('alpha').closest('button') as HTMLButtonElement;
    // 初始展开（aria-expanded=true），点一次折叠
    expect(mainBtn.getAttribute('aria-expanded')).toBe('true');
    fireEvent.click(mainBtn);
    expect(openProject).toHaveBeenCalledWith('/p/alpha');
    // 折叠后 aria-expanded=false
    expect(mainBtn.getAttribute('aria-expanded')).toBe('false');
  });

  it('已是活动项目时不重复调用 openProject', () => {
    const openProject = vi.fn(async () => ({}));
    mockedUseApp.mockReturnValue({
      ...baseState,
      projectContext: { project: 'alpha', path: '/p/alpha', sandbox: null, branch: 'main', mode: 'agent' },
      projects: [{ name: 'alpha', host: '/p/alpha', sandbox: '/projects/alpha' }],
      openProject,
    } as never);
    render(<Sidebar />);

    const mainBtn = screen.getByText('alpha').closest('button') as HTMLButtonElement;
    fireEvent.click(mainBtn);
    // isActive → 跳过 openProject
    expect(openProject).not.toHaveBeenCalled();
  });

  it('项目「在此项目新建对话」按钮：激活项目后 createSession + 展开', async () => {
    const openProject = vi.fn(async () => ({}));
    const createSession = vi.fn(async () => 'ns-id');
    mockedUseApp.mockReturnValue({
      ...baseState,
      projects: [{ name: 'beta', host: '/p/beta', sandbox: '/projects/beta' }],
      openProject,
      createSession,
    } as never);
    render(<Sidebar />);

    const newBtn = screen.getByTitle('在此项目新建对话');
    fireEvent.click(newBtn);

    await vi.waitFor(() => expect(openProject).toHaveBeenCalledWith('/p/beta'));
    await vi.waitFor(() => expect(createSession).toHaveBeenCalledWith('新对话'));
  });

  it('项目「在此项目新建对话」按钮：折叠态下点击会展开（expand 分支）', async () => {
    const createSession = vi.fn(async () => 'ns-id');
    mockedUseApp.mockReturnValue({
      ...baseState,
      projects: [{ name: 'beta', host: '/p/beta', sandbox: '/projects/beta' }],
      createSession,
    } as never);
    render(<Sidebar />);

    const mainBtn = screen.getByText('beta').closest('button') as HTMLButtonElement;
    // 折叠（aria-expanded 从 true → false）
    fireEvent.click(mainBtn);
    expect(mainBtn.getAttribute('aria-expanded')).toBe('false');

    // 点「在此项目新建对话」应触发 expand：aria-expanded 回到 true
    fireEvent.click(screen.getByTitle('在此项目新建对话'));
    await vi.waitFor(() => expect(createSession).toHaveBeenCalled());
    expect(mainBtn.getAttribute('aria-expanded')).toBe('true');
  });

  it('项目「更多」菜单展开后含「在 Finder 中显示」，点击调用 revealProject', async () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      projects: [{ name: 'alpha', host: '/p/alpha', sandbox: '/projects/alpha' }],
    } as never);
    render(<Sidebar />);

    const moreBtn = screen.getByTitle('更多');
    expect(screen.queryByText('在 Finder 中显示')).toBeNull();
    fireEvent.click(moreBtn);

    const item = await screen.findByText('在 Finder 中显示');
    fireEvent.click(item);

    await vi.waitFor(() => expect(mockedRevealProject).toHaveBeenCalledTimes(1));
    // 点击后菜单关闭
    expect(screen.queryByText('在 Finder 中显示')).toBeNull();
  });

  it('Escape 关闭「更多」菜单', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      projects: [{ name: 'alpha', host: '/p/alpha', sandbox: '/projects/alpha' }],
    } as never);
    render(<Sidebar />);

    fireEvent.click(screen.getByTitle('更多'));
    expect(screen.getByText('在 Finder 中显示')).toBeTruthy();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByText('在 Finder 中显示')).toBeNull();
  });

  it('点击菜单外区域关闭「更多」菜单', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      projects: [{ name: 'alpha', host: '/p/alpha', sandbox: '/projects/alpha' }],
    } as never);
    render(<Sidebar />);

    fireEvent.click(screen.getByTitle('更多'));
    expect(screen.getByText('在 Finder 中显示')).toBeTruthy();

    // 模拟点击外部
    fireEvent.mouseDown(document.body);
    expect(screen.queryByText('在 Finder 中显示')).toBeNull();
  });
});

describe('Sidebar — 导航视图切换（threads / scheduled）', () => {
  it('默认显示「项目」分组标签（threads 视图）', () => {
    render(<Sidebar />);
    expect(screen.getByText('项目')).toBeTruthy();
    expect(screen.getByText('对话')).toBeTruthy();
  });

  it('点击「已安排」切换到 scheduled 视图并显示空态', () => {
    render(<Sidebar />);
    fireEvent.click(screen.getByText('已安排'));

    expect(screen.getByText('暂无已安排任务')).toBeTruthy();
    // threads 视图的分组标签消失
    expect(screen.queryByText('项目')).toBeNull();
    expect(screen.queryByText('对话')).toBeNull();
  });

  it('「已安排」按钮再次点击不切回（单态切换：threads 只能通过新对话回切）', () => {
    render(<Sidebar />);
    const btn = screen.getByText('已安排');
    fireEvent.click(btn);
    expect(screen.getByText('暂无已安排任务')).toBeTruthy();

    // 再点一次仍然在 scheduled
    fireEvent.click(btn);
    expect(screen.getByText('暂无已安排任务')).toBeTruthy();
  });

  it('点击「新对话」回切到 threads 视图', () => {
    mockedUseApp.mockReturnValue({ ...baseState, createSession: vi.fn(async () => 'n') } as never);
    render(<Sidebar />);

    // 先切到 scheduled
    fireEvent.click(screen.getByText('已安排'));
    expect(screen.getByText('暂无已安排任务')).toBeTruthy();

    // 点新对话回到 threads
    fireEvent.click(screen.getByText('新对话'));
    expect(screen.getByText('项目')).toBeTruthy();
    expect(screen.getByText('对话')).toBeTruthy();
  });
});

describe('Sidebar — 运行中线程看板', () => {
  it('有 running 会话时显示「N 个线程并行运行中」看板', () => {
    const r1 = makeSession({ id: 'r1', title: '跑着1', mode: 'agent', status: 'running', project_name: 'alpha' });
    const r2 = makeSession({ id: 'r2', title: '跑着2', mode: 'agent', status: 'running', project_name: 'beta' });
    mockedUseApp.mockReturnValue({ ...baseState, sessions: [r1, r2] } as never);
    render(<Sidebar />);

    const board = screen.getByTestId('running-board');
    expect(board).toBeTruthy();
    expect(within(board).getByText(/2 个线程并行运行中/)).toBeTruthy();
    expect(within(board).getByText('跑着1')).toBeTruthy();
    expect(within(board).getByText('跑着2')).toBeTruthy();
  });

  it('无 running 会话时不渲染看板', () => {
    const idle = makeSession({ id: 'i1', title: '空闲', mode: 'chat', status: 'idle' });
    mockedUseApp.mockReturnValue({ ...baseState, sessions: [idle] } as never);
    render(<Sidebar />);

    expect(screen.queryByTestId('running-board')).toBeNull();
  });

  it('点击 running 看板的行调用 selectSession', () => {
    const selectSession = vi.fn();
    const r1 = makeSession({ id: 'r-click', title: '跑着点', mode: 'agent', status: 'running' });
    mockedUseApp.mockReturnValue({
      ...baseState,
      sessions: [r1],
      selectSession,
    } as never);
    render(<Sidebar />);

    const board = screen.getByTestId('running-board');
    fireEvent.click(within(board).getByText('跑着点'));
    expect(selectSession).toHaveBeenCalledWith('r-click');
  });
});

describe('Sidebar — 顶部导航按钮', () => {
  it('搜索按钮调用 setPaletteOpen(true)', () => {
    const setPaletteOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setPaletteOpen } as never);
    render(<Sidebar />);

    fireEvent.click(screen.getByText('搜索'));
    expect(setPaletteOpen).toHaveBeenCalledWith(true);
  });

  it('插件按钮调用 setPluginsOpen(true)', () => {
    const setPluginsOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setPluginsOpen } as never);
    render(<Sidebar />);

    fireEvent.click(screen.getByText('插件'));
    expect(setPluginsOpen).toHaveBeenCalledWith(true);
  });

  it('工厂按钮调用 navigate(factory) + setFactoryOpen(true)', () => {
    const setFactoryOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setFactoryOpen } as never);
    render(<Sidebar />);

    fireEvent.click(screen.getByText('工厂'));
    expect(mockedNavigate).toHaveBeenCalledWith('factory');
    expect(setFactoryOpen).toHaveBeenCalledWith(true);
  });
});

describe('Sidebar — 底部设置区', () => {
  it('设置按钮调用 setSettingsOpen(true)', () => {
    const setSettingsOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setSettingsOpen } as never);
    render(<Sidebar />);

    fireEvent.click(screen.getByTitle('设置'));
    expect(setSettingsOpen).toHaveBeenCalledWith(true);
  });

  it('主题按钮调用 useTheme().toggle', () => {
    const toggle = vi.fn();
    mockedUseTheme.mockReturnValue({ theme: 'dark', toggle });
    render(<Sidebar />);

    fireEvent.click(screen.getByLabelText('切换到亮色'));
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  it('亮色主题下按钮 aria-label 切换文案', () => {
    const toggle = vi.fn();
    mockedUseTheme.mockReturnValue({ theme: 'light', toggle });
    render(<Sidebar />);

    expect(screen.getByLabelText('切换到暗色')).toBeTruthy();
  });

  it('显示「本地模式」标识', () => {
    render(<Sidebar />);
    expect(screen.getByText('本地模式')).toBeTruthy();
  });
});

describe('Sidebar — 键盘可访问性', () => {
  it('会话行 Enter 键触发 selectSession', () => {
    const selectSession = vi.fn();
    const s = makeSession({ id: 'kb-1', title: '键盘行', mode: 'chat' });
    mockedUseApp.mockReturnValue({
      ...baseState,
      sessions: [s],
      selectSession,
    } as never);
    render(<Sidebar />);

    const row = screen.getByText('键盘行').closest('.thread') as HTMLElement;
    fireEvent.keyDown(row, { key: 'Enter' });
    expect(selectSession).toHaveBeenCalledWith('kb-1');
  });

  it('会话行空格键触发 selectSession', () => {
    const selectSession = vi.fn();
    const s = makeSession({ id: 'kb-2', title: '空格行', mode: 'chat' });
    mockedUseApp.mockReturnValue({
      ...baseState,
      sessions: [s],
      selectSession,
    } as never);
    render(<Sidebar />);

    const row = screen.getByText('空格行').closest('.thread') as HTMLElement;
    fireEvent.keyDown(row, { key: ' ' });
    expect(selectSession).toHaveBeenCalledWith('kb-2');
  });

  it('其他键不触发 selectSession', () => {
    const selectSession = vi.fn();
    const s = makeSession({ id: 'kb-3', title: '其他键', mode: 'chat' });
    mockedUseApp.mockReturnValue({
      ...baseState,
      sessions: [s],
      selectSession,
    } as never);
    render(<Sidebar />);

    const row = screen.getByText('其他键').closest('.thread') as HTMLElement;
    fireEvent.keyDown(row, { key: 'a' });
    expect(selectSession).not.toHaveBeenCalled();
  });
});

// M178.2 — 已安排任务视图（ScheduledView，经 Sidebar「已安排」导航驱动）
describe('Sidebar — 已安排任务视图 (M178.2)', () => {
  const openScheduled = () => fireEvent.click(screen.getByText('已安排'));

  it('空态渲染：无任务时显示原文案 + 新建任务按钮，进视图调 loadTasks', () => {
    const loadTasks = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({ ...baseState, loadTasks } as never);
    render(<Sidebar />);
    openScheduled();

    expect(screen.getByText('暂无已安排任务')).toBeTruthy();
    expect(screen.getByText('在此处规划的任务将自动出现在这里')).toBeTruthy();
    expect(screen.getByText('新建任务')).toBeTruthy();
    expect(loadTasks).toHaveBeenCalled();
  });

  it('任务卡渲染：kind/mode 徽标 + 下次运行相对时间 + 已运行次数 + 状态点', () => {
    const t = makeTask({
      id: 't1',
      title: '每日巡检',
      kind: 'interval',
      every_minutes: 30,
      mode: 'agent',
      next_run_at: new Date(Date.now() + 90 * 60_000).toISOString(),
      last_status: 'done',
      run_count: 7,
    });
    mockedUseApp.mockReturnValue({ ...baseState, tasks: [t] } as never);
    render(<Sidebar />);
    openScheduled();

    expect(screen.getByText('每日巡检')).toBeTruthy();
    expect(screen.getByText('每 30 分钟')).toBeTruthy();
    expect(screen.getByText('agent')).toBeTruthy();
    expect(screen.getByText('下次：1 小时后')).toBeTruthy();
    expect(screen.getByText('已运行 7 次')).toBeTruthy();
    // done → 绿点（dot ok 变体）
    expect(document.querySelector('.sched-meta .dot.ok')).not.toBeNull();
  });

  it('停用任务显示「已停用」而非相对时间', () => {
    const t = makeTask({ id: 't-off', title: '停掉的', enabled: false, next_run_at: null });
    mockedUseApp.mockReturnValue({ ...baseState, tasks: [t] } as never);
    render(<Sidebar />);
    openScheduled();

    expect(screen.getByText('下次：已停用')).toBeTruthy();
    // 停用任务的操作按钮文案为「启用」
    expect(screen.getByText('启用')).toBeTruthy();
  });

  it('新建表单 once 路径：提交调 addTask 带 kind=once 与 ISO run_at，成功后收起', async () => {
    const addTask = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({ ...baseState, addTask } as never);
    render(<Sidebar />);
    openScheduled();
    fireEvent.click(screen.getByText('新建任务'));

    fireEvent.change(screen.getByLabelText('任务标题'), { target: { value: '上线前检查' } });
    fireEvent.change(screen.getByLabelText('任务内容'), { target: { value: '跑全量测试并汇总' } });
    fireEvent.change(screen.getByLabelText('运行时间'), { target: { value: '2026-08-06T10:30' } });
    fireEvent.click(screen.getByText('创建'));

    await vi.waitFor(() => expect(addTask).toHaveBeenCalledTimes(1));
    expect(addTask).toHaveBeenCalledWith({
      title: '上线前检查',
      prompt: '跑全量测试并汇总',
      mode: 'chat',
      kind: 'once',
      run_at: new Date('2026-08-06T10:30').toISOString(),
      every_minutes: null,
    });
    // 成功后表单收起
    await vi.waitFor(() => expect(screen.queryByLabelText('任务标题')).toBeNull());
  });

  it('新建表单 interval 路径：切「每隔 N 分钟」提交带 every_minutes', async () => {
    const addTask = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({ ...baseState, addTask } as never);
    render(<Sidebar />);
    openScheduled();
    fireEvent.click(screen.getByText('新建任务'));

    fireEvent.change(screen.getByLabelText('任务标题'), { target: { value: '定时同步' } });
    fireEvent.change(screen.getByLabelText('任务内容'), { target: { value: '同步知识库' } });
    fireEvent.change(screen.getByLabelText('任务类型'), { target: { value: 'interval' } });
    fireEvent.change(screen.getByLabelText('间隔分钟'), { target: { value: '45' } });
    fireEvent.change(screen.getByLabelText('运行模式'), { target: { value: 'agent' } });
    fireEvent.click(screen.getByText('创建'));

    await vi.waitFor(() => expect(addTask).toHaveBeenCalledTimes(1));
    expect(addTask).toHaveBeenCalledWith({
      title: '定时同步',
      prompt: '同步知识库',
      mode: 'agent',
      kind: 'interval',
      run_at: null,
      every_minutes: 45,
    });
  });

  it('表单校验：once 未选时间不提交并红字提示', () => {
    const addTask = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({ ...baseState, addTask } as never);
    render(<Sidebar />);
    openScheduled();
    fireEvent.click(screen.getByText('新建任务'));

    fireEvent.change(screen.getByLabelText('任务标题'), { target: { value: '缺时间' } });
    fireEvent.change(screen.getByLabelText('任务内容'), { target: { value: 'x' } });
    fireEvent.click(screen.getByText('创建'));

    expect(addTask).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toContain('请选择运行时间');
  });

  it('addTask 失败时表单下方红字提示且不收起', async () => {
    const addTask = vi.fn(async () => {
      throw new Error('HTTP 422: bad');
    });
    mockedUseApp.mockReturnValue({ ...baseState, addTask } as never);
    render(<Sidebar />);
    openScheduled();
    fireEvent.click(screen.getByText('新建任务'));

    fireEvent.change(screen.getByLabelText('任务标题'), { target: { value: '会失败' } });
    fireEvent.change(screen.getByLabelText('任务内容'), { target: { value: 'x' } });
    fireEvent.change(screen.getByLabelText('任务类型'), { target: { value: 'interval' } });
    fireEvent.click(screen.getByText('创建'));

    await vi.waitFor(() =>
      expect(screen.getByRole('alert').textContent).toContain('HTTP 422')
    );
    // 表单仍在
    expect(screen.getByLabelText('任务标题')).toBeTruthy();
  });

  it('启用/停用切换按钮调 toggleTaskEnabled(id, !enabled)', () => {
    const toggleTaskEnabled = vi.fn(async () => {});
    const t = makeTask({ id: 't-tog', title: '切换我', enabled: true });
    mockedUseApp.mockReturnValue({ ...baseState, tasks: [t], toggleTaskEnabled } as never);
    render(<Sidebar />);
    openScheduled();

    fireEvent.click(screen.getByText('停用'));
    expect(toggleTaskEnabled).toHaveBeenCalledWith('t-tog', false);
  });

  it('删除需二次确认：首次点击出现确认文案，不调 removeTask；取消后复原', () => {
    const removeTask = vi.fn(async () => {});
    const t = makeTask({ id: 't-del', title: '删除我' });
    mockedUseApp.mockReturnValue({ ...baseState, tasks: [t], removeTask } as never);
    render(<Sidebar />);
    openScheduled();

    fireEvent.click(screen.getByText('删除'));
    expect(screen.getByText('确认删除？')).toBeTruthy();
    expect(removeTask).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText('取消'));
    expect(screen.queryByText('确认删除？')).toBeNull();
    expect(removeTask).not.toHaveBeenCalled();
  });

  it('确认删除后调 removeTask(id)', async () => {
    const removeTask = vi.fn(async () => {});
    const t = makeTask({ id: 't-del2', title: '确认删我' });
    mockedUseApp.mockReturnValue({ ...baseState, tasks: [t], removeTask } as never);
    render(<Sidebar />);
    openScheduled();

    fireEvent.click(screen.getByText('删除'));
    fireEvent.click(screen.getByText('确认'));
    await vi.waitFor(() => expect(removeTask).toHaveBeenCalledWith('t-del2'));
  });

  it('last_session_id 非空时点标题调 selectSession(last_session_id)', () => {
    const selectSession = vi.fn();
    const t = makeTask({ id: 't-link', title: '有会话', last_session_id: 'sess-9' });
    mockedUseApp.mockReturnValue({ ...baseState, tasks: [t], selectSession } as never);
    render(<Sidebar />);
    openScheduled();

    fireEvent.click(screen.getByTitle('打开上次会话'));
    expect(selectSession).toHaveBeenCalledWith('sess-9');
  });
});
