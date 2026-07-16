"""M111 · 上下文记忆分层。

三级记忆架构：
- working: 工作记忆（当前对话/任务）—— 容量小，速度快
- recent: 近期记忆（最近 N 个任务）—— 中等容量
- long_term: 长期记忆（Skill + Failure KB）—— 大容量，持久化

自动摘要：工作记忆满了自动压缩到近期记忆
关联检索：做新任务时，自动从长期记忆中检索相关经验

fail-open: 任何异常都优雅降级，不阻塞主流程。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from driving.failure_kb import _embed, _cosine_similarity


class MemoryLevel(str, Enum):
    working = "working"
    recent = "recent"
    long_term = "long_term"


@dataclass
class MemoryItem:
    """记忆条目。"""
    id: str
    content: str
    level: MemoryLevel
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    access_count: int = 0


@dataclass
class HierarchicalMemory:
    """分层记忆系统。

    三级记忆 + 自动压缩 + 关联检索。
    """
    max_working: int = 20
    max_recent: int = 50
    working: list[MemoryItem] = field(default_factory=list)
    recent: list[MemoryItem] = field(default_factory=list)
    long_term_refs: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        content: str,
        *,
        level: MemoryLevel = MemoryLevel.working,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """添加一条记忆，返回记忆 ID。"""
        try:
            mid = f"mem-{uuid.uuid4().hex[:8]}"
            emb = _embed(content)
            item = MemoryItem(
                id=mid,
                content=content,
                level=level,
                metadata=metadata or {},
                embedding=emb,
            )

            if level == MemoryLevel.working:
                self.working.append(item)
                if len(self.working) > self.max_working:
                    self._compress_working()
            elif level == MemoryLevel.recent:
                self.recent.append(item)
                if len(self.recent) > self.max_recent:
                    self.recent = self.recent[-self.max_recent:]
            else:
                self.long_term_refs.append({
                    "id": mid,
                    "content": content[:200],
                    "metadata": metadata or {},
                })

            return mid
        except Exception:
            return ""

    def _compress_working(self) -> None:
        """把最早的工作记忆压缩成摘要，移入近期记忆。"""
        try:
            if len(self.working) <= self.max_working:
                return

            to_compress = self.working[: len(self.working) - self.max_working + 5]
            self.working = self.working[len(to_compress):]

            summary_parts = []
            for item in to_compress[-5:]:
                summary_parts.append(f"- {item.content[:80]}")
            summary = f"[工作记忆摘要 {len(to_compress)} 条] " + "; ".join(summary_parts)

            emb = _embed(summary)
            self.recent.append(MemoryItem(
                id=f"mem-summary-{uuid.uuid4().hex[:6]}",
                content=summary,
                level=MemoryLevel.recent,
                metadata={"compressed_from": len(to_compress), "type": "summary"},
                embedding=emb,
            ))
            if len(self.recent) > self.max_recent:
                self.recent = self.recent[-self.max_recent:]
        except Exception:
            pass

    def get_level(self, level: MemoryLevel) -> list[MemoryItem]:
        """获取某一层级的所有记忆。"""
        try:
            if level == MemoryLevel.working:
                return list(self.working)
            elif level == MemoryLevel.recent:
                return list(self.recent)
            else:
                return [
                    MemoryItem(
                        id=r.get("id", ""),
                        content=r.get("content", ""),
                        level=MemoryLevel.long_term,
                        metadata=r.get("metadata", {}),
                    )
                    for r in self.long_term_refs
                ]
        except Exception:
            return []

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        levels: list[MemoryLevel] | None = None,
    ) -> list[MemoryItem]:
        """语义检索记忆，返回最相关的 top_k 条。"""
        try:
            if levels is None:
                levels = [MemoryLevel.working, MemoryLevel.recent, MemoryLevel.long_term]

            all_items: list[MemoryItem] = []
            for level in levels:
                all_items.extend(self.get_level(level))

            if not all_items:
                return []

            query_vec = _embed(query)
            scored = []
            for item in all_items:
                vec = item.embedding or _embed(item.content)
                sim = _cosine_similarity(query_vec, vec)
                scored.append((sim, item))

            scored.sort(key=lambda x: x[0], reverse=True)
            for _, item in scored[:top_k]:
                item.access_count += 1
            return [item for _, item in scored[:top_k]]
        except Exception:
            return []

    def get_summary(self) -> dict[str, Any]:
        """获取记忆系统的总体状态摘要。"""
        try:
            return {
                "working": len(self.working),
                "recent": len(self.recent),
                "long_term": len(self.long_term_refs),
                "working_capacity": f"{len(self.working)}/{self.max_working}",
                "recent_capacity": f"{len(self.recent)}/{self.max_recent}",
            }
        except Exception:
            return {"working": 0, "recent": 0, "long_term": 0}
