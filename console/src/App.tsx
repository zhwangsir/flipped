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
import { AppProvider, useApp } from "./store";

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
  const { sidebarCollapsed, showContext } = useApp();
  const [sidebarW, setSidebarW] = useState(() => readNum("flipped-sidebar-w", 272));
  const [contextW, setContextW] = useState(() => readNum("flipped-context-w", 468));

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
        (ctxHidden ? " ctx-collapsed" : "")
      }
      style={style}
    >
      <TopBar />
      <div className="body">
        <Sidebar />
        <Conversation />
        {showContext ? <ContextPanel /> : <Launcher />}
        {!sidebarCollapsed && (
          <ResizeHandle
            side="left"
            onResize={(dx) => setSidebarW((w) => clamp(w + dx, SIDEBAR_MIN, SIDEBAR_MAX))}
          />
        )}
        {showContext && (
          <ResizeHandle
            side="right"
            onResize={(dx) => setContextW((w) => clamp(w - dx, CONTEXT_MIN, CONTEXT_MAX))}
          />
        )}
      </div>
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
