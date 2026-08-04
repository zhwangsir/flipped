"""M172 A 队 · chat/plan 自动 RAG 上下文注入（检索 + 格式化，fail-open）TDD 测试。

契约（全部走 fake store 注入，不起真 Chroma）：
- project 非空 → 第一次 query 带 filter={"project": project}；空结果 → 无 filter 兜底重查
- project 查询有结果 → 不重查；project 为空 → 直接无 filter 查一次
- 格式化：首行 RAG_CONTEXT_HEADER；每条 "[i] source\n文本"（i 从 1，source 缺省 "unknown"）
- max_chars：逐 chunk 累计，加入即超则整体放弃后续；第一条即超 → 截断装入（count==1）
- fail-open：任何异常 / 无结果 → ("", 0)，绝不抛；chunk_count = 实际装入条数
"""
from __future__ import annotations

import pytest

from api.rag_context import RAG_CONTEXT_HEADER, build_rag_context


class FakeStore:
    """记录 query 调用参数；scripted 为逐次调用的返回列表，否则固定返回 results。"""

    def __init__(self, results=None, scripted=None):
        self.calls: list[dict] = []
        self._results = list(results or [])
        self._scripted = scripted

    def query(self, text, n_results=5, filter=None):
        self.calls.append({"text": text, "n_results": n_results, "filter": filter})
        if self._scripted is not None:
            return self._scripted[len(self.calls) - 1]
        return list(self._results)


def _item(text, source=None, **meta):
    m = dict(meta)
    if source is not None:
        m["source"] = source
    return {"id": "x", "text": text, "metadata": m, "distance": 0.1}


# ---------- project 过滤 / 兜底重查 ----------

def test_project_filter_passed_on_first_query():
    store = FakeStore(results=[_item("hit", "/abs/path/a.py")])
    ctx, count = build_rag_context("q", project="flipped", store=store)
    assert store.calls[0]["filter"] == {"project": "flipped"}
    assert store.calls[0]["n_results"] == 4  # 默认 n_results 透传
    assert len(store.calls) == 1
    assert count == 1
    assert ctx


def test_project_empty_result_falls_back_to_unfiltered():
    store = FakeStore(scripted=[[], [_item("global hit", "/abs/path/b.py")]])
    ctx, count = build_rag_context("q", project="flipped", store=store)
    assert len(store.calls) == 2
    assert store.calls[0]["filter"] == {"project": "flipped"}
    assert store.calls[1]["filter"] is None  # 第二次无 filter 兜底
    assert count == 1
    assert "global hit" in ctx


def test_project_hits_no_fallback():
    store = FakeStore(results=[_item("p hit", "/abs/path/a.py")])
    build_rag_context("q", project="flipped", store=store)
    assert len(store.calls) == 1  # 有结果不重查


@pytest.mark.parametrize("project", [None, ""])
def test_no_project_single_unfiltered_query(project):
    store = FakeStore(results=[_item("hit")])
    build_rag_context("q", project=project, store=store)
    assert len(store.calls) == 1
    assert store.calls[0]["filter"] is None


def test_n_results_passthrough():
    store = FakeStore(results=[_item("hit")])
    build_rag_context("q", n_results=7, store=store)
    assert store.calls[0]["n_results"] == 7


# ---------- 格式化形状 ----------

def test_format_shape_and_count():
    store = FakeStore(results=[
        _item("first chunk text", "/abs/path/a.py"),
        _item("second chunk text", "/abs/path/b.py"),
    ])
    ctx, count = build_rag_context("q", store=store)
    assert ctx.startswith(RAG_CONTEXT_HEADER)
    assert "[1] /abs/path/a.py" in ctx
    assert "[2] /abs/path/b.py" in ctx
    assert "first chunk text" in ctx
    assert "second chunk text" in ctx
    assert count == 2


def test_missing_source_defaults_unknown():
    store = FakeStore(results=[_item("no source text")])
    ctx, count = build_rag_context("q", store=store)
    assert "[1] unknown" in ctx
    assert count == 1


# ---------- max_chars 截断 ----------

def test_max_chars_drops_later_chunks_wholesale():
    # 第一条装得下；第二条装上会超 → 整体放弃，不半截装入
    t1 = "x" * 60
    t2 = "y" * 60
    store = FakeStore(results=[_item(t1, "/a.py"), _item(t2, "/b.py")])
    # 第一条装完余 10 字符，不够第二条（需 71）
    max_chars = len(RAG_CONTEXT_HEADER) + 1 + len("[1] /a.py\n") + 60 + 10
    ctx, count = build_rag_context("q", max_chars=max_chars, store=store)
    assert len(ctx) <= max_chars
    assert count == 1
    assert t1 in ctx
    assert t2 not in ctx


def test_first_chunk_oversized_is_truncated_to_fit():
    big = "z" * 5000
    store = FakeStore(results=[_item(big, "/big.py"), _item("second", "/b.py")])
    ctx, count = build_rag_context("q", max_chars=200, store=store)
    assert count == 1
    assert len(ctx) <= 200
    assert ctx.startswith(RAG_CONTEXT_HEADER)
    assert "[1] /big.py" in ctx
    assert "z" * 50 in ctx  # 截断后的正文仍在
    assert big not in ctx  # 未完整装入
    assert "second" not in ctx


# ---------- fail-open ----------

def test_query_exception_returns_empty():
    class BoomStore:
        def query(self, *a, **k):
            raise RuntimeError("boom")

    ctx, count = build_rag_context("q", project="flipped", store=BoomStore())
    assert (ctx, count) == ("", 0)


def test_empty_results_returns_empty():
    store = FakeStore(results=[])
    ctx, count = build_rag_context("q", store=store)
    assert ctx == ""
    assert count == 0


def test_project_and_fallback_both_empty_returns_empty():
    store = FakeStore(scripted=[[], []])
    ctx, count = build_rag_context("q", project="flipped", store=store)
    assert (ctx, count) == ("", 0)
    assert len(store.calls) == 2  # 确认走了兜底重查
