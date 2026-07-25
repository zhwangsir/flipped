import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { FactoryPanel } from './FactoryPanel';

// M146 回归保护：启动工厂失败可见反馈 + 防重复提交。
vi.mock('../store', () => ({ useApp: vi.fn() }));
// router.navigate 调 window.location.hash；隔离副作用
vi.mock('../router', () => ({ navigate: vi.fn() }));

import { useApp } from '../store';
import { navigate } from '../router';
import type { FactoryDetail, FactorySummary, FactoryRcaHistoryResponse, QualityTrendResponse } from '../types';

const mockedUseApp = vi.mocked(useApp);
const mockedNavigate = vi.mocked(navigate);

const baseState = {
  factoryOpen: true,
  setFactoryOpen: vi.fn(),
  factories: [],
  factoryDetail: null,
  selectFactory: vi.fn(),
  createFactory: vi.fn(async () => 'factory-x'),
  resumeFactory: vi.fn(async () => {}),
  pauseFactory: vi.fn(async () => {}),
  refreshFactories: vi.fn(async () => {}),
  // FactoryDetailCard 不渲染时这两个折叠区不消费，但 useApp 是整对象 mock,备齐无害
  factoryRcaHistory: null,
  loadFactoryRcaHistory: vi.fn(async () => {}),
  factoryQualityTrend: null,
  loadFactoryQualityTrend: vi.fn(async () => {}),
};

function makeSummary(over: Partial<FactorySummary> = {}): FactorySummary {
  return {
    factory_id: 'fac-1',
    product_goal: '写一个 Python 计算器',
    status: 'running',
    iteration_count: 3,
    max_tasks: 10,
    created_at: new Date(Date.now() - 60_000).toISOString(),
    updated_at: new Date(Date.now() - 30_000).toISOString(),
    ...over,
  };
}

function makeDetail(over: Partial<FactoryDetail> = {}): FactoryDetail {
  return {
    factory_id: 'fac-detail-1',
    product_goal: '构建 calc.py 库',
    cwd: '/tmp/calc',
    status: 'running',
    roadmap: [],
    completed: [],
    failed: [],
    current_task_id: null,
    context_summary: '',
    iteration_count: 2,
    max_tasks: 5,
    created_at: new Date(Date.now() - 60_000).toISOString(),
    updated_at: new Date(Date.now() - 30_000).toISOString(),
    ...over,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  mockedUseApp.mockReturnValue({ ...baseState, createFactory: vi.fn(async () => 'factory-x') } as never);
});

const openCreate = () => {
  render(<FactoryPanel />);
  fireEvent.click(screen.getByTitle('新建工厂'));
  fireEvent.change(screen.getByPlaceholderText(/Python 计算器库/), { target: { value: 'goal' } });
  fireEvent.change(screen.getByPlaceholderText('/tmp/my-project'), { target: { value: '/tmp/x' } });
};

