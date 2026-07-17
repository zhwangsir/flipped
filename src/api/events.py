"""按会话维度的 WebSocket 事件总线。

线协议（M136-B2 记录的既有事实 + 新增 ack）：

事件 WS ``/api/v1/sessions/{session_id}/events``：
- 连接后服务端先回放历史事件（重连可带 ``?last_event_id=`` 从断点续传），
  随后实时推送 ``Event`` JSON（见 schemas.Event）。
- 客户端 → 服务端帧（JSON）：
    - ``{"type": "ack", "last_event_id": <str>}``
      断点续传确认：服务端回 ``{"type": "ack_ok", "last_event_id": <str>}``（M136 新增）。
    - ``{"type": "ping"}``                    心跳，忽略。
    - ``{"type": "approval_result", ...}``    人工审批结果，转为 approval_result 事件。
    - 其它 type                               按用户消息事件转发（既有行为）。
  非 JSON 文本帧静默忽略，不会断开连接。
- 服务端 → 客户端控制帧：``ack_ok``（对 ack 的回执，不进事件历史）。

终端 WS ``/api/v1/terminal``（见 terminal.py）：
- 客户端 → 服务端：``{"d": "<input>"}`` 写入 pty；``{"r": [cols, rows]}`` 调整窗口。
- 服务端 → 客户端：pty 原始输出文本帧（xterm.js 直接渲染）。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from .schemas import Event, EventType, Role
from .session import SessionStore


class EventBus:
    """维护每个会话的 WS 连接集合，并负责把事件广播给在线客户端。

    支持从非 async 工作线程 emit：若已注册主事件循环，则通过
    run_coroutine_threadsafe 把广播任务投递回主循环。
    """

    def __init__(self, store: SessionStore):
        self.store = store
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(session_id, set()).add(websocket)

    async def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.get(session_id, set()).discard(websocket)

    async def publish(self, session_id: str, event: Event) -> None:
        payload = event.model_dump(mode="json")
        async with self._lock:
            conns = list(self._connections.get(session_id, set()))
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(payload)
            except (RuntimeError, WebSocketDisconnect, Exception):
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.get(session_id, set()).discard(ws)

    async def replay(self, session_id: str, websocket: WebSocket, after_id: str | None) -> None:
        for event in self.store.events(session_id, after_id=after_id):
            await websocket.send_json(event.model_dump(mode="json"))

    def _schedule_publish(self, session_id: str, event: Event) -> None:
        if self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self.publish(session_id, event), self._loop)
        except RuntimeError:
            pass

    def set_status(self, session_id: str, status: str) -> None:
        """同步更新会话状态（从工作线程安全调用）。"""
        from .session import SessionStatus
        try:
            self.store.update_status(session_id, SessionStatus(status))
        except Exception:
            pass

    def emit(self, session_id: str, type_: EventType, agent: Role | None = None,
             payload: dict[str, Any] | None = None, parent_id: str | None = None) -> Event:
        """同步入口：先落盘，再异步广播。可在非 async 上下文调用。"""
        event = self.store.add_event(session_id, type_, agent=agent,
                                     payload=payload or {}, parent_id=parent_id)
        # 尝试直接调度到当前事件循环
        try:
            loop = asyncio.get_running_loop()
            # 如果当前已经在主循环里，直接 create_task
            loop.create_task(self.publish(session_id, event))
        except RuntimeError:
            # 无线程本地事件循环（如工作线程），若已注册主循环则通过线程安全方式投递
            self._schedule_publish(session_id, event)
        return event


def get_bus(store: SessionStore) -> EventBus:
    return EventBus(store)
