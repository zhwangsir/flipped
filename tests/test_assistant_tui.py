"""M151.6 · TUI Assistant headless 单测（Textual run_test + pilot，确定性）。

覆盖 AssistantTUIApp 的 6 个交互场景：
1. 启动显示空态
2. Enter 经 mock httpx 发送消息（POST /messages）
3. /clear 清空流
4. tool_call 事件渲染为箭头行
5. approval_request 事件弹出 overlay
6. overlay 按 'o' 调 /approve 端点

所有用例都不依赖真实 :8011 后端：用 FakeAsyncClient 替换 httpx.AsyncClient；
事件路由通过 app._handle_event(...) 直接注入，绕过 WS 连接。
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from tui.assistant import (  # noqa: E402
    ApprovalOverlay,
    AssistantTUIApp,
    ContextPane,
    InputBar,
    StreamPane,
)


# ---------- Fake httpx.AsyncClient ----------


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data: dict | None = None) -> None:
        self.status_code = status_code
        self._json = json_data or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPError(f"status {self.status_code}")

    def json(self) -> dict:
        return self._json


class FakeAsyncClient:
    """内存版 httpx.AsyncClient 替身：记录所有调用，返回预设响应。"""

    def __init__(self, **kwargs: Any) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.base_url = kwargs.get("base_url", "")
        self.timeout = kwargs.get("timeout", 30.0)

    async def post(self, path: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("POST", path, kwargs))
        if "/approve" in path:
            return FakeResponse(200, {"ok": True, "decision": "approve"})
        if "/reject" in path:
            return FakeResponse(200, {"ok": True, "decision": "reject"})
        if "/sessions" in path and "/messages" not in path:
            return FakeResponse(200, {"id": "sess-fake", "mode": "agent"})
        if "/messages" in path:
            return FakeResponse(200, {"task_id": "task-fake", "session_id": "sess-fake"})
        return FakeResponse(200, {})

    async def get(self, path: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("GET", path, kwargs))
        return FakeResponse(200, {})

    async def aclose(self) -> None:
        pass


# ---------- 同步包装 run_test ----------


def _run_app(app: AssistantTUIApp, body) -> None:
    """同步包装 run_test：body(app, pilot) 为 async 回调。"""

    async def _runner() -> None:
        async with app.run_test() as pilot:
            await body(app, pilot)

    asyncio.run(_runner())


def _stream_entries(app: AssistantTUIApp) -> list[str]:
    return app.query_one(StreamPane)._entries


# ---------- 1. 启动显示空态 ----------


def test_startup_shows_empty_state():
    """AssistantTUIApp 启动后 StreamPane 显示空态提示文本。"""
    app = AssistantTUIApp(
        session_id="sess-test", enable_ws=False, http_client_factory=FakeAsyncClient
    )

    async def body(app, pilot):
        await pilot.pause()
        entries = _stream_entries(app)
        assert len(entries) >= 1, "空态应有提示文本"
        text = entries[0].lower()
        assert "no messages" in text or "type a request" in text or "空" in text

    _run_app(app, body)


# ---------- 2. Enter 经 mock httpx 发送消息 ----------


def test_enter_sends_message_via_httpx():
    """InputBar 输入文本后按 Enter → POST /messages 被调用，body 含原文。"""
    app = AssistantTUIApp(
        session_id="sess-test", enable_ws=False, http_client_factory=FakeAsyncClient
    )

    async def body(app, pilot):
        await pilot.pause()
        ib = app.query_one(InputBar)
        ib.focus()
        await pilot.pause()
        # 直接设置文本（避免逐字按键的复杂焦点行为）
        ib.text = "hello world"
        await pilot.pause()
        await pilot.press("enter")
        # 让 asyncio.create_task(_send_message) 跑完
        await asyncio.sleep(0.05)
        await pilot.pause()

        http = app._http
        assert http is not None
        posts = [c for c in http.calls if c[0] == "POST" and "/messages" in c[1]]
        assert len(posts) == 1, f"应有一次 POST /messages，实际 calls={http.calls}"
        body_sent = posts[0][2].get("json", {})
        assert body_sent.get("text") == "hello world"
        # 发送后输入框被清空
        assert ib.text == ""

    _run_app(app, body)


# ---------- 3. /clear 清空流 ----------


def test_clear_command_empties_stream():
    """StreamPane 有内容后输入 /clear → 流被清空回到空态。"""
    app = AssistantTUIApp(
        session_id="sess-test", enable_ws=False, http_client_factory=FakeAsyncClient
    )

    async def body(app, pilot):
        await pilot.pause()
        stream = app.query_one(StreamPane)
        # 注入一些内容
        stream.append_message("user", "first message")
        stream.append_message("assistant", "reply")
        stream.append_tool_call("list_files", "92 files")
        await pilot.pause()
        assert len(_stream_entries(app)) == 3

        ib = app.query_one(InputBar)
        ib.focus()
        await pilot.pause()
        ib.text = "/clear"
        await pilot.pause()
        await pilot.press("enter")
        await asyncio.sleep(0.02)
        await pilot.pause()

        entries = _stream_entries(app)
        assert len(entries) == 1, f"/clear 后应只剩空态提示，实际 {entries}"
        text = entries[0].lower()
        assert "no messages" in text or "type a request" in text or "空" in text

    _run_app(app, body)


# ---------- 4. tool_call 事件渲染为箭头行 ----------


def test_tool_call_event_renders_arrow_line():
    """模拟 WS 推送 tool_call 事件 → StreamPane 出现 → 箭头行。"""
    app = AssistantTUIApp(
        session_id="sess-test", enable_ws=False, http_client_factory=FakeAsyncClient
    )

    async def body(app, pilot):
        await pilot.pause()
        app._handle_event({
            "type": "tool_call",
            "agent": "worker",
            "payload": {"tool": "list_files", "args": {"path": "src"}, "summary": "92 files"},
        })
        await pilot.pause()
        entries = _stream_entries(app)
        arrow_lines = [e for e in entries if "→" in e]
        assert len(arrow_lines) == 1, f"应有一行 → 箭头，实际 entries={entries}"
        line = arrow_lines[0]
        assert "list_files" in line
        assert "92 files" in line

    _run_app(app, body)


# ---------- 5. approval_request 事件弹出 overlay ----------


def test_approval_request_event_shows_overlay():
    """模拟 WS 推送 approval_request → ApprovalOverlay 出现。"""
    app = AssistantTUIApp(
        session_id="sess-test", enable_ws=False, http_client_factory=FakeAsyncClient
    )

    async def body(app, pilot):
        await pilot.pause()
        app._handle_event({
            "type": "approval_request",
            "agent": "system",
            "payload": {"action": "rm -rf /tmp/x", "reason": "high risk"},
        })
        await pilot.pause()
        # overlay 应是当前活动 screen
        assert isinstance(app.screen, ApprovalOverlay), \
            f"应弹出 ApprovalOverlay，实际 screen={app.screen}"
        # overlay 内容包含 action
        overlay = app.screen
        assert "rm -rf /tmp/x" in str(overlay._action)

    _run_app(app, body)


# ---------- 6. overlay 按 'o' 调 /approve 端点 ----------


def test_overlay_o_key_calls_approve_endpoint():
    """ApprovalOverlay 出现后按 'o' → POST /approve 被调用。"""
    app = AssistantTUIApp(
        session_id="sess-test", enable_ws=False, http_client_factory=FakeAsyncClient
    )

    async def body(app, pilot):
        await pilot.pause()
        app._handle_event({
            "type": "approval_request",
            "agent": "system",
            "payload": {"action": "rm -rf /tmp/y", "reason": "high risk"},
        })
        await pilot.pause()
        assert isinstance(app.screen, ApprovalOverlay)

        await pilot.press("o")
        # 让 asyncio.create_task(_approve) 跑完
        await asyncio.sleep(0.05)
        await pilot.pause()

        http = app._http
        assert http is not None
        approves = [c for c in http.calls if c[0] == "POST" and "/approve" in c[1]]
        assert len(approves) == 1, f"应有一次 POST /approve，实际 calls={http.calls}"
        # overlay 已被 dismiss
        assert not isinstance(app.screen, ApprovalOverlay), \
            "approve 后 overlay 应关闭"

    _run_app(app, body)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
