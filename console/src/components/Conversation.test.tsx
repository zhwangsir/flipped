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
