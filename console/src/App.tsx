import "./styles/app.css";
import { ActivityBar } from "./components/ActivityBar";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { Conversation } from "./components/Conversation";
import { ContextPanel } from "./components/ContextPanel";
import { StatusBar } from "./components/StatusBar";
import { AppProvider } from "./store";

export function App() {
  return (
    <AppProvider>
      <div className="app">
        <ActivityBar />
        <TopBar />
        <div className="body">
          <Sidebar />
          <Conversation />
          <ContextPanel />
        </div>
        <StatusBar />
      </div>
    </AppProvider>
  );
}
