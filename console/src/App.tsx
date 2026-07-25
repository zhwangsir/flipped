import "./styles/app.css";
import { useEffect, useState, type CSSProperties } from "react";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { Conversation } from "./components/Conversation";
import { ContextPanel } from "./components/ContextPanel";
import { Launcher } from "./components/Launcher";
import { ResizeHandle } from "./components/ResizeHandle";
import { CommandPalette } from "./components/CommandPalette";
import { Settings } from "./components/Settings";
import { Plugins } from "./components/Plugins";
import { TerminalDrawer } from "./components/TerminalDrawer";
import { FactoryPanel } from "./components/FactoryPanel";
import { Assistant } from "./views/Assistant";
import { AppProvider, useApp } from "./store";
import { useHashRoute } from "./router";
import { IconPlus, IconChat, IconGear, IconLayout } from "./icons";

const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 460;
const CONTEXT_MIN = 320;
const CONTEXT_MAX = 760;
const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));

function readNum(key: string, fallback: number): number {
  try {
    const v = Number(localStorage.getItem(key));
    return Number.isFinite(v) && v > 0 ? v : fallback;
  } catch {
    return fallback;
  }
}
function writeNum(key: string, v: number) {
  try {
    localStorage.setItem(key, String(Math.round(v)));
  } catch {
    /* 隐私模式忽略 */
  }
}

function AppShell() {
  const { sidebarCollapsed, showContext, mobileSidebarOpen, setMobileSidebarOpen, mobilePanelOpen, setMobilePanelOpen, createSession, setSettingsOpen, setActiveView, setFactoryOpen } = useApp();
  const [sidebarW, setSidebarW] = useState(() => readNum("flipped-sidebar-w", 272));
  const [contextW, setContextW] = useState(() => readNum("flipped-context-w", 468));

  // M151.5 · hash 路由是顶层视图的唯一真相源：
  // '#/' → Assistant（默认）；'#/factory' → 既有工厂 shell（Conversation + FactoryPanel）。
  // route 变化时同步 store（activeView / factoryOpen），让旧组件无需感知 hash 也能
  // 正确渲染（FactoryPanel 读 factoryOpen 决定是否显示）。
  const route = useHashRoute();
  useEffect(() => {
    setActiveView(route);
    setFactoryOpen(route === "factory");
  }, [route, setActiveView, setFactoryOpen]);

  useEffect(() => writeNum("flipped-sidebar-w", sidebarW), [sidebarW]);
  useEffect(() => writeNum("flipped-context-w", contextW), [contextW]);

  // 面板隐藏 → 收起右侧列 + 显示浮动启动器(Codex 式按需打开 surface)
  const ctxHidden = !showContext;
  // 折叠态由 CSS 类接管宽度(0 / 启动器列),故仅在展开时用内联变量覆盖
  const style = {
    ...(sidebarCollapsed ? {} : { "--sidebar-w": sidebarW + "px" }),
    ...(showContext ? { "--context-w": contextW + "px" } : {}),
  } as CSSProperties;

  return (
    <div
      className={
        "app" +
        (sidebarCollapsed ? " sb-collapsed" : "") +
        (ctxHidden ? " ctx-collapsed" : "") +
        (mobileSidebarOpen ? " mobile-sidebar-open" : "") +
        (mobilePanelOpen ? " mobile-panel-open" : "")
      }
      style={style}
    >
      <TopBar />
      <div className="body">
        <Sidebar />
        {route === "factory" ? <Conversation /> : <Assistant />}
        {showContext ? <ContextPanel /> : <Launcher />}
        {!sidebarCollapsed && (
          <ResizeHandle
            side="left"
            value={sidebarW}
            min={SIDEBAR_MIN}
            max={SIDEBAR_MAX}
            onResize={(dx) => setSidebarW((w) => clamp(w + dx, SIDEBAR_MIN, SIDEBAR_MAX))}
          />
        )}
        {showContext && (
          <ResizeHandle
            side="right"
            value={contextW}
            min={CONTEXT_MIN}
            max={CONTEXT_MAX}
            onResize={(dx) => setContextW((w) => clamp(w - dx, CONTEXT_MIN, CONTEXT_MAX))}
          />
        )}
      </div>

      {/* M131 — 移动端遮罩层 */}
      {mobileSidebarOpen && (
        <div className="mobile-overlay" onClick={() => setMobileSidebarOpen(false)} />
      )}
      {mobilePanelOpen && (
        <div className="mobile-overlay" onClick={() => setMobilePanelOpen(false)} />
      )}

      {/* M131 — 移动端底部导航栏（参考 Claude/ChatGPT 移动端设计） */}
      <nav className="mobile-tabbar">
        <button
          className="tabbar-btn"
          onClick={() => setMobileSidebarOpen(true)}
          aria-label="对话列表"
        >
          <IconChat size={20} />
          <span>对话</span>
        </button>
        <button
          className="tabbar-btn tabbar-fab"
          onClick={() => createSession()}
          aria-label="新对话"
        >
          <IconPlus size={22} />
        </button>
        <button
          className="tabbar-btn"
          onClick={() => setMobilePanelOpen(true)}
          aria-label="上下文面板"
        >
          <IconLayout size={20} />
          <span>面板</span>
        </button>
        <button
          className="tabbar-btn"
          onClick={() => setSettingsOpen(true)}
          aria-label="设置"
        >
          <IconGear size={20} />
          <span>设置</span>
        </button>
      </nav>

      <TerminalDrawer />
      <CommandPalette />
      <Settings />
      <Plugins />
      <FactoryPanel />
    </div>
  );
}

export function App() {
  return (
    <AppProvider>
      <AppShell />
    </AppProvider>
  );
}
