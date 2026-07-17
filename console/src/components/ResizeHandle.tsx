/** 面板拖拽缩放把手。onResize 收到每次移动的水平增量 dx(像素)。
 * 可聚焦 separator 按 ARIA 规范必须带 aria-valuenow/min/max(axe aria-required-attr)。 */
export function ResizeHandle({ side, onResize, value, min, max }: {
  side: 'left' | 'right';
  onResize: (dx: number) => void;
  value: number;
  min: number;
  max: number;
}) {
  const onDown = (e: React.MouseEvent) => {
    e.preventDefault();
    let last = e.clientX;
    const onMove = (ev: MouseEvent) => {
      onResize(ev.clientX - last);
      last = ev.clientX;
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.classList.remove('resizing');
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    document.body.classList.add('resizing');
  };
  return (
    <div
      className={'resize-handle ' + side}
      onMouseDown={onDown}
      onKeyDown={(e) => {
        // 键盘可达:←/→ 以 8px 步进调整(语义同鼠标拖动 dx)
        if (e.key === 'ArrowLeft') {
          e.preventDefault();
          onResize(-8);
        } else if (e.key === 'ArrowRight') {
          e.preventDefault();
          onResize(8);
        }
      }}
      role="separator"
      aria-orientation="vertical"
      aria-label="拖动调整宽度"
      aria-valuenow={Math.round(value)}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
    />
  );
}
