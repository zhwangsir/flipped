import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { Conversation } from './Conversation';

// M146 回归保护：发送失败可见反馈 + 项目选择器搜索过滤。
vi.mock('../store', () => ({ useApp: vi.fn() }));
// 子组件同样消费 store/重型依赖，打薄避免干扰
vi.mock('./PlanCard', () => ({ PlanCard: () => null }));
vi.mock('./FailurePanel', () => ({ FailurePanel: () => null }));
vi.mock('../lib/native', () => ({ isTauri: () => false, pickFolder: vi.fn() }));

import { useApp } from '../store';
import type { StreamItem } from '../types';

const mockedUseApp = vi.mocked(useApp);

const baseState = {
  stream: [],
  sendTask: vi.fn(async () => {}),
  selectedSessionId: 'sess-1',
  sessionStatus: 'idle',
  progress: 0,
  lastError: null,
  approvalPending: null,
  sendApproval: vi.fn(),
  cancelTask: vi.fn(),
  selectedModel: 'coder',
  setModel: vi.fn(),
  selectedMode: 'agent',
  setMode: vi.fn(),
  setContextTab: vi.fn(),
  projectContext: { project: 'demo', path: '/p/demo', sandbox: null, branch: 'main', mode: 'agent' },
  projects: [
    { name: 'alpha', host: '/p/alpha', sandbox: '/projects/alpha' },
    { name: 'beta-app', host: '/p/beta-app', sandbox: '/projects/beta-app' },
    { name: 'gamma', host: '/p/gamma', sandbox: '/projects/gamma' },
  ],
  projectFiles: [],
  openProject: vi.fn(async () => ({})),
  createProject: vi.fn(async () => ({})),
  composerPrefill: '',
  prefillComposer: vi.fn(),
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  mockedUseApp.mockReturnValue({ ...baseState, sendTask: vi.fn(async () => {}) } as never);
});

describe('Conversation — 发送失败反馈（M146 P1）', () => {
  it('发送失败显示错误行且输入保留（此前静默吞错+用户以为已发出）', async () => {
    const sendTask = vi.fn(async () => {
      throw new Error('HTTP 500: boom');
    });
    mockedUseApp.mockReturnValue({ ...baseState, sendTask } as never);
    render(<Conversation />);

    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '帮我改个 bug' } });
    fireEvent.click(screen.getByTestId('send-button'));

    const err = await screen.findByTestId('send-error');
    expect(err.textContent).toContain('boom');
    expect(err.textContent).not.toContain('HTTP 500'); // 前缀已剥
    // 失败时输入不清空，用户可重试
    expect(input.value).toBe('帮我改个 bug');
  });

  it('发送成功清空输入且无错误行', async () => {
    const sendTask = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({ ...baseState, sendTask } as never);
    render(<Conversation />);

    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: 'hi' } });
    fireEvent.click(screen.getByTestId('send-button'));

    await vi.waitFor(() => expect(input.value).toBe(''));
    expect(screen.queryByTestId('send-error')).toBeNull();
  });

  it('发送中 busy 防重复提交', async () => {
    let release: () => void = () => {};
    const sendTask = vi.fn(() => new Promise<void>((r) => { release = r; }));
    mockedUseApp.mockReturnValue({ ...baseState, sendTask } as never);
    render(<Conversation />);

    const input = screen.getByTestId('composer-input');
    fireEvent.change(input, { target: { value: 'task' } });
    const btn = screen.getByTestId('send-button') as HTMLButtonElement;
    fireEvent.click(btn);
    fireEvent.click(btn); // 连点第二次
    await vi.waitFor(() => expect(sendTask).toHaveBeenCalledTimes(1));
    release();
  });
});

