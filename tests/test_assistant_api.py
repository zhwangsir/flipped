"""M151.1 · 代码助手 assistant router TDD 测试。

覆盖 /api/v1/assistant/* 端点：
- POST /sessions          创建助手会话（默认 mode=agent）
- POST /sessions/{id}/messages  发送消息（mode 路由 orchestrator/chat）
- POST /sessions/{id}/approve   审批放行
- POST /sessions/{id}/reject    审批否决
- GET  /sessions/{id}/history   事件流折叠为对话 turns

设计原则：
- 复用既有 store / bus / RUNNING_TASKS / _run_orchestrator / _run_chat，不重写
- 不破坏既有 /api/v1/sessions 端点（回归守门）
- 并发守卫同既有 /tasks（409）
- FLIPPED_MOCK_ORCHESTRATOR=1 走 mock 路径，免沙盒免模型
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

# 延迟 import：conftest 已设 FLIPPED_SESSION_STORE_PATH


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """隔离 DB + mock orchestrator，返回 TestClient。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    from api.main import app
    return TestClient(app)


# ---------- _events_to_turns 纯函数 ----------

def test_events_to_turns_groups_events_into_conversational_turns():
    """纯函数：把 Event 流折叠成 user/assistant/tool/approval 四类 turn。"""
    from api.assistant import _events_to_turns
    from api.schemas import Event, EventType, Role

    events = [
        Event(id="s-000001", session_id="s", type=EventType.message, agent=Role.user,
              payload={"text": "list files"}),
        Event(id="s-000002", session_id="s", type=EventType.message, agent=Role.supervisor,
              payload={"text": "我来调度"}),
        Event(id="s-000003", session_id="s", type=EventType.tool_call, agent=Role.worker,
              payload={"tool": "list_files", "args": {"path": "src"}}),
        Event(id="s-000004", session_id="s", type=EventType.tool_result, agent=Role.worker,
              payload={"status": "ok", "summary": "92 files"}),
        Event(id="s-000005", session_id="s", type=EventType.approval_request, agent=Role.system,
              payload={"action": "rm -rf /tmp/x", "reason": "high risk"}),
        Event(id="s-000006", session_id="s", type=EventType.message, agent=Role.verify,
              payload={"text": "验收通过"}),
    ]
    turns = _events_to_turns(events)
    # 6 个事件 → 5 个 turn（tool_call+tool_result 合并成一个 tool turn）
    assert len(turns) == 5
    assert turns[0].role == "user"
    assert turns[0].text == "list files"
    # supervisor/worker/overseer/verify 统一映射为 assistant
    assert turns[1].role == "assistant"
    assert turns[1].text == "我来调度"
    # tool turn
    assert turns[2].role == "tool"
    assert turns[2].tools[0]["tool"] == "list_files"
    assert turns[2].tools[0]["status"] == "ok"
    # approval turn
    assert turns[3].role == "approval"
    assert turns[3].approval["action"] == "rm -rf /tmp/x"
    # verify 仍映射为 assistant
    assert turns[4].role == "assistant"
    assert turns[4].text == "验收通过"


# ---------- POST /api/v1/assistant/sessions ----------

