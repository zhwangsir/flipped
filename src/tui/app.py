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
FOCUS_RELOAD_LIMIT = 50  # M140.2：聚焦时重拉该厂最近 N 条历史

KIND_COLORS = {
    "factory_start": "green",
    "task_start": "blue",
    "task_done": "cyan",
    "verify_result": "yellow",
    "infra_failure": "red",
}

# M140.1 · 状态着色映射（DataTable status 列）
STATUS_COLORS = {
    "done": "green",
    "running": "dodger_blue1",
    "failed": "red",
    "paused": "yellow",
}

_KIND_RE = re.compile(r"\[(\w+)\]")

STATE_COLUMNS = ("factory_id", "status", "progress", "tasks (done/failed/total)", "updated_at")


def _progress_bar(done: int, failed: int, total: int, width: int = 10) -> Text:
    """任务进度块条：done=绿块 / failed=红块 / pending=暗块 + 完成百分比。

    total<=0（roadmap 为空）时返回占位条，不除零。
    """
    if total <= 0:
        return Text("░" * width + "  —", style="dim")
    done_cells = min(int(done / total * width), width)
    failed_cells = min(int(failed / total * width), width - done_cells)
    pending = max(width - done_cells - failed_cells, 0)
    pct = int(done / total * 100)
    bar = Text()
    if done_cells:
        bar.append("█" * done_cells, style="green")
    if failed_cells:
        bar.append("█" * failed_cells, style="red")
    if pending:
        bar.append("░" * pending, style="dim")
    bar.append(f" {pct}%")
    return bar


def _status_text(status: str) -> Text:
    """按 STATUS_COLORS 给状态着色；未知状态不着色（fail-open）。"""
    return Text(status or "", style=STATUS_COLORS.get(status, ""))


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
        ("escape", "clear_focus", "Unfocus"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.paused = False
        self._last_seq: dict[str, int] = {}
        self._states: list[dict] = []  # 最近一次轮询的状态快照（供聚焦按行号取 factory_id / M140.3 聚合）
        self.focus_factory: str | None = None  # M140.2：聚焦中的工厂；None = 全部显示

    # ---------- 布局 ----------

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="states", cursor_type="row", zebra_stripes=True)
        yield EventLog(id="events")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#states", DataTable).add_columns(*STATE_COLUMNS)
        self._poll()
        self.set_interval(POLL_INTERVAL, self._poll)

    # ---------- 动作 ----------

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused

    # ---------- M140.2 · 工厂聚焦 ----------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter 聚焦 cursor 行工厂；已聚焦时再按 Enter 取消（toggle）。"""
        if self.focus_factory is not None:
            self._set_focus(None)
            return
        row = event.cursor_row
        if 0 <= row < len(self._states):
            self._set_focus(self._states[row]["factory_id"])

    def action_clear_focus(self) -> None:
        """Esc 取消聚焦。"""
        if self.focus_factory is not None:
            self._set_focus(None)

    def _set_focus(self, factory_id: str | None) -> None:
        self.focus_factory = factory_id
        if factory_id is not None:
            self._reload_focus_events(factory_id)
        self._update_subtitle()

    def _reload_focus_events(self, factory_id: str) -> None:
        """聚焦切换：清空事件区并重拉该厂最近 N 条。只读，fail-open；不动 _last_seq。"""
        log = self.query_one("#events", EventLog)
        log.clear()
        db_path = default_db_path()
        if not os.path.exists(db_path):
            return
        try:
            conn = connect(db_path)
        except sqlite3.Error:
            return
        try:
            events = list_events(conn, factory_id, after_seq=0)[-FOCUS_RELOAD_LIMIT:]
            log.write_lines(self._format_event(factory_id, e) for e in events)
        finally:
            conn.close()

    # ---------- M140.3 · Header 聚合统计 ----------

    def _update_subtitle(self) -> None:
        """sub_title：聚焦时显示聚焦厂；否则聚合 `N 工厂 · running X · done Y ...`（零计数省略）。"""
        if self.focus_factory is not None:
            self.sub_title = f"聚焦: {self.focus_factory}"
            return
        states = self._states
        if not states:
            self.sub_title = ""
            return
        counts: dict[str, int] = {}
        for s in states:
            counts[s["status"]] = counts.get(s["status"], 0) + 1
        parts = [f"{len(states)} 工厂"]
        for status in ("running", "done", "failed", "paused"):
            n = counts.get(status, 0)
            if n:
                parts.append(f"{status} {n}")
        self.sub_title = " · ".join(parts)

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
        self._states = states
        table = self.query_one("#states", DataTable)
        table.clear()
        if not states:
            table.add_row("No factories found", "", "", "", "")
            self._update_subtitle()
            return
        for s in states:
            table.add_row(
                s["factory_id"],
                _status_text(s["status"]),
                _progress_bar(s["done"], s["failed"], s["total"]),
                f"{s['done']}/{s['failed']}/{s['total']}",
                s["updated_at"],
            )
        self._update_subtitle()

    def _drain_events(self, conn: sqlite3.Connection, factory_id: str) -> None:
        last = self._last_seq.get(factory_id, 0)
        events = list_events(conn, factory_id, after_seq=last)
        if not events:
            return
        # M140.2：聚焦时只显示聚焦厂；他厂新事件仍推进 _last_seq（取消聚焦后不爆历史重放）
        if self.focus_factory is None or self.focus_factory == factory_id:
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
