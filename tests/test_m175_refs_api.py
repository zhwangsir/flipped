"""M175 · @ 文件引用接线进 assistant 发送通路 TDD 测试。

POST /api/v1/assistant/sessions/{id}/messages 接线语义：
- 发送前 expand_file_refs(req.text, ps.project_root())：LLM 输入用展开文本
  （TaskRequest.description / _run_chat 的 description），展示层 user message
  事件 payload.text 保持原文（@token 可见），payload.refs 附 FileRef asdict 清单。
- FLIPPED_FILE_REFS=0 整体关闭；fail-open：展开抛任何异常 = 不展开正常派发。
- AssistantTurn.refs（仅 user turn）从事件 payload 透传，无 refs 时保持 None。

测试风格沿用 test_m174_edit_rerun.py：
同步测试函数 + TestClient + project_state.set_active 指项目根 + fake async 记录调用。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.file_refs import REFS_HEADER

ZETA = "ZETA175_ANCHOR"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """隔离 DB + mock orchestrator，返回 TestClient（同 test_m174_edit_rerun.py）。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    # 默认开启 M175（防外部环境变量污染），个别用例自行 setenv("0")
    monkeypatch.delenv("FLIPPED_FILE_REFS", raising=False)
    from api.main import app
    return TestClient(app)


@pytest.fixture()
def project_root(tmp_path):
    """把活动项目指向 tmp_path/proj，测试后清理，绝不污染全局 ps。"""
    from api import project_state as ps
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    ps.set_active(proj)
    yield proj
    ps.clear_active()


@pytest.fixture()
def no_project_root():
    """确保无活动项目（project_root() 返回 None），测后恢复清理。"""
    from api import project_state as ps
    ps.clear_active()
    yield
    ps.clear_active()


def _new_session(client, mode: str | None = None) -> str:
    body = {"title": "t"}
    if mode:
        body["mode"] = mode
    return client.post("/api/v1/assistant/sessions", json=body).json()["id"]


def _send(client, sid: str, text: str):
    return client.post(f"/api/v1/assistant/sessions/{sid}/messages", json={"text": text})


def _history(client, sid: str) -> list[dict]:
    r = client.get(f"/api/v1/assistant/sessions/{sid}/history")
    assert r.status_code == 200, r.text
    return r.json()


def _user_turns(turns: list[dict]) -> list[dict]:
    return [t for t in turns if t["role"] == "user"]


# ====================================================================
# 1 · chat 通路：@hello.py 被展开进 LLM 输入（description 含内容锚点 + REFS_HEADER）
# ====================================================================

def test_chat_expands_file_ref_into_llm_input(client, monkeypatch, project_root):
    """fake _run_chat 收到的 description 含 ZETA175 锚点与 REFS_HEADER。"""
    (project_root / "hello.py").write_text(f"# {ZETA}\nprint('hi')\n", encoding="utf-8")
    sid = _new_session(client, mode="chat")
    called: dict = {}

    async def _fake_chat(session_id, task_id, description, model_alias, mode,
                         *, rag_auto=True, map_auto=True):
        called["description"] = description

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    r = _send(client, sid, "看下 @hello.py")
    assert r.status_code == 200, r.text
    assert ZETA in called["description"], "@ 引用文件内容必须注入 LLM 输入"
    assert REFS_HEADER in called["description"]
    assert "看下 @hello.py" in called["description"], "展开文本以原文开头（追加引用段）"


# ====================================================================
# 2 · user 事件保持原文 + refs 元数据（history turn 视图）
# ====================================================================

def test_user_event_keeps_original_text_and_carries_refs(client, monkeypatch, project_root):
    """history user turn：text==原文；refs[0] path/status/bytes 正确。"""
    (project_root / "hello.py").write_text(f"# {ZETA}\n", encoding="utf-8")
    sid = _new_session(client, mode="chat")

    async def _fake_chat(*args, **kwargs):
        return None

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    r = _send(client, sid, "看下 @hello.py")
    assert r.status_code == 200, r.text

    users = _user_turns(_history(client, sid))
    assert len(users) == 1
    turn = users[0]
    assert turn["text"] == "看下 @hello.py", "展示层必须保持原文（@token 可见）"
    assert turn["refs"], "user turn 必须带 refs 元数据"
    ref = turn["refs"][0]
    assert ref["path"] == "hello.py"
    assert ref["status"] == "ok"
    assert ref["bytes"] > 0
    assert ref["token"] == "@hello.py"
    assert ref["truncated"] is False


# ====================================================================
# 3 · missing：@ 不存在的文件 → refs[0].status == "missing"
# ====================================================================

