"""M139-B · FactoryMonitorApp —— factory_states / factory_events 的全屏 TUI 监控台。

布局：Header（标题）→ DataTable（工厂状态，居中 1fr）→ EventLog（事件流，底部）→ Footer。
轮询：每 1s 一次 `_poll`（`p` 暂停/恢复，`q` 退出）。

M144-B 三件套：
- 事件时间线排序：事件行 HH:MM:SS 前缀，多厂事件按 ts 有序插入（缺 ts 退化为到达序排尾）；
- 状态过滤：`1`running/`2`done/`3`failed/`4`paused/`0`全部，与聚焦正交叠加；
- 搜索跳转：`/` 进入搜索，实时前缀匹配 factory_id 跳 cursor，Enter 确认聚焦，Esc 取消。

只读纪律：
- DB 文件不存在时不 connect（sqlite3.connect 会顺手创建空文件），直接显示空态；
- 除 `ensure_event_table` 的幂等 DDL 外不写任何数据；
- 一切读取 fail-open，DB 缺失/空表/畸形 payload 都不允许让监控台崩掉。
"""
from __future__ import annotations

import bisect
import json
import os
import re
import sqlite3

from rich.highlighter import Highlighter
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Log

from driving.db import connect, default_db_path
from driving.event_log import ensure_event_table, list_events

POLL_INTERVAL = 1.0
MAX_LOG_LINES = 200
FOCUS_RELOAD_LIMIT = 50  # M140.2：聚焦时重拉该厂最近 N 条历史
_MISSING_TS_SORT_KEY = "\uffff"  # M144-B.1：缺 ts 事件排序键恒排尾（退化为到达序）

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


def _hhmmss(ts: str) -> str:
    """从 ISO 时间戳取 HH:MM:SS 显示前缀；缺失/过短 fail-open 为占位符。"""
    if ts and len(ts) >= 19:
        return ts[11:19]
    return "--:--:--"


