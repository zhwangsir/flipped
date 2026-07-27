"""M105 · 失败知识库（Failure Knowledge Base）。

失败模式形成知识库，下次遇到同类问题自动预警 + 注入规避策略。
- record_failure: 每次失败后记录（根因、错误详情、尝试修复、是否解决、解决耗时）
- query_similar_failures: 语义检索历史类似失败
- build_warning_from_history: 生成历史教训预警文本
- get_failure_stats: Top 失败模式统计（给前端用）

fail-open: 任何异常都不阻塞主流程。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from driving.db import connect, default_db_path


_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    failure_id TEXT NOT NULL UNIQUE,
    task_description TEXT NOT NULL,
    task_description_vector TEXT NOT NULL DEFAULT '',
    design_style TEXT NOT NULL DEFAULT 'auto',
    cause TEXT NOT NULL DEFAULT 'unknown',
    error_detail TEXT NOT NULL DEFAULT '',
    stop_reason TEXT NOT NULL DEFAULT '',
    iterations INTEGER NOT NULL DEFAULT 1,
    resolved INTEGER NOT NULL DEFAULT 0,
    resolution TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL
)
"""

_INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_failures_cause ON failures(cause)"
_INDEX_STYLE_SQL = "CREATE INDEX IF NOT EXISTS idx_failures_style ON failures(design_style)"

_write_lock = threading.Lock()
_wal_initialized: set[str] = set()


def _enable_wal(db_path: str) -> None:
    if db_path in _wal_initialized:
        return
    try:
        with connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
        _wal_initialized.add(db_path)
    except Exception:
        pass


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_TABLE_SQL)
    conn.execute(_INDEX_SQL)
    conn.execute(_INDEX_STYLE_SQL)


def _embed(text: str) -> list[float]:
    try:
        from driving.gold_memory import _embed as _gm_embed
        return _gm_embed(text[:500])
    except Exception:
        return []


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    try:
        from driving.gold_memory import _cosine_similarity as _gm_cos
        return _gm_cos(a, b)
    except Exception:
        import math
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)


def _signature(description: str, cause: str) -> str:
    key = f"{description.lower().strip()}:{cause}"
    return hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()[:16]


@dataclass
class FailureEntry:
    """失败知识库条目。"""
    failure_id: str
    task_description: str
    design_style: str
    cause: str
    error_detail: str
    stop_reason: str
    iterations: int
    resolved: bool
    resolution: str
    timestamp: str
    task_description_vector: list[float] = field(default_factory=list)
    similarity: float = 0.0


@dataclass
class FailureStats:
    """失败统计数据。"""
    total_failures: int
    resolved_count: int
    unresolved_count: int
    by_cause: dict[str, int]
    top_causes: list[tuple[str, int]]


def _row_to_entry(row: sqlite3.Row) -> FailureEntry:
    return FailureEntry(
        failure_id=row["failure_id"],
        task_description=row["task_description"],
        design_style=row["design_style"],
        cause=row["cause"],
        error_detail=row["error_detail"],
        stop_reason=row["stop_reason"],
        iterations=row["iterations"],
        resolved=bool(row["resolved"]),
        resolution=row["resolution"],
        timestamp=row["timestamp"],
        task_description_vector=json.loads(row["task_description_vector"]) if row["task_description_vector"] else [],
    )


