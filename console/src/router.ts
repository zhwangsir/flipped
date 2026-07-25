// M151.5 · 极简 hash 路由（不引 react-router）。
//
// 设计：
// - hash 是路由的唯一真相源：`#/` → Assistant（默认）；`#/factory` → 既有工厂 shell
// - 首次加载 hash 为空时视作 `#/`（默认进 Assistant）
// - useHashRoute 监听 hashchange，App 据此分支渲染并把 route 同步到 store
//   （factoryOpen / activeView），让旧组件（Sidebar 工厂按钮、FactoryPanel 关闭按钮）
//   只需改 hash 即可驱动全局视图切换。
//
// 不做的事：
// - 不引入 react-router（用户要求不打包，依赖越少越好）
// - 不做嵌套路由（M151 只有两态，YAGNI）

import { useEffect, useState } from "react";

export type Route = "assistant" | "factory";

/** 把 window.location.hash 解析成 Route。纯函数，便于单测。 */
export function parseHash(hash: string = (typeof window !== "undefined" ? window.location.hash : "")): Route {
  // 严格匹配 '#/factory'；其他（'', '#/', '#/assistant', '#/anything'）一律视作 Assistant
  if (hash === "#/factory") return "factory";
  return "assistant";
}

/** 监听 hashchange 返回当前 Route。首次挂载读一次初值。 */
export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash());
  useEffect(() => {
    const onHashChange = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHashChange);
    // 挂载时同步一次：防止 SSR / 首次渲染 hash 已设置但 state 还是初值
    setRoute(parseHash());
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  return route;
}

/** 编程式导航。设 hash 会触发 hashchange → useHashRoute 自动更新。 */
export function navigate(route: Route): void {
  if (typeof window === "undefined") return;
  const target = route === "factory" ? "#/factory" : "#/";
  // 同值不触发 hashchange，手动同步一次（防御性）
  if (window.location.hash === target) return;
  window.location.hash = target;
}
