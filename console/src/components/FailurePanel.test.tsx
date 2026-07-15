import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { FailurePanel } from './FailurePanel';

// mock useApp —— FailurePanel 只从 store 取 4 个字段,这里只提供这几个。
vi.mock('../store', () => ({
  useApp: vi.fn(),
}));

import { useApp } from '../store';

const mockedUseApp = vi.mocked(useApp);

// 默认空状态:无 RCA、无 verdict、无 counter。
const emptyState = {
  rcaHistory: [],
  lastVerifierVerdict: null,
  failureCounter: {},
  clearRca: vi.fn(),
};

// 构造一条 RCA 数据的辅助函数,默认字段填空。
function rca(overrides: Partial<import('../types').RcaInfo> = {}): import('../types').RcaInfo {
  return {
    cause: 'syntax_error',
    confidence: 0.5,
    detail: '',
    history_hint: '',
    related_rules: [],
    fix_suggestion: '',
    failure_counter: {},
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  // 每个用例前重置为空状态(clearRca 用独立 mock 避免跨用例污染)。
  mockedUseApp.mockReturnValue({ ...emptyState, clearRca: vi.fn() } as any);
});

describe('FailurePanel', () => {
  it('无数据时返回 null(不渲染面板)', () => {
    const { container } = render(<FailurePanel />);
    expect(container.firstChild).toBeNull();
  });

  it('有 RCA 时渲染 cause chip 与置信度', () => {
    mockedUseApp.mockReturnValue({
      ...emptyState,
      rcaHistory: [rca({ cause: 'syntax_error', confidence: 0.85 })],
      clearRca: vi.fn(),
    } as any);

    render(<FailurePanel />);
    // syntax_error → "语法错误";0.85 → "85%"
    expect(screen.getByText('语法错误')).toBeInTheDocument();
    expect(screen.getByText('85%')).toBeInTheDocument();
  });

  it('RCA 卡片可展开:旧记录默认折叠,点击 rca-head 后显示 detail/history_hint', () => {
    // 两条记录:新记录(syntax_error,无扩展信息)默认展开;旧记录(timeout,有 detail/history)默认折叠。
    mockedUseApp.mockReturnValue({
      ...emptyState,
      rcaHistory: [
        // 旧记录 → reverse 后渲染为第二张(index 1,默认折叠)
        rca({
          cause: 'timeout',
          confidence: 0.7,
          detail: '详情正文',
          history_hint: '历史提示',
          fix_suggestion: '建议',
        }),
        // 新记录 → reverse 后渲染为第一张(index 0,默认展开,但 hasExtra=false 故无展开区)
        rca({ cause: 'syntax_error', confidence: 0.9, detail: '', history_hint: '' }),
      ],
      clearRca: vi.fn(),
    } as any);

    render(<FailurePanel />);

    // 初始:旧记录(超时)的 detail / history_hint 不显示
    expect(screen.queryByText('详情正文')).not.toBeInTheDocument();
    expect(screen.queryByText('历史提示')).not.toBeInTheDocument();

    // 点击超时卡片的 rca-head 按钮展开
    const timeoutHead = screen.getByText('超时').closest('button') as HTMLElement;
    fireEvent.click(timeoutHead);

    // 展开后:detail / history_hint 显示
    expect(screen.getByText('详情正文')).toBeInTheDocument();
    expect(screen.getByText('历史提示')).toBeInTheDocument();
  });

  it('VerdictCard blocker:渲染"阻断" + issues + verdict-blocker class', () => {
    mockedUseApp.mockReturnValue({
      ...emptyState,
      lastVerifierVerdict: {
        severity: 'blocker',
        checked: true,
        issues: ['issue1'],
        suggestions: ['sug1'],
      },
      clearRca: vi.fn(),
    } as any);

    const { container } = render(<FailurePanel />);
    expect(screen.getByText(/阻断/)).toBeInTheDocument();
    expect(screen.getByText('issue1')).toBeInTheDocument();
    expect(container.querySelector('.verdict-blocker')).not.toBeNull();
  });

  it('VerdictCard warning:渲染"警告"', () => {
    mockedUseApp.mockReturnValue({
      ...emptyState,
      lastVerifierVerdict: {
        severity: 'warning',
        checked: true,
        issues: [],
        suggestions: [],
      },
      clearRca: vi.fn(),
    } as any);

    render(<FailurePanel />);
    expect(screen.getByText(/警告/)).toBeInTheDocument();
  });

  it('VerdictCard ok:渲染"通过"', () => {
    mockedUseApp.mockReturnValue({
      ...emptyState,
      lastVerifierVerdict: {
        severity: 'ok',
        checked: true,
        issues: [],
        suggestions: [],
      },
      clearRca: vi.fn(),
    } as any);

    render(<FailurePanel />);
    expect(screen.getByText(/通过/)).toBeInTheDocument();
  });

  it('counter chip 失败次数 ≥3 加 escalated class', () => {
    mockedUseApp.mockReturnValue({
      ...emptyState,
      failureCounter: { syntax_error: 3 },
      clearRca: vi.fn(),
    } as any);

    const { container } = render(<FailurePanel />);
    const chip = container.querySelector('.counter-chip');
    expect(chip).not.toBeNull();
    expect(chip!.classList.contains('escalated')).toBe(true);
  });

  it('counter chip 失败次数 <3 不加 escalated class', () => {
    mockedUseApp.mockReturnValue({
      ...emptyState,
      failureCounter: { timeout: 1 },
      clearRca: vi.fn(),
    } as any);

    const { container } = render(<FailurePanel />);
    const chip = container.querySelector('.counter-chip');
    expect(chip).not.toBeNull();
    expect(chip!.classList.contains('escalated')).toBe(false);
  });

  it('点击 fp-clear 按钮触发 clearRca', () => {
    const clearRca = vi.fn();
    mockedUseApp.mockReturnValue({
      ...emptyState,
      rcaHistory: [rca({ cause: 'syntax_error', confidence: 0.5 })],
      clearRca,
    } as any);

    const { container } = render(<FailurePanel />);
    const clearBtn = container.querySelector('.fp-clear') as HTMLElement;
    expect(clearBtn).not.toBeNull();
    fireEvent.click(clearBtn);
    expect(clearRca).toHaveBeenCalledTimes(1);
  });

  it('checked=false 的 verdict 不渲染 verdict-card', () => {
    mockedUseApp.mockReturnValue({
      ...emptyState,
      rcaHistory: [rca({ cause: 'syntax_error', confidence: 0.5 })],
      lastVerifierVerdict: {
        severity: 'ok',
        checked: false,
        issues: [],
        suggestions: [],
      },
      clearRca: vi.fn(),
    } as any);

    const { container } = render(<FailurePanel />);
    // 面板因 RCA 渲染,但 checked=false 的 verdict 不渲染 verdict-card
    expect(container.querySelector('.verdict-card')).toBeNull();
    expect(screen.queryByText('通过')).not.toBeInTheDocument();
  });
});
