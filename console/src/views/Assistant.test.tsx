import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
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
  assistantStream: { text: '', active: false },
  sendAssistantMessage: vi.fn(async () => {}),
  approveAssistant: vi.fn(async () => {}),
  rejectAssistant: vi.fn(async () => {}),
  clearAssistantTurns: vi.fn(),
  appendAssistantLocalTurn: vi.fn(),
  compactAssistant: vi.fn(async () => {}),
  undoAssistant: vi.fn(async () => ({ ok: true, session_id: 'sess-1', restored: false, deleted: [] })),
  editAssistantMessage: vi.fn(async () => {}),
  changedFiles: [],
  selectedSessionId: 'sess-1',
  selectedMode: 'agent',
  setMode: vi.fn(),
  selectedModel: 'coder',
  setModel: vi.fn(),
  // M176 — Goal 模式(合成 busy + /goal action)
  composerBusy: false,
  sendAssistantGoal: vi.fn(async () => {}),
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

  // M165.2a — Always 审批按钮:scope='always' 透传
  it('审批 Always 按钮 → approveAssistant(sid, "always")', () => {
    const approveAssistant = vi.fn(async (_sid: string, _scope?: string) => {});
    mockedUseApp.mockReturnValue({
      ...baseState,
      selectedSessionId: 'sess-42',
      assistantTurns: [
        {
          role: 'approval',
          approval: { action: 'git push --force', risk: 'high' },
          tools: [],
          created_at: '2026-07-25T00:00:00Z',
        },
      ],
      approveAssistant,
    } as never);
    render(<Assistant />);
    fireEvent.click(screen.getByTestId('assistant-approve-always-btn'));
    expect(approveAssistant).toHaveBeenCalledTimes(1);
    expect(approveAssistant.mock.calls[0][0]).toBe('sess-42');
    expect(approveAssistant.mock.calls[0][1]).toBe('always');
  });
});

// M166.4 — token 级流式气泡(chat/plan 直聊:turns 末尾渲染 assistantStream)
describe('Assistant — M166.4 token 流式气泡', () => {
  it('assistantStream active+text → 渲染 data-testid=assistant-streaming 且文本正确', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [
        { role: 'user', text: '给我写首诗', tools: [], created_at: '2026-07-25T00:00:00Z' },
      ],
      assistantStream: { text: '床前明月光', active: true },
    } as never);
    render(<Assistant />);
    const el = screen.getByTestId('assistant-streaming');
    expect(el.textContent).toContain('床前明月光');
    // 与 assistant turn 同视觉:.assistant-msg.assistant
    expect(el.className).toContain('assistant-msg');
    expect(el.className).toContain('assistant');
  });

  it('assistantStream inactive → 不渲染流式气泡', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [
        { role: 'assistant', text: '已完成', tools: [], created_at: '2026-07-25T00:00:00Z' },
      ],
      assistantStream: { text: '', active: false },
    } as never);
    render(<Assistant />);
    expect(screen.queryByTestId('assistant-streaming')).toBeNull();
  });

  it('assistantStream active 但 text 为空 → 不渲染流式气泡', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [
        { role: 'user', text: 'hi', tools: [], created_at: '2026-07-25T00:00:00Z' },
      ],
      assistantStream: { text: '', active: true },
    } as never);
    render(<Assistant />);
    expect(screen.queryByTestId('assistant-streaming')).toBeNull();
  });

  it('无 turns 但流式中 → 不显示空态 hero,渲染流式气泡', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [],
      assistantStream: { text: '第一个 token', active: true },
    } as never);
    render(<Assistant />);
    expect(screen.queryByTestId('assistant-empty')).toBeNull();
    expect(screen.getByTestId('assistant-streaming').textContent).toContain('第一个 token');
  });
});

