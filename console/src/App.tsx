import "./styles/app.css";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { Conversation } from "./components/Conversation";
import { ContextPanel } from "./components/ContextPanel";
import { StatusBar } from "./components/StatusBar";
import { CommandPalette } from "./components/CommandPalette";
import { AppProvider, useApp } from "./store";

function AppShell() {
  const { sidebarCollapsed } = useApp();
  return (
    <div className={"app" + (sidebarCollapsed ? " sb-collapsed" : "")}>
      <TopBar />
      <div className="body">
        <Sidebar />
        <Conversation />
        <ContextPanel />
      </div>
      <StatusBar />
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
