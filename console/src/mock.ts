// flipped Console 领域模型 + 演示数据(先 mock，再接 OpenHands + 监督编排)。

export type Role = "user" | "supervisor" | "worker" | "overseer" | "verify";

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
  status: "running" | "done" | "review";
  model: string;
  when: string;
}

export const sessions: Session[] = [
  { id: "s1", title: "FastAPI Todo API + 测试 + 浏览器验证", status: "running", model: "coder", when: "现在" },
  { id: "s2", title: "重构 auth 中间件，修 3 个失败用例", status: "done", model: "coder", when: "12 分钟前" },
  { id: "s3", title: "给 landing 页加暗色模式切换", status: "done", model: "coder", when: "1 小时前" },
  { id: "s4", title: "调研并接入 Stripe webhook", status: "review", model: "architect", when: "今天 09:14" },
];

export const stream: StreamItem[] = [
  {
    id: "1",
    role: "user",
    text: "用 FastAPI 建一个 Todo API(增/删/查)，写 pytest 跑通，并在内置浏览器打开 /docs 确认。",
  },
  {
    id: "2",
    role: "supervisor",
    model: "GLM-5.2",
    text: "拆解目标 → 子任务①：创建 app.py(Todo CRUD) 与 test_app.py，本地跑 pytest 通过。不传全量历史，交给执行者。",
  },
  {
    id: "3",
    role: "worker",
    model: "Kimi-K2.7",
    tools: [
      { tool: "file_editor", summary: "创建 app.py", detail: "FastAPI() · GET/POST/DELETE /todos", status: "ok" },
      { tool: "file_editor", summary: "创建 test_app.py", detail: "3 个用例：create / list / delete", status: "ok" },
      { tool: "terminal", summary: "pytest -q", detail: "3 passed in 0.42s", status: "ok" },
    ],
  },
  {
    id: "4",
    role: "overseer",
    model: "GLM-5.2",
    verdict: {
      efficiency: 0.9,
      direction: 1.0,
      action: "continue",
      note: "3 次工具调用完成建档 + 测试，无绕路；方向正确，放行下一步。",
    },
  },
  {
    id: "5",
    role: "supervisor",
    model: "GLM-5.2",
    text: "子任务②：启动 uvicorn，用内置浏览器打开 http://127.0.0.1:8000/docs 截图确认 Swagger 正常。",
  },
  {
    id: "6",
    role: "worker",
    model: "Kimi-K2.7",
    tools: [
      { tool: "terminal", summary: "uvicorn app:app --port 8000 &", detail: "Uvicorn running on 127.0.0.1:8000", status: "ok" },
      { tool: "browser", summary: "打开 /docs 并截图", detail: "标题：Todo API — Swagger UI", status: "ok" },
    ],
  },
  {
    id: "7",
    role: "overseer",
    model: "GLM-5.2",
    verdict: { efficiency: 0.95, direction: 1.0, action: "continue", note: "服务起、页面通、截图有据，达成目标。" },
  },
  {
    id: "8",
    role: "verify",
    text: "强制验收：pytest 全通过 + /docs HTTP 200 + Swagger 标题匹配 → 目标达成。",
    ok: true,
  },
];

export const diffLines: { type: "add" | "ctx"; text: string }[] = [
  { type: "ctx", text: "from fastapi import FastAPI, HTTPException" },
  { type: "ctx", text: "" },
  { type: "add", text: "app = FastAPI(title='Todo API')" },
  { type: "add", text: "_todos: dict[int, dict] = {}" },
  { type: "add", text: "" },
  { type: "add", text: "@app.get('/todos')" },
  { type: "add", text: "def list_todos():" },
  { type: "add", text: "    return list(_todos.values())" },
  { type: "add", text: "" },
  { type: "add", text: "@app.post('/todos')" },
  { type: "add", text: "def create_todo(title: str):" },
  { type: "add", text: "    tid = len(_todos) + 1" },
  { type: "add", text: "    _todos[tid] = {'id': tid, 'title': title}" },
  { type: "add", text: "    return _todos[tid]" },
];

export const terminalLines: string[] = [
  "$ pytest -q",
  "...                                                     [100%]",
  "3 passed in 0.42s",
  "$ uvicorn app:app --port 8000 &",
  "INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)",
  "INFO:     127.0.0.1 - \"GET /docs HTTP/1.1\" 200 OK",
];

export const files: { name: string; add?: boolean; depth: number }[] = [
  { name: "todo-api/", depth: 0 },
  { name: "app.py", add: true, depth: 1 },
  { name: "test_app.py", add: true, depth: 1 },
  { name: "requirements.txt", add: true, depth: 1 },
];

export const editorCode = `from fastapi import FastAPI, HTTPException

app = FastAPI(title="Todo API")
_todos: dict[int, dict] = {}


@app.get("/todos")
def list_todos():
    # 返回全部待办
    return list(_todos.values())


@app.post("/todos")
def create_todo(title: str):
    tid = len(_todos) + 1
    _todos[tid] = {"id": tid, "title": title}
    return _todos[tid]


@app.delete("/todos/{todo_id}")
def delete_todo(todo_id: int):
    if todo_id not in _todos:
        raise HTTPException(404, "not found")
    return _todos.pop(todo_id)`;

export interface TreeNode {
  name: string;
  kind: "folder" | "file";
  depth: number;
  open?: boolean;
  badge?: "add" | "mod";
  active?: boolean;
}
export const fileTree: TreeNode[] = [
  { name: "todo-api", kind: "folder", depth: 0, open: true },
  { name: "app.py", kind: "file", depth: 1, badge: "add", active: true },
  { name: "test_app.py", kind: "file", depth: 1, badge: "add" },
  { name: "requirements.txt", kind: "file", depth: 1, badge: "add" },
  { name: ".venv", kind: "folder", depth: 1 },
  { name: "README.md", kind: "file", depth: 1 },
];

export const mcpServers: { name: string; desc: string; tools: number; on: boolean }[] = [
  { name: "filesystem", desc: "读写沙盒文件", tools: 6, on: true },
  { name: "fetch", desc: "抓取网页为上下文", tools: 1, on: true },
  { name: "git", desc: "分支 / 提交 / diff", tools: 8, on: true },
  { name: "searxng", desc: "本地联网搜索", tools: 1, on: true },
  { name: "playwright", desc: "浏览器自动化", tools: 12, on: false },
];

export const problems: { level: "warn" | "error"; file: string; msg: string }[] = [
  { level: "warn", file: "app.py:14", msg: "create_todo 缺少返回类型标注" },
];
