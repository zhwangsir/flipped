import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import {
  fetchSessions,
  createSession,
  createTask,
  deleteSession,
  cancelTask,
  fetchMetrics,
  getMcpServers,
  fetchProjectContext,
  fetchProjectFiles,
  openProject,
  fetchProjects,
  createProject,
  fetchProjectFile,
  renderBrowser,
  fetchProjectDiff,
  revertProjectHunk,
  reviewProject,
  revealProject,
  toggleMcpServer,
  fetchFailureCounter,
  listFactories,
  createFactory,
  getFactoryDetail,
  resumeFactory,
  pauseFactory,
  fetchFactoryRcaHistory,
  fetchFactoryQualityTrend,
  createAssistantSession,
  sendAssistantMessage,
  startAssistantGoal,
  fetchAssistantGoal,
  fetchAssistantHistory,
  approveAssistant,
  rejectAssistant,
  compactAssistant,
  undoAssistant,
  editAssistantMessage,
  getMcpTools,
  callMcpTool,
  fetchProjectMap,
  regenerateProjectMap,
  connectEvents,
  fetchTasks,
  createScheduledTask,
  deleteTask,
  toggleTask,
  fetchBotChannels,
  testBotChannel,
  fetchWorkerRules,
  createWorkerRule,
  updateWorkerRule,
  deleteWorkerRule,
  toggleWorkerRule,
  fetchWorkerRuleVersions,
  rollbackWorkerRules,
  autoGenerateWorkerRules,
  fetchWorkerRuleStats,
} from './api';

// fetch 的统一 mock 工具
function mockFetch(impl: (url: string, init?: RequestInit) => Promise<{ ok: boolean; status: number; text: () => Promise<string>; json: () => Promise<unknown> }>) {
  const fn = vi.fn(impl);
  vi.stubGlobal('fetch', fn);
  return fn;
}

function okResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify(data),
    json: async () => data,
  };
}

