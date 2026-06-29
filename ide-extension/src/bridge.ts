// IDE 控制面 · agent↔扩展桥（D13）：本地 HTTP 让 Python 驾驭层调用 IDE 工具。
// 纯逻辑(分派/解析)抽出可单测；HTTP server 在 extension 侧。仅绑 127.0.0.1。
export type ToolMap = Record<string, (args: Record<string, unknown>) => Promise<unknown>>;

export interface ToolRequest {
  name: string;
  args: Record<string, unknown>;
}

/** 解析 POST /tool 的 body → {name, args}。 */
export function parseToolRequest(body: string): ToolRequest {
  const d = JSON.parse(body || "{}");
  if (typeof d.name !== "string" || !d.name) {
    throw new Error("missing tool name");
  }
  return { name: d.name, args: (d.args ?? {}) as Record<string, unknown> };
}

/** 按名分派到工具处理器；未知工具抛错。 */
export async function dispatchTool(
  name: string,
  args: Record<string, unknown>,
  tools: ToolMap,
): Promise<unknown> {
  const handler = tools[name];
  if (!handler) {
    throw new Error(`unknown tool: ${name}`);
  }
  return handler(args ?? {});
}
