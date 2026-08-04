"""M174 · 消息级编辑重跑端点 TDD 测试。

POST /api/v1/assistant/sessions/{session_id}/messages/{event_id}/edit
- 截断目标 user 消息及其后全部事件（复用 store.truncate_from），以新文本重派发。
- mode∈{auto,agent} 且 restore_files=True 且截断段内找到 snapshot 事件 →
  先 git restore 回滚 tracked + 删除该快照后 file_change(add/create) 的新增文件，
  再截断（fail-closed：restore 失败 500 不截断）；chat/plan 恒不碰 git。
- 重派发语义同 send_assistant_message：update_status(running) → emit status →
  emit message(user, {text, edited:True}) → auto/agent 重新 _git_snapshot →
  lazy import _run_chat/_run_orchestrator 选路 → create_task + RUNNING_TASKS 登记。
- _events_to_turns：仅 user turn 带 event_id（供前端定位编辑锚点）。

守卫：404 会话/事件不存在；422 事件非 user message / 非法 mode；
409 运行中 / pending approval。

测试风格沿用 test_assistant_api.py / test_m168_undo.py：
同步测试函数 + TestClient + monkeypatch 模块级 helper + fake async 记录调用。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """隔离 DB + mock orchestrator，返回 TestClient（同 test_assistant_api.py）。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    from api.main import app
    return TestClient(app)


@pytest.fixture()
def project_root(tmp_path):
    """把活动项目指向 tmp_path/proj（宿主侧目录），测试后清理，绝不污染全局 ps。"""
    from api import project_state as ps
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    ps.set_active(proj)
    yield proj
    ps.clear_active()


def _new_session(client, mode: str | None = None) -> str:
    body = {"title": "t"}
    if mode:
        body["mode"] = mode
    return client.post("/api/v1/assistant/sessions", json=body).json()["id"]


def _emit(sid, etype, payload, role=None):
    from api.main import bus
    from api.schemas import EventType, Role
    return bus.emit(sid, getattr(EventType, etype) if isinstance(etype, str) else etype,
                    role or Role.system, payload)


def _events(sid):
    from api.main import store
    return store.events(sid)


def _three_turns(sid) -> list[str]:
    """造 3 轮 user+assistant message 事件，返回 3 条 user 事件 id。"""
    from api.schemas import Role
    user_ids: list[str] = []
    for i in range(3):
        ev = _emit(sid, "message", {"text": f"u{i + 1}"}, Role.user)
        user_ids.append(ev.id)
        _emit(sid, "message", {"text": f"a{i + 1}"}, Role.supervisor)
    return user_ids


def _edit_url(sid: str, event_id: str) -> str:
    return f"/api/v1/assistant/sessions/{sid}/messages/{event_id}/edit"


class _FakeRunning:
    """RUNNING_TASKS 守卫只调 .done()（同 test_assistant_api.py 模式）。"""
    def done(self) -> bool:
        return False


# ====================================================================
# 1 · chat 模式编辑中间消息：截断 + 重派发 + 恒不碰 git
# ====================================================================

