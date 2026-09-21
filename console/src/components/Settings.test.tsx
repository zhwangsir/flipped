import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { Settings } from './Settings';

// Settings 同时消费 store 与 useTheme,两者都打薄以隔离 UI 行为。
vi.mock('../store', () => ({ useApp: vi.fn() }));
vi.mock('../hooks/useTheme', () => ({ useTheme: vi.fn() }));

import { useApp } from '../store';
import { useTheme } from '../hooks/useTheme';

const mockedUseApp = vi.mocked(useApp);
const mockedUseTheme = vi.mocked(useTheme);

// Settings.tsx 仅消费 store 的 6 个字段;只提供这些即可驱动全部交互。
const baseState = {
  settingsOpen: true,
  setSettingsOpen: vi.fn(),
  selectedModel: 'coder',
  setModel: vi.fn(),
  mcpServers: [] as import('../types').McpServer[],
  toggleMcpServer: vi.fn(async () => {}),
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  // readPref 在挂载时读 localStorage,跨用例残留会让初始 workMode/fileOpenTarget 漂移。
  localStorage.clear();
});

beforeEach(() => {
  // 每个用例给独立的 spy,避免跨用例 call count 污染。
  mockedUseApp.mockReturnValue({
    ...baseState,
    setSettingsOpen: vi.fn(),
    setModel: vi.fn(),
    toggleMcpServer: vi.fn(async () => {}),
  } as never);
  mockedUseTheme.mockReturnValue({ theme: 'light', toggle: vi.fn() });
});

describe('Settings — 渲染与关闭', () => {
  it('settingsOpen=false 时不渲染任何内容', () => {
    mockedUseApp.mockReturnValue({ ...baseState, settingsOpen: false } as never);
    const { container } = render(<Settings />);
    expect(container.firstChild).toBeNull();
  });

  it('settingsOpen=true 时渲染设置面板(data-testid=settings)', () => {
    render(<Settings />);
    expect(screen.getByTestId('settings')).toBeInTheDocument();
    expect(screen.getByText('← 返回应用')).toBeInTheDocument();
  });

  it('默认进入常规页,渲染导航分组与常规标题', () => {
    render(<Settings />);
    // 导航分组标签
    expect(screen.getByText('个人')).toBeInTheDocument();
    expect(screen.getByText('集成')).toBeInTheDocument();
    expect(screen.getByText('编码')).toBeInTheDocument();
    expect(screen.getByText('已归档')).toBeInTheDocument();
    // 常规页标题(与导航项 "常规" 同名,用 selector 精确定位)
    expect(screen.getByText('常规', { selector: '.settings-title' })).toBeInTheDocument();
    expect(screen.getByText('工作模式')).toBeInTheDocument();
  });

  it('点击"返回应用"按钮调用 setSettingsOpen(false)', () => {
    const setSettingsOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setSettingsOpen } as never);
    render(<Settings />);
    fireEvent.click(screen.getByText('← 返回应用'));
    expect(setSettingsOpen).toHaveBeenCalledWith(false);
  });
});

describe('Settings — 配置页 / 模型选择', () => {
  it('切换到配置页,渲染模型选择列表', () => {
    render(<Settings />);
    fireEvent.click(screen.getByText('配置'));
    expect(screen.getByText('默认执行模型')).toBeInTheDocument();
    expect(screen.getByText('GLM-5.2 · coder')).toBeInTheDocument();
    expect(screen.getByText('GLM-5.2 · architect')).toBeInTheDocument();
  });

  it('点击 architect 行调用 setModel("architect")', () => {
    const setModel = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, selectedModel: 'coder', setModel } as never);
    render(<Settings />);
    fireEvent.click(screen.getByText('配置'));
    fireEvent.click(screen.getByText('GLM-5.2 · architect'));
    expect(setModel).toHaveBeenCalledWith('architect');
  });

  it('点击 coder 行调用 setModel("coder")', () => {
    const setModel = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, selectedModel: 'architect', setModel } as never);
    render(<Settings />);
    fireEvent.click(screen.getByText('配置'));
    fireEvent.click(screen.getByText('GLM-5.2 · coder'));
    expect(setModel).toHaveBeenCalledWith('coder');
  });

  it('当前选中模型行带 active class,未选中行不带', () => {
    mockedUseApp.mockReturnValue({ ...baseState, selectedModel: 'coder' } as never);
    render(<Settings />);
    fireEvent.click(screen.getByText('配置'));
    const coderBtn = screen.getByText('GLM-5.2 · coder').closest('button') as HTMLElement;
    const architectBtn = screen.getByText('GLM-5.2 · architect').closest('button') as HTMLElement;
    expect(coderBtn.classList.contains('active')).toBe(true);
    expect(architectBtn.classList.contains('active')).toBe(false);
  });
});

