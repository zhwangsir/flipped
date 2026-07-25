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


# ---------- M144-B.1：事件时间线排序（HH:MM:SS 前缀 + 乱序按 ts 插入） ----------


def _seed_events_at(db_path: Path, rows: list[tuple[str, str, str]]) -> None:
    """直接 INSERT 指定 ts 的事件（append_event 不接受自定义 ts）。"""
    with connect(str(db_path)) as conn:
        ensure_event_table(conn)
        for factory_id, ts, kind in rows:
            conn.execute(
                "INSERT INTO factory_events (factory_id, ts, kind, payload_json) "
                "VALUES (?, ?, ?, ?)",
                (factory_id, ts, kind, json.dumps({"info": kind})),
            )


def test_event_lines_prefixed_with_hhmmss(tmp_db, monkeypatch):
    """M144-B.1a：事件行以 HH:MM:SS 时间戳前缀渲染（取事件行 ts 字段）。"""
    _seed_factory(tmp_db, "f1")
    _seed_events_at(tmp_db, [("f1", "2026-07-19T08:09:10+00:00", "factory_start")])
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        lines = _log_lines(app)
        assert len(lines) == 1
        assert lines[0].startswith("08:09:10 "), "事件行应以 HH:MM:SS 前缀开头"
        assert "[factory_start]" in lines[0]

    _run_app(app, body)


def test_out_of_order_events_sorted_by_ts(tmp_db, monkeypatch):
    """M144-B.1b：多厂事件交织到达时按事件 ts 有序插入，而非纯追加序。

    数据布局：f1 在前（updated_at 更新），其事件 ts 晚；f2 在后，其事件 ts 早。
    轮询先 drain f1 追加晚事件，f2 的早事件必须插入到它前面。
    """
    _seed_factory(tmp_db, "f1")
    _seed_factory(tmp_db, "f2")
    # f1 的事件 ts 晚（10:00:09），f2 的事件 ts 早（10:00:01）
    _seed_events_at(tmp_db, [("f1", "2026-07-19T10:00:09+00:00", "task_done")])
    _seed_events_at(tmp_db, [("f2", "2026-07-19T10:00:01+00:00", "factory_start")])
    _fix_row_order(tmp_db, "f1", "f2")  # f1 在前 → 先被 drain（追加序 vs ts 序相反）
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        lines = _log_lines(app)
        assert len(lines) == 2
        assert lines[0].startswith("10:00:01"), "ts 早的事件（f2 factory_start）应排在前面"
        assert " f2 " in lines[0]
        assert lines[1].startswith("10:00:09")
        assert " f1 " in lines[1]

    _run_app(app, body)


def test_event_missing_ts_appends_in_arrival_order(tmp_db, monkeypatch):
    """M144-B.1c：事件缺 ts 时 fail-open 退化为到达序排尾，不崩不排序。"""
    _seed_factory(tmp_db, "f1")
    _seed_factory(tmp_db, "f2")
    _seed_events_at(tmp_db, [("f1", "2026-07-19T11:00:05+00:00", "task_done")])
    _seed_events_at(tmp_db, [("f2", "", "factory_start")])  # 空 ts（缺 ts 退化场景）
    _fix_row_order(tmp_db, "f1", "f2")
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        lines = _log_lines(app)
        assert len(lines) == 2
        assert lines[0].startswith("11:00:05"), "带 ts 事件按 ts 序在前"
        assert "factory_start" in lines[1], "缺 ts 事件到达序排尾（fail-open）"
        assert " f2 " in lines[1]

    _run_app(app, body)


# ---------- M144-B.2：状态过滤快捷键（1/2/3/4 过滤，0 恢复全部） ----------


def _seed_four_statuses(db_path: Path) -> None:
    _seed_factory(db_path, "f-run", status="running")
    _seed_factory(db_path, "f-done", status="done", roadmap=2, completed=2)
    _seed_factory(db_path, "f-fail", status="failed", failed=1)
    _seed_factory(db_path, "f-pause", status="paused")


def _table_factory_ids(app: FactoryMonitorApp) -> list[str]:
    table = app.query_one("#states", DataTable)
    return [str(table.get_row_at(i)[0]) for i in range(table.row_count)]


def test_status_filter_keys_filter_rows(tmp_db, monkeypatch):
    """M144-B.2a：按 1/2/3 只显示对应状态的行，行数正确。"""
    _seed_four_statuses(tmp_db)
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        assert len(_table_factory_ids(app)) == 4

        await pilot.press("1")  # running
        await pilot.pause()
        assert _table_factory_ids(app) == ["f-run"]
        assert app.status_filter == "running"

        await pilot.press("2")  # done
        await pilot.pause()
        assert _table_factory_ids(app) == ["f-done"]
        assert app.status_filter == "done"

        await pilot.press("3")  # failed
        await pilot.pause()
        assert _table_factory_ids(app) == ["f-fail"]
        assert app.status_filter == "failed"

    _run_app(app, body)


def test_filter_zero_restores_all_rows(tmp_db, monkeypatch):
    """M144-B.2b：过滤后按 0 恢复显示全部行，标识清除。"""
    _seed_four_statuses(tmp_db)
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        await pilot.press("4")  # paused
        await pilot.pause()
        assert _table_factory_ids(app) == ["f-pause"]
        await pilot.press("0")  # 全部
        await pilot.pause()
        assert len(_table_factory_ids(app)) == 4
        assert app.status_filter is None
        assert "过滤" not in app.sub_title, "全部时不显示过滤标识"

    _run_app(app, body)


