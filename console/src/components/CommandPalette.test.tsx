import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { CommandPalette } from './CommandPalette';

// jsdom 未实现 scrollIntoView,补桩避免 useEffect 报错
if (typeof Element !== 'undefined' && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn();
}

vi.mock('../store', () => ({ useApp: vi.fn() }));
vi.mock('../hooks/useTheme', () => ({
  useTheme: vi.fn(() => ({ theme: 'dark', toggle: vi.fn() })),
}));

import { useApp } from '../store';
import { useTheme } from '../hooks/useTheme';
import type { Session } from '../types';

const mockedUseApp = vi.mocked(useApp);
const mockedUseTheme = vi.mocked(useTheme);

function makeSession(partial: Partial<Session> & { id: string }): Session {
  return {
    title: partial.title ?? 'T',
    status: partial.status ?? 'idle',
    model: partial.model ?? 'coder',
    mode: partial.mode ?? 'agent',
    project: partial.project ?? null,
    project_name: partial.project_name ?? null,
    goal: partial.goal ?? null,
    created_at: partial.created_at ?? new Date().toISOString(),
    updated_at: partial.updated_at ?? new Date().toISOString(),
    id: partial.id,
  };
}

const baseState = {
  paletteOpen: true,
  setPaletteOpen: vi.fn(),
  sessions: [] as Session[],
  selectSession: vi.fn(),
  createSession: vi.fn(async () => 'new-id'),
  openContext: vi.fn(),
  setSettingsOpen: vi.fn(),
  setPluginsOpen: vi.fn(),
  toggleSidebar: vi.fn(),
  toggleTerminal: vi.fn(),
  toggleContext: vi.fn(),
  projectContext: null as { project: string | null } | null,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  mockedUseApp.mockReturnValue({ ...baseState } as never);
  mockedUseTheme.mockReturnValue({ theme: 'dark', toggle: vi.fn() });
});

describe('CommandPalette — 渲染与基本交互', () => {
  it('paletteOpen=false 时返回 null', () => {
    mockedUseApp.mockReturnValue({ ...baseState, paletteOpen: false } as never);
    const { container } = render(<CommandPalette />);
    expect(container.firstChild).toBeNull();
  });

  it('paletteOpen=true 时渲染面板', () => {
    render(<CommandPalette />);
    expect(screen.getByTestId('command-palette')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('搜索聊天或运行命令')).toBeInTheDocument();
  });

  it('默认渲染所有分组: 聊天/推荐/面板/配置/切换项目', () => {
    render(<CommandPalette />);
    expect(screen.getByText('推荐')).toBeInTheDocument();
    expect(screen.getByText('面板')).toBeInTheDocument();
    expect(screen.getByText('配置')).toBeInTheDocument();
    expect(screen.getByText('切换项目')).toBeInTheDocument();
    // 聊天分组只有 sessions 非空时才显示
  });

  it('推荐分组包含「新对话」「搜索文件」「设置」', () => {
    render(<CommandPalette />);
    expect(screen.getByText('新对话')).toBeInTheDocument();
    expect(screen.getByText('搜索文件')).toBeInTheDocument();
    expect(screen.getByText('设置')).toBeInTheDocument();
  });

  it('面板分组包含「切换边栏」「切换底部面板」「打开浏览器标签页」等', () => {
    render(<CommandPalette />);
    expect(screen.getByText('切换边栏')).toBeInTheDocument();
    expect(screen.getByText('切换底部面板')).toBeInTheDocument();
    expect(screen.getByText('打开浏览器标签页')).toBeInTheDocument();
    expect(screen.getByText('打开审查选项卡')).toBeInTheDocument();
    expect(screen.getByText('打开文件')).toBeInTheDocument();
    expect(screen.getByText('切换侧边面板')).toBeInTheDocument();
  });

  it('配置分组: 深色主题时显示「切换到浅色主题」', () => {
    mockedUseTheme.mockReturnValue({ theme: 'dark', toggle: vi.fn() });
    render(<CommandPalette />);
    expect(screen.getByText('切换到浅色主题')).toBeInTheDocument();
  });

  it('配置分组: 浅色主题时显示「切换到深色主题」', () => {
    mockedUseTheme.mockReturnValue({ theme: 'light', toggle: vi.fn() });
    render(<CommandPalette />);
    expect(screen.getByText('切换到深色主题')).toBeInTheDocument();
  });

  it('无 projectContext 时项目名默认 flipped', () => {
    render(<CommandPalette />);
    // 切换项目分组下显示项目名
    expect(screen.getByText('flipped')).toBeInTheDocument();
  });

  it('有 projectContext 时使用其 project 名', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      projectContext: { project: 'my-proj' },
    } as never);
    render(<CommandPalette />);
    expect(screen.getByText('my-proj')).toBeInTheDocument();
  });
});

