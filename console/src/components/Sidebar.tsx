import { useState } from "react";
import { useApp } from "../store";
import { useTheme } from "../hooks/useTheme";
import { formatWhen } from "../types";
import type { Session } from "../types";
import {
  IconPlus,
  IconSearch,
  IconClock,
  IconPuzzle,
  IconFolder,
  IconChat,
  IconChevronDown,
  IconGear,
  IconX,
  IconSun,
  IconMoon,
} from "../icons";

/** Codex 风侧栏：全局文字导航 → 项目(可折叠) / 对话(可折叠) → 底部设置(无账户)。 */
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
    setPaletteOpen,
  } = useApp();
  const { theme, toggle } = useTheme();
  const [navView, setNavView] = useState<"threads" | "scheduled">("threads");
  const [projOpen, setProjOpen] = useState(true);
  const [convOpen, setConvOpen] = useState(true);

  const q = sessionQuery.trim().toLowerCase();
  const filtered = q ? sessions.filter((s) => s.title.toLowerCase().includes(q)) : sessions;
  // chat 模式 → 对话区；agent/plan(或历史无 mode)→ 项目区
  const projectThreads = filtered.filter((s) => (s.mode ?? "agent") !== "chat");
  const chatThreads = filtered.filter((s) => s.mode === "chat");

  const focusSearch = () => {
    setNavView("threads");
    requestAnimationFrame(() => document.getElementById("side-search-input")?.focus());
  };

  const renderThread = (s: Session) => (
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
  );

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
            {/* 项目区（可折叠） */}
            <button className="side-section" onClick={() => setProjOpen((o) => !o)}>
              <span className={"side-section-chev" + (projOpen ? " open" : "")}>
                <IconChevronDown size={11} />
              </span>
              <span className="side-section-label">项目</span>
            </button>
            {projOpen && (
              <>
                <div className="side-project">
                  <IconFolder size={13} />
                  <span className="side-project-name">flipped</span>
                  <span className="side-project-count">{projectThreads.length}</span>
                </div>
                <div className="side-threads">
                  {projectThreads.map(renderThread)}
                  {projectThreads.length === 0 && (
                    <div className="side-empty">{q ? "无匹配会话" : "暂无线程 · 点「新对话」"}</div>
                  )}
                </div>
              </>
            )}

            {/* 对话区（可折叠，chat 模式会话） */}
            <button className="side-section" onClick={() => setConvOpen((o) => !o)}>
              <span className={"side-section-chev" + (convOpen ? " open" : "")}>
                <IconChevronDown size={11} />
              </span>
              <IconChat size={12} />
              <span className="side-section-label">对话</span>
              {chatThreads.length > 0 && <span className="side-section-count">{chatThreads.length}</span>}
            </button>
            {convOpen && (
              <div className="side-threads conv">
                {chatThreads.map(renderThread)}
                {chatThreads.length === 0 && <div className="side-empty">暂无聊天</div>}
              </div>
            )}
          </>
        ) : (
          <div className="side-empty tall">暂无已安排任务</div>
        )}
      </div>

      <div className="side-foot">
        <button className="side-foot-item" onClick={() => setPaletteOpen(true)} title="设置与命令 (⌘K)">
          <IconGear size={15} /> 设置
        </button>
        <span className="side-foot-mode">本地模式</span>
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