def test_missing_file_ref_status(client, monkeypatch, project_root):
    sid = _new_session(client, mode="chat")

    async def _fake_chat(*args, **kwargs):
        return None

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    r = _send(client, sid, "看下 @nofile.py")
    assert r.status_code == 200, r.text

    users = _user_turns(_history(client, sid))
    assert users[0]["refs"][0]["status"] == "missing"
    assert users[0]["refs"][0]["path"] == "nofile.py"


# ====================================================================
# 4 · agent 通路：TaskRequest.description 同样拿到展开文本
# ====================================================================

def test_agent_mode_expands_file_ref_into_task_request(client, monkeypatch, project_root):
    """mode=agent：fake _run_orchestrator 收到的 TaskRequest.description 含锚点。"""
    (project_root / "hello.py").write_text(f"# {ZETA}\n", encoding="utf-8")
    sid = _new_session(client, mode="agent")
    called: dict = {}

    async def _fake_orch(session_id, task_id, req):
        called["description"] = req.description

    monkeypatch.setattr("api.main._run_orchestrator", _fake_orch)
    r = _send(client, sid, "看下 @hello.py")
    assert r.status_code == 200, r.text
    assert ZETA in called["description"]
    assert REFS_HEADER in called["description"]


# ====================================================================
# 5 · FLIPPED_FILE_REFS=0：整体关闭，description==原文，turn.refs 为 None
# ====================================================================

def test_env_kill_switch_disables_expansion(client, monkeypatch, project_root):
    monkeypatch.setenv("FLIPPED_FILE_REFS", "0")
    (project_root / "hello.py").write_text(f"# {ZETA}\n", encoding="utf-8")
    sid = _new_session(client, mode="chat")
    called: dict = {}

    async def _fake_chat(session_id, task_id, description, model_alias, mode,
                         *, rag_auto=True, map_auto=True):
        called["description"] = description

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    r = _send(client, sid, "看下 @hello.py")
    assert r.status_code == 200, r.text
    assert called["description"] == "看下 @hello.py", "关闭后 LLM 输入必须是原文"
    users = _user_turns(_history(client, sid))
    assert users[0]["refs"] is None


# ====================================================================
# 6 · 无项目 root：透传不炸，refs 为空
# ====================================================================

def test_no_project_root_passthrough(client, monkeypatch, no_project_root):
    sid = _new_session(client, mode="chat")
    called: dict = {}

    async def _fake_chat(session_id, task_id, description, model_alias, mode,
                         *, rag_auto=True, map_auto=True):
        called["description"] = description

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    r = _send(client, sid, "看下 @hello.py")
    assert r.status_code == 200, r.text
    assert called["description"] == "看下 @hello.py"
    users = _user_turns(_history(client, sid))
    assert users[0]["refs"] is None


# ====================================================================
# 7 · fail-open：expand_file_refs 抛异常 → 消息仍正常派发，description==原文
# ====================================================================

def test_expand_exception_fail_open(client, monkeypatch, project_root):
    (project_root / "hello.py").write_text(f"# {ZETA}\n", encoding="utf-8")
    sid = _new_session(client, mode="chat")
    called: dict = {}

    def _boom(text, root, **kwargs):
        raise RuntimeError("boom-175")

    monkeypatch.setattr("api.file_refs.expand_file_refs", _boom)

    async def _fake_chat(session_id, task_id, description, model_alias, mode,
                         *, rag_auto=True, map_auto=True):
        called["description"] = description

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    r = _send(client, sid, "看下 @hello.py")
    assert r.status_code == 200, r.text
    assert called["description"] == "看下 @hello.py", "fail-open：异常时必须透传原文"
    users = _user_turns(_history(client, sid))
    assert users[0]["refs"] is None


# ====================================================================
# 8 · turns 透传：无 refs 的普通消息 turn.refs 保持 None（现状形状不变）
# ====================================================================

def test_plain_message_turn_has_no_refs(client, monkeypatch, project_root):
    sid = _new_session(client, mode="chat")

    async def _fake_chat(*args, **kwargs):
        return None

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    r = _send(client, sid, "普通消息，没有引用")
    assert r.status_code == 200, r.text

    users = _user_turns(_history(client, sid))
    assert len(users) == 1
    assert users[0]["text"] == "普通消息，没有引用"
    assert users[0]["refs"] is None


# ====================================================================
# 9 · 邮箱假阳性端到端："user@example.com" 不命中 token，refs 为空
# ====================================================================

def test_email_like_text_is_not_a_ref(client, monkeypatch, project_root):
    sid = _new_session(client, mode="chat")
    called: dict = {}

    async def _fake_chat(session_id, task_id, description, model_alias, mode,
                         *, rag_auto=True, map_auto=True):
        called["description"] = description

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    r = _send(client, sid, "找 user@example.com 聊聊")
    assert r.status_code == 200, r.text
    assert called["description"] == "找 user@example.com 聊聊"
    users = _user_turns(_history(client, sid))
    assert users[0]["refs"] is None
