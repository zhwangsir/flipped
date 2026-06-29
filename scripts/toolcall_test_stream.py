#!/usr/bin/env python3
"""流式工具调用验证（exo 非流式会 502，必须用 stream:true）。
用法: python3 scripts/toolcall_test_stream.py <model_id> [endpoint]
退出码 0=通过(收到结构化 tool_calls), 1=未通过/失败。"""
import sys, json, urllib.request

EP = sys.argv[2] if len(sys.argv) > 2 else "http://100.64.201.37:52415/v1/chat/completions"
model = sys.argv[1]
payload = {
    "model": model, "stream": True, "max_tokens": 256, "temperature": 0,
    "messages": [{"role": "user", "content": "What is the weather in Tokyo right now? Use the get_weather tool."}],
    "tools": [{"type": "function", "function": {
        "name": "get_weather", "description": "Get current weather for a city",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}],
    "tool_choice": "auto",
}
req = urllib.request.Request(EP, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
print(f"[{model}]")
tool_calls, content, finish = {}, "", None
try:
    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "ignore").strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                ch = (chunk.get("choices") or [{}])[0]
                delta = ch.get("delta", {}) or {}
                if delta.get("content"):
                    content += delta["content"]
                for tc in (delta.get("tool_calls") or []):
                    slot = tool_calls.setdefault(tc.get("index", 0), {"name": "", "arguments": ""})
                    fn = tc.get("function", {}) or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
except Exception as e:
    print(f"  ✗ 请求失败: {type(e).__name__}: {e}")
    sys.exit(1)

if tool_calls:
    for i, s in sorted(tool_calls.items()):
        print(f"  ✓ tool_call[{i}]: {s['name']}({s['arguments']})")
    print(f"  finish_reason={finish}  (content 旁路={content[:50]!r})")
    sys.exit(0)
print(f"  ✗ 无 tool_calls; finish={finish}; content={content[:200]!r}")
sys.exit(1)
