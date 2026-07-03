import "./styles/app.css";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { Conversation } from "./components/Conversation";
import { ContextPanel } from "./components/ContextPanel";
import { Launcher } from "./components/Launcher";
import { CommandPalette } from "./components/CommandPalette";
import { Settings } from "./components/Settings";
import { Plugins } from "./components/Plugins";
import { TerminalDrawer } from "./components/TerminalDrawer";
import { AppProvider, useApp } from "./store";

function AppShell() {
  const { sidebarCollapsed, showContext } = useApp();
  // 面板隐藏 → 收起右侧列 + 显示浮动启动器(Codex 式按需打开 surface)
  const ctxHidden = !showContext;
  return (
    <div
      className={
        "app" +
        (sidebarCollapsed ? " sb-collapsed" : "") +
        (ctxHidden ? " ctx-collapsed" : "")
      }
    >
      <TopBar />
      <div className="body">
        <Sidebar />
        <Conversation />
        {showContext ? <ContextPanel /> : <Launcher />}
      </div>
      <TerminalDrawer />
      <CommandPalette />
      <Settings />
      <Plugins />
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
