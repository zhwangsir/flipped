"""M174 · SessionStore.truncate_from 事件截断原语。

契约：
- 删除 seq >= seq(event_id) 的全部事件（含目标事件本身），返回删除条数。
- event_id 不存在 → 0（幂等，不报错，不调 save 无副作用）。
- _counter 不重置（单调递增红线：截断后再 add_event，新 seq 严格大于被删最大 seq）。
- 持锁 + save() 持久化。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api.session import SessionStore, _seq_of  # noqa: E402


def _make_store_with_events(n: int = 5) -> tuple[SessionStore, str, list[str]]:
    """建内存 store（_path=None 时 save() 为 no-op），造 n 个事件，返回 (store, sid, event_ids)。"""
    store = SessionStore()
    session = store.create(title="t")
    ids = [store.add_event(session.id, "message", payload={"i": i}).id for i in range(n)]
    return store, session.id, ids


def test_truncate_middle_removes_tail_and_returns_count():
    """中段截断：5 事件截第 3 个 → 剩前 2 个，返回 3，余下事件 id 不变。"""
    store, sid, ids = _make_store_with_events(5)
    deleted = store.truncate_from(sid, ids[2])
    assert deleted == 3
    remaining = store.events(sid)
    assert [e.id for e in remaining] == ids[:2]


def test_truncate_includes_target_event_itself():
    """截掉的事件包含目标事件本身：目标 id 不在剩余里。"""
    store, sid, ids = _make_store_with_events(5)
    store.truncate_from(sid, ids[2])
    remaining_ids = [e.id for e in store.events(sid)]
    assert ids[2] not in remaining_ids


def test_truncate_last_event_removes_one():
    """截尾事件：删 1 个，返回 1。"""
    store, sid, ids = _make_store_with_events(5)
    deleted = store.truncate_from(sid, ids[-1])
    assert deleted == 1
    assert [e.id for e in store.events(sid)] == ids[:-1]


def test_truncate_unknown_event_id_is_idempotent():
    """未知 event_id → 返回 0，事件数不变（幂等）。"""
    store, sid, ids = _make_store_with_events(5)
    deleted = store.truncate_from(sid, f"{sid}-999999")
    assert deleted == 0
    assert [e.id for e in store.events(sid)] == ids


def test_counter_stays_monotonic_after_truncate():
    """计数器单调红线：截断后再 add_event，新事件 seq 严格大于被删最大 seq。"""
    store, sid, ids = _make_store_with_events(5)
    max_deleted_seq = _seq_of(ids[-1])  # 截断会删掉 seq 3..5，被删最大 seq = 5
    store.truncate_from(sid, ids[2])
    new_event = store.add_event(sid, "message", payload={"i": "new"})
    assert _seq_of(new_event.id) > max_deleted_seq


def test_truncate_persists_via_save(tmp_path):
    """save 被调：截断后重新 load 验证持久化生效。"""
    path = str(tmp_path / "sessions.json")
    store = SessionStore()
    store.load(path)  # 文件不存在：仅设置 _path
    session = store.create(title="t")
    ids = [store.add_event(session.id, "message", payload={"i": i}).id for i in range(5)]
    deleted = store.truncate_from(session.id, ids[2])
    assert deleted == 3

    reloaded = SessionStore()
    reloaded.load(path)
    assert [e.id for e in reloaded.events(session.id)] == ids[:2]


def test_truncate_unknown_session_returns_zero():
    """未知 session_id → 返回 0 不炸。"""
    store = SessionStore()
    assert store.truncate_from("sess-nonexistent", "sess-nonexistent-000001") == 0
