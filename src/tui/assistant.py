"""M151.6 · TUI Assistant —— 终端代码助手（claudecode/Codex 派生范式）。

基于 Textual 的全屏 TUI，连接已就绪的 assistant HTTP + WS API（:8011）：
- 左侧 StreamPane 70%：消息流（Markdown / Syntax 高亮），上限 500 行
- 右侧 ContextPane 30%：cwd / model / token 用量 / 最近 5 个工具调用 / 会话列表
- 底部 InputBar(TextArea)：多行；Enter 发送 / Shift+Enter 换行 / Tab 切焦点
- 模态 ApprovalOverlay：a=always / o=once(approve) / r=reject
- Slash 命令：/clear /compact /mode /help /files

WS 事件路由与 UI 渲染解耦：_handle_event(ev) 是纯 UI 方法，可被
WS 推送或测试直接调用；不依赖网络。测试用 FakeAsyncClient 替换 httpx。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Callable

import httpx
import websockets
from rich.console import Group
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, RichLog, Static, TextArea

DEFAULT_BASE_URL = os.environ.get("FLIPPED_API_BASE", "http://127.0.0.1:8011")
DEFAULT_WS_URL = os.environ.get("FLIPPED_WS_BASE", "ws://127.0.0.1:8011")

MAX_STREAM_LINES = 500
EMPTY_PROMPT = "(no messages yet — type a request below and press Enter)"

# Codex 派生 ANSI 调色板
DEFAULT_CSS = """
AssistantTUIApp {
    background: #1a1a1a;
    color: white;
}
#main {
    height: 1fr;
}
StreamPane {
    width: 70%;
    border: solid #3a3a3a;
    background: #1a1a1a;
    color: white;
    padding: 0 1;
}
ContextPane {
    width: 30%;
    border: solid #3a3a3a;
    background: #262626;
    color: white;
    padding: 0 1;
}
InputBar {
    height: 6;
    border: solid #3a3a3a;
    background: #262626;
    color: white;
}
ApprovalOverlay {
    align: center middle;
}
#approval-box {
    background: #262626;
    border: heavy #ff6e6e;
    color: white;
    padding: 2 4;
    width: 60;
    height: auto;
}
"""


# ---------- StreamPane ----------


class StreamPane(RichLog):
    """助手消息流。Markdown/Syntax 渲染；上限 500 行。

    维护 _entries: list[str] 作为 plain-text 镜像供测试断言使用
    （RichLog 自身无暴露已写入文本的 API）。
    """

    DEFAULT_CLASSES = ""

    def __init__(self) -> None:
        super().__init__(markup=True, wrap=True, auto_scroll=True, max_lines=MAX_STREAM_LINES)
        self._entries: list[str] = []
        self._show_empty_state: bool = True

    def on_mount(self) -> None:
        self._render_empty_state()

    def _render_empty_state(self) -> None:
        """清空并显示空态提示。"""
        self.clear()  # RichLog.clear
        self._entries = [EMPTY_PROMPT]
        self.write(Text(EMPTY_PROMPT, style="dim italic"))
        self._show_empty_state = True

    def clear_stream(self) -> None:
        """用户 /clear 命令：清空流并回到空态。"""
        self._render_empty_state()

    def _append_text(self, plain: str, renderable: Any) -> None:
        if self._show_empty_state:
            self.clear()
            self._entries = []
            self._show_empty_state = False
        self.write(renderable)
        self._entries.append(plain)
        if len(self._entries) > MAX_STREAM_LINES:
            self._entries = self._entries[-MAX_STREAM_LINES:]

    def append_message(self, role: str, text: str) -> None:
        prefix = "you" if role == "user" else "assistant"
        plain = f"[{prefix}] {text}"
        if role == "user":
            # 用户消息：纯 Text，单行
            renderable = Text.assemble(
                (f"[{prefix}] ", "bold bright_blue"),
                (text, ""),
            )
        else:
            # 助手消息：head Text + Markdown body（Group 组合，不能塞进 Text）
            head = Text(f"[{prefix}]", style="bold bright_magenta")
            body = Markdown(text)
            renderable = Group(head, body)
        self._append_text(plain, renderable)

    def append_tool_call(self, tool: str, summary: str = "") -> None:
        plain = f"→ {tool} {summary}".rstrip()
        renderable = Text.assemble(
            ("→ ", "bold bright_cyan"),
            (f"{tool} ", "bold"),
            (summary, "dim"),
        )
        self._append_text(plain, renderable)

    def append_tool_result(self, status: str, summary: str = "") -> None:
        mark = "✓" if status == "ok" else "✗"
        color = "green" if status == "ok" else "red"
        plain = f"← {mark} {summary}".rstrip()
        renderable = Text.assemble(
            (f"← {mark} ", f"bold {color}"),
            (summary, "dim"),
        )
        self._append_text(plain, renderable)

    def append_code(self, code: str, language: str = "python") -> None:
        plain = code
        renderable = Syntax(code, language, theme="ansi_dark", word_wrap=True)
        self._append_text(plain, renderable)

    def append_error(self, text: str) -> None:
        plain = f"[error] {text}"
        renderable = Text.assemble(("[error] ", "bold red"), (text, "red"))
        self._append_text(plain, renderable)


# ---------- ContextPane ----------


class ContextPane(Static):
    """右侧栏：cwd / model / token 用量 / 最近 5 个工具调用 / 会话列表。"""

    def __init__(self) -> None:
        super().__init__()
        self._cwd: str = os.getcwd()
        self._model: str = "coder"
        self._tokens: str = "—"
        self._recent_tools: list[str] = []
        self._sessions: list[str] = []

    def update_cwd(self, cwd: str) -> None:
        self._cwd = cwd
        self._refresh()

    def update_model(self, model: str) -> None:
        self._model = model
        self._refresh()

    def update_tokens(self, tokens: str) -> None:
        self._tokens = tokens
        self._refresh()

    def add_tool(self, summary: str) -> None:
        self._recent_tools.append(summary)
        self._recent_tools = self._recent_tools[-5:]
        self._refresh()

    def update_sessions(self, sessions: list[str]) -> None:
        self._sessions = sessions[:5]
        self._refresh()

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        tools = "\n".join(f"  • {t}" for t in self._recent_tools) or "  (none)"
        sessions = "\n".join(f"  • {s}" for s in self._sessions) or "  (none)"
        self.update(
            f"[bold]cwd[/bold]\n  {self._cwd}\n\n"
            f"[bold]model[/bold]\n  {self._model}\n\n"
            f"[bold]tokens[/bold]\n  {self._tokens}\n\n"
            f"[bold]recent tools[/bold]\n{tools}\n\n"
            f"[bold]sessions[/bold]\n{sessions}"
        )


# ---------- InputBar ----------


class InputBar(TextArea):
    """多行输入框。

    - Enter → 发送（重写 _on_key 拦截，避免 TextArea 默认插入换行）
    - Shift+Enter → 插入换行（仅在终端能区分时；不能区分时退化为 Enter=发送）
    - Tab → App 级 binding 切焦点
    - / 开头 → slash 命令
    """

    BINDINGS = [
        Binding("enter", "submit", "Send", show=True, key_display="↵"),
    ]

    def action_submit(self) -> None:
        text = self.text.strip()
        if not text:
            return
        # 先清空输入框，再交给 app 派发，避免重复触发时残留
        self.text = ""
        self.app.handle_input_submit(text)

    async def _on_key(self, event: events.Key) -> None:
        """拦截 Enter：发送而非换行；Shift+Enter 插入换行。

        TextArea 默认在 _on_key 里把 enter 当作插入 \\n；我们必须在子类拦截
        并 prevent_default，否则即使 BINDINGS 命中 action_submit，TextArea
        的 _on_key 仍会运行并插入换行（污染输入框）。
        """
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.action_submit()
            return
        if event.key == "shift+enter":
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        await super()._on_key(event)


# ---------- ApprovalOverlay ----------


class ApprovalOverlay(ModalScreen):
    """权限审批模态层。

    Bindings：a=always(approve) / o=once(approve) / r=reject / esc=cancel
    """

    BINDINGS = [
        ("a", "approve_always", "Always"),
        ("o", "approve_once", "Once"),
        ("r", "reject", "Reject"),
        ("escape", "dismiss_overlay", "Cancel"),
    ]

    def __init__(self, action: str, reason: str = "") -> None:
        super().__init__()
        self._action = action
        self._reason = reason

    def compose(self) -> ComposeResult:
        yield Static(
            f"△ Permission required\n\n"
            f"  action: {self._action}\n"
            f"  reason: {self._reason}\n\n"
            "[a] always  [o] once  [r] reject  [esc] cancel",
            id="approval-box",
        )

    def action_approve_always(self) -> None:
        self.app.handle_approval_decision("approve", always=True)
        self.dismiss()

    def action_approve_once(self) -> None:
        self.app.handle_approval_decision("approve", always=False)
        self.dismiss()

    def action_reject(self) -> None:
        self.app.handle_approval_decision("reject", always=False)
        self.dismiss()

    def action_dismiss_overlay(self) -> None:
        self.dismiss()


# ---------- AssistantTUIApp ----------


class AssistantTUIApp(App):
    """Codex-style terminal assistant for flipped."""

    TITLE = "Flipped Assistant"
    CSS_PATH = None
    DEFAULT_CSS = DEFAULT_CSS

    BINDINGS = [
        ("ctrl+l", "clear_stream", "Clear"),
        ("tab", "cycle_focus", "Focus"),
    ]

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        ws_url: str = DEFAULT_WS_URL,
        session_id: str | None = None,
        model_alias: str = "coder",
        cwd: str | None = None,
        enable_ws: bool = True,
        http_client_factory: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url.rstrip("/")
        self.session_id = session_id
        self.model_alias = model_alias
        self.cwd = cwd or os.getcwd()
        self._enable_ws = enable_ws
        self._http_client_factory = http_client_factory or httpx.AsyncClient
        self._http: Any = None
        self._ws_task: asyncio.Task | None = None
        self._stream: StreamPane | None = None  # 缓存，overlay 期间也能写

    # ---------- 布局 ----------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            yield StreamPane()
            yield ContextPane()
        yield InputBar()
        yield Footer()

    def on_mount(self) -> None:
        self._http = self._http_client_factory(
            base_url=self.base_url, timeout=30.0
        )
        self._stream = self.query_one(StreamPane)
        ctx = self.query_one(ContextPane)
        ctx.update_cwd(self.cwd)
        ctx.update_model(self.model_alias)
        if self._enable_ws:
            self._ws_task = asyncio.create_task(self._ws_loop())

    def on_unmount(self) -> None:
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()

    # ---------- WS loop ----------

    async def _ws_loop(self) -> None:
        if not self.session_id:
            return  # 没有会话 id 时无 URL 可连
        url = f"{self.ws_url}/api/v1/sessions/{self.session_id}/events"
        try:
            async for ws in websockets.connect(url):
                try:
                    async for raw in ws:
                        try:
                            ev = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(ev, dict):
                            self._handle_event(ev)
                except websockets.ConnectionClosed:
                    continue
        except (OSError, websockets.WebSocketException):
            return  # 后端不可用：静默退出（fire-and-forget）
        except asyncio.CancelledError:
            raise

    # ---------- 事件路由（纯 UI；可被 WS 或测试直接调用） ----------

    def _handle_event(self, ev: dict) -> None:
        etype = ev.get("type")
        payload = ev.get("payload") or {}
        stream = self._stream or self.query_one(StreamPane)
        if etype == "message":
            role = ev.get("agent") or payload.get("role") or "assistant"
            text = payload.get("text", "")
            stream.append_message(role, text)
        elif etype == "tool_call":
            tool = payload.get("tool", "?")
            summary = payload.get("summary", "")
            stream.append_tool_call(tool, summary)
            self.query_one(ContextPane).add_tool(f"{tool} {summary}".strip())
        elif etype == "tool_result":
            status = payload.get("status", "ok")
            summary = payload.get("summary", "")
            stream.append_tool_result(status, summary)
        elif etype == "approval_request":
            action = payload.get("action", "(unspecified)")
            reason = payload.get("reason", "")
            self._push_approval(action, reason)
        elif etype == "error":
            stream.append_error(payload.get("text", str(payload)))
        # status / plan / file_change / terminal / browser / checkpoint /
        # rca / verifier_verdict / approval_result → 不在主对话流渲染

    def _push_approval(self, action: str, reason: str) -> None:
        # 不堆叠多个 overlay
        if isinstance(self.screen, ApprovalOverlay):
            return
        self.push_screen(ApprovalOverlay(action, reason))

    # ---------- 输入 ----------

    def handle_input_submit(self, text: str) -> None:
        if text.startswith("/"):
            self._dispatch_slash(text)
            return
        # 普通消息：本地立即渲染用户气泡，再异步 POST
        if self._stream is not None:
            self._stream.append_message("user", text)
        asyncio.create_task(self._send_message(text))

    async def _send_message(self, text: str) -> dict:
        if self._http is None:
            self._http = self._http_client_factory(
                base_url=self.base_url, timeout=30.0
            )
        # 确保有会话
        if self.session_id is None:
            try:
                r = await self._http.post(
                    "/api/v1/assistant/sessions",
                    json={
                        "title": "TUI",
                        "mode": "agent",
                        "model_alias": self.model_alias,
                    },
                )
                r.raise_for_status()
                self.session_id = r.json().get("id")
            except (httpx.HTTPError, KeyError, ValueError) as e:
                self._stream_append_error(f"cannot create session: {e}")
                return {}
        if self.session_id is None:
            self._stream_append_error("no session id")
            return {}
        try:
            r = await self._http.post(
                f"/api/v1/assistant/sessions/{self.session_id}/messages",
                json={"text": text},
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            self._stream_append_error(f"send failed: {e}")
            return {}

    async def _approve(self, always: bool = False) -> dict:
        if self._http is None or self.session_id is None:
            return {}
        try:
            r = await self._http.post(
                f"/api/v1/assistant/sessions/{self.session_id}/approve"
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            self._stream_append_error(f"approve failed: {e}")
            return {}

    async def _reject(self) -> dict:
        if self._http is None or self.session_id is None:
            return {}
        try:
            r = await self._http.post(
                f"/api/v1/assistant/sessions/{self.session_id}/reject"
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            self._stream_append_error(f"reject failed: {e}")
            return {}

    def handle_approval_decision(self, decision: str, always: bool = False) -> None:
        if decision == "approve":
            asyncio.create_task(self._approve(always))
        else:
            asyncio.create_task(self._reject())

    def _stream_append_error(self, text: str) -> None:
        if self._stream is not None:
            self._stream.append_error(text)

    # ---------- Slash 命令 ----------

    def _dispatch_slash(self, text: str) -> None:
        parts = text.split(None, 1)
        cmd = parts[0]
        arg = parts[1] if len(parts) > 1 else ""
        stream = self._stream
        if stream is None:
            return
        if cmd == "/clear":
            self.action_clear_stream()
        elif cmd == "/compact":
            stream.append_message(
                "assistant", "(compact: not yet implemented in M151.6)"
            )
        elif cmd == "/mode":
            if arg in ("auto", "agent", "chat", "plan"):
                stream.append_message(
                    "assistant", f"mode → {arg} (applies to next session)"
                )
            else:
                stream.append_message(
                    "assistant", "usage: /mode {auto|agent|chat|plan}"
                )
        elif cmd == "/help":
            stream.append_message(
                "assistant",
                "slash: /clear /compact /mode {auto|agent|chat|plan} /files /help",
            )
        elif cmd == "/files":
            stream.append_message(
                "assistant", "(files: not yet implemented in M151.6)"
            )
        else:
            stream.append_message(
                "assistant", f"unknown command: {cmd} (try /help)"
            )

    # ---------- App-level actions ----------

    def action_clear_stream(self) -> None:
        if self._stream is not None:
            self._stream.clear_stream()

    def action_cycle_focus(self) -> None:
        widgets = [self.query_one(InputBar), self.query_one(StreamPane)]
        current = self.focused
        try:
            idx = widgets.index(current) if current in widgets else -1
        except ValueError:
            idx = -1
        next_idx = (idx + 1) % len(widgets)
        widgets[next_idx].focus()


# ---------- CLI ----------


def main() -> None:
    parser = argparse.ArgumentParser(description="Flipped TUI Assistant")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="assistant HTTP API base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--ws-url",
        default=DEFAULT_WS_URL,
        help="assistant WS base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="existing assistant session id to attach to",
    )
    parser.add_argument(
        "--model",
        default="coder",
        help="model alias shown in context pane (default: %(default)s)",
    )
    args = parser.parse_args()
    app = AssistantTUIApp(
        base_url=args.base_url,
        ws_url=args.ws_url,
        session_id=args.session,
        model_alias=args.model,
    )
    app.run()


if __name__ == "__main__":
    main()
