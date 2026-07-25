import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { TopBar } from './TopBar';

vi.mock('../store', () => ({ useApp: vi.fn() }));

import { useApp } from '../store';

const mockedUseApp = vi.mocked(useApp);

// TopBar 仅消费 store 的 9 个字段。
const baseState = {
  toggleSidebar: vi.fn(),
  toggleContext: vi.fn(),
  selectedSessionId: null as string | null,
  sessions: [] as import('../types').Session[],
  connection: 'idle' as 'idle' | 'connecting' | 'connected' | 'error',
  metrics: null as import('../types').Metrics | null,
  selectedMode: 'agent',
  setMobileSidebarOpen: vi.fn(),
  setMobilePanelOpen: vi.fn(),
};

// jsdom 不实现 window.matchMedia,TopBar 用它判断桌面/移动端,必须 stub。
beforeEach(() => {
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })));
  mockedUseApp.mockReturnValue({ ...baseState } as never);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe('TopBar — 标题与模式', () => {
  it('无选中会话时显示品牌 flipped', () => {
    mockedUseApp.mockReturnValue({ ...baseState, selectedSessionId: null, sessions: [] } as never);
    render(<TopBar />);
    expect(screen.getByText('flipped')).toBeInTheDocument();
  });

  it('有选中会话时显示会话标题,不显示品牌', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      selectedSessionId: 's1',
      sessions: [
        { id: 's1', title: '重构认证模块', status: 'idle', model: 'coder', created_at: '', updated_at: '' },
      ],
    } as never);
    render(<TopBar />);
    expect(screen.getByText('重构认证模块')).toBeInTheDocument();
    expect(screen.queryByText('flipped')).toBeNull();
  });

  it('selectedSessionId 指向不存在的会话时回退到品牌 flipped', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      selectedSessionId: 'missing',
      sessions: [{ id: 's1', title: '其他任务', status: 'idle', model: 'coder', created_at: '', updated_at: '' }],
    } as never);
    render(<TopBar />);
    expect(screen.getByText('flipped')).toBeInTheDocument();
  });

  it('显示当前模式标签(auto→自主)', () => {
    mockedUseApp.mockReturnValue({ ...baseState, selectedMode: 'auto' } as never);
    render(<TopBar />);
    expect(screen.getByText('自主')).toBeInTheDocument();
  });

  it('显示当前模式标签(plan→规划)', () => {
    mockedUseApp.mockReturnValue({ ...baseState, selectedMode: 'plan' } as never);
    render(<TopBar />);
    expect(screen.getByText('规划')).toBeInTheDocument();
  });

  it('显示当前模式标签(chat→对话)', () => {
    mockedUseApp.mockReturnValue({ ...baseState, selectedMode: 'chat' } as never);
    render(<TopBar />);
    expect(screen.getByText('对话')).toBeInTheDocument();
  });

  it('未知模式原样显示(selectedMode 值)', () => {
    mockedUseApp.mockReturnValue({ ...baseState, selectedMode: 'custom-x' } as never);
    render(<TopBar />);
    expect(screen.getByText('custom-x')).toBeInTheDocument();
  });
});

describe('TopBar — 连接状态', () => {
  it('idle 状态:dot 含 idle class + aria-label "连接状态: 未连接"', () => {
    mockedUseApp.mockReturnValue({ ...baseState, connection: 'idle' } as never);
    render(<TopBar />);
    const dot = screen.getByRole('status');
    expect(dot).toHaveAttribute('aria-label', '连接状态: 未连接');
    expect(dot.classList.contains('idle')).toBe(true);
    expect(dot.classList.contains('dot')).toBe(true);
  });

  it('connecting 状态:aria-label "连接状态: 连接中"', () => {
    mockedUseApp.mockReturnValue({ ...baseState, connection: 'connecting' } as never);
    render(<TopBar />);
    expect(screen.getByRole('status')).toHaveAttribute('aria-label', '连接状态: 连接中');
  });

  it('connected 状态:aria-label "连接状态: 已连接"', () => {
    mockedUseApp.mockReturnValue({ ...baseState, connection: 'connected' } as never);
    render(<TopBar />);
    expect(screen.getByRole('status')).toHaveAttribute('aria-label', '连接状态: 已连接');
  });

  it('error 状态:aria-label "连接状态: 连接错误"', () => {
    mockedUseApp.mockReturnValue({ ...baseState, connection: 'error' } as never);
    render(<TopBar />);
    expect(screen.getByRole('status')).toHaveAttribute('aria-label', '连接状态: 连接错误');
  });
});

