import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { Launcher } from './Launcher';

vi.mock('../store', () => ({ useApp: vi.fn() }));

import { useApp } from '../store';
import type { ContextTab } from '../types';

const mockedUseApp = vi.mocked(useApp);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  mockedUseApp.mockReturnValue({ openContext: vi.fn() } as never);
});

describe('Launcher', () => {
  it('渲染 toolbar 与 4 个入口按钮', () => {
    render(<Launcher />);
    const toolbar = screen.getByRole('toolbar');
    expect(toolbar).toHaveAttribute('aria-orientation', 'vertical');
    expect(toolbar).toHaveAttribute('aria-label', '面板入口');
    const items = screen.getAllByRole('button');
    expect(items).toHaveLength(4);
  });

  it('4 个入口的 aria-label 分别为 审查/终端/浏览器/文件', () => {
    render(<Launcher />);
    expect(screen.getByLabelText('审查')).toBeInTheDocument();
    expect(screen.getByLabelText('终端')).toBeInTheDocument();
    expect(screen.getByLabelText('浏览器')).toBeInTheDocument();
    expect(screen.getByLabelText('文件')).toBeInTheDocument();
  });

  it('点击「审查」调用 openContext("diff")', () => {
    const openContext = vi.fn();
    mockedUseApp.mockReturnValue({ openContext } as never);
    render(<Launcher />);
    fireEvent.click(screen.getByLabelText('审查'));
    expect(openContext).toHaveBeenCalledWith('diff');
  });

  it('点击「终端」调用 openContext("term")', () => {
    const openContext = vi.fn();
    mockedUseApp.mockReturnValue({ openContext } as never);
    render(<Launcher />);
    fireEvent.click(screen.getByLabelText('终端'));
    expect(openContext).toHaveBeenCalledWith('term');
  });

  it('点击「浏览器」调用 openContext("browser")', () => {
    const openContext = vi.fn();
    mockedUseApp.mockReturnValue({ openContext } as never);
    render(<Launcher />);
    fireEvent.click(screen.getByLabelText('浏览器'));
    expect(openContext).toHaveBeenCalledWith('browser');
  });

  it('点击「文件」调用 openContext("files")', () => {
    const openContext = vi.fn();
    mockedUseApp.mockReturnValue({ openContext } as never);
    render(<Launcher />);
    fireEvent.click(screen.getByLabelText('文件'));
    expect(openContext).toHaveBeenCalledWith('files');
  });

  it('带快捷键的入口 data-label 拼接 label + shortcut', () => {
    render(<Launcher />);
    const review = screen.getByLabelText('审查');
    expect(review).toHaveAttribute('data-label', '审查  ⌃⇧G');
    const browser = screen.getByLabelText('浏览器');
    expect(browser).toHaveAttribute('data-label', '浏览器  ⌘T');
    const files = screen.getByLabelText('文件');
    expect(files).toHaveAttribute('data-label', '文件  ⌘P');
  });

  it('终端入口无快捷键时 data-label 等于 label', () => {
    render(<Launcher />);
    expect(screen.getByLabelText('终端')).toHaveAttribute('data-label', '终端');
  });
});

// 仅用作类型断言:确保 ContextTab 字面量符合
const _t: ContextTab = 'diff';
void _t;