describe('FactoryPanel — 启动工厂（M146 P1）', () => {
  it('创建失败显示错误且卡片不关闭（此前静默,用户以为已启动）', async () => {
    const createFactory = vi.fn(async () => {
      throw new Error('HTTP 409: 已有运行中工厂');
    });
    mockedUseApp.mockReturnValue({ ...baseState, createFactory } as never);
    openCreate();

    fireEvent.click(screen.getByText('启动工厂'));
    const err = await screen.findByTestId('factory-create-error');
    expect(err.textContent).toContain('已有运行中工厂');
    // 卡片保留可重试
    expect(screen.getByText('新建工厂', { selector: '.factory-create-title' })).toBeTruthy();
  });

  it('创建中按钮禁用防重复提交', async () => {
    let release: (v: string) => void = () => {};
    const createFactory = vi.fn(() => new Promise<string>((r) => { release = r; }));
    mockedUseApp.mockReturnValue({ ...baseState, createFactory } as never);
    openCreate();

    const btn = screen.getByText('启动工厂') as HTMLButtonElement;
    fireEvent.click(btn);
    //  pending 期间按钮变「启动中…」且禁用
    const busyBtn = (await screen.findByText('启动中…')) as HTMLButtonElement;
    expect(busyBtn.disabled).toBe(true);
    fireEvent.click(busyBtn);
    expect(createFactory).toHaveBeenCalledTimes(1);
    release('factory-x');
  });

  it('创建成功后清空表单 + 关闭卡片', async () => {
    const createFactory = vi.fn(async () => 'fac-new');
    mockedUseApp.mockReturnValue({ ...baseState, createFactory } as never);
    openCreate();

    fireEvent.click(screen.getByText('启动工厂'));
    await vi.waitFor(() => expect(createFactory).toHaveBeenCalledWith('goal', '/tmp/x', 5));
    // 卡片关闭后回到列表空态
    await screen.findByText('暂无工厂');
  });

  it('创建失败抛非 Error 对象 → 显示默认错误', async () => {
    const createFactory = vi.fn(async () => {
      throw 'string err'; // 非 Error 实例
    });
    mockedUseApp.mockReturnValue({ ...baseState, createFactory } as never);
    openCreate();
    fireEvent.click(screen.getByText('启动工厂'));
    const err = await screen.findByTestId('factory-create-error');
    expect(err.textContent).toContain('操作失败');
  });

  it('取消按钮关闭创建卡片', () => {
    mockedUseApp.mockReturnValue({ ...baseState } as never);
    openCreate();
    fireEvent.click(screen.getByText('取消'));
    expect(screen.queryByText('新建工厂', { selector: '.factory-create-title' })).toBeNull();
  });

  it('maxTasks 输入非数字时回退到 5', () => {
    mockedUseApp.mockReturnValue({ ...baseState } as never);
    openCreate();
    const maxInput = screen.getByLabelText('最大任务数') as HTMLInputElement;
    fireEvent.change(maxInput, { target: { value: '' } });
    // Number('')===NaN → fallback 5
    // 重新输入有效值确认控件工作
    fireEvent.change(maxInput, { target: { value: '7' } });
    expect(maxInput.value).toBe('7');
  });
});

describe('FactoryPanel — 面板外壳与列表', () => {
  it('factoryOpen=false → 不渲染任何内容', () => {
    mockedUseApp.mockReturnValue({ ...baseState, factoryOpen: false } as never);
    const { container } = render(<FactoryPanel />);
    expect(container.firstChild).toBeNull();
  });

  it('刷新按钮触发 refreshFactories', () => {
    const refreshFactories = vi.fn(async () => {});
    mockedUseApp.mockReturnValue({ ...baseState, refreshFactories } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByTitle('刷新'));
    expect(refreshFactories).toHaveBeenCalled();
  });

  it('关闭按钮触发 navigate(assistant) + setFactoryOpen(false)', () => {
    const setFactoryOpen = vi.fn();
    mockedUseApp.mockReturnValue({ ...baseState, setFactoryOpen } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByLabelText('关闭'));
    expect(mockedNavigate).toHaveBeenCalledWith('assistant');
    expect(setFactoryOpen).toHaveBeenCalledWith(false);
  });

  it('空列表显示「暂无工厂」空态', () => {
    mockedUseApp.mockReturnValue({ ...baseState, factories: [] } as never);
    render(<FactoryPanel />);
    expect(screen.getByText('暂无工厂')).toBeTruthy();
    expect(screen.getByText(/创建一个 24h/)).toBeTruthy();
  });

  it('列表有数据 → 渲染 FactoryCard + 计数', () => {
    const factories = [
      makeSummary({ factory_id: 'fac-a', product_goal: 'goal A', status: 'running', iteration_count: 5, max_tasks: 10 }),
      makeSummary({ factory_id: 'fac-b', product_goal: 'goal B', status: 'paused', iteration_count: 2, max_tasks: 4 }),
    ];
    mockedUseApp.mockReturnValue({ ...baseState, factories } as never);
    render(<FactoryPanel />);
    expect(screen.getByText('2')).toBeTruthy(); // factory-count
    expect(screen.getByText('goal A')).toBeTruthy();
    expect(screen.getByText('goal B')).toBeTruthy();
    expect(screen.getByText('运行中')).toBeTruthy();
    expect(screen.getByText('已暂停')).toBeTruthy();
  });

  it('点击 FactoryCard → 调用 selectFactory(id)', () => {
    const selectFactory = vi.fn();
    const factories = [makeSummary({ factory_id: 'fac-click' })];
    mockedUseApp.mockReturnValue({ ...baseState, factories, selectFactory } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('写一个 Python 计算器'));
    expect(selectFactory).toHaveBeenCalledWith('fac-click');
  });

  it('FactoryCard 进度 0/max 时 pct=0 不崩', () => {
    const factories = [makeSummary({ max_tasks: 0, iteration_count: 0, product_goal: '' })];
    mockedUseApp.mockReturnValue({ ...baseState, factories } as never);
    render(<FactoryPanel />);
    // 空 goal → 显示「(未设定目标)」
    expect(screen.getByText('(未设定目标)')).toBeTruthy();
  });

  it('FactoryCard 未知 status → 原样回显', () => {
    const factories = [makeSummary({ status: 'weird' as never })];
    mockedUseApp.mockReturnValue({ ...baseState, factories } as never);
    render(<FactoryPanel />);
    expect(screen.getByText('weird')).toBeTruthy();
  });
});

