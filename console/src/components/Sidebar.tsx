import { useState } from "react";
import { sessions, fileTree } from "../mock";
import { IconPlus, IconFile, IconFolder } from "../icons";

export function Sidebar() {
  const [tab, setTab] = useState<"chats" | "files">("chats");
  return (
    <aside className="sidebar">
      <div className="seg">
        <button className={tab === "chats" ? "active" : ""} onClick={() => setTab("chats")}>
          会话
        </button>
        <button className={tab === "files" ? "active" : ""} onClick={() => setTab("files")}>
          资源管理器
        </button>
      </div>

      {tab === "chats" ? (
        <>
          <button className="new-task">
            <IconPlus size={15} /> 新任务
          </button>
          <div className="side-label">
            <span>最近</span>
            <span>{sessions.length}</span>
          </div>
          <div className="scroll">
            {sessions.map((s, i) => (
              <div key={s.id} className={"session" + (i === 0 ? " active" : "")}>
                <div className="session-top">
                  <span className={"dot " + s.status} />
                  <span className="session-title">{s.title}</span>
                </div>
                <div className="session-meta">
                  <span className="chip">{s.model}</span>
                  <span>{s.when}</span>
                </div>
              </div>
            ))}
          </div>
        </>
      ) : (
        <>
          <div className="side-label">
            <span>TODO-API</span>
          </div>
          <div className="scroll">
            <div className="tree">
              {fileTree.map((n, i) => (
                <div
                  key={i}
                  className={"tree-row" + (n.active ? " active" : "")}
                  style={{ paddingLeft: 8 + n.depth * 14 }}
                >
                  <span className="ic">{n.kind === "folder" ? <IconFolder size={14} /> : <IconFile size={14} />}</span>
                  <span>{n.name}</span>
                  {n.badge === "add" && <span className="tree-badge add">A</span>}
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </aside>
  );
}
