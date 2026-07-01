"""内存会话仓库（Phase B 先内存，后续换 SQLite/Postgres + Redis Pub/Sub）。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .schemas import Event, Role, Session, SessionStatus


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._events: dict[str, list[Event]] = {}
        self._counter: dict[str, int] = {}

    def _next_id(self, session_id: str) -> str:
        self._counter[session_id] = self._counter.get(session_id, 0) + 1
        return f"{session_id}-{self._counter[session_id]}"

    def create(self, title: str, model: str = "coder") -> Session:
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        session = Session(id=sid, title=title, status=SessionStatus.idle, model=model,
                          created_at=now, updated_at=now)
        self._sessions[sid] = session
        self._events[sid] = []
        self._counter[sid] = 0
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def list(self) -> list[Session]:
        return list(self._sessions.values())

    def update_status(self, session_id: str, status: SessionStatus) -> Session | None:
        session = self._sessions.get(session_id)
        if not session:
            return None
        session.status = status
        session.updated_at = datetime.now(timezone.utc).isoformat()
        return session

    def add_event(self, session_id: str, type_: str, agent: Role | None = None,
                  payload: dict[str, Any] | None = None, parent_id: str | None = None) -> Event:
        event = Event(
            id=self._next_id(session_id),
            session_id=session_id,
            type=type_,
            agent=agent,
            payload=payload or {},
            parent_id=parent_id,
        )
        self._events[session_id].append(event)
        return event

    def events(self, session_id: str, after_id: str | None = None) -> list[Event]:
        evs = list(self._events.get(session_id, []))
        if not after_id:
            return evs
        # 简单 replay：返回 id 字典序更大的事件（id 含递增计数）
        return [e for e in evs if e.id > after_id]

    def last_event_id(self, session_id: str) -> str | None:
        evs = self._events.get(session_id)
        return evs[-1].id if evs else None


store = SessionStore()
