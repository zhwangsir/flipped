import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { Plugins } from './Plugins';

vi.mock('../store', () => ({ useApp: vi.fn() }));

import { useApp } from '../store';
import type { McpServer } from '../types';

const mockedUseApp = vi.mocked(useApp);

function makeServer(partial: Partial<McpServer> = {}): McpServer {
  return {
    name: partial.name ?? 'srv',
    description: partial.description ?? '',
    transport: partial.transport ?? 'stdio',
    enabled: partial.enabled ?? true,
    tools: partial.tools ?? [],
    tool_count: partial.tool_count ?? 0,
  };
}

const baseState = {
  pluginsOpen: true,
  setPluginsOpen: vi.fn(),
  mcpServers: [] as McpServer[],
  toggleMcpServer: vi.fn(async () => {}),
  prefillComposer: vi.fn(),
  refreshMcpServers: vi.fn(),
  setSettingsOpen: vi.fn(),
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  mockedUseApp.mockReturnValue({ ...baseState } as never);
});

describe('Plugins — 渲染', () => {
  it('pluginsOpen=false 时返回 null', () => {
    mockedUseApp.mockReturnValue({ ...baseState, pluginsOpen: false } as never);
    const { container } = render(<Plugins />);
    expect(container.firstChild).toBeNull();
  });

  it('pluginsOpen=true 时渲染 overlay', () => {
    render(<Plugins />);
    expect(screen.getByTestId('plugins')).toBeInTheDocument();
  });

  it('默认显示「插件」tab', () => {
    render(<Plugins />);
    const tabs = screen.getAllByRole('button').filter((b) => b.className.includes('plugins-tab'));
    expect(tabs[0].className).toContain('active');
    expect(tabs[0].textContent).toBe('插件');
  });

  it('点击「技能」tab 切换', () => {
    render(<Plugins />);
    const skillsTab = screen.getByText('技能');
    fireEvent.click(skillsTab);
    expect(screen.getByText('Supervisor · GLM-5.2')).toBeInTheDocument();
    expect(screen.getByText('Worker · Kimi-K2.7')).toBeInTheDocument();
    expect(screen.getByText('Overseer · GLM-5.2')).toBeInTheDocument();
  });

  it('插件 tab 渲染精选与效率分组', () => {
    render(<Plugins />);
    expect(screen.getByText('精选')).toBeInTheDocument();
    expect(screen.getByText('效率')).toBeInTheDocument();
  });

  it('精选分组包含浏览器/终端/文件/审查 4 项', () => {
    render(<Plugins />);
    // 同名可能多处,只验证存在
    expect(screen.getAllByText('浏览器').length).toBeGreaterThan(0);
    expect(screen.getAllByText('终端').length).toBeGreaterThan(0);
    expect(screen.getAllByText('文件').length).toBeGreaterThan(0);
    expect(screen.getAllByText('审查').length).toBeGreaterThan(0);
  });

  it('效率分组包含 RAG 知识库 / Git / 联网搜索', () => {
    render(<Plugins />);
    expect(screen.getByText('RAG 知识库')).toBeInTheDocument();
    expect(screen.getByText('Git')).toBeInTheDocument();
    expect(screen.getByText('联网搜索')).toBeInTheDocument();
  });

  it('「即将支持」项显示对应徽章而非 Try in chat 按钮', () => {
    render(<Plugins />);
    expect(screen.getAllByText('即将支持').length).toBeGreaterThan(0);
  });

  it('ready/mcp 项显示 Try in chat 按钮', () => {
    render(<Plugins />);
    const tryButtons = screen.getAllByText('Try in chat');
    expect(tryButtons.length).toBeGreaterThan(0);
  });
});

describe('Plugins — MCP 服务器', () => {
  it('无 MCP 服务器时显示「暂无 MCP 服务器」', () => {
    render(<Plugins />);
    expect(screen.getByText('暂无 MCP 服务器')).toBeInTheDocument();
  });

  it('有 MCP 服务器时渲染 chip 列表', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      mcpServers: [
        makeServer({ name: 'filesystem', enabled: true, tool_count: 6 }),
        makeServer({ name: 'searxng', enabled: false, tool_count: 1 }),
      ],
    } as never);
    render(<Plugins />);
    expect(screen.getByText('filesystem')).toBeInTheDocument();
    expect(screen.getByText('searxng')).toBeInTheDocument();
  });

  it('点击 MCP chip 调用 toggleMcpServer(name, !enabled)', () => {
    const toggleMcpServer = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({
      ...baseState,
      toggleMcpServer,
      mcpServers: [makeServer({ name: 'filesystem', enabled: true })],
    } as never);
    render(<Plugins />);
    fireEvent.click(screen.getByText('filesystem'));
    expect(toggleMcpServer).toHaveBeenCalledWith('filesystem', false);
  });

  it('enabled=false 的 chip 点击后启用', () => {
    const toggleMcpServer = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({
      ...baseState,
      toggleMcpServer,
      mcpServers: [makeServer({ name: 'git', enabled: false })],
    } as never);
    render(<Plugins />);
    fireEvent.click(screen.getByText('git'));
    expect(toggleMcpServer).toHaveBeenCalledWith('git', true);
  });

  it('enabled chip className 含 on', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      mcpServers: [makeServer({ name: 'fs', enabled: true })],
    } as never);
    render(<Plugins />);
    const chip = screen.getByText('fs').closest('button');
    expect(chip?.className).toContain('on');
  });
});

