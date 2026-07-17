"""M136-A · append-only 事件日志 + 幂等键（Temporal 风格崩溃恢复）。

factory_loop 已有 SQLite 快照 + resume，但崩溃恢复后 task 完成副作用
（context_summary / quality_history / memory 追加、外部记录器写入）会被重复执行——
因为没有事件日志记录"该副作用已应用"。本模块提供最小原语：

- `factory_events` 表：append-only，`seq` 自增主键，事件按 `(factory_id, seq)` 有序；
- `idempotency_key` UNIQUE 索引：同一 key 只写入一次（SQLite 唯一索引允许多个 NULL，
  无 key 的事件不受限）；
- 全部 fail-open：任何 DB 异常返回 None/False/[]，绝不抛进主流程。

设计决策：重复幂等键的 append 返回 None（INSERT OR IGNORE + rowcount 判定），
不抛异常、不返回已有 seq——调用方用 `seen_idempotency_key` 做"是否已应用"判断，
append 只负责"尽力记录"。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

EVENT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS factory_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    factory_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT
)
"""

_EVENT_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_factory_events_fid_seq
ON factory_events (factory_id, seq)
"""

_EVENT_IDEMPOTENCY_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_factory_events_idempotency
ON factory_events (idempotency_key)
"""


def ensure_event_table(conn: sqlite3.Connection) -> None:
    """幂等迁移：创建 factory_events 表 + 索引。可重复调用；旧库自动补齐。"""
    conn.execute(EVENT_TABLE_SQL)
    conn.execute(_EVENT_INDEX_SQL)
    conn.execute(_EVENT_IDEMPOTENCY_INDEX_SQL)


def append_event(
    conn: sqlite3.Connection,
    factory_id: str,
    kind: str,
    payload: dict,
    idempotency_key: str | None = None,
) -> int | None:
    """追加事件，返回新事件 seq。

    幂等键冲突（重复/崩溃重放）时返回 None，不抛异常、不插重复行。
    任何 DB 异常 fail-open 返回 None。
    """
    try:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO factory_events
                (factory_id, ts, kind, payload_json, idempotency_key)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                factory_id,
                datetime.now(timezone.utc).isoformat(),
                kind,
                json.dumps(payload or {}, ensure_ascii=False, default=str),
                idempotency_key,
            ),
        )
        if cur.rowcount == 0:
            return None  # 幂等键已存在（崩溃重放去重）
        return int(cur.lastrowid)
    except Exception:  # noqa: BLE001
        return None


def seen_idempotency_key(conn: sqlite3.Connection, key: str) -> bool:
    """幂等键是否已存在。fail-open：出错返回 False（退化为旧路径，副作用照常应用）。"""
    if not key:
        return False
    try:
        cur = conn.execute(
            "SELECT 1 FROM factory_events WHERE idempotency_key = ? LIMIT 1",
            (key,),
        )
        return cur.fetchone() is not None
    except Exception:  # noqa: BLE001
        return False


def list_events(
    conn: sqlite3.Connection,
    factory_id: str,
    after_seq: int = 0,
) -> list[dict]:
    """按 seq 顺序列出 factory 的事件（`after_seq` 之后，供增量读取）。fail-open 返回 []。"""
    try:
        cur = conn.execute(
            """
            SELECT seq, factory_id, ts, kind, payload_json, idempotency_key
            FROM factory_events
            WHERE factory_id = ? AND seq > ?
            ORDER BY seq ASC
            """,
            (factory_id, after_seq),
        )
        events: list[dict] = []
        for row in cur.fetchall():
            try:
                payload = json.loads(row[4])
            except Exception:  # noqa: BLE001
                payload = {}
            events.append({
                "seq": row[0],
                "factory_id": row[1],
                "ts": row[2],
                "kind": row[3],
                "payload": payload,
                "idempotency_key": row[5],
            })
        return events
    except Exception:  # noqa: BLE001
        return []
