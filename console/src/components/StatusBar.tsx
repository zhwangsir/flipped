import { IconGit, IconCube, IconCheck, IconWarn, IconBolt } from "../icons";

export function StatusBar() {
  return (
    <footer className="statusbar">
      <span className="sb">
        <IconGit size={13} /> <span className="mono">main</span>
      </span>
      <span className="sb ok">
        <IconCheck size={13} /> 3 passed
      </span>
      <span className="sb">
        <IconWarn size={13} /> 1
      </span>
      <span className="spacer" />
      <span className="sb-live">
        <span className="dot review" /> Overseer 监督中
      </span>
      <span className="sb accent">
        <IconBolt size={13} /> Kimi-K2.7 · <span className="mono">coder</span>
      </span>
      <span className="sb">
        <IconCube size={13} /> 沙盒 <span className="mono">py3.12</span>
      </span>
      <span className="sb mono">12.4k tok</span>
      <span className="sb mono">Ln 14, Col 5</span>
    </footer>
  );
}
