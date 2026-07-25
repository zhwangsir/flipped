import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { FactoryPanel } from './FactoryPanel';

// M146 回归保护：启动工厂失败可见反馈 + 防重复提交。
vi.mock('../store', () => ({ useApp: vi.fn() }));

import { useApp } from '../store';

const mockedUseApp = vi.mocked(useApp);

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
});