function errResponse(status: number, text: string) {
  return {
    ok: false,
    status,
    text: async () => text,
    json: async () => { throw new Error('not json'); },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

beforeEach(() => {
  // 默认 fetch 返回空数组,避免未 mock 的测试报错
  mockFetch(async () => okResponse([]));
});

describe('api — HTTP GET 类', () => {
  it('fetchSessions GET /sessions', async () => {
    const fetchMock = mockFetch(async () => okResponse([{ id: 's1' }]));
    const result = await fetchSessions();
    expect(result).toEqual([{ id: 's1' }]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/api/v1/sessions');
  });

  it('fetchMetrics GET /metrics', async () => {
    const fetchMock = mockFetch(async () => okResponse({ llm: {}, context: {} }));
    await fetchMetrics();
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/metrics');
  });

  it('getMcpServers GET /mcp/servers', async () => {
    const fetchMock = mockFetch(async () => okResponse([]));
    await getMcpServers();
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/mcp/servers');
  });

  it('fetchProjectContext GET /project/context', async () => {
    const fetchMock = mockFetch(async () => okResponse({ project: 'p', branch: 'main', mode: 'agent' }));
    await fetchProjectContext();
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/project/context');
  });

  it('fetchProjectFiles GET /project/files', async () => {
    const fetchMock = mockFetch(async () => okResponse({ root: '/r', tree: [] }));
    await fetchProjectFiles();
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/project/files');
  });

  it('fetchProjects GET /projects', async () => {
    const fetchMock = mockFetch(async () => okResponse({ projects_dir: '/x', projects: [], active: null }));
    await fetchProjects();
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/projects');
  });

  it('fetchProjectFile GET /project/file 并编码 path', async () => {
    const fetchMock = mockFetch(async () => okResponse({ path: 'a b', content: 'x' }));
    await fetchProjectFile('a b');
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/api/v1/project/file?path=a%20b');
  });

  it('fetchProjectDiff GET /project/diff', async () => {
    const fetchMock = mockFetch(async () => okResponse({ files: [] }));
    await fetchProjectDiff();
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/project/diff');
  });

  it('revertProjectHunk POST /project/revert-hunk(M193.2;body 带 path + hunk_index)', async () => {
    const fetchMock = mockFetch(async () =>
      okResponse({ ok: true, path: 'src/a.ts', hunk_index: 1, action: 'hunk_reverted' })
    );
    const r = await revertProjectHunk('src/a.ts', 1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('/api/v1/project/revert-hunk');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ path: 'src/a.ts', hunk_index: 1 });
    expect(r.action).toBe('hunk_reverted');
    expect(r.hunk_index).toBe(1);
  });

  it('reviewProject POST /project/review(M179.2;无 model → 空 body {})', async () => {
    const fetchMock = mockFetch(async () =>
      okResponse({ findings: [], files_reviewed: 0, model: 'coder', note: '工作区干净' })
    );
    const r = await reviewProject();
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('/api/v1/project/review');
    expect(init.method).toBe('POST');
    expect(init.body).toBe('{}');
    expect(r.files_reviewed).toBe(0);
    expect(r.note).toBe('工作区干净');
  });

  it('reviewProject(model) → body 带 model;错误响应原样抛 HTTP 错误', async () => {
    const fetchMock = mockFetch(async () =>
      okResponse({
        findings: [{ path: 'a.ts', line: 1, severity: 'high', message: 'm', suggestion: null }],
        files_reviewed: 1,
        model: 'kimi',
      })
    );
    const r = await reviewProject('kimi');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ model: 'kimi' });
    expect(r.findings).toHaveLength(1);
    expect(r.findings[0].severity).toBe('high');

    mockFetch(async () => errResponse(502, 'LLM 解析失败'));
    await expect(reviewProject()).rejects.toThrow('HTTP 502');
  });

  it('fetchProjectMap GET /project/map(M173 项目地图)', async () => {
    const fetchMock = mockFetch(async () => okResponse({ map: null, needs_project: true }));
    const result = await fetchProjectMap();
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/project/map');
    expect(result.needs_project).toBe(true);
    expect(result.map).toBeNull();
  });

  it('fetchFailureCounter GET /rca/failure_counter', async () => {
    const fetchMock = mockFetch(async () => okResponse({ counter: { x: 2 } }));
    await fetchFailureCounter();
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/rca/failure_counter');
  });

  it('listFactories GET /factories', async () => {
    const fetchMock = mockFetch(async () => okResponse([]));
    await listFactories();
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/factories');
  });

  it('getFactoryDetail GET /factories/:id/detail 并编码 id', async () => {
    const fetchMock = mockFetch(async () => okResponse({ factory_id: 'x y' }));
    await getFactoryDetail('x y');
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/api/v1/factories/x%20y/detail');
  });

  it('fetchFactoryRcaHistory GET /factories/:id/rca_history', async () => {
    const fetchMock = mockFetch(async () => okResponse({ items: [] }));
    await fetchFactoryRcaHistory('f1');
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/factories/f1/rca_history');
  });

  it('fetchFactoryQualityTrend GET /factories/:id/quality-trend', async () => {
    const fetchMock = mockFetch(async () => okResponse({ points: [] }));
    await fetchFactoryQualityTrend('f1');
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/factories/f1/quality-trend');
  });

  it('fetchAssistantHistory GET /assistant/sessions/:id/history', async () => {
    const fetchMock = mockFetch(async () => okResponse([]));
    await fetchAssistantHistory('s1');
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/assistant/sessions/s1/history');
  });
});

