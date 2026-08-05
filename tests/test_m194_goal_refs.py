"""M194.1 · goal objective 走 @ 展开 TDD 测试（消化 L-M176-4）。

POST /api/v1/assistant/sessions/{id}/goal 与 send 通路（M175）同款语义：
- GoalState.objective 用展开文本（goal set 事件 payload.objective 含文件内容，
  第 1 轮 _run_chat prompt == 展开文本）；
- 用户消息事件 payload.text 保持原文（@token 可见），有 refs 时 payload.refs
  附 FileRef asdict 清单，goal.started 标记不变；
- CreateGoalResponse.objective 保持原文（用户面向，不改响应模型）；
- FLIPPED_FILE_REFS=0 整体关闭；无活动项目（project_root() is None）零 refs 不炸；
- 断点续跑（M191 rebuild_running 从 goal set 事件 payload 重建 objective）
  取到的已是展开文本，行为自然一致。

测试风格沿用 test_m176_goal_api.py / test_m175_refs_api.py：
同步测试函数 + TestClient + ps.set_active 指项目根 + fake async 记录调用。
"""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from api.file_refs import REFS_HEADER

ZETA = "ZETA194_ANCHOR"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """隔离 DB + mock orchestrator + 防 goal/file_refs 相关 env 污染。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    monkeypatch.delenv("FLIPPED_GOAL", raising=False)
    monkeypatch.delenv("FLIPPED_GOAL_MAX_ITER", raising=False)
    monkeypatch.delenv("FLIPPED_GOAL_JUDGE", raising=False)
    monkeypatch.delenv("FLIPPED_FILE_REFS", raising=False)
    from api.main import app
    with TestClient(app) as c:
        yield c


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


def _new_session(client, mode: str = "chat") -> str:
    return client.post("/api/v1/assistant/sessions",
                       json={"title": "t", "mode": mode}).json()["id"]


def _post_goal(client, sid: str, **body):
    return client.post(f"/api/v1/assistant/sessions/{sid}/goal", json=body)


def _events(client, sid: str) -> list[dict]:
    r = client.get(f"/api/v1/sessions/{sid}/events")
    assert r.status_code == 200, r.text
    return r.json()


def _wait_task_gone(sid: str, timeout: float = 5.0) -> None:
    from api.main import RUNNING_TASKS
    deadline = time.time() + timeout
    while time.time() < deadline:
        if RUNNING_TASKS.get(sid) is None:
            return
        time.sleep(0.01)
    raise AssertionError(f"goal task 未在 {timeout}s 内结束: {sid}")


def _wait_task_present(sid: str, timeout: float = 5.0):
    from api.main import RUNNING_TASKS
    deadline = time.time() + timeout
    while time.time() < deadline:
        t = RUNNING_TASKS.get(sid)
        if t is not None:
            return t
        time.sleep(0.01)
    raise AssertionError(f"goal task 未登记: {sid}")


def _install_fakes(monkeypatch, calls: list[str]) -> None:
    """fake _run_chat（记录 description）+ fake _judge（首轮判达成即停）。"""
    async def _fake_chat(session_id, task_id, description, model_alias, mode):
        calls.append(description)

    async def _fake_judge(state, session_id, model_alias):
        return {"achieved": True, "gap": ""}

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    monkeypatch.setattr("api.assistant._judge", _fake_judge)


# ====================================================================
# 1 · goal 带 @ 文件：LLM 输入/goal set 事件用展开文本，user 消息原文 + refs
# ====================================================================

def test_goal_expands_file_ref(client, monkeypatch, project_root):
    (project_root / "readme.md").write_text(f"# {ZETA}\n项目说明\n", encoding="utf-8")
    sid = _new_session(client)
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)

    objective = "请总结 @readme.md"
    r = _post_goal(client, sid, objective=objective)
    assert r.status_code == 200, r.text
    # CreateGoalResponse.objective 保持原文（用户面向）
    assert r.json()["objective"] == objective
    _wait_task_gone(sid)

    events = _events(client, sid)

    # goal set 事件 payload.objective 含展开后的文件内容
    sets = [e for e in events if e["type"] == "goal" and e["payload"].get("phase") == "set"]
    assert len(sets) == 1
    set_objective = sets[0]["payload"]["objective"]
    assert ZETA in set_objective, "goal set 事件的 objective 必须是展开文本"
    assert REFS_HEADER in set_objective
    assert objective in set_objective, "展开文本以原文开头（追加引用段）"

    # 第 1 轮派发给 LLM 的 prompt == 展开文本（build_iter_prompt 首轮返回 state.objective）
    assert calls and ZETA in calls[0], "goal 第 1 轮 LLM 输入必须含展开后的文件内容"

    # 用户消息事件：text 原文 + goal.started 标记 + refs 元数据齐全
    users = [e for e in events if e["type"] == "message" and e["agent"] == "user"]
    assert len(users) == 1
    payload = users[0]["payload"]
    assert payload["text"] == objective, "展示层必须保持原文（@token 可见）"
    assert payload["goal"]["started"] is True
    assert payload["refs"], "有 @ 命中时 user 消息必须带 refs 元数据"
    ref = payload["refs"][0]
    assert ref["token"] == "@readme.md"
    assert ref["path"] == "readme.md"
    assert ref["status"] == "ok"
    assert ref["bytes"] > 0
    assert ref["truncated"] is False


# ====================================================================
# 2 · 无活动项目：goal 正常 200，objective 原文零 refs
# ====================================================================

def test_goal_no_project_root_passthrough(client, monkeypatch, no_project_root):
    sid = _new_session(client)
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)

    objective = "看下 @readme.md"
    r = _post_goal(client, sid, objective=objective)
    assert r.status_code == 200, r.text
    assert r.json()["objective"] == objective
    _wait_task_gone(sid)

    events = _events(client, sid)
    sets = [e for e in events if e["type"] == "goal" and e["payload"].get("phase") == "set"]
    assert sets[0]["payload"]["objective"] == objective, "无项目时 objective 必须原文透传"
    users = [e for e in events if e["type"] == "message" and e["agent"] == "user"]
    assert "refs" not in users[0]["payload"], "无项目时不准落 refs 键"


# ====================================================================
# 3 · FLIPPED_FILE_REFS=0：整体关闭，objective 原文零 refs
# ====================================================================

def test_goal_env_kill_switch_disables_expansion(client, monkeypatch, project_root):
    monkeypatch.setenv("FLIPPED_FILE_REFS", "0")
    (project_root / "readme.md").write_text(f"# {ZETA}\n", encoding="utf-8")
    sid = _new_session(client)
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)

    objective = "请总结 @readme.md"
    r = _post_goal(client, sid, objective=objective)
    assert r.status_code == 200, r.text
    _wait_task_gone(sid)

    events = _events(client, sid)
    sets = [e for e in events if e["type"] == "goal" and e["payload"].get("phase") == "set"]
    assert sets[0]["payload"]["objective"] == objective, "关闭后 goal objective 必须是原文"
    assert ZETA not in sets[0]["payload"]["objective"]
    users = [e for e in events if e["type"] == "message" and e["agent"] == "user"]
    assert "refs" not in users[0]["payload"]


# ====================================================================
# 4 · 断点续跑：rebuild_running / summarize_goal_events 重建的 objective
#     == 展开文本（M191 resume 行为自然一致，不改 resume 代码）
# ====================================================================

def test_goal_resume_rebuilds_expanded_objective(client, monkeypatch, project_root):
    (project_root / "readme.md").write_text(f"# {ZETA}\n", encoding="utf-8")
    sid = _new_session(client)

    async def _fake_chat(session_id, task_id, description, model_alias, mode):
        await asyncio.Event().wait()  # 永不返回：goal 停在 running，事件流无终态

    monkeypatch.setattr("api.main._run_chat", _fake_chat)

    objective = "请总结 @readme.md"
    r = _post_goal(client, sid, objective=objective)
    assert r.status_code == 200, r.text
    _wait_task_present(sid)

    try:
        from api.goal import rebuild_running, summarize_goal_events
        from api.main import store
        events = store.events(sid)

        rebuilt = rebuild_running(events)
        assert rebuilt is not None, "running 中的 goal 必须可重建（无终态事件）"
        state, _start = rebuilt
        assert ZETA in state.objective, "断点续跑重建的 objective 必须是展开文本"
        assert REFS_HEADER in state.objective

        info = summarize_goal_events(events)
        assert info is not None
        assert ZETA in info["objective"], "GET /goal 重建的 objective 必须是展开文本"
    finally:
        client.post(f"/api/v1/sessions/{sid}/cancel")
        _wait_task_gone(sid)
