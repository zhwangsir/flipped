"""Gold Memory 自学习机制（M10.4-D / M11.2 语义检索增强）。

让系统越跑越快：把每轮成功任务的 (prompt 模式, verify_cmd 模式, 设计风格)
沉淀成 Gold Memory，下次遇到类似任务时直接复用。

Gold Memory 是一张 SQLite 持久化的"经验表"：
- 任务描述的向量嵌入（M11.2：语义检索替代 MD5 哈希精确匹配）
- 任务描述的关键词签名（保留作为唯一键 + fallback）
- 使用的 design_style
- 成功的 verify_cmd 模式
- 成功率统计
- 最近一次成功的 feedback/planner 调整

M11.2 查询策略：向量余弦相似度 Top-K（语义匹配）→ fallback 到签名匹配。
让"实现登录页面"和"创建登录页"能命中同一条经验。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from driving.factory_loop import FactoryTask, FactoryState, TaskResult


_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS gold_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_signature TEXT NOT NULL,
    design_style TEXT NOT NULL DEFAULT 'auto',
    description TEXT NOT NULL,
    verify_cmd TEXT NOT NULL,
    stop_reason TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    success INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    task_vector TEXT NOT NULL DEFAULT '',
    UNIQUE(task_signature, design_style, verify_cmd)
)
"""

_INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_gold_sig ON gold_memory(task_signature)"


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_TABLE_SQL)
    conn.execute(_INDEX_SQL)
    # M11.2 迁移：给旧表加 task_vector 列
    cols = {row[1] for row in conn.execute("PRAGMA table_info(gold_memory)")}
    if "task_vector" not in cols:
        conn.execute("ALTER TABLE gold_memory ADD COLUMN task_vector TEXT NOT NULL DEFAULT ''")


# M96: 并发安全 — 保护写操作的锁 + WAL 模式
_gold_memory_write_lock = threading.Lock()
_wal_initialized: set[str] = set()


def _enable_wal(db_path: str) -> None:
    """M96: 启用 SQLite WAL 模式 + busy_timeout,提升并发读写能力。

    WAL(Write-Ahead Logging)允许读写并发(默认 rollback journal 模式下写会阻塞读)。
    busy_timeout=5000ms 让写冲突时等待而非立即报 "database is locked"。
    每个 db_path 只初始化一次(幂等)。
    """
    if db_path in _wal_initialized:
        return
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
        _wal_initialized.add(db_path)
    except Exception:
        pass  # 临时文件或内存 DB 可能不支持 WAL,fail-open


# M11.2：模块级 embedding 单例（懒加载，避免每次调用都初始化模型）
_embedding_model = None


def _get_embedding_model():
    """获取 embedding 模型单例（sentence-transformers 优先，fallback MockEmbedding）。"""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    try:
        from rag.embeddings import _default_embedding
        _embedding_model = _default_embedding()
    except Exception:
        _embedding_model = None
    return _embedding_model


def _embed(text: str) -> list[float]:
    """把文本嵌入为向量。无 embedding 模型时返回空列表（fallback 到签名匹配）。"""
    model = _get_embedding_model()
    if model is None:
        return []
    try:
        vecs = model.embed([text])
        return vecs[0] if vecs else []
    except Exception:
        return []


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。维度不匹配或空向量返回 0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _signature(description: str) -> str:
    """从任务描述提取关键词签名（去停用词 + 取高频词）。

    让"实现登录页面"和"创建登录页"匹配到同一条经验。
    """
    text = description.lower()
    # 提取中英文关键词（中文单字 + 英文单词）
    words = re.findall(r"[a-z_]+|[\u4e00-\u9fff]", text)
    # 去常见停用词（中文单字不被 len 过滤）
    stop = {"the", "a", "an", "is", "to", "for", "and", "or", "in", "on",
            "的", "了", "是", "在", "和", "与", "或", "实", "现", "创", "建"}
    # 英文词 > 1 字符，中文单字保留
    words = [w for w in words if w not in stop and (len(w) > 1 or "\u4e00" <= w <= "\u9fff")]
    if not words:
        return hashlib.md5(description.encode()).hexdigest()[:12]
    # 排序后 hash，保证顺序无关
    return hashlib.md5("|".join(sorted(set(words))).encode()).hexdigest()[:12]


@dataclass
class GoldEntry:
    """一条 Gold Memory 经验。"""
    task_signature: str
    design_style: str
    description: str
    verify_cmd: str
    stop_reason: str
    success: bool
    summary: str = ""
    created_at: str = ""


