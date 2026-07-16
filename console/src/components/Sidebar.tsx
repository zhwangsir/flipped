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
  IconFactory,
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

interface ProjGroup {
  name: string;
  host: string;
  sessions: Session[];
}

/** Codex 风侧栏：文字导航 → 「项目」(多项目分组,活动高亮)/「对话」→ 底部设置(无账户)。 */
export function Sidebar() {
  const {
    sessions,
    selectedSessionId,
    selectSession,
    createSession,
    deleteSession,
    setPaletteOpen,
    setSettingsOpen,
    setPluginsOpen,
    setFactoryOpen,
    projectContext,
    projects,
    openProject,
  } = useApp();
  const { theme, toggle } = useTheme();
  const [navView, setNavView] = useState<"threads" | "scheduled">("threads");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const moreRef = useRef<HTMLDivElement>(null);
  const activeName = projectContext?.project || null;

  // 项目「⋯」菜单点外部关闭
  useEffect(() => {
    if (!menuFor) return;
    const onDown = (e: MouseEvent) => {
      if (!moreRef.current?.contains(e.target as Node)) setMenuFor(null);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [menuFor]);

  // F9 — 并行看板:跨项目汇总所有运行中线程
  const running = sessions.filter((s) => s.status === "running");
  // 会话分组:chat → 对话区;其余按 project_name 归到各项目
  const chatThreads = sessions.filter((s) => s.mode === "chat");
  const nonChat = sessions.filter((s) => (s.mode ?? "agent") !== "chat");
  const byProject = new Map<string, Session[]>();
  for (const s of nonChat) {
    const k = s.project_name || "";
    (byProject.get(k) ?? byProject.set(k, []).get(k)!).push(s);
  }
  // 项目组 = ~/projects 项目(即使无会话也显示) ∪ 会话里出现但已不在 ~/projects 的(ghost)
  const groups: ProjGroup[] = [];
  const seen = new Set<string>();
  for (const p of projects) {
    groups.push({ name: p.name, host: p.host, sessions: byProject.get(p.name) ?? [] });
    seen.add(p.name);
  }
  for (const [name, sess] of byProject) {
    if (!name || seen.has(name)) continue;
    groups.push({ name, host: sess[0]?.project ?? "", sessions: sess });
    seen.add(name);
  }
  const unassigned = byProject.get("") ?? [];

  const toggleCollapse = (name: string) =>
    setCollapsed((c) => {
      const n = new Set(c);
      n.has(name) ? n.delete(name) : n.add(name);
      return n;
    });
  const expand = (name: string) =>
    setCollapsed((c) => {
      if (!c.has(name)) return c;
      const n = new Set(c);
      n.delete(name);
      return n;
    });

  const renderThread = (s: Session) => (
    <div
      key={s.id}
      className={"thread" + (s.id === selectedSessionId ? " active" : "")}
      role="button"
      tabIndex={0}
      onClick={() => selectSession(s.id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          selectSession(s.id);
        }
      }}
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
        aria-label="删除对话"
      >
        <IconX size={11} />
      </button>
    </div>
  );

  const renderGroup = (g: ProjGroup) => {
    const open = !collapsed.has(g.name);
    const isActive = activeName === g.name;
    return (
      <div key={g.name}>
        <div
          className={
            "side-project" + (menuFor === g.name ? " force-actions" : "") + (isActive ? " active" : "")
          }
        >
          <button
            className="side-project-main"
            aria-expanded={open}
            onClick={() => {
              if (g.host && !isActive) openProject(g.host).catch(() => {});
              toggleCollapse(g.name);
            }}
          >
            <IconFolder size={14} />
            <span className="side-project-name">{g.name}</span>
            <span className={"side-project-chev" + (open ? " open" : "")}>
              <IconChevronDown size={12} />
            </span>
          </button>
          <button
            className="side-proj-act"
            title="在此项目新建对话"
            onClick={async () => {
              if (g.host && !isActive) await openProject(g.host).catch(() => {});
              createSession("新对话");
              expand(g.name);
            }}
          >
            <IconEdit size={13} />
          </button>
          <div className="side-proj-morewrap" ref={menuFor === g.name ? moreRef : undefined}>
            <button
              className="side-proj-act"
              title="更多"
              aria-haspopup="menu"
              aria-expanded={menuFor === g.name}
              onClick={() => setMenuFor((m) => (m === g.name ? null : g.name))}
            >
              <IconMore size={15} />
            </button>
            {menuFor === g.name && (
              <div className="proj-menu" role="menu">
                <button
                  className="proj-menu-item"
                  onClick={() => {
                    setMenuFor(null);
                    // TODO: 接入 store 的置顶项目方法（目前 store 无对应 API）
                    console.log("[proj-menu] 置顶项目", g.name);
                  }}
                >
                  <IconPin size={14} /> 置顶项目
                </button>
                <button
                  className="proj-menu-item"
                  onClick={async () => {
                    if (g.host && !isActive) await openProject(g.host).catch(() => {});
                    revealProject().catch(() => {});
                    setMenuFor(null);
                  }}
                >
                  <IconFolder size={14} /> 在 Finder 中显示
                </button>
                <button
                  className="proj-menu-item"
                  onClick={() => {
                    setMenuFor(null);
                    // TODO: 接入工作树创建流程（需要 git worktree add 命令支持）
                    console.log("[proj-menu] 创建永久工作树", g.name);
                  }}
                >
                  <IconGit size={14} /> 创建永久工作树
                </button>
                <button
                  className="proj-menu-item"
                  onClick={() => {
                    const next = window.prompt("重命名项目", g.name);
                    if (next && next.trim() && next.trim() !== g.name) {
                      // TODO: 接入 store 的 renameProject 方法（目前 store 无对应 API）
                      console.log("[proj-menu] 重命名项目", g.name, "→", next.trim());
                    }
                    setMenuFor(null);
                  }}
                >
                  <IconEdit size={14} /> 重命名项目
                </button>
                <button
                  className="proj-menu-item"
                  onClick={() => {
                    if (window.confirm(`归档「${g.name}」下的对话并新建一个会话？`)) {
                      createSession("新对话").catch(() => {});
                    }
                    setMenuFor(null);
                  }}
                >
                  <IconArchive size={14} /> 归档对话
                </button>
                <button
                  className="proj-menu-item danger"
                  onClick={() => {
                    if (window.confirm(`确定移除项目「${g.name}」？（不会删除磁盘文件）`)) {
                      // TODO: 接入 store 的 removeProject 方法（目前 store 无对应 API）
                      console.log("[proj-menu] 移除项目", g.name);
                    }
                    setMenuFor(null);
                  }}
                >
                  <IconX size={14} /> 移除
                </button>
              </div>
            )}
          </div>
        </div>
        {open && (
          <div className="side-threads">
            {g.sessions.map(renderThread)}
            {g.sessions.length === 0 && <div className="side-empty">暂无线程</div>}
          </div>
        )}
      </div>
    );
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
        <button className="side-nav-item" onClick={() => setPaletteOpen(true)}>
          <IconSearch size={16} /> 搜索
        </button>
        <button
          className={"side-nav-item" + (navView === "scheduled" ? " active" : "")}
          onClick={() => setNavView("scheduled")}
        >
          <IconClock size={16} /> 已安排
        </button>
        <button className="side-nav-item" onClick={() => setPluginsOpen(true)}>
          <IconPuzzle size={16} /> 插件
        </button>
        <button className="side-nav-item" onClick={() => setFactoryOpen(true)}>
          <IconFactory size={16} /> 工厂
        </button>
      </nav>

      <div className="scroll">
        {navView === "threads" ? (
          <>
            {running.length > 0 && (
              <div className="side-running" data-testid="running-board">
                <div className="side-running-head">
                  <span className="dot running" />
                  {running.length} 个线程并行运行中
                </div>
                {running.map((s) => (
                  <button
                    key={s.id}
                    className={"side-running-row" + (s.id === selectedSessionId ? " active" : "")}
                    onClick={() => selectSession(s.id)}
                    title={s.title}
                  >
                    <span className="srr-title">{s.title}</span>
                    {s.project_name && <span className="srr-proj">{s.project_name}</span>}
                  </button>
                ))}
              </div>
            )}
            <div className="side-group-label">项目</div>
            {groups.length === 0 && (
              <div className="side-empty">~/projects 暂无项目 · 底部「选择项目」新建或导入</div>
            )}
            {groups.map(renderGroup)}
            {unassigned.length > 0 && (
              <>
                <div className="side-project">
                  <span className="side-project-main static">
                    <IconFolder size={14} />
                    <span className="side-project-name">未分配</span>
                  </span>
                </div>
                <div className="side-threads">{unassigned.map(renderThread)}</div>
              </>
            )}

            <div className="side-group-label">对话</div>
            <div className="side-threads conv">
              {chatThreads.map(renderThread)}
              {chatThreads.length === 0 && <div className="side-empty">暂无聊天</div>}
            </div>
          </>
        ) : (
          <div className="side-empty tall scheduled-empty">
            <span className="scheduled-empty-icon">
              <IconClock size={22} />
            </span>
            <span className="scheduled-empty-title">暂无已安排任务</span>
            <span className="scheduled-empty-hint">在此处规划的任务将自动出现在这里</span>
          </div>
        )}
      </div>

      <div className="side-foot">
        <button className="side-foot-item" onClick={() => setSettingsOpen(true)} title="设置">
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
