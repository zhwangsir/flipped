import { useState } from "react";
import {
  IconChat,
  IconFolder,
  IconSearch,
  IconGit,
  IconCube,
  IconBrowser,
  IconPuzzle,
  IconGear,
} from "../icons";

const items = [
  { key: "agent", label: "智能体", Icon: IconChat },
  { key: "explorer", label: "资源管理器", Icon: IconFolder },
  { key: "search", label: "搜索", Icon: IconSearch },
  { key: "git", label: "源代码管理", Icon: IconGit },
  { key: "sandbox", label: "沙盒", Icon: IconCube },
  { key: "browser", label: "浏览器", Icon: IconBrowser },
  { key: "mcp", label: "MCP 工具", Icon: IconPuzzle },
];

export function ActivityBar() {
  const [active, setActive] = useState("agent");
  return (
    <nav className="rail">
      <div className="rail-mark">f</div>
      {items.map(({ key, label, Icon }) => (
        <button
          key={key}
          className={"rail-btn" + (active === key ? " active" : "")}
          onClick={() => setActive(key)}
          aria-label={label}
          title={label}
        >
          <Icon size={19} />
        </button>
      ))}
      <div className="rail-spacer" />
      <button className="rail-btn" aria-label="设置" title="设置">
        <IconGear size={19} />
      </button>
      <div className="rail-avatar">王</div>
    </nav>
  );
}