describe('Settings — 常规页 / 工作模式与文件打开目标', () => {
  it('点击"适用于日常工作"切换工作模式并持久化到 localStorage', () => {
    render(<Settings />);
    const dailyBtn = screen.getByText('适用于日常工作').closest('button') as HTMLElement;
    fireEvent.click(dailyBtn);
    expect(localStorage.getItem('flipped-set-workmode')).toBe('daily');
    // 选中态切换到 daily
    expect(dailyBtn.classList.contains('active')).toBe(true);
    const codingBtn = screen.getByText('适用于编程').closest('button') as HTMLElement;
    expect(codingBtn.classList.contains('active')).toBe(false);
  });

  it('初始 workMode 默认为 coding(无 localStorage 时)', () => {
    render(<Settings />);
    const codingBtn = screen.getByText('适用于编程').closest('button') as HTMLElement;
    expect(codingBtn.classList.contains('active')).toBe(true);
  });

  it('切换默认文件打开目标并持久化', () => {
    render(<Settings />);
    const select = screen.getByLabelText('默认文件打开目标') as HTMLSelectElement;
    expect(select.value).toBe('editor');
    fireEvent.change(select, { target: { value: 'preview' } });
    expect(select.value).toBe('preview');
    expect(localStorage.getItem('flipped-set-file-open-target')).toBe('preview');
  });

  it('localStorage 中已有 workmode=daily 时初始选中 daily', () => {
    localStorage.setItem('flipped-set-workmode', 'daily');
    render(<Settings />);
    const dailyBtn = screen.getByText('适用于日常工作').closest('button') as HTMLElement;
    expect(dailyBtn.classList.contains('active')).toBe(true);
  });
});

describe('Settings — MCP 服务器', () => {
  it('无 MCP 服务器时显示空态', () => {
    mockedUseApp.mockReturnValue({ ...baseState, mcpServers: [] } as never);
    render(<Settings />);
    fireEvent.click(screen.getByText('MCP 服务器'));
    expect(screen.getByText('暂无 MCP 服务器')).toBeInTheDocument();
  });

  it('渲染 MCP 服务器列表(name/transport/description/tool_count)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      mcpServers: [
        {
          name: 'fetch',
          description: 'URL 抓取',
          transport: 'stdio',
          enabled: true,
          tools: ['fetch'],
          tool_count: 1,
        },
      ],
    } as never);
    render(<Settings />);
    fireEvent.click(screen.getByText('MCP 服务器'));
    expect(screen.getByText('fetch')).toBeInTheDocument();
    expect(screen.getByText('stdio')).toBeInTheDocument();
    expect(screen.getByText(/URL 抓取/)).toBeInTheDocument();
    expect(screen.getByText(/1 工具/)).toBeInTheDocument();
  });

  it('已启用服务器点击 toggle 调用 toggleMcpServer(name, false)', () => {
    const toggleMcpServer = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({
      ...baseState,
      mcpServers: [
        {
          name: 'fetch',
          description: 'URL 抓取',
          transport: 'stdio',
          enabled: true,
          tools: ['fetch'],
          tool_count: 1,
        },
      ],
      toggleMcpServer,
    } as never);
    render(<Settings />);
    fireEvent.click(screen.getByText('MCP 服务器'));
    fireEvent.click(screen.getByLabelText('fetch 开关'));
    expect(toggleMcpServer).toHaveBeenCalledWith('fetch', false);
  });

  it('未启用服务器点击 toggle 调用 toggleMcpServer(name, true)', () => {
    const toggleMcpServer = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({
      ...baseState,
      mcpServers: [
        {
          name: 'search',
          description: '联网搜索',
          transport: 'sse',
          enabled: false,
          tools: ['search'],
          tool_count: 2,
        },
      ],
      toggleMcpServer,
    } as never);
    render(<Settings />);
    fireEvent.click(screen.getByText('MCP 服务器'));
    fireEvent.click(screen.getByLabelText('search 开关'));
    expect(toggleMcpServer).toHaveBeenCalledWith('search', true);
  });
});

