/** flipped Console 领域模型与后端事件转换。 */

export type Role = "user" | "supervisor" | "worker" | "overseer" | "verify" | "system";

export type ToolName = "terminal" | "file_editor" | "browser" | "search";

export interface ToolCall {
  tool: ToolName;
  summary: string;
  detail?: string;
  status: "ok" | "running" | "error";
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
  status: "idle" | "running" | "done" | "review" | "error";
  model: string;
  created_at: string;
  updated_at: string;
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
  const role = ev.agent || "system";
  const p = ev.payload;
  switch (ev.type) {
    case "message":
      return { id: ev.id, role, model: p.model, text: p.text };
    case "tool_call":
      return {
        id: ev.id,
        role,
        tools: [{ tool: p.tool as ToolName, summary: p.summary || p.tool, status: p.status || "running" }],
      };
    case "tool_result":
      return {
        id: ev.id,
        role,
        tools: [{ tool: p.tool as ToolName, summary: p.summary || p.tool, status: p.status || "ok" }],
      };
    case "terminal":
      return { id: ev.id, role, text: `$ ${p.command || ""}\n${p.output || ""}` };
    case "file_change":
      return { id: ev.id, role, text: `文件变更: ${p.path} (${p.change || "mod"})` };
    case "browser":
      return { id: ev.id, role, text: `浏览器: ${p.url}${p.title ? ` (${p.title})` : ""}` };
    case "error":
      return { id: ev.id, role: "system", text: `错误: ${p.message}` };
    case "status":
    case "checkpoint":
    case "approval_request":
    case "approval_result":
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
  if (sec < 60) return "刚刚";
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小时前`;
  return new Date(iso).toLocaleDateString();
}
