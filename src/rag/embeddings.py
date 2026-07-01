"""可插拔嵌入模型。

默认尝试 sentence-transformers (语义、离线)；若未安装则 fallback 到 mock 嵌入，
确保沙箱/测试环境仍可运行 RAG 流程。
"""
from __future__ import annotations

import abc
import hashlib
import os
from typing import Any


class EmbeddingModel(abc.ABC):
    """嵌入模型抽象。"""

    @abc.abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """返回与 texts 等长的向量列表，所有向量维度相同。"""
        ...

    def dim(self) -> int | None:
        """向量维度；None 表示按需计算。"""
        return None


class MockEmbedding(EmbeddingModel):
    """确定性哈希嵌入，用于测试和无 sentence-transformers 的环境。

    非语义，但关键词精确匹配时会有较高余弦相似度。
    """

    def __init__(self, dim: int = 64):
        self._dim = dim

    def dim(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self._dim
            for w in text.lower().split():
                h = hashlib.sha256(w.encode()).digest()
                for i in range(self._dim):
                    idx = i % len(h)
                    sign = 1.0 if (i + h[idx]) % 2 == 0 else -1.0
                    vec[i] += sign * (h[idx] / 255.0)
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            vectors.append([x / norm for x in vec])
        return vectors


class SentenceTransformerEmbeddings(EmbeddingModel):
    """sentence-transformers 本地嵌入（~80MB 模型，完全离线）。

    依赖 sentence-transformers；未安装时实例化会抛 ImportError，
    由调用方 catch 后 fallback 到 MockEmbedding。
    """

    def __init__(self, model: str | None = None, mock_dim: int = 384):
        self.model_name = model or os.environ.get(
            "RAG_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
        self._mock_dim = mock_dim
        self._model: Any = None
        self._dim: int | None = None

    def _load(self) -> None:
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(self.model_name)
        self._dim = self._model.get_sentence_embedding_dimension()

    def dim(self) -> int:
        self._load()
        return self._dim or self._mock_dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._load()
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()


def _default_embedding() -> EmbeddingModel:
    """生产环境优先用 sentence-transformers；否则 mock。"""
    try:
        emb = SentenceTransformerEmbeddings()
        emb.dim()  # 强制加载，失败则 fallback
        return emb
    except Exception:
        return MockEmbedding()