// M165.1a — slash 命令接线:/help /mode /files /compact
describe('Assistant — slash 命令接线', () => {
  it('/help 追加帮助 turn(列出全部命令)', () => {
    const appendAssistantLocalTurn = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, appendAssistantLocalTurn } as never);
    render(<Assistant />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/help' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(appendAssistantLocalTurn).toHaveBeenCalledTimes(1);
    const text = appendAssistantLocalTurn.mock.calls[0][0] as string;
    expect(text).toContain('/clear');
    expect(text).toContain('/compact');
    expect(text).toContain('/mode');
    expect(text).toContain('/files');
    expect(text).toContain('/help');
  });

  it('/mode 从 agent 循环切到 chat 并追加确认 turn', () => {
    const setMode = vi.fn();
    const appendAssistantLocalTurn = vi.fn();
    mockedUseApp.mockReturnValue({
      ...baseState,
      selectedMode: 'agent',
      setMode,
      appendAssistantLocalTurn,
    } as never);
    render(<Assistant />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/mode' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(setMode).toHaveBeenCalledWith('chat');
    expect(appendAssistantLocalTurn).toHaveBeenCalledTimes(1);
    expect(appendAssistantLocalTurn.mock.calls[0][0]).toContain('chat');
  });

  it('/mode 从 plan 循环回 auto', () => {
    const setMode = vi.fn();
    mockedUseApp.mockReturnValue({
      ...baseState,
      selectedMode: 'plan',
      setMode,
    } as never);
    render(<Assistant />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/mode' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(setMode).toHaveBeenCalledWith('auto');
  });

  it('/files 无变更 → 追加「暂无文件变更记录」turn', () => {
    const appendAssistantLocalTurn = vi.fn();
    mockedUseApp.mockReturnValue({
      ...baseState,
      changedFiles: [],
      appendAssistantLocalTurn,
    } as never);
    render(<Assistant />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/files' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(appendAssistantLocalTurn).toHaveBeenCalledWith('暂无文件变更记录');
  });

  it('/compact 无选中会话 → 提示先开始对话,不调 compactAssistant', () => {
    const appendAssistantLocalTurn = vi.fn();
    const compactAssistant = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({
      ...baseState,
      selectedSessionId: null,
      appendAssistantLocalTurn,
      compactAssistant,
    } as never);
    render(<Assistant />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/compact' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(appendAssistantLocalTurn).toHaveBeenCalledWith('请先开始对话再压缩上下文');
    expect(compactAssistant).not.toHaveBeenCalled();
  });

  it('/compact 有会话 → 调 compactAssistant(sid)', () => {
    const compactAssistant = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({
      ...baseState,
      selectedSessionId: 'sess-9',
      compactAssistant,
    } as never);
    render(<Assistant />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/compact' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(compactAssistant).toHaveBeenCalledWith('sess-9');
  });
});

// M168.2 — /undo 撤销最近一轮 agent 文件改动(对标 opencode /undo)
describe('Assistant — /undo 命令', () => {
  it('/undo 无选中会话 → 提示先开始对话,不调 undoAssistant', () => {
    const appendAssistantLocalTurn = vi.fn();
    const undoAssistant = vi.fn(async () => ({ ok: true, session_id: 's', restored: false, deleted: [] }));
    mockedUseApp.mockReturnValue({
      ...baseState,
      selectedSessionId: null,
      appendAssistantLocalTurn,
      undoAssistant,
    } as never);
    render(<Assistant />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/undo' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(appendAssistantLocalTurn).toHaveBeenCalledWith('请先开始对话再撤销改动');
    expect(undoAssistant).not.toHaveBeenCalled();
  });

  it('/undo 成功(有回滚+删除) → 调 undoAssistant(sid) 并追加结果摘要 turn', async () => {
    const appendAssistantLocalTurn = vi.fn();
    const undoAssistant = vi.fn(async () => ({
      ok: true,
      session_id: 'sess-9',
      restored: true,
      deleted: ['a.ts', 'b.ts'],
    }));
    mockedUseApp.mockReturnValue({
      ...baseState,
      selectedSessionId: 'sess-9',
      appendAssistantLocalTurn,
      undoAssistant,
    } as never);
    render(<Assistant />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/undo' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(undoAssistant).toHaveBeenCalledWith('sess-9');
    await waitFor(() => expect(appendAssistantLocalTurn).toHaveBeenCalledTimes(1));
    const text = appendAssistantLocalTurn.mock.calls[0][0] as string;
    expect(text).toContain('已撤销最近一轮改动');
    expect(text).toContain('回滚 tracked 文件');
    expect(text).toContain('2 个新增文件');
    expect(text).toContain('a.ts');
    expect(text).toContain('b.ts');
  });

  it('/undo 成功(快照无差异) → 追加「无文件变动」turn', async () => {
    const appendAssistantLocalTurn = vi.fn();
    const undoAssistant = vi.fn(async () => ({
      ok: true,
      session_id: 'sess-9',
      restored: false,
      deleted: [],
    }));
    mockedUseApp.mockReturnValue({
      ...baseState,
      selectedSessionId: 'sess-9',
      appendAssistantLocalTurn,
      undoAssistant,
    } as never);
    render(<Assistant />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/undo' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    await waitFor(() => expect(appendAssistantLocalTurn).toHaveBeenCalledTimes(1));
    expect(appendAssistantLocalTurn.mock.calls[0][0]).toContain('快照无差异,无文件变动');
  });

  it('/undo 失败 → 追加错误 turn(含 err.message)', async () => {
    const appendAssistantLocalTurn = vi.fn();
    const undoAssistant = vi.fn(async () => {
      throw new Error('HTTP 409: 运行中不能撤销');
    });
    mockedUseApp.mockReturnValue({
      ...baseState,
      selectedSessionId: 'sess-9',
      appendAssistantLocalTurn,
      undoAssistant,
    } as never);
    render(<Assistant />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/undo' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    await waitFor(() => expect(appendAssistantLocalTurn).toHaveBeenCalledTimes(1));
    expect(appendAssistantLocalTurn.mock.calls[0][0]).toBe('撤销失败:HTTP 409: 运行中不能撤销');
  });

  it('/help 文本含 /undo', () => {
    const appendAssistantLocalTurn = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, appendAssistantLocalTurn } as never);
    render(<Assistant />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/help' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(appendAssistantLocalTurn).toHaveBeenCalledTimes(1);
    expect(appendAssistantLocalTurn.mock.calls[0][0]).toContain('/undo');
  });
});

// M169.2 — token 用量渲染:assistant turn 逐条 usage 行 + 头部 session 合计 chip
describe('Assistant — M169.2 token 用量渲染', () => {
  it('assistant turn 带 usage → 渲染 turn-usage 行(↑ prompt · ↓ completion)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [
        {
          role: 'assistant',
          text: '完成了',
          tools: [],
          created_at: '2026-07-25T00:00:01Z',
          usage: { prompt: 12345, completion: 3420, calls: 1 },
        },
      ],
    } as never);
    render(<Assistant />);
    const el = screen.getByTestId('turn-usage');
    expect(el.textContent).toContain('↑ 12.3k');
    expect(el.textContent).toContain('↓ 3.4k');
  });

  it('assistant turn 无 usage → 不渲染 turn-usage', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [
        { role: 'assistant', text: '好的', tools: [], created_at: '2026-07-25T00:00:01Z' },
      ],
    } as never);
    render(<Assistant />);
    expect(screen.queryByTestId('turn-usage')).toBeNull();
  });

  it('user turn 带 usage(防御) → 不渲染 turn-usage', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [
        {
          role: 'user',
          text: '你好',
          tools: [],
          created_at: '2026-07-25T00:00:00Z',
          usage: { prompt: 100, completion: 50, calls: 1 },
        },
      ],
    } as never);
    render(<Assistant />);
    expect(screen.queryByTestId('turn-usage')).toBeNull();
  });

  it('两条带 usage 的 assistant turn → session-usage 显示合计,逐条行各渲染一条', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [
        {
          role: 'assistant',
          text: '第一轮',
          tools: [],
          created_at: '2026-07-25T00:00:01Z',
          usage: { prompt: 12345, completion: 3420, calls: 1 },
        },
        {
          role: 'assistant',
          text: '第二轮',
          tools: [],
          created_at: '2026-07-25T00:00:02Z',
          usage: { prompt: 1000, completion: 1000, calls: 1 },
        },
      ],
    } as never);
    render(<Assistant />);
    const el = screen.getByTestId('session-usage');
    // 合计 prompt 13345 → 13.3k;completion 4420 → 4.4k
    expect(el.textContent).toContain('↑ 13.3k');
    expect(el.textContent).toContain('↓ 4.4k');
    expect(screen.getAllByTestId('turn-usage').length).toBe(2);
  });

  it('全部 turn 无 usage → 不渲染 session-usage', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [
        { role: 'user', text: 'hi', tools: [], created_at: '2026-07-25T00:00:00Z' },
        { role: 'assistant', text: '你好', tools: [], created_at: '2026-07-25T00:00:01Z' },
      ],
    } as never);
    render(<Assistant />);
    expect(screen.queryByTestId('session-usage')).toBeNull();
  });
});

