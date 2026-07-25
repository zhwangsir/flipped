// M151.5 · Console hash 路由 + 工厂视图保留 TDD 测试。
//
// 2 例（按 M151 计划）：
// 1. 默认 `#/`（hash 空）渲染 Assistant，不渲染 Conversation
// 2. `#/factory` 渲染既有 shell（Conversation），并同步 setFactoryOpen(true) 让
//    FactoryPanel 打开（FactoryPanel 自身的 factoryOpen→visible 逻辑由 FactoryPanel.test.tsx 覆盖）
//
// 策略：mock 重组件为带 testid 的桩，让测试聚焦在「hash → route → 渲染分支 +
// store 同步」。store mock 用 vi.hoisted 共享 factoryOpen，setFactoryOpen 真正
// 翻转 shared 状态（验证 effect 调用），但 FactoryPanel 的可见性由其自己的单测覆盖。

import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import type { ReactNode } from "react";
import { render, screen, cleanup, waitFor } from "@testing-library/react";

// vi.hoisted：在 vi.mock 之前可用的共享状态。setFactoryOpen 真正翻转 factoryOpen，
// 让测试能验证「route → store 同步」effect 真的跑了。
const shared = vi.hoisted(() => ({
  factoryOpen: false,
  setFactoryOpen: vi.fn((v: boolean) => {
    shared.factoryOpen = v;
  }),
}));

vi.mock("./store", () => ({
  AppProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useApp: () => ({
    sidebarCollapsed: false,
    showContext: true,
    mobileSidebarOpen: false,
    setMobileSidebarOpen: vi.fn(),
    mobilePanelOpen: false,
    setMobilePanelOpen: vi.fn(),
    createSession: vi.fn(),
    setSettingsOpen: vi.fn(),
    setActiveView: vi.fn(),
    get factoryOpen() {
      return shared.factoryOpen;
    },
    setFactoryOpen: shared.setFactoryOpen,
    activeView: "assistant",
  }),
}));

// ---- 桩：重组件替换为带 testid 的 div ----
vi.mock("./components/TopBar", () => ({ TopBar: () => <div data-testid="topbar-stub" /> }));
vi.mock("./components/Sidebar", () => ({ Sidebar: () => <div data-testid="sidebar-stub" /> }));
vi.mock("./components/Conversation", () => ({
  Conversation: () => <div data-testid="conversation-view" />,
}));
vi.mock("./components/ContextPanel", () => ({
  ContextPanel: () => <div data-testid="context-panel-stub" />,
}));
vi.mock("./components/Launcher", () => ({ Launcher: () => <div data-testid="launcher-stub" /> }));
vi.mock("./components/ResizeHandle", () => ({ ResizeHandle: () => null }));
vi.mock("./components/CommandPalette", () => ({ CommandPalette: () => null }));
vi.mock("./components/Settings", () => ({ Settings: () => null }));
vi.mock("./components/Plugins", () => ({ Plugins: () => null }));
vi.mock("./components/TerminalDrawer", () => ({ TerminalDrawer: () => null }));
vi.mock("./components/FactoryPanel", () => ({
  FactoryPanel: () => (shared.factoryOpen ? <div data-testid="factory-panel" /> : null),
}));
vi.mock("./views/Assistant", () => ({
  Assistant: () => <div data-testid="assistant-view" />,
}));

import { App } from "./App";

beforeEach(() => {
  window.location.hash = "";
  shared.factoryOpen = false;
  shared.setFactoryOpen.mockClear();
});

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

describe("App · hash 路由（M151.5）", () => {
  it("默认 `#/`（hash 空）渲染 Assistant，不渲染工厂 shell", () => {
    render(<App />);
    // Assistant 视图可见
    expect(screen.getByTestId("assistant-view")).toBeTruthy();
    // Conversation（工厂 shell 主区）不可见
    expect(screen.queryByTestId("conversation-view")).toBeNull();
    // FactoryPanel 关闭（factoryOpen=false）
    expect(screen.queryByTestId("factory-panel")).toBeNull();
  });

  it("`#/factory` 渲染既有 shell（Conversation）并同步打开 FactoryPanel", async () => {
    render(<App />);
    // 初始：Assistant 可见
    expect(screen.getByTestId("assistant-view")).toBeTruthy();

    // 切到 #/factory → hashchange → useHashRoute 更新 → AppShell 重渲
    window.location.hash = "#/factory";

    // Conversation 出现（route='factory' → 主区切到工厂 shell）
    await waitFor(() => {
      expect(screen.getByTestId("conversation-view")).toBeTruthy();
    });
    // Assistant 不再渲染
    expect(screen.queryByTestId("assistant-view")).toBeNull();

    // route → store 同步：setFactoryOpen(true) 被调用（FactoryPanel 据此打开；
    // factoryOpen→visible 的渲染逻辑由 FactoryPanel.test.tsx 覆盖）
    await waitFor(() => {
      expect(shared.setFactoryOpen).toHaveBeenCalledWith(true);
    });
  });
});
