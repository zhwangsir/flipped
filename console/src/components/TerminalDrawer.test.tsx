import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { TerminalDrawer } from './TerminalDrawer';

vi.mock('../store', () => ({ useApp: vi.fn() }));
vi.mock('./PtyTerminal', () => ({
  PtyTerminal: vi.fn((props: { active: boolean; className?: string }) => (
    <div data-testid="pty-mock" data-active={props.active ? 'true' : 'false'} data-class={props.className ?? ''} />
  )),
}));

import { useApp } from '../store';
import { PtyTerminal } from './PtyTerminal';

const mockedUseApp = vi.mocked(useApp);
const mockedPtyTerminal = vi.mocked(PtyTerminal);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  mockedUseApp.mockReturnValue({ terminalOpen: false, toggleTerminal: vi.fn() } as never);
});

describe('TerminalDrawer', () => {
  it('terminalOpen=false 时 drawer 不含 open 类,PtyTerminal active=false', () => {
    render(<TerminalDrawer />);
    const drawer = document.querySelector('.term-drawer');
    expect(drawer).not.toBeNull();
    expect(drawer?.className).not.toContain('open');
    expect(mockedPtyTerminal).toHaveBeenCalledWith(expect.objectContaining({ active: false }), expect.anything());
  });

  it('terminalOpen=true 时 drawer 含 open 类,PtyTerminal active=true', () => {
    mockedUseApp.mockReturnValue({ terminalOpen: true, toggleTerminal: vi.fn() } as never);
    render(<TerminalDrawer />);
    const drawer = document.querySelector('.term-drawer');
    expect(drawer?.className).toContain('open');
    expect(mockedPtyTerminal).toHaveBeenCalledWith(expect.objectContaining({ active: true }), expect.anything());
  });

  it('渲染标题「终端」与 pty · zsh 子标', () => {
    render(<TerminalDrawer />);
    expect(screen.getByText('终端')).toBeInTheDocument();
    expect(document.querySelector('.mono')?.textContent).toContain('pty · zsh');
  });

  it('点击关闭按钮调用 toggleTerminal', () => {
    const toggleTerminal = vi.fn();
    mockedUseApp.mockReturnValue({ terminalOpen: true, toggleTerminal } as never);
    render(<TerminalDrawer />);
    fireEvent.click(screen.getByLabelText('关闭终端 (⌘J)'));
    expect(toggleTerminal).toHaveBeenCalledOnce();
  });

  it('关闭按钮 title 含 ⌘J 提示', () => {
    render(<TerminalDrawer />);
    const btn = screen.getByLabelText('关闭终端 (⌘J)');
    expect(btn).toHaveAttribute('title', '关闭 (⌘J)');
  });

  it('terminalOpen=false 时 drawer 含 inert 属性', () => {
    render(<TerminalDrawer />);
    const drawer = document.querySelector('.term-drawer') as HTMLElement | null;
    expect(drawer?.hasAttribute('inert')).toBe(true);
  });

  it('terminalOpen=true 时 drawer 不含 inert 属性', () => {
    mockedUseApp.mockReturnValue({ terminalOpen: true, toggleTerminal: vi.fn() } as never);
    render(<TerminalDrawer />);
    const drawer = document.querySelector('.term-drawer') as HTMLElement | null;
    expect(drawer?.hasAttribute('inert')).toBe(false);
  });
});