// M167.4 — busy 交互:停止按钮可见可点 + Enter 入队不发送(集成层,mock store)
describe('Assistant — M167.4 busy 排队与停止(集成)', () => {
  it('busy 时 Composer 渲染停止按钮,点击调 stopAssistantTask', () => {
    const stopAssistantTask = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantBusy: true,
      // M176 — Assistant 传 Composer 的是合成值 composerBusy(store 内 = assistantBusy||goalActive),mock 需同步
      composerBusy: true,
      assistantQueue: [],
      stopAssistantTask,
    } as never);
    render(<Assistant />);
    const btn = screen.getByTestId('composer-stop-btn');
    fireEvent.click(btn);
    expect(stopAssistantTask).toHaveBeenCalledTimes(1);
  });

  it('busy 时 Enter 入队而不调 sendAssistantMessage', () => {
    const enqueueAssistantMessage = vi.fn();
    const sendAssistantMessage = vi.fn(async (_text: string, _mode?: string) => {});
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantBusy: true,
      composerBusy: true,
      assistantQueue: [],
      enqueueAssistantMessage,
      sendAssistantMessage,
    } as never);
    render(<Assistant />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '排队消息' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(enqueueAssistantMessage).toHaveBeenCalledWith('排队消息');
    expect(sendAssistantMessage).not.toHaveBeenCalled();
  });

  it('busy 时 Esc 中断 → 调 stopAssistantTask', () => {
    const stopAssistantTask = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantBusy: true,
      composerBusy: true,
      assistantQueue: [],
      stopAssistantTask,
    } as never);
    render(<Assistant />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.keyDown(ta, { key: 'Escape' });
    expect(stopAssistantTask).toHaveBeenCalledTimes(1);
  });

  it('assistantQueue 非空 → 渲染排队 chips,× 按 index 移除', () => {
    const removeAssistantQueued = vi.fn();
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantBusy: true,
      composerBusy: true,
      assistantQueue: ['第一条排队', '第二条排队'],
      removeAssistantQueued,
    } as never);
    render(<Assistant />);
    expect(screen.getByTestId('composer-queue')).toBeTruthy();
    expect(screen.getByTestId('queue-chip-0').textContent).toContain('第一条排队');
    fireEvent.click(screen.getByTestId('queue-remove-0'));
    expect(removeAssistantQueued).toHaveBeenCalledWith(0);
  });
});

