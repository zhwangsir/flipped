"""M111 · 上下文记忆分层测试。

三级记忆：工作记忆(当前对话) / 近期记忆(最近 N 个任务) / 长期记忆(Skill + Failure KB)。
自动摘要 + 关联检索。
"""
from __future__ import annotations

import tempfile
import os

import pytest

from driving.memory_hierarchy import (
    HierarchicalMemory,
    MemoryItem,
    MemoryLevel,
)


class TestMemoryItem:
    def test_item_has_expected_fields(self):
        item = MemoryItem(
            id="m1",
            content="test content",
            level=MemoryLevel.working,
            metadata={"task": "test"},
        )
        assert item.id == "m1"
        assert item.content == "test content"
        assert item.level == MemoryLevel.working


class TestHierarchicalMemory:
    def test_add_and_retrieve_working(self):
        mem = HierarchicalMemory()
        mem.add("hello world", level=MemoryLevel.working, metadata={"type": "msg"})
        items = mem.get_level(MemoryLevel.working)
        assert len(items) == 1
        assert items[0].content == "hello world"

    def test_add_recent(self):
        mem = HierarchicalMemory()
        mem.add("task 1 result", level=MemoryLevel.recent, metadata={"task_id": "t1"})
        items = mem.get_level(MemoryLevel.recent)
        assert len(items) == 1

    def test_search_by_keyword(self):
        mem = HierarchicalMemory()
        mem.add("build landing page with hero section", level=MemoryLevel.recent)
        mem.add("fix login form validation", level=MemoryLevel.recent)
        results = mem.search("landing page", top_k=5)
        assert len(results) >= 1
        assert "landing" in results[0].content.lower()

    def test_working_memory_has_limit(self):
        mem = HierarchicalMemory(max_working=5)
        for i in range(10):
            mem.add(f"message {i}", level=MemoryLevel.working)
        items = mem.get_level(MemoryLevel.working)
        assert len(items) <= 5

    def test_compress_working_to_recent(self):
        mem = HierarchicalMemory(max_working=3)
        for i in range(10):
            mem.add(f"message {i}", level=MemoryLevel.working)
        recent = mem.get_level(MemoryLevel.recent)
        assert len(recent) > 0

    def test_empty_search_returns_empty(self):
        mem = HierarchicalMemory()
        results = mem.search("nonexistent")
        assert results == []

    def test_get_summary(self):
        mem = HierarchicalMemory()
        mem.add("task 1: build header", level=MemoryLevel.recent)
        mem.add("task 2: build footer", level=MemoryLevel.recent)
        summary = mem.get_summary()
        assert "working" in summary
        assert "recent" in summary
        assert "long_term" in summary