describe('api — HTTP POST/DELETE 类', () => {
  it('createSession POST /sessions 并编码 title/mode', async () => {
    const fetchMock = mockFetch(async () => okResponse({ id: 's' }));
    await createSession('我的标题', 'chat');
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/api/v1/sessions');
    expect(url).toContain('title=');
    expect(url).toContain('mode=chat');
    expect(init.method).toBe('POST');
  });

  it('createTask POST /sessions/:id/tasks 带 body', async () => {
    const fetchMock = mockFetch(async () => okResponse({}));
    await createTask('s1', '做点事', 'coder', 'agent');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
    const body = JSON.parse(init.body as string);
    expect(body.description).toBe('做点事');
    expect(body.context.model).toBe('coder');
    expect(body.context.mode).toBe('agent');
  });

  it('createTask 不传 model/mode 时 context 为空对象', async () => {
    const fetchMock = mockFetch(async () => okResponse({}));
    await createTask('s1', '做点事');
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.context).toEqual({});
  });

  it('deleteSession DELETE /sessions/:id', async () => {
    const fetchMock = mockFetch(async () => okResponse({ ok: true }));
    await deleteSession('s1');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('DELETE');
  });

  it('cancelTask POST /sessions/:id/cancel', async () => {
    const fetchMock = mockFetch(async () => okResponse({ id: 's1' }));
    await cancelTask('s1');
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/api/v1/sessions/s1/cancel');
    expect(init.method).toBe('POST');
  });

  it('openProject POST /project/open 带 path', async () => {
    const fetchMock = mockFetch(async () => okResponse({ name: 'p', host: '/h', sandbox: '/s' }));
    await openProject('/host/path');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ path: '/host/path' });
  });

  it('createProject POST /projects 带 name', async () => {
    const fetchMock = mockFetch(async () => okResponse({ name: 'n' }));
    await createProject('myproj');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ name: 'myproj' });
  });

  it('renderBrowser POST /browser/render 带 url', async () => {
    const fetchMock = mockFetch(async () => okResponse({ url: 'u', title: '', screenshot: '', elements: [], viewport: { width: 1, height: 1 } }));
    await renderBrowser('http://x');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ url: 'http://x' });
  });

  it('revealProject POST /project/reveal', async () => {
    const fetchMock = mockFetch(async () => okResponse({ ok: true }));
    await revealProject();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
  });

  it('regenerateProjectMap POST /project/map/regenerate(M173 强制重建)', async () => {
    const fetchMock = mockFetch(async () =>
      okResponse({
        map: { markdown: '# x', generated_at: '2026-08-04T00:00:00Z', stale: false, from_cache: false, stack: ['ts'] },
        needs_project: false,
      })
    );
    const result = await regenerateProjectMap();
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/api/v1/project/map/regenerate');
    expect(init.method).toBe('POST');
    expect(result.map?.stack).toEqual(['ts']);
  });

  it('toggleMcpServer POST /mcp/servers/:name/toggle?enabled=bool 并编码 name', async () => {
    const fetchMock = mockFetch(async () => okResponse({ name: 'n', enabled: true }));
    await toggleMcpServer('my server', true);
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/api/v1/mcp/servers/my%20server/toggle');
    expect(url).toContain('enabled=true');
    expect(init.method).toBe('POST');
  });

  it('createFactory POST /factories 默认 max_tasks=10', async () => {
    const fetchMock = mockFetch(async () => okResponse({}));
    await createFactory('goal', '/cwd');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ product_goal: 'goal', cwd: '/cwd', max_tasks: 10 });
  });

  it('createFactory 自定义 max_tasks', async () => {
    const fetchMock = mockFetch(async () => okResponse({}));
    await createFactory('g', '/c', 5);
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.max_tasks).toBe(5);
  });

  it('resumeFactory POST /factories/:id/resume', async () => {
    const fetchMock = mockFetch(async () => okResponse({}));
    await resumeFactory('f1');
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/factories/f1/resume');
    expect(init.method).toBe('POST');
  });

  it('pauseFactory POST /factories/:id/pause', async () => {
    const fetchMock = mockFetch(async () => okResponse({}));
    await pauseFactory('f1');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
  });

  it('createAssistantSession POST /assistant/sessions 默认值', async () => {
    const fetchMock = mockFetch(async () => okResponse({ id: 's' }));
    await createAssistantSession();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
    const body = JSON.parse(init.body as string);
    expect(body.title).toBe('新对话');
    expect(body.mode).toBe('agent');
    expect(body.model_alias).toBe('coder');
    expect(body.cwd).toBeUndefined();
  });

  it('createAssistantSession 透传 cwd', async () => {
    const fetchMock = mockFetch(async () => okResponse({ id: 's' }));
    await createAssistantSession({ cwd: '/proj' });
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.cwd).toBe('/proj');
  });

  it('sendAssistantMessage POST /assistant/sessions/:id/messages', async () => {
    const fetchMock = mockFetch(async () => okResponse({ task_id: 't', session_id: 's' }));
    await sendAssistantMessage('s1', { text: 'hello', mode: 'chat' });
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/assistant/sessions/s1/messages');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ text: 'hello', mode: 'chat' });
  });

  // M176 — Goal 模式:startAssistantGoal / fetchAssistantGoal
  it('startAssistantGoal POST /assistant/sessions/:id/goal 带 body 并编码 id', async () => {
    const fetchMock = mockFetch(async () =>
      okResponse({ task_id: 't', session_id: 's', objective: 'o', max_iterations: 5 })
    );
    await startAssistantGoal('s 1', { objective: '修复 bug', mode: 'agent', model: 'coder', max_iterations: 3 });
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/assistant/sessions/s%201/goal');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({
      objective: '修复 bug',
      mode: 'agent',
      model: 'coder',
      max_iterations: 3,
    });
  });

  it('fetchAssistantGoal GET 同径;200 → 状态对象', async () => {
    const fetchMock = mockFetch(async () =>
      okResponse({ objective: 'o', status: 'running', iteration: 2, max_iterations: 5, gap: '还差 1 处' })
    );
    const r = await fetchAssistantGoal('s1');
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/assistant/sessions/s1/goal');
    expect(r?.status).toBe('running');
    expect(r?.iteration).toBe(2);
    expect(r?.gap).toBe('还差 1 处');
  });

  it('fetchAssistantGoal 404 → null(无 goal);500 → 抛错', async () => {
    mockFetch(async () => errResponse(404, 'no goal'));
    expect(await fetchAssistantGoal('s1')).toBeNull();
    mockFetch(async () => errResponse(500, 'boom'));
    await expect(fetchAssistantGoal('s1')).rejects.toThrow('HTTP 500');
  });

  it('approveAssistant POST /assistant/sessions/:id/approve', async () => {
    const fetchMock = mockFetch(async () => okResponse({ ok: true, session_id: 's', decision: 'approve' }));
    await approveAssistant('s1');
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/assistant/sessions/s1/approve');
    expect(init.method).toBe('POST');
  });

  // M165.2a — Always 审批:scope 透传后端
  it('approveAssistant 带 scope=always → body 含 {scope:"always"}', async () => {
    const fetchMock = mockFetch(async () => okResponse({ ok: true, session_id: 's', decision: 'approve' }));
    await approveAssistant('s1', 'always');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ scope: 'always' });
  });

  it('approveAssistant 不传 scope → 无 body(兼容旧契约)', async () => {
    const fetchMock = mockFetch(async () => okResponse({ ok: true, session_id: 's', decision: 'approve' }));
    await approveAssistant('s1');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.body).toBeUndefined();
  });

  // M165.1a — /compact 压缩上下文端点
  it('compactAssistant POST /assistant/sessions/:id/compact', async () => {
    const fetchMock = mockFetch(async () => okResponse({ ok: true, session_id: 's', summary: '压缩摘要' }));
    const r = await compactAssistant('s1');
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/assistant/sessions/s1/compact');
    expect(init.method).toBe('POST');
    expect(r.summary).toBe('压缩摘要');
  });

  // M168.2 — /undo 撤销最近一轮 agent 文件改动端点(对标 opencode /undo)
  it('undoAssistant POST /assistant/sessions/:id/undo(无 body)', async () => {
    const fetchMock = mockFetch(async () =>
      okResponse({ ok: true, session_id: 's1', restored: true, deleted: ['a.ts', 'b.ts'] })
    );
    const r = await undoAssistant('s1');
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/assistant/sessions/s1/undo');
    expect(init.method).toBe('POST');
    expect(init.body).toBeUndefined();
    expect(r.ok).toBe(true);
    expect(r.session_id).toBe('s1');
    expect(r.restored).toBe(true);
    expect(r.deleted).toEqual(['a.ts', 'b.ts']);
  });

  it('rejectAssistant POST /assistant/sessions/:id/reject', async () => {
    const fetchMock = mockFetch(async () => okResponse({ ok: true, session_id: 's', decision: 'reject' }));
    await rejectAssistant('s1');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
  });

  // M174-C — 编辑 user 消息并重跑端点(截断该事件后历史,默认恢复文件)
  it('editAssistantMessage POST /assistant/sessions/:sid/messages/:eid/edit', async () => {
    const fetchMock = mockFetch(async () =>
      okResponse({ ok: true, session_id: 's1', task_id: 't2', truncated: true, restored: true, deleted: ['a.ts'] })
    );
    const r = await editAssistantMessage('s1', 'e1', '改后的文本');
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/assistant/sessions/s1/messages/e1/edit');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ text: '改后的文本', restore_files: true });
    expect(r.ok).toBe(true);
    expect(r.session_id).toBe('s1');
    expect(r.task_id).toBe('t2');
    expect(r.truncated).toBe(true);
    expect(r.restored).toBe(true);
    expect(r.deleted).toEqual(['a.ts']);
  });

  it('editAssistantMessage restoreFiles=false → body restore_files:false', async () => {
    const fetchMock = mockFetch(async () =>
      okResponse({ ok: true, session_id: 's1', task_id: 't3', truncated: true, restored: false, deleted: [] })
    );
    await editAssistantMessage('s1', 'e1', 'x', false);
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body).toEqual({ text: 'x', restore_files: false });
  });
});