def test_subtitle_shows_filter_tag(tmp_db, monkeypatch):
    """M144-B.2c：过滤器激活时 sub_title 聚合统计后追加 `| 过滤:xxx`。"""
    _seed_four_statuses(tmp_db)
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        await pilot.press("1")
        await pilot.pause()
        sub = app.sub_title
        assert "4 工厂" in sub, "聚合统计仍覆盖全部工厂"
        assert "running 1" in sub
        assert "过滤:running" in sub, "激活过滤器后追加标识"

    _run_app(app, body)


def test_filter_combines_with_focus(tmp_db, monkeypatch):
    """M144-B.2d：过滤与 Enter 聚焦正交叠加，过滤器在 _poll 重拉后保持。"""
    _seed_factory(tmp_db, "f1", status="running")
    _seed_factory(tmp_db, "f2", status="running")
    _seed_factory(tmp_db, "f3", status="done", roadmap=2, completed=2)
    _seed_events(tmp_db, "f1", ["factory_start", "task_start"])
    _seed_events(tmp_db, "f3", ["factory_start"])
    _fix_row_order(tmp_db, "f1", "f2", "f3")
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        await pilot.press("1")  # 过滤 running：f1, f2 可见，f3 隐藏
        await pilot.pause()
        visible = _table_factory_ids(app)
        assert set(visible) == {"f1", "f2"}
        assert visible[0] == "f1", "cursor 应落在过滤后的首行 f1"

        await pilot.press("enter")  # 聚焦 cursor 行（过滤后行序的 f1）
        await pilot.pause()
        assert app.focus_factory == "f1"
        assert app.status_filter == "running", "聚焦不改变过滤器（正交叠加）"
        assert "过滤:running" in app.sub_title
        lines = _log_lines(app)
        assert len(lines) == 2 and all(" f1 " in line for line in lines), "聚焦事件过滤仍生效"

        _seed_events(tmp_db, "f2", ["task_done"])
        _seed_events(tmp_db, "f1", ["task_done"])
        app._poll()  # 重拉后过滤器保持
        assert app.status_filter == "running"
        assert set(_table_factory_ids(app)) == {"f1", "f2"}, "过滤器在轮询重拉后保持"
        assert len(_log_lines(app)) == 3, "聚焦厂新事件正常显示，他厂事件仍只推进 seq"

    _run_app(app, body)


# ---------- M144-B.3：搜索跳转（/ 前缀匹配 → Enter 聚焦 / Esc 取消） ----------


def test_search_prefix_moves_cursor(tmp_db, monkeypatch):
    """M144-B.3a：/ 进入搜索，实时前缀匹配 factory_id（大小写不敏感），cursor 跳首个匹配行。"""
    _seed_factory(tmp_db, "Alpha")
    _seed_factory(tmp_db, "beta")
    _seed_factory(tmp_db, "Alpine")
    _fix_row_order(tmp_db, "Alpha", "beta", "Alpine")
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        table = app.query_one("#states", DataTable)
        assert table.cursor_row == 0

        await pilot.press("slash")  # 进入搜索
        await pilot.pause()
        assert app.search_active is True
        assert "搜索" in app.sub_title

        await pilot.press("a", "l", "p", "i")  # 前缀 "alpi" 匹配 Alpine（大小写不敏感）
        await pilot.pause()
        assert app.search_query == "alpi"
        assert table.cursor_row == 2, "cursor 应跳到首个大小写不敏感前缀匹配行 Alpine"
        assert "搜索:alpi" in app.sub_title

        await pilot.press("backspace")  # 前缀 "alp" → 首个匹配回到 Alpha
        await pilot.pause()
        assert app.search_query == "alp"
        assert table.cursor_row == 0

    _run_app(app, body)


def test_search_enter_confirms_focus(tmp_db, monkeypatch):
    """M144-B.3b：搜索中 Enter 确认并复用聚焦机制聚焦匹配厂，退出搜索模式。"""
    _seed_factory(tmp_db, "Alpha")
    _seed_factory(tmp_db, "beta")
    _seed_events(tmp_db, "beta", ["factory_start"])
    _fix_row_order(tmp_db, "Alpha", "beta")
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        await pilot.press("slash", "b", "e", "t")
        await pilot.pause()
        assert app.search_active is True

        await pilot.press("enter")  # 确认 → 聚焦 beta
        await pilot.pause()
        assert app.search_active is False, "Enter 确认后退出搜索模式"
        assert app.search_query == ""
        assert app.focus_factory == "beta", "Enter 确认复用聚焦机制"
        assert "beta" in app.sub_title
        lines = _log_lines(app)
        assert len(lines) == 1 and "beta" in lines[0], "聚焦后事件区重拉该厂历史"

    _run_app(app, body)


def test_search_escape_cancels_and_clears(tmp_db, monkeypatch):
    """M144-B.3c：搜索中 Esc 取消搜索并清空前缀，不触发聚焦/取消聚焦。"""
    _seed_factory(tmp_db, "Alpha")
    _seed_factory(tmp_db, "beta")
    _fix_row_order(tmp_db, "Alpha", "beta")
    monkeypatch.setenv("FLIPPED_DB", str(tmp_db))
    app = FactoryMonitorApp()

    async def body(app, pilot):
        await pilot.pause()
        app._poll()
        await pilot.press("slash", "b", "e")
        await pilot.pause()
        table = app.query_one("#states", DataTable)
        assert table.cursor_row == 1
        assert app.search_query == "be"

        await pilot.press("escape")  # 取消搜索
        await pilot.pause()
        assert app.search_active is False
        assert app.search_query == ""
        assert "搜索" not in app.sub_title
        assert app.focus_factory is None, "Esc 取消搜索不得触发聚焦"

    _run_app(app, body)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