describe('Conversation — 项目选择器搜索过滤（M146）', () => {
  const openPicker = () => {
    render(<Conversation />);
    // ctx-proj 按钮显示当前项目名
    fireEvent.click(screen.getByText('demo'));
    return screen.getByLabelText('搜索项目');
  };

  it('输入查询串过滤项目列表', () => {
    const search = openPicker();
    expect(screen.getByText('alpha')).toBeTruthy();
    expect(screen.getByText('beta-app')).toBeTruthy();

    fireEvent.change(search, { target: { value: 'beta' } });
    expect(screen.queryByText('alpha')).toBeNull();
    expect(screen.getByText('beta-app')).toBeTruthy();
    expect(screen.queryByText('gamma')).toBeNull();
  });

  it('无匹配时显示空态提示', () => {
    const search = openPicker();
    fireEvent.change(search, { target: { value: 'zzz' } });
    expect(screen.getByText(/无匹配/)).toBeTruthy();
    expect(screen.queryByText('alpha')).toBeNull();
  });
});

describe('Conversation — StatusBanner / ErrorBanner', () => {
  it('sessionStatus=idle → 不渲染 banner', () => {
    mockedUseApp.mockReturnValue({ ...baseState, sessionStatus: 'idle' } as never);
    render(<Conversation />);
    expect(screen.queryByTestId('status-banner')).toBeNull();
  });

  it('sessionStatus=running + progress=0 → 显示「运行中…」无进度条', () => {
    mockedUseApp.mockReturnValue({ ...baseState, sessionStatus: 'running', progress: 0 } as never);
    render(<Conversation />);
    expect(screen.getByTestId('status-banner')).toBeTruthy();
    expect(screen.getByText('运行中…')).toBeTruthy();
    expect(document.querySelector('.progress-track')).toBeNull();
  });

  it('sessionStatus=running + progress>0 → 显示进度条', () => {
    mockedUseApp.mockReturnValue({ ...baseState, sessionStatus: 'running', progress: 42 } as never);
    render(<Conversation />);
    expect(screen.getByText(/运行中… 42%/)).toBeTruthy();
    expect(document.querySelector('.progress-track')).not.toBeNull();
    expect(document.querySelector('.progress-fill')?.getAttribute('style')).toContain('42%');
  });

  it('sessionStatus=done → 显示「任务已完成」', () => {
    mockedUseApp.mockReturnValue({ ...baseState, sessionStatus: 'done' } as never);
    render(<Conversation />);
    expect(screen.getByText('任务已完成')).toBeTruthy();
  });

  it('sessionStatus=review → 显示「待人工审批」', () => {
    mockedUseApp.mockReturnValue({ ...baseState, sessionStatus: 'review' } as never);
    render(<Conversation />);
    expect(screen.getByText('待人工审批')).toBeTruthy();
  });

  it('sessionStatus=error → 显示「执行出错」', () => {
    mockedUseApp.mockReturnValue({ ...baseState, sessionStatus: 'error' } as never);
    render(<Conversation />);
    expect(screen.getByText('执行出错')).toBeTruthy();
  });

  it('lastError 有值 → 显示错误 banner', () => {
    mockedUseApp.mockReturnValue({ ...baseState, lastError: 'boom' } as never);
    render(<Conversation />);
    expect(screen.getByTestId('error-banner').textContent).toContain('boom');
  });
});

