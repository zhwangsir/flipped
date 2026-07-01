"""B5 审批流后端集成测试（TestClient，无需真实 socket 绑定）。

当前 Codex 执行环境无法 bind TCP 端口，因此用 FastAPI TestClient 在进程内验证
approval_request / approval_result 状态机；真实浏览器/WS E2E 仍由
scripts/verify_b5.sh 在可 bind 端口的宿主环境中覆盖。
"""
import importlib
import os
import time

import pytest
from fastapi.testclient import TestClient

# 必须在导入 src.api.main 前设置 mock 开关，否则 main.MOCK_WORKER 在模块加载时固化。
os.environ["FLIPPED_MOCK_WORKER"] = "1"
os.environ["FLIPPED_MOCK_APPROVAL"] = "1"

from src.api.schemas import EventType, Role  # noqa: E402
import src.api.main as _main  # noqa: E402
import src.api.session as _session  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    """每个测试独立 app + bus，store 为单例（按 session_id 隔离）。"""
    monkeypatch.setenv("FLIPPED_MOCK_WORKER", "1")
    monkeypatch.setenv("FLIPPED_MOCK_APPROVAL", "1")
    importlib.reload(_main)
    with TestClient(_main.app) as tc:
        yield tc


def _wait_for_event(session_id: str, event_type: str, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for ev in reversed(_session.store.events(session_id)):
            if ev.type == event_type:
                return ev
        time.sleep(0.05)
    return None


def _wait_for_status(session_id: str, value: str, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for ev in reversed(_session.store.events(session_id)):
            if ev.type == EventType.status and ev.payload.get("status") == value:
                return ev
        time.sleep(0.05)
    return None


def test_approval_flow_approve(client):
    r = client.post("/api/v1/sessions?title=B5 Approval")
    assert r.status_code == 200
    sid = r.json()["id"]

    r = client.post(
        f"/api/v1/sessions/{sid}/tasks",
        json={"description": "create app.py and test it"},
    )
    assert r.status_code == 200

    approval = _wait_for_event(sid, EventType.approval_request)
    assert approval is not None, "expected approval_request event"

    # 模拟前端发送 approval_result
    _main.bus.emit(
        sid,
        EventType.approval_result,
        Role.user,
        {"decision": "approve", "reason": "test"},
    )

    status = _wait_for_status(sid, "done")
    assert status is not None, "expected final status done"
    assert status.payload["status"] == "done"


def test_approval_flow_reject(client):
    r = client.post("/api/v1/sessions?title=B5 Reject")
    assert r.status_code == 200
    sid = r.json()["id"]

    r = client.post(
        f"/api/v1/sessions/{sid}/tasks",
        json={"description": "create app.py and test it"},
    )
    assert r.status_code == 200

    approval = _wait_for_event(sid, EventType.approval_request)
    assert approval is not None

    _main.bus.emit(
        sid,
        EventType.approval_result,
        Role.user,
        {"decision": "reject", "reason": "test"},
    )

    status = _wait_for_status(sid, "review")
    assert status is not None, "expected status review"
    assert status.payload["status"] == "review"

    error = _wait_for_event(sid, EventType.error)
    assert error is not None, "expected error event"