// M170.2 — MCP 工具列表/调用端点(Plugins 面板「MCP 工具调用」)
describe('api — MCP 工具调用 (M170.2)', () => {
  it('getMcpTools GET /mcp/tools 并返回 tools 列表', async () => {
    const fetchMock = mockFetch(async () =>
      okResponse({
        tools: [
          { name: 'web_search', description: '联网搜索', inputSchema: { type: 'object' } },
          { name: 'rag_query', description: '知识库检索', inputSchema: { type: 'object' } },
        ],
      })
    );
    const r = await getMcpTools();
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit | undefined;
    expect(url).toContain('/api/v1/mcp/tools');
    expect(init?.method ?? 'GET').toBe('GET');
    expect(r.tools).toHaveLength(2);
    expect(r.tools[0].name).toBe('web_search');
    expect(r.tools[0].description).toBe('联网搜索');
  });

  it('callMcpTool POST /mcp/tools/:name/call 带 arguments body', async () => {
    const fetchMock = mockFetch(async () =>
      okResponse({ ok: true, tool: 'web_search', result: { hits: ['a', 'b'] } })
    );
    const r = await callMcpTool('web_search', { arguments: { query: 'mlx server' } });
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/api/v1/mcp/tools/web_search/call');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ arguments: { query: 'mlx server' } });
    expect(r.ok).toBe(true);
    expect(r.result).toEqual({ hits: ['a', 'b'] });
  });

  it('callMcpTool 编码工具名并透传 session_id(长工具 202 契约)', async () => {
    const fetchMock = mockFetch(async () =>
      okResponse({ ok: true, accepted: true, tool: 'run_coding_task', session_id: 's1' })
    );
    const r = await callMcpTool('run_coding_task', {
      arguments: { goal: '修 bug' },
      session_id: 's1',
    });
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/api/v1/mcp/tools/run_coding_task/call');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({
      arguments: { goal: '修 bug' },
      session_id: 's1',
    });
    expect(r.accepted).toBe(true);
    expect(r.session_id).toBe('s1');
  });
});

