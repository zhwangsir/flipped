import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { PlanCard } from './PlanCard';

vi.mock('../store', () => ({ useApp: vi.fn() }));

import { useApp } from '../store';
import type { PlanState } from '../types';

const mockedUseApp = vi.mocked(useApp);

function plan(overrides: Partial<PlanState> = {}): PlanState {
  return {
    steps: [],
    complete: false,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  mockedUseApp.mockReturnValue({ plan: null } as never);
});

describe('PlanCard', () => {
  it('plan 为 null 时返回 null', () => {
    mockedUseApp.mockReturnValue({ plan: null } as never);
    const { container } = render(<PlanCard />);
    expect(container.firstChild).toBeNull();
  });

  it('steps 为空数组时返回 null', () => {
    mockedUseApp.mockReturnValue({ plan: plan({ steps: [] }) } as never);
    const { container } = render(<PlanCard />);
    expect(container.firstChild).toBeNull();
  });

  it('渲染计划步骤与进度计数', () => {
    mockedUseApp.mockReturnValue({
      plan: plan({
        steps: [
          { index: 0, text: '拆解需求', status: 'done' },
          { index: 1, text: '写实现', status: 'running' },
          { index: 2, text: '跑测试', status: 'retry' },
          { index: 3, text: '收尾', status: 'aborted' },
        ],
      }),
    } as never);
    render(<PlanCard />);

    expect(screen.getByTestId('plan-card')).toBeInTheDocument();
    expect(screen.getByText('拆解需求')).toBeInTheDocument();
    expect(screen.getByText('写实现')).toBeInTheDocument();
    expect(screen.getByText('跑测试')).toBeInTheDocument();
    expect(screen.getByText('收尾')).toBeInTheDocument();
    // done 只有 1 个
    expect(screen.getByText('1/4')).toBeInTheDocument();
  });

  it('每个状态对应中文徽章', () => {
    mockedUseApp.mockReturnValue({
      plan: plan({
        steps: [
          { index: 0, text: 'A', status: 'done' },
          { index: 1, text: 'B', status: 'running' },
          { index: 2, text: 'C', status: 'retry' },
          { index: 3, text: 'D', status: 'aborted' },
        ],
      }),
    } as never);
    render(<PlanCard />);

    expect(screen.getByText('完成')).toBeInTheDocument();
    expect(screen.getByText('进行中')).toBeInTheDocument();
    expect(screen.getByText('重试')).toBeInTheDocument();
    expect(screen.getByText('中止')).toBeInTheDocument();
  });

  it('complete=true 时显示「已完成」标记', () => {
    mockedUseApp.mockReturnValue({
      plan: plan({
        complete: true,
        steps: [{ index: 0, text: 'X', status: 'done' }],
      }),
    } as never);
    render(<PlanCard />);
    expect(screen.getByText('已完成')).toBeInTheDocument();
  });

  it('complete=false 时不显示「已完成」标记', () => {
    mockedUseApp.mockReturnValue({
      plan: plan({
        complete: false,
        steps: [{ index: 0, text: 'X', status: 'running' }],
      }),
    } as never);
    render(<PlanCard />);
    expect(screen.queryByText('已完成')).toBeNull();
  });

  it('步骤 className 包含状态', () => {
    mockedUseApp.mockReturnValue({
      plan: plan({
        steps: [{ index: 0, text: 'X', status: 'retry' }],
      }),
    } as never);
    render(<PlanCard />);
    const li = screen.getByText('X').closest('li');
    expect(li?.className).toContain('retry');
  });
});
