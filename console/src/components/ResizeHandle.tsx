/** 面板拖拽缩放把手。onResize 收到每次移动的水平增量 dx(像素)。 */
export function ResizeHandle({ side, onResize }: { side: 'left' | 'right'; onResize: (dx: number) => void }) {
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
      role="separator"
      aria-orientation="vertical"
      aria-label="拖动调整宽度"
    />
  );
}