describe('FactoryPanel — 详情视图', () => {
  it('factoryDetail 存在 → 不渲染列表,渲染详情', () => {
    const detail = makeDetail();
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail } as never);
    render(<FactoryPanel />);
    expect(screen.queryByText('活跃工厂')).toBeNull();
    expect(screen.getByText('构建 calc.py 库')).toBeTruthy();
    expect(screen.getByText('Roadmap')).toBeTruthy();
  });

  it('详情 status=running → 显示「暂停」按钮', () => {
    const detail = makeDetail({ status: 'running' });
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail } as never);
    render(<FactoryPanel />);
    expect(screen.getByText('暂停')).toBeTruthy();
  });

  it('详情 status=paused → 显示「恢复」按钮', () => {
    const detail = makeDetail({ status: 'paused' });
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail } as never);
    render(<FactoryPanel />);
    expect(screen.getByText('恢复')).toBeTruthy();
  });

  it('详情 status=error → 显示「恢复」按钮', () => {
    const detail = makeDetail({ status: 'error' });
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail } as never);
    render(<FactoryPanel />);
    expect(screen.getByText('恢复')).toBeTruthy();
  });

  it('点击返回按钮 → selectFactory("")', () => {
    const selectFactory = vi.fn();
    const detail = makeDetail();
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail, selectFactory } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('返回'));
    expect(selectFactory).toHaveBeenCalledWith('');
  });

  it('暂停按钮成功 → 调用 pauseFactory + 移除错误', async () => {
    const pauseFactory = vi.fn(async () => {});
    const detail = makeDetail({ status: 'running' });
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail, pauseFactory } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('暂停'));
    await vi.waitFor(() => expect(pauseFactory).toHaveBeenCalledWith('fac-detail-1'));
    expect(screen.queryByTestId('factory-action-error')).toBeNull();
  });

  it('暂停按钮失败 → 显示 actionErr', async () => {
    const pauseFactory = vi.fn(async () => {
      throw new Error('HTTP 500: pause failed');
    });
    const detail = makeDetail({ status: 'running' });
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail, pauseFactory } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('暂停'));
    const err = await screen.findByTestId('factory-action-error');
    expect(err.textContent).toContain('pause failed');
  });

  it('暂停失败抛非 Error → 显示默认', async () => {
    const pauseFactory = vi.fn(async () => {
      throw 'oops';
    });
    const detail = makeDetail({ status: 'running' });
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail, pauseFactory } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('暂停'));
    const err = await screen.findByTestId('factory-action-error');
    expect(err.textContent).toContain('操作失败');
  });

  it('恢复按钮成功 → 调用 resumeFactory', async () => {
    const resumeFactory = vi.fn(async () => {});
    const detail = makeDetail({ status: 'paused' });
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail, resumeFactory } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('恢复'));
    await vi.waitFor(() => expect(resumeFactory).toHaveBeenCalledWith('fac-detail-1'));
  });

  it('恢复按钮失败 → 显示 actionErr', async () => {
    const resumeFactory = vi.fn(async () => {
      throw new Error('HTTP 500: resume failed');
    });
    const detail = makeDetail({ status: 'error' });
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail, resumeFactory } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('恢复'));
    const err = await screen.findByTestId('factory-action-error');
    expect(err.textContent).toContain('resume failed');
  });

  it('actionBusy 期间防重复点击', async () => {
    let release: () => void = () => {};
    const pauseFactory = vi.fn(() => new Promise<void>((r) => { release = r; }));
    const detail = makeDetail({ status: 'running' });
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail, pauseFactory } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('暂停'));
    const busyBtn = (await screen.findByText('处理中…')) as HTMLButtonElement;
    expect(busyBtn.disabled).toBe(true);
    fireEvent.click(busyBtn);
    expect(pauseFactory).toHaveBeenCalledTimes(1);
    release();
  });

  it('Roadmap 空态显示提示', () => {
    const detail = makeDetail({ roadmap: [] });
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail } as never);
    render(<FactoryPanel />);
    expect(screen.getByText('GLM planner 正在拆分任务…')).toBeTruthy();
  });

  it('指标 Bento：已完成/失败/执行中/待执行 计数正确', () => {
    const detail = makeDetail({
      roadmap: [
        { id: 't1', description: '', verify_cmd: [], status: 'running', attempts: 1, feedback: '', depends_on: [], artifacts: [] },
        { id: 't2', description: '', verify_cmd: [], status: 'pending', attempts: 1, feedback: '', depends_on: [], artifacts: [] },
        { id: 't3', description: '', verify_cmd: [], status: 'done', attempts: 1, feedback: '', depends_on: [], artifacts: [] },
        { id: 't4', description: '', verify_cmd: [], status: 'failed', attempts: 1, feedback: '', depends_on: [], artifacts: [] },
      ],
      completed: [{ task: { id: 't1', description: '', verify_cmd: [], status: 'done', attempts: 1, feedback: '', depends_on: [], artifacts: [] }, verified: true, stop_reason: '', iteration: 1, summary: '' }],
      failed: [{ task: { id: 't4', description: '', verify_cmd: [], status: 'failed', attempts: 1, feedback: '', depends_on: [], artifacts: [] }, verified: false, stop_reason: '', iteration: 1, summary: '' }],
    });
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail } as never);
    render(<FactoryPanel />);
    // MetricCard 渲染 4 个 value
    expect(screen.getByText('已完成').previousElementSibling?.textContent).toBe('1');
    expect(screen.getByText('失败').previousElementSibling?.textContent).toBe('1');
    expect(screen.getByText('执行中').previousElementSibling?.textContent).toBe('1');
    expect(screen.getByText('待执行').previousElementSibling?.textContent).toBe('1');
  });

  it('TaskRow 渲染 + attempts>1 显示重试次数 + 展开看 verify_cmd/feedback', () => {
    const detail = makeDetail({
      roadmap: [
        {
          id: 'task-1',
          description: '写 add 函数',
          verify_cmd: ['pytest', 'tests/test_add.py'],
          status: 'running',
          attempts: 3,
          feedback: '上次失败：缺导入',
          depends_on: [],
          artifacts: [],
        },
      ],
      current_task_id: 'task-1',
    });
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail } as never);
    render(<FactoryPanel />);
    expect(screen.getByText('task-1')).toBeTruthy();
    expect(screen.getByText(/3/)).toBeTruthy(); // attempts
    // current task 标记 current class
    expect(document.querySelector('.fd-task.current')).not.toBeNull();
    // 展开看反馈
    fireEvent.click(screen.getByText('task-1'));
    expect(screen.getByText('验收命令')).toBeTruthy();
    expect(screen.getByText(/上次失败/)).toBeTruthy();
  });

  it('TaskRow verify_cmd=["true"] → hasVerify=false,不展开', () => {
    const detail = makeDetail({
      roadmap: [
        { id: 't1', description: 'task', verify_cmd: ['true'], status: 'pending', attempts: 1, feedback: '', depends_on: [], artifacts: [] },
      ],
    });
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail } as never);
    render(<FactoryPanel />);
    // 点击不会展开（无 chev body）
    fireEvent.click(screen.getByText('t1'));
    expect(screen.queryByText('验收命令')).toBeNull();
  });

  it('ResultRow 渲染 + 展开/折叠 summary', () => {
    const detail = makeDetail({
      completed: [
        {
          task: { id: 'task-done', description: '完成 add', verify_cmd: [], status: 'done', attempts: 1, feedback: '', depends_on: [], artifacts: [] },
          verified: true,
          stop_reason: 'end_turn',
          iteration: 1,
          summary: 'add 函数已实现',
        },
      ],
    });
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail } as never);
    render(<FactoryPanel />);
    expect(screen.getByText('已完成任务')).toBeTruthy();
    expect(screen.getByText('task-done')).toBeTruthy();
    // 默认折叠
    expect(screen.queryByText('add 函数已实现')).toBeNull();
    // 展开
    fireEvent.click(screen.getByText('task-done'));
    expect(screen.getByText('add 函数已实现')).toBeTruthy();
  });

  it('failed 部分渲染 + 失败任务列表', () => {
    const detail = makeDetail({
      failed: [
        {
          task: { id: 'task-fail', description: '一项失败任务', verify_cmd: [], status: 'failed', attempts: 2, feedback: '', depends_on: [], artifacts: [] },
          verified: false,
          stop_reason: 'verify_failed',
          iteration: 2,
          summary: '校验失败：缺测试',
        },
      ],
    });
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail } as never);
    render(<FactoryPanel />);
    // 列表标题「失败任务」 + 任务条目「一项失败任务」并存
    expect(screen.getAllByText('失败任务').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('一项失败任务')).toBeTruthy();
    expect(screen.getByText('task-fail')).toBeTruthy();
  });
});