describe('Settings - theme toggle', () => {
  it('当前主题=light 时点击深色调用 toggle()', () => {
    const toggle = vi.fn();
    mockedUseTheme.mockReturnValue({ theme: 'light', toggle });
    render(<Settings />);
    fireEvent.click(screen.getByText('外观'));
    fireEvent.click(screen.getByText('深色'));
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  it('当前主题=dark 时点击浅色调用 toggle()', () => {
    const toggle = vi.fn();
    mockedUseTheme.mockReturnValue({ theme: 'dark', toggle });
    render(<Settings />);
    fireEvent.click(screen.getByText('外观'));
    fireEvent.click(screen.getByText('浅色'));
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  it('点击当前主题不调用 toggle(已是当前主题)', () => {
    const toggle = vi.fn();
    mockedUseTheme.mockReturnValue({ theme: 'light', toggle });
    render(<Settings />);
    fireEvent.click(screen.getByText('外观'));
    fireEvent.click(screen.getByText('浅色'));
    expect(toggle).not.toHaveBeenCalled();
  });
});

describe('Settings — 其他导航页', () => {
  it('键盘快捷键页渲染快捷键列表', () => {
    render(<Settings />);
    fireEvent.click(screen.getByText('键盘快捷键'));
    expect(screen.getByText('键盘快捷键', { selector: '.settings-title' })).toBeInTheDocument();
    expect(screen.getByText('命令面板')).toBeInTheDocument();
    expect(screen.getByText('⌘K')).toBeInTheDocument();
    expect(screen.getByText('设置')).toBeInTheDocument();
    expect(screen.getByText('⌘,')).toBeInTheDocument();
  });

  it('浏览器页渲染渲染引擎行', () => {
    render(<Settings />);
    fireEvent.click(screen.getByText('浏览器'));
    expect(screen.getByText('渲染引擎')).toBeInTheDocument();
    expect(screen.getByText(/已启用/)).toBeInTheDocument();
  });

  it('Git 页渲染差异视图行', () => {
    render(<Settings />);
    fireEvent.click(screen.getByText('Git'));
    expect(screen.getByText('差异视图')).toBeInTheDocument();
  });

  it('已归档对话页渲染空态', () => {
    render(<Settings />);
    fireEvent.click(screen.getByText('已归档对话'));
    expect(screen.getByText('已归档对话', { selector: '.settings-title' })).toBeInTheDocument();
    expect(screen.getByText('暂无已归档对话')).toBeInTheDocument();
  });

  it('导航高亮跟随选中项', () => {
    render(<Settings />);
    const gitBtn = screen.getByText('Git').closest('button') as HTMLElement;
    fireEvent.click(gitBtn);
    expect(gitBtn.classList.contains('active')).toBe(true);
    // 切换到别的项后 Git 不再高亮
    const browserBtn = screen.getByText('浏览器').closest('button') as HTMLElement;
    fireEvent.click(browserBtn);
    expect(gitBtn.classList.contains('active')).toBe(false);
    expect(browserBtn.classList.contains('active')).toBe(true);
  });
});
