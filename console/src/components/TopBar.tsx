import { useApp } from "../store";
import { IconSidebar, IconLayout, IconBolt } from "../icons";
import { formatTokens } from "../lib/format";

const CONN_LABEL: Record<string, string> = {
  connected: "已连接",
  connecting: "连接中",
  error: "连接错误",
  idle: "未连接",
};

const MODE_LABEL: Record<string, string> = {
  auto: "自主",
  agent: "智能体",
  chat: "对话",
  plan: "规划",
};

/** Codex 顶栏：极度克制。左侧栏折叠钮 + 线程标题 + 模式芯片，右侧用量芯片 + 极小连接点 + 面板折叠钮。 */
export function TopBar() {
  const { toggleSidebar, toggleContext, selectedSessionId, sessions, connection, metrics, selectedMode, setMobileSidebarOpen, setMobilePanelOpen } = useApp();
  const session = sessions.find((s) => s.id === selectedSessionId);
  const llm = metrics?.llm;
  const calls = llm?.total_calls ?? 0;
  const modeLabel = MODE_LABEL[selectedMode] || selectedMode;
  return (
    <header className="topbar">
      <button
        className="icon-btn ghost"
        onClick={() => {
          // 移动端：打开抽屉；桌面端：折叠/展开
          if (window.matchMedia("(max-width: 768px)").matches) {
            setMobileSidebarOpen(true);
          } else {
            toggleSidebar();
          }
        }}
        aria-label="折叠侧栏"
        title="折叠 / 展开侧栏 (⌘B)"
      >
        <IconSidebar size={16} />
      </button>
      {session ? (
        <span className="topbar-title">{session.title}</span>
      ) : (
        <span className="topbar-brand">flipped</span>
      )}
      <span className="topbar-mode mono" title={"当前模式：" + modeLabel}>{modeLabel}</span>
      <span className="spacer" />
      {calls > 0 && llm && (
        <span
          className="topbar-usage mono"
          data-testid="usage-chip"
          title={
            "本地模型累计用量(编排/监督 + 沙盒执行)\n" +
            `调用 ${calls} 次 · 错误 ${llm.errors ?? 0}\n` +
            `prompt ${formatTokens(llm.prompt_tokens ?? 0)} + completion ${formatTokens(
              llm.completion_tokens ?? 0
            )} = ${formatTokens(llm.total_tokens ?? 0)} tokens\n` +
            `平均延迟 ${Math.round(llm.avg_latency_ms ?? 0)}ms`
          }
        >
          <IconBolt size={11} />
          {formatTokens(llm.total_tokens ?? 0)}
        </span>
      )}
      <span
        className={"topbar-conn dot " + connection}
        title={"WebSocket " + (CONN_LABEL[connection] || connection)}
        aria-label={"WebSocket " + (CONN_LABEL[connection] || connection)}
      />
      <button
        className="icon-btn ghost"
        aria-label="切换上下文面板"
        title="显示 / 隐藏右侧面板"
        onClick={() => {
          // 移动端：打开底部面板；桌面端：切换面板
          if (window.matchMedia("(max-width: 768px)").matches) {
            setMobilePanelOpen(true);
          } else {
            toggleContext();
          }
        }}
      >
        <IconLayout size={16} />
      </button>
    </header>
  );
}
