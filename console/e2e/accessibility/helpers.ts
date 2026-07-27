/**
 * 无障碍测试共享 mock helper。
 *
 * 拦截 store.tsx 挂载时调用的所有后端 API，返回最小确定性数据，让前端组件树
 * 能完整渲染（topbar / sidebar / Assistant / FactoryPanel），同时避免真实
 * 后端会话/工厂列表变化导致扫描结果 flaky。
 *
 * 与 store.tsx useEffect 列表对齐：
 *   - /sessions                → Session[]
 *   - /metrics                 → Metrics
 *   - /mcp/servers             → McpServer[]
 *   - /projects                → { projects_dir, projects, active }
 *   - /project/context         → ProjectContext
 *   - /project/files           → { root, tree }
 *   - /project/diff            → { files }
 *   - /factories               → FactorySummary[]
 *   - /assistant/sessions/:id/history → AssistantTurn[]
 */
import type { Page } from '@playwright/test';

export async function mockBackend(page: Page, opts: { withApproval?: boolean } = {}): Promise<void> {
  const sessions = [
    {
      id: 'a11y-sess-1',
      title: 'a11y mock 线程',
      status: 'idle',
      model: 'coder',
      mode: 'agent',
      project: '/tmp/a11y-proj',
      project_name: 'a11y-proj',
      goal: 'mock',
      created_at: '2026-07-27T00:00:00+00:00',
      updated_at: '2026-07-27T00:00:00+00:00',
    },
    {
      id: 'a11y-sess-2',
      title: 'a11y mock 对话',
      status: 'idle',
      model: 'coder',
      mode: 'chat',
      project: null,
      project_name: null,
      goal: null,
      created_at: '2026-07-27T00:00:00+00:00',
      updated_at: '2026-07-27T00:00:00+00:00',
    },
  ];

  await page.route('**/api/v1/sessions', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(sessions),
    });
  });

  await page.route('**/api/v1/metrics', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        llm: { total_calls: 0, errors: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, avg_latency_ms: 0 },
      }),
    });
  });

  await page.route('**/api/v1/mcp/servers', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  });

  // 关键：返回 { projects_dir, projects, active } 而非裸数组，否则 store setProjects(undefined) 崩溃
  await page.route('**/api/v1/projects', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        projects_dir: '/tmp/a11y-projects',
        projects: [{ name: 'a11y-proj', host: '/tmp/a11y-proj', sandbox: '/projects/a11y-proj' }],
        active: null,
      }),
    });
  });

  await page.route('**/api/v1/project/context', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ project: 'a11y-proj', path: '/tmp/a11y-proj', sandbox: '/projects/a11y-proj', branch: 'main', mode: 'agent' }),
    });
  });

  await page.route('**/api/v1/project/files', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ root: '/tmp/a11y-proj', tree: [] }) });
  });

  await page.route('**/api/v1/project/diff', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ files: [] }) });
  });

  await page.route('**/api/v1/factories', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          factory_id: 'a11y-factory-1',
          product_goal: 'a11y mock 工厂',
          cwd: '/tmp/a11y-factory',
          status: 'done',
          total_tasks: 3,
          completed: 3,
          failed: 0,
          current_task_id: null,
          iteration_count: 1,
          max_tasks: 3,
          created_at: '2026-07-27T00:00:00+00:00',
          updated_at: '2026-07-27T00:00:00+00:00',
        },
      ]),
    });
  });

  // 工厂详情（点开列表项时拉取）
  // 形状必须对齐 src/types.ts 的 FactoryDetail 扁平结构（factory_id/roadmap/completed/failed
  // 均在顶层），而非嵌套 {factory, tasks, summary}。FactoryPanel.tsx 直接读 detail.factory_id /
  // detail.roadmap.length，嵌套形会让 detail.factory_id 为 undefined → undefined.slice() 抛错。
  // 含 1 条 done 任务，让 factory.spec.ts 的任务行交互（fd-task-chev）可被验证。
  const detailTask = {
    id: 'a11y-task-1',
    description: 'a11y mock 任务：创建基础结构',
    verify_cmd: ['test -f /tmp/a11y-factory/index.html'],
    status: 'done',
    attempts: 1,
    feedback: '验证通过',
    depends_on: [],
    artifacts: ['/tmp/a11y-factory/index.html'],
  };
  await page.route('**/api/v1/factories/*/detail', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        factory_id: 'a11y-factory-1',
        product_goal: 'a11y mock 工厂',
        cwd: '/tmp/a11y-factory',
        status: 'done',
        roadmap: [detailTask],
        completed: [
          { task: detailTask, verified: true, stop_reason: 'verified', iteration: 1, summary: 'ok' },
        ],
        failed: [],
        current_task_id: null,
        context_summary: '',
        iteration_count: 1,
        max_tasks: 3,
        created_at: '2026-07-27T00:00:00+00:00',
        updated_at: '2026-07-27T00:00:00+00:00',
      }),
    });
  });

  await page.route('**/api/v1/factories/*/rca_history', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ entries: [] }) });
  });

  await page.route('**/api/v1/factories/*/quality-trend', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ points: [] }) });
  });

  await page.route('**/api/v1/rca/failure_counter', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ total: 0, by_class: {} }) });
  });

  // Assistant 历史：默认空 turns（渲染空态 hero）
  const historyBody = opts.withApproval
    ? [
        {
          role: 'approval',
          text: null,
          approval: { id: 'a11y-approval-1', action: 'rm -rf /tmp/test', risk: 'high', reason: '删除操作' },
          tools: [],
          ts: '2026-07-27T00:00:00+00:00',
        },
      ]
    : [];
  await page.route('**/api/v1/assistant/sessions/*/history', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(historyBody) });
  });
}
