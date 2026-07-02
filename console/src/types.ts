/** flipped Console 领域模型与后端事件转换。 */

export type SessionStatus = 'idle' | 'running' | 'done' | 'review' | 'error';

export type Role = 'user' | 'supervisor' | 'worker' | 'overseer' | 'verify' | 'system';

export type ToolName = 'terminal' | 'file_editor' | 'browser' | 'search';

export interface ToolChild {
  type: 'file_change' | 'terminal' | 'browser' | 'output';
  text: string;
}

export interface ToolCall {
  tool: ToolName;
  summary: string;
  detail?: string;
  status: 'ok' | 'running' | 'error';
  children?: ToolChild[];
}

export interface ApprovalInfo {
  id: string;
  action?: string;
  reason?: string;
  risk?: string;
}

export interface StreamItem {
  id: string;
  role: Role;
  model?: string;
  text?: string;
  tools?: ToolCall[];
  verdict?: { efficiency: number; direction: number; action: string; note: string };
  ok?: boolean;
}

export interface Session {
  id: string;
  title: string;
  status: SessionStatus;
  model: string;
  created_at: string;
  updated_at: string;
}

/** ContextPanel 从事件流派生的真实上下文数据（M6.1）。 */
export interface TerminalBlock {
  command: string;
  output: string;
  exit?: number;
}
export interface BrowserView {
  url: string;
  title?: string;
  screenshot?: string;
}
export interface ChangedFile {
  path: string;
  change: string;
  language?: string;
}

/** orchestration-api 发过来的原始事件（与 src/api/schemas.py 对齐）。 */
export interface ApiEvent {
  id: string;
  session_id: string;
  type: string;
  agent: Role | null;
  payload: Record<string, any>;
  parent_id?: string | null;
  created_at?: string;
}

/** 把后端事件转成 StreamItem；无法展示的事件返回 null。 */
export function eventToStreamItem(ev: ApiEvent): StreamItem | null {
  const role = ev.agent || 'system';
  const p = ev.payload;
  switch (ev.type) {
    case 'message':
      // 隐藏机械 system prompt
      if (role === 'system') return null;
      return { id: ev.id, role, text: p.text };
    case 'tool_call':
      return {
        id: ev.id,
        role,
        tools: [{ tool: p.tool as ToolName, summary: p.summary || p.tool, status: p.status || 'running' }],
      };
    case 'tool_result':
      return {
        id: ev.id,
        role,
        tools: [{ tool: p.tool as ToolName, summary: p.summary || p.tool, status: p.status || 'ok' }],
      };
    case 'terminal':
      return { id: ev.id, role, text: `$ ${p.command || ''}\n${p.output || ''}` };
    case 'file_change':
      return { id: ev.id, role, text: `文件变更: ${p.path} (${p.change || 'mod'})` };
    case 'browser':
      return { id: ev.id, role, text: `浏览器: ${p.url}${p.title ? ` (${p.title})` : ''}` };
    case 'error':
      return { id: ev.id, role: 'system', text: p.message };
    case 'approval_result': {
      const approved = ['approve', 'approved', '同意', '放行'].includes(p.decision);
      return { id: ev.id, role: 'user', text: approved ? '审批：已放行' : '审批：已否决' };
    }
    case 'status':
    case 'checkpoint':
    case 'approval_request':
      return null;
    default:
      return { id: ev.id, role, text: JSON.stringify(p) };
  }
}

/** 简单的相对时间，用于会话列表。 */
export function formatWhen(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const sec = Math.max(0, Math.floor((now - then) / 1000));
  if (sec < 60) return '刚刚';
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小时前`;
  return new Date(iso).toLocaleDateString();
}
