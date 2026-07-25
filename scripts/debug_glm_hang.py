"""M149 排障: 复现 GLM-5.2-fp8 大 prompt + thinking off + temp=0 挂起。

直连 exo, stream=true, 观察 prefill 耗时与 token 流。
变量: prompt 规模(约 12k tokens) + tools + enable_thinking=false + temperature=0。
"""
import json
import time
import urllib.request

EXO = "http://studio01-1:52415/v1/chat/completions"

# 构造约 12k token 的系统 prompt（重复填充模拟 OpenHands 大系统提示）
filler = (
    "You are an autonomous software engineer agent. You must use tools to "
    "complete tasks. Follow safety rules. Always verify your work. "
) * 400  # ~30 tokens/iter × 400 ≈ 12k tokens

TOOLS = [{
    "type": "function",
    "function": {
        "name": "terminal",
        "description": "Execute a shell command",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
}]

payload = {
    "model": "mlx-community/GLM-5.2-fp8",
    "messages": [
        {"role": "system", "content": filler},
        {"role": "user", "content": "Create a file hello.py printing hello. Use the terminal tool."},
    ],
    "tools": TOOLS,
    "tool_choice": "auto",
    "temperature": 0,
    "max_tokens": 512,
    "stream": True,
    "extra_body": {
        "enable_thinking": False,
        "chat_template_kwargs": {"enable_thinking": False},
    },
}

req = urllib.request.Request(
    EXO,
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
)

t0 = time.monotonic()
print(f"[{time.strftime('%H:%M:%S')}] 发送请求 (~12k tokens prompt, stream=true) ...", flush=True)
first_token_at = None
chunks = 0
try:
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunks += 1
            if first_token_at is None:
                first_token_at = time.monotonic()
                print(f"[首 token] {first_token_at - t0:.1f}s", flush=True)
            if chunks <= 3 or chunks % 50 == 0:
                try:
                    d = json.loads(data)
                    delta = d["choices"][0].get("delta", {})
                    piece = delta.get("content") or ""
                    tc = delta.get("tool_calls")
                    print(f"  chunk#{chunks} +{time.monotonic()-t0:.1f}s content={piece[:40]!r} tc={'Y' if tc else '-'}", flush=True)
                except Exception:
                    pass
    wall = time.monotonic() - t0
    print(f"[完成] chunks={chunks} 总耗时 {wall:.1f}s", flush=True)
except Exception as exc:
    wall = time.monotonic() - t0
    print(f"[失败] {wall:.1f}s 后: {type(exc).__name__}: {exc}", flush=True)
