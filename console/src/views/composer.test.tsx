import { afterEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { Composer } from './Composer';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('Composer — 输入守卫与 slash 补全', () => {
  it('空输入不发(发送按钮禁用,点击无效果)', () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} />);
    const btn = screen.getByTestId('assistant-send-btn') as HTMLButtonElement;
    // 空输入时按钮禁用
    expect(btn.disabled).toBe(true);
    fireEvent.click(btn);
    expect(onSend).not.toHaveBeenCalled();
  });

  it('busy=true 时输入框与按钮均禁用', () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} busy={true} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    const btn = screen.getByTestId('assistant-send-btn') as HTMLButtonElement;
    expect(ta.disabled).toBe(true);
    expect(btn.disabled).toBe(true);
  });

  it('输入 / 唤起 slash 补全菜单,显示 5 项命令', () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} />);
    const ta = screen.getByTestId('assistant-composer-input') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '/' } });
    const menu = screen.getByTestId('slash-menu');
    expect(menu).toBeTruthy();
    // 5 项命令
    const items = menu.querySelectorAll('.slash-item');
    expect(items.length).toBe(5);
    // 命令文本检查
    const cmds = Array.from(items).map((i) => i.querySelector('.slash-cmd')?.textContent);
    expect(cmds).toEqual(['/clear', '/compact', '/mode', '/help', '/files']);
  });
});