def _event_sort_key(event: dict) -> str:
    """事件排序键：ts 字符串（ISO 字典序=时序）；缺 ts 用哨兵值恒排尾。"""
    ts = str(event.get("ts") or "")
    return ts if ts else _MISSING_TS_SORT_KEY


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
        ("slash", "search", "Search"),
        ("1", "filter_running", "Running"),
        ("2", "filter_done", "Done"),
        ("3", "filter_failed", "Failed"),
        ("4", "filter_paused", "Paused"),
        ("0", "filter_all", "All"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.paused = False
        self._last_seq: dict[str, int] = {}
        self._states: list[dict] = []  # 最近一次轮询的状态快照（全量，供 M140.3 聚合）
        self._visible_states: list[dict] = []  # 状态过滤后的可见行（Enter 聚焦按行号索引它）
        self.focus_factory: str | None = None  # M140.2：聚焦中的工厂；None = 全部显示
        # M144-B.1：事件时间线缓冲 (sort_key, seq, line)，与 Log 显示内容保持同步
        self._event_buffer: list[tuple[str, int, str]] = []
        self.status_filter: str | None = None  # M144-B.2：None = 全部
        self.search_active: bool = False  # M144-B.3：搜索模式
        self.search_query: str = ""

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
        """Enter：搜索态确认聚焦匹配厂；否则聚焦 cursor 行工厂（已聚焦再按取消）。"""
        if self.search_active:
            self._confirm_search()
            return
        if self.focus_factory is not None:
            self._set_focus(None)
            return
        row = event.cursor_row
        if 0 <= row < len(self._visible_states):
            self._set_focus(self._visible_states[row]["factory_id"])

    def action_clear_focus(self) -> None:
        """Esc：搜索态优先取消搜索；否则取消聚焦。"""
        if self.search_active:
            self._cancel_search()
            return
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
        self._event_buffer = []
        db_path = default_db_path()
        if not os.path.exists(db_path):
            return
        try:
            conn = connect(db_path)
        except sqlite3.Error:
            return
        try:
            events = list_events(conn, factory_id, after_seq=0)[-FOCUS_RELOAD_LIMIT:]
            entries = sorted(
                (
                    _event_sort_key(e),
                    int(e.get("seq") or 0),
                    self._format_event(factory_id, e),
                )
                for e in events
            )
            self._event_buffer = entries[-MAX_LOG_LINES:]
            log.write_lines(line for _, _, line in self._event_buffer)
        finally:
            conn.close()

    # ---------- M144-B.2 · 状态过滤 ----------

    def action_filter_running(self) -> None:
        self._set_status_filter("running")

    def action_filter_done(self) -> None:
        self._set_status_filter("done")

    def action_filter_failed(self) -> None:
        self._set_status_filter("failed")

    def action_filter_paused(self) -> None:
        self._set_status_filter("paused")

    def action_filter_all(self) -> None:
        self._set_status_filter(None)

    def _set_status_filter(self, status: str | None) -> None:
        """切换状态过滤器并用最近快照重绘表格；过滤器跨轮询保持。"""
        self.status_filter = status
        self._refresh_states(self._states)

    # ---------- M144-B.3 · 搜索跳转 ----------

    def action_search(self) -> None:
        """`/` 进入搜索模式：清空前缀，等待 on_key 逐字累积。"""
        self.search_active = True
        self.search_query = ""
        self._update_subtitle()

    def on_key(self, event: events.Key) -> None:
        """搜索态按键累积：可打印字符入前缀，backspace 回删；enter/esc 走聚焦/取消路径。

        本 handler 先于 App bindings 派发（MRO 顺序），prevent_default 可屏蔽
        数字过滤 / p / q 等 bindings，避免搜索输入误触全局动作。
        """
        if not self.search_active:
            return
        if event.key in ("enter", "escape"):
            return  # 交给 RowSelected / clear_focus，避免双触发
        event.prevent_default()
        if event.key == "backspace":
            self.search_query = self.search_query[:-1]
        elif event.is_printable:
            self.search_query += event.character or ""
        else:
            return
        self._apply_search_cursor()
        self._update_subtitle()

    def _first_match_index(self) -> int | None:
        """可见行中首个大小写不敏感前缀匹配行号；空前缀/无匹配返回 None。"""
        query = self.search_query.lower()
        if not query:
            return None
        for i, state in enumerate(self._visible_states):
            if state["factory_id"].lower().startswith(query):
                return i
        return None

    def _apply_search_cursor(self) -> None:
        idx = self._first_match_index()
        if idx is not None:
            self.query_one("#states", DataTable).move_cursor(row=idx, animate=False)

    def _confirm_search(self) -> None:
        """Enter 确认：复用聚焦机制聚焦匹配厂（无匹配仅退出搜索）。"""
        idx = self._first_match_index()
        factory_id = self._visible_states[idx]["factory_id"] if idx is not None else None
        self.search_active = False
        self.search_query = ""
        if factory_id is not None:
            self._set_focus(factory_id)
        else:
            self._update_subtitle()

    def _cancel_search(self) -> None:
        """Esc 取消：退出搜索并清空前缀，不动聚焦状态。"""
        self.search_active = False
        self.search_query = ""
        self._update_subtitle()

    # ---------- M140.3 · Header 聚合统计 ----------

    def _update_subtitle(self) -> None:
        """sub_title：[搜索] | [聚焦厂 或 聚合统计] | [过滤标识]，各段按需省略。"""
        segments: list[str] = []
        if self.search_active:
            segments.append(f"搜索:{self.search_query}")
        if self.focus_factory is not None:
            segments.append(f"聚焦: {self.focus_factory}")
        elif self._states:
            counts: dict[str, int] = {}
            for s in self._states:
                counts[s["status"]] = counts.get(s["status"], 0) + 1
            parts = [f"{len(self._states)} 工厂"]
            for status in ("running", "done", "failed", "paused"):
                n = counts.get(status, 0)
                if n:
                    parts.append(f"{status} {n}")
            segments.append(" · ".join(parts))
        if self.status_filter is not None:
            segments.append(f"过滤:{self.status_filter}")
        self.sub_title = " | ".join(segments)

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
        # M144-B.2：状态过滤只影响可见行；全量快照保留供聚合统计
        if self.status_filter is None:
            self._visible_states = states
        else:
            self._visible_states = [s for s in states if s["status"] == self.status_filter]
        table = self.query_one("#states", DataTable)
        table.clear()
        if not states:
            table.add_row("No factories found", "", "", "", "")
        elif not self._visible_states:
            table.add_row(f"No {self.status_filter} factories", "", "", "", "")
        else:
            for s in self._visible_states:
                table.add_row(
                    s["factory_id"],
                    _status_text(s["status"]),
                    _progress_bar(s["done"], s["failed"], s["total"]),
                    f"{s['done']}/{s['failed']}/{s['total']}",
                    s["updated_at"],
                )
        if self.search_active:
            self._apply_search_cursor()  # 轮询重绘后搜索 cursor 保持
        self._update_subtitle()

    def _drain_events(self, conn: sqlite3.Connection, factory_id: str) -> None:
        last = self._last_seq.get(factory_id, 0)
        events = list_events(conn, factory_id, after_seq=last)
        if not events:
            return
        # M140.2：聚焦时只显示聚焦厂；他厂新事件仍推进 _last_seq（取消聚焦后不爆历史重放）
        if self.focus_factory is None or self.focus_factory == factory_id:
            for event in events:
                self._insert_event_line(factory_id, event)
        self._last_seq[factory_id] = events[-1]["seq"]  # list_events 按 seq 升序

    def _insert_event_line(self, factory_id: str, event: dict) -> None:
        """M144-B.1：按事件 ts 有序插入时间线；乱序到达重排，缺 ts 到达序排尾。

        缓冲与 Log 内容同步：尾部追加走 write_line 快路径；中间插入/截断后
        clear + 重写（≤ MAX_LOG_LINES 行，成本可控）。
        """
        entry = (
            _event_sort_key(event),
            int(event.get("seq") or 0),
            self._format_event(factory_id, event),
        )
        idx = bisect.bisect_right(self._event_buffer, entry)
        self._event_buffer.insert(idx, entry)
        if len(self._event_buffer) > MAX_LOG_LINES:
            del self._event_buffer[:-MAX_LOG_LINES]
        log = self.query_one("#events", EventLog)
        if idx == len(self._event_buffer) - 1:
            log.write_line(entry[2])  # 尾部快路径；Log 自身 max_lines 同步截断
        else:
            log.clear()
            log.write_lines(line for _, _, line in self._event_buffer)

    @staticmethod
    def _format_event(factory_id: str, event: dict) -> str:
        ts = _hhmmss(str(event.get("ts") or ""))
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
