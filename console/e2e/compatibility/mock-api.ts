/**
 * 跨浏览器兼容性测试 · 共享 API mock 工具
 *
 * Console 前端在 store.tsx 挂载后会并发拉取多个后端 API（sessions/metrics/mcp/
 * project/projects/factories/rca/failure_counter 等）。兼容性测试必须不依赖真实后端
 * （端口 8011 在 CI 沙盒里通常不存在），统一用 page.route() 拦截到 mock 响应。
 *
 * 这里的 mock 只返回「空态」结构：让 UI 在三大浏览器下都能稳定渲染主壳，从而把
 * 断言聚焦在「布局/路由/响应式/交互」的浏览器差异上，而不是后端数据正确性。
 *
 * 路径必须与 console/src/api.ts 实际请求路径完全一致（注意单复数）：
 *   /project/context  /project/files  /project/diff  → 单数（项目级单资源）
 *   /projects                                      → 复数（项目列表）
 *   /rca/failure_counter                            → RCA 子命名空间
 */
import type { Page, Route } from '@playwright/test';

const API = 'http://127.0.0.1:8011/api/v1/**';

/** 让 fetch mock 直接返回空态；让 WebSocket 连接失败由前端 fail-open 处理（store.tsx 已 try/catch）。 */
export async function mockEmptyApi(page: Page) {
  await page.route(API, (route: Route) => {
    const url = route.request().url();
    const path = url.replace('http://127.0.0.1:8011/api/v1', '').split('?')[0];

    // 会话列表：空数组 → 侧栏渲染空态而非崩溃
    if (path === '/sessions') return route.fulfill({ status: 200, json: [] });
    // 性能指标：返回 0 调用，避免 usage chip 闪烁
    if (path === '/metrics') {
      return route.fulfill({
        status: 200,
        json: { llm: { total_calls: 0, errors: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, avg_latency_ms: 0 } },
      });
    }
    // MCP 服务器列表：空数组 → 插件页空态
    if (path === '/mcp/servers') return route.fulfill({ status: 200, json: [] });
    // 项目列表（复数）：空 → 侧栏显示「~/projects 暂无项目」
    if (path === '/projects') {
      return route.fulfill({
        status: 200,
        json: { projects_dir: '/tmp/projects', projects: [], active: null },
      });
    }
    // 项目上下文（单数）：无活动项目
    if (path === '/project/context') {
      return route.fulfill({
        status: 200,
        json: { path: '', project: '', branch: '', git_branch: '' },
      });
    }
    // 项目文件树（单数）：空（注意 tree 必须为数组，否则 ContextPanel projectFiles.length 崩）
    if (path === '/project/files') {
      return route.fulfill({ status: 200, json: { root: '', tree: [] } });
    }
    // 项目 diff（单数）：空数组（files 必须为数组）
    if (path === '/project/diff') return route.fulfill({ status: 200, json: { files: [] } });
    // 工厂列表：空数组 → 工厂面板显示「暂无工厂」
    if (path === '/factories') return route.fulfill({ status: 200, json: [] });
    // RCA 失败计数器：counter 必须为对象
    if (path === '/rca/failure_counter') return route.fulfill({ status: 200, json: { counter: {} } });
    // Assistant 历史：必须是数组（store.setAssistantTurns(turns)，Assistant.tsx 用 turns.map）
    // 路径形如 /assistant/sessions/{sid}/history
    if (path.startsWith('/assistant/sessions/') && path.endsWith('/history')) {
      return route.fulfill({ status: 200, json: [] });
    }

    // 兜底：其它 GET 返回空对象，POST 返回 ok
    const method = route.request().method();
    if (method === 'GET') return route.fulfill({ status: 200, json: {} });
    return route.fulfill({ status: 200, json: { ok: true } });
  });
}

/**
 * mock 一个会话创建响应：POST /sessions 返回单个 session。
 * 用于交互测试中点击「新对话」后 UI 能进入正常选中态。
 */
export async function mockCreateSession(page: Page, session = { id: 'sess-mock-1', title: '新对话', status: 'idle', mode: 'agent' }) {
  await page.route('http://127.0.0.1:8011/api/v1/sessions*', (route: Route) => {
    if (route.request().method() !== 'POST') return route.fulfill({ status: 200, json: [] });
    return route.fulfill({ status: 200, json: session });
  });
}
