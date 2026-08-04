"""M165.1b + M165.2b · assistant compact 端点 + approve scope=always 持久化审批 TDD 测试。

覆盖：
- approve/reject 可选 body {"scope": "once"|"always"}（无 body 向后兼容；bogus → 422）
- approve scope=always → 最近 pending approval_request 的 action 持久化到宿主侧
  grants 文件（data/approval_grants.json，env FLIPPED_HOST_GRANTS 可覆盖），
  严禁写 session.cwd/.flipped（容器路径）
- reject scope=always → 200 且 scope 被忽略（不落盘）
- orchestrator approval_gate：宿主侧 grants fnmatch 命中 current_subtask → auto 直通
  不 interrupt；未命中 → 维持 interrupt 行为
- compact 端点：404（无会话）/ 409（无 message 事件）/ 200 + CompactResponse +
  bus emit "[compact] 摘要" / 摘要异常 → 5xx 且不 emit（fail-closed）
- remember_host_grant / load_host_grants 单测：幂等去重、损坏文件 fail-open、多 cwd 隔离

设计原则：
- grants 路径一律用 env FLIPPED_HOST_GRANTS 指向 tmp_path，绝不写真 data/
- store/bus mock 模式复用 test_assistant_api.py（FLIPPED_MOCK_ORCHESTRATOR=1 + TestClient）
- approval_gate 用 build_orchestrator + InMemorySaver 单测（与 test_orchestrator.py 同型）
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """隔离 DB + mock orchestrator，返回 TestClient。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    from api.main import app
    return TestClient(app)


@pytest.fixture()
def grants_file(monkeypatch, tmp_path):
    """把宿主侧 grants 路径指到 tmp_path，返回路径。绝不写真 data/。"""
    path = tmp_path / "approval_grants.json"
    monkeypatch.setenv("FLIPPED_HOST_GRANTS", str(path))
    return path


def _make_session_with_pending_approval(client) -> str:
    """建会话 + emit 一条 pending approval_request（approve/reject 的 409 守卫前提）。"""
    sid = client.post("/api/v1/assistant/sessions", json={"title": "t"}).json()["id"]
    from api.main import bus
    from api.schemas import EventType, Role
    bus.emit(sid, EventType.approval_request, Role.system,
             {"action": "git push origin main", "reason": "high risk"})
    return sid


def _stub_resume(monkeypatch):
    called = {"decision": None}

    async def _fake_resume(session_id, decision):
        called["decision"] = decision

    monkeypatch.setattr("api.assistant._resume_with_decision", _fake_resume)
    return called


# ====================================================================
# M165.2b · approve/reject scope body
# ====================================================================

def test_approve_without_body_backward_compatible(client, monkeypatch):
    """无 body 的 approve → 200（向后兼容，scope 缺省 once）。"""
    sid = _make_session_with_pending_approval(client)
    called = _stub_resume(monkeypatch)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/approve")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["decision"] == "approve"
    assert called["decision"] == "approve"


def test_approve_scope_once_does_not_persist(client, monkeypatch, grants_file):
    """显式 scope=once → 200，但不写宿主侧 grants 文件。"""
    sid = _make_session_with_pending_approval(client)
    _stub_resume(monkeypatch)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/approve", json={"scope": "once"})
    assert r.status_code == 200, r.text
    assert not grants_file.exists(), "scope=once 不应持久化 grants"


def test_approve_scope_always_persists_host_grant(client, monkeypatch, grants_file):
    """approve scope=always → 200 且最近 pending approval_request 的 action 落宿主侧 grants。"""
    sid = _make_session_with_pending_approval(client)
    _stub_resume(monkeypatch)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/approve", json={"scope": "always"})
    assert r.status_code == 200, r.text
    assert grants_file.exists(), "scope=always 应创建宿主侧 grants 文件"
    data = json.loads(grants_file.read_text(encoding="utf-8"))
    # session.cwd 缺省 "/workspace"（assistant 创建端点不传 cwd）→ 以该字符串为 key
    assert data == {"/workspace": ["git push origin main"]}


def test_approve_scope_bogus_returns_422(client, monkeypatch):
    """scope 非法值 → pydantic 校验失败 422。"""
    sid = _make_session_with_pending_approval(client)
    _stub_resume(monkeypatch)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/approve", json={"scope": "bogus"})
    assert r.status_code == 422


