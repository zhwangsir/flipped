"""调研上下文聚合单元测试。"""
from __future__ import annotations

from unittest.mock import MagicMock

from driving.researcher import format_context, gather


def test_format_context() -> None:
    ctx = format_context("query", "web results", "rag results")
    assert "调研问题: query" in ctx
    assert "web results" in ctx
    assert "rag results" in ctx


def test_gather_combines_web_and_rag(monkeypatch) -> None:
    mock_web = MagicMock(return_value=[{"title": "t", "url": "http://x", "snippet": "s"}])
    monkeypatch.setattr("driving.researcher.web_search", mock_web)

    mock_store = MagicMock()
    mock_store.query.return_value = [{"text": "private doc", "metadata": {"source": "x"}, "distance": 0.5}]
    monkeypatch.setattr("driving.researcher.ChromaVectorStore", lambda: mock_store)

    ctx = gather("python testing", use_web=True, use_rag=True, n_results=2)

    assert "private doc" in ctx
    assert "http://x" in ctx
    mock_web.assert_called_once_with("python testing", max_results=2)
    mock_store.query.assert_called_once_with("python testing", n_results=2)


def test_gather_web_only(monkeypatch) -> None:
    mock_web = MagicMock(return_value=[])
    monkeypatch.setattr("driving.researcher.web_search", mock_web)

    mock_store = MagicMock()
    monkeypatch.setattr("driving.researcher.ChromaVectorStore", lambda: mock_store)

    ctx = gather("python testing", use_web=True, use_rag=False, n_results=2)
    assert "调研问题: python testing" in ctx
    assert "Web 搜索结果" in ctx
    assert "私有知识库 (RAG)" not in ctx
    mock_web.assert_called_once()
    mock_store.query.assert_not_called()