// M174-C — user 气泡「编辑并重跑」:hover 编辑钮 → 行内编辑态 → 调 store.editAssistantMessage
describe('Assistant — M174 user 消息编辑重跑', () => {
  const userTurn = {
    role: 'user' as const,
    text: '帮我写个 hello',
    tools: [],
    event_id: 'evt-1',
    created_at: '2026-07-25T00:00:00Z',
  };

  it('user turn 带 event_id 且非 busy → 渲染编辑按钮', () => {
    mockedUseApp.mockReturnValue({ ...baseState, assistantTurns: [userTurn] } as never);
    render(<Assistant />);
    expect(screen.getByTestId('umsg-edit-btn')).toBeTruthy();
  });

  it('点击编辑按钮 → 出现 textarea 且值为原文', () => {
    mockedUseApp.mockReturnValue({ ...baseState, assistantTurns: [userTurn] } as never);
    render(<Assistant />);
    fireEvent.click(screen.getByTestId('umsg-edit-btn'));
    const ta = screen.getByTestId('umsg-edit-input') as HTMLTextAreaElement;
    expect(ta.value).toBe('帮我写个 hello');
  });

  it('改文本点「重新执行」→ 调 editAssistantMessage(sessionId, event_id, 新文本)', () => {
    const editAssistantMessage = vi.fn(async (_sid: string, _eid: string, _text: string) => {});
    mockedUseApp.mockReturnValue({ ...baseState, assistantTurns: [userTurn], editAssistantMessage } as never);
    render(<Assistant />);
    fireEvent.click(screen.getByTestId('umsg-edit-btn'));
    const ta = screen.getByTestId('umsg-edit-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '改成 bye' } });
    fireEvent.click(screen.getByTestId('umsg-edit-confirm'));
    expect(editAssistantMessage).toHaveBeenCalledTimes(1);
    expect(editAssistantMessage).toHaveBeenCalledWith('sess-1', 'evt-1', '改成 bye');
  });

  it('textarea 内 Enter 确认;Shift+Enter 换行不确认', () => {
    const editAssistantMessage = vi.fn(async (_sid: string, _eid: string, _text: string) => {});
    mockedUseApp.mockReturnValue({ ...baseState, assistantTurns: [userTurn], editAssistantMessage } as never);
    render(<Assistant />);
    fireEvent.click(screen.getByTestId('umsg-edit-btn'));
    const ta = screen.getByTestId('umsg-edit-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '第一行' } });
    // Shift+Enter:不确认,仍在编辑态
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: true });
    expect(editAssistantMessage).not.toHaveBeenCalled();
    expect(screen.getByTestId('umsg-edit-input')).toBeTruthy();
    // Enter(不含 shift):确认提交
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(editAssistantMessage).toHaveBeenCalledTimes(1);
    expect(editAssistantMessage).toHaveBeenCalledWith('sess-1', 'evt-1', '第一行');
  });

  it('Esc 退出编辑态,不调 action,气泡恢复原文', () => {
    const editAssistantMessage = vi.fn(async (_sid: string, _eid: string, _text: string) => {});
    mockedUseApp.mockReturnValue({ ...baseState, assistantTurns: [userTurn], editAssistantMessage } as never);
    render(<Assistant />);
    fireEvent.click(screen.getByTestId('umsg-edit-btn'));
    const ta = screen.getByTestId('umsg-edit-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '改了一半' } });
    fireEvent.keyDown(ta, { key: 'Escape' });
    expect(editAssistantMessage).not.toHaveBeenCalled();
    expect(screen.queryByTestId('umsg-edit-input')).toBeNull();
    expect(screen.getByTestId('assistant-msg-user').textContent).toContain('帮我写个 hello');
  });

  it('点「取消」退出编辑态,不调 action,气泡恢复原文', () => {
    const editAssistantMessage = vi.fn(async (_sid: string, _eid: string, _text: string) => {});
    mockedUseApp.mockReturnValue({ ...baseState, assistantTurns: [userTurn], editAssistantMessage } as never);
    render(<Assistant />);
    fireEvent.click(screen.getByTestId('umsg-edit-btn'));
    fireEvent.click(screen.getByTestId('umsg-edit-cancel'));
    expect(editAssistantMessage).not.toHaveBeenCalled();
    expect(screen.queryByTestId('umsg-edit-input')).toBeNull();
    expect(screen.getByTestId('assistant-msg-user').textContent).toContain('帮我写个 hello');
  });

  it('assistantBusy=true → 不显示编辑按钮', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantBusy: true,
      assistantQueue: [],
      stopAssistantTask: vi.fn(async () => {}),
      assistantTurns: [userTurn],
    } as never);
    render(<Assistant />);
    expect(screen.getByTestId('assistant-msg-user').textContent).toContain('帮我写个 hello');
    expect(screen.queryByTestId('umsg-edit-btn')).toBeNull();
  });

  it('turn.event_id 缺失 → 不显示编辑按钮(向后兼容旧会话)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [{ role: 'user', text: '旧消息', tools: [], created_at: '2026-07-25T00:00:00Z' }],
    } as never);
    render(<Assistant />);
    expect(screen.getByTestId('assistant-msg-user').textContent).toContain('旧消息');
    expect(screen.queryByTestId('umsg-edit-btn')).toBeNull();
  });
});