def test_reject_scope_always_ignored(client, monkeypatch, grants_file):
    """reject + scope=always → 200，scope 被忽略（不落盘 grants）。"""
    sid = _make_session_with_pending_approval(client)
    called = _stub_resume(monkeypatch)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/reject", json={"scope": "always"})
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == "reject"
    assert called["decision"] == "reject"
    assert not grants_file.exists(), "reject 不应持久化 grants"


# ====================================================================
# M165.2b · orchestrator approval_gate 接宿主侧 grants
# ====================================================================

def _build_gate_graph():
    """构建 approval_gate 测试图：supervisor 恒产高风险子任务（git push）。

    与 test_orchestrator.py::_approval_graph 同型：verify 通过后 supervisor 检测到
    "已完成且验证通过" 标记 → believe_done=True 收束循环。
    """
    from langgraph.checkpoint.memory import InMemorySaver
    from driving.orchestrator import build_orchestrator

    c = {"work": 0}

    def supervisor(state):
        result = {"current_subtask": "git push origin main", "believe_done": False,
                  "history": state.get("history", []) + [{"step": "supervisor"}]}
        fb = state.get("feedback", "")
        if state.get("iteration", 0) >= 1 and "已完成且验证通过" in fb:
            result["believe_done"] = True
        return result

    def worker(state):
        c["work"] += 1
        return {"last_obs": {"summary": {}}, "signatures": state.get("signatures", []) + ["s"],
                "history": state.get("history", []) + [{"step": "worker"}]}

    def overseer(state):
        return {"verdict": {"action": "continue"},
                "history": state.get("history", []) + [{"step": "overseer"}]}

    def verifier(cmd, cwd):
        return True, ""

    g = build_orchestrator(supervisor, worker, overseer, verifier,
                           checkpointer=InMemorySaver())
    init = {"goal": "G", "cwd": "/tmp", "verify_cmd": ["true"], "max_iterations": 3,
            "loop_threshold": 3, "require_approval": True, "iteration": 0,
            "signatures": [], "feedback": "", "verified": False,
            "done": False, "stop_reason": "", "history": []}
    return g, init, c


def test_approval_gate_host_grant_hit_auto_passes_without_interrupt(grants_file):
    """宿主侧 grants fnmatch 命中 current_subtask → auto 直通：不 interrupt、worker 直接执行。"""
    grants_file.write_text(json.dumps({"/tmp": ["git push*"]}), encoding="utf-8")
    g, init, c = _build_gate_graph()
    cfg = {"configurable": {"thread_id": "m165-grant-hit"}}
    res = g.invoke(init, cfg)
    assert "__interrupt__" not in res, "grants 命中应直通，不应 interrupt"
    assert c["work"] >= 1, "grants 命中应直通到 worker"
    assert res.get("verified") is True


def test_approval_gate_host_grant_miss_still_interrupts(grants_file):
    """宿主侧 grants 未命中（pattern 不匹配）→ 维持 interrupt 行为。"""
    grants_file.write_text(json.dumps({"/tmp": ["docker *"]}), encoding="utf-8")
    g, init, c = _build_gate_graph()
    cfg = {"configurable": {"thread_id": "m165-grant-miss"}}
    res = g.invoke(init, cfg)
    assert "__interrupt__" in res, "grants 未命中应照常 interrupt"
    assert c["work"] == 0, "interrupt 前 worker 不应执行"


def test_approval_gate_host_grant_other_cwd_still_interrupts(grants_file):
    """grants 里有 pattern 但挂在别的 cwd 下 → 多 cwd 隔离，照常 interrupt。"""
    grants_file.write_text(json.dumps({"/other": ["git push*"]}), encoding="utf-8")
    g, init, c = _build_gate_graph()
    cfg = {"configurable": {"thread_id": "m165-grant-other-cwd"}}
    res = g.invoke(init, cfg)
    assert "__interrupt__" in res, "别的 cwd 的 grant 不应放行本 cwd"
    assert c["work"] == 0


# ====================================================================
# M165.2b · remember_host_grant / load_host_grants 单测
# ====================================================================