describe('api — 错误处理', () => {
  it('非 ok 响应抛出 HTTP {status}: {text}', async () => {
    mockFetch(async () => errResponse(404, 'not found'));
    await expect(fetchSessions()).rejects.toThrow('HTTP 404: not found');
  });

  it('500 响应抛出 HTTP 500', async () => {
    mockFetch(async () => errResponse(500, 'server error'));
    await expect(fetchMetrics()).rejects.toThrow('HTTP 500');
  });
});

// M163.1 — 畸形响应降级：后端返回非数组 sessions 时，fetchSessions 应回退为 []，
// 而非把对象/原始值原样传出导致下游 .filter/.map 崩溃。
// 钉的行为：呼应 e2e/error-handling/malformed-response.spec.ts:67（store 应兜底）。
describe('api — 畸形响应降级 (M163.1)', () => {
  it('fetchSessions 返回对象而非数组 → 降级为 []', async () => {
    mockFetch(async () => okResponse({ not: 'an array' }));
    const result = await fetchSessions();
    expect(Array.isArray(result)).toBe(true);
    expect(result).toEqual([]);
  });

  it('fetchSessions 返回 null → 降级为 []', async () => {
    mockFetch(async () => okResponse(null));
    const result = await fetchSessions();
    expect(result).toEqual([]);
  });

  it('fetchSessions 返回合法数组 → 原样透传（不误伤正常路径）', async () => {
    mockFetch(async () => okResponse([{ id: 's1' }]));
    const result = await fetchSessions();
    expect(result).toEqual([{ id: 's1' }]);
  });
});