describe('TopBar — 桌面端按钮(默认 matchMedia.matches=false)', () => {
  it('点击侧栏折叠按钮触发 toggleSidebar,不触发 setMobileSidebarOpen', () => {
    const toggleSidebar = vi.fn();
    const setMobileSidebarOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, toggleSidebar, setMobileSidebarOpen } as never);
    render(<TopBar />);
    fireEvent.click(screen.getByLabelText('折叠侧栏'));
    expect(toggleSidebar).toHaveBeenCalledTimes(1);
    expect(setMobileSidebarOpen).not.toHaveBeenCalled();
  });

  it('点击上下文面板按钮触发 toggleContext,不触发 setMobilePanelOpen', () => {
    const toggleContext = vi.fn();
    const setMobilePanelOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, toggleContext, setMobilePanelOpen } as never);
    render(<TopBar />);
    fireEvent.click(screen.getByLabelText('切换上下文面板'));
    expect(toggleContext).toHaveBeenCalledTimes(1);
    expect(setMobilePanelOpen).not.toHaveBeenCalled();
  });
});

describe('TopBar — 移动端按钮(matchMedia.matches=true)', () => {
  it('点击侧栏按钮触发 setMobileSidebarOpen(true),不触发 toggleSidebar', () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })));
    const toggleSidebar = vi.fn();
    const setMobileSidebarOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, toggleSidebar, setMobileSidebarOpen } as never);
    render(<TopBar />);
    fireEvent.click(screen.getByLabelText('折叠侧栏'));
    expect(setMobileSidebarOpen).toHaveBeenCalledWith(true);
    expect(toggleSidebar).not.toHaveBeenCalled();
  });

  it('点击上下文面板按钮触发 setMobilePanelOpen(true),不触发 toggleContext', () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })));
    const toggleContext = vi.fn();
    const setMobilePanelOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, toggleContext, setMobilePanelOpen } as never);
    render(<TopBar />);
    fireEvent.click(screen.getByLabelText('切换上下文面板'));
    expect(setMobilePanelOpen).toHaveBeenCalledWith(true);
    expect(toggleContext).not.toHaveBeenCalled();
  });
});

describe('TopBar — 用量芯片', () => {
  it('无 metrics 时不渲染用量芯片', () => {
    mockedUseApp.mockReturnValue({ ...baseState, metrics: null } as never);
    render(<TopBar />);
    expect(screen.queryByTestId('usage-chip')).toBeNull();
  });

  it('metrics.llm.total_calls=0 时不渲染用量芯片', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      metrics: { llm: { total_calls: 0, total_tokens: 0 } } as never,
    } as never);
    render(<TopBar />);
    expect(screen.queryByTestId('usage-chip')).toBeNull();
  });

  it('有调用时渲染用量芯片并显示总 token(formatTokens 2000→2.0k)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      metrics: {
        llm: {
          total_calls: 5,
          errors: 1,
          prompt_tokens: 1200,
          completion_tokens: 800,
          total_tokens: 2000,
          avg_latency_ms: 350,
        },
      } as never,
    } as never);
    render(<TopBar />);
    const chip = screen.getByTestId('usage-chip');
    expect(chip.textContent).toContain('2.0k');
  });

  it('用量芯片 title 包含调用次数与错误数', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      metrics: {
        llm: {
          total_calls: 7,
          errors: 2,
          prompt_tokens: 100,
          completion_tokens: 200,
          total_tokens: 300,
          avg_latency_ms: 120,
        },
      } as never,
    } as never);
    render(<TopBar />);
    const chip = screen.getByTestId('usage-chip');
    expect(chip.getAttribute('title')).toContain('调用 7 次');
    expect(chip.getAttribute('title')).toContain('错误 2');
  });
});
