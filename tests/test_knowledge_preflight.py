"""P5 · 知识预检模块测试。"""
from __future__ import annotations

import time

from driving.knowledge_preflight import (
    KnowledgePreflight,
    KnowledgeCache,
    KnowledgeContext,
    SearchResult,
    generate_search_queries,
    make_preflight,
)


class TestSearchResult:
    def test_to_dict(self):
        r = SearchResult(title="T", url="http://x", snippet="S")
        d = r.to_dict()
        assert d["title"] == "T"
        assert d["url"] == "http://x"


class TestKnowledgeContext:
    def test_to_dict(self):
        ctx = KnowledgeContext(task_id="t1", queries=["q1"])
        d = ctx.to_dict()
        assert d["task_id"] == "t1"
        assert d["queries"] == ["q1"]

    def test_to_prompt_text_empty(self):
        ctx = KnowledgeContext(task_id="t1")
        assert ctx.to_prompt_text() == ""

    def test_to_prompt_text_with_results(self):
        ctx = KnowledgeContext(
            task_id="t1",
            queries=["test query"],
            results=[SearchResult(title="Result", url="http://x", snippet="Snippet")],
        )
        text = ctx.to_prompt_text()
        assert "联网知识预检" in text
        assert "Result" in text
        assert "http://x" in text


class TestKnowledgeCache:
    def test_put_and_get(self):
        cache = KnowledgeCache(ttl_seconds=60)
        results = [SearchResult(title="T", url="http://x", snippet="S")]
        cache.put("query1", results)
        got = cache.get("query1")
        assert got is not None
        assert len(got) == 1
        assert got[0].title == "T"

    def test_miss(self):
        cache = KnowledgeCache()
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        cache = KnowledgeCache(ttl_seconds=0.1)
        results = [SearchResult(title="T", url="http://x", snippet="S")]
        cache.put("query", results)
        time.sleep(0.2)
        assert cache.get("query") is None

    def test_invalidate(self):
        cache = KnowledgeCache(ttl_seconds=60)
        results = [SearchResult(title="T", url="http://x", snippet="S")]
        cache.put("query", results)
        cache.invalidate("query")
        assert cache.get("query") is None

    def test_clear(self):
        cache = KnowledgeCache(ttl_seconds=60)
        cache.put("q1", [SearchResult("t", "http://x", "s")])
        cache.put("q2", [SearchResult("t", "http://y", "s")])
        cache.clear()
        assert cache.get("q1") is None
        assert cache.get("q2") is None

    def test_stats(self):
        cache = KnowledgeCache(ttl_seconds=60, max_entries=10)
        cache.put("q1", [SearchResult("t", "http://x", "s")])
        stats = cache.stats()
        assert stats["total_entries"] == 1
        assert stats["valid_entries"] == 1

    def test_max_entries_eviction(self):
        cache = KnowledgeCache(ttl_seconds=60, max_entries=2)
        cache.put("q1", [SearchResult("t", "http://x", "s")])
        cache.put("q2", [SearchResult("t", "http://y", "s")])
        cache.put("q3", [SearchResult("t", "http://z", "s")])
        stats = cache.stats()
        assert stats["total_entries"] <= 2


class TestGenerateSearchQueries:
    def test_generates_queries(self):
        class MockTask:
            id = "t1"
            title = "Build a React component"
            description = "Create a reusable React component with TypeScript"
            category = type("Cat", (), {"value": "code_generation"})()

        queries = generate_search_queries(MockTask())
        assert len(queries) >= 1
        assert "Build a React component" in queries[0]

    def test_empty_task(self):
        class MockTask:
            id = ""
            title = ""
            description = ""
            category = type("Cat", (), {"value": "unknown"})()

        queries = generate_search_queries(MockTask())
        assert len(queries) == 0

    def test_max_queries(self):
        class MockTask:
            id = "t1"
            title = "T"
            description = "D" * 100
            category = type("Cat", (), {"value": "code_generation"})()

        queries = generate_search_queries(MockTask(), max_queries=1)
        assert len(queries) <= 1