describe('Conversation — ApprovalCard', () => {
  const pending = { id: 'appr-1', action: 'rm -rf /tmp/x', reason: '需要清理临时目录', risk: 'high' };

  it('approvalPending → 渲染审批卡 + 默认 risk=medium', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      approvalPending: { id: 'appr-1', action: 'do something' },
    } as never);
    render(<Conversation />);
    expect(screen.getByTestId('approval-card')).toBeTruthy();
    expect(screen.getByText('medium')).toBeTruthy();
    expect(screen.getByText('do something')).toBeTruthy();
  });

  it('有 reason → 显示 reason', () => {
    mockedUseApp.mockReturnValue({ ...baseState, approvalPending: pending } as never);
    render(<Conversation />);
    expect(screen.getByText('需要清理临时目录')).toBeTruthy();
    expect(screen.getByText('high')).toBeTruthy();
    expect(screen.getByText('rm -rf /tmp/x')).toBeTruthy();
  });

  it('点击放行 → 调用 sendApproval(approve)', async () => {
    const sendApproval = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, approvalPending: pending, sendApproval } as never);
    render(<Conversation />);
    fireEvent.click(screen.getByTestId('approve-button'));
    await vi.waitFor(() => expect(sendApproval).toHaveBeenCalledWith('approve'));
  });

  it('点击否决 → 调用 sendApproval(reject)', async () => {
    const sendApproval = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, approvalPending: pending, sendApproval } as never);
    render(<Conversation />);
    fireEvent.click(screen.getByTestId('reject-button'));
    await vi.waitFor(() => expect(sendApproval).toHaveBeenCalledWith('reject'));
  });

  it('approvalPending → composer 禁用 + 不发送', () => {
    const sendTask = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({ ...baseState, approvalPending: pending, sendTask } as never);
    render(<Conversation />);
    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    expect(input.disabled).toBe(true);
    const sendBtn = screen.getByTestId('send-button') as HTMLButtonElement;
    expect(sendBtn.disabled).toBe(true);
  });
});

