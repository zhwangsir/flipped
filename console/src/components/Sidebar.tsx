import { useState, useEffect, useRef } from "react";
import { useApp } from "../store";
import { useTheme } from "../hooks/useTheme";
import { formatWhen } from "../types";
import type { Session } from "../types";
import { revealProject } from "../api";
import {
  IconPlus,
  IconSearch,
  IconClock,
  IconPuzzle,
  IconFolder,
  IconChevronDown,
  IconGear,
  IconGit,
  IconMore,
  IconEdit,
  IconPin,
  IconArchive,
  IconX,
  IconSun,
  IconMoon,
} from "../icons";

/** Codex 风侧栏：文字导航 → 「项目」标签 + flipped 可折叠行(名后 chevron + hover ✎/⋯) / 「对话」→ 底部设置(无账户)。 */
export function Sidebar() {
  const {
    sessions,
    selectedSessionId,
    selectSession,
    createSession,
    deleteSession,
    setContextTab,
    setPaletteOpen,
    projectContext,
  } = useApp();
  const { theme, toggle } = useTheme();
  const [navView, setNavView] = useState<"threads" | "scheduled">("threads");
  const [projOpen, setProjOpen] = useState(true);
  const [projMenu, setProjMenu] = useState(false);
  const moreRef = useRef<HTMLDivElement>(null);
  const projectName = projectContext?.project || "flipped";

  // 项目「⋯」菜单点外部关闭
  useEffect(() => {
    if (!projMenu) return;
    const onDown = (e: MouseEvent) => {
      if (!moreRef.current?.contains(e.target as Node)) setProjMenu(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [projMenu]);

  // chat 模式 → 对话区；agent/plan(或历史无 mode)→ 项目区
  const projectThreads = sessions.filter((s) => (s.mode ?? "agent") !== "chat");
  const chatThreads = sessions.filter((s) => s.mode === "chat");

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
        <button className="side-nav-item" onClick={() => setPaletteOpen(true)}>
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

      <div className="scroll">
        {navView === "threads" ? (
          <>
            {/* 项目 —— 纯标签 */}
            <div className="side-group-label">项目</div>
            {/* flipped —— 可折叠项目行(名后 chevron + hover ✎/⋯) */}
            <div className={"side-project" + (projMenu ? " force-actions" : "")}>
              <button className="side-project-main" onClick={() => setProjOpen((o) => !o)}>
                <IconFolder size={14} />
                <span className="side-project-name">{projectName}</span>
                <span className={"side-project-chev" + (projOpen ? " open" : "")}>
                  <IconChevronDown size={12} />
                </span>
              </button>
              <button
                className="side-proj-act"
                title="在此项目新建对话"
                onClick={() => {
                  createSession("新对话");
                  setProjOpen(true);
                }}
              >
                <IconEdit size={13} />
              </button>
              <div className="side-proj-morewrap" ref={moreRef}>
                <button
                  className="side-proj-act"
                  title="更多"
                  aria-haspopup="menu"
                  onClick={() => setProjMenu((o) => !o)}
                >
                  <IconMore size={15} />
                </button>
                {projMenu && (
                  <div className="proj-menu" role="menu">
                    <button className="proj-menu-item" onClick={() => setProjMenu(false)}>
                      <IconPin size={14} /> 置顶项目
                    </button>
                    <button
                      className="proj-menu-item"
                      onClick={() => {
                        revealProject().catch(() => {});
                        setProjMenu(false);
                      }}
                    >
                      <IconFolder size={14} /> 在 Finder 中显示
                    </button>
                    <button className="proj-menu-item" onClick={() => setProjMenu(false)}>
                      <IconGit size={14} /> 创建永久工作树
                    </button>
                    <button className="proj-menu-item" onClick={() => setProjMenu(false)}>
                      <IconEdit size={14} /> 重命名项目
                    </button>
                    <button className="proj-menu-item" onClick={() => setProjMenu(false)}>
                      <IconArchive size={14} /> 归档对话
                    </button>
                    <button className="proj-menu-item danger" onClick={() => setProjMenu(false)}>
                      <IconX size={14} /> 移除
                    </button>
                  </div>
                )}
              </div>
            </div>
            {projOpen && (
              <div className="side-threads">
                {projectThreads.map(renderThread)}
                {projectThreads.length === 0 && (
                  <div className="side-empty">暂无线程 · 点「新对话」</div>
                )}
              </div>
            )}

            {/* 对话 —— 纯标签 */}
            <div className="side-group-label">对话</div>
            <div className="side-threads conv">
              {chatThreads.map(renderThread)}
              {chatThreads.length === 0 && <div className="side-empty">暂无聊天</div>}
            </div>
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
