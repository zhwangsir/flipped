import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import { Plugins } from './Plugins';

vi.mock('../store', () => ({ useApp: vi.fn() }));

import { useApp } from '../store';
import type { McpServer, McpToolInfo } from '../types';

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

function makeTool(partial: Partial<McpToolInfo> = {}): McpToolInfo {
  return {
    name: partial.name ?? 'web_search',
    description: partial.description ?? '',
    inputSchema: partial.inputSchema ?? { type: 'object' },
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
  mcpTools: [] as McpToolInfo[],
  refreshMcpTools: vi.fn(async () => {}),
  callMcpTool: vi.fn(async () => ({ ok: true, tool: 'web_search', result: {} })),
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

// M170.2 — 「已安装」区 MCP 工具列表 + 参数表单 + 调用结果/错误/派发渲染
describe('Plugins — MCP 工具调用 (M170.2)', () => {
  function stateWithTools(overrides: Record<string, unknown> = {}) {
    return {
      ...baseState,
      mcpServers: [makeServer({ name: 'flipped', tools: ['web_search'], tool_count: 1 })],
      mcpTools: [makeTool({ name: 'web_search', description: '联网搜索' })],
      ...overrides,
    } as never;
  }

  function stateWithLongTool(overrides: Record<string, unknown> = {}) {
    return {
      ...baseState,
      mcpServers: [makeServer({ name: 'flipped', tools: ['run_coding_task'], tool_count: 1 })],
      mcpTools: [makeTool({ name: 'run_coding_task', description: '跑编码任务' })],
      ...overrides,
    } as never;
  }

  it('mcpTools 为空时打开面板自动 refreshMcpTools', () => {
    const refreshMcpTools = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({ ...baseState, refreshMcpTools } as never);
    render(<Plugins />);
    expect(refreshMcpTools).toHaveBeenCalled();
  });

  it('tools 非空的服务器渲染工具列表与「调用」按钮', () => {
    mockedUseApp.mockReturnValue(stateWithTools());
    render(<Plugins />);
    expect(screen.getByTestId('mcp-tool-call-btn-web_search')).toBeInTheDocument();
    expect(screen.getByText('web_search')).toBeInTheDocument();
    // description 出现在工具行(静态能力目录里也有同名「联网搜索」卡,故用 getAllByText)
    expect(screen.getAllByText('联网搜索').length).toBeGreaterThan(0);
  });

  it('tools 为空的服务器不渲染工具列表', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      mcpServers: [makeServer({ name: 'empty', tools: [], tool_count: 0 })],
      mcpTools: [makeTool({ name: 'web_search' })],
    } as never);
    render(<Plugins />);
    expect(screen.queryByTestId('mcp-tool-call-btn-web_search')).toBeNull();
  });

  it('点击「调用」展开参数表单并显示 description 提示文案', () => {
    mockedUseApp.mockReturnValue(stateWithTools());
    render(<Plugins />);
    expect(screen.queryByTestId('mcp-tool-form-web_search')).toBeNull();
    fireEvent.click(screen.getByTestId('mcp-tool-call-btn-web_search'));
    const form = screen.getByTestId('mcp-tool-form-web_search');
    expect(form).toBeInTheDocument();
    expect(within(form).getByLabelText('query')).toBeInTheDocument();
    expect(within(form).getByText('联网搜索')).toBeInTheDocument();
  });

  it('必填字段为空时提交键禁用,填写后启用', () => {
    mockedUseApp.mockReturnValue(stateWithTools());
    render(<Plugins />);
    fireEvent.click(screen.getByTestId('mcp-tool-call-btn-web_search'));
    const form = screen.getByTestId('mcp-tool-form-web_search');
    const submit = within(form).getByRole('button', { name: '运行' });
    expect(submit).toBeDisabled();
    fireEvent.change(within(form).getByLabelText('query'), { target: { value: 'mlx' } });
    expect(submit).not.toBeDisabled();
  });

  it('快工具提交成功后内联渲染 result(JSON)且可点 × 关闭', async () => {
    const callMcpTool = vi.fn(async () => ({ ok: true, tool: 'web_search', result: { hits: ['a', 'b'] } }));
    mockedUseApp.mockReturnValue(stateWithTools({ callMcpTool }));
    render(<Plugins />);
    fireEvent.click(screen.getByTestId('mcp-tool-call-btn-web_search'));
    const form = screen.getByTestId('mcp-tool-form-web_search');
    fireEvent.change(within(form).getByLabelText('query'), { target: { value: 'mlx' } });
    fireEvent.submit(form);
    const result = await screen.findByTestId('mcp-tool-result');
    expect(callMcpTool).toHaveBeenCalledWith('web_search', { query: 'mlx' });
    expect(result.querySelector('pre')?.textContent).toContain('"hits"');
    expect(result.querySelector('pre')?.textContent).toContain('"a"');
    fireEvent.click(within(result).getByLabelText('关闭结果'));
    expect(screen.queryByTestId('mcp-tool-result')).toBeNull();
  });

  it('快工具 ok:false 时渲染 error', async () => {
    const callMcpTool = vi.fn(async () => ({ ok: false, tool: 'web_search', error: 'searxng down' }));
    mockedUseApp.mockReturnValue(stateWithTools({ callMcpTool }));
    render(<Plugins />);
    fireEvent.click(screen.getByTestId('mcp-tool-call-btn-web_search'));
    const form = screen.getByTestId('mcp-tool-form-web_search');
    fireEvent.change(within(form).getByLabelText('query'), { target: { value: 'mlx' } });
    fireEvent.submit(form);
    const err = await screen.findByTestId('mcp-tool-error');
    expect(err.textContent).toContain('searxng down');
  });

  it('长工具有会话时渲染「已派发到当前会话」提示', async () => {
    const callMcpTool = vi.fn(async () => ({
      ok: true,
      accepted: true,
      tool: 'run_coding_task',
      session_id: 's1',
    }));
    mockedUseApp.mockReturnValue(stateWithLongTool({ callMcpTool }));
    render(<Plugins />);
    fireEvent.click(screen.getByTestId('mcp-tool-call-btn-run_coding_task'));
    const form = screen.getByTestId('mcp-tool-form-run_coding_task');
    fireEvent.change(within(form).getByLabelText('goal'), { target: { value: '修 bug' } });
    fireEvent.submit(form);
    const d = await screen.findByTestId('mcp-tool-dispatched');
    expect(d.textContent).toContain('已派发到当前会话');
    expect(callMcpTool).toHaveBeenCalledWith('run_coding_task', { goal: '修 bug' });
  });

  it('长工具无会话时提示「请先在 Assistant 开始对话」', async () => {
    const callMcpTool = vi.fn(async () => ({ ok: false, tool: 'run_coding_task', error: 'no-session' }));
    mockedUseApp.mockReturnValue(stateWithLongTool({ callMcpTool }));
    render(<Plugins />);
    fireEvent.click(screen.getByTestId('mcp-tool-call-btn-run_coding_task'));
    const form = screen.getByTestId('mcp-tool-form-run_coding_task');
    fireEvent.change(within(form).getByLabelText('goal'), { target: { value: '修 bug' } });
    fireEvent.submit(form);
    const err = await screen.findByTestId('mcp-tool-error');
    expect(err.textContent).toContain('请先在 Assistant 开始对话');
  });
});