// M178.2 — 已安排任务端点(后台任务系统)
describe('api — 已安排任务 (M178.2)', () => {
  it('fetchTasks GET /tasks 返回数组', async () => {
    const fetchMock = mockFetch(async () => okResponse([{ id: 'task-1', title: '巡检' }]));
    const result = await fetchTasks();
    expect(result).toEqual([{ id: 'task-1', title: '巡检' }]);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/api/v1/tasks');
  });

  it('fetchTasks 非数组响应降级为 []', async () => {
    mockFetch(async () => okResponse({ not: 'an array' }));
    const result = await fetchTasks();
    expect(Array.isArray(result)).toBe(true);
    expect(result).toEqual([]);
  });

  it('createScheduledTask POST /tasks 带 body', async () => {
    const fetchMock = mockFetch(async () => okResponse({ id: 'task-9' }));
    const body = {
      title: '每日巡检',
      prompt: '跑一遍测试',
      mode: 'agent',
      kind: 'interval' as const,
      every_minutes: 60,
      run_at: null,
    };
    const r = await createScheduledTask(body);
    expect(r.id).toBe('task-9');
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/api/v1/tasks');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual(body);
  });

  it('deleteTask DELETE /tasks/:id', async () => {
    const fetchMock = mockFetch(async () => okResponse({ ok: true }));
    const r = await deleteTask('task-1');
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/api/v1/tasks/task-1');
    expect(init.method).toBe('DELETE');
    expect(r).toEqual({ ok: true });
  });

  it('toggleTask POST /tasks/:id/toggle?enabled=bool(无 body)', async () => {
    const fetchMock = mockFetch(async () => okResponse({ id: 'task-1', enabled: false }));
    const r = await toggleTask('task-1', false);
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/api/v1/tasks/task-1/toggle?enabled=false');
    expect(init.method).toBe('POST');
    expect(r.enabled).toBe(false);
  });
});

// M182 — Bot 通道端点(多平台消息接入)
describe('api — Bot 通道 (M182)', () => {
  it('fetchBotChannels GET /bot/channels 并取 channels 字段', async () => {
    const channels = [
      {
        platform: 'telegram',
        enabled: true,
        configured: true,
        inbound_count: 3,
        outbound_count: 5,
        error_count: 0,
        last_inbound_at: 1722700000,
        last_outbound_at: 1722700100,
        last_error: '',
      },
    ];
    const fetchMock = mockFetch(async () => okResponse({ channels }));
    const result = await fetchBotChannels();
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/api/v1/bot/channels');
    expect(result).toEqual(channels);
    expect(result[0].platform).toBe('telegram');
  });

  it('testBotChannel POST /bot/channels/:platform/test 带 {text} body 并编码 platform', async () => {
    const fetchMock = mockFetch(async () => okResponse({ ok: true }));
    const r = await testBotChannel('my plat', 'ping from console');
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/api/v1/bot/channels/my%20plat/test');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ text: 'ping from console' });
    expect(r.ok).toBe(true);
  });

  it('testBotChannel 失败响应 → {ok:false,error}', async () => {
    mockFetch(async () => okResponse({ ok: false, error: 'chat_id 未配置' }));
    const r = await testBotChannel('telegram', 'x');
    expect(r.ok).toBe(false);
    expect(r.error).toBe('chat_id 未配置');
  });
});