describe('FactoryPanel — RCA 历史折叠区', () => {
  it('默认折叠 + 点击展开触发 loadFactoryRcaHistory', async () => {
    const loadFactoryRcaHistory = vi.fn(async () => {});
    const detail = makeDetail();
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail, loadFactoryRcaHistory } as never);
    render(<FactoryPanel />);
    const toggle = screen.getByText('RCA 历史').closest('button')!;
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(loadFactoryRcaHistory).toHaveBeenCalledWith('fac-detail-1');
  });

  it('展开后空历史 → 显示空态提示', () => {
    const detail = makeDetail();
    mockedUseApp.mockReturnValue({
      ...baseState,
      factoryDetail: detail,
      factoryRcaHistory: { factory_id: 'fac-detail-1', rca_history: [], cause_stats: {} },
    } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('RCA 历史').closest('button')!);
    expect(screen.getByText(/暂无 RCA 历史/)).toBeTruthy();
  });

  it('展开后有数据 → 显示 cause_stats chips + 时间线倒序', () => {
    const detail = makeDetail();
    const rcaHistory: FactoryRcaHistoryResponse = {
      factory_id: 'fac-detail-1',
      rca_history: [
        {
          cause: 'syntax_error',
          confidence: 0.9,
          fix_suggestion: '检查缩进',
          history_hint: '上次类似失败',
          related_rules: ['rule-a'],
          task_index: 1,
          timestamp: new Date(Date.now() - 30_000).toISOString(),
        },
        {
          cause: 'verify_mismatch',
          confidence: 0.7,
          fix_suggestion: '',
          history_hint: '',
          related_rules: [],
          task_index: -1,
          timestamp: new Date(Date.now() - 10_000).toISOString(),
        },
      ],
      cause_stats: { syntax_error: 1, verify_mismatch: 1 },
    };
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail, factoryRcaHistory: rcaHistory } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('RCA 历史').closest('button')!);
    // chips 按 cause_stats 值排序（同值时保持插入顺序）
    expect(screen.getByText('syntax_error · 1')).toBeTruthy();
    expect(screen.getByText('verify_mismatch · 1')).toBeTruthy();
    // 倒序：最新(verify_mismatch)在前
    const items = document.querySelectorAll('.fd-rca-item');
    expect(items.length).toBe(2);
    // syntax_error 项有 fix_suggestion/history_hint/related_rules,可展开
    const syntaxItem = Array.from(items).find((el) =>
      el.querySelector('.fd-rca-cause.syntax_error')
    )!;
    fireEvent.click(syntaxItem.querySelector('button')!);
    expect(screen.getByText('建议')).toBeTruthy();
    expect(screen.getByText('检查缩进')).toBeTruthy();
    expect(screen.getByText('历史')).toBeTruthy();
    expect(screen.getByText('上次类似失败')).toBeTruthy();
    expect(screen.getByText('规则')).toBeTruthy();
  });

  it('单项无 fix/history/rules → 不可点击展开', () => {
    const detail = makeDetail();
    mockedUseApp.mockReturnValue({
      ...baseState,
      factoryDetail: detail,
      factoryRcaHistory: {
        factory_id: 'fac-detail-1',
        rca_history: [
          { cause: 'unknown', confidence: 0, fix_suggestion: '', history_hint: '', related_rules: [], task_index: -1, timestamp: new Date().toISOString() },
        ],
        cause_stats: { unknown: 1 },
      },
    } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('RCA 历史').closest('button')!);
    // 无 chev → 点击不展开
    const head = document.querySelector('.fd-rca-item-head') as HTMLButtonElement;
    expect(head).toBeTruthy();
    fireEvent.click(head);
    expect(screen.queryByText('建议')).toBeNull();
  });
});