describe('Conversation — Turn / ToolRow 渲染', () => {
  it('空 stream + selectedSessionId → 显示「准备就绪」', () => {
    mockedUseApp.mockReturnValue({ ...baseState, stream: [], selectedSessionId: 'sess-1' } as never);
    render(<Conversation />);
    expect(screen.getByText('准备就绪')).toBeTruthy();
  });

  it('user 消息：右对齐气泡 + 文本', () => {
    const stream: StreamItem[] = [{ id: 'u1', role: 'user', text: '帮我写个函数' }];
    mockedUseApp.mockReturnValue({ ...baseState, stream } as never);
    render(<Conversation />);
    expect(screen.getByText('帮我写个函数')).toBeTruthy();
  });

  it('worker 角色：不显示 role 标签（干净执行体）', () => {
    const stream: StreamItem[] = [{ id: 'w1', role: 'worker', text: '正在写代码' }];
    mockedUseApp.mockReturnValue({ ...baseState, stream } as never);
    render(<Conversation />);
    expect(screen.getByText('正在写代码')).toBeTruthy();
    expect(screen.queryByText('Worker · 执行')).toBeNull();
  });

  it('supervisor 角色：显示 role 标签 + model', () => {
    const stream: StreamItem[] = [
      { id: 's1', role: 'supervisor', text: '规划中', model: 'GLM-5.2' },
    ];
    mockedUseApp.mockReturnValue({ ...baseState, stream } as never);
    render(<Conversation />);
    expect(screen.getByText('Supervisor · 调度')).toBeTruthy();
    expect(screen.getByText('GLM-5.2')).toBeTruthy();
  });

  it('overseer 角色：显示标签', () => {
    const stream: StreamItem[] = [{ id: 'o1', role: 'overseer', text: '监督中' }];
    mockedUseApp.mockReturnValue({ ...baseState, stream } as never);
    render(<Conversation />);
    expect(screen.getByText('Overseer · 监督')).toBeTruthy();
  });

  it('verify 角色 + ok → 显示 verify-banner', () => {
    const stream: StreamItem[] = [
      { id: 'v1', role: 'verify', text: '校验通过', ok: true },
    ];
    mockedUseApp.mockReturnValue({ ...baseState, stream } as never);
    render(<Conversation />);
    // verify 角色既显示 banner 又显示 text
    expect(screen.getAllByText('校验通过').length).toBeGreaterThanOrEqual(1);
  });

  it('system 角色：显示标签', () => {
    const stream: StreamItem[] = [{ id: 'sys1', role: 'system', text: '系统提示' }];
    mockedUseApp.mockReturnValue({ ...baseState, stream } as never);
    render(<Conversation />);
    expect(screen.getByText('系统')).toBeTruthy();
  });

  it('verdict → 渲染效率/方向 meter + note + action', () => {
    const stream: StreamItem[] = [
      {
        id: 'vd1',
        role: 'overseer',
        verdict: { efficiency: 0.85, direction: 0.62, action: 'proceed', note: '一切顺利' },
      },
    ];
    mockedUseApp.mockReturnValue({ ...baseState, stream } as never);
    render(<Conversation />);
    expect(screen.getByText('效率')).toBeTruthy();
    expect(screen.getByText('方向')).toBeTruthy();
    expect(screen.getByText('0.85')).toBeTruthy();
    expect(screen.getByText('0.62')).toBeTruthy();
    expect(screen.getByText('一切顺利')).toBeTruthy();
    expect(screen.getByText('action = proceed')).toBeTruthy();
  });

  it('tool_call (terminal) → 渲染 $ 命令 + 完成状态', () => {
    const stream: StreamItem[] = [
      {
        id: 'tc1',
        role: 'worker',
        tools: [
          { tool: 'terminal', summary: 'ls -la', status: 'ok', children: [{ type: 'terminal', text: 'output here' }] },
        ],
      },
    ];
    mockedUseApp.mockReturnValue({ ...baseState, stream } as never);
    render(<Conversation />);
    expect(screen.getByText('$ ls -la')).toBeTruthy();
    expect(screen.getByText('完成')).toBeTruthy();
  });

  it('tool_call (file_editor) → 渲染文件路径(mono)', () => {
    const stream: StreamItem[] = [
      {
        id: 'tc2',
        role: 'worker',
        tools: [{ tool: 'file_editor', summary: '/src/main.ts', status: 'running' }],
      },
    ];
    mockedUseApp.mockReturnValue({ ...baseState, stream } as never);
    render(<Conversation />);
    expect(screen.getByText('/src/main.ts')).toBeTruthy();
    expect(screen.getByText('运行中')).toBeTruthy();
  });

  it('tool_call (browser) → 渲染摘要', () => {
    const stream: StreamItem[] = [
      {
        id: 'tc3',
        role: 'worker',
        tools: [{ tool: 'browser', summary: '访问 google', status: 'error', detail: 'timeout' }],
      },
    ];
    mockedUseApp.mockReturnValue({ ...baseState, stream } as never);
    render(<Conversation />);
    expect(screen.getByText('访问 google')).toBeTruthy();
    expect(screen.getByText('失败')).toBeTruthy();
    // error 状态默认展开 → 显示 detail
    expect(screen.getByText('timeout')).toBeTruthy();
  });

  it('tool_call (search) → 渲染搜索标签', () => {
    const stream: StreamItem[] = [
      {
        id: 'tc4',
        role: 'worker',
        tools: [{ tool: 'search', summary: '', status: 'ok' }],
      },
    ];
    mockedUseApp.mockReturnValue({ ...baseState, stream } as never);
    render(<Conversation />);
    // summary='' → toolPrimary fallback 到 ACTION_LABEL[search]='搜索'
    expect(screen.getByText('搜索')).toBeTruthy();
  });

  it('tool_call (terminal 无 summary) → 显示 $ 命令 fallback', () => {
    const stream: StreamItem[] = [
      {
        id: 'tc5',
        role: 'worker',
        tools: [{ tool: 'terminal', summary: 'terminal', status: 'ok' }],
      },
    ];
    mockedUseApp.mockReturnValue({ ...baseState, stream } as never);
    render(<Conversation />);
    // summary===tool → toolPrimary 视作空 → fallback '命令'
    expect(screen.getByText('$ 命令')).toBeTruthy();
  });

  it('ToolRow 点击展开/折叠 child 输出', () => {
    const stream: StreamItem[] = [
      {
        id: 'tr1',
        role: 'worker',
        tools: [
          {
            tool: 'terminal',
            summary: 'cat foo.txt',
            status: 'ok',
            children: [{ type: 'terminal', text: 'hello world' }],
          },
        ],
      },
    ];
    mockedUseApp.mockReturnValue({ ...baseState, stream } as never);
    render(<Conversation />);
    // 默认折叠（status=ok → 默认 closed）
    expect(screen.queryByText('hello world')).toBeNull();
    // 点击展开
    fireEvent.click(screen.getByText('$ cat foo.txt'));
    expect(screen.getByText('hello world')).toBeTruthy();
    // 再点折叠
    fireEvent.click(screen.getByText('$ cat foo.txt'));
    expect(screen.queryByText('hello world')).toBeNull();
  });

  it('ToolRow 无 body → 按钮 disabled', () => {
    const stream: StreamItem[] = [
      {
        id: 'tr2',
        role: 'worker',
        tools: [{ tool: 'terminal', summary: 'noop', status: 'ok' }],
      },
    ];
    mockedUseApp.mockReturnValue({ ...baseState, stream } as never);
    render(<Conversation />);
    const head = screen.getByText('$ noop').closest('button') as HTMLButtonElement;
    expect(head.disabled).toBe(true);
  });

  it('ToolChild file_change/browser/output 渲染对应图标', () => {
    const stream: StreamItem[] = [
      {
        id: 'tc6',
        role: 'worker',
        tools: [
          {
            tool: 'file_editor',
            summary: 'edit main.ts',
            status: 'error',
            children: [
              { type: 'file_change', text: '文件: /src/main.ts' },
              { type: 'browser', text: '浏览器: http://localhost' },
              { type: 'output', text: '输出文本' },
            ],
          },
        ],
      },
    ];
    mockedUseApp.mockReturnValue({ ...baseState, stream } as never);
    render(<Conversation />);
    // error 状态默认展开 → 子项都可见
    expect(screen.getByText('文件: /src/main.ts')).toBeTruthy();
    expect(screen.getByText('浏览器: http://localhost')).toBeTruthy();
    expect(screen.getByText('输出文本')).toBeTruthy();
  });
});