@dataclass
class GoldQueryResult:
    """Gold Memory 查询结果。"""
    found: bool
    success_rate: float = 0.0
    total_attempts: int = 0
    successful_attempts: int = 0
    recommended_verify_cmd: str = ""
    recommended_style: str = ""
    notes: list[str] = field(default_factory=list)


def record_task_result(
    task: FactoryTask,
    state: FactoryState,
    result: TaskResult,
    db_path: str = "data/gold_memory.db",
) -> None:
    """记录一个任务结果到 Gold Memory。

    M96: 加锁保护写操作,防止并发任务的 "database is locked" 异常。
    """
    sig = _signature(task.description)
    verify_cmd_str = " ".join(task.verify_cmd) if task.verify_cmd else "true"
    # M11.2：嵌入任务描述向量，用于语义检索
    vector = _embed(task.description[:500])
    vector_json = json.dumps(vector) if vector else ""
    # M96: 启用 WAL + 加锁写
    _enable_wal(db_path)
    with _gold_memory_write_lock:
        with sqlite3.connect(db_path) as conn:
            _ensure_table(conn)
            conn.execute(
                """
                INSERT INTO gold_memory (
                    task_signature, design_style, description, verify_cmd,
                    stop_reason, summary, success, created_at, task_vector
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_signature, design_style, verify_cmd) DO UPDATE SET
                    stop_reason=excluded.stop_reason,
                    summary=excluded.summary,
                    success=excluded.success,
                    created_at=excluded.created_at,
                    task_vector=excluded.task_vector
                """,
                (
                    sig,
                    state.design_style or "auto",
                    task.description[:500],
                    verify_cmd_str[:500],
                    result.stop_reason,
                    result.summary[:500],
                    1 if result.verified else 0,
                    datetime.now(timezone.utc).isoformat(),
                    vector_json,
                ),
            )


def query_similar(
    description: str,
    design_style: str = "auto",
    db_path: str = "data/gold_memory.db",
    limit: int = 5,
) -> GoldQueryResult:
    """查询相似任务的历史经验。

    M11.2：先用向量余弦相似度做语义检索（让"实现登录页面"匹配"创建登录页"）。
    无向量或无语义匹配时，fallback 到签名精确匹配。

    返回该任务签名 + 设计风格下的成功率 + 推荐的 verify_cmd。
    """
    sig = _signature(description)
    query_vec = _embed(description[:500])

    with sqlite3.connect(db_path) as conn:
        _ensure_table(conn)
        # 1. M11.2 语义检索：取所有带向量的行，计算余弦相似度
        if query_vec:
            cur = conn.execute(
                """
                SELECT verify_cmd, success, stop_reason, summary, design_style, task_vector
                FROM gold_memory
                WHERE task_vector != '' AND (design_style = ? OR design_style = 'auto' OR ? = 'auto')
                """,
                (design_style, design_style),
            )
            all_rows = cur.fetchall()
            # 计算相似度并排序
            scored = []
            for r in all_rows:
                try:
                    stored_vec = json.loads(r[5])
                except Exception:
                    continue
                sim = _cosine_similarity(query_vec, stored_vec)
                if sim >= 0.5:  # 相似度阈值
                    scored.append((sim, r))
            scored.sort(key=lambda x: x[0], reverse=True)
            rows = [s[1] for s in scored[:limit]]

        # 2. Fallback：签名精确匹配（无向量或语义检索无结果时）
        if not query_vec or not rows:
            cur = conn.execute(
                """
                SELECT verify_cmd, success, stop_reason, summary, design_style, task_vector
                FROM gold_memory
                WHERE task_signature = ? AND (design_style = ? OR design_style = 'auto' OR ? = 'auto')
                ORDER BY created_at DESC LIMIT ?
                """,
                (sig, design_style, design_style, limit),
            )
            rows = cur.fetchall()

    if not rows:
        return GoldQueryResult(found=False)

    total = len(rows)
    successes = sum(1 for r in rows if r[1])
    # 找最近一次成功的 verify_cmd
    recommended = ""
    recommended_style = ""
    for r in rows:
        if r[1]:  # success
            recommended = r[0]
            recommended_style = r[4]
            break

    notes = []
    for r in rows:
        if not r[1] and r[2]:  # failed
            notes.append(f"失败模式({r[2]}): {r[3][:100]}")

    return GoldQueryResult(
        found=True,
        success_rate=successes / total,
        total_attempts=total,
        successful_attempts=successes,
        recommended_verify_cmd=recommended,
        recommended_style=recommended_style,
        notes=notes[:3],
    )