// M183 — Worker 规则端点(学习系统:CRUD + 版本史 + 回滚 + 自动生成 + 统计)
describe('api — Worker 规则 (M183)', () => {
  const sampleRule = {
    id: 'r1',
    text: '修复后必须跑测试',
    scope: 'worker',
    source: 'manual',
    enabled: true,
    priority: 50,
    created_at: 1722700000,
  };

  it('fetchWorkerRules GET /worker/rules', async () => {
    const fetchMock = mockFetch(async () => okResponse({ version: 3, rules: [sampleRule] }));
    const r = await fetchWorkerRules();
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/worker/rules');
    expect(r.version).toBe(3);
    expect(r.rules).toHaveLength(1);
  });

  it('createWorkerRule POST /worker/rules 默认 scope=worker 带 priority', async () => {
    const fetchMock = mockFetch(async () => okResponse(sampleRule));
    await createWorkerRule('新规则', 'worker', 80);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ text: '新规则', scope: 'worker', priority: 80 });
  });

  it('updateWorkerRule PUT /worker/rules/:id 带 patch body', async () => {
    const fetchMock = mockFetch(async () => okResponse(sampleRule));
    await updateWorkerRule('r 1', { text: '改', priority: 90 });
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/api/v1/worker/rules/r%201');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body as string)).toEqual({ text: '改', priority: 90 });
  });

  it('deleteWorkerRule DELETE /worker/rules/:id', async () => {
    const fetchMock = mockFetch(async () => okResponse({ ok: true }));
    const r = await deleteWorkerRule('r1');
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/api/v1/worker/rules/r1');
    expect(init.method).toBe('DELETE');
    expect(r.ok).toBe(true);
  });

  it('toggleWorkerRule POST /worker/rules/:id/toggle 带 {enabled} body', async () => {
    const fetchMock = mockFetch(async () => okResponse({ ...sampleRule, enabled: false }));
    const r = await toggleWorkerRule('r1', false);
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/api/v1/worker/rules/r1/toggle');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ enabled: false });
    expect(r.enabled).toBe(false);
  });

  it('fetchWorkerRuleVersions GET /worker/rules/versions 并取 versions 字段', async () => {
    const versions = [{ version: 2, ts: 1722700000, action: 'create', detail: '新增规则', rule_count: 5 }];
    const fetchMock = mockFetch(async () => okResponse({ versions }));
    const r = await fetchWorkerRuleVersions();
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/worker/rules/versions');
    expect(r).toEqual(versions);
    expect(r[0].rule_count).toBe(5);
  });

  it('rollbackWorkerRules POST /worker/rules/rollback 带 {version} body', async () => {
    const fetchMock = mockFetch(async () => okResponse({ ok: true, version: 4 }));
    const r = await rollbackWorkerRules(2);
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/api/v1/worker/rules/rollback');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ version: 2 });
    expect(r).toEqual({ ok: true, version: 4 });
  });

  it('autoGenerateWorkerRules POST /worker/rules/auto-generate 空 body {}', async () => {
    const fetchMock = mockFetch(async () => okResponse({ added: [sampleRule], candidates: 3 }));
    const r = await autoGenerateWorkerRules();
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/api/v1/worker/rules/auto-generate');
    expect(init.method).toBe('POST');
    expect(init.body).toBe('{}');
    expect(r.added).toHaveLength(1);
    expect(r.candidates).toBe(3);
  });

  it('fetchWorkerRuleStats GET /worker/rules/stats', async () => {
    const fetchMock = mockFetch(async () =>
      okResponse({ stats: { r1: { applied: 4, success: 3, failure: 1 } }, total_runs: 10 })
    );
    const r = await fetchWorkerRuleStats();
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/worker/rules/stats');
    expect(r.stats.r1.applied).toBe(4);
    expect(r.total_runs).toBe(10);
  });
});

