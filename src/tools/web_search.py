"""web_search 工具核心 — 查询自托管 SearXNG，返回带来源的结构化结果。

纯函数（可单测），不依赖 agent 框架。loop.py 再把它包成 LangChain tool。
访问 localhost SearXNG，无需 NO_PROXY（localhost 默认不走代理）。
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8080")
DEFAULT_TIMEOUT = float(os.environ.get("SEARXNG_TIMEOUT", "30"))
# SearXNG 上游引擎(经 Clash)偶发瞬时空结果/超时 -> 对空结果与网络错重试
DEFAULT_RETRIES = int(os.environ.get("SEARXNG_RETRIES", "3"))


class SearchError(RuntimeError):
    """搜索失败时抛出，便于上层(agent/工具)显式处理。"""


def _fetch(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _parse(data: dict, max_results: int) -> list[dict]:
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


def search(
    query: str,
    max_results: int = 5,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> list[dict]:
    """联网搜索 query，返回 [{title, url, snippet}]（最多 max_results 条）。

    上游引擎瞬时抖动(空结果/网络错)会自动重试 retries 次(短退避)。
    持续网络失败抛 SearchError（不静默吞错）；多次仍真空则返回 []。
    """
    if not query or not query.strip():
        raise SearchError("query 不能为空")

    params = urllib.parse.urlencode({"q": query.strip(), "format": "json"})
    url = f"{SEARXNG_URL}/search?{params}"

    last_err: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            results = _parse(_fetch(url, timeout), max_results)
        except Exception as e:  # noqa: BLE001 — 边界统一处理，重试或转 SearchError
            last_err = e
        else:
            if results:
                return results
        if attempt < retries - 1:
            time.sleep(0.6 * (attempt + 1))  # 短退避，给上游引擎喘息

    if last_err is not None:
        raise SearchError(f"SearXNG 请求失败: {type(last_err).__name__}: {last_err}") from last_err
    return []  # 多次重试仍空 -> 视为真无结果


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
