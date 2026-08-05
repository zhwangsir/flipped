"""M191.2 · 审批暂停 goal 续跑（消化 L-M188-1）。

覆盖：
- goal.py 纯函数 has_pending_approval：逆序扫（request 最新→True；result 最新→False；
  无→False），enum/字符串 type 双兼容
- goal.py rebuild_running 增守卫：未终态 goal + pending approval → None（审批 parked
  的 goal 不走自动续跑，由审批放行钩子接手）；approval_result 回答后正常返回
- goal.py summarize_goal_events：paused 相位 → status=="paused"
- assistant._goal_loop：dispatch 后出现未答 approval_request → emit paused 并干净
  return（不再派下一轮）；judge_first=True 的首轮跳过 iter/dispatch 直进 judge；
  judge_first 于 max 轮判 continue → 循环后补 exhausted(reason="max_iter")
- assistant._resume_with_decision 钩子：未终态 goal → 重建续跑（RUNNING_TASKS 注册
  + 「goal 审批续跑」status 事件）；FLIPPED_GOAL=0 不触发

测试风格沿用 test_m188_goal_resume.py：同步测试 + TestClient + asyncio.run 驱动协程。
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.goal import GoalState, has_pending_approval, rebuild_running, summarize_goal_events
from api.schemas import Event, EventType, Role


# ====================================================================
# 0 · 工具
# ====================================================================

def _goal_ev(phase: str, **payload) -> Event:
    return Event(id="e", session_id="s", type=EventType.goal, agent=Role.system,
                 payload={"phase": phase, **payload})


def _approval_ev(kind: str) -> Event:
    etype = EventType.approval_request if kind == "approval_request" else EventType.approval_result
    return Event(id="a", session_id="s", type=etype, agent=Role.system, payload={})


# ====================================================================
# 1 · has_pending_approval 纯函数
# ====================================================================

def test_hpa_empty_and_no_approval_events():
    assert has_pending_approval([]) is False
    assert has_pending_approval([_goal_ev("set", objective="G")]) is False


def test_hpa_request_latest_true():
    evs = [_goal_ev("set", objective="G"), _approval_ev("approval_request")]
    assert has_pending_approval(evs) is True


def test_hpa_result_latest_false():
    evs = [_approval_ev("approval_request"), _approval_ev("approval_result")]
    assert has_pending_approval(evs) is False
    # 逆序语义：result 之后又来 request → True
    evs2 = [_approval_ev("approval_request"), _approval_ev("approval_result"),
            _approval_ev("approval_request")]
    assert has_pending_approval(evs2) is True


def test_hpa_string_type_compatible():
    """events 元素 type 可能是字符串（非 enum）→ 同样可识别。"""
    req = SimpleNamespace(type="approval_request", payload={})
    res = SimpleNamespace(type="approval_result", payload={})
    assert has_pending_approval([req]) is True
    assert has_pending_approval([req, res]) is False


# ====================================================================
# 2 · rebuild_running 审批守卫
# ====================================================================

def _running_goal_events() -> list:
    return [_goal_ev("set", objective="G", max_iterations=5),
            _goal_ev("iter", iteration=1),
            _goal_ev("judge", iteration=1, achieved=False, gap="g1", error=False)]


def test_rebuild_pending_approval_returns_none():
    """未终态 goal 但审批 parked → None（不自动续跑）。"""
    evs = _running_goal_events() + [_approval_ev("approval_request")]
    assert rebuild_running(evs) is None


def test_rebuild_answered_approval_rebuilds_normally():
    """approval_result 回答后 → 正常返回 (state, start)。"""
    evs = (_running_goal_events()
           + [_approval_ev("approval_request"), _approval_ev("approval_result")])
    r = rebuild_running(evs)
    assert r is not None
    state, start = r
    assert start == 2
    assert state.last_gap == "g1"


# ====================================================================
# 3 · summarize_goal_events：paused 相位
# ====================================================================

def test_summarize_paused_phase():
    evs = [_goal_ev("set", objective="G", max_iterations=5),
           _goal_ev("iter", iteration=1),
           _goal_ev("paused", iteration=1)]
    info = summarize_goal_events(evs)
    assert info is not None
    assert info["status"] == "paused"
    assert info["iteration"] == 1
    assert info["objective"] == "G"


# ====================================================================
# 4 · TestClient 端点级
# ====================================================================

@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    monkeypatch.delenv("FLIPPED_GOAL", raising=False)
    monkeypatch.delenv("FLIPPED_GOAL_MAX_ITER", raising=False)
    monkeypatch.delenv("FLIPPED_GOAL_JUDGE", raising=False)
    monkeypatch.delenv("FLIPPED_GOAL_VERIFY", raising=False)
    from api.main import app
    with TestClient(app) as c:
        yield c


def _new_session(client, mode: str = "chat") -> str:
    return client.post("/api/v1/assistant/sessions",
                       json={"title": "t", "mode": mode}).json()["id"]


def _goal_phases(sid: str) -> list:
    from api.main import store
    return [(e.payload or {}).get("phase") for e in store.events(sid)
            if (e.type.value if hasattr(e.type, "value") else e.type) == "goal"]


def _goal_events(sid: str) -> list:
    from api.main import store
    return [e for e in store.events(sid)
            if (e.type.value if hasattr(e.type, "value") else e.type) == "goal"]


async def _det_achieved(session_id, mode):
    return {"achieved": True, "gap": ""}


async def _det_gap(session_id, mode):
    return {"achieved": False, "gap": "还差"}


def test_goal_loop_pauses_on_pending_approval(client, monkeypatch):
    """dispatch 后事件流出现未答 approval_request → emit paused 并 return，
    不再 judge、不再派下一轮；state.status 保持 running（paused 是驻留相位）。"""
    from api.assistant import _goal_loop
    from api.main import bus

    sid = _new_session(client, mode="agent")

    async def _fake_orch(session_id, task_id, task_req):
        bus.emit(session_id, EventType.approval_request, Role.system,
                 {"action": "run something"})

    monkeypatch.setattr("api.main._run_orchestrator", _fake_orch)

    state = GoalState(objective="G", max_iterations=3)
    asyncio.run(_goal_loop(sid, "task-p", state, "agent", "coder"))

    assert _goal_phases(sid) == ["iter", "paused"], "paused 后不得再 judge/iter"
    assert state.status == "running", "paused 非终态，status 保持 running"


def test_goal_loop_judge_first_skips_dispatch(client, monkeypatch):
    """judge_first=True 且 i==start：跳过 iter emit 与 dispatch，直进 judge；
    判达成 → judge + achieved，无 iter 事件。"""
    from api.assistant import _goal_loop
    from api.main import store
    from api.schemas import SessionStatus

    monkeypatch.setattr("api.assistant._verify_deterministic", _det_achieved)

    sid = _new_session(client)
    state = GoalState(objective="G", max_iterations=1)
    asyncio.run(_goal_loop(sid, "task-j", state, "chat", "coder",
                           start=1, judge_first=True))

    phases = _goal_phases(sid)
    assert phases == ["judge", "achieved"], f"judge_only 轮不得 emit iter: {phases}"
    judge_ev = _goal_events(sid)[0]
    assert judge_ev.payload["achieved"] is True
    assert judge_ev.payload["error"] is False
    assert store.get(sid).status == SessionStatus.done


def test_goal_loop_judge_first_continue_at_max_emits_exhausted(client, monkeypatch):
    """judge_first 于 max 轮判 continue（工作已做必须判，冤枉达成是 bug）
    → 循环后补 exhausted(reason="max_iter") + 会话 done。"""
    from api.assistant import _goal_loop
    from api.main import store
    from api.schemas import SessionStatus

    monkeypatch.setattr("api.assistant._verify_deterministic", _det_gap)

    sid = _new_session(client)
    state = GoalState(objective="G", max_iterations=1)
    asyncio.run(_goal_loop(sid, "task-c", state, "chat", "coder",
                           start=1, judge_first=True))

    phases = _goal_phases(sid)
    assert phases == ["judge", "exhausted"], f"max 轮判 continue 须补 exhausted: {phases}"
    exhausted_ev = _goal_events(sid)[-1]
    assert exhausted_ev.payload["reason"] == "max_iter"
    assert exhausted_ev.payload["gap"] == "还差"
    assert store.get(sid).status == SessionStatus.done


def _seed_running_goal(sid: str) -> None:
    """未终态 goal 事件流：set + iter1 + judge1（未达成）。"""
    from api.main import bus
    bus.emit(sid, EventType.goal, Role.system,
             {"phase": "set", "objective": "G", "iteration": 0, "max_iterations": 5})
    bus.emit(sid, EventType.goal, Role.system,
             {"phase": "iter", "objective": "G", "iteration": 1, "max_iterations": 5})
    bus.emit(sid, EventType.goal, Role.system,
             {"phase": "judge", "objective": "G", "iteration": 1, "max_iterations": 5,
              "achieved": False, "gap": "g1", "source": "llm", "error": False})


def test_resume_with_decision_spawns_goal_continuation(client, monkeypatch):
    """审批放行跑完该轮后，未终态 goal → 重建循环态续跑 wrapper：
    RUNNING_TASKS 注册句柄 + emit「goal 审批续跑」status + judge_first 直判推进。"""
    from api.assistant import _resume_with_decision
    from api.main import RUNNING_TASKS, bus, store

    monkeypatch.setattr("driving.orchestrator.resume_orchestrated",
                        lambda *a, **k: {"verified": True})
    monkeypatch.setattr("api.assistant._verify_deterministic", _det_achieved)

    sid = _new_session(client)
    _seed_running_goal(sid)
    # 审批已被回答（result 在 request 之后）→ rebuild 不被守卫拦截
    bus.emit(sid, EventType.approval_request, Role.system, {"action": "x"})
    bus.emit(sid, EventType.approval_result, Role.system, {"decision": "approve"})

    async def _drive():
        await _resume_with_decision(sid, "approve")
        assert sid in RUNNING_TASKS, "续跑 wrapper 须注册 RUNNING_TASKS"
        await RUNNING_TASKS[sid]

    asyncio.run(_drive())

    status_evs = [e for e in store.events(sid)
                  if (e.type.value if hasattr(e.type, "value") else e.type) == "status"]
    assert any("goal 审批续跑" in json.dumps(e.payload or {}, ensure_ascii=False)
               for e in status_evs), "须 emit「goal 审批续跑」status 事件"
    phases = _goal_phases(sid)
    assert phases[-2:] == ["judge", "achieved"], f"续跑须 judge_first 直判推进: {phases}"


def test_resume_hook_disabled_when_goal_off(client, monkeypatch):
    """FLIPPED_GOAL=0 → 钩子不触发：无续跑 task、无「goal 审批续跑」事件。"""
    from api.assistant import _resume_with_decision
    from api.main import RUNNING_TASKS, store

    monkeypatch.setenv("FLIPPED_GOAL", "0")
    monkeypatch.setattr("driving.orchestrator.resume_orchestrated",
                        lambda *a, **k: {"verified": True})

    sid = _new_session(client)
    _seed_running_goal(sid)

    asyncio.run(_resume_with_decision(sid, "approve"))

    assert RUNNING_TASKS.get(sid) is None
    status_evs = [e for e in store.events(sid)
                  if (e.type.value if hasattr(e.type, "value") else e.type) == "status"]
    assert not any("goal 审批续跑" in json.dumps(e.payload or {}, ensure_ascii=False)
                   for e in status_evs)
