import { afterEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { ResizeHandle } from './ResizeHandle';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('ResizeHandle', () => {
  it('渲染 separator 并携带 ARIA 属性', () => {
    render(
      <ResizeHandle side="left" onResize={vi.fn()} value={200} min={120} max={400} />,
    );
    const handle = screen.getByRole('separator');
    expect(handle).toBeInTheDocument();
    expect(handle).toHaveAttribute('aria-orientation', 'vertical');
    expect(handle).toHaveAttribute('aria-label', '拖动调整宽度');
    expect(handle).toHaveAttribute('aria-valuenow', '200');
    expect(handle).toHaveAttribute('aria-valuemin', '120');
    expect(handle).toHaveAttribute('aria-valuemax', '400');
    expect(handle.className).toContain('left');
    expect(handle).toHaveAttribute('tabindex', '0');
  });

  it('side=right 时 className 包含 right', () => {
    render(
      <ResizeHandle side="right" onResize={vi.fn()} value={300} min={100} max={500} />,
    );
    expect(screen.getByRole('separator').className).toContain('right');
  });

  it('键盘 ArrowLeft 调用 onResize(-8)', () => {
    const onResize = vi.fn();
    render(<ResizeHandle side="left" onResize={onResize} value={200} min={120} max={400} />);
    const handle = screen.getByRole('separator');
    fireEvent.keyDown(handle, { key: 'ArrowLeft' });
    expect(onResize).toHaveBeenCalledWith(-8);
  });

  it('键盘 ArrowRight 调用 onResize(8)', () => {
    const onResize = vi.fn();
    render(<ResizeHandle side="left" onResize={onResize} value={200} min={120} max={400} />);
    fireEvent.keyDown(screen.getByRole('separator'), { key: 'ArrowRight' });
    expect(onResize).toHaveBeenCalledWith(8);
  });

  it('其它键不触发 onResize', () => {
    const onResize = vi.fn();
    render(<ResizeHandle side="left" onResize={onResize} value={200} min={120} max={400} />);
    fireEvent.keyDown(screen.getByRole('separator'), { key: 'Enter' });
    expect(onResize).not.toHaveBeenCalled();
  });

  it('鼠标拖动:按下后 mousemove 触发 onResize(dx),mouseup 后停止', () => {
    const onResize = vi.fn();
    render(<ResizeHandle side="left" onResize={onResize} value={200} min={120} max={400} />);
    const handle = screen.getByRole('separator');

    // mousedown 起点 clientX=100
    fireEvent.mouseDown(handle, { clientX: 100 });
    expect(document.body.classList.contains('resizing')).toBe(true);

    // 移动到 140 → dx=40
    fireEvent.mouseMove(document, { clientX: 140 });
    expect(onResize).toHaveBeenLastCalledWith(40);

    // 再移动到 130 → dx=-10 (相对上次)
    fireEvent.mouseMove(document, { clientX: 130 });
    expect(onResize).toHaveBeenLastCalledWith(-10);

    // mouseup 后停止监听,body.resizing 移除
    fireEvent.mouseUp(document);
    expect(document.body.classList.contains('resizing')).toBe(false);
    const callsBefore = onResize.mock.calls.length;
    fireEvent.mouseMove(document, { clientX: 200 });
    expect(onResize.mock.calls.length).toBe(callsBefore);
  });

  it('mousedown 后立即 mouseup 不触发 onResize(无 mousemove)', () => {
    const onResize = vi.fn();
    render(<ResizeHandle side="left" onResize={onResize} value={200} min={120} max={400} />);
    fireEvent.mouseDown(screen.getByRole('separator'), { clientX: 100 });
    fireEvent.mouseUp(document);
    expect(onResize).not.toHaveBeenCalled();
    expect(document.body.classList.contains('resizing')).toBe(false);
  });

  it('value 为小数时 aria-valuenow 取整', () => {
    render(<ResizeHandle side="left" onResize={vi.fn()} value={200.7} min={120} max={400} />);
    expect(screen.getByRole('separator')).toHaveAttribute('aria-valuenow', '201');
  });
});
