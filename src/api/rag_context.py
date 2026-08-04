"""chat/plan 自动 RAG 上下文注入：检索 + 格式化（fail-open）。"""
from __future__ import annotations

from typing import Any

RAG_CONTEXT_HEADER = "以下是用户项目知识库的检索结果（供参考，可能不完全相关）："


def build_rag_context(
    query: str,
    *,
    project: str | None = None,
    n_results: int = 4,
    max_chars: int = 2400,
    store: Any = None,
) -> tuple[str, int]:
    """返回 (context_text, chunk_count)。任何异常/无结果 → ("", 0)。"""
    try:
        if store is None:
            from rag.vector_store import ChromaVectorStore  # 函数级 lazy import（同 api/mcp_call.py 惯例）
            store = ChromaVectorStore()
        if project:
            results = store.query(query, n_results=n_results, filter={"project": project})
            if not results:
                results = store.query(query, n_results=n_results)  # 提召回：不过滤兜底重查
        else:
            results = store.query(query, n_results=n_results)
        if not results:
            return "", 0
        blocks: list[str] = []
        total = len(RAG_CONTEXT_HEADER)
        for i, item in enumerate(results, 1):
            metadata = item.get("metadata") or {}
            source = metadata.get("source") or "unknown"
            text = str(item.get("text") or "")
            block = f"[{i}] {source}\n{text}"
            if total + len(block) + 1 > max_chars:  # +1：与前文连接的 "\n"
                if blocks:
                    break  # 当前 chunk 整体放弃，不半截装入
                # 第一条即超：截断文本装入，保证至少一条
                avail = max(0, max_chars - total - 1 - len(f"[{i}] {source}\n"))
                blocks.append(f"[{i}] {source}\n{text[:avail]}")
                break
            blocks.append(block)
            total += len(block) + 1
        return RAG_CONTEXT_HEADER + "\n" + "\n".join(blocks), len(blocks)
    except Exception:
        return "", 0
