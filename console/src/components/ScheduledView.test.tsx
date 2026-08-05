/**
 * ScheduledView.test.tsx · M187 前端 TDD
 *
 * M187.1 — TaskForm cron 选项/输入/基础校验/提交 payload;TaskCard cron badge
 * M187.2 — TaskCard 编辑按钮 → 行内 TaskForm 预填,提交走 editTask,
 *          成功收起 / 失败红字 role="alert" 不收起;once run_at ISO ↔ datetime-local 转换
 *
 * mock 惯例同 FailurePanel.test:vi.mock('../store') 只提供本视图用到的字段。
 */
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, act } from '@testing-library/react';
import { ScheduledView } from './ScheduledView';
import type { ScheduledTask } from '../types';

vi.mock('../store', () => ({
  useApp: vi.fn(),
}));

import { useApp } from '../store';

const mockedUseApp = vi.mocked(useApp);

// 与 Sidebar.test 同款的任务构造器(M187 起含 cron 字段)
function makeTask(partial: Partial<ScheduledTask> & { id: string }): ScheduledTask {
  return {
    title: '任务',
    prompt: '做点事',
    mode: 'chat',
    model: 'coder',
    kind: 'once',
    run_at: null,
    every_minutes: null,
    cron: null,
    enabled: true,
    next_run_at: null,
    last_run_at: null,
    last_status: null,
    last_session_id: null,
    run_count: 0,
    created_at: new Date().toISOString(),
    ...partial,
  };
}

/** ISO → datetime-local input 值(与组件内转换同逻辑,测试独立再算一遍)。 */
function isoToLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

let addTask: ReturnType<typeof vi.fn>;
let editTask: ReturnType<typeof vi.fn>;

function stateWith(tasks: ScheduledTask[]) {
  return {
    tasks,
    loadTasks: vi.fn(async () => {}),
    addTask,
    editTask,
    removeTask: vi.fn(async () => {}),
    toggleTaskEnabled: vi.fn(async () => {}),
    selectSession: vi.fn(),
  } as never;
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  addTask = vi.fn(async () => {});
  editTask = vi.fn(async () => {});
  mockedUseApp.mockReturnValue(stateWith([]));
});

/** 打开「新建任务」行内表单。 */
function openCreateForm() {
  render(<ScheduledView />);
  fireEvent.click(screen.getByText('新建任务'));
}

describe('ScheduledView · M187.1 cron', () => {
  it('kind select 含第三项 cron 表达式', () => {
    openCreateForm();
    const select = screen.getByLabelText('任务类型') as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(['once', 'interval', 'cron']);
  });

  it('选 cron → 出现 cron 输入框,运行时间/间隔分钟输入消失;切回 interval → 间隔分钟回归', () => {
    openCreateForm();
    const select = screen.getByLabelText('任务类型');
    // 默认 once → 运行时间
    expect(screen.getByLabelText('运行时间')).toBeInTheDocument();
    // interval → 间隔分钟
    fireEvent.change(select, { target: { value: 'interval' } });
    expect(screen.getByLabelText('间隔分钟')).toBeInTheDocument();
    expect(screen.queryByLabelText('运行时间')).toBeNull();
    // cron → 文本输入,前两者消失
    fireEvent.change(select, { target: { value: 'cron' } });
    const cronInput = screen.getByLabelText('cron 表达式') as HTMLInputElement;
    expect(cronInput.placeholder).toBe('0 9 * * 1-5');
    expect(screen.queryByLabelText('运行时间')).toBeNull();
    expect(screen.queryByLabelText('间隔分钟')).toBeNull();
  });

  it('cron 提交 payload 正确(cron 字段 trim,run_at/every_minutes 为 null)', async () => {
    openCreateForm();
    fireEvent.change(screen.getByLabelText('任务标题'), { target: { value: '晨报' } });
    fireEvent.change(screen.getByLabelText('任务内容'), { target: { value: '写日报' } });
    fireEvent.change(screen.getByLabelText('任务类型'), { target: { value: 'cron' } });
    fireEvent.change(screen.getByLabelText('cron 表达式'), { target: { value: '  0 9 * * 1-5  ' } });
    fireEvent.click(screen.getByText('创建'));
    await waitFor(() => expect(addTask).toHaveBeenCalledTimes(1));
    expect(addTask).toHaveBeenCalledWith({
      title: '晨报',
      prompt: '写日报',
      mode: 'chat',
      kind: 'cron',
      run_at: null,
      every_minutes: null,
      cron: '0 9 * * 1-5',
    });
  });

  it('cron 为空 → 红字提示 5 段且不提交', async () => {
    openCreateForm();
    fireEvent.change(screen.getByLabelText('任务标题'), { target: { value: 't' } });
    fireEvent.change(screen.getByLabelText('任务内容'), { target: { value: 'p' } });
    fireEvent.change(screen.getByLabelText('任务类型'), { target: { value: 'cron' } });
    fireEvent.click(screen.getByText('创建'));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '请输入 5 段 cron 表达式（分 时 日 月 周）'
    );
    expect(addTask).not.toHaveBeenCalled();
  });

  it('cron 非 5 段(如 3 段) → 红字且不提交', async () => {
    openCreateForm();
    fireEvent.change(screen.getByLabelText('任务标题'), { target: { value: 't' } });
    fireEvent.change(screen.getByLabelText('任务内容'), { target: { value: 'p' } });
    fireEvent.change(screen.getByLabelText('任务类型'), { target: { value: 'cron' } });
    fireEvent.change(screen.getByLabelText('cron 表达式'), { target: { value: '* * *' } });
    fireEvent.click(screen.getByText('创建'));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '请输入 5 段 cron 表达式（分 时 日 月 周）'
    );
    expect(addTask).not.toHaveBeenCalled();
  });

  it('TaskCard kind=cron → badge 显示 cron 表达式文本', () => {
    mockedUseApp.mockReturnValue(stateWith([makeTask({ id: 't1', kind: 'cron', cron: '0 9 * * 1-5' })]));
    render(<ScheduledView />);
    expect(screen.getByText('cron 0 9 * * 1-5')).toBeInTheDocument();
  });

  it('TaskCard kind=once/interval badge 现状保留(一次性 / 每 N 分钟)', () => {
    mockedUseApp.mockReturnValue(
      stateWith([
        makeTask({ id: 't1', kind: 'once', title: '甲' }),
        makeTask({ id: 't2', kind: 'interval', every_minutes: 45, title: '乙' }),
      ])
    );
    render(<ScheduledView />);
    expect(screen.getByText('一次性')).toBeInTheDocument();
    expect(screen.getByText('每 45 分钟')).toBeInTheDocument();
  });
});