class TestKnowledgePreflight:
    def test_preflight_with_mock_search(self):
        def mock_search(query, max_results):
            return [
                {"title": f"Result for {query}", "url": "http://example.com", "snippet": "Snippet"},
                {"title": "Another", "url": "http://other.com", "snippet": "Other snippet"},
            ]

        preflight = KnowledgePreflight(search_fn=mock_search)
        context = preflight.preflight(
            type("Task", (), {
                "id": "t1",
                "title": "Test Task",
                "description": "Test description",
                "category": type("Cat", (), {"value": "code_generation"})(),
            })()
        )
        assert context.task_id == "t1"
        assert len(context.results) > 0
        assert context.search_time_ms > 0
        assert "联网搜索" in context.summary or "未返回" in context.summary

    def test_preflight_with_cache_hit(self):
        call_count = [0]

        def mock_search(query, max_results):
            call_count[0] += 1
            return [{"title": "Cached Result", "url": "http://cached.com", "snippet": "S"}]

        preflight = KnowledgePreflight(search_fn=mock_search)
        task = type("Task", (), {
            "id": "t1",
            "title": "Test",
            "description": "desc",
            "category": type("Cat", (), {"value": "code_generation"})(),
        })()

        # First call - actual search
        ctx1 = preflight.preflight(task)
        assert ctx1.cached is False
        first_call_count = call_count[0]

        # Second call - should use cache for same queries
        ctx2 = preflight.preflight(task)
        assert ctx2.cached is True
        assert call_count[0] == first_call_count  # No new search calls

    def test_preflight_fail_open(self):
        """网络不可用时不阻塞，返回空结果。"""
        def failing_search(query, max_results):
            raise ConnectionError("network unavailable")

        preflight = KnowledgePreflight(search_fn=failing_search)
        context = preflight.preflight(
            type("Task", (), {
                "id": "t1",
                "title": "Test",
                "description": "desc",
                "category": type("Cat", (), {"value": "code_generation"})(),
            })()
        )
        assert context.task_id == "t1"
        assert len(context.results) == 0
        assert "未返回" in context.summary or "内置知识" in context.summary

    def test_preflight_deduplicates_urls(self):
        def mock_search(query, max_results):
            return [
                {"title": "Same URL", "url": "http://same.com", "snippet": "S1"},
                {"title": "Same URL Again", "url": "http://same.com", "snippet": "S2"},
            ]

        preflight = KnowledgePreflight(search_fn=mock_search)
        context = preflight.preflight(
            type("Task", (), {
                "id": "t1",
                "title": "Test",
                "description": "desc",
                "category": type("Cat", (), {"value": "code_generation"})(),
            })()
        )
        urls = [r.url for r in context.results]
        assert len(urls) == len(set(urls))  # No duplicates

    def test_preflight_respects_max_total(self):
        def mock_search(query, max_results):
            return [
                {"title": f"R{i}", "url": f"http://r{i}.com", "snippet": f"S{i}"}
                for i in range(10)
            ]

        preflight = KnowledgePreflight(
            search_fn=mock_search,
            max_results_per_query=10,
            max_total_results=3,
        )
        context = preflight.preflight(
            type("Task", (), {
                "id": "t1",
                "title": "Test",
                "description": "desc",
                "category": type("Cat", (), {"value": "code_generation"})(),
            })()
        )
        assert len(context.results) <= 3

    def test_get_stats(self):
        preflight = KnowledgePreflight(search_fn=lambda q, m: [])
        stats = preflight.get_stats()
        assert "cache" in stats

    def test_make_preflight_factory(self):
        p = make_preflight(search_fn=lambda q, m: [], cache_ttl=60)
        assert p.cache.ttl == 60