def build_memory_hint(description: str, design_style: str = "auto", db_path: str = "data/gold_memory.db") -> str:
    """生成给 planner 的经验提示。

    如果有类似任务的历史经验，返回一段提示让 planner 复用成功的 verify_cmd 模式。
    这让系统"越跑越快"——第一次摸索，第二次直接复用。
    """
    result = query_similar(description, design_style, db_path)
    if not result.found or result.total_attempts == 0:
        return ""

    parts = [f"【Gold Memory 经验】检测到 {result.total_attempts} 次相似任务历史"]
    if result.success_rate > 0:
        parts.append(f"成功率 {result.success_rate:.0%}（{result.successful_attempts}/{result.total_attempts}）")
    if result.recommended_verify_cmd:
        parts.append(f"推荐复用 verify_cmd 模式: {result.recommended_verify_cmd}")
    if result.notes:
        parts.append("已知失败模式（避免）:")
        for note in result.notes:
            parts.append(f"  - {note}")
    return "\n".join(parts) + "\n"


def clear_memory(db_path: str = "data/gold_memory.db") -> None:
    """清空 Gold Memory（测试用）。"""
    with sqlite3.connect(db_path) as conn:
        _ensure_table(conn)
        conn.execute("DELETE FROM gold_memory")


def query_similar_failures(
    description: str,
    design_style: str = "auto",
    db_path: str = "data/gold_memory.db",
    limit: int = 5,
) -> list[GoldEntry]:
    """M91.1 查询相似任务的历史失败记录(只返回 success=0)。

    复用 query_similar 的向量语义检索逻辑,但只返回失败记录。
    RCA 用此函数查"类似任务历史上怎么失败的",增强根因分析的修复建议。

    Returns:
        list[GoldEntry],每条含 stop_reason/summary,按相似度降序。
    """
    sig = _signature(description)
    query_vec = _embed(description[:500])

    with sqlite3.connect(db_path) as conn:
        _ensure_table(conn)
        # 1. 语义检索:取所有带向量的失败行
        if query_vec:
            cur = conn.execute(
                """
                SELECT task_signature, design_style, description, verify_cmd,
                       stop_reason, summary, success, created_at, task_vector
                FROM gold_memory
                WHERE success = 0 AND task_vector != ''
                  AND (design_style = ? OR design_style = 'auto' OR ? = 'auto')
                """,
                (design_style, design_style),
            )
            all_rows = cur.fetchall()
            scored = []
            for r in all_rows:
                try:
                    stored_vec = json.loads(r[8])
                except Exception:
                    continue
                sim = _cosine_similarity(query_vec, stored_vec)
                if sim >= 0.5:
                    scored.append((sim, r))
            scored.sort(key=lambda x: x[0], reverse=True)
            rows = [s[1] for s in scored[:limit]]
        else:
            rows = []

        # 2. Fallback:签名精确匹配的失败记录
        if not query_vec or not rows:
            cur = conn.execute(
                """
                SELECT task_signature, design_style, description, verify_cmd,
                       stop_reason, summary, success, created_at, task_vector
                FROM gold_memory
                WHERE success = 0 AND task_signature = ?
                  AND (design_style = ? OR design_style = 'auto' OR ? = 'auto')
                ORDER BY created_at DESC LIMIT ?
                """,
                (sig, design_style, design_style, limit),
            )
            rows = cur.fetchall()

    return [
        GoldEntry(
            task_signature=r[0], design_style=r[1], description=r[2],
            verify_cmd=r[3], stop_reason=r[4], summary=r[5],
            success=bool(r[6]), created_at=r[7],
        )
        for r in rows
    ]


def stats(db_path: str = "data/gold_memory.db") -> dict[str, Any]:
    """返回 Gold Memory 统计信息。"""
    with sqlite3.connect(db_path) as conn:
        _ensure_table(conn)
        cur = conn.execute("SELECT COUNT(*), SUM(success) FROM gold_memory")
        row = cur.fetchone()
        total = row[0] or 0
        success = row[1] or 0
        return {
            "total_entries": total,
            "successful": success,
            "failed": total - success,
            "success_rate": success / total if total > 0 else 0,
        }
