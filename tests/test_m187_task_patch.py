"""M187.2 任务编辑 PATCH + M187.3 重启安全 TDD 测试（A 队后端）。

覆盖：
- TaskRegistry.update 纯逻辑：未知 id None、白名单外键 ValueError、空 fields
  ValueError、改文案字段不重算、改调度字段重算、合并非法不落盘、disabled
  改调度 next_run_at 保持 None、显式置空 run_at 被拦、成功后落盘可 reload
- PATCH 端点：改 title 200 且 next_run_at 原值、未知 id 404、空 body 422、
  mode 非法 422、合并非法 422、FLIPPED_TASKS=0 404
- lifespan M187.3：预置 running 无 checkpoint 假会话 → 启动后 error；
  running 有 checkpoint → 不标 error 且走 _resume_orchestrator（monkeypatch 防真跑）
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api.tasks import TaskRegistry

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 10, 30, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ====================================================================
# 1 · TaskRegistry.update（纯逻辑，tmp 路径隔离）
# ====================================================================

def test_update_unknown_id_returns_none(tmp_path):
    reg = TaskRegistry(tmp_path / "tasks.json")
    assert reg.update("task-nope", title="x", now=NOW) is None


def test_update_unknown_field_raises(tmp_path):
    reg = TaskRegistry(tmp_path / "tasks.json")
    t = reg.add(title="t", prompt="p", kind="interval", every_minutes=5, now=NOW)
    with pytest.raises(ValueError, match="未知字段"):
        reg.update(t.id, banana=1, now=NOW)


def test_update_empty_fields_raises(tmp_path):
    reg = TaskRegistry(tmp_path / "tasks.json")
    t = reg.add(title="t", prompt="p", kind="interval", every_minutes=5, now=NOW)
    with pytest.raises(ValueError):
        reg.update(t.id, now=NOW)


def test_update_title_keeps_next_run_at(tmp_path):
    reg = TaskRegistry(tmp_path / "tasks.json")
    run_at = _iso(NOW + timedelta(hours=1))
    t = reg.add(title="t", prompt="p", kind="once", run_at=run_at, now=NOW)
    t2 = reg.update(t.id, title="新标题", now=NOW)
    assert t2 is not None and t2.title == "新标题"
    assert t2.next_run_at == run_at, "仅文案字段变更不得重算 next_run_at"


def test_update_cron_recomputes_next_run_at(tmp_path):
    reg = TaskRegistry(tmp_path / "tasks.json")
    t = reg.add(title="t", prompt="p", kind="cron", cron="0 9 * * *", now=NOW)
    before = t.next_run_at
    t2 = reg.update(t.id, cron="* * * * *", now=NOW)
    assert t2 is not None and t2.cron == "* * * * *"
    assert t2.next_run_at != before, "调度字段实际变更必须重算"
    # cron 按本地时区解释（`* * * * *` 时区无关）：断言同一时刻而非同一字符串
    assert datetime.fromisoformat(t2.next_run_at or "") == datetime(2026, 8, 5, 10, 31, tzinfo=UTC)


def test_update_kind_cron_to_once_without_run_at_raises_not_saved(tmp_path):
    path = tmp_path / "tasks.json"
    reg = TaskRegistry(path)
    t = reg.add(title="t", prompt="p", kind="cron", cron="0 9 * * *", now=NOW)
    with pytest.raises(ValueError):
        reg.update(t.id, kind="once", now=NOW)
    unchanged = reg.get(t.id)
    assert unchanged is not None and unchanged.kind == "cron", "校验失败不得改动内存"
    reg2 = TaskRegistry(path)
    reloaded = reg2.get(t.id)
    assert reloaded is not None and reloaded.kind == "cron", "校验失败不得落盘"


def test_update_disabled_schedule_change_keeps_next_run_none(tmp_path):
    reg = TaskRegistry(tmp_path / "tasks.json")
    t = reg.add(title="t", prompt="p", kind="interval", every_minutes=5, now=NOW)
    reg.toggle(t.id, False, now=NOW)
    t2 = reg.update(t.id, every_minutes=10, now=NOW)
    assert t2 is not None and t2.every_minutes == 10
    assert t2.next_run_at is None, "disabled 任务重算结果恒为 None"


def test_update_explicit_run_at_none_on_once_raises(tmp_path):
    reg = TaskRegistry(tmp_path / "tasks.json")
    t = reg.add(title="t", prompt="p", kind="once",
                run_at=_iso(NOW + timedelta(hours=1)), now=NOW)
    with pytest.raises(ValueError):
        reg.update(t.id, run_at=None, now=NOW)


def test_update_non_cron_with_cron_raises(tmp_path):
    reg = TaskRegistry(tmp_path / "tasks.json")
    t = reg.add(title="t", prompt="p", kind="interval", every_minutes=5, now=NOW)
    with pytest.raises(ValueError):
        reg.update(t.id, cron="* * * * *", now=NOW)


def test_update_blank_title_raises(tmp_path):
    reg = TaskRegistry(tmp_path / "tasks.json")
    t = reg.add(title="t", prompt="p", kind="interval", every_minutes=5, now=NOW)
    with pytest.raises(ValueError):
        reg.update(t.id, title="   ", now=NOW)


def test_update_persists_reload(tmp_path):
    path = tmp_path / "tasks.json"
    reg = TaskRegistry(path)
    t = reg.add(title="t", prompt="p", kind="interval", every_minutes=5, now=NOW)
    reg.update(t.id, title="改后", mode="plan", every_minutes=30, now=NOW)
    reg2 = TaskRegistry(path)
    reloaded = reg2.get(t.id)
    assert reloaded is not None
    assert reloaded.title == "改后" and reloaded.mode == "plan"
    assert reloaded.every_minutes == 30


# ====================================================================
# 2 · PATCH 端点（TestClient，注册表 monkeypatch 到 tmp 路径）
# ====================================================================

@pytest.fixture()
def registry(monkeypatch, tmp_path):
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


def test_patch_title_200_next_run_at_unchanged(client, registry):
    run_at = _iso(datetime.now(UTC) + timedelta(hours=1))
    t = registry.add(title="t", prompt="p", kind="once", run_at=run_at)
    r = client.patch(f"/api/v1/tasks/{t.id}", json={"title": "新标题"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["title"] == "新标题" and data["next_run_at"] == run_at


def test_patch_cron_200_recomputes(client, registry):
    t = registry.add(title="t", prompt="p", kind="cron", cron="0 9 * * *")
    before = t.next_run_at
    r = client.patch(f"/api/v1/tasks/{t.id}", json={"cron": "*/10 * * * *"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["cron"] == "*/10 * * * *" and data["next_run_at"] != before


def test_patch_unknown_id_404(client):
    r = client.patch("/api/v1/tasks/task-nope", json={"title": "x"})
    assert r.status_code == 404, r.text


def test_patch_empty_body_422(client, registry):
    t = registry.add(title="t", prompt="p", kind="interval", every_minutes=5)
    r = client.patch(f"/api/v1/tasks/{t.id}", json={})
    assert r.status_code == 422, r.text


def test_patch_invalid_mode_422(client, registry):
    t = registry.add(title="t", prompt="p", kind="interval", every_minutes=5)
    r = client.patch(f"/api/v1/tasks/{t.id}", json={"mode": "banana"})
    assert r.status_code == 422, r.text


def test_patch_merged_illegal_422(client, registry):
    t = registry.add(title="t", prompt="p", kind="interval", every_minutes=5)
    r = client.patch(f"/api/v1/tasks/{t.id}", json={"kind": "cron"})
    assert r.status_code == 422, f"合并后 cron 缺表达式必须被拦: {r.text}"
    unchanged = registry.get(t.id)
    assert unchanged is not None and unchanged.kind == "interval", "422 不得落盘"


def test_patch_feature_off_404(client, monkeypatch):
    monkeypatch.setenv("FLIPPED_TASKS", "0")
    r = client.patch("/api/v1/tasks/task-x", json={"title": "x"})
    assert r.status_code == 404, r.text


# ====================================================================
# 3 · M187.3 lifespan 重启安全
# ====================================================================

def _write_sessions(path, sessions):
    path.write_text(json.dumps({"sessions": sessions, "events": {}},
                               ensure_ascii=False), encoding="utf-8")


def _fake_session(sid, status, checkpoint=None):
    now = _iso(datetime.now(UTC))
    s = {"id": sid, "title": sid, "status": status, "mode": "chat",
         "created_at": now, "updated_at": now}
    if checkpoint:
        s["checkpoint_db_path"] = checkpoint
    return s


def test_lifespan_marks_stale_running_session_error(monkeypatch, tmp_path):
    """running 且无 checkpoint_db_path 的会话（chat/plan 进程死后无恢复可能）
    → 启动时一次性标 error，不再永远假 running。"""
    store_path = tmp_path / ".sessions.json"
    _write_sessions(store_path, [_fake_session("sess-stale", "running")])
    monkeypatch.setenv("FLIPPED_SESSION_STORE_PATH", str(store_path))
    from api.main import app
    from api.schemas import SessionStatus
    from api.session import store
    with TestClient(app):
        sess = store.get("sess-stale")
        assert sess is not None
        assert sess.status == SessionStatus.error


def test_lifespan_resumes_checkpoint_session_not_error(monkeypatch, tmp_path):
    """running 且有 checkpoint_db_path → 走 _resume_orchestrator（注册进
    RUNNING_TASKS 防重入），不得被 stale 扫描标 error。"""
    store_path = tmp_path / ".sessions.json"
    _write_sessions(store_path, [
        _fake_session("sess-resume", "running", checkpoint="/tmp/fake.db")])
    monkeypatch.setenv("FLIPPED_SESSION_STORE_PATH", str(store_path))
    resumed: list[str] = []

    async def _fake_resume(session):
        resumed.append(session.id)

    monkeypatch.setattr("api.main._resume_orchestrator", _fake_resume)
    from api.main import RUNNING_TASKS, app
    from api.schemas import SessionStatus
    from api.session import store
    with TestClient(app):
        sess = store.get("sess-resume")
        assert sess is not None
        assert sess.status == SessionStatus.running, "有 checkpoint 不得标 error"
        assert resumed == ["sess-resume"], "必须走恢复路径"
    assert "sess-resume" not in RUNNING_TASKS, "恢复任务完成后须从防重入映射清除"