describe('ScheduledView · M187.2 任务编辑', () => {
  const cronTask = () =>
    makeTask({
      id: 't1',
      title: '旧标题',
      prompt: '旧内容',
      mode: 'agent',
      kind: 'cron',
      cron: '*/5 * * * *',
    });

  it('点「编辑」→ 行内表单预填现值(title/prompt/kind/cron/mode),提交按钮文案「保存」', () => {
    mockedUseApp.mockReturnValue(stateWith([cronTask()]));
    render(<ScheduledView />);
    fireEvent.click(screen.getByText('编辑'));
    expect(screen.getByLabelText('任务标题')).toHaveValue('旧标题');
    expect(screen.getByLabelText('任务内容')).toHaveValue('旧内容');
    expect(screen.getByLabelText('任务类型')).toHaveValue('cron');
    expect(screen.getByLabelText('cron 表达式')).toHaveValue('*/5 * * * *');
    expect(screen.getByLabelText('运行模式')).toHaveValue('agent');
    expect(screen.getByText('保存')).toBeInTheDocument();
  });

  it('编辑提交 → editTask 被调且 body 正确;成功 → 表单收起', async () => {
    mockedUseApp.mockReturnValue(stateWith([cronTask()]));
    render(<ScheduledView />);
    fireEvent.click(screen.getByText('编辑'));
    fireEvent.change(screen.getByLabelText('任务标题'), { target: { value: '新标题' } });
    fireEvent.click(screen.getByText('保存'));
    await waitFor(() => expect(editTask).toHaveBeenCalledTimes(1));
    expect(editTask).toHaveBeenCalledWith('t1', {
      title: '新标题',
      prompt: '旧内容',
      mode: 'agent',
      kind: 'cron',
      run_at: null,
      every_minutes: null,
      cron: '*/5 * * * *',
    });
    expect(addTask).not.toHaveBeenCalled();
    // 成功 → 收起编辑表单
    await waitFor(() => expect(screen.queryByLabelText('任务标题')).toBeNull());
  });

  it('编辑失败 → 红字 role="alert" 且表单不收起', async () => {
    editTask.mockRejectedValueOnce(new Error('HTTP 422: cron 表达式非法'));
    mockedUseApp.mockReturnValue(stateWith([cronTask()]));
    render(<ScheduledView />);
    fireEvent.click(screen.getByText('编辑'));
    fireEvent.click(screen.getByText('保存'));
    expect(await screen.findByRole('alert')).toHaveTextContent('422');
    // 表单不收起,可继续改
    expect(screen.getByLabelText('任务标题')).toBeInTheDocument();
  });

  it('编辑提交中 → 按钮 disabled 且文案「保存中…」', async () => {
    let release!: () => void;
    editTask.mockImplementationOnce(
      () => new Promise<void>((resolve) => { release = resolve; })
    );
    mockedUseApp.mockReturnValue(stateWith([cronTask()]));
    render(<ScheduledView />);
    fireEvent.click(screen.getByText('编辑'));
    fireEvent.click(screen.getByText('保存'));
    const busyBtn = await screen.findByText('保存中…');
    expect(busyBtn).toBeDisabled();
    await act(async () => {
      release();
    });
    await waitFor(() => expect(screen.queryByLabelText('任务标题')).toBeNull());
  });

  it('once 任务编辑 → run_at ISO 转 datetime-local 预填,提交转回 ISO(round-trip)', async () => {
    const iso = '2026-08-06T01:30:00.000Z';
    mockedUseApp.mockReturnValue(
      stateWith([makeTask({ id: 't2', kind: 'once', run_at: iso })])
    );
    render(<ScheduledView />);
    fireEvent.click(screen.getByText('编辑'));
    expect(screen.getByLabelText('运行时间')).toHaveValue(isoToLocalInput(iso));
    fireEvent.click(screen.getByText('保存'));
    await waitFor(() => expect(editTask).toHaveBeenCalledTimes(1));
    expect(editTask).toHaveBeenCalledWith(
      't2',
      expect.objectContaining({ kind: 'once', run_at: iso, every_minutes: null, cron: null })
    );
  });

  it('interval 任务编辑 → 预填间隔分钟,提交 every_minutes 正确', async () => {
    mockedUseApp.mockReturnValue(
      stateWith([makeTask({ id: 't3', kind: 'interval', every_minutes: 45 })])
    );
    render(<ScheduledView />);
    fireEvent.click(screen.getByText('编辑'));
    expect(screen.getByLabelText('间隔分钟')).toHaveValue(45);
    fireEvent.click(screen.getByText('保存'));
    await waitFor(() => expect(editTask).toHaveBeenCalledTimes(1));
    expect(editTask).toHaveBeenCalledWith(
      't3',
      expect.objectContaining({ kind: 'interval', every_minutes: 45, run_at: null, cron: null })
    );
  });
});
