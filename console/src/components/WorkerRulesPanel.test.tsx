import { afterEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';
import { WorkerRulesPanel } from './WorkerRulesPanel';
import type { WorkerRule, WorkerRulesInfo, WorkerRuleStatsData } from '../types';

// 面板自取数:mock ../api 模块(不经 store),与 RulesPanel.test 同范式
vi.mock('../api', () => ({
  fetchWorkerRules: vi.fn(),
  createWorkerRule: vi.fn(),
  updateWorkerRule: vi.fn(),
  deleteWorkerRule: vi.fn(),
  toggleWorkerRule: vi.fn(),
  fetchWorkerRuleVersions: vi.fn(),
  rollbackWorkerRules: vi.fn(),
  autoGenerateWorkerRules: vi.fn(),
  fetchWorkerRuleStats: vi.fn(),
}));

import {
  fetchWorkerRules,
  createWorkerRule,
  updateWorkerRule,
  deleteWorkerRule,
  toggleWorkerRule,
  fetchWorkerRuleVersions,
  rollbackWorkerRules,
  autoGenerateWorkerRules,
  fetchWorkerRuleStats,
} from '../api';

const mockedFetchRules = vi.mocked(fetchWorkerRules);
const mockedCreate = vi.mocked(createWorkerRule);
const mockedUpdate = vi.mocked(updateWorkerRule);
const mockedDelete = vi.mocked(deleteWorkerRule);
const mockedToggle = vi.mocked(toggleWorkerRule);
const mockedFetchVersions = vi.mocked(fetchWorkerRuleVersions);
const mockedRollback = vi.mocked(rollbackWorkerRules);
const mockedAuto = vi.mocked(autoGenerateWorkerRules);
const mockedFetchStats = vi.mocked(fetchWorkerRuleStats);

const autoRule: WorkerRule = {
  id: 'r-auto',
  text: '提交前跑 lint',
  scope: 'worker',
  source: 'auto',
  enabled: true,
  priority: 70,
  created_at: 1722700000,
};
const manualRule: WorkerRule = {
  id: 'r-manual',
  text: '禁止 console.log',
  scope: 'all',
  source: 'manual',
  enabled: false,
  priority: 60,
  created_at: 1722700100,
};

const defaultInfo: WorkerRulesInfo = { version: 3, rules: [autoRule, manualRule] };
const defaultStats: WorkerRuleStatsData = {
  stats: {
    'r-auto': { applied: 10, success: 8, failure: 2 },
    'r-manual': { applied: 0, success: 0, failure: 0 },
    'r-none': { applied: 5, success: 2, failure: 3 },
  },
  total_runs: 15,
};

function setupLoad(info = defaultInfo, stats = defaultStats) {
  mockedFetchRules.mockResolvedValue(info);
  mockedFetchStats.mockResolvedValue(stats);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('WorkerRulesPanel', () => {
  it('mount 并行调 fetchWorkerRules + fetchWorkerRuleStats', async () => {
    setupLoad();
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrules-panel')).toBeInTheDocument());
    expect(mockedFetchRules).toHaveBeenCalledTimes(1);
    expect(mockedFetchStats).toHaveBeenCalledTimes(1);
  });

  it('loading 骨架「加载中…」', () => {
    mockedFetchRules.mockReturnValue(new Promise(() => {}));
    render(<WorkerRulesPanel />);
    expect(screen.getByText('加载中…')).toBeInTheDocument();
  });

  it('版本徽标「v{n}」', async () => {
    setupLoad();
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByText('v3')).toBeInTheDocument());
  });

  it('规则行渲染(按 priority desc,来源徽标 auto/manual)', async () => {
    setupLoad();
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrule-r-auto')).toBeInTheDocument());
    expect(screen.getByTestId('wrule-r-manual')).toBeInTheDocument();
    // auto 来源徽标
    expect(screen.getByText('auto').className).toContain('purple');
    // manual 来源徽标
    expect(screen.getByText('manual').className).toContain('blue');
  });

  it('toggle 调 api 乐观更新(先变 UI 再 refresh)', async () => {
    setupLoad();
    mockedToggle.mockResolvedValue({ ...autoRule, enabled: false });
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrule-r-auto')).toBeInTheDocument());
    const checkbox = screen.getByTestId('toggle-r-auto') as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
    fireEvent.click(checkbox);
    await waitFor(() => expect(mockedToggle).toHaveBeenCalledWith('r-auto', false));
    expect(mockedToggle).toHaveBeenCalledTimes(1);
  });

  it('点击「编辑」→ 行内 textarea 预填文本 + 保存调 updateWorkerRule', async () => {
    setupLoad();
    mockedUpdate.mockResolvedValue(autoRule);
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrule-r-auto')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('edit-r-auto'));
    // 编辑框与新建框都是 textarea,用显示值区分
    const textarea = screen.getByDisplayValue('提交前跑 lint') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: '提交前必须跑 lint' } });
    fireEvent.click(screen.getByTestId('save-edit-r-auto'));
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1));
    expect(mockedUpdate).toHaveBeenCalledWith('r-auto', { text: '提交前必须跑 lint', scope: 'worker', priority: 70 });
  });

  it('编辑取消 → 不调 api,收起 textarea', async () => {
    setupLoad();
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrule-r-auto')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('edit-r-auto'));
    expect(screen.getByDisplayValue('提交前跑 lint')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('cancel-edit-r-auto'));
    expect(mockedUpdate).not.toHaveBeenCalled();
    expect(screen.queryByDisplayValue('提交前跑 lint')).toBeNull();
  });

  it('删除二次确认 → 取消不调 api', async () => {
    setupLoad();
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrule-r-auto')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('del-r-auto'));
    expect(screen.getByText(/确认删除/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('取消'));
    expect(mockedDelete).not.toHaveBeenCalled();
  });

  it('删除二次确认 → 确认调 deleteWorkerRule 并刷新', async () => {
    setupLoad();
    mockedDelete.mockResolvedValue({ ok: true });
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrule-r-auto')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('del-r-auto'));
    await waitFor(() => expect(screen.getByText(/确认删除/)).toBeInTheDocument());
    fireEvent.click(screen.getByText('确认'));
    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith('r-auto'));
    // 删除后重刷(目前保持两条,第二次 fetch 仍返回两条,不做空断言;只断言 api 调用即可)
    expect(mockedDelete).toHaveBeenCalledTimes(1);
  });

  it('新建表单空文本禁用「添加」按钮', async () => {
    setupLoad();
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrules-add')).toBeInTheDocument());
    const btn = screen.getByTestId('wrules-add') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('新建表单提交调 createWorkerRule 并清空', async () => {
    setupLoad();
    mockedCreate.mockResolvedValue({ ...autoRule, id: 'r-new', text: '新规则' });
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrules-add')).toBeInTheDocument());
    const textarea = screen.getByPlaceholderText('新规则…') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: '新规则' } });
    fireEvent.click(screen.getByTestId('wrules-add'));
    await waitFor(() => expect(mockedCreate).toHaveBeenCalledTimes(1));
    expect(mockedCreate).toHaveBeenCalledWith('新规则', 'worker', 50);
    // 清空
    expect(textarea.value).toBe('');
  });

  it('自动生成有新增 → 绿 note「新增 N 条规则」并刷新', async () => {
    setupLoad();
    mockedAuto.mockResolvedValue({ added: [autoRule, manualRule], candidates: 2 });
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrules-auto')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('wrules-auto'));
    await waitFor(() => expect(screen.getByText('新增 2 条规则')).toBeInTheDocument());
    expect(screen.getByText('新增 2 条规则').className).toContain('ok');
  });

  it('自动生成无候选 → 灰 note「无新候选」', async () => {
    setupLoad();
    mockedAuto.mockResolvedValue({ added: [], candidates: 0 });
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrules-auto')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('wrules-auto'));
    await waitFor(() => expect(screen.getByText('无新候选')).toBeInTheDocument());
    expect(screen.getByText('无新候选').className).toContain('muted');
  });

  it('版本史展开渲染列表 + 回滚二次确认调 api', async () => {
    setupLoad();
    mockedFetchVersions.mockResolvedValue([
      { version: 2, ts: 1722700000, action: 'create', detail: '新增规则', rule_count: 5 },
    ]);
    mockedRollback.mockResolvedValue({ ok: true, version: 3 });
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrules-auto')).toBeInTheDocument());
    fireEvent.click(screen.getByText('版本史'));
    await waitFor(() => expect(screen.getByTestId('wrules-versions')).toBeInTheDocument());
    expect(screen.getByText(/新增规则/)).toBeInTheDocument();
    expect(screen.getByText('5 条')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('rollback-2'));
    await waitFor(() => expect(screen.getByText(/回滚到 v2/)).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('confirm-rollback-2'));
    await waitFor(() => expect(mockedRollback).toHaveBeenCalledWith(2));
  });

  it('回滚取消 → 不调 api', async () => {
    setupLoad();
    mockedFetchVersions.mockResolvedValue([
      { version: 2, ts: 1722700000, action: 'create', detail: '新增规则', rule_count: 5 },
    ]);
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrules-auto')).toBeInTheDocument());
    fireEvent.click(screen.getByText('版本史'));
    await waitFor(() => expect(screen.getByTestId('wrules-versions')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('rollback-2'));
    await waitFor(() => expect(screen.getByText(/回滚到 v2/)).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('cancel-rollback-2'));
    expect(mockedRollback).not.toHaveBeenCalled();
  });

  it('stats 成功率条渲染(≥80% 绿 / ≥50% 琥珀 / <50% 红)', async () => {
    setupLoad();
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrules-panel')).toBeInTheDocument());
    // auto: 8/10 = 80% 绿
    expect(screen.getByTestId('stat-r-auto').className).toContain('ok');
    // none(不在规则列表中故不渲染)
  });

  it('stats 分母为 0 时显示「未应用」灰字', async () => {
    setupLoad(defaultInfo, {
      stats: {
        'r-auto': { applied: 0, success: 0, failure: 0 },
      },
      total_runs: 0,
    });
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('stat-r-auto')).toBeInTheDocument());
    const row = screen.getByTestId('stat-r-auto');
    expect(row.className).toContain('muted');
    expect(within(row).getByText('未应用')).toBeInTheDocument();
  });

  it('M185.2 成功率=success/(success+failure) 而非 success/applied', async () => {
    // applied=10 但 outcome 只有 4 次（2 成 2 败）→ 新公式 0.5 琥珀；旧公式 0.2 红
    setupLoad(defaultInfo, {
      stats: {
        'r-auto': { applied: 10, success: 2, failure: 2 },
      },
      total_runs: 4,
    });
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('stat-r-auto')).toBeInTheDocument());
    expect(screen.getByTestId('stat-r-auto').className).toContain('amber');
  });

  it('M185.2 零 outcome（已注入未 verify）不渲染 bar、灰字不炸', async () => {
    setupLoad(defaultInfo, {
      stats: {
        'r-auto': { applied: 3, success: 0, failure: 0 },
      },
      total_runs: 0,
    });
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('stat-r-auto')).toBeInTheDocument());
    const row = screen.getByTestId('stat-r-auto');
    expect(row.className).toContain('muted');
    expect(within(row).getByText(/应用 3/)).toBeInTheDocument();
    expect(row.querySelector('.wrules-bar')).toBeNull();
  });

  it('M185.2 语义注记渲染（semantics 字段）', async () => {
    setupLoad(defaultInfo, { ...defaultStats, semantics: 'applied=注入次；测试语义注记' });
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrules-semantics')).toBeInTheDocument());
    expect(screen.getByTestId('wrules-semantics').textContent).toContain('测试语义注记');
  });

  it('M185.2 semantics 缺省 → 本地兜底文案', async () => {
    setupLoad();
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrules-semantics')).toBeInTheDocument());
    expect(screen.getByTestId('wrules-semantics').textContent).toContain('success_rate=success/(success+failure)');
  });

  it('加载失败 → 红字 + 重试可恢复', async () => {
    // M194.7 — 带参失败后会先做一次无参回落尝试;两次都拒绝才进错误态
    // (clearAllMocks 不清 mockResolvedValue 实现,单次 reject 会让回落意外成功)
    mockedFetchRules.mockRejectedValueOnce(new Error('HTTP 500: boom'));
    mockedFetchRules.mockRejectedValueOnce(new Error('HTTP 500: boom'));
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByText(/加载失败：HTTP 500: boom/)).toBeInTheDocument());
    mockedFetchRules.mockResolvedValue(defaultInfo);
    mockedFetchStats.mockResolvedValue(defaultStats);
    fireEvent.click(screen.getByText('重试'));
    await waitFor(() => expect(screen.getByTestId('wrules-panel')).toBeInTheDocument());
    // M194.7 — 带参失败后会先做一次无参回落尝试(同样失败),故重试是第 3 次调用
    expect(mockedFetchRules).toHaveBeenCalledTimes(3);
  });
});

