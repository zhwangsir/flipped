import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { Assistant } from './Assistant';

// M151.4 — Assistant 视图单测:覆盖空态/气泡对齐/Enter 发送/Shift+Enter 换行/
// /clear 清空/工具卡折叠/审批 Allow once 调 approve 共 6 例。
vi.mock('../store', () => ({ useApp: vi.fn() }));

import { useApp } from '../store';

const mockedUseApp = vi.mocked(useApp);

const baseState = {
  assistantTurns: [],
  assistantBusy: false,
  assistantError: null,
  sendAssistantMessage: vi.fn(async () => {}),
  approveAssistant: vi.fn(async () => {}),
  rejectAssistant: vi.fn(async () => {}),
  clearAssistantTurns: vi.fn(),
  selectedSessionId: 'sess-1',
  selectedMode: 'agent',
  setMode: vi.fn(),
  selectedModel: 'coder',
  setModel: vi.fn(),
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  mockedUseApp.mockReturnValue({ ...baseState } as never);
});

describe('Assistant — 空态与气泡', () => {
  it('空态显示 hero(无 turns)', () => {
    render(<Assistant />);
    const empty = screen.getByTestId('assistant-empty');
    expect(empty.textContent).toContain('我们能帮你构建什么');
  });

  it('user 右对齐 + assistant 左对齐(indigo/coral 强调)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [
        { role: 'user', text: '帮我写个 hello', tools: [], created_at: '2026-07-25T00:00:00Z' },
        { role: 'assistant', text: '好的,开始写', tools: [], created_at: '2026-07-25T00:00:01Z' },
      ],
    } as never);
    render(<Assistant />);
    const userMsg = screen.getByTestId('assistant-msg-user');
    const asstMsg = screen.getByTestId('assistant-msg-assistant');
    // user 气泡文本正确
    expect(userMsg.textContent).toContain('帮我写个 hello');
    expect(asstMsg.textContent).toContain('好的,开始写');
    // CSS 类对齐(右对齐/左对齐由 .user/.assistant 类承担)
    expect(userMsg.className).toContain('user');
    expect(asstMsg.className).toContain('assistant');
  });
});

describe('Assistant — Composer 交互', () => {
  it('Enter 发送 / Shift+Enter 换行', () => {
    const sendAssistantMessage = vi.fn(async (_text: string, _mode?: string) => {});
    mockedUseApp.mockReturnValue({ ...baseState, sendAssistantMessage } as never);
    render(<Assistant />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;

    // Enter 发送
    fireEvent.change(ta, { target: { value: 'hello world' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(sendAssistantMessage).toHaveBeenCalledTimes(1);
    expect(sendAssistantMessage.mock.calls[0][0]).toBe('hello world');
    // 发送后输入框清空
    expect(ta.value).toBe('');

    // Shift+Enter 换行(不触发发送)
    fireEvent.change(ta, { target: { value: 'line1' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: true });
    expect(sendAssistantMessage).toHaveBeenCalledTimes(1); // 仍是 1 次
    // 输入框内容不被 keyDown 改写,但 Shift+Enter 不清空 = 保留可继续输入
    expect(ta.value).toBe('line1');
  });

  it('/clear 清空当前对话', () => {
    const clearAssistantTurns = vi.fn();
    const sendAssistantMessage = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [
        { role: 'user', text: '旧消息', tools: [], created_at: '2026-07-25T00:00:00Z' },
      ],
      clearAssistantTurns,
      sendAssistantMessage,
    } as never);
    render(<Assistant />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;

    // 输入 /clear + Enter
    fireEvent.change(ta, { target: { value: '/clear' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    // /clear 触发 clearAssistantTurns,不触发 sendAssistantMessage
    expect(clearAssistantTurns).toHaveBeenCalledTimes(1);
    expect(sendAssistantMessage).not.toHaveBeenCalled();
    // 输入框清空
    expect(ta.value).toBe('');
  });
});

describe('Assistant — 工具卡与审批', () => {
  it('tool turn 用 ToolCard 折叠渲染(ok 默认折叠)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [
        {
          role: 'tool',
          tools: [
            {
              tool: 'terminal',
              status: 'ok',
              summary: '$ ls',
              output: 'file1.txt\nfile2.txt',
            },
          ],
          created_at: '2026-07-25T00:00:00Z',
        },
      ],
    } as never);
    render(<Assistant />);
    // 工具卡存在
    const card = screen.getByTestId('assistant-tool-card');
    expect(card.className).toContain('ok');
    // 默认折叠(无 body)
    expect(screen.queryByTestId('assistant-tool-body')).toBeNull();
    // 点击展开
    fireEvent.click(screen.getByTestId('assistant-tool-head'));
    expect(screen.getByTestId('assistant-tool-body')).toBeTruthy();
  });

  it('审批 Allow once 调 approveAssistant(selectedSessionId)', () => {
    const approveAssistant = vi.fn(async (_sid: string) => {});
    mockedUseApp.mockReturnValue({
      ...baseState,
      selectedSessionId: 'sess-42',
      assistantTurns: [
        {
          role: 'approval',
          approval: { action: 'rm -rf /tmp/cache', risk: 'high' },
          tools: [],
          created_at: '2026-07-25T00:00:00Z',
        },
      ],
      approveAssistant,
    } as never);
    render(<Assistant />);
    // 审批卡可见 + 显示动作文本
    const approval = screen.getByTestId('assistant-approval');
    expect(approval.textContent).toContain('rm -rf /tmp/cache');
    // 点击 Allow once
    fireEvent.click(screen.getByTestId('assistant-approve-btn'));
    expect(approveAssistant).toHaveBeenCalledTimes(1);
    expect(approveAssistant.mock.calls[0][0]).toBe('sess-42');
  });
});
