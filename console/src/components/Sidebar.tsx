import { useState } from "react";
import { useApp } from "../store";
import { fileTree } from "../mock";
import { formatWhen } from "../types";
import { IconPlus, IconFile, IconFolder, IconX } from "../icons";

export function Sidebar() {
  const { sessions, selectedSessionId, selectSession, createSession, deleteSession } = useApp();
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
          <button className="new-task" onClick={() => createSession("新任务")}>
            <IconPlus size={15} /> 新任务
          </button>
          <div className="side-label">
            <span>最近</span>
            <span>{sessions.length}</span>
          </div>
          <div className="scroll">
            {sessions.map((s) => (
              <div
                key={s.id}
                className={"session" + (s.id === selectedSessionId ? " active" : "")}
                onClick={() => selectSession(s.id)}
              >
                <div className="session-top">
                  <span className={"dot " + s.status} />
                  <span className="session-title">{s.title}</span>
                  <button
                    className="session-del"
                    aria-label="删除会话"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteSession(s.id);
                    }}
                  >
                    <IconX size={12} />
                  </button>
                </div>
                <div className="session-meta">
                  <span className="chip">{s.model}</span>
                  <span>{formatWhen(s.updated_at)}</span>
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
