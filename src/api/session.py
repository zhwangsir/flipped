"""会话仓库（Phase B 先内存；M5.4 加入 JSON 持久化以支持崩溃恢复）。"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import Event, Role, Session, SessionStatus


def _seq_of(event_id: str) -> int:
    """从事件 id 尾部解析递增序号（兼容旧无零填充与新零填充两种形态）。

    解析失败返回 -1（排在最前，保证数值比较不会把它误当新事件）。
    """
    try:
        return int(event_id.rsplit("-", 1)[-1])
    except (ValueError, IndexError):
        return -1


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._events: dict[str, list[Event]] = {}
        self._counter: dict[str, int] = {}
        # M190.1 — 编辑重跑截断回收站：sid → [batch...]（cap 5，先进先出）
        self._trash: dict[str, list[dict]] = {}
        self._path: str | None = None
        # bus.emit 可从工作线程调用（factory_loop 等），所有读写需持锁
        self._lock = threading.RLock()

    def load(self, path: str) -> None:
        """从 JSON 文件加载会话与事件。"""
        with self._lock:
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
                    [_seq_of(e.id) for e in self._events[session.id]] + [0]
                )
            # M190.1 — 旧格式无 trash 键 → 缺省空（向后兼容）
            self._trash = {sid: list(batches) for sid, batches in data.get("trash", {}).items()}

    def save(self) -> None:
        """持久化到 JSON 文件（tmp + os.replace 原子写，防并发/崩溃写坏）。"""
        with self._lock:
            if not self._path:
                return
            data = {
                "sessions": [s.model_dump(mode="json") for s in self._sessions.values()],
                "events": {sid: [e.model_dump(mode="json") for e in evs] for sid, evs in self._events.items()},
                "trash": self._trash,
            }
            tmp = f"{self._path}.tmp"
            Path(tmp).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self._path)

    def update(self, session_id: str, **kwargs) -> Session | None:
        """更新会话字段并持久化。"""
        with self._lock:
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
        # 零填充 6 位：保证 id 字典序 == 数值序（旧数据无填充，由数值比较兜底）
        self._counter[session_id] = self._counter.get(session_id, 0) + 1
        return f"{session_id}-{self._counter[session_id]:06d}"

    def create(self, title: str, model: str = "coder", mode: str = "agent",
               project: str | None = None, project_name: str | None = None) -> Session:
        with self._lock:
            sid = f"sess-{uuid.uuid4().hex[:8]}"
            now = datetime.now(timezone.utc).isoformat()
            session = Session(id=sid, title=title, status=SessionStatus.idle, model=model,
                              mode=mode, project=project, project_name=project_name,
                              created_at=now, updated_at=now)
            self._sessions[sid] = session
            self._events[sid] = []
            self._counter[sid] = 0
            self.save()
            return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def list(self) -> list[Session]:
        with self._lock:
            return list(self._sessions.values())

    def delete(self, session_id: str) -> bool:
        """删除会话及其事件；返回是否存在过。"""
        with self._lock:
            existed = session_id in self._sessions
            self._sessions.pop(session_id, None)
            self._events.pop(session_id, None)
            self._counter.pop(session_id, None)
            self._trash.pop(session_id, None)  # M190.1 连带清回收站
            self.save()
            return existed

    def update_status(self, session_id: str, status: SessionStatus) -> Session | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            session.status = status
            session.updated_at = datetime.now(timezone.utc).isoformat()
            self.save()
            return session

    def add_event(self, session_id: str, type_: str, agent: Role | None = None,
                  payload: dict[str, Any] | None = None, parent_id: str | None = None) -> Event:
        with self._lock:
            event = Event(
                id=self._next_id(session_id),
                session_id=session_id,
                type=type_,
                agent=agent,
                payload=payload or {},
                parent_id=parent_id,
            )
            # setdefault 兼容非会话事件流（如 factory_id 桥接），不再 KeyError
            self._events.setdefault(session_id, []).append(event)
            self.save()
            return event

    def events(self, session_id: str, after_id: str | None = None) -> list[Event]:
        with self._lock:
            evs = list(self._events.get(session_id, []))
        if not after_id:
            return evs
        # 数值比较尾部序号：兼容旧无零填充 id（"sess-x-9"）与新零填充 id（"sess-x-000010"）
        after_seq = _seq_of(after_id)
        if after_seq < 0:
            return evs  # 游标无法解析：全量回放，宁可重复不可丢事件
        return [e for e in evs if _seq_of(e.id) > after_seq]

    def last_event_id(self, session_id: str) -> str | None:
        with self._lock:
            evs = self._events.get(session_id)
            return evs[-1].id if evs else None

    def truncate_from(self, session_id: str, event_id: str) -> int:
        """删除 seq >= seq(event_id) 的全部事件（含目标事件本身），返回删除条数。
        event_id 不存在 → 0（幂等，不报错）。_counter 不重置（单调递增红线）。
        M190.1：截下批次先入 trash（可恢复）再删。持锁 + save() 持久化。"""
        with self._lock:
            evs = self._events.get(session_id, [])
            idx = next((i for i, e in enumerate(evs) if e.id == event_id), None)
            if idx is None:
                return 0
            batch = {
                "from_event_id": event_id,
                "prev_event_id": evs[idx - 1].id if idx > 0 else None,
                "events": [e.model_dump(mode="json") for e in evs[idx:]],
            }
            batches = self._trash.setdefault(session_id, [])
            batches.append(batch)
            del batches[:-5]  # cap 5，先进先出
            deleted = len(evs) - idx
            del evs[idx:]
            self.save()
            return deleted

    def trash_pending(self, session_id: str) -> int:
        """最近一批被截断事件的条数；无 → 0（M190.1）。"""
        with self._lock:
            batches = self._trash.get(session_id) or []
            return len(batches[-1]["events"]) if batches else 0

    def restore_trash(self, session_id: str) -> int | None:
        """恢复最近一批截断事件（M190.1）。

        语义：撤销编辑重跑 = 丢弃截断点之后的全部事件（重跑产物：edited user 消息
        + 应答 + status/snapshot），再把 trash 批次按原 id 重挂回原位。_counter
        单调红线不受损——被丢弃的都是截断后新 id，重挂的旧 id 接在原锚点之后，
        列表序与 id 序保持一致，无 seq 交错。

        拒绝（None 且不弹出批次）仅两种真歧义：
        - 批次锚点 prev_event_id 在当前事件流中已不存在（被后续截断吞掉）。
        - 截断点之后存在「非编辑重跑产生」的新 user 消息（message/user 且无
          edited 标记）——撤销会误删用户真实新输入。
        命中 → 弹出该批、删除截断点后事件、重挂、save，返回恢复条数。
        """
        with self._lock:
            batches = self._trash.get(session_id) or []
            if not batches:
                return None
            batch = batches[-1]
            evs = self._events.get(session_id, [])
            prev_id = batch["prev_event_id"]
            if prev_id is None:
                cut = 0
            else:
                anchor = next((i for i, e in enumerate(evs) if e.id == prev_id), None)
                if anchor is None:
                    return None  # 锚点丢失，拒绝且不弹出
                cut = anchor + 1
            for e in evs[cut:]:
                etype = e.type.value if hasattr(e.type, "value") else str(e.type)
                agent = e.agent.value if hasattr(e.agent, "value") else (
                    str(e.agent) if e.agent else None)
                if etype == "message" and agent == "user" and not e.payload.get("edited"):
                    return None  # 截断后有真实新 user 输入，拒绝且不弹出
            batches.pop()
            del evs[cut:]
            restored = [Event(**d) for d in batch["events"]]
            evs.extend(restored)
            self._events[session_id] = evs
            self.save()
            return len(restored)


store = SessionStore()