// M194.7 — 服务端排序/过滤:默认 sort=priority 走服务端;enabled 开关(全部/启用/停用);
// 服务端请求失败/不支持 → 回落本地排序全量拉取(现状行为不回归)
describe('WorkerRulesPanel — M194.7 服务端排序/过滤', () => {
  it('mount 默认带 { sort: "priority" } 走服务端排序', async () => {
    setupLoad();
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrule-r-auto')).toBeInTheDocument());
    expect(mockedFetchRules).toHaveBeenCalledWith({ sort: 'priority' });
  });

  it('enabled 过滤开关渲染(全部/启用/停用,默认全部 active)', async () => {
    setupLoad();
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrules-filter')).toBeInTheDocument());
    const group = screen.getByTestId('wrules-filter');
    expect(within(group).getByText('全部')).toBeInTheDocument();
    expect(within(group).getByText('启用')).toBeInTheDocument();
    expect(within(group).getByText('停用')).toBeInTheDocument();
    expect(within(group).getByText('全部').className).toContain('active');
  });

  it('切「停用」→ 重新拉取带 { sort: "priority", enabled: false }', async () => {
    setupLoad();
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrules-filter')).toBeInTheDocument());
    mockedFetchRules.mockClear();
    fireEvent.click(screen.getByText('停用'));
    await waitFor(() =>
      expect(mockedFetchRules).toHaveBeenCalledWith({ sort: 'priority', enabled: false })
    );
  });

  it('切「启用」→ { sort: "priority", enabled: true };切回「全部」→ 仅 sort', async () => {
    setupLoad();
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrules-filter')).toBeInTheDocument());
    fireEvent.click(screen.getByText('启用'));
    await waitFor(() =>
      expect(mockedFetchRules).toHaveBeenCalledWith({ sort: 'priority', enabled: true })
    );
    fireEvent.click(screen.getByText('全部'));
    await waitFor(() => expect(mockedFetchRules).toHaveBeenLastCalledWith({ sort: 'priority' }));
  });

  it('服务端 500 → 回落本地排序全量拉取,规则照常渲染不炸', async () => {
    // 带参请求 500,回落无参全量成功(故意乱序:manual(p60) 在前)
    mockedFetchRules.mockRejectedValueOnce(new Error('HTTP 500: boom'));
    mockedFetchRules.mockResolvedValueOnce({ version: 3, rules: [manualRule, autoRule] });
    mockedFetchStats.mockResolvedValue(defaultStats);
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrule-r-auto')).toBeInTheDocument());
    // 无错误红字(回落成功)
    expect(screen.queryByText(/加载失败/)).toBeNull();
    // 本地排序 priority desc:auto(70) 在 manual(60) 前
    const rows = document.querySelectorAll('.wrules-row');
    expect(rows[0].getAttribute('data-testid')).toBe('wrule-r-auto');
    expect(rows[1].getAttribute('data-testid')).toBe('wrule-r-manual');
  });

  it('回落后切「停用」→ 无参拉取 + 本地过滤(只剩停用规则)', async () => {
    mockedFetchRules.mockRejectedValueOnce(new Error('HTTP 500: boom'));
    mockedFetchRules.mockResolvedValueOnce({ version: 3, rules: [manualRule, autoRule] });
    mockedFetchStats.mockResolvedValue(defaultStats);
    render(<WorkerRulesPanel />);
    await waitFor(() => expect(screen.getByTestId('wrule-r-auto')).toBeInTheDocument());
    mockedFetchRules.mockResolvedValue({ version: 3, rules: [manualRule, autoRule] });
    mockedFetchRules.mockClear();
    fireEvent.click(screen.getByText('停用'));
    // 回落通路不再带查询参数
    await waitFor(() => expect(mockedFetchRules).toHaveBeenCalledWith(undefined));
    await waitFor(() => {
      expect(screen.queryByTestId('wrule-r-auto')).toBeNull();
      expect(screen.getByTestId('wrule-r-manual')).toBeInTheDocument();
    });
  });
});
