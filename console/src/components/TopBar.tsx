import { useApp } from "../store";
import { IconSidebar, IconLayout } from "../icons";

const CONN_LABEL: Record<string, string> = {
  connected: "已连接",
  connecting: "连接中",
  error: "连接错误",
  idle: "未连接",
};

/** Codex 顶栏：极度克制。左侧栏折叠钮 + 线程标题，右侧极小连接点 + 面板折叠钮。 */
export function TopBar() {
  const { toggleSidebar, toggleContext, selectedSessionId, sessions, connection } = useApp();
  const session = sessions.find((s) => s.id === selectedSessionId);
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
      {session && <span className="topbar-title">{session.title}</span>}
      <span className="spacer" />
      <span
        className={"topbar-conn dot " + connection}
        title={"WebSocket " + (CONN_LABEL[connection] || connection)}
        aria-label={"WebSocket " + (CONN_LABEL[connection] || connection)}
      />
      <button
        className="icon-btn ghost"
        aria-label="切换上下文面板"
        title="显示 / 隐藏右侧面板"
        onClick={toggleContext}
      >
        <IconLayout size={16} />
      </button>
    </header>
  );
}
