"""web_search 工具核心 — 查询自托管 SearXNG，返回带来源的结构化结果。

纯函数（可单测），不依赖 agent 框架。loop.py 再把它包成 LangChain tool。
访问 localhost SearXNG，无需 NO_PROXY（localhost 默认不走代理）。
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8080")
DEFAULT_TIMEOUT = float(os.environ.get("SEARXNG_TIMEOUT", "30"))


class SearchError(RuntimeError):
    """搜索失败时抛出，便于上层(agent/工具)显式处理。"""


def search(query: str, max_results: int = 5, timeout: float = DEFAULT_TIMEOUT) -> list[dict]:
    """联网搜索 query，返回 [{title, url, snippet}]（最多 max_results 条）。

    失败时抛 SearchError（不静默吞错）。
    """
    if not query or not query.strip():
        raise SearchError("query 不能为空")

    params = urllib.parse.urlencode({"q": query.strip(), "format": "json"})
    url = f"{SEARXNG_URL}/search?{params}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception as e:  # noqa: BLE001 — 边界统一转为 SearchError
        raise SearchError(f"SearXNG 请求失败: {type(e).__name__}: {e}") from e

    results: list[dict] = []
    for item in data.get("results", [])[:max_results]:
        url_ = item.get("url", "")
        if not url_:
            continue
        results.append({
            "title": item.get("title", "").strip(),
            "url": url_,
            "snippet": (item.get("content") or "").strip(),
        })
    return results


def format_for_llm(results: list[dict]) -> str:
    """把结果格式化成便于 LLM 引用来源的文本。"""
    if not results:
        return "（无搜索结果）"
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r['title']}\n    URL: {r['url']}\n    {r['snippet'][:300]}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "LangGraph latest version"
    hits = search(q)
    print(f"query={q!r} -> {len(hits)} 条")
    print(format_for_llm(hits))
