"""RAG 模块单元测试：嵌入 + 向量库 + ingest。"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from rag.embeddings import MockEmbedding
from rag.ingest import ingest_directory, ingest_file, ingest_text
from rag.vector_store import ChromaVectorStore


def test_mock_embedding_deterministic() -> None:
    emb = MockEmbedding(dim=8)
    v1 = emb.embed(["hello world"])[0]
    v2 = emb.embed(["hello world"])[0]
    assert v1 == v2
    assert len(v1) == 8
    assert abs(sum(x * x for x in v1) - 1.0) < 1e-6


def test_chroma_crud() -> None:
    emb = MockEmbedding(dim=16)
    store = ChromaVectorStore(db_dir=None, collection="test_crud", embedding=emb)
    store.delete_collection()
    store = ChromaVectorStore(db_dir=None, collection="test_crud", embedding=emb)

    ids = store.add_documents([
        {"text": "Python is a programming language", "metadata": {"source": "test"}},
        {"text": "JavaScript runs in browsers", "metadata": {"source": "test"}},
    ])
    assert len(ids) == 2

    results = store.query("programming language", n_results=2)
    assert len(results) == 2
    texts = [r["text"] for r in results]
    assert "Python is a programming language" in texts


def test_ingest_text() -> None:
    emb = MockEmbedding(dim=8)
    store = ChromaVectorStore(db_dir=None, collection="test_text", embedding=emb)
    store.delete_collection()
    store = ChromaVectorStore(db_dir=None, collection="test_text", embedding=emb)

    ids = ingest_text("hello world", metadata={"key": "value"}, store=store)
    assert len(ids) == 1

    results = store.query("hello", n_results=1)
    assert results[0]["text"] == "hello world"
    assert results[0]["metadata"]["key"] == "value"


def test_ingest_file_and_directory() -> None:
    emb = MockEmbedding(dim=8)
    store = ChromaVectorStore(db_dir=None, collection="test_files", embedding=emb)
    store.delete_collection()
    store = ChromaVectorStore(db_dir=None, collection="test_files", embedding=emb)

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "test.py"
        p.write_text("def add(a, b): return a + b", encoding="utf-8")
        ids = ingest_file(p, store=store)
        assert len(ids) >= 1

        results = store.query("add function", n_results=1)
        assert "add(a, b)" in results[0]["text"]

        # fresh store for directory
        store2 = ChromaVectorStore(db_dir=None, collection="test_dir", embedding=emb)
        store2.delete_collection()
        store2 = ChromaVectorStore(db_dir=None, collection="test_dir", embedding=emb)
        (Path(tmp) / "sub").mkdir()
        (Path(tmp) / "sub" / "readme.md").write_text(
            "# Project docs\nThis is about testing.", encoding="utf-8"
        )
        ids = ingest_directory(tmp, store=store2)
        assert len(ids) >= 1

        results = store2.query("project docs", n_results=3)
        texts = [r["text"] for r in results]
        assert any("Project docs" in t for t in texts)
