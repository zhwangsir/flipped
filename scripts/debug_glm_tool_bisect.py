"""M149.10 · 工具 schema 复杂度二分：定位 5 真实工具触发 exo 数据面超时/垃圾参数的具体成分。

基线已知（debug_glm_replay_oh.py）：
- 14k SP + 2 简单工具 + 非stream + thinking off → 3/3 有效（13-25s）
- 14k SP + 5 真实工具（security_risk 枚举×3 + task_tracker 嵌套数组）→ 超时或垃圾参数

本脚本从 2 简单工具逐步加料到全量 5 工具，每档 1 发请求；
若某档超时，紧跟一发"恢复探针"（2 简单工具）判断 wedge 是否粘滞。

用法: .venv/bin/python3 scripts/debug_glm_tool_bisect.py
"""
import json
import time
import urllib.request

SP = json.load(open("/tmp/oh_sysprompt.json"))
KEY = ""
for raw in open(".env"):
    if raw.startswith("LITELLM_MASTER_KEY="):
        KEY = raw.strip().split("=", 1)[1]

USER = {"role": "user", "content": "在工作目录创建 hello.py，打印 hello world。使用工具完成。"}

_RISK = {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"],
         "description": "Assess the security risk of this action."}

# 简单版（与 replay 的 TOOLS 相同）
T_TERMINAL_SIMPLE = {"type": "function", "function": {
    "name": "terminal",
    "description": "Execute a bash command in the terminal and return its output.",
    "parameters": {"type": "object", "properties": {
        "command": {"type": "string", "description": "The bash command to execute."},
        "timeout": {"type": "integer", "description": "Timeout in seconds."},
    }, "required": ["command"]}}}
T_FILE_SIMPLE = {"type": "function", "function": {
    "name": "file_editor",
    "description": "Create, view or edit files.",
    "parameters": {"type": "object", "properties": {
        "command": {"type": "string", "enum": ["create", "view", "str_replace"]},
        "path": {"type": "string"},
        "file_text": {"type": "string"},
        "old_str": {"type": "string"},
        "new_str": {"type": "string"},
    }, "required": ["command", "path"]}}}

# 真实版组件
T_TERMINAL_RISK = {"type": "function", "function": {
    "name": "terminal",
    "description": "Execute a shell command in the terminal within a persistent shell session.",
    "parameters": {"type": "object", "description": "Schema for terminal command execution.",
        "properties": {
            "command": {"type": "string", "description": "The shell command to execute. Can be empty string to view current output."},
            "timeout": {"type": "integer", "description": "Timeout in seconds."},
            "security_risk": _RISK,
        }, "required": ["command", "security_risk"]}}}
T_FILE_RISK = {"type": "function", "function": {
    "name": "file_editor",
    "description": "Custom editing tool for viewing, creating and editing files in plain-text format.",
    "parameters": {"type": "object", "description": "Schema for file editor operations.",
        "properties": {
            "command": {"type": "string", "enum": ["view", "create", "str_replace", "insert"]},
            "path": {"type": "string"},
            "file_text": {"type": "string"},
            "old_str": {"type": "string"},
            "new_str": {"type": "string"},
            "insert_line": {"type": "integer"},
            "view_range": {"type": "array", "items": {"type": "integer"}},
            "security_risk": _RISK,
        }, "required": ["command", "path", "security_risk"]}}}
T_TRACKER = {"type": "function", "function": {
    "name": "task_tracker",
    "description": "This tool provides structured task management capabilities for development workflows.",
    "parameters": {"type": "object", "description": "An action where the agent writes or updates a task list for task management.",
        "properties": {
            "command": {"type": "string", "description": "The command to execute: view or plan."},
            "task_list": {"type": "array", "items": {"type": "object", "properties": {
                "title": {"type": "string"},
                "status": {"type": "string", "enum": ["todo", "in_progress", "done"]},
                "notes": {"type": "string"},
            }, "required": ["title", "status"]}},
            "security_risk": _RISK,
        }, "required": ["command", "security_risk"]}}}
