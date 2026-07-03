import { useState } from "react";
import { useApp } from "../store";
import { useTheme } from "../hooks/useTheme";
import { formatWhen } from "../types";
import {
  IconPlus,
  IconSearch,
  IconClock,
  IconPuzzle,
  IconFile,
  IconX,
  IconSun,
  IconMoon,
} from "../icons";

/** Codex 风侧栏：全局文字导航 → 项目/线程 → 底部账户区。 */
export function Sidebar() {
  const {
    sessions,
    selectedSessionId,
    selectSession,
    createSession,
    deleteSession,
    sessionQuery,
    setSessionQuery,
    setContextTab,
  } = useApp();
  const { theme, toggle } = useTheme();
  const [navView, setNavView] = useState<"threads" | "scheduled">("threads");

  const q = sessionQuery.trim().toLowerCase();
  const filtered = q ? sessions.filter((s) => s.title.toLowerCase().includes(q)) : sessions;

  const focusSearch = () => {
    setNavView("threads");
    requestAnimationFrame(() => document.getElementById("side-search-input")?.focus());
  };

  return (
    <aside className="sidebar">
      <nav className="side-nav">
        <button
          className="side-nav-item"
          onClick={() => {
            createSession("新对话");
            setNavView("threads");
          }}
        >
          <IconPlus size={16} /> 新对话
        </button>
        <button className="side-nav-item" onClick={focusSearch}>
          <IconSearch size={16} /> 搜索
        </button>
        <button
          className={"side-nav-item" + (navView === "scheduled" ? " active" : "")}
          onClick={() => setNavView("scheduled")}
        >
          <IconClock size={16} /> 已安排
        </button>
        <button className="side-nav-item" onClick={() => setContextTab("mcp")}>
          <IconPuzzle size={16} /> 插件
        </button>
      </nav>

      <div className="side-search">
        <IconSearch size={13} />
        <input
          id="side-search-input"
          value={sessionQuery}
          onChange={(e) => setSessionQuery(e.target.value)}
          placeholder="搜索会话…"
          aria-label="搜索会话"
        />
        {sessionQuery && (
          <button className="side-search-clear" onClick={() => setSessionQuery("")} aria-label="清除">
            <IconX size={12} />
          </button>
        )}
      </div>

      <div className="scroll">
        {navView === "threads" ? (
          <>
            <div className="side-project">
              <IconFile size={13} />
              <span className="side-project-name">flipped</span>
              <span className="side-project-count">{filtered.length}</span>
            </div>
            <div className="side-threads">
              {filtered.map((s) => (
                <div
                  key={s.id}
                  className={"thread" + (s.id === selectedSessionId ? " active" : "")}
                  onClick={() => selectSession(s.id)}
                >
                  <span className={"dot " + s.status} />
                  <span className="thread-title">{s.title}</span>
                  <span className="thread-time">{formatWhen(s.updated_at)}</span>
                  <button
                    className="thread-del"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteSession(s.id);
                    }}
                    aria-label="删除会话"
                  >
                    <IconX size={11} />
                  </button>
                </div>
              ))}
              {filtered.length === 0 && (
                <div className="side-empty">{q ? "无匹配会话" : "暂无会话 · 点「新对话」开始"}</div>
              )}
            </div>
          </>
        ) : (
          <div className="side-empty tall">暂无已安排任务</div>
        )}
      </div>

      <div className="side-account">
        <div className="side-avatar">王</div>
        <div className="side-account-text">
          <div className="side-account-name">Master</div>
          <div className="side-account-sub">本地模式</div>
        </div>
        <button
          className="side-theme"
          onClick={toggle}
          aria-label={theme === "dark" ? "切换到亮色" : "切换到暗色"}
          title="切换主题"
        >
          {theme === "dark" ? <IconSun size={15} /> : <IconMoon size={15} />}
        </button>
      </div>
    </aside>
  );
}