def test_assistant_session_create_returns_id_with_mode_agent(client):
    """默认创建 mode=agent 的助手会话，返回 Session。"""
    r = client.post("/api/v1/assistant/sessions", json={"title": "帮我读文件"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"].startswith("sess-")
    assert data["mode"] == "agent"
    assert data["status"] == "idle"


def test_assistant_session_create_accepts_mode_override_chat(client):
    """body 传 mode=chat 时会话 mode=chat。"""
    r = client.post("/api/v1/assistant/sessions",
                    json={"title": "随便聊聊", "mode": "chat"})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "chat"


def test_assistant_session_create_invalid_mode_returns_422(client):
    """非法 mode 走 Pydantic 校验失败 → 422（不是 404）。"""
    r = client.post("/api/v1/assistant/sessions",
                    json={"title": "x", "mode": "bogus"})
    assert r.status_code == 422


# ---------- POST /api/v1/assistant/sessions/{id}/messages ----------

def test_assistant_message_dispatches_orchestrator_and_returns_task_id(client):
    """mode=agent + FLIPPED_MOCK_ORCHESTRATOR=1 → 派发返回 task_id。"""
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t"}).json()["id"]
    r = client.post(f"/api/v1/assistant/sessions/{sid}/messages",
                    json={"text": "list files in src/"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["session_id"] == sid
    assert data["task_id"].startswith("task-")


def test_assistant_message_unknown_session_returns_404(client):
    r = client.post("/api/v1/assistant/sessions/sess-nope/messages",
                    json={"text": "hi"})
    assert r.status_code == 404


def test_assistant_message_concurrent_dispatch_returns_409(client):
    """同会话已有未完成任务时拒绝重复派发（与既有 /tasks 守卫一致）。"""
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t"}).json()["id"]
    # 塞一个「未完成」假对象进 RUNNING_TASKS：守卫只调 .done()，无需真实 Task
    # （同步测试函数无 running loop，不能 asyncio.create_task）
    from api.main import RUNNING_TASKS

    class _FakeRunning:
        def done(self) -> bool:
            return False

    RUNNING_TASKS[sid] = _FakeRunning()
    try:
        r = client.post(f"/api/v1/assistant/sessions/{sid}/messages",
                        json={"text": "second"})
        assert r.status_code == 409
    finally:
        RUNNING_TASKS.pop(sid, None)


def test_assistant_message_mode_chat_routes_to_run_chat(client, monkeypatch):
    """mode=chat → 调 _run_chat（不走 orchestrator）。monkeypatch api.main._run_chat 验证。"""
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t", "mode": "chat"}).json()["id"]
    called = {"chat": False}

    async def _fake_chat(session_id, task_id, description, model, mode):
        called["chat"] = True
        called["model"] = model
        called["mode"] = mode

    # assistant.py 函数级 lazy import `from .main import _run_chat`，故 patch 源头 api.main
    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/messages",
                    json={"text": "hi", "mode": "chat", "model": "coder"})
    assert r.status_code == 200, r.text
    assert called["chat"] is True
    assert called["model"] == "coder"
    assert called["mode"] == "chat"


# ---------- GET /api/v1/assistant/sessions/{id}/history ----------

def test_assistant_history_unknown_session_returns_404(client):
    r = client.get("/api/v1/assistant/sessions/sess-nope/history")
    assert r.status_code == 404


def test_assistant_history_returns_turns_for_existing_session(client):
    """已有事件的会话 → history 端点返回折叠后的 turns。"""
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t"}).json()["id"]
    from api.main import bus
    from api.schemas import EventType, Role
    bus.emit(sid, EventType.message, Role.user, {"text": "hello"})
    bus.emit(sid, EventType.message, Role.supervisor, {"text": "hi back"})

    r = client.get(f"/api/v1/assistant/sessions/{sid}/history")
    assert r.status_code == 200, r.text
    turns = r.json()
    assert len(turns) == 2
    assert turns[0]["role"] == "user"
    assert turns[0]["text"] == "hello"
    assert turns[1]["role"] == "assistant"
    assert turns[1]["text"] == "hi back"


# ---------- POST /api/v1/assistant/sessions/{id}/approve | reject ----------

def test_assistant_approve_unknown_session_returns_404(client):
    r = client.post("/api/v1/assistant/sessions/sess-nope/approve")
    assert r.status_code == 404


def test_assistant_approve_emits_approval_result_event_and_calls_resume(client, monkeypatch):
    """approve → 调 _resume_with_decision('approve') + 发 approval_result 事件。"""
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t"}).json()["id"]
    called = {"decision": None}

    async def _fake_resume(session_id, decision):
        called["decision"] = decision

    # M151.2：approve 需有 pending approval_request 才放行（409 守卫），先 emit 一个
    from api.main import bus
    from api.schemas import EventType, Role
    bus.emit(sid, EventType.approval_request, Role.system,
             {"action": "rm -rf /tmp/x", "reason": "high risk"})

    monkeypatch.setattr("api.assistant._resume_with_decision", _fake_resume)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/approve")
    assert r.status_code == 200, r.text
    assert called["decision"] == "approve"
    # 验证 approval_result 事件落库
    from api.main import store
    events = store.events(sid)
    types = [e.type for e in events]
    assert "approval_result" in types


def test_assistant_reject_calls_resume_with_reject(client, monkeypatch):
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t"}).json()["id"]
    called = {"decision": None}

    async def _fake_resume(session_id, decision):
        called["decision"] = decision

    # M151.2：reject 同样需 pending approval_request
    from api.main import bus
    from api.schemas import EventType, Role
    bus.emit(sid, EventType.approval_request, Role.system,
             {"action": "rm -rf /tmp/x", "reason": "high risk"})

    monkeypatch.setattr("api.assistant._resume_with_decision", _fake_resume)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/reject")
    assert r.status_code == 200, r.text
    assert called["decision"] == "reject"


# ---------- 回归：不破坏既有 /api/v1/sessions ----------

def test_assistant_router_does_not_break_existing_sessions_endpoint(client):
    """新 router 挂载后，既有 GET /api/v1/sessions 仍可用。"""
    # 先经 assistant 创建一个会话
    client.post("/api/v1/assistant/sessions", json={"title": "via assistant"})
    # 既有端点应能看到
    r = client.get("/api/v1/sessions")
    assert r.status_code == 200
    sessions = r.json()
    assert any(s["title"] == "via assistant" for s in sessions)
