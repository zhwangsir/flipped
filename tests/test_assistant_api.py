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


# ====================================================================
# 补测：把 assistant.py 覆盖率从 80% 提升到 90%+
# 覆盖目标行：146, 222, 297, 318-320, 330-370
# ====================================================================

# ---------- _events_to_turns 孤儿 tool_result（第 146 行）----------

def test_events_to_turns_orphan_tool_result_without_preceding_tool_call():
    """孤儿 tool_result（无前置 tool_call）→ 单独成 tool turn（覆盖第 146 行）。

    构造事件流：先发一条 user message，再直接发 tool_result（无前置 tool_call）。
    预期 tool_result 走 else 分支，单独折叠成一个 tool turn。
    """
    from api.assistant import _events_to_turns
    from api.schemas import Event, EventType, Role

    events = [
        Event(id="s-000001", session_id="s", type=EventType.message, agent=Role.user,
              payload={"text": "hi"}),
        # 直接发 tool_result，没有前置 tool_call → 触发第 146 行 else 分支
        Event(id="s-000002", session_id="s", type=EventType.tool_result, agent=Role.worker,
              payload={"tool": "orphan_tool", "status": "ok", "summary": "stale result"}),
    ]
    turns = _events_to_turns(events)
    # user message + orphan tool turn
    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[0].text == "hi"
    assert turns[1].role == "tool"
    assert turns[1].tools[0]["tool"] == "orphan_tool"
    assert turns[1].tools[0]["status"] == "ok"
    assert turns[1].tools[0]["summary"] == "stale result"


# ---------- send message 非法 mode 422（第 222 行）----------

def test_assistant_message_invalid_mode_returns_422(client):
    """send message 时 body 传 mode=bogus → 422（覆盖第 222 行）。

    既有 test_assistant_session_create_invalid_mode_returns_422 测的是 create session 端点，
    此处补测 send message 端点的同型校验（mode 取自 body 或 session）。
    """
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t"}).json()["id"]
    r = client.post(f"/api/v1/assistant/sessions/{sid}/messages",
                    json={"text": "hi", "mode": "bogus"})
    assert r.status_code == 422


# ---------- approve 409 守卫 + _has_pending_approval False 分支（第 297, 318-320 行）----------

def test_assistant_approve_without_any_approval_events_returns_409(client):
    """session 存在但事件流中无任何 approval 事件 → 409（覆盖第 297 行 + 第 320 行 return False）。

    _has_pending_approval 扫描事件流，既无 approval_request 也无 approval_result 时
    循环走完返回 False → _do_decision 抛 409。
    """
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t"}).json()["id"]
    r = client.post(f"/api/v1/assistant/sessions/{sid}/approve")
    assert r.status_code == 409
    assert "no pending approval_request" in r.json()["detail"]


def test_assistant_approve_after_approval_result_returns_409(client):
    """approval_request 后已发 approval_result → 409（覆盖第 318-319 行 return False）。

    事件流：approval_request → approval_result。_has_pending_approval 从后往前扫，
    先遇到 approval_result → 返回 False → 409（已回答过的 request 不再 pending）。
    """
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t"}).json()["id"]
    from api.main import bus
    from api.schemas import EventType, Role
    bus.emit(sid, EventType.approval_request, Role.system,
             {"action": "rm -rf /tmp/x", "reason": "high risk"})
    bus.emit(sid, EventType.approval_result, Role.system,
             {"decision": "approve", "note": "已放行"})
    r = client.post(f"/api/v1/assistant/sessions/{sid}/approve")
    assert r.status_code == 409


# ---------- _resume_with_decision 各分支（第 330-370 行）----------

def test_resume_with_decision_session_not_found_returns_early(client):
    """session 不存在 → 早退不报错（覆盖第 333-335 行）。

    _resume_with_decision 取不到 session 时直接 return，不调 resume_orchestrated。
    """
    import asyncio
    from api.assistant import _resume_with_decision
    # 不应抛异常，也不应调到 resume_orchestrated
    asyncio.run(_resume_with_decision("sess-nope", "approve"))


def test_resume_with_decision_final_none_sets_error_status(client, monkeypatch):
    """final is None → status=error + emit error event（覆盖第 357-361 行）。

    resume_orchestrated 返回 None 表示无 checkpoint，应将状态置 error 并发 error 事件。
    """
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t"}).json()["id"]

    def _fake_resume(*args, **kwargs):
        return None
    monkeypatch.setattr("driving.orchestrator.resume_orchestrated", _fake_resume)

    import asyncio
    from api.assistant import _resume_with_decision
    asyncio.run(_resume_with_decision(sid, "approve"))

    from api.main import store
    from api.schemas import SessionStatus
    session = store.get(sid)
    assert session.status == SessionStatus.error
    events = store.events(sid)
    assert any(e.type == "error" for e in events)


