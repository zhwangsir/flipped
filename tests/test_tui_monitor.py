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
from rich.text import Text  # noqa: E402
from textual.widgets import DataTable  # noqa: E402

from driving import factory_loop  # noqa: E402
from driving.db import connect  # noqa: E402
from driving.event_log import append_event, ensure_event_table  # noqa: E402
from tui.app import EventLog, FactoryMonitorApp, _progress_bar  # noqa: E402


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
        row = table.get_row_at(0)
        assert str(row[0]) == "f1"
        assert str(row[1]) == "running"
        assert row[1].style == "dodger_blue1", "running 状态应着蓝色（M140.1）"
        assert str(row[3]) == "1/0/2"  # done/failed/total（M140.1 新增 progress 列后索引后移）

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


# ---------- M140.1：状态着色 + 进度条 ----------


def test_progress_bar_rendering():
    """_progress_bar 纯函数：done 绿块 / failed 红块 / pending 暗块 + 百分比。"""
    bar = _progress_bar(done=1, failed=0, total=2, width=10)
    assert isinstance(bar, Text)
    assert bar.plain == "█████░░░░░ 50%"

    bar = _progress_bar(done=3, failed=1, total=4, width=10)
    assert "75%" in bar.plain
    # 含绿/红两种着色段
    styles = {span.style for span in bar._spans} if hasattr(bar, "_spans") else set()
    assert any("green" in str(s) for s in styles), "done 段应绿色"
    assert any("red" in str(s) for s in styles), "failed 段应红色"


def test_progress_bar_zero_total_placeholder():
    bar = _progress_bar(done=0, failed=0, total=0, width=10)
    assert "—" in bar.plain or "░" in bar.plain


def test_status_cell_colored_by_state(tmp_db, monkeypatch):
    """不同状态工厂在 DataTable 中按映射着色。"""
    _seed_factory(tmp_db, "f-done", status="done", roadmap=2, completed=2)
    _seed_factory(tmp_db, "f-failed", status="failed", roadmap=2, completed=0, failed=1)
    _seed_factory(tmp_db, "f-paused", status="paused", roadmap=2, completed=1)
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        table = app.query_one("#states", DataTable)
        styles = {}
        for i in range(table.row_count):
            row = table.get_row_at(i)
            styles[str(row[0])] = (str(row[1]), row[1].style)
        assert styles["f-done"] == ("done", "green")
        assert styles["f-failed"] == ("failed", "red")
        assert styles["f-paused"] == ("paused", "yellow")
        # 进度条列存在且为 Text
        row0 = table.get_row_at(0)
        assert hasattr(row0[2], "plain"), "progress 列应为 Text 对象"

    _run_app(app, body)


# ---------- M140.2：工厂聚焦过滤 ----------


def _fix_row_order(db_path: Path, *ordered_ids: str) -> None:
    """按传入顺序固定 factory_states 行序（updated_at DESC，早序号=更新）。"""
    with connect(str(db_path)) as conn:
        for i, fid in enumerate(ordered_ids):
            ts = f"2026-01-01T00:00:{20 - i:02d}+00:00"
            conn.execute(
                "UPDATE factory_states SET updated_at = ? WHERE factory_id = ?", (ts, fid)
            )


def test_focus_factory_filters_event_log(tmp_db, monkeypatch):
    """Enter 聚焦 cursor 行工厂：事件区清空重拉该厂历史，他厂新事件只推进 seq 不显示；Esc 恢复。"""
    _seed_factory(tmp_db, "f1")
    _seed_factory(tmp_db, "f2")
    _seed_events(tmp_db, "f1", ["factory_start", "task_start"])
    _seed_events(tmp_db, "f2", ["factory_start"])
    _fix_row_order(tmp_db, "f1", "f2")
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        assert len(_log_lines(app)) == 3  # f1×2 + f2×1 全显示

        await pilot.press("enter")  # cursor 在第一行（f1）→ 聚焦
        await pilot.pause()
        assert app.focus_factory == "f1"
        assert "f1" in app.sub_title
        lines = _log_lines(app)
        assert len(lines) == 2, "聚焦后重拉 f1 最近事件（factory_start/task_start）"
        assert all(" f1 " in line for line in lines), "聚焦后只显示 f1 事件"

        _seed_events(tmp_db, "f2", ["task_done"])  # 过滤期间他厂新事件
        app._poll()
        assert len(_log_lines(app)) == 2, "f2 新事件不显示"
        assert app._last_seq.get("f2", 0) > 1, "f2 事件仍推进 seq（取消聚焦后不爆历史重放）"

        _seed_events(tmp_db, "f1", ["task_done"])  # 聚焦厂新事件正常显示
        app._poll()
        assert len(_log_lines(app)) == 3
        assert "task_done" in _log_lines(app)[-1]

        await pilot.press("escape")  # 取消聚焦
        await pilot.pause()
        assert app.focus_factory is None
        _seed_events(tmp_db, "f2", ["verify_result"])
        app._poll()
        text = "\n".join(_log_lines(app))
        assert "verify_result" in text and " f2 " in text, "恢复后他厂新事件正常显示"

    _run_app(app, body)


def test_enter_toggles_focus_off(tmp_db, monkeypatch):
    """聚焦状态下再按 Enter 取消聚焦。"""
    _seed_factory(tmp_db, "f1")
    _seed_events(tmp_db, "f1", ["factory_start"])
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        await pilot.press("enter")
        await pilot.pause()
        assert app.focus_factory == "f1"
        await pilot.press("enter")
        await pilot.pause()
        assert app.focus_factory is None

    _run_app(app, body)


# ---------- M140.3：Header 聚合统计 ----------


def test_subtitle_aggregates_status_counts(tmp_db, monkeypatch):
    """sub_title 聚合：N 工厂 + 各状态计数（零计数省略）。"""
    _seed_factory(tmp_db, "f-run", status="running")
    _seed_factory(tmp_db, "f-done", status="done", roadmap=2, completed=2)
    _seed_factory(tmp_db, "f-fail", status="failed", failed=1)
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        sub = app.sub_title
        assert "3 工厂" in sub
        assert "running 1" in sub
        assert "done 1" in sub
        assert "failed 1" in sub
        assert "paused" not in sub, "零计数项应省略"

    _run_app(app, body)


def test_subtitle_restores_after_unfocus(tmp_db, monkeypatch):
    """聚焦→取消后，sub_title 从「聚焦: f1」恢复为聚合统计。"""
    _seed_factory(tmp_db, "f1")
    _seed_events(tmp_db, "f1", ["factory_start"])
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        await pilot.press("enter")
        await pilot.pause()
        assert "聚焦" in app.sub_title and "f1" in app.sub_title
        await pilot.press("escape")
        await pilot.pause()
        assert "1 工厂" in app.sub_title and "running 1" in app.sub_title

    _run_app(app, body)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