// M175-C — user 气泡 @ 文件引用行:refs 元数据渲染路径/大小/状态
describe('Assistant — M175 user 消息 @ 引用行', () => {
  it('user turn 带 refs(ok) → 渲染路径与 "1.0KB"(bytes=1024)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [
        {
          role: 'user',
          text: '看下 @hello.py',
          tools: [],
          created_at: '2026-07-25T00:00:00Z',
          refs: [{ token: '@hello.py', path: 'hello.py', status: 'ok', bytes: 1024, truncated: false }],
        },
      ],
    } as never);
    render(<Assistant />);
    const ref = screen.getByTestId('umsg-ref-hello.py');
    expect(ref.textContent).toContain('hello.py');
    expect(ref.textContent).toContain('1.0KB');
    expect(ref.className).not.toContain('bad');
  });

  it('refs missing → 渲染「未找到」且带 bad 样式', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [
        {
          role: 'user',
          text: '看下 @ghost.py',
          tools: [],
          created_at: '2026-07-25T00:00:00Z',
          refs: [{ token: '@ghost.py', path: 'ghost.py', status: 'missing', bytes: 0, truncated: false }],
        },
      ],
    } as never);
    render(<Assistant />);
    const ref = screen.getByTestId('umsg-ref-ghost.py');
    expect(ref.textContent).toContain('未找到');
    expect(ref.className).toContain('bad');
  });

  it('无 refs → 不渲染 umsg-refs', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [
        { role: 'user', text: '普通消息', tools: [], created_at: '2026-07-25T00:00:00Z' },
      ],
    } as never);
    render(<Assistant />);
    expect(screen.queryByTestId('umsg-refs')).toBeNull();
  });
});