describe('api — connectEvents WebSocket', () => {
  function mockWs() {
    const handlers: Record<string, ((e?: unknown) => void) | undefined> = {};
    const ws = {
      readyState: 0,
      onopen: null as null | (() => void),
      onclose: null as null | (() => void),
      onerror: null as null | ((e: unknown) => void) | null,
      onmessage: null as null | ((msg: { data: string }) => void),
      send: vi.fn(),
      close: vi.fn(),
      // 测试触发辅助
      _fire(name: 'open' | 'close' | 'error', e?: unknown) {
        handlers[name]?.(e);
      },
      _message(data: unknown) {
        handlers.message?.({ data: JSON.stringify(data) });
      },
    };
    Object.defineProperty(ws, 'onopen', {
      get: () => handlers.open,
      set: (v) => { handlers.open = v || undefined; },
    });
    Object.defineProperty(ws, 'onclose', {
      get: () => handlers.close,
      set: (v) => { handlers.close = v || undefined; },
    });
    Object.defineProperty(ws, 'onerror', {
      get: () => handlers.error,
      set: (v) => { handlers.error = v || undefined; },
    });
    Object.defineProperty(ws, 'onmessage', {
      get: () => handlers.message,
      set: (v) => { handlers.message = v || undefined; },
    });
    // Vitest 4：箭头函数无 [[Construct]]，构造函数 mock 必须用 function 关键字
    const Ctor = vi.fn(function () { return ws; }) as unknown as { new (url: string): typeof ws; OPEN: number; CONNECTING: number; CLOSING: number; CLOSED: number };
    Ctor.OPEN = 1;
    Ctor.CONNECTING = 0;
    Ctor.CLOSING = 2;
    Ctor.CLOSED = 3;
    vi.stubGlobal('WebSocket', Ctor);
    return { ws, Ctor };
  }

  it('connectEvents 创建 WebSocket 并 onopen 回调', () => {
    const { ws } = mockWs();
    const onOpen = vi.fn();
    const onMessage = vi.fn();
    const conn = connectEvents('s1', { onMessage, onOpen });
    ws.readyState = 1; // OPEN
    ws._fire('open');
    expect(onOpen).toHaveBeenCalled();
    conn.close();
    expect(ws.close).toHaveBeenCalled();
  });

  it('onmessage 解析 JSON 并转发给 onMessage', () => {
    const { ws } = mockWs();
    const onMessage = vi.fn();
    connectEvents('s1', { onMessage });
    const event = { type: 'message', data: 'x' };
    ws._message(event);
    expect(onMessage).toHaveBeenCalledWith(event);
  });

  it('onmessage 收到非法 JSON 不抛错(静默忽略)', () => {
    const { ws } = mockWs();
    const onMessage = vi.fn();
    connectEvents('s1', { onMessage });
    // 直接调用 onmessage with bad data
    ws.onmessage?.({ data: '{bad json' });
    expect(onMessage).not.toHaveBeenCalled();
  });

  it('主动 close 不触发重连', () => {
    const { ws } = mockWs();
    const onClose = vi.fn();
    const conn = connectEvents('s1', { onMessage: vi.fn(), onClose });
    conn.close();
    ws._fire('close');
    expect(onClose).toHaveBeenCalled();
  });

  it('getLastEventId 透传 ?last_event_id=', () => {
    const { Ctor } = mockWs();
    connectEvents('s1', { onMessage: vi.fn(), getLastEventId: () => 'evt-42' });
    const calls = (Ctor as unknown as { mock: { calls: string[][] } }).mock.calls;
    expect(calls[0][0]).toContain('last_event_id=evt-42');
  });

  it('send 在 readyState=OPEN 时调用 ws.send', () => {
    const { ws } = mockWs();
    const conn = connectEvents('s1', { onMessage: vi.fn() });
    ws.readyState = 1; // OPEN
    conn.send({ foo: 'bar' });
    expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ foo: 'bar' }));
  });

  it('send 在 readyState!=OPEN 时不调用 ws.send', () => {
    const { ws } = mockWs();
    const conn = connectEvents('s1', { onMessage: vi.fn() });
    ws.readyState = 0; // CONNECTING
    conn.send({ foo: 'bar' });
    expect(ws.send).not.toHaveBeenCalled();
  });

  it('onerror 转发给 handler.onError', () => {
    const { ws } = mockWs();
    const onError = vi.fn();
    connectEvents('s1', { onMessage: vi.fn(), onError });
    const err = new Event('error');
    ws._fire('error', err);
    expect(onError).toHaveBeenCalledWith(err);
  });
});
