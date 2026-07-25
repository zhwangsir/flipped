"""M149 · GLM-5.2-fp8 tool-calling 契约测试（经 LiteLLM proxy :4000）。

背景：M0 关键验收 = 工具调用必须被正确解析为结构化 tool_calls；
若模型把调用塞进 content（parser 失效特征），agentic 全链路会静默失败。
此前该验收只存在于 scripts/toolcall_test.py 手动脚本，未进 pytest 回归网。

M149 单模型模式：architect = coder = GLM-5.2-fp8，两别名都必须过契约。
门控：与 test_orchestrator_ide_action.py 相同的 _litellm_reachable() 模式——
无 master key 或 proxy 不可达时 skip，不阻塞离线全量回归。
"""
import json
import os
import socket
import urllib.request

import pytest

PROXY = "http://127.0.0.1:4000"

WEATHER_TOOL = {
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
}


def _litellm_reachable() -> bool:
    if not os.environ.get("LITELLM_MASTER_KEY"):
        return False
    try:
        with socket.create_connection(("127.0.0.1", 4000), timeout=2):
            return True
    except OSError:
        return False


def _chat_with_tool(alias: str) -> dict:
    payload = {
        "model": alias,
        "messages": [
            {"role": "user",
             "content": "What is the weather in Tokyo right now? Use the get_weather tool."}
        ],
        "tools": [WEATHER_TOOL],
        "tool_choice": "auto",
        "max_tokens": 256,
        "temperature": 0,
    }
    req = urllib.request.Request(
        f"{PROXY}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as r:  # 本地大模型首 token 慢
        return json.load(r)


pytestmark = pytest.mark.skipif(
    not _litellm_reachable(),
    reason="无 LITELLM_MASTER_KEY 或 LiteLLM 127.0.0.1:4000 不可达",
)


@pytest.mark.parametrize("alias", ["architect", "coder"])
def test_glm_toolcall_returns_structured_tool_calls(alias):
    """两别名经 proxy 调 GLM-5.2-fp8：必须返回结构化 tool_calls 而非 content 内嵌。"""
    msg = _chat_with_tool(alias)["choices"][0]["message"]

    tool_calls = msg.get("tool_calls")
    assert tool_calls, (
        f"[{alias}] 未返回 tool_calls（parser 失效特征）。"
        f"content 片段: {(msg.get('content') or '')[:200]!r}"
    )

    fn = tool_calls[0].get("function", {})
    assert fn.get("name") == "get_weather", f"[{alias}] 工具名错误: {fn.get('name')!r}"
    args = json.loads(fn.get("arguments") or "{}")
    assert "tokyo" in (args.get("city") or "").lower(), f"[{alias}] 参数 city 异常: {args!r}"


@pytest.mark.parametrize("alias", ["architect", "coder"])
def test_glm_toolcall_content_has_no_unparsed_call(alias):
    """content 不得残留未解析的工具调用文本（parser 失效的显式断言）。"""
    msg = _chat_with_tool(alias)["choices"][0]["message"]
    content = (msg.get("content") or "").lower()
    assert "get_weather" not in content, f"[{alias}] content 内疑似未解析工具调用: {content[:200]!r}"
