import { useApp } from "../store";
import { IconGit, IconLayout, IconCube } from "../icons";

const MODEL_LABEL: Record<string, string> = { coder: "Kimi-K2.7", architect: "GLM-5.2" };
const STATUS_LABEL: Record<string, string> = {
  running: "运行中",
  done: "已完成",
  review: "待审批",
  error: "出错",
  idle: "空闲",
};

export function TopBar() {
  const {
    sessions,
    selectedSessionId,
    sessionStatus,
    selectedModel,
    changedFiles,
    setContextTab,
    toggleContext,
  } = useApp();

  const session = sessions.find((s) => s.id === selectedSessionId);
  const activeFile =
    [...changedFiles].reverse().find((f) => f.content) || changedFiles[changedFiles.length - 1];
  const st = sessionStatus || "idle";

  return (
    <header className="topbar">
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
      <span className="pill">
        <IconCube size={13} /> 沙盒 <span className="mono">Docker</span>
      </span>
      <span className="pill">
        模型 <span className="mono">{MODEL_LABEL[selectedModel] || selectedModel}</span>
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
