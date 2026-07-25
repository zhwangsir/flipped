"""M149.6 · GLM-5.2-fp8 + OpenHands 真实系统提示复现实验。

v7 E2E 实测：OpenHands 14k chars 系统提示 + 复杂工具 → 模型输出全面乱码
（temperature=0、thinking off 均不免疫）。本脚本用提取的真实系统提示
+ OpenHands 风格工具 schema，参数化测试哪种配置能产生合法 tool_calls。

用法: python3 scripts/debug_glm_replay_oh.py <variant>
  A = 完整系统提示 + 工具, stream, thinking off (= v7 配置, 预期乱码)
  B = 同 A 但非 stream
  C = 同 A 但 thinking on
  D = 截断系统提示(前 2k chars) + 工具
  E = 完整系统提示, 无工具
"""
import json
import os
import sys
import time
import urllib.request

SP = json.load(open("/tmp/oh_sysprompt.json"))
KEY = ""
for raw in open(os.path.join(os.path.dirname(__file__), "..", ".env")):
    if raw.startswith("LITELLM_MASTER_KEY="):
        KEY = raw.strip().split("=", 1)[1]

# OpenHands 风格工具（terminal + file_editor，schema 复杂度贴近真实）
TOOLS = [
    {"type": "function", "function": {
        "name": "terminal",
        "description": "Execute a bash command in the terminal and return its output.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "The bash command to execute."},
            "timeout": {"type": "integer", "description": "Timeout in seconds."},
        }, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "file_editor",
        "description": "Create, view or edit files.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "enum": ["create", "view", "str_replace"]},
            "path": {"type": "string"},
            "file_text": {"type": "string"},
            "old_str": {"type": "string"},
            "new_str": {"type": "string"},
        }, "required": ["command", "path"]}}},
]

USER = {"role": "user", "content": "在工作目录创建 hello.py，打印 hello world。使用工具完成。"}

# M149.9 变体 H：贴近真实 OpenHands 路径的 5 工具（每个动作带 security_risk 枚举、
# task_tracker 嵌套数组、finish/think 默认工具），用于隔离"工具 schema 复杂度"变量。
_RISK = {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"],
         "description": "Assess the security risk of this action."}
REAL_TOOLS = [
    {"type": "function", "function": {
        "name": "terminal",
        "description": "Execute a shell command in the terminal within a persistent shell session.",
        "parameters": {"type": "object", "description": "Schema for terminal command execution.",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute. Can be empty string to view current output."},
                "timeout": {"type": "integer", "description": "Timeout in seconds."},
                "security_risk": _RISK,
            }, "required": ["command", "security_risk"]}}},
    {"type": "function", "function": {
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
            }, "required": ["command", "path", "security_risk"]}}},
    {"type": "function", "function": {
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
            }, "required": ["command", "security_risk"]}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Signals the completion of the current task or conversation.",
        "parameters": {"type": "object", "properties": {
            "message": {"type": "string", "description": "Final message to send to the user."},
        }, "required": ["message"]}}},
    {"type": "function", "function": {
        "name": "think",
        "description": "Use the tool to think about something. It will not obtain new information or make any changes to the system.",
        "parameters": {"type": "object", "properties": {
            "thought": {"type": "string", "description": "The thought to log."},
        }, "required": ["thought"]}}},
]


def run(variant: str) -> None:
    sp = SP[:2000] if variant == "D" else SP
    tools = None if variant == "E" else TOOLS
    if variant == "H":
        tools = REAL_TOOLS  # M149.9: 5 真实工具变体（其余同 B：非 stream + thinking off）
    stream = variant not in ("B", "F", "H")
    thinking = variant in ("C", "F")
    # M149.9: max_tokens 经 env 覆盖——隔离"长生成预算"变量（真实 OH 路径 16384 vs 回放 300）
    max_tokens = int(os.environ.get("GLM_REPLAY_MAX_TOKENS", "300"))
    payload = {
        "model": "coder",
        "messages": [{"role": "system", "content": sp}, USER],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": stream,
        "extra_body": {"enable_thinking": thinking,
                       "chat_template_kwargs": {"enable_thinking": thinking}},
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    req = urllib.request.Request(
        "http://localhost:4000/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {KEY}"}, method="POST")

    print(f"[{variant}] sys={len(sp)}chars tools={bool(tools)} stream={stream} thinking={thinking}")
    t0 = time.monotonic()
    content, tc = "", None
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            if stream:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:") or line == "data: [DONE]":
                        continue
                    d = json.loads(line[5:])
                    delta = d.get("choices", [{}])[0].get("delta", {})
                    content += delta.get("content") or ""
                    if delta.get("tool_calls"):
                        tc = delta["tool_calls"]
            else:
                d = json.loads(resp.read())
                m = d["choices"][0]["message"]
                content = m.get("content") or ""
                tc = m.get("tool_calls")
    except Exception as exc:
        print(f"  ERROR after {time.monotonic()-t0:.0f}s: {exc}")
        return

    dt = time.monotonic() - t0
    # 乱码判据: 可打印 ASCII 字母占比过低 或 含大量重复数字碎片
    letters = sum(c.isalpha() for c in content)
    ratio = letters / max(len(content), 1)
    gibberish = ratio < 0.5 and not tc
    print(f"  {dt:.0f}s content_len={len(content)} alpha_ratio={ratio:.2f} "
          f"tool_calls={'YES' if tc else 'no'} 判定={'乱码!' if gibberish else 'OK'}")
    print(f"  content 片段: {content[:160]!r}")
    if tc:
        print(f"  tool_call: {json.dumps(tc)[:200]}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "A")
