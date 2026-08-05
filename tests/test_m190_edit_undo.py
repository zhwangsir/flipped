"""M190.1 · 编辑重跑截断可恢复（trash + restore_trash）— 消化 L-M174-1。

契约（PLAN.md M190 节，字段名一字不差）：
- truncate_from：截下批次先入 trash 再删（返回删除条数不变）：
  batch = {"from_event_id", "prev_event_id", "events":[Event.model_dump...]}；每会话 cap 5 批。
- trash_pending(sid) -> int：最近一批条数；无 → 0。
- restore_trash(sid) -> int | None：撤销=丢弃截断点之后的重跑产物（edited user
  消息+应答+status/snapshot）再把批次按原 id 重挂回原位。
  无批次 → None；锚点丢失 / 截断后有非 edited 的新 user 消息 → None 且不弹出；
  命中 → 弹出该批、删截断点后事件、重挂、save，返回恢复条数。
- trash 随 save/load 持久化（"trash" 键）；delete(sid) 连带清 trash。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api.session import SessionStore  # noqa: E402


def _make_store_with_events(n: int = 5):
    store = SessionStore()
    session = store.create(title="t")
    ids = [store.add_event(session.id, "message", payload={"i": i}).id for i in range(n)]
    return store, session.id, ids


# ---------- truncate_from 入 trash ----------

def test_truncate_stashes_batch_into_trash():
    """截断后 trash_pending == 删除条数，批次记录 from/prev 正确。"""
    store, sid, ids = _make_store_with_events(5)
    store.truncate_from(sid, ids[2])
    assert store.trash_pending(sid) == 3
    batch = store._trash[sid][-1]
    assert batch["from_event_id"] == ids[2]
    assert batch["prev_event_id"] == ids[1]
    assert [e["id"] for e in batch["events"]] == ids[2:]


def test_truncate_unknown_event_no_trash():
    """幂等未删（未知 id）→ 不入 trash。"""
    store, sid, ids = _make_store_with_events(3)
    assert store.truncate_from(sid, f"{sid}-999999") == 0
    assert store.trash_pending(sid) == 0


def test_trash_cap_5_batches():
    """每会话 trash cap 5：第 6 批顶掉最老批。"""
    store = SessionStore()
    session = store.create(title="t")
    for round_ in range(6):
        # 每轮：加 2 个事件 → 截掉后 1 个（连同目标）→ 入 trash 1 批
        a = store.add_event(session.id, "message", payload={"r": round_})
        b = store.add_event(session.id, "message", payload={"r": round_})
        store.truncate_from(session.id, b.id)
    assert len(store._trash[session.id]) == 5


def test_trash_pending_empty_when_no_truncate():
    store, sid, _ = _make_store_with_events(2)
    assert store.trash_pending(sid) == 0


def test_trash_pending_unknown_session():
    assert SessionStore().trash_pending("sess-nonexistent") == 0


# ---------- restore_trash ----------

def test_restore_reappends_events_with_original_ids():
    """截断后无新事件 → 恢复全部事件，id 逐一相等、顺序不变。"""
    store, sid, ids = _make_store_with_events(5)
    store.truncate_from(sid, ids[2])
    restored = store.restore_trash(sid)
    assert restored == 3
    assert [e.id for e in store.events(sid)] == ids
    assert store.events(sid)[2].payload == {"i": 2}


def test_restore_pops_batch():
    """恢复后该批弹出，trash_pending 归零；再次恢复 → None。"""
    store, sid, ids = _make_store_with_events(4)
    store.truncate_from(sid, ids[1])
    assert store.restore_trash(sid) == 3
    assert store.trash_pending(sid) == 0
    assert store.restore_trash(sid) is None


def test_restore_blocked_by_new_user_message_and_keeps_batch():
    """截断后追加了真实新 user 消息（无 edited 标记）→ None 且不弹出批次。"""
    from api.schemas import Role
    store, sid, ids = _make_store_with_events(5)
    store.truncate_from(sid, ids[2])
    store.add_event(sid, "message", agent=Role.user, payload={"text": "新输入"})
    assert store.restore_trash(sid) is None
    assert store.trash_pending(sid) == 3
    # 现有事件未被污染
    assert [e.id for e in store.events(sid)] == ids[:2] + [f"{sid}-000006"]


def test_restore_discards_rerun_products_and_reappends():
    """截断后仅有重跑产物（edited user 消息 + assistant 应答 + status）
    → 丢弃产物、按原 id 重挂批次（真实编辑流中 undo 可达的关键路径）。"""
    from api.schemas import Role
    store, sid, ids = _make_store_with_events(5)
    store.truncate_from(sid, ids[2])
    # 模拟编辑端点重派发产生的三条事件
    store.add_event(sid, "status", agent=Role.system, payload={"status": "running"})
    edited = store.add_event(sid, "message", agent=Role.user,
                             payload={"text": "改后", "edited": True})
    store.add_event(sid, "message", agent=Role.supervisor, payload={"text": "应答"})
    assert store.restore_trash(sid) == 3
    after = store.events(sid)
    # 重跑产物（含 edited 消息）已被丢弃，原批次按原 id 接回锚点之后
    assert [e.id for e in after] == ids
    assert edited.id not in [e.id for e in after]
    assert store.trash_pending(sid) == 0


def test_restore_blocked_when_anchor_lost():
    """批次锚点已不在事件流（覆盖它的批次被 cap 顶掉/已消费）→ None 且不弹出。"""
    store, sid, ids = _make_store_with_events(5)
    store.truncate_from(sid, ids[2])          # 批次1：prev=ids[1]
    store.truncate_from(sid, ids[0])          # 批次2：prev=None，吞掉 ids[0..1]
    store._trash[sid].pop()                   # 模拟批次2已被消费/顶掉 → 锚点永久丢失
    assert store.restore_trash(sid) is None   # 批次1锚点 ids[1] 不在流中
    assert store.trash_pending(sid) == 3      # 批次1保留不弹出
    assert store.events(sid) == []            # 事件流未被污染


def test_restore_chained_lifo_after_double_truncate():
    """两次截断后按 LIFO 逐层撤销：先恢复内层批次（锚点随之回归），再恢复外层。"""
    store, sid, ids = _make_store_with_events(5)
    store.truncate_from(sid, ids[2])          # 批次1：prev=ids[1]
    store.truncate_from(sid, ids[0])          # 批次2：prev=None
    assert store.restore_trash(sid) == 2      # 批次2恢复 ids[0..1]，批次1锚点回归
    assert store.restore_trash(sid) == 3      # 批次1恢复 ids[2..4]
    assert [e.id for e in store.events(sid)] == ids


def test_restore_from_empty_events_tail():
    """截断到 0 事件（prev=None）后无新事件 → 可恢复（None==None 合法）。"""
    store, sid, ids = _make_store_with_events(3)
    store.truncate_from(sid, ids[0])  # 全截
    assert store.events(sid) == []
    assert store.restore_trash(sid) == 3
    assert [e.id for e in store.events(sid)] == ids


def test_restore_unknown_session_returns_none():
    assert SessionStore().restore_trash("sess-nonexistent") is None


# ---------- 持久化与清理 ----------

def test_trash_persists_via_save(tmp_path):
    """trash 随 save 落盘；重载后可恢复。"""
    path = str(tmp_path / "sessions.json")
    store = SessionStore()
    store.load(path)
    session = store.create(title="t")
    ids = [store.add_event(session.id, "message", payload={"i": i}).id for i in range(4)]
    store.truncate_from(session.id, ids[2])

    reloaded = SessionStore()
    reloaded.load(path)
    assert reloaded.trash_pending(session.id) == 2
    assert reloaded.restore_trash(session.id) == 2
    assert [e.id for e in reloaded.events(session.id)] == ids


def test_old_store_file_without_trash_key_loads_ok(tmp_path):
    """旧格式（无 trash 键）→ 加载不炸，trash 为空。"""
    import json
    path = tmp_path / "sessions.json"
    store0 = SessionStore()
    s = store0.create(title="t")
    store0.add_event(s.id, "message", payload={"i": 0})
    data = {"sessions": [x.model_dump(mode="json") for x in store0.list()],
            "events": {s.id: [e.model_dump(mode="json") for e in store0.events(s.id)]}}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    reloaded = SessionStore()
    reloaded.load(str(path))
    assert reloaded.trash_pending(s.id) == 0


def test_delete_session_clears_trash():
    store, sid, ids = _make_store_with_events(3)
    store.truncate_from(sid, ids[1])
    assert store.delete(sid) is True
    assert store.trash_pending(sid) == 0
    assert sid not in store._trash


# ---------- undo 端点（TestClient，同 test_m174_edit_rerun.py 模式） ----------

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    from api.main import app
    return TestClient(app)


def _new_session(client) -> str:
    return client.post("/api/v1/assistant/sessions", json={"title": "t", "mode": "chat"}).json()["id"]


def _emit(sid, text, role):
    from api.main import bus
    from api.schemas import EventType, Role
    return bus.emit(sid, EventType.message, role, {"text": text})


def _undo_url(sid: str) -> str:
    return f"/api/v1/assistant/sessions/{sid}/edit/undo"


def _truncate_tail(sid: str, event_id: str) -> int:
    from api.main import store
    return store.truncate_from(sid, event_id)


def test_undo_404_unknown_session(client):
    assert client.post(_undo_url("sess-nonexistent")).status_code == 404


def test_undo_404_when_trash_empty(client):
    sid = _new_session(client)
    r = client.post(_undo_url(sid))
    assert r.status_code == 404
    assert "no truncated events" in r.json()["detail"]


def test_undo_200_restores_events_and_emits_status(client):
    from api.main import store
    from api.schemas import Role
    sid = _new_session(client)
    u1 = _emit(sid, "u1", Role.user)
    _emit(sid, "a1", Role.supervisor)
    u2 = _emit(sid, "u2", Role.user)
    before = [e.id for e in store.events(sid)]
    assert _truncate_tail(sid, u2.id) == 1

    r = client.post(_undo_url(sid))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["session_id"] == sid and body["restored"] == 1
    # 恢复的事件按原 id 重挂；末尾多一条 undo status 事件（留痕）
    after_ids = [e.id for e in store.events(sid)]
    assert after_ids[: len(before)] == before
    assert len(after_ids) == len(before) + 1
    # status 事件留痕
    status_evs = [e for e in store.events(sid)
                  if (e.type.value if hasattr(e.type, "value") else e.type) == "status"]
    assert any("编辑重跑已撤销" in str(e.payload.get("note", "")) for e in status_evs)


def test_undo_409_after_new_events(client):
    from api.main import store
    from api.schemas import Role
    sid = _new_session(client)
    _emit(sid, "u1", Role.user)
    u2 = _emit(sid, "u2", Role.user)
    _truncate_tail(sid, u2.id)
    _emit(sid, "u2-new", Role.user)  # 截断点后追加新事件
    r = client.post(_undo_url(sid))
    assert r.status_code == 409
    assert "new events appended" in r.json()["detail"]


def test_undo_409_when_running(client, monkeypatch):
    from api.main import RUNNING_TASKS
    from api.schemas import Role
    sid = _new_session(client)
    u1 = _emit(sid, "u1", Role.user)
    _truncate_tail(sid, u1.id)

    class _FakeRunning:
        def done(self):
            return False

    monkeypatch.setitem(RUNNING_TASKS, sid, _FakeRunning())
    assert client.post(_undo_url(sid)).status_code == 409