// M176 — Goal 模式:goal marker 四相位渲染 + /goal 提交接线 + composerBusy 驱动停止态
describe('Assistant — M176 Goal 模式', () => {
  it('goal turn 四相位渲染 marker(iter 含轮次+gap/achieved/exhausted/stopped)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [
        {
          role: 'goal',
          tools: [],
          goal: { phase: 'iter', objective: '修复 TS 错误', iteration: 2, max_iterations: 5, prompt: 'p', gap: '还差 3 处' },
          created_at: '2026-08-04T00:00:00Z',
        },
        {
          role: 'goal',
          tools: [],
          goal: { phase: 'achieved', objective: '修复 TS 错误', iteration: 3, max_iterations: 5, achieved: true },
          created_at: '2026-08-04T00:01:00Z',
        },
        {
          role: 'goal',
          tools: [],
          goal: { phase: 'exhausted', objective: '修复 TS 错误', iteration: 5, max_iterations: 5, reason: 'max_iter' },
          created_at: '2026-08-04T00:02:00Z',
        },
        {
          role: 'goal',
          tools: [],
          goal: { phase: 'stopped', objective: '修复 TS 错误', iteration: 1, max_iterations: 5 },
          created_at: '2026-08-04T00:03:00Z',
        },
      ],
    } as never);
    render(<Assistant />);
    const iter = screen.getByTestId('goal-marker-iter');
    expect(iter.textContent).toContain('目标迭代 2/5');
    expect(iter.textContent).toContain('还差 3 处');
    expect(iter.className).toContain('iter');
    const achieved = screen.getByTestId('goal-marker-achieved');
    expect(achieved.textContent).toContain('目标达成 · 第 3 轮');
    expect(achieved.className).toContain('achieved');
    const exhausted = screen.getByTestId('goal-marker-exhausted');
    expect(exhausted.textContent).toContain('目标未达成 · 达到最大轮次');
    expect(exhausted.className).toContain('exhausted');
    const stopped = screen.getByTestId('goal-marker-stopped');
    expect(stopped.textContent).toContain('目标已停止');
    expect(stopped.className).toContain('stopped');
  });

  it('goal turn 无 goal payload → 不渲染 marker(防御)', () => {
    mockedUseApp.mockReturnValue({
      ...baseState,
      assistantTurns: [
        { role: 'goal', tools: [], goal: null, created_at: '2026-08-04T00:00:00Z' },
      ],
    } as never);
    render(<Assistant />);
    expect(screen.queryByTestId('goal-marker-iter')).toBeNull();
    expect(screen.queryByTestId('goal-marker-achieved')).toBeNull();
  });

  it('/goal <目标> 提交 → sendAssistantGoal(经 Composer onGoal 接线),不走 sendAssistantMessage', () => {
    const sendAssistantGoal = vi.fn(async () => {});
    const sendAssistantMessage = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({ ...baseState, sendAssistantGoal, sendAssistantMessage } as never);
    render(<Assistant />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/goal 修复所有 TS 错误' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(sendAssistantGoal).toHaveBeenCalledWith('修复所有 TS 错误');
    expect(sendAssistantMessage).not.toHaveBeenCalled();
    expect(ta.value).toBe('');
  });

  it('composerBusy=true(goal 运行中)→ Composer 渲染停止按钮(M176 合成 busy)', () => {
    mockedUseApp.mockReturnValue({ ...baseState, composerBusy: true, assistantBusy: false } as never);
    render(<Assistant />);
    expect(screen.getByTestId('composer-stop-btn')).toBeTruthy();
    expect(screen.queryByTestId('assistant-send-btn')).toBeNull();
  });
});

