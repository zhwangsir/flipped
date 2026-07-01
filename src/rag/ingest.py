"""文档 ingest：文件、目录、纯文本 -> 向量库。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from rag.vector_store import ChromaVectorStore, VectorStore


SUPPORTED_EXTS = {".txt", ".md", ".py", ".json", ".js", ".ts", ".html", ".css", ".yaml", ".yml"}
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100


def _chunk(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def ingest_text(text: str, metadata: dict[str, Any] | None = None, *, store: VectorStore | None = None) -> list[str]:
    store = store or ChromaVectorStore()
    docs = [{"text": text, "metadata": metadata or {}}]
    return store.add_documents(docs)


def ingest_file(path: str | Path, *, store: VectorStore | None = None) -> list[str]:
    store = store or ChromaVectorStore()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    text = p.read_text(encoding="utf-8", errors="ignore")
    chunks = _chunk(text)
    docs = [{"text": c, "metadata": {"source": str(p), "chunk": i}} for i, c in enumerate(chunks)]
    return store.add_documents(docs)


def ingest_directory(
    dir_path: str | Path,
    extensions: set[str] | None = None,
    *,
    store: VectorStore | None = None,
) -> list[str]:
    store = store or ChromaVectorStore()
    exts = extensions or SUPPORTED_EXTS
    ids: list[str] = []
    for p in Path(dir_path).rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            ids.extend(ingest_file(p, store=store))
    return ids
