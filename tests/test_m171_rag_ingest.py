"""M171 RAG 摄入层测试：幂等 upsert、gitignore 过滤、结构化分块、五字段元数据。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from rag.embeddings import MockEmbedding
from rag.ingest import _chunk_structured, ingest_directory, ingest_file
from rag.vector_store import ChromaVectorStore


def _make_store(name: str) -> ChromaVectorStore:
    emb = MockEmbedding(dim=16)
    store = ChromaVectorStore(db_dir=None, collection=name, embedding=emb)
    store.delete_collection()
    return ChromaVectorStore(db_dir=None, collection=name, embedding=emb)


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, timeout=10)


def test_gitignore_filtering_in_git_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], repo)
    _git(["config", "user.email", "test@example.com"], repo)
    _git(["config", "user.name", "Test"], repo)
    (repo / ".gitignore").write_text("ignored.md\nnode_modules/\n", encoding="utf-8")
    (repo / "keep.md").write_text("# Keep\nthis file is indexed.", encoding="utf-8")
    (repo / "ignored.md").write_text("# Ignored\nshould not be indexed.", encoding="utf-8")
    nm = repo / "node_modules"
    nm.mkdir()
    (nm / "x.md").write_text("# Dep\nshould not be indexed.", encoding="utf-8")

    store = _make_store("m171_gitignore")
    ids = ingest_directory(repo, store=store)
    assert len(ids) >= 1

    metadatas = store._collection.get(include=["metadatas"])["metadatas"]
    assert len(metadatas) == len(ids)
    sources = {m["source"] for m in metadatas}
    assert any(s.endswith("keep.md") for s in sources)
    assert not any("ignored.md" in s for s in sources)
    assert not any("node_modules" in s for s in sources)


def test_fallback_rglob_for_non_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.md").write_text("# Alpha\nplain directory ingest.", encoding="utf-8")

    store = _make_store("m171_rglob")
    ids = ingest_directory(plain, store=store)
    assert len(ids) >= 1

    metadatas = store._collection.get(include=["metadatas"])["metadatas"]
    assert any(m["source"].endswith("a.md") for m in metadatas)


def test_idempotent_reingest(tmp_path: Path) -> None:
    f = tmp_path / "doc.md"
    f.write_text("# Title\nSome body text here.", encoding="utf-8")

    store = _make_store("m171_idem")
    ids1 = ingest_file(f, store=store)
    count1 = store._collection.count()
    ids2 = ingest_file(f, store=store)
    count2 = store._collection.count()

    assert ids1 == ids2
    assert count1 == len(ids1)
    assert count2 == count1


def test_upsert_documents_overwrites_same_id() -> None:
    store = _make_store("m171_upsert")
    ids = store.upsert_documents([{"id": "fixed:0", "text": "version one", "metadata": {"v": 1}}])
    assert ids == ["fixed:0"]
    assert store._collection.count() == 1

    store.upsert_documents([{"id": "fixed:0", "text": "version two", "metadata": {"v": 2}}])
    assert store._collection.count() == 1

    results = store.query("version", n_results=1)
    assert results[0]["text"] == "version two"

    # 缺省 id 退回 uuid，新增而非覆盖
    new_ids = store.upsert_documents([{"text": "another doc"}])
    assert len(new_ids) == 1 and new_ids[0] and new_ids[0] != "fixed:0"
    assert store._collection.count() == 2


def test_markdown_structured_chunking() -> None:
    text = (
        "# Intro\n"
        "This is the introduction paragraph.\n"
        "\n"
        "## Setup\n"
        "Run the installer to set things up.\n"
        "\n"
        "## Usage\n"
        "Call the API with your key.\n"
    )
    chunks = _chunk_structured(text, ".md", chunk_size=60)
    assert len(chunks) == 3
    for chunk in chunks:
        # 标题行必须位于段首，不被孤立切断
        assert chunk.split("\n", 1)[0].startswith("#")
    setup_chunk = next(c for c in chunks if "## Setup" in c)
    assert "Run the installer" in setup_chunk


def test_code_blankline_chunking() -> None:
    text = (
        "def alpha():\n"
        "    return 1\n"
        "\n"
        "\n"
        "def beta():\n"
        "    return 2\n"
    )
    chunks = _chunk_structured(text, ".py", chunk_size=40)
    assert len(chunks) == 2
    for chunk in chunks:
        assert not ("alpha" in chunk and "beta" in chunk)


def test_metadata_fields(tmp_path: Path) -> None:
    projdir = tmp_path / "projdir"
    projdir.mkdir()
    f = projdir / "a.md"
    f.write_text("# Hello\nworld", encoding="utf-8")

    store = _make_store("m171_meta")
    ids = ingest_file(f, store=store, project="myproj")
    assert len(ids) == 1

    md = store.query("Hello", n_results=1)[0]["metadata"]
    assert md["source"] == str(f.resolve())
    assert md["ext"] == ".md"
    assert md["chunk"] == 0
    assert md["project"] == "myproj"
    assert len(md["content_hash"]) == 16
    assert ids[0] == f"{md['content_hash']}:0"

    # project 缺省 = 目录 basename
    store2 = _make_store("m171_meta_default")
    ingest_directory(projdir, store=store2)
    md2 = store2.query("Hello", n_results=1)[0]["metadata"]
    assert md2["project"] == "projdir"


def test_empty_file_returns_empty(tmp_path: Path) -> None:
    store = _make_store("m171_empty")
    f1 = tmp_path / "empty.md"
    f1.write_text("", encoding="utf-8")
    assert ingest_file(f1, store=store) == []

    f2 = tmp_path / "blank.md"
    f2.write_text("  \n\n  ", encoding="utf-8")
    assert ingest_file(f2, store=store) == []
    assert store._collection.count() == 0
