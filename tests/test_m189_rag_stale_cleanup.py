"""M189.1 RAG ingest 按 content_hash 清理残留 chunk 测试。

覆盖：_stale_ids 纯函数、get_where/delete_ids 原语边界、
内容改动后重 ingest 无旧 hash 残留、幂等重 ingest、多文件互不误删、
清理失败 fail-open 不炸主流程。
"""
from __future__ import annotations

from pathlib import Path

from rag.embeddings import MockEmbedding
from rag.ingest import _stale_ids, ingest_file
from rag.vector_store import ChromaVectorStore


def _make_store(name: str) -> ChromaVectorStore:
    emb = MockEmbedding(dim=16)
    store = ChromaVectorStore(db_dir=None, collection=name, embedding=emb)
    store.delete_collection()
    return ChromaVectorStore(db_dir=None, collection=name, embedding=emb)


# ---------- _stale_ids 纯函数 ----------

def test_stale_ids_filters_by_keep_hash() -> None:
    existing = [
        {"id": "aaa:0", "metadata": {"content_hash": "aaa"}},
        {"id": "bbb:0", "metadata": {"content_hash": "bbb"}},
        {"id": "bbb:1", "metadata": {"content_hash": "bbb"}},
    ]
    assert _stale_ids(existing, "bbb") == ["aaa:0"]


def test_stale_ids_missing_content_hash_key_is_stale() -> None:
    existing = [
        {"id": "old:0", "metadata": {}},
        {"id": "new:0", "metadata": {"content_hash": "new"}},
    ]
    assert _stale_ids(existing, "new") == ["old:0"]


def test_stale_ids_all_keep_returns_empty() -> None:
    existing = [
        {"id": "x:0", "metadata": {"content_hash": "x"}},
        {"id": "x:1", "metadata": {"content_hash": "x"}},
    ]
    assert _stale_ids(existing, "x") == []


def test_stale_ids_empty_input_returns_empty() -> None:
    assert _stale_ids([], "anything") == []


# ---------- get_where / delete_ids 原语边界 ----------

def test_get_where_empty_collection_returns_empty() -> None:
    store = _make_store("m189_empty_get")
    assert store.get_where({"source": "/nonexistent"}) == []


def test_delete_ids_empty_list_returns_zero() -> None:
    store = _make_store("m189_del_empty")
    assert store.delete_ids([]) == 0
    assert store._collection.count() == 0


def test_delete_ids_nonexistent_id_does_not_raise() -> None:
    store = _make_store("m189_del_ghost")
    store.upsert_documents([{"id": "real:0", "text": "hello", "metadata": {"a": 1}}])
    # 删除不存在的 id 不应抛异常
    store.delete_ids(["ghost:0"])
    assert store._collection.count() == 1


def test_get_where_returns_id_and_metadata_only() -> None:
    store = _make_store("m189_get_shape")
    store.upsert_documents([
        {"id": "h1:0", "text": "alpha", "metadata": {"source": "/a", "content_hash": "h1"}},
        {"id": "h1:1", "text": "beta", "metadata": {"source": "/a", "content_hash": "h1"}},
        {"id": "h2:0", "text": "gamma", "metadata": {"source": "/b", "content_hash": "h2"}},
    ])
    rows = store.get_where({"source": "/a"})
    assert len(rows) == 2
    for row in rows:
        assert set(row.keys()) == {"id", "metadata"}
        assert row["metadata"]["content_hash"] == "h1"
    ids = {r["id"] for r in rows}
    assert ids == {"h1:0", "h1:1"}


# ---------- 核心场景：内容改动后旧 hash 零残留 ----------

def test_reingest_after_edit_removes_stale_chunks(tmp_path: Path) -> None:
    f = tmp_path / "doc.txt"
    # 长文本（>800 字符）产生多 chunk：1700 字符 -> 3 个 chunk
    old_text = "oldmarker " + ("alpha " * 300)
    f.write_text(old_text, encoding="utf-8")

    store = _make_store("m189_core")
    ids1 = ingest_file(f, store=store)
    assert len(ids1) >= 2  # 确认确实产生了多 chunk
    assert store._collection.count() == len(ids1)

    # 改写为短文本，chunk 数变少，content_hash 变化
    new_text = "brand new content without the old marker."
    f.write_text(new_text, encoding="utf-8")
    ids2 = ingest_file(f, store=store)
    assert len(ids2) == 1

    # 同 source 只剩新 hash 的 chunk，旧 id 零残留
    rows = store.get_where({"source": str(f.resolve())})
    remaining_ids = {r["id"] for r in rows}
    assert remaining_ids == set(ids2)
    assert not any(i in remaining_ids for i in ids1)
    assert store._collection.count() == len(ids2)
    new_hash = ids2[0].split(":")[0]
    assert all(r["metadata"]["content_hash"] == new_hash for r in rows)

    # 语义检索结果不含旧文本
    hits = store.query("oldmarker alpha", n_results=5)
    assert hits, "查询应返回结果"
    assert all("oldmarker" not in h["text"] for h in hits)


# ---------- 幂等：内容不变重复 ingest 无删除 ----------

def test_reingest_unchanged_content_is_idempotent(tmp_path: Path) -> None:
    f = tmp_path / "stable.txt"
    text = "stable " + ("content " * 200)  # >800 字符，多 chunk
    f.write_text(text, encoding="utf-8")

    store = _make_store("m189_idem")
    ids1 = ingest_file(f, store=store)
    count1 = store._collection.count()
    ids2 = ingest_file(f, store=store)
    count2 = store._collection.count()

    assert ids1 == ids2
    assert count2 == count1 == len(ids1)


# ---------- 多文件互不误删 ----------

def test_reingest_one_file_preserves_other_files(tmp_path: Path) -> None:
    fa = tmp_path / "a.txt"
    fb = tmp_path / "b.txt"
    fa.write_text("filea " + ("xxx " * 300), encoding="utf-8")  # 多 chunk
    fb.write_text("fileb " + ("yyy " * 300), encoding="utf-8")  # 多 chunk

    store = _make_store("m189_multi")
    ids_a1 = ingest_file(fa, store=store)
    ids_b = ingest_file(fb, store=store)
    total_before = store._collection.count()
    assert total_before == len(ids_a1) + len(ids_b)

    # 改 A 重 ingest，B 应完好
    fa.write_text("filea shortened.", encoding="utf-8")
    ids_a2 = ingest_file(fa, store=store)

    rows_b = store.get_where({"source": str(fb.resolve())})
    assert {r["id"] for r in rows_b} == set(ids_b)

    rows_a = store.get_where({"source": str(fa.resolve())})
    assert {r["id"] for r in rows_a} == set(ids_a2)
    assert store._collection.count() == len(ids_a2) + len(ids_b)


# ---------- fail-open：清理异常不炸主流程 ----------

class _RaisingGetWhereStore(ChromaVectorStore):
    """get_where 永远抛异常，用于验证清理 fail-open。"""

    def get_where(self, filter):  # type: ignore[override]
        raise RuntimeError("simulated cleanup failure")


def test_ingest_fail_open_when_cleanup_raises(tmp_path: Path) -> None:
    f = tmp_path / "ok.txt"
    f.write_text("some normal content here.", encoding="utf-8")

    emb = MockEmbedding(dim=16)
    store = _RaisingGetWhereStore(db_dir=None, collection="m189_failopen", embedding=emb)
    ids = ingest_file(f, store=store)

    # 清理抛异常仍正常返回 upsert 的 ids
    assert len(ids) == 1
    assert store._collection.count() == 1
