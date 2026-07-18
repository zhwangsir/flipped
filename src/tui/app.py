"""M139-B · FactoryMonitorApp —— factory_states / factory_events 的全屏 TUI 监控台。

布局：Header（标题）→ DataTable（工厂状态，居中 1fr）→ EventLog（事件流，底部）→ Footer。
轮询：每 1s 一次 `_poll`（`p` 暂停/恢复，`q` 退出）。

只读纪律：
- DB 文件不存在时不 connect（sqlite3.connect 会顺手创建空文件），直接显示空态；
- 除 `ensure_event_table` 的幂等 DDL 外不写任何数据；
- 一切读取 fail-open，DB 缺失/空表/畸形 payload 都不允许让监控台崩掉。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3

from rich.highlighter import Highlighter
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Log

from driving.db import connect, default_db_path
from driving.event_log import ensure_event_table, list_events

POLL_INTERVAL = 1.0
MAX_LOG_LINES = 200

KIND_COLORS = {
    "factory_start": "green",
    "task_start": "blue",
    "task_done": "cyan",
    "verify_result": "yellow",
    "infra_failure": "red",
}

_KIND_RE = re.compile(r"\[(\w+)\]")

STATE_COLUMNS = ("factory_id", "status", "tasks (done/failed/total)", "updated_at")


class _KindHighlighter(Highlighter):
    """按事件行内的 [kind] 标签给整行着色；未知 kind 不着色。"""

    def highlight(self, text: Text) -> None:
        match = _KIND_RE.search(text.plain)
        if match:
            color = KIND_COLORS.get(match.group(1))
            if color:
                text.stylize(color)


class EventLog(Log):
    """带 kind 着色的滚动事件日志；max_lines 截断防内存膨胀。"""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("highlight", True)
        kwargs.setdefault("max_lines", MAX_LOG_LINES)
        super().__init__(*args, **kwargs)
        self.highlighter = _KindHighlighter()


def _json_list(raw: str | None) -> list:
    """宽松解析 JSON 数组列；畸形/非数组一律降级为空列表。"""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return value if isinstance(value, list) else []


class FactoryMonitorApp(App):
    """Flipped Factory Monitor：统一 SQLite 库的全屏只读监控台。"""

    CSS_PATH = None
    DEFAULT_CSS = """
    #states {
        height: 1fr;
    }
    #events {
        height: 40%;
        border-top: heavy $primary;
    }
    """

    TITLE = "Flipped Factory Monitor"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("p", "toggle_pause", "Pause"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.paused = False
        self._last_seq: dict[str, int] = {}

    # ---------- 布局 ----------

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="states")
        yield EventLog(id="events")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#states", DataTable).add_columns(*STATE_COLUMNS)
        self._poll()
        self.set_interval(POLL_INTERVAL, self._poll)

    # ---------- 动作 ----------

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused

    # ---------- 轮询 ----------

    def _poll(self) -> None:
        """刷新状态表 + 增量事件流。fail-open：任何异常都不得让 TUI 崩掉。"""
        if self.paused:
            return
        db_path = default_db_path()
        if not os.path.exists(db_path):
            # 不 connect：避免 sqlite3.connect 顺手创建空文件（只读观察者纪律）
            self._refresh_states([])
            return
        try:
            conn = connect(db_path)
        except sqlite3.Error:
            self._refresh_states([])
            return
        try:
            try:
                ensure_event_table(conn)
            except sqlite3.Error:
                pass
            states = self._read_states(conn)
            self._refresh_states(states)
            for state in states:
                self._drain_events(conn, state["factory_id"])
        finally:
            conn.close()

    def _read_states(self, conn: sqlite3.Connection) -> list[dict]:
        try:
            cur = conn.execute(
                "SELECT factory_id, status, roadmap_json, completed_json, "
                "failed_json, updated_at FROM factory_states "
                "ORDER BY updated_at DESC"
            )
            rows = cur.fetchall()
        except sqlite3.Error:
            return []  # 表不存在等 → 空态
        states = []
        for factory_id, status, roadmap_json, completed_json, failed_json, updated_at in rows:
            states.append({
                "factory_id": factory_id,
                "status": status,
                "done": len(_json_list(completed_json)),
                "failed": len(_json_list(failed_json)),
                "total": len(_json_list(roadmap_json)),
                "updated_at": updated_at or "",
            })
        return states

    def _refresh_states(self, states: list[dict]) -> None:
        table = self.query_one("#states", DataTable)
        table.clear()
        if not states:
            table.add_row("No factories found", "", "", "")
            return
        for s in states:
            table.add_row(
                s["factory_id"],
                s["status"],
                f"{s['done']}/{s['failed']}/{s['total']}",
                s["updated_at"],
            )

    def _drain_events(self, conn: sqlite3.Connection, factory_id: str) -> None:
        last = self._last_seq.get(factory_id, 0)
        events = list_events(conn, factory_id, after_seq=last)
        if not events:
            return
        log = self.query_one("#events", EventLog)
        log.write_lines(self._format_event(factory_id, e) for e in events)
        self._last_seq[factory_id] = events[-1]["seq"]  # list_events 按 seq 升序

    @staticmethod
    def _format_event(factory_id: str, event: dict) -> str:
        ts = str(event.get("ts") or "")[:19]
        kind = str(event.get("kind") or "?")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        summary = ", ".join(
            f"{k}={v}" for k, v in sorted(payload.items())
            if isinstance(v, (str, int, float, bool))
        )
        return f"{ts} [{kind}] {factory_id} {summary}".rstrip()


def main() -> None:
    FactoryMonitorApp().run()


if __name__ == "__main__":
    main()