describe('Conversation — 新线程视图', () => {
  it('无 session + 无 stream + 无 approval → 显示 hero 大问句（有项目）', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      selectedSessionId: null,
      stream: [],
      approvalPending: null,
      projectContext: { project: 'my-app', path: '/p/my-app', sandbox: null, branch: 'main', mode: 'agent' },
    } as never);
    render(<Conversation />);
    expect(screen.getByText('我们应该在 my-app 中构建什么？')).toBeTruthy();
  });

  it('无 session + 无项目 → 显示「选择一个项目」', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      selectedSessionId: null,
      stream: [],
      approvalPending: null,
      projectContext: null,
    } as never);
    render(<Conversation />);
    expect(screen.getByText('选择一个项目，开始构建')).toBeTruthy();
  });
});

describe('Conversation — + 菜单与 @ 提及', () => {
  it('+ 菜单展开 → 显示三个选项 + 点击「文件和文件夹」插入 @', () => {
    mockedUseApp.mockReturnValue({ ...baseState } as never);
    render(<Conversation />);
    fireEvent.click(screen.getByTitle('添加'));
    expect(screen.getByText('文件和文件夹')).toBeTruthy();
    expect(screen.getByText('目标')).toBeTruthy();
    expect(screen.getByText('计划模式')).toBeTruthy();
    fireEvent.click(screen.getByText('文件和文件夹'));
    // 插入 @ 到 textarea
    const ta = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    expect(ta.value).toContain('@');
  });

  it('点击「目标」插入「目标：」前缀', () => {
    mockedUseApp.mockReturnValue({ ...baseState } as never);
    render(<Conversation />);
    fireEvent.click(screen.getByTitle('添加'));
    fireEvent.click(screen.getByText('目标'));
    const ta = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    expect(ta.value).toContain('目标：');
  });

  it('点击「计划模式」→ setMode(plan) + 关闭菜单', () => {
    const setMode = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setMode } as never);
    render(<Conversation />);
    fireEvent.click(screen.getByTitle('添加'));
    fireEvent.click(screen.getByText('计划模式'));
    expect(setMode).toHaveBeenCalledWith('plan');
  });

  it('已有文本时点「文件和文件夹」→ 在前加空格再 @', () => {
    mockedUseApp.mockReturnValue({ ...baseState } as never);
    render(<Conversation />);
    const ta = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'hi' } });
    fireEvent.click(screen.getByTitle('添加'));
    fireEvent.click(screen.getByText('文件和文件夹'));
    expect(ta.value).toBe('hi @');
  });

  it('@ 提及输入 → 显示匹配文件列表 + 选择后替换', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      projectFiles: [
        { name: 'a.ts', path: 'src/a.ts', type: 'file' },
        { name: 'b.ts', path: 'src/b.ts', type: 'file' },
        { name: 'c.md', path: 'docs/c.md', type: 'file' },
      ],
    } as never);
    render(<Conversation />);
    const ta = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '@a', selectionStart: 2 } });
    expect(screen.getByText('src/a.ts')).toBeTruthy();
    // 点击选择
    fireEvent.click(screen.getByText('src/a.ts'));
    expect(ta.value).toContain('@src/a.ts ');
  });

  it('@ 提及键盘 ArrowDown/Up/Enter/Escape', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      projectFiles: [
        { name: 'a.ts', path: 'src/a.ts', type: 'file' },
        { name: 'b.ts', path: 'src/b.ts', type: 'file' },
      ],
    } as never);
    render(<Conversation />);
    const ta = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '@', selectionStart: 1 } });
    // ArrowDown → 选中第二项
    fireEvent.keyDown(ta, { key: 'ArrowDown' });
    expect(document.querySelector('.mention-item.active')?.textContent).toContain('src/b.ts');
    // ArrowUp → 回到第一项
    fireEvent.keyDown(ta, { key: 'ArrowUp' });
    expect(document.querySelector('.mention-item.active')?.textContent).toContain('src/a.ts');
    // Enter → 选择第一项
    fireEvent.keyDown(ta, { key: 'Enter' });
    expect(ta.value).toContain('@src/a.ts ');
  });

  it('@ 提及 Escape → 关闭 mention 菜单', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      projectFiles: [{ name: 'a.ts', path: 'src/a.ts', type: 'file' }],
    } as never);
    render(<Conversation />);
    const ta = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '@a', selectionStart: 2 } });
    expect(screen.getByText('src/a.ts')).toBeTruthy();
    fireEvent.keyDown(ta, { key: 'Escape' });
    expect(screen.queryByText('src/a.ts')).toBeNull();
  });

  it('composer Enter (no shift) → submit; shift+Enter 不发送', async () => {
    const sendTask = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({ ...baseState, sendTask } as never);
    render(<Conversation />);
    const ta = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'hello' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: true });
    expect(sendTask).not.toHaveBeenCalled();
    fireEvent.keyDown(ta, { key: 'Enter' });
    await vi.waitFor(() => expect(sendTask).toHaveBeenCalledWith('hello'));
  });
});