def test_resume_with_decision_final_verified_sets_done_status(client, monkeypatch):
    """final.get('verified')=True → status=done（覆盖第 362-363 行）。"""
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t"}).json()["id"]

    def _fake_resume(*args, **kwargs):
        return {"verified": True, "stop_reason": None}
    monkeypatch.setattr("driving.orchestrator.resume_orchestrated", _fake_resume)

    import asyncio
    from api.assistant import _resume_with_decision
    asyncio.run(_resume_with_decision(sid, "approve"))

    from api.main import store
    from api.schemas import SessionStatus
    session = store.get(sid)
    assert session.status == SessionStatus.done


@pytest.mark.parametrize("stop_reason",
                         ["worker_error", "overseer_abort", "loop_detected", "circuit_breaker"])
def test_resume_with_decision_final_error_stop_reason_sets_error_status(client, monkeypatch, stop_reason):
    """final.stop_reason 属于错误类 → status=error（覆盖第 364-365 行，4 种 stop_reason 全覆盖）。"""
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t"}).json()["id"]

    def _fake_resume(*args, **kwargs):
        return {"verified": False, "stop_reason": stop_reason}
    monkeypatch.setattr("driving.orchestrator.resume_orchestrated", _fake_resume)

    import asyncio
    from api.assistant import _resume_with_decision
    asyncio.run(_resume_with_decision(sid, "approve"))

    from api.main import store
    from api.schemas import SessionStatus
    session = store.get(sid)
    assert session.status == SessionStatus.error


def test_resume_with_decision_final_other_sets_review_status(client, monkeypatch):
    """final 既非 verified 也非错误 stop_reason → status=review（覆盖第 366-367 行）。"""
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t"}).json()["id"]

    def _fake_resume(*args, **kwargs):
        return {"verified": False, "stop_reason": "awaiting_approval"}
    monkeypatch.setattr("driving.orchestrator.resume_orchestrated", _fake_resume)

    import asyncio
    from api.assistant import _resume_with_decision
    asyncio.run(_resume_with_decision(sid, "approve"))

    from api.main import store
    from api.schemas import SessionStatus
    session = store.get(sid)
    assert session.status == SessionStatus.review


def test_resume_with_decision_exception_sets_error_status(client, monkeypatch):
    """resume_orchestrated 抛异常 → status=error + emit error event（覆盖第 368-370 行）。"""
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t"}).json()["id"]

    def _fake_resume(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr("driving.orchestrator.resume_orchestrated", _fake_resume)

    import asyncio
    from api.assistant import _resume_with_decision
    asyncio.run(_resume_with_decision(sid, "approve"))

    from api.main import store
    from api.schemas import SessionStatus
    session = store.get(sid)
    assert session.status == SessionStatus.error
    events = store.events(sid)
    error_events = [e for e in events if e.type == "error"]
    assert len(error_events) >= 1
    assert "resume failed: boom" in error_events[-1].payload["message"]


def test_resume_with_decision_real_nodes_branch(client, monkeypatch):
    """FLIPPED_MOCK_ORCHESTRATOR 未设 → 走 _build_real_nodes 分支（覆盖第 349-356 行）。

    默认 fixture 设 FLIPPED_MOCK_ORCHESTRATOR=1 走 mock 分支（341-348）；
    本测试 delenv 后走 real 分支，mock _build_real_nodes 避免真实沙盒/executor 导入。
    """
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t"}).json()["id"]

    # 切换到 real 分支
    monkeypatch.delenv("FLIPPED_MOCK_ORCHESTRATOR")

    _fake_nodes_called = {"called": False}

    def _fake_build(session_id, cwd, verify_cmd):
        _fake_nodes_called["called"] = True
        return {
            "supervisor": lambda s: {},
            "worker": lambda s: {},
            "overseer": lambda s: {},
            "verifier": lambda c, w: (True, "ok"),
        }
    monkeypatch.setattr("api.main._build_real_nodes", _fake_build)

    def _fake_resume(*args, **kwargs):
        return {"verified": True, "stop_reason": None}
    monkeypatch.setattr("driving.orchestrator.resume_orchestrated", _fake_resume)

    import asyncio
    from api.assistant import _resume_with_decision
    asyncio.run(_resume_with_decision(sid, "approve"))

    assert _fake_nodes_called["called"] is True
    from api.main import store
    from api.schemas import SessionStatus
    session = store.get(sid)
    assert session.status == SessionStatus.done
