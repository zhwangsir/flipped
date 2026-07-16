"""web_search 工具核心 — 内置搜索，开箱即用。

纯函数（可单测），不依赖 agent 框架。loop.py 再把它包成 LangChain tool。

两种搜索模式：
1. API 模式（默认）：DuckDuckGo Instant Answer API（免费、无需 API key、快速）
2. 浏览器模式：通过内置 Playwright 浏览器访问搜索引擎（更真实、支持更多引擎）

用户若配置了 SEARXNG_URL 环境变量则优先使用自托管 SearXNG。
配置 SEARCH_MODE=browser 可启用浏览器模式。

开箱即用：无需 Docker、无需代理、无需配置，安装依赖后直接可用。
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

DEFAULT_TIMEOUT = float(os.environ.get("SEARCH_TIMEOUT", "30"))
DEFAULT_RETRIES = int(os.environ.get("SEARCH_RETRIES", "3"))

SEARXNG_URL = os.environ.get("SEARXNG_URL")
SEARCH_MODE = os.environ.get("SEARCH_MODE", "api")


class SearchError(RuntimeError):
    """搜索失败时抛出，便于上层(agent/工具)显式处理。"""


def _fetch(url: str, timeout: float, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _parse_ddg(data: dict, max_results: int) -> list[dict]:
    """解析 DuckDuckGo Instant Answer API 返回。"""
    results: list[dict] = []

    if "Answer" in data and data["Answer"]:
        results.append({
            "title": data.get("Heading", "") or "Instant Answer",
            "url": data.get("AbstractURL", ""),
            "snippet": data["Answer"],
        })

    for item in data.get("RelatedTopics", [])[:max_results]:
        if isinstance(item, dict):
            url_ = item.get("FirstURL", "")
            if not url_:
                continue
            results.append({
                "title": item.get("Text", "").strip(),
                "url": url_,
                "snippet": "",
            })

    for item in data.get("Results", [])[:max_results]:
        url_ = item.get("FirstURL", "")
        if not url_:
            continue
        results.append({
            "title": item.get("Text", "").strip(),
            "url": url_,
            "snippet": "",
        })

    return results[:max_results]


def _parse_searxng(data: dict, max_results: int) -> list[dict]:
    """解析 SearXNG API 返回。"""
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
    if not results:
        for item in data.get("infoboxes", [])[:max_results]:
            url_ = item.get("id") or item.get("url")
            if not url_ and item.get("urls"):
                url_ = item["urls"][0].get("url")
            if not url_:
                continue
            results.append({
                "title": item.get("infobox", "").strip() or item.get("title", "").strip(),
                "url": url_,
                "snippet": (item.get("content") or "").strip(),
            })
    return results


def search(
    query: str,
    max_results: int = 5,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    mode: str | None = None,
) -> list[dict]:
    """联网搜索 query，返回 [{title, url, snippet}]（最多 max_results 条）。

    两种搜索模式：
    1. API 模式（默认）：DuckDuckGo Instant Answer API（免费、无需 API key、快速）
    2. 浏览器模式：通过内置 Playwright 浏览器访问搜索引擎

    若配置了 SEARXNG_URL 环境变量则优先使用自托管 SearXNG。
    配置 SEARCH_MODE=browser 可全局启用浏览器模式。

    上游引擎瞬时抖动(空结果/网络错)会自动重试 retries 次(短退避)。
    持续网络失败抛 SearchError（不静默吞错）；多次仍真空则返回 []。
    """
    if not query or not query.strip():
        raise SearchError("query 不能为空")

    query_clean = query.strip()
    effective_mode = mode or SEARCH_MODE

    if SEARXNG_URL:
        return _search_searxng(query_clean, max_results, timeout, retries)
    elif effective_mode == "browser":
        return _search_browser(query_clean, max_results, timeout)
    else:
        return _search_ddg(query_clean, max_results, timeout, retries)


def _search_searxng(query: str, max_results: int, timeout: float, retries: int) -> list[dict]:
    """使用自托管 SearXNG 搜索。"""
    params = urllib.parse.urlencode({"q": query, "format": "json"})
    url = f"{SEARXNG_URL}/search?{params}"

    last_err: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            results = _parse_searxng(_fetch(url, timeout), max_results)
        except Exception as e:  # noqa: BLE001
            last_err = e
        else:
            if results:
                return results
        if attempt < retries - 1:
            time.sleep(0.6 * (attempt + 1))

    if last_err is not None:
        raise SearchError(f"SearXNG 请求失败: {type(last_err).__name__}: {last_err}") from last_err
    return []


def _search_ddg(query: str, max_results: int, timeout: float, retries: int) -> list[dict]:
    """使用 DuckDuckGo 免费 API 搜索（开箱即用）。"""
    params = urllib.parse.urlencode({"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"})
    url = f"https://api.duckduckgo.com/?{params}"

    last_err: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            results = _parse_ddg(_fetch(url, timeout), max_results)
        except Exception as e:  # noqa: BLE001
            last_err = e
        else:
            if results:
                return results
        if attempt < retries - 1:
            time.sleep(0.6 * (attempt + 1))

    if last_err is not None:
        raise SearchError(f"DuckDuckGo 请求失败: {type(last_err).__name__}: {last_err}") from last_err
    return []


def _search_browser(query: str, max_results: int, timeout: float) -> list[dict]:
    """使用内置浏览器搜索（通过 unified_browser 模块）。

    更真实的搜索体验，支持更多搜索引擎和动态页面。
    启动较慢（需启动 Chromium），但结果更全面。
    """
    try:
        from tools.unified_browser import browser_search as browser_search_impl
        return browser_search_impl(query, max_results=max_results, timeout=timeout)
    except ImportError as e:
        raise SearchError(f"浏览器搜索不可用: {e}") from e
    except Exception as e:
        raise SearchError(f"浏览器搜索失败: {type(e).__name__}: {e}") from e


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
