"""Chroma 向量库封装。"""
from __future__ import annotations

import abc
import os
import uuid
from typing import Any

import chromadb

from rag.embeddings import EmbeddingModel, _default_embedding


DEFAULT_COLLECTION = "flipped_knowledge"


class VectorStore(abc.ABC):
    """向量库抽象。"""

    @abc.abstractmethod
    def add_documents(self, docs: list[dict[str, Any]]) -> list[str]:
        """添加文档；每个 doc 至少包含 'text'，可选 'metadata'。返回 id 列表。"""
        ...

    @abc.abstractmethod
    def upsert_documents(self, docs: list[dict[str, Any]]) -> list[str]:
        """幂等写入；doc 可带 'id'（缺省退回 uuid4），同 id 覆盖。返回 id 列表。"""
        ...

    @abc.abstractmethod
    def query(self, text: str, n_results: int = 5, filter: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """语义检索，返回 [{id, text, metadata, distance}] 列表。"""
        ...

    @abc.abstractmethod
    def delete_collection(self) -> None:
        """删除整个集合（谨慎）。"""
        ...

    @abc.abstractmethod
    def get_where(self, filter: dict[str, Any]) -> list[dict[str, Any]]:
        """按 metadata 过滤返回 [{"id": str, "metadata": dict}]（不含 text/embedding，轻量）；空结果返回 []。"""
        ...

    @abc.abstractmethod
    def delete_ids(self, ids: list[str]) -> int:
        """按 id 删除，返回删除条数；空列表返回 0 且不触库。"""
        ...


class ChromaVectorStore(VectorStore):
    """基于 Chroma 的本地持久化向量库。

    db_dir=None 且环境变量 RAG_DB_DIR 未设置时使用 EphemeralClient（内存，测试用）。
    """

    def __init__(
        self,
        db_dir: str | None = None,
        collection: str = DEFAULT_COLLECTION,
        embedding: EmbeddingModel | None = None,
    ):
        self.embedding = embedding or _default_embedding()
        self.collection_name = collection
        db_dir = db_dir or os.environ.get("RAG_DB_DIR")
        if db_dir:
            self._client = chromadb.PersistentClient(path=db_dir)
        else:
            self._client = chromadb.EphemeralClient()
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def add_documents(self, docs: list[dict[str, Any]]) -> list[str]:
        if not docs:
            return []
        ids = [str(uuid.uuid4()) for _ in docs]
        texts = [str(d.get("text", "")) for d in docs]
        embeddings = self.embedding.embed(texts)
        metadatas = [d.get("metadata") or {} for d in docs]
        self._collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )
        return ids

    def upsert_documents(self, docs: list[dict[str, Any]]) -> list[str]:
        if not docs:
            return []
        ids = [str(d.get("id") or uuid.uuid4()) for d in docs]
        texts = [str(d.get("text", "")) for d in docs]
        embeddings = self.embedding.embed(texts)
        metadatas = [d.get("metadata") or None for d in docs]
        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )
        return ids

    def query(self, text: str, n_results: int = 5, filter: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        embedding = self.embedding.embed([text])[0]
        results = self._collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            where=filter,
            include=["documents", "metadatas", "distances"],
        )
        items: list[dict[str, Any]] = []
        ids = results.get("ids") or [[]]
        documents = results.get("documents") or [[]]
        metadatas = results.get("metadatas") or [[]]
        distances = results.get("distances") or [[]]
        for i, doc_id in enumerate(ids[0]):
            items.append({
                "id": doc_id,
                "text": documents[0][i] if documents and len(documents[0]) > i else "",
                "metadata": metadatas[0][i] if metadatas and len(metadatas[0]) > i else {},
                "distance": distances[0][i] if distances and len(distances[0]) > i else None,
            })
        return items

    def get_where(self, filter: dict[str, Any]) -> list[dict[str, Any]]:
        results = self._collection.get(where=filter, include=["metadatas"])
        ids = results.get("ids") or []
        metadatas = results.get("metadatas") or []
        # Chroma 返回平铺 list，zip 成 dict 列表；metadatas 元素可能为 None，兜底 {}
        return [
            {"id": doc_id, "metadata": metadatas[i] or {}}
            for i, doc_id in enumerate(ids)
        ]

    def delete_ids(self, ids: list[str]) -> int:
        if not ids:
            return 0
        self._collection.delete(ids=ids)
        return len(ids)

    def delete_collection(self) -> None:
        try:
            self._client.delete_collection(self.collection_name)
        except Exception:
            pass
