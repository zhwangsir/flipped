"""M149.13 多轮上下文增长悬崖测试：SP10886 + 逐轮累积对话历史。

假设：SP 悬崖真正约束的是【总上下文长度】而非仅系统提示。
第一轮 SP10886 + user(468) ≈ 11.4k 安全；多轮后总长度破 ~13k 应退化。
档位：追加 0/1/2/3 轮 (assistant tool_call + tool_result) 历史，每轮 ~1.2k chars。
判定：finish_reason / tool_calls JSON 有效性 / alpha 占比。
"""
import json
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
                "command": {"type": "string", "description": "The shell command to execute."},
                "timeout": {"type": "integer", "description": "Timeout in seconds."},
                "security_risk": _RISK},
            "required": ["command", "security_risk"]}}},
    {"type": "function", "function": {
        "name": "file_editor",
        "description": "Custom editing tool for viewing, creating and editing files in plain-text format.",
        "parameters": {"type": "object", "description": "Schema for file editor operations.",
            "properties": {
                "command": {"type": "string", "enum": ["view", "create", "str_replace", "insert", "undo_edit"]},
                "path": {"type": "string"},
                "file_text": {"type": "string"},
                "old_str": {"type": "string"},
                "new_str": {"type": "string"},
                "insert_line": {"type": "integer"},
                "view_range": {"type": "array", "items": {"type": "integer"}},
                "security_risk": _RISK},
            "required": ["command", "path", "security_risk"]}}},
]


def make_history_round(i: int) -> list[dict]:
    """一轮典型 OH 历史：assistant tool_call + tool 结果（~1.2k chars）。"""
    filler = ("观测输出：文件列表与目录结构的详细内容，包含权限、大小、修改时间等元数据信息。"
              "drwxr-xr-x  5 user  staff  160 Jul 23 19:00 . ") * 6
    return [
        {"role": "assistant", "content": f"我先执行第 {i} 步探索。",
         "tool_calls": [{"id": f"call_{i}", "type": "function",
                         "function": {"name": "terminal",
                                      "arguments": json.dumps({"command": f"ls -la round{i}",
                                                               "security_risk": "LOW"})}}]},
        {"role": "tool", "tool_call_id": f"call_{i}", "content": filler},
    ]


def trial(n_rounds: int) -> None:
    msgs = [{"role": "system", "content": SP}, {"role": "user", "content": USER_MSG}]
    for i in range(n_rounds):
        msgs.extend(make_history_round(i))
    total_chars = sum(len(json.dumps(m, ensure_ascii=False)) for m in msgs)
    payload = {"model": "coder", "messages": msgs, "tools": TOOLS,
               "temperature": 0, "stream": False}
    req = urllib.request.Request(
        LITELLM, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"},
        method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        print(f"rounds={n_rounds} total~{total_chars}ch -> TIMEOUT/ERR {type(exc).__name__} ({time.monotonic()-t0:.0f}s)")
        return
    dt = time.monotonic() - t0
    ch = data["choices"][0]
    msg = ch["message"]
    content = msg.get("content") or ""
    tcs = msg.get("tool_calls") or []
    alpha = sum(c.isalpha() for c in content) / max(len(content), 1)
    json_ok = 0
    for tc in tcs:
        try:
            json.loads(tc["function"]["arguments"])
            json_ok += 1
        except Exception:
            pass
    verdict = "OK" if (tcs and json_ok == len(tcs) and alpha > 0.5) else "GARBAGE"
    print(f"rounds={n_rounds} total~{total_chars}ch -> {dt:.0f}s finish={ch.get('finish_reason')} "
          f"tc={len(tcs)} json_ok={json_ok} content_len={len(content)} alpha={alpha:.2f} [{verdict}]")
    if verdict == "GARBAGE":
        print(f"  content[:160]: {content[:160]!r}")
        if tcs:
            print(f"  tc0 args[:160]: {tcs[0]['function']['arguments'][:160]!r}")


for n in (0, 1, 2, 3):
    trial(n)
