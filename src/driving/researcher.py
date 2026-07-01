"""调研上下文聚合：Web 搜索 + RAG 向量库 -> 给 orchestrator 的背景知识。"""
from __future__ import annotations

from rag.vector_store import ChromaVectorStore
from tools.web_search import search as web_search, format_for_llm


def gather(
    query: str,
    *,
    use_web: bool = True,
    use_rag: bool = True,
    n_results: int = 5,
) -> str:
    """并行/串行聚合 Web 搜索与私有 RAG 结果，返回格式化上下文。"""
    web_results = ""
    rag_results = ""

    if use_web:
        try:
            results = web_search(query, max_results=n_results)
            web_results = format_for_llm(results)
        except Exception as e:
            web_results = f"(web search failed: {e})"

    if use_rag:
        try:
            store = ChromaVectorStore()
            results = store.query(query, n_results=n_results)
            rag_results = _format_rag_results(results)
        except Exception as e:
            rag_results = f"(rag query failed: {e})"

    return format_context(query, web_results, rag_results)


def _format_rag_results(results: list[dict]) -> str:
    if not results:
        return "（无 RAG 结果）"
    lines: list[str] = []
    for i, r in enumerate(results, 1):
        meta = r.get("metadata") or {}
        source = meta.get("source", "unknown")
        lines.append(f"[{i}] {source}\n    {r.get('text', '')[:300]}")
    return "\n".join(lines)


def format_context(query: str, web_results: str, rag_results: str) -> str:
    parts = [f"调研问题: {query}"]
    if web_results:
        parts.append(f"\nWeb 搜索结果:\n{web_results}")
    if rag_results:
        parts.append(f"\n私有知识库 (RAG) 结果:\n{rag_results}")
    return "\n".join(parts)