def test_edit_middle_message_chat_truncates_and_redispatches(client, monkeypatch):
    """chat 模式编辑第 2 条 user：truncated==4，_run_chat 被调一次且 description=新文本。"""
    sid = _new_session(client, mode="chat")
    user_ids = _three_turns(sid)
    called: dict = {}

    async def _fake_chat(session_id, task_id, description, model, mode):
        called["description"] = description
        called["model"] = model
        called["mode"] = mode

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    # chat/plan 恒 no-op：即使 restore_files 缺省 True 也不准调 git
    git_calls = {"restore": 0, "snapshot": 0}
    monkeypatch.setattr("api.assistant._git_restore",
                        lambda root, h: git_calls.__setitem__("restore", git_calls["restore"] + 1))
    monkeypatch.setattr("api.assistant._git_snapshot",
                        lambda root: git_calls.__setitem__("snapshot", git_calls["snapshot"] + 1))

    r = client.post(_edit_url(sid, user_ids[1]), json={"text": "改写 u2"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["session_id"] == sid
    assert data["task_id"].startswith("task-")
    assert data["truncated"] == 4, "user2/asst2/user3/asst3 共 4 条被截断"
    assert data["restored"] is False
    assert data["deleted"] == []
    assert called["description"] == "改写 u2"
    assert called["mode"] == "chat"
    assert git_calls == {"restore": 0, "snapshot": 0}, "chat 模式恒不执行 git 操作"


# ====================================================================
# 2 · 截断后历史：只剩前缀 + 新 edited user 消息
# ====================================================================

def test_edit_history_keeps_prefix_and_appends_edited_message(client, monkeypatch):
    """截断后 message 事件 = [u1, a1] + 新 user 消息（payload.edited=True）。"""
    sid = _new_session(client, mode="chat")
    user_ids = _three_turns(sid)

    async def _fake_chat(*args):
        return None

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    r = client.post(_edit_url(sid, user_ids[1]), json={"text": "改写 u2"})
    assert r.status_code == 200, r.text

    msgs = [e for e in _events(sid) if e.type == "message"]
    assert [m.payload["text"] for m in msgs] == ["u1", "a1", "改写 u2"]
    assert msgs[-1].agent == "user"
    assert msgs[-1].payload["edited"] is True
    # 被截断的旧消息不得残留（user2 原事件连同其后事件一并删除）
    assert all(m.payload["text"] not in ("u2", "a2", "u3", "a3") for m in msgs)


# ====================================================================
# 3 · agent 模式：找到快照 → git restore（hash 正确）+ restored=True + 重新快照
# ====================================================================

def test_edit_agent_mode_restores_snapshot_and_resnapshots(client, monkeypatch, project_root):
    """agent 模式编辑带快照的消息：_git_restore 用截断段内快照 hash，restored=True。"""
    sid = _new_session(client)  # 默认 mode=agent
    from api.schemas import Role
    u1 = _emit(sid, "message", {"text": "u1"}, Role.user)
    _emit(sid, "snapshot", {"snapshot": "snapAAA", "head": "h1", "task_id": "t-old"})
    _emit(sid, "message", {"text": "a1"}, Role.supervisor)

    calls: dict = {}
    monkeypatch.setattr("api.assistant._git_head", lambda root: "head456")

    def _restore(root, h):
        calls["root"] = root
        calls["hash"] = h

    monkeypatch.setattr("api.assistant._git_restore", _restore)
    monkeypatch.setattr("api.assistant._git_snapshot", lambda root: "snapNEW")

    async def _fake_orch(session_id, task_id, req):
        return None

    monkeypatch.setattr("api.main._run_orchestrator", _fake_orch)
    r = client.post(_edit_url(sid, u1.id), json={"text": "改写 u1"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["restored"] is True
    assert data["truncated"] == 3, "u1/snapshot/a1 共 3 条被截断"
    assert calls["hash"] == "snapAAA"
    from pathlib import Path
    assert Path(calls["root"]) == project_root
    # 重派发后重新快照（同 send 语义）：旧快照已被截断，事件流只剩新快照
    snaps = [e for e in _events(sid) if e.type == "snapshot"]
    assert len(snaps) == 1
    assert snaps[0].payload["snapshot"] == "snapNEW"
    assert snaps[0].payload["task_id"] == data["task_id"]


# ====================================================================
# 4 · agent 模式：turn 内新增文件（file_change add）在截断前被收集并删除
# ====================================================================

def test_edit_agent_mode_deletes_added_files(client, monkeypatch, project_root):
    """截断段内 file_change(add) 指向的真实文件被删除，deleted 含原始路径。"""
    sid = _new_session(client)
    from api.schemas import Role
    u1 = _emit(sid, "message", {"text": "u1"}, Role.user)
    _emit(sid, "snapshot", {"snapshot": "snapAAA", "head": "h1", "task_id": "t-old"})
    new_file = project_root / "new.py"
    new_file.write_text("x")
    _emit(sid, "file_change", {"path": "/workspace/new.py", "change": "add"}, Role.worker)
    _emit(sid, "message", {"text": "a1"}, Role.supervisor)

    monkeypatch.setattr("api.assistant._git_head", lambda root: "head456")
    monkeypatch.setattr("api.assistant._git_restore", lambda root, h: None)
    monkeypatch.setattr("api.assistant._git_snapshot", lambda root: None)

    async def _fake_orch(*args):
        return None

    monkeypatch.setattr("api.main._run_orchestrator", _fake_orch)
    r = client.post(_edit_url(sid, u1.id), json={"text": "改写"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["restored"] is True
    assert not new_file.exists(), "turn 内 add 的新文件应被删除"
    assert "/workspace/new.py" in data["deleted"]


# ====================================================================
# 5 · restore_files=False：跳过 git restore，截断/重派发照常
# ====================================================================

def test_edit_restore_files_false_skips_git_restore(client, monkeypatch, project_root):
    """restore_files=False → _git_restore 不被调，restored=False，truncated 正常。"""
    sid = _new_session(client)
    from api.schemas import Role
    u1 = _emit(sid, "message", {"text": "u1"}, Role.user)
    _emit(sid, "snapshot", {"snapshot": "snapAAA", "head": "h1", "task_id": "t-old"})
    _emit(sid, "message", {"text": "a1"}, Role.supervisor)

    calls = {"restore": 0}
    monkeypatch.setattr("api.assistant._git_restore",
                        lambda root, h: calls.__setitem__("restore", calls["restore"] + 1))
    monkeypatch.setattr("api.assistant._git_head", lambda root: "head456")
    monkeypatch.setattr("api.assistant._git_snapshot", lambda root: "snapNEW")

    async def _fake_orch(*args):
        return None

    monkeypatch.setattr("api.main._run_orchestrator", _fake_orch)
    r = client.post(_edit_url(sid, u1.id), json={"text": "改写", "restore_files": False})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["restored"] is False
    assert data["truncated"] == 3
    assert calls["restore"] == 0


# ====================================================================
# 6-9 · 守卫：409 运行中 / 409 pending approval / 404 事件 / 422 非 user 消息
# ====================================================================

def test_edit_running_task_returns_409(client):
    """RUNNING_TASKS 有未完成句柄 → 409（与 send/undo 守卫一致）。"""
    from api.main import RUNNING_TASKS
    sid = _new_session(client)
    from api.schemas import Role
    u1 = _emit(sid, "message", {"text": "u1"}, Role.user)
    RUNNING_TASKS[sid] = _FakeRunning()
    try:
        r = client.post(_edit_url(sid, u1.id), json={"text": "x"})
        assert r.status_code == 409
    finally:
        RUNNING_TASKS.pop(sid, None)


def test_edit_pending_approval_returns_409(client):
    """事件流有未回答的 approval_request → 409（复用 _has_pending_approval）。"""
    sid = _new_session(client)
    from api.schemas import Role
    u1 = _emit(sid, "message", {"text": "u1"}, Role.user)
    _emit(sid, "approval_request", {"action": "rm -rf /tmp/x", "reason": "high risk"})
    r = client.post(_edit_url(sid, u1.id), json={"text": "x"})
    assert r.status_code == 409


def test_edit_unknown_event_returns_404(client):
    """event_id 不在会话事件流里 → 404。"""
    sid = _new_session(client)
    r = client.post(_edit_url(sid, f"{sid}-999999"), json={"text": "x"})
    assert r.status_code == 404


def test_edit_assistant_message_returns_422(client):
    """目标事件是 assistant message（非 user）→ 422。"""
    sid = _new_session(client)
    from api.schemas import Role
    a1 = _emit(sid, "message", {"text": "a1"}, Role.supervisor)
    r = client.post(_edit_url(sid, a1.id), json={"text": "x"})
    assert r.status_code == 422


# ====================================================================
# 10 · _events_to_turns：仅 user turn 带 event_id
# ====================================================================

def test_events_to_turns_assigns_event_id_only_to_user_turns():
    """user turn event_id==原事件 id；assistant/tool/approval turn 保持 None。"""
    from api.assistant import _events_to_turns
    from api.schemas import Event, EventType, Role

    events = [
        Event(id="s-000001", session_id="s", type=EventType.message, agent=Role.user,
              payload={"text": "u1"}),
        Event(id="s-000002", session_id="s", type=EventType.message, agent=Role.supervisor,
              payload={"text": "a1"}),
        Event(id="s-000003", session_id="s", type=EventType.tool_call, agent=Role.worker,
              payload={"tool": "list_files", "args": {}}),
        Event(id="s-000004", session_id="s", type=EventType.tool_result, agent=Role.worker,
              payload={"status": "ok", "summary": "done"}),
        Event(id="s-000005", session_id="s", type=EventType.approval_request, agent=Role.system,
              payload={"action": "rm -rf /tmp/x"}),
        Event(id="s-000006", session_id="s", type=EventType.message, agent=Role.user,
              payload={"text": "u2"}),
    ]
    turns = _events_to_turns(events)
    user_turns = [t for t in turns if t.role == "user"]
    assert [t.event_id for t in user_turns] == ["s-000001", "s-000006"]
    for t in turns:
        if t.role != "user":
            assert t.event_id is None, f"{t.role} turn 不应带 event_id"
    # 既有字段行为不变
    assert turns[0].text == "u1"
    assert turns[1].role == "assistant" and turns[1].text == "a1"


# ====================================================================
# 11 · 守卫：404 会话不存在
# ====================================================================

def test_edit_unknown_session_returns_404(client):
    r = client.post("/api/v1/assistant/sessions/sess-nope/messages/evt-x/edit",
                    json={"text": "x"})
    assert r.status_code == 404


# ====================================================================
# 12 · 守卫：非法 mode → 422（req.mode 覆盖时走 _ALLOWED_MODES 校验）
# ====================================================================

def test_edit_invalid_mode_returns_422(client):
    sid = _new_session(client)
    from api.schemas import Role
    u1 = _emit(sid, "message", {"text": "u1"}, Role.user)
    r = client.post(_edit_url(sid, u1.id), json={"text": "x", "mode": "bogus"})
    assert r.status_code == 422
