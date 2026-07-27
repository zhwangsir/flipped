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
  fetchAssistantHistory,
  approveAssistant,
  rejectAssistant,
  connectEvents,
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

  it('approveAssistant POST /assistant/sessions/:id/approve', async () => {
    const fetchMock = mockFetch(async () => okResponse({ ok: true, session_id: 's', decision: 'approve' }));
    await approveAssistant('s1');
    const url = fetchMock.mock.calls[0][0] as string;
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(url).toContain('/assistant/sessions/s1/approve');
    expect(init.method).toBe('POST');
  });

  it('rejectAssistant POST /assistant/sessions/:id/reject', async () => {
    const fetchMock = mockFetch(async () => okResponse({ ok: true, session_id: 's', decision: 'reject' }));
    await rejectAssistant('s1');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
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
