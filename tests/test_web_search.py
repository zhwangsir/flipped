"""web_search 轻量单测（无需 pytest，python 直接跑）。前置：SearXNG 在跑。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tools.web_search import SearchError, format_for_llm, search  # noqa: E402


def test_returns_results():
    # SearXNG 上游引擎(经 Clash)偶发抖动 -> 多 query 任一返回即通过(仍要求真实结果, 不放水)
    r: list = []
    for q in ("LangGraph", "Python programming language", "Wikipedia"):
        r = search(q, max_results=3)
        if r:
            break
    assert isinstance(r, list) and len(r) >= 1, "3 个 query 均无结果(SearXNG 引擎全抖?)"
    assert all(x.get("url", "").startswith("http") for x in r), "每条结果须含 http URL"
    assert all(x.get("title") for x in r), "每条结果须有标题"


def test_empty_query_raises():
    try:
        search("")
    except SearchError:
        return
    raise AssertionError("空 query 应抛 SearchError")


def test_format_for_llm():
    out = format_for_llm([{"title": "T", "url": "https://x", "snippet": "s"}])
    assert "https://x" in out and "[1]" in out


if __name__ == "__main__":
    test_returns_results()
    test_empty_query_raises()
    test_format_for_llm()
    print("web_search 单测: 全部通过 ✅")
