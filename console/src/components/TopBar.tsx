import { useApp } from "../store";
import { IconSidebar, IconLayout } from "../icons";

/** Codex 顶栏：极度克制。左侧栏折叠钮，右面板折叠钮，中间全是可拖拽空白。 */
export function TopBar() {
  const { toggleSidebar, toggleContext, selectedSessionId } = useApp();
  return (
    <header className="topbar">
      <button
        className="icon-btn ghost"
        onClick={toggleSidebar}
        aria-label="折叠侧栏"
        title="折叠 / 展开侧栏 (⌘B)"
      >
        <IconSidebar size={16} />
      </button>
      <span className="spacer" />
      {selectedSessionId && (
        <button
          className="icon-btn ghost"
          aria-label="切换上下文面板"
          title="显示 / 隐藏右侧面板"
          onClick={toggleContext}
        >
          <IconLayout size={16} />
        </button>
      )}
    </header>
  );
}
