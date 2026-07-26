"""M5 产线化真实验收 — factory 健康检测（heartbeat 主动监护核心）。

detect_stuck_factories 读 factory DB，识别两类产线风险：
1. 卡住的工厂：status=running 但 updated_at 超 stale_minutes（进程可能崩溃/僵死）
2. 可恢复的工厂：failed_json 含 stop_reason=circuit_breaker 的任务（可触发 resume）

设计为纯只读检测，不扰动产线。heartbeat.py 据此写"建议动作"通知。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from driving.factory_health import detect_stuck_factories


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _minutes_ago_iso(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _ensure_factory_table(conn: sqlite3.Connection) -> None:
    """建 factory_states 表（与 factory_loop._TABLE_SQL 一致的最小子集）。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS factory_states (
            factory_id TEXT PRIMARY KEY,
            product_goal TEXT NOT NULL,
            cwd TEXT NOT NULL,
            status TEXT NOT NULL,
            roadmap_json TEXT NOT NULL,
            completed_json TEXT NOT NULL,
            failed_json TEXT NOT NULL,
            current_task_id TEXT,
            context_summary TEXT NOT NULL,
            iteration_count INTEGER NOT NULL,
            max_tasks INTEGER NOT NULL,
            design_style TEXT NOT NULL DEFAULT 'auto',
            design_context TEXT NOT NULL DEFAULT '',
            rca_history_json TEXT NOT NULL DEFAULT '[]',
            current_worktree_id TEXT,
            cli_enabled INTEGER NOT NULL DEFAULT 1,
            cli_stats_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _insert_factory(
    conn: sqlite3.Connection,
    *,
    factory_id: str,
    product_goal: str = "test goal",
    cwd: str = "/tmp/test",
    status: str = "running",
    roadmap_json: str = "[]",
    failed_json: str = "[]",
    updated_at: str | None = None,
    created_at: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO factory_states (
            factory_id, product_goal, cwd, status, roadmap_json, completed_json,
            failed_json, current_task_id, context_summary, iteration_count,
            max_tasks, design_style, design_context, rca_history_json,
            current_worktree_id, cli_enabled, cli_stats_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, '', 0, 1, 'auto', '', '[]', NULL, 1, '{}', ?, ?)
        """,
        (
            factory_id,
            product_goal,
            cwd,
            status,
            roadmap_json,
            "[]",
            failed_json,
            created_at or _now_iso(),
            updated_at or _now_iso(),
        ),
    )
    conn.commit()


def _failed_json_with_circuit_breaker(task_id: str = "task-abc", summary: str = "verify failed") -> str:
    """构造 failed_json：含一条 stop_reason=circuit_breaker 的 TaskResult。"""
    return json.dumps(
        [
            {
                "task": {"id": task_id, "description": "test", "verify_cmd": [], "status": "failed",
                         "attempts": 3, "max_attempts": 3, "depends_on": [], "artifacts": [], "feedback": ""},
                "verified": False,
                "stop_reason": "circuit_breaker",
                "iteration": 3,
                "summary": summary,
                "recorded_at": _now_iso(),
            }
        ]
    )


def _failed_json_with_timeout() -> str:
    """构造 failed_json：stop_reason=task_timeout（非 circuit_breaker）。"""
    return json.dumps(
        [
            {
                "task": {"id": "task-to", "description": "test", "verify_cmd": [], "status": "failed",
                         "attempts": 1, "max_attempts": 3, "depends_on": [], "artifacts": [], "feedback": ""},
                "verified": False,
                "stop_reason": "task_timeout",
                "iteration": 1,
                "summary": "timed out",
                "recorded_at": _now_iso(),
            }
        ]
    )


class TestDetectStuckFactories:
    """detect_stuck_factories 行为测试。"""

    def test_empty_db_returns_empty(self, tmp_path):
        db = str(tmp_path / "f.db")
        with sqlite3.connect(db) as conn:
            _ensure_factory_table(conn)
        assert detect_stuck_factories(db_path=db) == []

    def test_running_factory_stale_updated_at_is_stuck(self, tmp_path):
        """status=running 且 updated_at 超 stale_minutes → 卡住信号。"""
        db = str(tmp_path / "f.db")
        with sqlite3.connect(db) as conn:
            _ensure_factory_table(conn)
            _insert_factory(
                conn,
                factory_id="fac-stale",
                status="running",
                updated_at=_minutes_ago_iso(120),  # 2 小时前
            )
        result = detect_stuck_factories(db_path=db, stale_minutes=30)
        assert len(result) == 1
        assert result[0]["factory_id"] == "fac-stale"
        assert result[0]["status"] == "running"
        assert "stale_updated_at" in result[0]["signals"]
        assert result[0]["minutes_since_update"] >= 120

    def test_running_factory_recent_updated_at_not_stuck(self, tmp_path):
        """status=running 且 updated_at 刚刚 → 不卡住（正常推进中）。"""
        db = str(tmp_path / "f.db")
        with sqlite3.connect(db) as conn:
            _ensure_factory_table(conn)
            _insert_factory(
                conn,
                factory_id="fac-fresh",
                status="running",
                updated_at=_minutes_ago_iso(2),  # 2 分钟前
            )
        result = detect_stuck_factories(db_path=db, stale_minutes=30)
        assert result == []

    def test_done_factory_not_stuck_even_if_stale(self, tmp_path):
        """status=done 的工厂即使 updated_at 很旧也不算卡住（已结束）。"""
        db = str(tmp_path / "f.db")
        with sqlite3.connect(db) as conn:
            _ensure_factory_table(conn)
            _insert_factory(
                conn,
                factory_id="fac-done",
                status="done",
                updated_at=_minutes_ago_iso(720),  # 12 小时前
            )
        result = detect_stuck_factories(db_path=db, stale_minutes=30)
        assert result == []

    def test_failed_circuit_breaker_is_recoverable_signal(self, tmp_path):
        """failed_json 含 stop_reason=circuit_breaker → 可恢复信号（即使 status 非 running）。"""
        db = str(tmp_path / "f.db")
        with sqlite3.connect(db) as conn:
            _ensure_factory_table(conn)
            _insert_factory(
                conn,
                factory_id="fac-cb",
                status="failed",
                failed_json=_failed_json_with_circuit_breaker(summary="APP_k vs APP_CONFIG 大小写"),
                updated_at=_minutes_ago_iso(5),  # 不算卡住
            )
        result = detect_stuck_factories(db_path=db, stale_minutes=30)
        assert len(result) == 1
        assert result[0]["factory_id"] == "fac-cb"
        assert "circuit_breaker_task" in result[0]["signals"]
        assert len(result[0]["circuit_breaker_tasks"]) == 1
        assert result[0]["circuit_breaker_tasks"][0]["stop_reason"] == "circuit_breaker"
        assert "APP_k" in result[0]["circuit_breaker_tasks"][0]["summary"]

    def test_failed_timeout_not_recoverable_signal(self, tmp_path):
        """failed_json 只有 task_timeout（非 circuit_breaker）→ 不算可恢复。"""
        db = str(tmp_path / "f.db")
        with sqlite3.connect(db) as conn:
            _ensure_factory_table(conn)
            _insert_factory(
                conn,
                factory_id="fac-to",
                status="failed",
                failed_json=_failed_json_with_timeout(),
                updated_at=_minutes_ago_iso(5),
            )
        result = detect_stuck_factories(db_path=db, stale_minutes=30)
        assert result == []

    def test_mixed_factories_only_stuck_returned(self, tmp_path):
        """混合场景：done + fresh-running + stale-running + circuit_breaker → 只返回后两者。"""
        db = str(tmp_path / "f.db")
        with sqlite3.connect(db) as conn:
            _ensure_factory_table(conn)
            _insert_factory(conn, factory_id="fac-done", status="done",
                            updated_at=_minutes_ago_iso(720))
            _insert_factory(conn, factory_id="fac-fresh", status="running",
                            updated_at=_minutes_ago_iso(2))
            _insert_factory(conn, factory_id="fac-stale", status="running",
                            updated_at=_minutes_ago_iso(90))
            _insert_factory(conn, factory_id="fac-cb", status="failed",
                            failed_json=_failed_json_with_circuit_breaker(),
                            updated_at=_minutes_ago_iso(5))
        result = detect_stuck_factories(db_path=db, stale_minutes=30)
        ids = {r["factory_id"] for r in result}
        assert ids == {"fac-stale", "fac-cb"}

    def test_stale_and_circuit_breaker_combined_signals(self, tmp_path):
        """同一工厂同时卡住 + 有 circuit_breaker → 两个信号都报。"""
        db = str(tmp_path / "f.db")
        with sqlite3.connect(db) as conn:
            _ensure_factory_table(conn)
            _insert_factory(
                conn,
                factory_id="fac-both",
                status="running",
                failed_json=_failed_json_with_circuit_breaker(),
                updated_at=_minutes_ago_iso(180),
            )
        result = detect_stuck_factories(db_path=db, stale_minutes=30)
        assert len(result) == 1
        assert "stale_updated_at" in result[0]["signals"]
        assert "circuit_breaker_task" in result[0]["signals"]
        assert result[0]["minutes_since_update"] >= 180

    def test_exception_returns_empty(self, monkeypatch, tmp_path):
        """DB 异常（文件不存在等）fail-open 返回 []，不阻塞心跳。"""
        result = detect_stuck_factories(db_path=str(tmp_path / "nonexistent.db"))
        assert result == []

    def test_default_db_path_uses_factory_default(self, tmp_path, monkeypatch):
        """db_path=None 时用 factory_loop.default_db_path()。"""
        db = str(tmp_path / "default.db")
        monkeypatch.setattr("driving.factory_loop.default_db_path", lambda: db)
        with sqlite3.connect(db) as conn:
            _ensure_factory_table(conn)
            _insert_factory(conn, factory_id="fac-default", status="running",
                            updated_at=_minutes_ago_iso(60))
        result = detect_stuck_factories(stale_minutes=30)
        assert len(result) == 1
        assert result[0]["factory_id"] == "fac-default"

    def test_running_task_in_roadmap_is_stuck_signal(self, tmp_path):
        """roadmap_json 含 status=running 的 task → running_task 信号（任务级卡住）。"""
        db = str(tmp_path / "f.db")
        roadmap = json.dumps(
            [
                {"id": "task-1", "description": "done task", "verify_cmd": [], "status": "done",
                 "attempts": 1, "max_attempts": 3, "depends_on": [], "artifacts": [], "feedback": ""},
                {"id": "task-2", "description": "stuck task", "verify_cmd": [], "status": "running",
                 "attempts": 2, "max_attempts": 3, "depends_on": [], "artifacts": [], "feedback": ""},
            ]
        )
        with sqlite3.connect(db) as conn:
            _ensure_factory_table(conn)
            _insert_factory(
                conn,
                factory_id="fac-running-task",
                status="running",
                roadmap_json=roadmap,
                updated_at=_minutes_ago_iso(5),  # 工厂级不算卡住
            )
        result = detect_stuck_factories(db_path=db, stale_minutes=30)
        assert len(result) == 1
        assert "running_task" in result[0]["signals"]
        assert "task-2" in result[0]["running_tasks"]
