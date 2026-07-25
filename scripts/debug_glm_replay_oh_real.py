"""M149.11 真实路径重放：OH 第一轮完整 payload（SP10886 + 真实任务 + 全量5工具）。

与 bisect 稳定配置的唯一差异：user msg 为真实任务 + 不设 max_tokens。
判定：tool_calls 参数是否为有效 JSON / 内容是否乱码。
"""
import json
import os
import time
import urllib.request

LITELLM = "http://localhost:4000/v1/chat/completions"
KEY = None
for line in open("/Users/wangzhenyu/Desktop/ALLProject/flipped/.env"):
    if line.startswith("LITELLM_MASTER_KEY="):
        KEY = line.strip().split("=", 1)[1]
assert KEY

SP = open("/tmp/oh_sp.txt").read()
USER_MSG = open("/tmp/oh_user.txt").read()

_RISK = {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"],
         "description": "Assess the security risk of this action."}
TOOLS = [
    {"type": "function", "function": {
        "name": "terminal",
        "description": "Execute a shell command in the terminal within a persistent shell session.",
        "parameters": {"type": "object", "description": "Schema for terminal command execution.",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute. Can be empty string to view current output."},
                "timeout": {"type": "integer", "description": "Timeout in seconds."},
                "security_risk": _RISK},
            "required": ["command", "security_risk"]}}},
    {"type": "function", "function": {
        "name": "file_editor",
        "description": "Custom editing tool for viewing, creating and editing files in plain-text format.",
        "parameters": {"type": "object", "description": "Schema for file editor operations.",
            "properties": {
                "command": {"type": "string", "description": "The commands to run. Allowed options are: `view`, `create`, `str_replace`, `insert`, `undo_edit`.",
                            "enum": ["view", "create", "str_replace", "insert", "undo_edit"]},
                "path": {"type": "string", "description": "Absolute path to file or directory."},
                "file_text": {"type": "string", "description": "Required parameter of `create` command, with the content of the file to be created."},
                "old_str": {"type": "string", "description": "Required parameter of `str_replace` command containing the string in `path` to replace."},
                "new_str": {"type": "string", "description": "Optional parameter of `str_replace` command containing the new string."},
                "insert_line": {"type": "integer", "description": "Required parameter of `insert` command."},
                "view_range": {"type": "array", "items": {"type": "integer"}, "description": "Optional parameter of `view` command."},
                "security_risk": _RISK},
            "required": ["command", "path", "security_risk"]}}},
    {"type": "function", "function": {
        "name": "task_tracker",
        "description": "This tool provides structured task management capabilities for development workflows.",
        "parameters": {"type": "object", "description": "An action where the agent writes or updates a task list for task management.",
            "properties": {
                "command": {"type": "string", "description": "The command to execute. `view` shows the current task list. `plan` creates or updates the task list.",
                            "enum": ["view", "plan"]},
                "task_list": {"type": "array", "description": "The full task list. Required parameter of `plan` command.",
                    "items": {"type": "object", "properties": {
                        "title": {"type": "string"}, "status": {"type": "string", "enum": ["todo", "in_progress", "done"]},
                        "notes": {"type": "string"}}}}},
            "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Signals the completion of the current task or conversation.",
        "parameters": {"type": "object", "properties": {
            "message": {"type": "string", "description": "Final message to send to the user."}},
            "required": ["message"]}}},
    {"type": "function", "function": {
        "name": "think",
        "description": "Use the tool to think about something. It will not obtain new information or make any changes.",
        "parameters": {"type": "object", "properties": {
            "thought": {"type": "string", "description": "The thought to log."}},
            "required": ["thought"]}}},
]

for trial in range(3):
    payload = {
        "model": "coder",
        "messages": [{"role": "system", "content": SP},
                     {"role": "user", "content": USER_MSG}],
        "temperature": 0,
        "stream": False,
        "tools": TOOLS,
        "tool_choice": "auto",
        "extra_body": {"enable_thinking": False,
                       "chat_template_kwargs": {"enable_thinking": False}},
    }
    req = urllib.request.Request(
        LITELLM, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = json.loads(resp.read())
        dt = time.time() - t0
        ch = body["choices"][0]
        msg = ch["message"]
        content = msg.get("content") or ""
        tcs = msg.get("tool_calls") or []
        usage = body.get("usage", {})
        alpha = sum(c.isalpha() for c in content)
        ratio = alpha / max(len(content), 1)
        print(f"--- trial {trial+1}: {dt:.1f}s finish={ch.get('finish_reason')} "
              f"usage={usage.get('prompt_tokens')}->{usage.get('completion_tokens')} "
              f"tool_calls={len(tcs)} content_len={len(content)} alpha={ratio:.2f}")
        for tc in tcs:
            args = tc["function"]["arguments"]
            try:
                json.loads(args)
                ok = "JSON-OK"
            except Exception:
                ok = "JSON-BAD"
            print(f"    {tc['function']['name']} args[{ok}]: {args[:200]}")
        if content:
            print(f"    content[:200]: {content[:200]!r}")
    except Exception as exc:
        print(f"--- trial {trial+1}: FAIL {time.time()-t0:.1f}s {exc}")
