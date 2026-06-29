#!/usr/bin/env python3
"""单次工具调用(function calling)解析验证。

用法: python3 scripts/toolcall_test.py <model_id> [endpoint]
判定: 模型对带 tools 的请求返回结构化 tool_calls -> 通过；
      若把调用塞进 content -> parser 失效特征；
      退出码 0 = 通过, 1 = 未通过/失败。
"""
import sys
import json
import urllib.request

DEFAULT_ENDPOINT = "http://100.64.201.37:52415/v1/chat/completions"


def run(model: str, endpoint: str) -> bool:
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "What is the weather in Tokyo right now? Use the get_weather tool."}
        ],
        "tools": [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string", "description": "City name"}},
                    "required": ["city"],
                },
            },
        }],
        "tool_choice": "auto",
        "max_tokens": 256,
        "temperature": 0,
    }
    req = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    print(f"[{model}]")
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            data = json.load(r)
    except Exception as e:  # noqa: BLE001 — 边界处统一捕获并如实上报
        body = ""
        try:
            body = e.read().decode()[:300]  # type: ignore[attr-defined]
        except Exception:
            pass
        print(f"  ✗ 请求失败: {type(e).__name__}: {e}  {body}")
        return False

    msg = data["choices"][0]["message"]
    tool_calls = msg.get("tool_calls")
    if tool_calls:
        fn = tool_calls[0].get("function", {})
        print(f"  ✓ 工具调用解析成功 -> name={fn.get('name')} args={fn.get('arguments')}")
        return True

    content = (msg.get("content") or "")[:300]
    print(f"  ✗ 未返回 tool_calls。content 片段: {content!r}")
    if "get_weather" in content or "tool_call" in content.lower():
        print("  ⚠ content 内疑似有未被解析的工具调用 = parser 失效特征")
    return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 scripts/toolcall_test.py <model_id> [endpoint]")
        sys.exit(2)
    model_id = sys.argv[1]
    ep = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_ENDPOINT
    sys.exit(0 if run(model_id, ep) else 1)