describe('FactoryPanel — 质量趋势折叠区', () => {
  it('默认折叠 + 展开触发 loadFactoryQualityTrend', async () => {
    const loadFactoryQualityTrend = vi.fn(async () => {});
    const detail = makeDetail();
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail, loadFactoryQualityTrend } as never);
    render(<FactoryPanel />);
    const toggle = screen.getByText('质量趋势').closest('button')!;
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(loadFactoryQualityTrend).toHaveBeenCalledWith('fac-detail-1');
  });

  it('展开后无数据 → 显示空态', () => {
    const detail = makeDetail();
    mockedUseApp.mockReturnValue({
      ...baseState,
      factoryDetail: detail,
      factoryQualityTrend: null,
    } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('质量趋势').closest('button')!);
    expect(screen.getByText(/暂无质量数据/)).toBeTruthy();
  });

  it('展开后有数据 → 显示方向 badge + 曲线 + 维度明细', () => {
    const detail = makeDetail();
    const trend: QualityTrendResponse = {
      factory_id: 'fac-detail-1',
      trend: {
        direction: 'improving',
        delta: 12.3,
        latest_overall: 88,
        latest_grade: 'A',
        samples: 5,
      },
      history: [
        {
          task_id: 'task-a',
          timestamp: new Date(Date.now() - 60_000).toISOString(),
          score: { functionality: 80, code_quality: 75, design: 70, maintainability: 82, performance: 78, grade: 'B', overall: 77 },
        },
        {
          task_id: 'task-b',
          timestamp: new Date(Date.now() - 30_000).toISOString(),
          score: { functionality: 90, code_quality: 88, design: 85, maintainability: 92, performance: 87, grade: 'A', overall: 88 },
        },
      ],
    };
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail, factoryQualityTrend: trend } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('质量趋势').closest('button')!);
    expect(screen.getByText('持续提升')).toBeTruthy();
    expect(screen.getByText('+12.3 分')).toBeTruthy();
    expect(screen.getByText('最新 88 分')).toBeTruthy();
    expect(screen.getByText('A')).toBeTruthy(); // grade badge
    // 维度明细
    expect(screen.getByText('功能')).toBeTruthy();
    expect(screen.getByText('代码')).toBeTruthy();
    expect(screen.getByText('设计')).toBeTruthy();
    expect(screen.getByText('可维护')).toBeTruthy();
    expect(screen.getByText('性能')).toBeTruthy();
    // 曲线 bar
    expect(document.querySelectorAll('.fd-quality-bar').length).toBe(2);
  });

  it('趋势方向 degrading → 显示对应标签', () => {
    const detail = makeDetail();
    const trend: QualityTrendResponse = {
      factory_id: 'fac-detail-1',
      trend: { direction: 'degrading', delta: -5, samples: 3 },
      history: [{ task_id: 'a', timestamp: new Date().toISOString(), score: { functionality: 60, code_quality: 60, design: 60, maintainability: 60, performance: 60, grade: 'C', overall: 60 } }],
    };
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail, factoryQualityTrend: trend } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('质量趋势').closest('button')!);
    expect(screen.getByText('有所下降')).toBeTruthy();
    // delta=-5 也显示
    expect(screen.getByText('-5.0 分')).toBeTruthy();
  });

  it('方向 unknown → 默认 muted 标签', () => {
    const detail = makeDetail();
    const trend: QualityTrendResponse = {
      factory_id: 'fac-detail-1',
      trend: { direction: 'unknown' as never, samples: 0 },
      history: [{ task_id: 'a', timestamp: new Date().toISOString(), score: { functionality: 60, code_quality: 60, design: 60, maintainability: 60, performance: 60, grade: 'C', overall: 60 } }],
    };
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail, factoryQualityTrend: trend } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('质量趋势').closest('button')!);
    expect(screen.getByText('未知')).toBeTruthy();
  });

  it('趋势 delta=0 → 不渲染 delta span', () => {
    const detail = makeDetail();
    const trend: QualityTrendResponse = {
      factory_id: 'fac-detail-1',
      trend: { direction: 'stable', delta: 0, samples: 3 },
      history: [{ task_id: 'a', timestamp: new Date().toISOString(), score: { functionality: 60, code_quality: 60, design: 60, maintainability: 60, performance: 60, grade: 'C', overall: 60 } }],
    };
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail, factoryQualityTrend: trend } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('质量趋势').closest('button')!);
    expect(screen.getByText('保持稳定')).toBeTruthy();
    expect(screen.queryByText(/分$/)).toBeNull();
  });

  it('维度值 ≥ 85 / < 70 高亮不同 class', () => {
    const detail = makeDetail();
    const trend: QualityTrendResponse = {
      factory_id: 'fac-detail-1',
      trend: { direction: 'stable', samples: 1 },
      history: [
        { task_id: 'a', timestamp: new Date().toISOString(), score: { functionality: 90, code_quality: 65, design: 75, maintainability: 80, performance: 50, grade: 'B', overall: 75 } },
      ],
    };
    mockedUseApp.mockReturnValue({ ...baseState, factoryDetail: detail, factoryQualityTrend: trend } as never);
    render(<FactoryPanel />);
    fireEvent.click(screen.getByText('质量趋势').closest('button')!);
    const highVal = document.querySelector('.fd-quality-dim-val.high');
    const lowVal = document.querySelector('.fd-quality-dim-val.low');
    expect(highVal).not.toBeNull();
    expect(lowVal).not.toBeNull();
  });
});
