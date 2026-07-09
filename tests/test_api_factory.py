"""factory API 集成测试（TestClient，无需真实 LLM / 沙盒）。

用 monkeypatch 替换 factory_loop 的 default_planner 和 default_orchestrator_fn，
使工厂在进程内快速完成，验证 REST 端点的创建/查询/恢复/暂停闭环。
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("FLIPPED_MOCK_WORKER", "1")
os.environ.setdefault("FLIPPED_MOCK_APPROVAL", "1")

import src.api.main as _main  # noqa: E402
from driving.factory_loop import (  # noqa: E402
    FactoryState,
    FactoryStatus,
    FactoryTask,
    TaskResult,
    TaskStatus,
    load_factory_state,
    save_factory_state,
)


@pytest.fixture
def tmp_factory_db(monkeypatch, tmp_path):
    db = str(tmp_path / "factory_test.db")
    monkeypatch.setenv("FLIPPED_FACTORY_DB", db)
    # 必须导入与 src.api.main 相同的模块路径（src.api.factory 而非 api.factory）
    import src.api.factory as factory_mod
    monkeypatch.setattr(factory_mod, "FACTORY_DB", db)
    return db


@pytest.fixture
def client(monkeypatch, tmp_factory_db):
    monkeypatch.setenv("FLIPPED_MOCK_WORKER", "1")
    importlib.reload(_main)
    with TestClient(_main.app) as tc:
        yield tc


def _stub_planner(state: FactoryState) -> list[FactoryTask]:
    return [
        FactoryTask(id="ft-1", description="task one", verify_cmd=["true"]),
        FactoryTask(id="ft-2", description="task two", verify_cmd=["true"]),
    ]


def _stub_orchestrator_ok(task: FactoryTask, state: FactoryState) -> TaskResult:
    return TaskResult(
        task=task, verified=True, stop_reason="completed", iteration=1, summary="ok"
    )


def _quick_run_factory_loop(product_goal, cwd, *, factory_id=None, db_path="data/factory.db",
                             max_tasks=10, planner=None, orchestrator_fn=None, event_bus=None,
                             **kwargs):
    """跳过真实 LLM，直接标记工厂完成。"""
    tasks = _stub_planner(FactoryState(
        factory_id=factory_id or "test", product_goal=product_goal, cwd=cwd, roadmap=[],
    ))
    state = FactoryState(
        factory_id=factory_id or "test-factory",
        product_goal=product_goal,
        cwd=cwd,
        status=FactoryStatus.done,
        roadmap=tasks,
        max_tasks=max_tasks,
    )
    for t in tasks:
        t.status = TaskStatus.done
        state.completed.append(TaskResult(
            task=t, verified=True, stop_reason="completed", iteration=1, summary="ok",
        ))
    save_factory_state(state, db_path)
    return state


def _quick_resume_factory_loop(factory_id, db_path="data/factory.db", **kwargs):
    """快速恢复并标记完成。"""
    state = load_factory_state(factory_id, db_path)
    if state is None:
        return None
    if state.status == FactoryStatus.done:
        return state
    state.status = FactoryStatus.done
    for t in state.roadmap:
        if t.status != TaskStatus.done:
            t.status = TaskStatus.done
            state.completed.append(TaskResult(
                task=t, verified=True, stop_reason="completed", iteration=1, summary="ok",
            ))
    save_factory_state(state, db_path)
    return state


# ---------- 创建 + 列表 + 查询 ----------


def test_create_factory_returns_summary(client, monkeypatch):
    import src.api.factory as factory_mod
    monkeypatch.setattr(factory_mod, "run_factory_loop", _quick_run_factory_loop)

    r = client.post("/api/v1/factories", json={
        "product_goal": "build calc", "cwd": "/tmp", "max_tasks": 3,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["product_goal"] == "build calc"
    assert data["status"] in ("running", "pending", "done")
    assert data["factory_id"].startswith("factory-")
    assert data["max_tasks"] == 3


def test_list_factories(client, monkeypatch):
    import src.api.factory as factory_mod
    monkeypatch.setattr(factory_mod, "run_factory_loop", _quick_run_factory_loop)

    client.post("/api/v1/factories", json={"product_goal": "goal A", "cwd": "/tmp"})
    client.post("/api/v1/factories", json={"product_goal": "goal B", "cwd": "/tmp"})

    r = client.get("/api/v1/factories")
    assert r.status_code == 200
    ids = [f["factory_id"] for f in r.json()]
    assert len(ids) >= 2


def test_get_factory_404(client):
    r = client.get("/api/v1/factories/nonexistent")
    assert r.status_code == 404


def test_get_factory_detail(client, monkeypatch, tmp_factory_db):
    import src.api.factory as factory_mod
    monkeypatch.setattr(factory_mod, "run_factory_loop", _quick_run_factory_loop)

    r = client.post("/api/v1/factories", json={"product_goal": "detail test", "cwd": "/tmp"})
    fid = r.json()["factory_id"]

    r2 = client.get(f"/api/v1/factories/{fid}/detail")
    assert r2.status_code == 200
    detail = r2.json()
    assert detail["factory_id"] == fid
    assert "roadmap" in detail
    assert "completed" in detail
    assert "failed" in detail


# ---------- 暂停 ----------


def test_pause_factory(client, tmp_factory_db):
    """直接预置一个 running 工厂状态，测试 pause 端点。"""
    state = FactoryState(
        factory_id="test-pause-factory",
        product_goal="pause me",
        cwd="/tmp",
        status=FactoryStatus.running,
        roadmap=[FactoryTask(id="ft-1", description="task one", verify_cmd=["true"])],
        max_tasks=3,
    )
    save_factory_state(state, tmp_factory_db)

    r = client.post("/api/v1/factories/test-pause-factory/pause")
    assert r.status_code == 200
    assert r.json()["status"] == "paused"

    # 验证持久化
    loaded = load_factory_state("test-pause-factory", tmp_factory_db)
    assert loaded is not None
    assert loaded.status == FactoryStatus.paused


def test_pause_nonexistent_factory(client):
    r = client.post("/api/v1/factories/nonexistent/pause")
    assert r.status_code == 404


# ---------- 恢复 ----------


def test_resume_factory(client, monkeypatch, tmp_factory_db):
    import src.api.factory as factory_mod
    monkeypatch.setattr(factory_mod, "resume_factory_loop", _quick_resume_factory_loop)

    # 预置一个 paused 状态的工厂
    state = FactoryState(
        factory_id="test-resume-factory",
        product_goal="resume me",
        cwd="/tmp",
        status=FactoryStatus.paused,
        roadmap=[FactoryTask(id="ft-1", description="task one", verify_cmd=["true"])],
        max_tasks=3,
    )
    save_factory_state(state, tmp_factory_db)

    r = client.post("/api/v1/factories/test-resume-factory/resume")
    assert r.status_code == 200

    # 等待后台完成
    import time as _t
    _t.sleep(1.0)
    loaded = load_factory_state("test-resume-factory", tmp_factory_db)
    assert loaded is not None
    assert loaded.status == FactoryStatus.done


def test_resume_nonexistent_factory(client):
    r = client.post("/api/v1/factories/nonexistent/resume")
    assert r.status_code == 404


def test_resume_done_factory_is_noop(client, tmp_factory_db):
    """已完成的工厂 resume 应直接返回。"""
    state = FactoryState(
        factory_id="test-done-factory",
        product_goal="already done",
        cwd="/tmp",
        status=FactoryStatus.done,
        roadmap=[],
        max_tasks=3,
    )
    save_factory_state(state, tmp_factory_db)

    r = client.post("/api/v1/factories/test-done-factory/resume")
    assert r.status_code == 200
    assert r.json()["status"] == "done"
