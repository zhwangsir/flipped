"""chat/plan 自动 RAG 上下文注入：检索 + 格式化（fail-open）。"""
from __future__ import annotations

import threading
from typing import Any

RAG_CONTEXT_HEADER = "以下是用户项目知识库的检索结果（供参考，可能不完全相关）："

# 默认 store 进程级单例（M197.2 黑盒修复）。
# 背景：chromadb SharedSystemClient 按 path 缓存 System 并计引用数；每次调用新建
# PersistentClient 时，函数返回后 client 被 GC → refcount 归零 → System 被逐出全局
# 缓存。并发 to_thread 下另一线程的 `return _identifier_to_system[id]` 恰在逐出后
# 执行 → KeyError（被 fail-open 吞掉表现为 rag_chunks=0）。持活单例使 refcount
# 不归零，竞态消除；RAG_DB_DIR 进程启动时固定，单例语义安全。
_default_store: Any = None
_default_store_lock = threading.Lock()


def _get_default_store() -> Any:
    global _default_store
    if _default_store is None:
        with _default_store_lock:
            if _default_store is None:
                from rag.vector_store import ChromaVectorStore  # 函数级 lazy import（同 api/mcp_call.py 惯例）
                _default_store = ChromaVectorStore()
    return _default_store


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
            store = _get_default_store()
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
        import os as _os
        if _os.environ.get("FLIPPED_RAG_DEBUG") == "1":  # 临时诊断：fail-open 异常可见
            import traceback, sys as _sys
            traceback.print_exc(file=_sys.stderr)
        return "", 0