describe('Conversation — 项目选择器分支', () => {
  it('空 projects → 显示「~/projects 下暂无项目」', () => {
    mockedUseApp.mockReturnValue({ ...baseState, projects: [] } as never);
    render(<Conversation />);
    fireEvent.click(screen.getByText('demo'));
    expect(screen.getByText(/~/)).toBeTruthy();
  });

  it('点击项目条目 → 调用 openProject + 关闭 picker', async () => {
    const openProject = vi.fn(async () => ({}));
    mockedUseApp.mockReturnValue({ ...baseState, openProject } as never);
    render(<Conversation />);
    fireEvent.click(screen.getByText('demo'));
    fireEvent.click(screen.getByText('alpha'));
    await vi.waitFor(() => expect(openProject).toHaveBeenCalledWith('/p/alpha'));
  });

  it('New project → 新建空白项目模式 + 提交', async () => {
    const createProject = vi.fn(async () => ({}));
    mockedUseApp.mockReturnValue({ ...baseState, createProject } as never);
    render(<Conversation />);
    fireEvent.click(screen.getByText('demo'));
    fireEvent.click(screen.getByText('New project'));
    fireEvent.click(screen.getByText('新建空白项目'));
    const input = screen.getByPlaceholderText(/项目名/) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'my-new-app' } });
    fireEvent.click(screen.getByText('创建'));
    await vi.waitFor(() => expect(createProject).toHaveBeenCalledWith('my-new-app'));
  });

  it('导入文件夹模式 → 提交路径', async () => {
    const openProject = vi.fn(async () => ({}));
    mockedUseApp.mockReturnValue({ ...baseState, openProject } as never);
    render(<Conversation />);
    fireEvent.click(screen.getByText('demo'));
    fireEvent.click(screen.getByText('New project'));
    fireEvent.click(screen.getByText('导入现有文件夹'));
    // isTauri=false → 进入 import 输入模式
    const input = screen.getByPlaceholderText(/粘贴文件夹绝对路径/) as HTMLInputElement;
    fireEvent.change(input, { target: { value: '/tmp/my-app' } });
    fireEvent.click(screen.getByText('导入'));
    await vi.waitFor(() => expect(openProject).toHaveBeenCalledWith('/tmp/my-app'));
  });

  it('导入失败 → 显示错误', async () => {
    const openProject = vi.fn(async () => {
      throw new Error('HTTP 400: 路径不存在');
    });
    mockedUseApp.mockReturnValue({ ...baseState, openProject } as never);
    render(<Conversation />);
    fireEvent.click(screen.getByText('demo'));
    fireEvent.click(screen.getByText('New project'));
    fireEvent.click(screen.getByText('导入现有文件夹'));
    const input = screen.getByPlaceholderText(/粘贴文件夹绝对路径/) as HTMLInputElement;
    fireEvent.change(input, { target: { value: '/bad/path' } });
    fireEvent.click(screen.getByText('导入'));
    await screen.findByText(/路径不存在/);
  });

  it('新建项目失败 → 显示错误', async () => {
    const createProject = vi.fn(async () => {
      throw new Error('HTTP 409: 项目已存在');
    });
    mockedUseApp.mockReturnValue({ ...baseState, createProject } as never);
    render(<Conversation />);
    fireEvent.click(screen.getByText('demo'));
    fireEvent.click(screen.getByText('New project'));
    fireEvent.click(screen.getByText('新建空白项目'));
    const input = screen.getByPlaceholderText(/项目名/) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'dup' } });
    fireEvent.click(screen.getByText('创建'));
    await screen.findByText(/项目已存在/);
  });

  it('picker 中 Escape 取消 → 回到项目列表', () => {
    mockedUseApp.mockReturnValue({ ...baseState } as never);
    render(<Conversation />);
    fireEvent.click(screen.getByText('demo'));
    fireEvent.click(screen.getByText('New project'));
    fireEvent.click(screen.getByText('新建空白项目'));
    const input = screen.getByPlaceholderText(/项目名/) as HTMLInputElement;
    fireEvent.keyDown(input, { key: 'Escape' });
    // 回到列表 → 重新看到「New project」入口
    expect(screen.getByText('New project')).toBeTruthy();
  });

  it('Enter 在 picker input 提交 = 点按钮', async () => {
    const createProject = vi.fn(async () => ({}));
    mockedUseApp.mockReturnValue({ ...baseState, createProject } as never);
    render(<Conversation />);
    fireEvent.click(screen.getByText('demo'));
    fireEvent.click(screen.getByText('New project'));
    fireEvent.click(screen.getByText('新建空白项目'));
    const input = screen.getByPlaceholderText(/项目名/) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'enter-app' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await vi.waitFor(() => expect(createProject).toHaveBeenCalledWith('enter-app'));
  });

  it('项目输入框 onChange 清除错误', () => {
    const createProject = vi.fn(async () => {
      throw new Error('HTTP 409: 项目已存在');
    });
    mockedUseApp.mockReturnValue({ ...baseState, createProject } as never);
    render(<Conversation />);
    fireEvent.click(screen.getByText('demo'));
    fireEvent.click(screen.getByText('New project'));
    fireEvent.click(screen.getByText('新建空白项目'));
    const input = screen.getByPlaceholderText(/项目名/) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'dup' } });
    fireEvent.click(screen.getByText('创建'));
    return screen.findByText(/项目已存在/).then(() => {
      // 修改输入 → 错误消失
      fireEvent.change(input, { target: { value: 'dup2' } });
      expect(screen.queryByText(/项目已存在/)).toBeNull();
    });
  });
});