describe('CommandPalette — 会话列表', () => {
  it('sessions 渲染到「聊天」分组,前 9 个有 ⌘N 快捷键', () => {
    const sessions = Array.from({ length: 9 }, (_, i) =>
      makeSession({ id: `s${i}`, title: `会话${i}`, mode: 'chat' }),
    );
    mockedUseApp.mockReturnValue({ ...baseState, sessions } as never);
    render(<CommandPalette />);
    expect(screen.getByText('聊天')).toBeInTheDocument();
    expect(screen.getByText('会话0')).toBeInTheDocument();
    expect(screen.getByText('会话8')).toBeInTheDocument();
    // ⌘1 快捷键
    expect(screen.getByText('⌘1')).toBeInTheDocument();
    expect(screen.getByText('⌘9')).toBeInTheDocument();
  });

  it('第 10 个会话无 ⌘N 快捷键', () => {
    const sessions = Array.from({ length: 10 }, (_, i) =>
      makeSession({ id: `s${i}`, title: `会话${i}`, mode: 'chat' }),
    );
    mockedUseApp.mockReturnValue({ ...baseState, sessions } as never);
    render(<CommandPalette />);
    // ⌘1~⌘9 存在
    expect(screen.getByText('⌘9')).toBeInTheDocument();
    // 第 10 个会话依然渲染但无 ⌘10
    expect(screen.queryByText('⌘10')).toBeNull();
  });

  it('chat 会话 source 显示「对话」,agent 会话 source 显示项目名', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      projectContext: { project: 'alpha' },
      sessions: [
        makeSession({ id: 'c1', title: '闲聊', mode: 'chat' }),
        makeSession({ id: 'a1', title: '编码', mode: 'agent' }),
      ],
    } as never);
    render(<CommandPalette />);
    expect(screen.getByText('对话')).toBeInTheDocument();
    expect(screen.getAllByText('alpha').length).toBeGreaterThan(0);
  });
});

describe('CommandPalette — 过滤', () => {
  it('输入查询时按 label 过滤', () => {
    render(<CommandPalette />);
    const input = screen.getByPlaceholderText('搜索聊天或运行命令');
    fireEvent.change(input, { target: { value: '设置' } });
    expect(screen.getByText('设置')).toBeInTheDocument();
    expect(screen.queryByText('新对话')).toBeNull();
  });

  it('输入查询时按 section 名过滤', () => {
    render(<CommandPalette />);
    const input = screen.getByPlaceholderText('搜索聊天或运行命令');
    fireEvent.change(input, { target: { value: '面板' } });
    expect(screen.getByText('切换边栏')).toBeInTheDocument();
    expect(screen.queryByText('新对话')).toBeNull();
  });

  it('无匹配时显示「无匹配」', () => {
    render(<CommandPalette />);
    fireEvent.change(screen.getByPlaceholderText('搜索聊天或运行命令'), {
      target: { value: 'zzzz不存在的命令' },
    });
    expect(screen.getByText('无匹配')).toBeInTheDocument();
  });
});

