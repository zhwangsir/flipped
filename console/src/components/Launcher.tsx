import { useApp } from "../store";
import type { ContextTab } from "../types";
import { IconReview, IconTerminal, IconBrowser, IconFolder } from "../icons";

interface LauncherEntry {
  tab: ContextTab;
  icon: typeof IconReview;
  label: string;
  shortcut?: string;
}

const ENTRIES: LauncherEntry[] = [
  { tab: "diff", icon: IconReview, label: "审查", shortcut: "⌃⇧G" },
  { tab: "term", icon: IconTerminal, label: "终端" },
  { tab: "browser", icon: IconBrowser, label: "浏览器", shortcut: "⌘T" },
  { tab: "files", icon: IconFolder, label: "文件", shortcut: "⌘P" },
];

/** 右侧窄图标栏：上下文面板隐藏时的入口(审查/终端/浏览器/文件)。hover 左弹标签。 */
export function Launcher() {
  const { openContext } = useApp();
  return (
    <nav className="launcher" role="toolbar" aria-orientation="vertical" aria-label="面板入口">
      {ENTRIES.map(({ tab, icon: Icon, label, shortcut }) => (
        <button
          key={tab}
          type="button"
          className="launcher-item"
          onClick={() => openContext(tab)}
          data-label={shortcut ? `${label}  ${shortcut}` : label}
          aria-label={label}
        >
          <Icon size={18} />
        </button>
      ))}
    </nav>
  );
}
