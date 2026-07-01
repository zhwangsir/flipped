import { IconPlay, IconGit, IconLayout, IconCube } from "../icons";

export function TopBar() {
  return (
    <header className="topbar">
      <div className="crumb">
        todo-api <span className="sep">/</span> <b>app.py</b>
      </div>
      <div className="top-actions">
        <button className="icon-btn run">
          <IconPlay size={13} /> 运行
        </button>
        <button className="icon-btn">
          <IconGit size={14} /> main
        </button>
      </div>
      <span className="spacer" />
      <span className="pill">
        <span className="dot running" /> 运行中
      </span>
      <span className="pill">
        <IconCube size={13} /> 沙盒 <span className="mono">Docker</span>
      </span>
      <span className="pill">
        模型 <span className="mono">Kimi-K2.7</span>
      </span>
      <button className="icon-btn" aria-label="布局">
        <IconLayout size={15} />
      </button>
    </header>
  );
}