describe('CommandPalette — 键盘交互', () => {
  it('Escape 关闭面板', () => {
    const setPaletteOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setPaletteOpen } as never);
    render(<CommandPalette />);
    fireEvent.keyDown(document.querySelector('.palette')!, { key: 'Escape' });
    expect(setPaletteOpen).toHaveBeenCalledWith(false);
  });

  it('ArrowDown 移动选中项(下移)', () => {
    render(<CommandPalette />);
    const items = screen.getAllByRole('button').filter((b) => b.className.includes('palette-item'));
    expect(items[0].className).toContain('active');
    fireEvent.keyDown(document.querySelector('.palette')!, { key: 'ArrowDown' });
    expect(items[1].className).toContain('active');
  });

  it('ArrowUp 移动选中项(上移)', () => {
    render(<CommandPalette />);
    const items = screen.getAllByRole('button').filter((b) => b.className.includes('palette-item'));
    fireEvent.keyDown(document.querySelector('.palette')!, { key: 'ArrowDown' });
    fireEvent.keyDown(document.querySelector('.palette')!, { key: 'ArrowDown' });
    fireEvent.keyDown(document.querySelector('.palette')!, { key: 'ArrowUp' });
    expect(items[1].className).toContain('active');
  });

  it('ArrowUp 在第一项时不越界(保持第 0 项)', () => {
    render(<CommandPalette />);
    const items = screen.getAllByRole('button').filter((b) => b.className.includes('palette-item'));
    fireEvent.keyDown(document.querySelector('.palette')!, { key: 'ArrowUp' });
    expect(items[0].className).toContain('active');
  });

  it('Enter 执行选中项的 run(切换边栏)', () => {
    const toggleSidebar = vi.fn();
    const setPaletteOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, toggleSidebar, setPaletteOpen } as never);
    render(<CommandPalette />);
    const items = screen.getAllByRole('button').filter((b) => b.className.includes('palette-item'));
    // 找到「切换边栏」的 index
    const idx = items.findIndex((b) => b.textContent?.includes('切换边栏'));
    expect(idx).toBeGreaterThan(-1);
    // 移动选中到 idx
    for (let i = 0; i < idx; i++) {
      fireEvent.keyDown(document.querySelector('.palette')!, { key: 'ArrowDown' });
    }
    fireEvent.keyDown(document.querySelector('.palette')!, { key: 'Enter' });
    expect(toggleSidebar).toHaveBeenCalled();
    expect(setPaletteOpen).toHaveBeenCalledWith(false);
  });

  it('⌘1-9 直接切换对应会话', () => {
    const sessions = Array.from({ length: 3 }, (_, i) =>
      makeSession({ id: `s${i}`, title: `会话${i}`, mode: 'chat' }),
    );
    const selectSession = vi.fn();
    const setPaletteOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, sessions, selectSession, setPaletteOpen } as never);
    render(<CommandPalette />);
    fireEvent.keyDown(document.querySelector('.palette')!, { key: '2', metaKey: true });
    expect(selectSession).toHaveBeenCalledWith('s1');
    expect(setPaletteOpen).toHaveBeenCalledWith(false);
  });

  it('⌘5 不存在第 5 个会话时不报错也不切换', () => {
    const sessions = [makeSession({ id: 's0', title: 'A', mode: 'chat' })];
    const selectSession = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, sessions, selectSession } as never);
    render(<CommandPalette />);
    fireEvent.keyDown(document.querySelector('.palette')!, { key: '5', metaKey: true });
    expect(selectSession).not.toHaveBeenCalled();
  });
});

describe('CommandPalette — 点击交互', () => {
  it('点击 overlay 关闭面板', () => {
    const setPaletteOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setPaletteOpen } as never);
    render(<CommandPalette />);
    fireEvent.click(screen.getByTestId('command-palette'));
    expect(setPaletteOpen).toHaveBeenCalledWith(false);
  });

  it('点击 palette 内部不关闭(stopPropagation)', () => {
    const setPaletteOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setPaletteOpen } as never);
    render(<CommandPalette />);
    fireEvent.click(document.querySelector('.palette')!);
    expect(setPaletteOpen).not.toHaveBeenCalled();
  });

  it('点击「新对话」调用 createSession 并关闭', () => {
    const createSession = vi.fn(async () => 'new-id');
    const setPaletteOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, createSession, setPaletteOpen } as never);
    render(<CommandPalette />);
    fireEvent.click(screen.getByText('新对话'));
    expect(createSession).toHaveBeenCalledWith('新对话');
    expect(setPaletteOpen).toHaveBeenCalledWith(false);
  });

  it('点击「设置」打开设置面板', () => {
    const setSettingsOpen = vi.fn();
    const setPaletteOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setSettingsOpen, setPaletteOpen } as never);
    render(<CommandPalette />);
    fireEvent.click(screen.getByText('设置'));
    expect(setSettingsOpen).toHaveBeenCalledWith(true);
    expect(setPaletteOpen).toHaveBeenCalledWith(false);
  });

  it('点击「MCP · 插件」打开 plugins 面板', () => {
    const setPluginsOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setPluginsOpen } as never);
    render(<CommandPalette />);
    fireEvent.click(screen.getByText('MCP · 插件'));
    expect(setPluginsOpen).toHaveBeenCalledWith(true);
  });

  it('点击「切换主题」调用 toggle', () => {
    const toggle = vi.fn();
    mockedUseTheme.mockReturnValue({ theme: 'dark', toggle });
    render(<CommandPalette />);
    fireEvent.click(screen.getByText('切换到浅色主题'));
    expect(toggle).toHaveBeenCalled();
  });

  it('鼠标移过项更新选中(sel)', () => {
    render(<CommandPalette />);
    const items = screen.getAllByRole('button').filter((b) => b.className.includes('palette-item'));
    fireEvent.mouseMove(items[3]);
    expect(items[3].className).toContain('active');
    expect(items[0].className).not.toContain('active');
  });
});