def record_failure(
    task_description: str,
    design_style: str,
    *,
    cause: str,
    error_detail: str,
    stop_reason: str,
    iterations: int = 1,
    resolved: bool = False,
    resolution: str = "",
    db_path: str | None = None,
) -> FailureEntry | None:
    """记录一次失败到知识库。返回写入的条目，异常时返回 None（fail-open）。"""
    db_path = db_path or default_db_path()
    try:
        fid = _signature(task_description, cause)
        vector = _embed(task_description)
        vector_json = json.dumps(vector) if vector else ""
        now = datetime.now(timezone.utc).isoformat()

        _enable_wal(db_path)
        with _write_lock:
            with connect(db_path) as conn:
                _ensure_table(conn)
                conn.execute(
                    """
                    INSERT INTO failures (
                        failure_id, task_description, task_description_vector,
                        design_style, cause, error_detail, stop_reason,
                        iterations, resolved, resolution, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fid + "-" + now[:19].replace(":", ""),
                        task_description[:500],
                        vector_json,
                        design_style,
                        cause,
                        error_detail[:1000],
                        stop_reason,
                        iterations,
                        1 if resolved else 0,
                        resolution[:1000],
                        now,
                    ),
                )

        return FailureEntry(
            failure_id=fid,
            task_description=task_description[:500],
            design_style=design_style,
            cause=cause,
            error_detail=error_detail[:1000],
            stop_reason=stop_reason,
            iterations=iterations,
            resolved=resolved,
            resolution=resolution[:1000],
            timestamp=now,
            task_description_vector=vector,
        )
    except Exception:
        return None


def query_similar_failures(
    description: str,
    design_style: str = "auto",
    *,
    db_path: str | None = None,
    max_results: int = 5,
    threshold: float = 0.4,
) -> list[FailureEntry]:
    """语义检索历史类似失败。空列表或异常时返回 []（fail-open）。"""
    db_path = db_path or default_db_path()
    try:
        _enable_wal(db_path)
        with connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_table(conn)
            rows = conn.execute(
                "SELECT * FROM failures ORDER BY timestamp DESC LIMIT 100"
            ).fetchall()

        if not rows:
            return []

        query_vec = _embed(description)
        entries = [_row_to_entry(r) for r in rows]

        if query_vec:
            scored = []
            for e in entries:
                if e.task_description_vector:
                    score = _cosine_similarity(query_vec, e.task_description_vector)
                    e.similarity = score
                    if score >= threshold:
                        scored.append(e)
            scored.sort(key=lambda x: x.similarity, reverse=True)
            return scored[:max_results]

        # Fallback: 按 cause 关键词匹配
        keywords = set(description.lower().split())
        for e in entries:
            overlap = len(keywords & set(e.task_description.lower().split()))
            e.similarity = min(1.0, overlap / max(1, len(keywords)))
        entries.sort(key=lambda x: x.similarity, reverse=True)
        return [e for e in entries if e.similarity > 0][:max_results]
    except Exception:
        return []


def get_failure_stats(
    db_path: str | None = None,
    *,
    limit: int = 10,
) -> FailureStats:
    """获取失败统计数据。异常时返回空统计（fail-open）。"""
    db_path = db_path or default_db_path()
    try:
        _enable_wal(db_path)
        with connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_table(conn)

            total_row = conn.execute(
                "SELECT COUNT(*) as cnt, SUM(resolved) as resolved FROM failures"
            ).fetchone()
            total = total_row["cnt"] if total_row else 0
            resolved = total_row["resolved"] if total_row and total_row["resolved"] else 0

            cause_rows = conn.execute(
                "SELECT cause, COUNT(*) as cnt FROM failures GROUP BY cause ORDER BY cnt DESC LIMIT ?",
                (limit,),
            ).fetchall()

            by_cause = {row["cause"]: row["cnt"] for row in cause_rows}
            top_causes = [(row["cause"], row["cnt"]) for row in cause_rows]

        return FailureStats(
            total_failures=total,
            resolved_count=resolved,
            unresolved_count=total - resolved,
            by_cause=by_cause,
            top_causes=top_causes,
        )
    except Exception:
        return FailureStats(
            total_failures=0,
            resolved_count=0,
            unresolved_count=0,
            by_cause={},
            top_causes=[],
        )


def build_warning_from_history(
    description: str,
    design_style: str = "auto",
    *,
    db_path: str | None = None,
    max_warnings: int = 3,
) -> str:
    """从历史失败中构建预警文本，注入到 supervisor prompt。

    没有历史失败时返回空字符串。
    """
    db_path = db_path or default_db_path()
    try:
        failures = query_similar_failures(
            description, design_style, db_path=db_path, max_results=max_warnings
        )
        if not failures:
            return ""

        parts = ["【历史教训】类似任务曾遇到以下问题，请注意规避："]
        for i, f in enumerate(failures[:max_warnings], 1):
            detail = f.error_detail[:80] if f.error_detail else f.cause
            if f.resolved and f.resolution:
                parts.append(f"  {i}. {f.cause}: {detail} → 解决方案: {f.resolution[:60]}")
            else:
                parts.append(f"  {i}. {f.cause}: {detail} (未解决)")

        return "\n".join(parts)
    except Exception:
        return ""


def get_all_failures(
    *,
    db_path: str | None = None,
    limit: int = 1000,
    resolved: bool | None = None,
) -> list[FailureEntry]:
    """获取所有失败记录（用于聚类分析）。"""
    db_path = db_path or default_db_path()
    try:
        with connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            query = "SELECT * FROM failures"
            conditions = []
            params: list[Any] = []
            if resolved is not None:
                conditions.append("resolved = ?")
                params.append(1 if resolved else 0)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [_row_to_entry(row) for row in rows]
    except Exception:
        return []


def run_clustering_analysis(
    *,
    db_path: str | None = None,
    include_resolved: bool = False,
) -> dict[str, Any]:
    """运行失败聚类分析，返回完整的分析报告。

    M109 集成：一键获取聚类统计 + 系统性失败 + 改进建议。
    """
    db_path = db_path or default_db_path()
    try:
        from driving.failure_clustering import (
            cluster_failures,
            identify_systemic_failures,
            generate_improvement_suggestions,
            get_cluster_stats,
        )

        failures = get_all_failures(
            db_path=db_path,
            resolved=False if not include_resolved else None,
        )
        if not failures:
            return {
                "has_data": False,
                "total_failures": 0,
                "stats": {},
                "systemic_failures": [],
                "suggestions": [],
            }

        failure_dicts = [
            {
                "id": f.failure_id,
                "task_description": f.task_description,
                "cause": f.cause,
                "error_detail": f.error_detail,
                "iterations": f.iterations,
                "resolved": f.resolved,
            }
            for f in failures
        ]

        clusters = cluster_failures(failure_dicts)
        total = len(failures)
        systemic = identify_systemic_failures(clusters, total_failures=total)
        suggestions = generate_improvement_suggestions(clusters, total_failures=total)
        stats = get_cluster_stats(clusters, total_failures=total)

        return {
            "has_data": True,
            "total_failures": total,
            "stats": stats,
            "systemic_failures": [
                {
                    "cluster_id": s.cluster_id,
                    "cause_category": s.cause_category,
                    "summary": s.summary,
                    "frequency": s.frequency,
                    "percentage": s.percentage,
                    "severity": s.severity,
                    "suggested_fix": s.suggested_fix,
                }
                for s in systemic
            ],
            "suggestions": suggestions,
        }
    except Exception:
        return {
            "has_data": False,
            "total_failures": 0,
            "stats": {},
            "systemic_failures": [],
            "suggestions": [],
            "error": "clustering analysis failed",
        }
