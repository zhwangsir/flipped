import { useApp } from "../store";
import { IconReview, IconTerminal, IconBrowser, IconFolder } from "../icons";

/** Codex 右侧浮动启动器：面板隐藏时的入口(审查/终端/浏览器/文件)。点击开对应 surface。 */
export function Launcher() {
  const { openContext } = useApp();
  return (
    <div className="launcher">
      <button className="launcher-item" onClick={() => openContext("diff")}>
        <IconReview size={17} />
        <span>审查</span>
        <kbd>⌃⇧G</kbd>
      </button>
      <button className="launcher-item" onClick={() => openContext("term")}>
        <IconTerminal size={17} />
        <span>终端</span>
      </button>
      <button className="launcher-item" onClick={() => openContext("browser")}>
        <IconBrowser size={17} />
        <span>浏览器</span>
        <kbd>⌘T</kbd>
      </button>
      <button className="launcher-item" onClick={() => openContext("files")}>
        <IconFolder size={17} />
        <span>文件</span>
        <kbd>⌘P</kbd>
      </button>
    </div>
  );
}
