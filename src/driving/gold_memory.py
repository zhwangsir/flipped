"""Gold Memory 自学习机制（M10.4-D）。

让系统越跑越快：把每轮成功任务的 (prompt 模式, verify_cmd 模式, 设计风格)
沉淀成 Gold Memory，下次遇到类似任务时直接复用。

Gold Memory 是一张 SQLite 持久化的"经验表"：
- 任务描述的关键词签名
- 使用的 design_style
- 成功的 verify_cmd 模式
- 成功率统计
- 最近一次成功的 feedback/planner 调整

查询时按关键词签名 + 设计风格做模糊匹配，返回 Top-K 最相关的经验。
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
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
    UNIQUE(task_signature, design_style, verify_cmd)
)
"""

_INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_gold_sig ON gold_memory(task_signature)"


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_TABLE_SQL)
    conn.execute(_INDEX_SQL)


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
    """记录一个任务结果到 Gold Memory。"""
    sig = _signature(task.description)
    verify_cmd_str = " ".join(task.verify_cmd) if task.verify_cmd else "true"
    with sqlite3.connect(db_path) as conn:
        _ensure_table(conn)
        conn.execute(
            """
            INSERT INTO gold_memory (
                task_signature, design_style, description, verify_cmd,
                stop_reason, summary, success, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_signature, design_style, verify_cmd) DO UPDATE SET
                stop_reason=excluded.stop_reason,
                summary=excluded.summary,
                success=excluded.success,
                created_at=excluded.created_at
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
            ),
        )


def query_similar(
    description: str,
    design_style: str = "auto",
    db_path: str = "data/gold_memory.db",
    limit: int = 5,
) -> GoldQueryResult:
    """查询相似任务的历史经验。

    返回该任务签名 + 设计风格下的成功率 + 推荐的 verify_cmd。
    """
    sig = _signature(description)
    with sqlite3.connect(db_path) as conn:
        _ensure_table(conn)
        # design_style 匹配：精确匹配 OR 有一方是 auto（宽松匹配，让经验跨风格复用）
        cur = conn.execute(
            """
            SELECT verify_cmd, success, stop_reason, summary, design_style
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
