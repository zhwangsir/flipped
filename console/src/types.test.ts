import { describe, it, expect } from 'vitest';
import { detectServerUrl, eventToStreamItem, formatWhen, type ApiEvent } from './types';

// ---- detectServerUrl:从终端输出探测 dev server(F-detect / Windsurf 式) ----

describe('detectServerUrl', () => {
  it('探测 Vite 风格输出', () => {
    expect(detectServerUrl('  ➜  Local:   http://localhost:5173/')).toBe('http://localhost:5173');
  });
  it('探测 uvicorn/127.0.0.1', () => {
    expect(detectServerUrl('Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C)')).toBe(
      'http://127.0.0.1:8000'
    );
  });
  it('0.0.0.0 归一化为 localhost', () => {
    expect(detectServerUrl('listening on http://0.0.0.0:3000')).toBe('http://localhost:3000');
  });
  it('保留路径,去尾斜杠', () => {
    expect(detectServerUrl('open http://localhost:8011/api/v1/health/')).toBe(
      'http://localhost:8011/api/v1/health'
    );
  });
  it('无 URL 返回 null', () => {
    expect(detectServerUrl('just some build output, 3 passed')).toBeNull();
  });
  it('非 localhost 外部 URL 不误报', () => {
    expect(detectServerUrl('fetching https://example.com/api')).toBeNull();
  });
  it('空串返回 null', () => {
    expect(detectServerUrl('')).toBeNull();
  });
});

// ---- eventToStreamItem:后端事件 → UI StreamItem ----

function ev(type: string, agent: ApiEvent['agent'], payload: Record<string, unknown>): ApiEvent {
  return { id: 'e1', session_id: 's1', type, agent, payload };
}

describe('eventToStreamItem', () => {
  it('message/worker → 文本条目', () => {
    const item = eventToStreamItem(ev('message', 'worker', { text: '你好' }));
    expect(item).toMatchObject({ role: 'worker', text: '你好' });
  });
  it('机械 system message 隐藏(返回 null)', () => {
    expect(eventToStreamItem(ev('message', 'system', { text: 'sys prompt' }))).toBeNull();
  });
  it('plan 事件不进消息流(单独渲染成卡片)', () => {
    expect(eventToStreamItem(ev('plan', 'supervisor', { steps: [], complete: false }))).toBeNull();
  });
  it('status/checkpoint/approval_request → null', () => {
    expect(eventToStreamItem(ev('status', 'system', {}))).toBeNull();
    expect(eventToStreamItem(ev('checkpoint', 'system', {}))).toBeNull();
    expect(eventToStreamItem(ev('approval_request', 'system', {}))).toBeNull();
  });
  it('tool_call → 带 running 工具', () => {
    const item = eventToStreamItem(ev('tool_call', 'worker', { tool: 'terminal', summary: 'pytest' }));
    expect(item?.tools?.[0]).toMatchObject({ tool: 'terminal', summary: 'pytest', status: 'running' });
  });
  it('terminal → $ 命令 + 输出', () => {
    const item = eventToStreamItem(ev('terminal', 'worker', { command: 'ls', output: 'a\nb' }));
    expect(item?.text).toBe('$ ls\na\nb');
  });
  it('error → system 文本', () => {
    const item = eventToStreamItem(ev('error', 'system', { message: '炸了' }));
    expect(item).toMatchObject({ role: 'system', text: '炸了' });
  });
  it('approval_result 放行 → 用户条目', () => {
    const item = eventToStreamItem(ev('approval_result', 'user', { decision: 'approve' }));
    expect(item).toMatchObject({ role: 'user', text: '审批：已放行' });
  });
  it('未知类型 → JSON 兜底(不崩)', () => {
    const item = eventToStreamItem(ev('weird', 'worker', { a: 1 }));
    expect(item?.text).toContain('"a":1');
  });
});

// ---- formatWhen:相对时间 ----

describe('formatWhen', () => {
  const ago = (sec: number) => new Date(Date.now() - sec * 1000).toISOString();
  it('30 秒内 → 刚刚', () => expect(formatWhen(ago(30))).toBe('刚刚'));
  it('分钟级', () => expect(formatWhen(ago(120))).toBe('2 分钟前'));
  it('小时级', () => expect(formatWhen(ago(3 * 3600))).toBe('3 小时前'));
  it('昨天', () => expect(formatWhen(ago(24 * 3600 + 60))).toBe('昨天'));
});