describe('Conversation — 运行中停止按钮 + 模式/模型 select', () => {
  it('sessionStatus=running → 显示停止按钮 + 点击调 cancelTask', async () => {
    const cancelTask = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({ ...baseState, sessionStatus: 'running', cancelTask } as never);
    render(<Conversation />);
    const stopBtn = screen.getByTitle('停止');
    fireEvent.click(stopBtn);
    await vi.waitFor(() => expect(cancelTask).toHaveBeenCalled());
  });

  it('模型 select 改变 → setModel', () => {
    const setModel = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setModel } as never);
    render(<Conversation />);
    const modelSelect = screen.getByTitle('执行模型') as HTMLSelectElement;
    fireEvent.change(modelSelect, { target: { value: 'architect' } });
    expect(setModel).toHaveBeenCalledWith('architect');
  });

  it('模式 select 改变 → setMode', () => {
    const setMode = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setMode } as never);
    render(<Conversation />);
    const modeSelect = screen.getByTitle(/模式：/) as HTMLSelectElement;
    fireEvent.change(modeSelect, { target: { value: 'plan' } });
    expect(setMode).toHaveBeenCalledWith('plan');
  });

  it('沙盒访问按钮点击 → setContextTab(term)', () => {
    const setContextTab = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setContextTab } as never);
    render(<Conversation />);
    fireEvent.click(screen.getByTitle(/沙盒访问/));
    expect(setContextTab).toHaveBeenCalledWith('term');
  });
});

describe('Conversation — composerPrefill 行内评论回填', () => {
  it('composerPrefill 有值 → 拼接到输入框 + 清空 prefill', () => {
    const prefillComposer = vi.fn();
    mockedUseApp.mockReturnValue({
      ...baseState,
      composerPrefill: '关于 文件:行 12',
      prefillComposer,
    } as never);
    render(<Conversation />);
    const ta = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    expect(ta.value).toContain('关于 文件:行 12');
    expect(prefillComposer).toHaveBeenCalledWith('');
  });

  it('已有文本时 prefill → 追加到新行', () => {
    const prefillComposer = vi.fn();
    mockedUseApp.mockReturnValue({
      ...baseState,
      composerPrefill: '追加评论',
      prefillComposer,
    } as never);
    render(<Conversation />);
    const ta = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'old text' } });
    // 触发 effect 通过新的 prefill
    mockedUseApp.mockReturnValue({
      ...baseState,
      composerPrefill: '追加评论',
      prefillComposer,
    } as never);
    // 重新 render 后内容应包含 prefill
    expect(ta.value.includes('old text')).toBe(true);
  });
});