def test_remember_host_grant_idempotent_and_multi_cwd(grants_file):
    """幂等去重 + 多 cwd 隔离 + 文件结构 {"<cwd>": [patterns]}。"""
    from driving.approval import load_host_grants, remember_host_grant

    g1 = remember_host_grant("/workspace", "git push*")
    g2 = remember_host_grant("/workspace", "git push*")
    assert g1 == ["git push*"]
    assert g2 == ["git push*"], "重复写入应幂等去重"

    remember_host_grant("/workspace", "npm publish*")
    remember_host_grant("/projects/x", "docker *")

    assert load_host_grants("/workspace") == ["git push*", "npm publish*"]
    assert load_host_grants("/projects/x") == ["docker *"]
    assert load_host_grants("/nonexistent") == []

    data = json.loads(grants_file.read_text(encoding="utf-8"))
    assert data == {"/workspace": ["git push*", "npm publish*"],
                    "/projects/x": ["docker *"]}


def test_load_host_grants_missing_and_corrupt_fail_open(grants_file):
    """文件缺失/损坏/结构不对 → 空列表（fail-open）。"""
    from driving.approval import load_host_grants, remember_host_grant

    assert load_host_grants("/workspace") == [], "文件缺失 → 空"

    grants_file.write_text("not json{{{", encoding="utf-8")
    assert load_host_grants("/workspace") == [], "损坏 JSON → 空"

    grants_file.write_text(json.dumps(["git push*"]), encoding="utf-8")
    assert load_host_grants("/workspace") == [], "顶层不是 dict → 空"

    # 损坏文件上 remember 应能自愈重写（不丢失本次 pattern）
    grants_file.write_text("not json{{{", encoding="utf-8")
    grants = remember_host_grant("/workspace", "git push*")
    assert grants == ["git push*"]
    assert load_host_grants("/workspace") == ["git push*"]


# ====================================================================
# M165.1b · compact 端点
# ====================================================================

def test_compact_unknown_session_returns_404(client):
    r = client.post("/api/v1/assistant/sessions/sess-nope/compact")
    assert r.status_code == 404


def test_compact_empty_history_returns_409(client):
    """会话存在但事件流中无 message 事件 → 409。"""
    sid = client.post("/api/v1/assistant/sessions", json={"title": "t"}).json()["id"]
    r = client.post(f"/api/v1/assistant/sessions/{sid}/compact")
    assert r.status_code == 409


def test_compact_success_emits_supervisor_compact_message(client, monkeypatch):
    """有 message 历史 + 摘要函数注入 → 200 + CompactResponse + bus 事件含 "[compact] 摘要"。"""
    sid = client.post("/api/v1/assistant/sessions", json={"title": "t"}).json()["id"]
    from api.main import bus
    from api.schemas import EventType, Role
    bus.emit(sid, EventType.message, Role.user, {"text": "帮我重构 login 模块"})
    bus.emit(sid, EventType.message, Role.supervisor, {"text": "已拆成 3 个子任务"})

    seen = {"transcript": None, "model": None}

    async def _fake_summarize(transcript: str, model: str) -> str:
        seen["transcript"] = transcript
        seen["model"] = model
        return "摘要"

    monkeypatch.setattr("api.assistant._summarize_transcript", _fake_summarize)

    r = client.post(f"/api/v1/assistant/sessions/{sid}/compact")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["session_id"] == sid
    assert data["summary"] == "摘要"

    # transcript 折叠：user/assistant 分行
    assert "user: 帮我重构 login 模块" in seen["transcript"]
    assert "assistant: 已拆成 3 个子任务" in seen["transcript"]

    # bus 事件：supervisor 发出的 "[compact] 摘要"（前端 history 折叠呈现为 assistant turn）
    from api.main import store
    events = store.events(sid)
    compact_events = [e for e in events
                      if e.type == "message" and "[compact] 摘要" in e.payload.get("text", "")]
    assert len(compact_events) == 1
    assert compact_events[0].agent == "supervisor"


def test_compact_summarize_failure_returns_5xx_and_does_not_emit(client, monkeypatch):
    """摘要函数抛异常 → 5xx 且不 emit（fail-closed，别 emit 半截）。"""
    sid = client.post("/api/v1/assistant/sessions", json={"title": "t"}).json()["id"]
    from api.main import bus
    from api.schemas import EventType, Role
    bus.emit(sid, EventType.message, Role.user, {"text": "hello"})

    async def _boom(transcript: str, model: str) -> str:
        raise RuntimeError("model down")

    monkeypatch.setattr("api.assistant._summarize_transcript", _boom)

    r = client.post(f"/api/v1/assistant/sessions/{sid}/compact")
    assert r.status_code in (500, 502), r.text

    from api.main import store
    events = store.events(sid)
    assert not any("[compact]" in e.payload.get("text", "") for e in events), \
        "摘要失败不应 emit 任何 [compact] 事件"
