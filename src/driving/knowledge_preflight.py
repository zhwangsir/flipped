"""P5 · 知识预检模块。

每次任务执行前，先联网查询获取最新知识和上下文，再进行操作。

核心能力：
1. 根据任务类型和描述自动生成搜索查询
2. 联网搜索获取最新信息
3. 本地缓存层（TTL 机制），避免重复查询相同主题
4. 知识摘要提取，注入到任务执行上下文
5. fail-open 设计：网络不可用时不阻塞主流程

集成点：
    UnmannedLoop.run_one() 执行前 → knowledge_preflight(task) → 注入到执行上下文
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from driving.structured_logger import StructuredLogger, LogLevel


@dataclass
class SearchResult:
    """单条搜索结果。"""
    title: str
    url: str
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


@dataclass
class KnowledgeContext:
    """任务的知识上下文。"""
    task_id: str
    queries: list[str] = field(default_factory=list)
    results: list[SearchResult] = field(default_factory=list)
    summary: str = ""
    cached: bool = False
    search_time_ms: float = 0.0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "queries": self.queries,
            "results": [r.to_dict() for r in self.results],
            "summary": self.summary,
            "cached": self.cached,
            "search_time_ms": self.search_time_ms,
            "timestamp": self.timestamp,
        }

    def to_prompt_text(self) -> str:
        """转换为可注入到 LLM prompt 的文本。"""
        if not self.results:
            return ""

        lines = [f"【联网知识预检】基于 {len(self.queries)} 个查询获取到 {len(self.results)} 条最新信息："]
        for i, r in enumerate(self.results[:10], 1):
            lines.append(f"  {i}. [{r.title}]")
            lines.append(f"     URL: {r.url}")
            snippet = r.snippet[:200] if r.snippet else ""
            if snippet:
                lines.append(f"     摘要: {snippet}")
        if self.cached:
            lines.append("  (来源: 本地缓存)")
        return "\n".join(lines)


@dataclass
class CacheEntry:
    """缓存条目。"""
    key: str
    results: list[SearchResult]
    timestamp: float
    ttl: float


class KnowledgeCache:
    """知识缓存层，TTL 机制避免重复查询。"""

    def __init__(self, ttl_seconds: float = 3600, max_entries: int = 500) -> None:
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._cache: dict[str, CacheEntry] = {}

    def _make_key(self, query: str) -> str:
        return hashlib.md5(query.encode()).hexdigest()

    def get(self, query: str) -> list[SearchResult] | None:
        key = self._make_key(query)
        entry = self._cache.get(key)
        if entry is None:
            return None
        if time.time() - entry.timestamp > entry.ttl:
            del self._cache[key]
            return None
        return entry.results

    def put(self, query: str, results: list[SearchResult], ttl: float | None = None) -> None:
        if len(self._cache) >= self.max_entries:
            # 淘汰最旧的条目
            oldest = min(self._cache.values(), key=lambda e: e.timestamp)
            del self._cache[oldest.key]
        key = self._make_key(query)
        self._cache[key] = CacheEntry(
            key=key,
            results=results,
            timestamp=time.time(),
            ttl=ttl or self.ttl,
        )

    def invalidate(self, query: str) -> None:
        key = self._make_key(query)
        self._cache.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()

    def stats(self) -> dict[str, Any]:
        valid = sum(
            1 for e in self._cache.values()
            if time.time() - e.timestamp <= e.ttl
        )
        return {
            "total_entries": len(self._cache),
            "valid_entries": valid,
            "expired_entries": len(self._cache) - valid,
            "max_entries": self.max_entries,
            "ttl_seconds": self.ttl,
        }


# 任务类型 → 搜索关键词模板
_TASK_TYPE_KEYWORDS: dict[str, list[str]] = {
    "code_generation": ["best practices", "latest API", "code example"],
    "ui_design": ["design trends", "UI patterns", "accessibility guidelines"],
    "algorithm": ["algorithm optimization", "time complexity", "latest research"],
    "debugging": ["common errors", "debugging techniques", "stack overflow"],
    "documentation": ["official documentation", "API reference", "getting started"],
    "testing": ["testing best practices", "test patterns", "coverage strategies"],
    "refactoring": ["refactoring patterns", "code smell", "clean code"],
    "architecture": ["architecture patterns", "system design", "scalability"],
    "security": ["security vulnerabilities", "OWASP", "security best practices"],
    "performance": ["performance optimization", "benchmarking", "profiling"],
}


def generate_search_queries(task: Any, *, max_queries: int = 3) -> list[str]:
    """根据任务自动生成搜索查询。

    Args:
        task: ChallengeTask 或类似对象，需有 title/description/category 属性。
    """
    title = getattr(task, "title", "") or ""
    description = getattr(task, "description", "") or ""
    category = getattr(task, "category", None)
    category_str = category.value if hasattr(category, "value") else str(category)

    queries: list[str] = []

    # 主查询：标题 + 描述
    main_query = title or description
    if main_query:
        queries.append(main_query[:200])

    # 分类关键词查询
    keywords = _TASK_TYPE_KEYWORDS.get(category_str, [])
    if keywords and main_query:
        queries.append(f"{main_query[:100]} {keywords[0]}")

    # 技术栈查询
    if description and len(description) > 20:
        queries.append(f"{description[:150]} latest guide")

    return queries[:max_queries]


class KnowledgePreflight:
    """知识预检引擎。

    search_fn: 可注入的搜索函数，签名 (query: str, max_results: int) -> list[dict]。
               默认使用 tools.web_search.search（fail-open）。
    """

    def __init__(
        self,
        *,
        cache: KnowledgeCache | None = None,
        search_fn: Callable[[str, int], list[dict]] | None = None,
        logger: StructuredLogger | None = None,
        max_results_per_query: int = 3,
        max_total_results: int = 10,
    ) -> None:
        self.cache = cache or KnowledgeCache()
        self.logger = logger or StructuredLogger(
            module_name="knowledge_preflight",
            min_level=LogLevel.info,
        )
        self.max_results_per_query = max_results_per_query
        self.max_total_results = max_total_results
        self._search_fn = search_fn

    def _default_search(self, query: str, max_results: int) -> list[dict]:
        """默认搜索函数：调用 tools.web_search.search。"""
        try:
            from tools.web_search import search as web_search
            return web_search(query, max_results=max_results)
        except Exception:
            return []

    def _search(self, query: str) -> tuple[list[SearchResult], bool]:
        """执行搜索（带缓存）。

        Returns:
            (results, is_cache_hit)
        """
        # 查缓存
        cached = self.cache.get(query)
        if cached is not None:
            self.logger.debug("cache_hit", {"query": query[:50]})
            return cached, True

        # 执行搜索（fail-open）
        search_fn = self._search_fn or self._default_search
        try:
            raw_results = search_fn(query, self.max_results_per_query)
        except Exception as exc:
            self.logger.warn("search_failed", {
                "query": query[:50],
                "error": str(exc),
            })
            return [], False

        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("snippet", ""),
            )
            for r in raw_results
            if r.get("url", "").startswith("http")
        ]

        # 写缓存
        self.cache.put(query, results)
        return results, False

    def preflight(self, task: Any) -> KnowledgeContext:
        """任务执行前的知识预检。

        流程：
        1. 根据任务生成搜索查询
        2. 逐个查询（带缓存）
        3. 去重 + 截断
        4. 生成摘要
        """
        task_id = getattr(task, "id", "") or getattr(task, "title", "")
        start = time.time()

        queries = generate_search_queries(task)
        self.logger.info("preflight_start", {
            "task_id": task_id,
            "queries": queries,
        })

        all_results: list[SearchResult] = []
        seen_urls: set[str] = set()
        any_cached = False

        for q in queries:
            results, is_cached = self._search(q)
            if is_cached:
                any_cached = True
            for r in results:
                if r.url not in seen_urls:
                    seen_urls.add(r.url)
                    all_results.append(r)
            if len(all_results) >= self.max_total_results:
                break

        all_results = all_results[:self.max_total_results]

        # 生成摘要
        summary = self._generate_summary(task, all_results)

        elapsed = (time.time() - start) * 1000

        context = KnowledgeContext(
            task_id=task_id,
            queries=queries,
            results=all_results,
            summary=summary,
            cached=any_cached,
            search_time_ms=round(elapsed, 2),
        )

        self.logger.info("preflight_complete", {
            "task_id": task_id,
            "results_count": len(all_results),
            "cached": any_cached,
            "time_ms": round(elapsed, 2),
        })

        return context

    def _generate_summary(self, task: Any, results: list[SearchResult]) -> str:
        """从搜索结果生成知识摘要。"""
        if not results:
            return "（联网搜索未返回结果，将使用内置知识执行任务）"

        title = getattr(task, "title", "")
        lines = [f"基于联网搜索获取了 {len(results)} 条与「{title}」相关的最新信息。"]
        lines.append("关键发现：")
        for i, r in enumerate(results[:5], 1):
            snippet = r.snippet[:150] if r.snippet else "无摘要"
            lines.append(f"  {i}. {r.title}: {snippet}")
        return "\n".join(lines)

    def get_stats(self) -> dict[str, Any]:
        """获取预检统计。"""
        return {
            "cache": self.cache.stats(),
        }


def make_preflight(
    *,
    search_fn: Callable[[str, int], list[dict]] | None = None,
    cache_ttl: float = 3600,
) -> KnowledgePreflight:
    """便捷工厂函数。"""
    return KnowledgePreflight(
        cache=KnowledgeCache(ttl_seconds=cache_ttl),
        search_fn=search_fn,
    )
