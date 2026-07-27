import React from "react";
import ReactDOM from "react-dom/client";
// D-0013 修复：移除未使用的 @fontsource-variable/geist（Geist Sans）。
// tokens.css 的 --font-sans 用系统字体栈（-apple-system / Segoe UI / system-ui），
// Geist Sans 从未被任何 font-family 引用 —— 它是纯死重：5 个 woff2 子集（~75KB）
// + 对应 @font-face CSS 规则全部被打进 entry chunk，拖慢 FCP。
// 仅保留 Geist Mono（用于 --font-mono / 代码块 / 终端），其 fontsource 包已自带
// font-display: swap，不阻塞首次绘制。
import "@fontsource-variable/geist-mono";
import "./styles/global.css";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
