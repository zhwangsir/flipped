"""web_search 单测 — DuckDuckGo 内置搜索，开箱即用。

默认使用 DuckDuckGo 免费 API，无需 Docker、无需代理、无需配置。
若配置了 SEARXNG_URL 环境变量则使用自托管 SearXNG。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from tools.web_search import SearchError, format_for_llm, search  # noqa: E402


def _ddg_reachable() -> bool:
    """M149: DuckDuckGo 是外网依赖（开发机走 Clash 时可能全网不通），
    与 _litellm_reachable() 同模式——依赖不可达时 skip，避免环境抖动污染回归网。"""
    import socket
    try:
        with socket.create_connection(("duckduckgo.com", 443), timeout=3):
            return True
    except OSError:
        return False


_requires_ddg = pytest.mark.skipif(
    not _ddg_reachable(), reason="DuckDuckGo 外网不可达（环境性，非代码回归）"
)


@_requires_ddg
def test_search_returns_results():
    """内置 DuckDuckGo 搜索应返回结果（开箱即用，无需外部服务）。"""
    r = search("Python programming language", max_results=3)
    assert isinstance(r, list), "搜索结果应为列表"
    assert len(r) >= 1, "应至少返回 1 条结果"
    for item in r:
        assert "url" in item, "每条结果须含 url"
        assert "title" in item, "每条结果须含 title"
        assert item["url"].startswith("http"), f"URL 格式错误: {item['url']}"


def test_empty_query_raises():
    """空 query 应抛 SearchError。"""
    try:
        search("")
    except SearchError:
        return
    raise AssertionError("空 query 应抛 SearchError")


def test_format_for_llm():
    """format_for_llm 应正确格式化结果。"""
    out = format_for_llm([{"title": "T", "url": "https://x", "snippet": "s"}])
    assert "https://x" in out and "[1]" in out


@_requires_ddg
def test_search_with_timeout():
    """超时参数应生效。"""
    r = search("test", timeout=5)
    assert isinstance(r, list)


if __name__ == "__main__":
    test_search_returns_results()
    test_empty_query_raises()
    test_format_for_llm()
    test_search_with_timeout()
    print("web_search 单测: 全部通过 ✅")
