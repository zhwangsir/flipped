"""M191.4 · stale running watchdog TDD 测试（B 队调度域）。

契约（PLAN.md M191.4 节，字段名一字不差）：
- _STALE_SEEN 两击确认：status==running 且 RUNNING_TASKS 无活句柄 → 首击只记标记，
  次击按 lifespan 同款恢复（try_resume_goal → checkpoint resume → 无 checkpoint 标
  error + bus.emit status「watchdog: 运行句柄丢失，标记 error」）；动作后弹出标记。
- 活句柄/非 running 会话清标记；paused 不动（审批中合法无句柄）。
- FLIPPED_WATCHDOG=0 不起 watchdog 协程（测试环境直调 _stale_sweep_once 做断言）。

fixture 沿用 test_m190_edit_undo.py 惯例：FLIPPED_MOCK_ORCHESTRATOR=1 +
FLIPPED_CHECKPOINT_DB 指 tmp_path；TestClient 不进 context（lifespan 不跑），
协程用 asyncio.run 直调。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

import api.main as main
from api.schemas import EventType, Role, SessionStatus


@pytest.fixture()
def env(monkeypatch, tmp_path):
    """隔离环境：mock orchestrator + tmp checkpoint + 关 watchdog 协程 + 状态清理。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    monkeypatch.setenv("FLIPPED_WATCHDOG", "0")  # 防真 watchdog 协程干扰，直调 sweep 断言
    # 隔离：其他测试模块遗留的 running 会话先压回 idle，避免污染本轮断言
    for s in main.store.list():
        if s.status == SessionStatus.running:
            main.store.update_status(s.id, SessionStatus.idle)
    created: list[str] = []
    yield created
    main._STALE_SEEN.clear()
    main.RUNNING_TASKS.clear()
    for sid in created:
        main.store.delete(sid)


@pytest.fixture()
def client(env):
    return TestClient(main.app)


def _new_session(client, created) -> str:
    r = client.post("/api/v1/sessions", params={"title": "m191", "mode": "chat"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    created.append(sid)
    return sid


def _sweep():
    asyncio.run(main._stale_sweep_once())


def _status_notes(sid: str) -> list[str]:
    out = []
    for e in main.store.events(sid):
        etype = e.type.value if hasattr(e.type, "value") else e.type
        if etype == "status":
            out.append(str(e.payload.get("note", "")))
    return out


class _FakeRunning:
    """未完成的假活句柄（同 test_m190_edit_undo 惯例）。"""

    def done(self):
        return False


# ====================================================================
# 1 · 两击确认：首击只记标记，次击无 checkpoint → error + watchdog note
# ====================================================================

def test_two_strike_marks_error_without_checkpoint(client, env):
    sid = _new_session(client, env)
    main.store.update_status(sid, SessionStatus.running)  # 无句柄、无 checkpoint

    _sweep()  # 首击：只记标记不动
    assert main.store.get(sid).status == SessionStatus.running
    assert sid in main._STALE_SEEN

    _sweep()  # 次击：无 checkpoint → error + watchdog note + 清标记
    assert main.store.get(sid).status == SessionStatus.error
    assert sid not in main._STALE_SEEN
    assert any("watchdog: 运行句柄丢失，标记 error" in n for n in _status_notes(sid))


# ====================================================================
# 2 · 活句柄不碰：running + 未完成句柄 → 两次 sweep 后仍 running、无标记
# ====================================================================

def test_live_handle_untouched(client, env):
    sid = _new_session(client, env)
    main.store.update_status(sid, SessionStatus.running)
    main.RUNNING_TASKS[sid] = _FakeRunning()

    _sweep()
    _sweep()
    assert main.store.get(sid).status == SessionStatus.running
    assert sid not in main._STALE_SEEN


# ====================================================================
# 3 · paused 不碰：审批中合法无句柄
# ====================================================================

def test_paused_untouched(client, env):
    sid = _new_session(client, env)
    main.store.update_status(sid, SessionStatus.paused)

    _sweep()
    _sweep()
    assert main.store.get(sid).status == SessionStatus.paused
    assert sid not in main._STALE_SEEN


# ====================================================================
# 4 · checkpoint 分支：次击 create_task(_resume_orchestrator) 注册 RUNNING_TASKS
# ====================================================================

def test_checkpoint_branch_registers_resume_task(client, env, monkeypatch, tmp_path):
    sid = _new_session(client, env)
    main.store.update_status(sid, SessionStatus.running)
    main.store.update(sid, checkpoint_db_path=str(tmp_path / "cp.db"))

    async def _fake_resume(session):
        await asyncio.sleep(3600)  # 挂住，防真跑 resume 链路

    monkeypatch.setattr("api.main._resume_orchestrator", _fake_resume)

    async def _run():
        await main._stale_sweep_once()  # 首击
        assert main.store.get(sid).status == SessionStatus.running
        await main._stale_sweep_once()  # 次击：注册恢复句柄
        return main.RUNNING_TASKS.get(sid)

    handle = asyncio.run(_run())
    assert handle is not None, "次击后 RUNNING_TASKS 须出现恢复句柄"
    assert sid not in main._STALE_SEEN
    assert main.store.get(sid).status == SessionStatus.running


# ====================================================================
# 5 · goal 分支：事件流含未终态 goal → try_resume_goal 命中注册句柄
# ====================================================================

def test_goal_branch_registers_goal_task(client, env, monkeypatch):
    sid = _new_session(client, env)
    main.store.update_status(sid, SessionStatus.running)
    # 未终态 goal 事件流：set + iter（无 judge、无 approval）
    main.bus.emit(sid, EventType.goal, Role.system,
                  {"phase": "set", "objective": "o", "iteration": 0, "max_iterations": 5})
    main.bus.emit(sid, EventType.goal, Role.system,
                  {"phase": "iter", "objective": "o", "iteration": 1, "max_iterations": 5})

    def _fake_try_resume_goal(session):
        return asyncio.create_task(asyncio.sleep(3600))  # 假 goal 续跑句柄

    monkeypatch.setattr("api.assistant.try_resume_goal", _fake_try_resume_goal)

    async def _run():
        await main._stale_sweep_once()  # 首击
        await main._stale_sweep_once()  # 次击：goal 续跑优先注册
        return main.RUNNING_TASKS.get(sid)

    handle = asyncio.run(_run())
    assert handle is not None, "次击后 RUNNING_TASKS 须出现 goal 续跑句柄"
    assert sid not in main._STALE_SEEN
    assert main.store.get(sid).status == SessionStatus.running


# ====================================================================
# 6 · 健康清标记：已记标记的会话后来有了活句柄 → 清标记不动状态
# ====================================================================

def test_healthy_session_clears_stale_mark(client, env):
    sid = _new_session(client, env)
    main.store.update_status(sid, SessionStatus.running)
    main._STALE_SEEN.add(sid)  # 模拟此前首击已记标记
    main.RUNNING_TASKS[sid] = _FakeRunning()  # 后来活句柄出现

    _sweep()
    assert sid not in main._STALE_SEEN
    assert main.store.get(sid).status == SessionStatus.running
