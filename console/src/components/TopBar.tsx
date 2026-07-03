import { useApp } from "../store";
import { IconGit, IconLayout, IconSidebar } from "../icons";

const STATUS_LABEL: Record<string, string> = {
  running: "运行中",
  done: "已完成",
  review: "待审批",
  error: "出错",
  idle: "空闲",
};

/** Codex 精简顶栏：侧栏折叠 + 面包屑 + 变更 + 一枚状态 pill + 面板切换。
 *  模型/沙盒等下沉到 composer 与状态栏，顶栏保持克制。 */
export function TopBar() {
  const {
    sessions,
    selectedSessionId,
    sessionStatus,
    changedFiles,
    setContextTab,
    toggleContext,
    toggleSidebar,
  } = useApp();

  const session = sessions.find((s) => s.id === selectedSessionId);
  const activeFile =
    [...changedFiles].reverse().find((f) => f.content) || changedFiles[changedFiles.length - 1];
  const st = sessionStatus || "idle";

  return (
    <header className="topbar">
      <button
        className="icon-btn ghost"
        onClick={toggleSidebar}
        aria-label="折叠侧栏"
        title="折叠 / 展开侧栏 (⌘B)"
      >
        <IconSidebar size={15} />
      </button>
      <div className="crumb">
        {session ? session.title : "flipped"}
        {activeFile && (
          <>
            {" "}
            <span className="sep">/</span> <b>{activeFile.path.split("/").pop()}</b>
          </>
        )}
      </div>
      <div className="top-actions">
        <button className="icon-btn" onClick={() => setContextTab("diff")} title="查看本次变更">
          <IconGit size={14} /> 变更
          {changedFiles.length > 0 && <span className="mono">{changedFiles.length}</span>}
        </button>
      </div>
      <span className="spacer" />
      <span className="pill">
        <span className={"dot " + st} /> {STATUS_LABEL[st] || st}
      </span>
      <button
        className="icon-btn"
        aria-label="切换上下文面板"
        title="显示 / 隐藏右侧面板"
        onClick={toggleContext}
      >
        <IconLayout size={15} />
      </button>
    </header>
  );
}
