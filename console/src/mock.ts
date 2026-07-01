// flipped Console 演示数据（仅用于未接入真实数据的面板：文件树 / diff / 终端 / MCP / 问题）。

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
