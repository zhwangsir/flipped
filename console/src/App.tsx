import "./styles/app.css";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { Conversation } from "./components/Conversation";
import { ContextPanel } from "./components/ContextPanel";
import { CommandPalette } from "./components/CommandPalette";
import { TerminalDrawer } from "./components/TerminalDrawer";
import { AppProvider, useApp } from "./store";

function AppShell() {
  const { sidebarCollapsed, showContext, selectedSessionId } = useApp();
  // 新线程(无活动会话)聚焦中央 composer；或用户手动折叠了面板 → 收起右侧列
  const ctxHidden = !showContext || !selectedSessionId;
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
        <ContextPanel />
      </div>
      <TerminalDrawer />
      <CommandPalette />
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
