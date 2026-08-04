"""M178.1 · 后台任务系统 TDD 测试（B 队）。

覆盖：
- compute_next_run：once 未来/过去/disabled、interval 从 created_at/last_run_at 滚动、
  落后多轮跳到首个未来时刻
- due_tasks：到期过滤（disabled/未来排除）+ next_run_at 升序
- TaskRegistry：add+持久化 reload 一致、原子写、坏 JSON 不炸、get/remove/toggle 重算、
  mark_run once 跑完 disabled、run_count 累加、interval 滚动
- 端点（TestClient）：POST 201 字段对、once 缺 run_at 422、interval every<1 422、
  非法 mode 422、GET 排序（None 沉底）、DELETE/toggle 404、FLIPPED_TASKS=0 全 404
- _dispatch_scheduled：fake _run_chat 断言建会话+user 消息落库+mark_run done；
  防重入（RUNNING_TASKS 未完成 → skipped 且不新建会话）

测试风格沿用 test_m176_goal_api.py：同步测试函数 + TestClient（with 管理 portal）
+ fake async 记录调用；时钟经 now 参数注入，无 freezegun；tmp 路径隔离注册表。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.tasks import ScheduledTask, TaskRegistry, compute_next_run, due_tasks

NOW = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ====================================================================
# 1 · compute_next_run（纯函数）
# ====================================================================

def _task(**kw) -> ScheduledTask:
    defaults = dict(id="task-t0000001", title="t", prompt="p", created_at=_iso(NOW))
    defaults.update(kw)
    return ScheduledTask(**defaults)


def test_next_run_once_future_returns_run_at():
    run_at = _iso(NOW + timedelta(hours=1))
    t = _task(kind="once", run_at=run_at)
    assert compute_next_run(t, NOW) == run_at


def test_next_run_once_past_returns_none():
    t = _task(kind="once", run_at=_iso(NOW - timedelta(seconds=1)))
    assert compute_next_run(t, NOW) is None


def test_next_run_disabled_returns_none():
    t = _task(kind="once", run_at=_iso(NOW + timedelta(hours=1)), enabled=False)
    assert compute_next_run(t, NOW) is None


def test_next_run_interval_rolls_from_created_at():
    # created=11:50，每 15 分钟 → 12:05（首个 >now 时刻）
    t = _task(kind="interval", every_minutes=15,
              created_at=_iso(NOW - timedelta(minutes=10)))
    assert compute_next_run(t, NOW) == _iso(NOW + timedelta(minutes=5))


def test_next_run_interval_rolls_from_last_run_at():
    # last_run=11:30 晚于 created=10:00 → 基准取 last_run；11:45 过 → 12:00 也 <=now → 12:15
    t = _task(kind="interval", every_minutes=15,
              created_at=_iso(NOW - timedelta(hours=2)),
              last_run_at=_iso(NOW - timedelta(minutes=30)))
    assert compute_next_run(t, NOW) == _iso(NOW + timedelta(minutes=15))


def test_next_run_interval_catches_up_multiple_periods():
    # created=10:00，每 30 分钟，now=12:00 → 10:30…12:00 全 <=now → 首个未来 12:30
    t = _task(kind="interval", every_minutes=30,
              created_at=_iso(NOW - timedelta(hours=2)))
    assert compute_next_run(t, NOW) == _iso(NOW + timedelta(minutes=30))


def test_next_run_interval_invalid_every_returns_none():
    t = _task(kind="interval", every_minutes=0)
    assert compute_next_run(t, NOW) is None


# ====================================================================
# 2 · due_tasks（纯函数）
# ====================================================================

def test_due_tasks_filters_and_sorts():
    due_old = _task(id="task-a", next_run_at=_iso(NOW - timedelta(minutes=5)))
    due_new = _task(id="task-b", next_run_at=_iso(NOW - timedelta(seconds=1)))
    future = _task(id="task-c", next_run_at=_iso(NOW + timedelta(minutes=1)))
    disabled = _task(id="task-d", next_run_at=_iso(NOW - timedelta(minutes=9)), enabled=False)
    no_next = _task(id="task-e", next_run_at=None)
    result = due_tasks([future, disabled, due_new, no_next, due_old], NOW)
    assert [t.id for t in result] == ["task-a", "task-b"], "只留到期 enabled 任务，按 next_run_at 升序"


# ====================================================================
# 3 · TaskRegistry（tmp 路径隔离）
# ====================================================================

def test_registry_add_persists_and_reload(tmp_path):
    path = tmp_path / "tasks.json"
    reg = TaskRegistry(path)
    run_at = _iso(NOW + timedelta(hours=1))
    t = reg.add(title="日报", prompt="写日报", mode="chat", model="coder",
                kind="once", run_at=run_at, now=NOW)
    assert t.id.startswith("task-") and len(t.id) == len("task-") + 8
    assert t.created_at == _iso(NOW)
    assert t.next_run_at == run_at
    assert t.enabled is True and t.run_count == 0
    # reload：全新实例从磁盘恢复，字段完全一致
    reg2 = TaskRegistry(path)
    assert reg2.get(t.id) == t


def test_registry_save_atomic_no_tmp_left(tmp_path):
    path = tmp_path / "tasks.json"
    reg = TaskRegistry(path)
    reg.add(title="t", prompt="p", kind="once", run_at=_iso(NOW + timedelta(hours=1)), now=NOW)
    assert path.exists()
    assert not Path(f"{path}.tmp").exists(), "原子写完成后 tmp 文件已被 os.replace 收走"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["tasks"]) == 1


def test_registry_load_corrupt_json_returns_empty(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text("{not json at all", encoding="utf-8")
    reg = TaskRegistry(path)  # 不炸
    assert reg.list() == []


def test_registry_get_remove_and_unknown_remove(tmp_path):
    reg = TaskRegistry(tmp_path / "tasks.json")
    t = reg.add(title="t", prompt="p", kind="once",
                run_at=_iso(NOW + timedelta(hours=1)), now=NOW)
    assert reg.get(t.id) is not None
    assert reg.remove(t.id) is True
    assert reg.get(t.id) is None
    assert reg.remove("task-nope") is False, "未知 id 删除返回 False"
    assert reg.remove(t.id) is False


def test_registry_list_sorted_next_run_none_last(tmp_path):
    reg = TaskRegistry(tmp_path / "tasks.json")
    late = reg.add(title="late", prompt="p", kind="once",
                   run_at=_iso(NOW + timedelta(hours=3)), now=NOW)
    early = reg.add(title="early", prompt="p", kind="once",
                    run_at=_iso(NOW + timedelta(hours=1)), now=NOW)
    off = reg.add(title="off", prompt="p", kind="once",
                  run_at=_iso(NOW + timedelta(hours=2)), now=NOW)
    reg.toggle(off.id, False, now=NOW)
    assert [t.id for t in reg.list()] == [early.id, late.id, off.id], "升序，None 沉底"


def test_registry_toggle_recomputes_next_run(tmp_path):
    reg = TaskRegistry(tmp_path / "tasks.json")
    t = reg.add(title="巡检", prompt="p", kind="interval", every_minutes=30,
                now=NOW - timedelta(hours=2))
    # 停用 → next None
    t2 = reg.toggle(t.id, False, now=NOW)
    assert t2 is not None and t2.enabled is False and t2.next_run_at is None
    # 再启用 → 以 created_at 为基准滚动到首个未来（10:00 +30m…→ 12:30）
    t3 = reg.toggle(t.id, True, now=NOW)
    assert t3 is not None and t3.enabled is True
    assert t3.next_run_at == _iso(NOW + timedelta(minutes=30))
    assert reg.toggle("task-nope", True, now=NOW) is None


def test_registry_mark_run_once_disables_and_counts(tmp_path):
    reg = TaskRegistry(tmp_path / "tasks.json")
    t = reg.add(title="一次性", prompt="p", kind="once",
                run_at=_iso(NOW - timedelta(minutes=1)), now=NOW - timedelta(hours=1))
    t2 = reg.mark_run(t.id, "done", "sess-abc", now=NOW)
    assert t2 is not None
    assert t2.enabled is False and t2.next_run_at is None, "once 跑完即停"
    assert t2.last_run_at == _iso(NOW) and t2.last_status == "done"
    assert t2.last_session_id == "sess-abc" and t2.run_count == 1
    t3 = reg.mark_run(t.id, "failed", None, now=NOW + timedelta(minutes=1))
    assert t3 is not None and t3.run_count == 2 and t3.last_status == "failed"


def test_registry_mark_run_interval_rolls_next_run(tmp_path):
    reg = TaskRegistry(tmp_path / "tasks.json")
    t = reg.add(title="巡检", prompt="p", kind="interval", every_minutes=30,
                now=NOW - timedelta(hours=2))
    t2 = reg.mark_run(t.id, "done", "sess-x", now=NOW)
    assert t2 is not None and t2.enabled is True
    assert t2.next_run_at == _iso(NOW + timedelta(minutes=30)), "interval 以 last_run_at 滚动"


# ====================================================================
# 4 · REST 端点（TestClient，注册表 monkeypatch 到 tmp 路径）
# ====================================================================

@pytest.fixture()
def registry(monkeypatch, tmp_path):
    """每个端点测试独立任务注册表（tmp 路径隔离，防环境污染单例）。"""
    reg = TaskRegistry(tmp_path / "tasks.json")
    monkeypatch.setattr("api.main._TASK_REGISTRY", reg)
    monkeypatch.delenv("FLIPPED_TASKS", raising=False)
    monkeypatch.delenv("FLIPPED_TASKS_PATH", raising=False)
    return reg


@pytest.fixture()
def client(registry):
    from api.main import app
    with TestClient(app) as c:
        yield c


def test_create_task_201_and_fields(client):
    run_at = _iso(datetime.now(timezone.utc) + timedelta(hours=1))
    r = client.post("/api/v1/tasks", json={
        "title": "每日日报", "prompt": "帮我写日报", "mode": "chat", "model": "coder",
        "kind": "once", "run_at": run_at,
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["id"].startswith("task-")
    assert data["title"] == "每日日报" and data["prompt"] == "帮我写日报"
    assert data["mode"] == "chat" and data["model"] == "coder" and data["kind"] == "once"
    assert data["run_at"] == run_at and data["next_run_at"] == run_at
    assert data["enabled"] is True and data["run_count"] == 0
    assert data["created_at"], "created_at 由服务端写入"


def test_create_task_once_missing_run_at_422(client):
    r = client.post("/api/v1/tasks", json={"title": "t", "prompt": "p", "kind": "once"})
    assert r.status_code == 422, r.text


def test_create_task_interval_every_zero_422(client):
    r = client.post("/api/v1/tasks", json={
        "title": "t", "prompt": "p", "kind": "interval", "every_minutes": 0})
    assert r.status_code == 422, r.text


def test_create_task_invalid_mode_422(client):
    r = client.post("/api/v1/tasks", json={
        "title": "t", "prompt": "p", "mode": "banana", "kind": "interval", "every_minutes": 5})
    assert r.status_code == 422, r.text


def test_list_tasks_sorted_next_run_none_last(client, registry):
    now = datetime.now(timezone.utc)
    late = registry.add(title="late", prompt="p", kind="once",
                        run_at=_iso(now + timedelta(hours=3)), now=now)
    early = registry.add(title="early", prompt="p", kind="once",
                         run_at=_iso(now + timedelta(hours=1)), now=now)
    off = registry.add(title="off", prompt="p", kind="once",
                       run_at=_iso(now + timedelta(hours=2)), now=now)
    registry.toggle(off.id, False, now=now)
    r = client.get("/api/v1/tasks")
    assert r.status_code == 200, r.text
    assert [t["id"] for t in r.json()] == [early.id, late.id, off.id]


def test_delete_task_unknown_404(client, registry):
    t = registry.add(title="t", prompt="p", kind="once",
                     run_at=_iso(datetime.now(timezone.utc) + timedelta(hours=1)))
    r = client.delete(f"/api/v1/tasks/{t.id}")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert registry.get(t.id) is None
    r2 = client.delete(f"/api/v1/tasks/{t.id}")
    assert r2.status_code == 404, "重复删除 → 404"


def test_toggle_task_unknown_404(client):
    r = client.post("/api/v1/tasks/task-nope/toggle", params={"enabled": False})
    assert r.status_code == 404, r.text


def test_toggle_task_off_and_on(client, registry):
    now = datetime.now(timezone.utc)
    t = registry.add(title="巡检", prompt="p", kind="interval", every_minutes=30, now=now)
    r = client.post(f"/api/v1/tasks/{t.id}/toggle", params={"enabled": False})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False and r.json()["next_run_at"] is None
    r2 = client.post(f"/api/v1/tasks/{t.id}/toggle", params={"enabled": True})
    assert r2.status_code == 200, r.text
    assert r2.json()["enabled"] is True and r2.json()["next_run_at"] is not None


def test_tasks_disabled_all_endpoints_404(client, monkeypatch):
    monkeypatch.setenv("FLIPPED_TASKS", "0")  # 整体开关：4 端点全 404
    body = {"title": "t", "prompt": "p", "kind": "interval", "every_minutes": 5}
    assert client.post("/api/v1/tasks", json=body).status_code == 404
    assert client.get("/api/v1/tasks").status_code == 404
    assert client.delete("/api/v1/tasks/task-x").status_code == 404
    assert client.post("/api/v1/tasks/task-x/toggle",
                       params={"enabled": True}).status_code == 404


# ====================================================================
# 5 · _dispatch_scheduled（进程内派发链，fake _run_chat，绝不碰真 LLM）
# ====================================================================

def test_dispatch_creates_session_and_marks_done(client, registry, monkeypatch):
    calls: list[tuple] = []

    async def _fake_chat(session_id, task_id, description, model_alias, mode):
        calls.append((session_id, task_id, description, model_alias, mode))

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    from api.main import RUNNING_TASKS, _dispatch_scheduled
    from api.session import store

    now = datetime.now(timezone.utc)
    task = registry.add(title="定时日报", prompt="帮我写日报", mode="chat", model="coder",
                        kind="interval", every_minutes=30, now=now)

    async def _run():
        await _dispatch_scheduled(task)
        await asyncio.sleep(0.05)  # 让被派发的协程跑完

    asyncio.run(_run())

    assert len(calls) == 1, "chat 模式应派发到 _run_chat"
    sid, _tid, desc, model_alias, mode = calls[0]
    assert desc == "帮我写日报" and model_alias == "coder" and mode == "chat"
    sess = store.get(sid)
    assert sess is not None, "派发必须新建会话"
    assert sess.title == "定时日报" and sess.mode == "chat"
    user_msgs = [e for e in store.events(sid)
                 if e.type == "message" and e.agent == "user"]
    assert any(e.payload.get("text") == "帮我写日报" for e in user_msgs), "user 消息必须落库"
    reloaded = registry.get(task.id)
    assert reloaded is not None
    assert reloaded.last_status == "done" and reloaded.last_session_id == sid
    assert reloaded.run_count == 1 and reloaded.next_run_at is not None, "interval 已滚动"
    RUNNING_TASKS.pop(sid, None)  # 清理，防跨测试污染


def test_dispatch_reentry_marks_skipped(registry, monkeypatch):
    from api.main import RUNNING_TASKS, _dispatch_scheduled
    from api.session import store

    class _FakeRunning:
        """RUNNING_TASKS 防重入只调 .done()（同 test_m176 模式）。"""
        def done(self) -> bool:
            return False

    now = datetime.now(timezone.utc)
    task = registry.add(title="巡检", prompt="巡检一下", mode="chat",
                        kind="interval", every_minutes=10, now=now)
    registry.mark_run(task.id, "done", "sess-prev", now)
    RUNNING_TASKS["sess-prev"] = _FakeRunning()
    try:
        before = len(store.list())
        asyncio.run(_dispatch_scheduled(registry.get(task.id)))
        assert len(store.list()) == before, "上次会话仍在跑 → 不得新建会话"
        reloaded = registry.get(task.id)
        assert reloaded is not None
        assert reloaded.last_status == "skipped" and reloaded.last_session_id is None
        assert reloaded.run_count == 2
    finally:
        RUNNING_TASKS.pop("sess-prev", None)
