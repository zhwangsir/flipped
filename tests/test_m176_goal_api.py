"""M176.2 · Goal 模式后端接线 TDD 测试（B 队）。

POST /api/v1/assistant/sessions/{id}/goal：
- FLIPPED_GOAL=0 → 404；会话不存在 → 404；RUNNING_TASKS 守卫 → 409；非法 mode → 422
- emit message(user, {text, goal.started=True}) + goal set → create_task(_goal_loop)
- _goal_loop：逐轮 build_iter_prompt 派发（fake _run_chat）→ fake _judge 判定 →
  achieved 即停 / continue 续跑（prompt 含上轮 gap 与轮次）/ max_iter 耗尽 /
  judge None 连续 2 次熔断 / cancel → goal stopped 事件
GET /goal：summarize_goal_events 重建最新状态；无 goal 事件 → 404
history：goal 事件仅 iter/achieved/exhausted/stopped 折成 role=goal turn（set/judge 跳过）

测试风格沿用 test_m175_refs_api.py / test_m174_edit_rerun.py：
同步测试函数 + TestClient + fake async 记录调用；judge 一律 fake（绝不碰真 LLM）。
"""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """隔离 DB + mock orchestrator + 防 goal 相关 env 污染；with 管理保证 portal 常驻。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    monkeypatch.delenv("FLIPPED_GOAL", raising=False)
    monkeypatch.delenv("FLIPPED_GOAL_MAX_ITER", raising=False)
    monkeypatch.delenv("FLIPPED_GOAL_JUDGE", raising=False)
    from api.main import app
    with TestClient(app) as c:
        yield c


def _new_session(client, mode: str = "chat") -> str:
    return client.post("/api/v1/assistant/sessions",
                       json={"title": "t", "mode": mode}).json()["id"]


def _post_goal(client, sid: str, **body):
    return client.post(f"/api/v1/assistant/sessions/{sid}/goal", json=body)


def _events(client, sid: str) -> list[dict]:
    r = client.get(f"/api/v1/sessions/{sid}/events")
    assert r.status_code == 200, r.text
    return r.json()


def _goal_events(client, sid: str) -> list[dict]:
    return [e for e in _events(client, sid) if e["type"] == "goal"]


def _goal_phases(client, sid: str) -> list[str]:
    return [e["payload"].get("phase") for e in _goal_events(client, sid)]


def _wait_task_gone(sid: str, timeout: float = 5.0) -> None:
    """轮询 RUNNING_TASKS 直到 wrapper 协程结束（done_callback pop）。"""
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


def _fake_chat_recorder(calls: list[str]):
    async def _fake_chat(session_id, task_id, description, model_alias, mode):
        calls.append(description)
    return _fake_chat


def _fake_judge_verdicts(verdicts: list[dict | None]):
    """按序返回 verdict；耗尽后恒 achieved（防无限续跑）。"""
    it = iter(verdicts)

    async def _fake_judge(state, session_id, model_alias):
        return next(it, {"achieved": True, "gap": ""})
    return _fake_judge


class _FakeRunning:
    """RUNNING_TASKS 守卫只调 .done()（同 test_m174_edit_rerun.py 模式）。"""
    def done(self) -> bool:
        return False


# ====================================================================
# 1 · 建 goal 派发成功：响应字段 + user 消息带 goal.started 标记 + set 事件
# ====================================================================

def test_create_goal_dispatch_success(client, monkeypatch):
    sid = _new_session(client)
    calls: list[str] = []
    monkeypatch.setattr("api.main._run_chat", _fake_chat_recorder(calls))
    monkeypatch.setattr("api.assistant._judge",
                        _fake_judge_verdicts([{"achieved": True, "gap": ""}]))

    r = _post_goal(client, sid, objective="修复所有 TS 错误")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["session_id"] == sid
    assert data["objective"] == "修复所有 TS 错误"
    assert data["task_id"].startswith("task-")
    assert data["max_iterations"] == 5, "缺省取 FLIPPED_GOAL_MAX_ITER 默认 5"
    _wait_task_gone(sid)

    events = _events(client, sid)
    users = [e for e in events if e["type"] == "message" and e["agent"] == "user"]
    assert len(users) == 1, "goal 全程只落 1 条 user 消息"
    assert users[0]["payload"]["text"] == "修复所有 TS 错误"
    assert users[0]["payload"]["goal"]["started"] is True
    assert _goal_phases(client, sid)[0] == "set"


# ====================================================================
# 2 · achieved 即停：judge 首轮判达成 → _run_chat 恰 1 次，事件流含 achieved
# ====================================================================

def test_achieved_stops_after_first_iteration(client, monkeypatch):
    sid = _new_session(client)
    calls: list[str] = []
    monkeypatch.setattr("api.main._run_chat", _fake_chat_recorder(calls))
    monkeypatch.setattr("api.assistant._judge",
                        _fake_judge_verdicts([{"achieved": True, "gap": ""}]))

    r = _post_goal(client, sid, objective="让 pnpm test 全过")
    assert r.status_code == 200, r.text
    _wait_task_gone(sid)

    assert calls == ["让 pnpm test 全过"], "第 1 轮 prompt = objective 原文"
    phases = _goal_phases(client, sid)
    assert phases == ["set", "iter", "judge", "achieved"]
    achieved = _goal_events(client, sid)[-1]["payload"]
    assert achieved["iteration"] == 1
    from api.main import store
    assert store.get(sid).status == "done", "终态须 update_status(done)"


# ====================================================================
# 3 · continue 续跑：第 2 轮 prompt 含上轮 gap 与轮次计数
# ====================================================================

def test_continue_carries_gap_into_next_prompt(client, monkeypatch):
    sid = _new_session(client)
    calls: list[str] = []
    monkeypatch.setattr("api.main._run_chat", _fake_chat_recorder(calls))
    monkeypatch.setattr("api.assistant._judge", _fake_judge_verdicts([
        {"achieved": False, "gap": "还差X"},
        {"achieved": True, "gap": ""},
    ]))

    r = _post_goal(client, sid, objective="目标G")
    assert r.status_code == 200, r.text
    _wait_task_gone(sid)

    assert len(calls) == 2
    assert "还差X" in calls[1], "续跑 prompt 必须带上轮差距"
    assert "第 2/5 轮" in calls[1], "续跑 prompt 必须带轮次计数"
    assert "目标G" in calls[1]
    assert _goal_phases(client, sid) == ["set", "iter", "judge", "iter", "judge", "achieved"]
    # judge 事件的 gap 已透传
    judges = [e["payload"] for e in _goal_events(client, sid) if e["payload"]["phase"] == "judge"]
    assert judges[0]["achieved"] is False and judges[0]["gap"] == "还差X"
    assert judges[1]["achieved"] is True


# ====================================================================
# 4 · max_iter 耗尽：max_iterations=2，judge 恒 False 变 gap → exhausted max_iter
# ====================================================================

def test_max_iterations_exhausted(client, monkeypatch):
    sid = _new_session(client)
    calls: list[str] = []
    monkeypatch.setattr("api.main._run_chat", _fake_chat_recorder(calls))
    n = {"i": 0}

    async def _fake_judge(state, session_id, model_alias):
        n["i"] += 1
        return {"achieved": False, "gap": f"还差{n['i']}处"}

    monkeypatch.setattr("api.assistant._judge", _fake_judge)

    r = _post_goal(client, sid, objective="NEVERDONE", max_iterations=2)
    assert r.status_code == 200, r.text
    assert r.json()["max_iterations"] == 2
    _wait_task_gone(sid)

    assert len(calls) == 2, "恰跑 max_iterations 轮"
    final = _goal_events(client, sid)[-1]["payload"]
    assert final["phase"] == "exhausted"
    assert final["reason"] == "max_iter"
    assert final["iteration"] == 2


# ====================================================================
# 5 · judge 失败熔断：_judge 恒 None → 连续 2 次 → exhausted_judge_errors
# ====================================================================

def test_judge_none_circuit_breaks(client, monkeypatch):
    sid = _new_session(client)
    calls: list[str] = []
    monkeypatch.setattr("api.main._run_chat", _fake_chat_recorder(calls))

    async def _fake_judge(state, session_id, model_alias):
        return None

    monkeypatch.setattr("api.assistant._judge", _fake_judge)

    r = _post_goal(client, sid, objective="目标J")
    assert r.status_code == 200, r.text
    _wait_task_gone(sid)

    assert len(calls) == 2, "judge 连续 2 次失败后熔断，不再跑第 3 轮"
    final = _goal_events(client, sid)[-1]["payload"]
    assert final["phase"] == "exhausted"
    assert final["reason"] == "judge_errors"
    judges = [e["payload"] for e in _goal_events(client, sid) if e["payload"]["phase"] == "judge"]
    assert all(j["achieved"] is False and j["gap"] == "judge 失败" for j in judges)


# ====================================================================
# 6 · FLIPPED_GOAL=0：端点整体 404
# ====================================================================

def test_env_kill_switch_disables_goal_endpoint(client, monkeypatch):
    monkeypatch.setenv("FLIPPED_GOAL", "0")
    sid = _new_session(client)
    r = _post_goal(client, sid, objective="目标K")
    assert r.status_code == 404, r.text
    assert _goal_events(client, sid) == [], "关闭时不准落任何 goal 事件"


# ====================================================================
# 7 · 409：会话已有 running task
# ====================================================================

def test_conflict_409_when_task_running(client):
    from api.main import RUNNING_TASKS
    sid = _new_session(client)
    RUNNING_TASKS[sid] = _FakeRunning()
    try:
        r = _post_goal(client, sid, objective="目标B")
        assert r.status_code == 409, r.text
    finally:
        RUNNING_TASKS.pop(sid, None)


# ====================================================================
# 8 · cancel → goal stopped 事件（CancelledError 沿 await 链传播进轮内）
# ====================================================================

def test_cancel_emits_goal_stopped(client, monkeypatch):
    sid = _new_session(client)

    async def _fake_chat(session_id, task_id, description, model_alias, mode):
        await asyncio.Event().wait()  # 永不返回，直到 cancel

    monkeypatch.setattr("api.main._run_chat", _fake_chat)

    r = _post_goal(client, sid, objective="SLOW 目标")
    assert r.status_code == 200, r.text
    _wait_task_present(sid)

    rc = client.post(f"/api/v1/sessions/{sid}/cancel")
    assert rc.status_code == 200, rc.text
    _wait_task_gone(sid)

    phases = _goal_phases(client, sid)
    assert phases == ["set", "iter", "stopped"], f"cancel 后必须 emit goal stopped: {phases}"


# ====================================================================
# 9 · GET /goal：有 goal 事件 → 200 重建 dict
# ====================================================================

def test_get_goal_reconstructs_state(client, monkeypatch):
    sid = _new_session(client)
    calls: list[str] = []
    monkeypatch.setattr("api.main._run_chat", _fake_chat_recorder(calls))
    monkeypatch.setattr("api.assistant._judge",
                        _fake_judge_verdicts([{"achieved": True, "gap": ""}]))

    r = _post_goal(client, sid, objective="目标Q", max_iterations=3)
    assert r.status_code == 200, r.text
    _wait_task_gone(sid)

    g = client.get(f"/api/v1/assistant/sessions/{sid}/goal")
    assert g.status_code == 200, g.text
    info = g.json()
    assert info["objective"] == "目标Q"
    assert info["status"] == "achieved"
    assert info["max_iterations"] == 3
    assert info["iteration"] == 1


# ====================================================================
# 10 · GET /goal：无 goal 事件 → 404；会话不存在 → 404（POST/GET 同）
# ====================================================================

def test_get_goal_404_without_goal_events(client):
    sid = _new_session(client)
    r = client.get(f"/api/v1/assistant/sessions/{sid}/goal")
    assert r.status_code == 404, r.text


def test_goal_session_not_found_404(client):
    assert _post_goal(client, "sess-不存在", objective="x").status_code == 404
    assert client.get("/api/v1/assistant/sessions/sess-不存在/goal").status_code == 404


# ====================================================================
# 11 · 非法 mode → 422（校验同 send）
# ====================================================================

def test_invalid_mode_422(client):
    sid = _new_session(client)
    r = _post_goal(client, sid, objective="目标M", mode="bogus")
    assert r.status_code == 422, r.text
    assert _goal_events(client, sid) == []


# ====================================================================
# 12 · turns 折叠：仅 iter/achieved/exhausted/stopped 成 goal turn，set/judge 跳过
# ====================================================================

def test_history_collapses_only_visible_goal_phases(client, monkeypatch):
    sid = _new_session(client)
    calls: list[str] = []
    monkeypatch.setattr("api.main._run_chat", _fake_chat_recorder(calls))
    monkeypatch.setattr("api.assistant._judge", _fake_judge_verdicts([
        {"achieved": False, "gap": "g1"},
        {"achieved": True, "gap": ""},
    ]))

    r = _post_goal(client, sid, objective="目标H")
    assert r.status_code == 200, r.text
    _wait_task_gone(sid)

    turns = client.get(f"/api/v1/assistant/sessions/{sid}/history").json()
    goal_turns = [t for t in turns if t["role"] == "goal"]
    assert [t["goal"]["phase"] for t in goal_turns] == ["iter", "iter", "achieved"], \
        "set/judge 不得折成 turn"
    assert all(t["goal"]["objective"] == "目标H" for t in goal_turns)
    assert goal_turns[1]["goal"]["iteration"] == 2
    assert goal_turns[1]["goal"]["gap"] == "g1", "第 2 轮 iter payload 带上轮 gap"
    user_turns = [t for t in turns if t["role"] == "user"]
    assert len(user_turns) == 1