T_FINISH = {"type": "function", "function": {
    "name": "finish",
    "description": "Signals the completion of the current task or conversation.",
    "parameters": {"type": "object", "properties": {
        "message": {"type": "string", "description": "Final message to send to the user."},
    }, "required": ["message"]}}}
T_THINK = {"type": "function", "function": {
    "name": "think",
    "description": "Use the tool to think about something. It will not obtain new information or make any changes to the system.",
    "parameters": {"type": "object", "properties": {
        "thought": {"type": "string", "description": "The thought to log."},
    }, "required": ["thought"]}}}

# 二分档位：逐档加料
R_LEVELS = [
    ("R1 2简单工具(基线)", [T_TERMINAL_SIMPLE, T_FILE_SIMPLE]),
    ("R2 +think+finish", [T_TERMINAL_SIMPLE, T_FILE_SIMPLE, T_THINK, T_FINISH]),
    ("R3 真实terminal(带risk)", [T_TERMINAL_RISK, T_FILE_SIMPLE]),
    ("R4 真实file_editor(带risk+嵌套)", [T_TERMINAL_SIMPLE, T_FILE_RISK]),
    ("R5 双真实+risk", [T_TERMINAL_RISK, T_FILE_RISK]),
    ("R6 +task_tracker嵌套数组", [T_TERMINAL_RISK, T_FILE_RISK, T_TRACKER]),
    ("R7 全量5真实工具(=H)", [T_TERMINAL_RISK, T_FILE_RISK, T_TRACKER, T_FINISH, T_THINK]),
]

RECOVERY = [T_TERMINAL_SIMPLE, T_FILE_SIMPLE]


def one_call(tools, timeout=180, max_tokens=150):
    payload = {
        "model": "coder",
        "messages": [{"role": "system", "content": SP}, USER],
        "temperature": 0, "max_tokens": max_tokens, "stream": False,
        "tools": tools, "tool_choice": "auto",
        "extra_body": {"enable_thinking": False,
                       "chat_template_kwargs": {"enable_thinking": False}},
    }
    req = urllib.request.Request(
        "http://localhost:4000/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {KEY}"}, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.loads(resp.read())
    except Exception as e:
        return time.monotonic() - t0, "TIMEOUT/ERR", str(e)[:80]
    dt = time.monotonic() - t0
    m = d["choices"][0]["message"]
    tcs = m.get("tool_calls") or []
    if not tcs:
        return dt, "NO_TOOLCALL", (m.get("content") or "")[:80]
    args = tcs[0]["function"]["arguments"]
    try:
        parsed = json.loads(args)
        # 语义校验：参数 key 必须是 schema properties 的子集
        props = set(tcs[0]["function"].get("_props", []))
        bad_keys = [k for k in parsed if "</" in k or "arg_" in k or len(k) > 40]
        if bad_keys:
            return dt, "GARBAGE_KEYS", f"tool={tcs[0]['function']['name']} keys={bad_keys[:2]}"
        return dt, "OK", f"tool={tcs[0]['function']['name']} args={json.dumps(parsed, ensure_ascii=False)[:80]}"
    except Exception:
        return dt, "INVALID_JSON", args[:100]


def main():
    print(f"SP={len(SP)}chars 非stream thinking=off max_tokens=150 timeout=180s\n")
    for tag, tools in R_LEVELS:
        dt, verdict, detail = one_call(tools)
        print(f"[{tag}] {dt:.0f}s {verdict} {detail}", flush=True)
        if verdict in ("TIMEOUT/ERR", "GARBAGE_KEYS", "INVALID_JSON"):
            # 恢复探针：wedge 是否粘滞
            dt2, v2, d2 = one_call(RECOVERY)
            print(f"  ↳ 恢复探针(2简单工具): {dt2:.0f}s {v2} {d2}", flush=True)
    print("\n完成。")


if __name__ == "__main__":
    main()