describe('Plugins — 搜索过滤', () => {
  it('输入查询后按 name/desc 过滤精选+效率', () => {
    render(<Plugins />);
    const input = screen.getByPlaceholderText('搜索插件');
    fireEvent.change(input, { target: { value: '浏览器' } });
    expect(screen.getAllByText('浏览器').length).toBeGreaterThan(0);
    expect(screen.queryByText('终端')).toBeNull();
    expect(screen.queryByText('Git')).toBeNull();
  });

  it('按 desc 关键词过滤(如「向量检索」)', () => {
    render(<Plugins />);
    fireEvent.change(screen.getByPlaceholderText('搜索插件'), { target: { value: '向量检索' } });
    expect(screen.getByText('RAG 知识库')).toBeInTheDocument();
    expect(screen.queryByText('浏览器')).toBeNull();
  });
});

describe('Plugins — 顶部按钮交互', () => {
  it('点击关闭按钮调用 setPluginsOpen(false)', () => {
    const setPluginsOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setPluginsOpen } as never);
    render(<Plugins />);
    fireEvent.click(screen.getByLabelText('关闭'));
    expect(setPluginsOpen).toHaveBeenCalledWith(false);
  });

  it('点击设置按钮关闭 plugins 并打开 settings', () => {
    const setPluginsOpen = vi.fn();
    const setSettingsOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setPluginsOpen, setSettingsOpen } as never);
    render(<Plugins />);
    const settingsBtn = screen.getByTitle('设置');
    fireEvent.click(settingsBtn);
    expect(setPluginsOpen).toHaveBeenCalledWith(false);
    expect(setSettingsOpen).toHaveBeenCalledWith(true);
  });

  it('点击刷新按钮调用 refreshMcpServers', () => {
    const refreshMcpServers = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, refreshMcpServers } as never);
    render(<Plugins />);
    fireEvent.click(screen.getByTitle('刷新 MCP 服务器'));
    expect(refreshMcpServers).toHaveBeenCalled();
  });
});

describe('Plugins — Try in chat', () => {
  it('点击 Try in chat 调用 prefillComposer 并关闭面板', () => {
    const prefillComposer = vi.fn();
    const setPluginsOpen = vi.fn();
    mockedUseApp.mockReturnValue({
      ...baseState,
      prefillComposer,
      setPluginsOpen,
    } as never);
    render(<Plugins />);
    const tryButtons = screen.getAllByText('Try in chat');
    fireEvent.click(tryButtons[0]);
    expect(prefillComposer).toHaveBeenCalledWith(expect.stringContaining('帮我'));
    expect(setPluginsOpen).toHaveBeenCalledWith(false);
  });

  it('prefill 文本包含被点击能力名', () => {
    const prefillComposer = vi.fn();
    mockedUseApp.mockReturnValue({
      ...baseState,
      prefillComposer,
    } as never);
    render(<Plugins />);
    // 找到「浏览器」对应的 Try in chat 按钮
    const cards = screen.getAllByText('浏览器');
    // 第一个出现在精选 grid,找到其父卡片里的 Try in chat
    const card = cards[0].closest('.plugin-card');
    const btn = card?.querySelector('.plugin-try') as HTMLElement;
    fireEvent.click(btn);
    expect(prefillComposer).toHaveBeenCalledWith(expect.stringContaining('浏览器'));
  });
});

describe('Plugins — 技能 tab 内容', () => {
  it('技能 tab 显示 3 个内置角色', () => {
    render(<Plugins />);
    fireEvent.click(screen.getByText('技能'));
    expect(screen.getByText('Supervisor · GLM-5.2')).toBeInTheDocument();
    expect(screen.getByText('Worker · Kimi-K2.7')).toBeInTheDocument();
    expect(screen.getByText('Overseer · GLM-5.2')).toBeInTheDocument();
  });

  it('技能 tab 显示内置徽章', () => {
    render(<Plugins />);
    fireEvent.click(screen.getByText('技能'));
    expect(screen.getAllByText('内置').length).toBe(3);
  });

  it('技能 tab 显示副标题说明', () => {
    render(<Plugins />);
    fireEvent.click(screen.getByText('技能'));
    expect(screen.getByText(/Supervisor.*Worker.*Overseer/)).toBeInTheDocument();
  });
});
