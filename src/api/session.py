"""会话仓库（Phase B 先内存；M5.4 加入 JSON 持久化以支持崩溃恢复）。"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import Event, Role, Session, SessionStatus


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._events: dict[str, list[Event]] = {}
        self._counter: dict[str, int] = {}
        self._path: str | None = None

    def load(self, path: str) -> None:
        """从 JSON 文件加载会话与事件。"""
        self._path = path
        if not os.path.exists(path):
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return
        for s in data.get("sessions", []):
            session = Session(**s)
            self._sessions[session.id] = session
            self._events[session.id] = [Event(**e) for e in data.get("events", {}).get(session.id, [])]
            self._counter[session.id] = max(
                [int(e.id.split("-")[-1]) for e in self._events[session.id]] + [0]
            )

    def save(self) -> None:
        """持久化到 JSON 文件。"""
        if not self._path:
            return
        data = {
            "sessions": [s.model_dump(mode="json") for s in self._sessions.values()],
            "events": {sid: [e.model_dump(mode="json") for e in evs] for sid, evs in self._events.items()},
        }
        Path(self._path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def update(self, session_id: str, **kwargs) -> Session | None:
        """更新会话字段并持久化。"""
        session = self._sessions.get(session_id)
        if not session:
            return None
        for k, v in kwargs.items():
            if hasattr(session, k):
                setattr(session, k, v)
        session.updated_at = datetime.now(timezone.utc).isoformat()
        self.save()
        return session

    def _next_id(self, session_id: str) -> str:
        self._counter[session_id] = self._counter.get(session_id, 0) + 1
        return f"{session_id}-{self._counter[session_id]}"

    def create(self, title: str, model: str = "coder", mode: str = "agent") -> Session:
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        session = Session(id=sid, title=title, status=SessionStatus.idle, model=model,
                          mode=mode, created_at=now, updated_at=now)
        self._sessions[sid] = session
        self._events[sid] = []
        self._counter[sid] = 0
        self.save()
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def list(self) -> list[Session]:
        return list(self._sessions.values())

    def delete(self, session_id: str) -> bool:
        """删除会话及其事件；返回是否存在过。"""
        existed = session_id in self._sessions
        self._sessions.pop(session_id, None)
        self._events.pop(session_id, None)
        self._counter.pop(session_id, None)
        self.save()
        return existed

    def update_status(self, session_id: str, status: SessionStatus) -> Session | None:
        session = self._sessions.get(session_id)
        if not session:
            return None
        session.status = status
        session.updated_at = datetime.now(timezone.utc).isoformat()
        self.save()
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
        self.save()
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
