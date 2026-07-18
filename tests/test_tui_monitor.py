"""M139-B · 全屏 TUI 监控台 headless 单测（Textual run_test + pilot，确定性）。

全部用例使用 tmp 路径 DB（经 FLIPPED_DB env 注入），不触碰真实 data/。
TUI 为只读观察者：断言渲染结果，绝不断言/依赖写入副作用。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402
from textual.widgets import DataTable  # noqa: E402

from driving import factory_loop  # noqa: E402
from driving.db import connect  # noqa: E402
from driving.event_log import append_event, ensure_event_table  # noqa: E402
from tui.app import EventLog, FactoryMonitorApp  # noqa: E402


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td) / "flipped.db"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_factory(db_path: Path, factory_id: str = "f1", *, status: str = "running",
                  roadmap: int = 2, completed: int = 1, failed: int = 0) -> None:
    """用真实建表函数 + 原始 INSERT 种一行 factory_states。"""
    with connect(str(db_path)) as conn:
        factory_loop._ensure_table(conn)  # factory_states + factory_events（真实 DDL）
        now = _utc_now()
        conn.execute(
            """
            INSERT INTO factory_states (
                factory_id, product_goal, cwd, status, roadmap_json,
                completed_json, failed_json, context_summary,
                iteration_count, max_tasks, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                factory_id, "goal", "/tmp", status,
                json.dumps([{"id": f"t{i}"} for i in range(roadmap)]),
                json.dumps([{"id": f"t{i}"} for i in range(completed)]),
                json.dumps([{"id": f"x{i}"} for i in range(failed)]),
                "", 0, 10, now, now,
            ),
        )


def _seed_events(db_path: Path, factory_id: str, kinds: list[str]) -> None:
    with connect(str(db_path)) as conn:
        ensure_event_table(conn)
        for kind in kinds:
            append_event(conn, factory_id, kind, {"info": kind})


def _run_app(app: FactoryMonitorApp, body) -> None:
    """同步包装 run_test：body(app, pilot) 为 async 回调。"""
    async def _runner() -> None:
        async with app.run_test() as pilot:
            await body(app, pilot)

    asyncio.run(_runner())


def _log_lines(app: FactoryMonitorApp) -> list[str]:
    log = app.query_one("#events", EventLog)
    return [line for line in log.lines if line.strip()]


# ---------- 场景 1：空库空态 ----------


def test_missing_db_shows_no_factories_and_no_crash(tmp_db, monkeypatch):
    """DB 文件不存在：DataTable 显示 No factories found，Log 为空，不抛异常。"""
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))  # 文件不创建
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        table = app.query_one("#states", DataTable)
        assert table.row_count == 1
        assert str(table.get_row_at(0)[0]) == "No factories found"
        assert _log_lines(app) == []

    _run_app(app, body)
    assert not tmp_db.exists(), "TUI 不得因轮询而创建 DB 文件（只读观察者）"


def test_empty_db_file_shows_no_factories(tmp_db, monkeypatch):
    """DB 为 0 字节空文件：同样显示 No factories found，不抛异常。"""
    tmp_db.touch()
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        table = app.query_one("#states", DataTable)
        assert table.row_count == 1
        assert str(table.get_row_at(0)[0]) == "No factories found"
        assert _log_lines(app) == []

    _run_app(app, body)


# ---------- 场景 2：写入事件后渲染 ----------


def test_seeded_state_and_events_render(tmp_db, monkeypatch):
    _seed_factory(tmp_db)
    _seed_events(tmp_db, "f1", ["factory_start", "task_done"])
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        text = "\n".join(_log_lines(app))
        assert "factory_start" in text
        assert "task_done" in text
        table = app.query_one("#states", DataTable)
        assert table.row_count == 1
        row = [str(c) for c in table.get_row_at(0)]
        assert row[0] == "f1"
        assert row[1] == "running"
        assert row[2] == "1/0/2"  # done/failed/total

    _run_app(app, body)


# ---------- 场景 3：after_seq 增量不重复 ----------


def test_second_poll_adds_no_duplicate_events(tmp_db, monkeypatch):
    _seed_factory(tmp_db)
    _seed_events(tmp_db, "f1", ["factory_start", "task_done"])
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        assert len(_log_lines(app)) == 2
        app._poll()  # 无新事件 → 不重复追加
        assert len(_log_lines(app)) == 2

    _run_app(app, body)


def test_incremental_poll_picks_up_only_new_events(tmp_db, monkeypatch):
    _seed_factory(tmp_db)
    _seed_events(tmp_db, "f1", ["factory_start"])
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        assert len(_log_lines(app)) == 1
        _seed_events(tmp_db, "f1", ["task_start", "task_done"])  # 轮询间隙写入
        app._poll()
        lines = _log_lines(app)
        assert len(lines) == 3
        assert "task_start" in lines[1]
        assert "task_done" in lines[2]

    _run_app(app, body)


# ---------- 场景 4：畸形 payload 不崩 ----------


def test_broken_payload_json_does_not_crash(tmp_db, monkeypatch):
    _seed_factory(tmp_db)
    with connect(str(tmp_db)) as conn:
        ensure_event_table(conn)
        append_event(conn, "f1", "factory_start", {"ok": 1})
        # 绕过 append_event 的 json.dumps，直接写无效 JSON
        conn.execute(
            "INSERT INTO factory_events (factory_id, ts, kind, payload_json) "
            "VALUES (?, ?, ?, ?)",
            ("f1", _utc_now(), "task_done", "{broken"),
        )
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()  # 不抛异常
        text = "\n".join(_log_lines(app))
        assert "factory_start" in text, "正常事件仍显示"
        assert "task_done" in text, "畸形 payload 事件按 kind 降级显示"

    _run_app(app, body)


# ---------- 场景 5：暂停 / 恢复 ----------


def test_pause_and_resume_polling(tmp_db, monkeypatch):
    _seed_factory(tmp_db)
    _seed_events(tmp_db, "f1", ["factory_start"])
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        assert len(_log_lines(app)) == 1

        await pilot.press("p")  # 暂停
        await pilot.pause()
        assert app.paused is True
        _seed_events(tmp_db, "f1", ["task_done"])
        app._poll()
        assert len(_log_lines(app)) == 1, "暂停中轮询必须跳过，Log 不更新"

        await pilot.press("p")  # 恢复
        await pilot.pause()
        assert app.paused is False
        app._poll()
        assert len(_log_lines(app)) == 2
        assert "task_done" in _log_lines(app)[-1]

    _run_app(app, body)


# ---------- 大量事件截断（保留最近 200 行） ----------


def test_log_truncates_to_max_lines(tmp_db, monkeypatch):
    _seed_factory(tmp_db)
    _seed_events(tmp_db, "f1", ["task_start"] * 210)
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        log = app.query_one("#events", EventLog)
        assert len(log.lines) == 200, "超过 max_lines 自动截断，保留最近 200 行"
        assert "task_start" in log.lines[-1]

    _run_app(app, body)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