// M181.2 — 移动远程控制入口:assistant-head 恒渲染 + 「远程」按钮弹 RemoteModal
describe('Assistant — M181.2 移动远程控制', () => {
  it('assistant-head 恒渲染(无 usage 也存在),含「远程」按钮', () => {
    mockedUseApp.mockReturnValue({ ...baseState, assistantTurns: [] } as never);
    render(<Assistant />);
    expect(document.querySelector('.assistant-head')).toBeTruthy();
    expect(screen.queryByTestId('session-usage')).toBeNull(); // 无 usage 不渲染 chip
    expect(screen.getByTestId('remote-open')).toBeTruthy();
  });

  it('点「远程」→ POST /remote/sessions 成功,出现 RemoteModal', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        token: 'tok-9',
        url: 'http://192.168.1.5:8011/r/tok-9',
        qr_url: '/api/v1/remote/tok-9/qr.svg',
        session_id: 'sess-1',
        session_title: '我的会话',
        expires_at: Math.floor(Date.now() / 1000) + 600,
        host_note: '',
      }),
      text: async () => '',
    }));
    vi.stubGlobal('fetch', fetchMock);
    try {
      mockedUseApp.mockReturnValue({ ...baseState, selectedSessionId: 'sess-1' } as never);
      render(<Assistant />);
      expect(screen.queryByRole('dialog')).toBeNull(); // 未点不渲染
      fireEvent.click(screen.getByTestId('remote-open'));
      await waitFor(() => expect(screen.getByRole('dialog')).toBeTruthy());
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const firstCall = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
      expect(firstCall[0]).toContain('/api/v1/remote/sessions');
      await waitFor(() => expect(screen.getByAltText('远程控制二维码')).toBeTruthy());
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
