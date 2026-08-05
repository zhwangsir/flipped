"""M188.2 · goal 断点续跑 TDD 测试（消化 L-M176-3）。

覆盖：
- 纯逻辑 rebuild_running（goal.py）：无 set / 已终态 → None；set-only → 第 1 轮；
  iter 后无 judge = 半途轮重跑；iter 后有 judge = 从下一轮起；gap 签名 /
  judge 失败计数重建（续跑后 no-progress / judge_errors 熔断语义不丢）
- try_resume_goal（assistant.py）：FLIPPED_GOAL=0 → None；不可重建 → None；
  可重建 → emit status 事件 + 创建 _goal_loop task（start/verify_cmd 透传）
- lifespan 接线（main.py）：running goal 会话（无 checkpoint）→ 续跑且不标 error；
  running 无 goal 无 checkpoint → error（现状不变）；running 有 checkpoint 无 goal
  → orchestrator 恢复（现状不变）；paused goal 不续跑（登记限制）

测试风格沿用 test_m188_goal_verify.py：同步测试 + TestClient + fake async。
lifespan 测试用 FLIPPED_SESSION_STORE_PATH 指向 tmp store 文件预置状态。
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from api.goal import GoalState, rebuild_running
from api.schemas import Event, EventType, Role


# ====================================================================
# 0 · 工具：内存事件构造
# ====================================================================

def _ev(phase: str, **payload) -> Event:
    return Event(id="e", session_id="s", type=EventType.goal, agent=Role.system,
                 payload={"phase": phase, **payload})


def _msg_ev() -> Event:
    return Event(id="m", session_id="s", type=EventType.message, agent=Role.worker,
                 payload={"text": "x"})


# ====================================================================
# 1 · 纯逻辑：rebuild_running
# ====================================================================

def test_rebuild_no_goal_events_returns_none():
    assert rebuild_running([]) is None
    assert rebuild_running([_msg_ev()]) is None


def test_rebuild_terminal_phases_return_none():
    for terminal in ("achieved", "exhausted", "stopped"):
        evs = [_ev("set", objective="G", max_iterations=5),
               _ev("iter", iteration=1),
               _ev("judge", iteration=1, achieved=(terminal == "achieved"), gap=""),
               _ev(terminal, iteration=1)]
        assert rebuild_running(evs) is None, f"{terminal} 终态不得续跑"


def test_rebuild_set_only_starts_at_round_1():
    r = rebuild_running([_ev("set", objective="G", max_iterations=3)])
    assert r is not None
    state, start = r
    assert start == 1
    assert state.objective == "G" and state.max_iterations == 3
    assert state.status == "running" and state.iteration == 0


def test_rebuild_midway_round_reruns_that_round():
    """iter(2) 后无 judge = 第 2 轮半途 → 从第 2 轮重跑，gap 保留第 1 轮的。"""
    evs = [_ev("set", objective="G", max_iterations=5),
           _ev("iter", iteration=1),
           _ev("judge", iteration=1, achieved=False, gap="还差A"),
           _ev("iter", iteration=2)]
    state, start = rebuild_running(evs)
    assert start == 2, "半途轮须整个重跑"
    assert state.last_gap == "还差A", "续跑 prompt 须带最近一轮 gap"
    assert state._judge_errors == 0


def test_rebuild_completed_round_starts_next():
    evs = [_ev("set", objective="G", max_iterations=5),
           _ev("iter", iteration=1), _ev("judge", iteration=1, achieved=False, gap="g1"),
           _ev("iter", iteration=2), _ev("judge", iteration=2, achieved=False, gap="g2")]
    state, start = rebuild_running(evs)
    assert start == 3
    assert state.last_gap == "g2"


def test_rebuild_gap_sigs_rebuilt_for_no_progress():
    """两轮相同 gap 签名已入史 → 续跑后第三轮同 gap 即 no-progress 熔断。"""
    evs = [_ev("set", objective="G", max_iterations=9),
           _ev("iter", iteration=1), _ev("judge", iteration=1, achieved=False, gap="同gap"),
           _ev("iter", iteration=2), _ev("judge", iteration=2, achieved=False, gap="同gap")]
    state, start = rebuild_running(evs)
    assert start == 3
    assert state._gap_sigs, "gap 签名历史须重建（否则 no-progress 熔断失效）"
    from api.goal import record_verdict
    # 再来一轮同 gap → 与史中末位相同 → no_progress
    assert record_verdict(state, {"achieved": False, "gap": "同gap"}) == "exhausted_no_progress"


def test_rebuild_judge_error_count_rebuilt():
    """judge 失败（gap=judge 失败）连续计数重建 → 续跑后再失败 1 次即熔断。"""
    evs = [_ev("set", objective="G", max_iterations=9),
           _ev("iter", iteration=1), _ev("judge", iteration=1, achieved=False, gap="judge 失败")]
    state, start = rebuild_running(evs)
    assert start == 2
    assert state._judge_errors == 1
    from api.goal import record_verdict
    assert record_verdict(state, None) == "exhausted_judge_errors"


def test_rebuild_uses_latest_set():
    """历史有旧 goal（已终态）+ 新 goal（running）→ 只从最新 set 起重放。"""
    evs = [_ev("set", objective="OLD", max_iterations=5),
           _ev("iter", iteration=1), _ev("achieved", iteration=1),
           _ev("set", objective="NEW", max_iterations=4),
           _ev("iter", iteration=1)]
    state, start = rebuild_running(evs)
    assert state.objective == "NEW" and state.max_iterations == 4
    assert start == 1


# ====================================================================
# 2 · try_resume_goal 接线
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


def _wait_task_gone(sid: str, timeout: float = 8.0) -> None:
    from api.main import RUNNING_TASKS
    deadline = time.time() + timeout
    while time.time() < deadline:
        if RUNNING_TASKS.get(sid) is None:
            return
        time.sleep(0.01)
    raise AssertionError(f"task 未在 {timeout}s 内结束: {sid}")


def test_try_resume_goal_env_off_returns_none(client, monkeypatch):
    monkeypatch.setenv("FLIPPED_GOAL", "0")
    from api.assistant import try_resume_goal
    from api.main import store
    from api.schemas import SessionStatus
    sid = _new_session(client)
    store.update_status(sid, SessionStatus.running)
    assert try_resume_goal(store.get(sid)) is None


def test_post_goal_sets_session_running(client, monkeypatch):
    """M188.2 修复：goal 运行期间会话必须 running，否则进程死后 lifespan 看不到它。"""
    from api.main import store

    async def _hang_chat(session_id, task_id, description, model_alias, mode):
        await asyncio.Event().wait()

    monkeypatch.setattr("api.main._run_chat", _hang_chat)
    sid = _new_session(client)
    r = client.post(f"/api/v1/assistant/sessions/{sid}/goal", json={"objective": "G"})
    assert r.status_code == 200, r.text
    assert store.get(sid).status == "running"
    from api.main import RUNNING_TASKS
    RUNNING_TASKS[sid].cancel()
    _wait_task_gone(sid)


def test_try_resume_goal_no_goal_events_returns_none(client):
    from api.assistant import try_resume_goal
    from api.main import store
    sid = _new_session(client)
    assert try_resume_goal(store.get(sid)) is None


def test_try_resume_goal_creates_task_and_emits_status(client, monkeypatch):
    """running 会话 + 半途 goal（iter1 judged, iter2 半途）→ task 从第 2 轮重跑。"""
    from api.assistant import try_resume_goal
    from api.main import bus, store
    from api.schemas import SessionStatus
    sid = _new_session(client)
    store.update_status(sid, SessionStatus.running)
    bus.emit(sid, EventType.goal, Role.system,
             {"phase": "set", "objective": "G", "iteration": 0, "max_iterations": 5})
    bus.emit(sid, EventType.goal, Role.system,
             {"phase": "iter", "objective": "G", "iteration": 1, "max_iterations": 5})
    bus.emit(sid, EventType.goal, Role.system,
             {"phase": "judge", "objective": "G", "iteration": 1, "max_iterations": 5,
              "achieved": False, "gap": "还差B", "source": "llm"})
    bus.emit(sid, EventType.goal, Role.system,
             {"phase": "iter", "objective": "G", "iteration": 2, "max_iterations": 5})

    calls: list[str] = []

    async def _fake_chat(session_id, task_id, description, model_alias, mode):
        calls.append(description)

    monkeypatch.setattr("api.main._run_chat", _fake_chat)
    monkeypatch.setattr("api.assistant._verify_deterministic", _det_none)

    async def _judge_achieved(state, session_id, model_alias):
        return {"achieved": True, "gap": ""}

    monkeypatch.setattr("api.assistant._judge", _judge_achieved)

    async def _drive():
        t = try_resume_goal(store.get(sid))
        assert t is not None and isinstance(t, asyncio.Task)
        await t  # 续跑协程在本 loop 内跑完（fake chat 即时返回 + judge 首轮达成）

    asyncio.run(_drive())

    assert calls and "还差B" in calls[0] and "第 2/5 轮" in calls[0], \
        f"续跑须从第 2 轮重跑并带上轮 gap: {calls}"
    status_evs = [e for e in store.events(sid)
                  if (e.type.value if hasattr(e.type, "value") else e.type) == "status"]
    assert any("断点续跑" in json.dumps(e.payload or {}, ensure_ascii=False)
               for e in status_evs), "须 emit status 事件说明续跑起点"
    phases = [ (e.payload or {}).get("phase") for e in store.events(sid)
               if (e.type.value if hasattr(e.type, "value") else e.type) == "goal"]
    assert phases[-2:] == ["judge", "achieved"], f"续跑须推进到终态: {phases}"


async def _det_none(session_id, mode):
    return None


# ====================================================================
# 3 · lifespan 接线：goal 恢复优先级
# ====================================================================

def _seed_store(path, *, with_goal: bool, with_checkpoint: bool,
                status: str = "running") -> str:
    """预置 store 文件：1 个会话 + 可选半途 goal 事件流，返回 session_id。"""
    from api.schemas import SessionStatus
    from api.session import SessionStore
    st = SessionStore()
    st.load(str(path))  # 绑定持久化路径（文件尚不存在 → 空库）
    s = st.create("t", mode="chat")
    if with_goal:
        st.add_event(s.id, EventType.goal, agent=Role.system,
                     payload={"phase": "set", "objective": "G", "iteration": 0,
                              "max_iterations": 5})
        st.add_event(s.id, EventType.goal, agent=Role.system,
                     payload={"phase": "iter", "objective": "G", "iteration": 1,
                              "max_iterations": 5})
    if with_checkpoint:
        st.update(s.id, checkpoint_db_path="cp.db")
    st.update_status(s.id, SessionStatus(status))
    return s.id


@pytest.fixture()
def boot_client(monkeypatch, tmp_path):
    """按预置 store 启动 app（lifespan 恢复逻辑在 TestClient __enter__ 触发）。"""
    def _boot(*, with_goal: bool, with_checkpoint: bool, status: str = "running"):
        monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
        monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
        monkeypatch.delenv("FLIPPED_GOAL", raising=False)
        store_path = tmp_path / f"store-{with_goal}-{with_checkpoint}-{status}.json"
        sid = _seed_store(store_path, with_goal=with_goal,
                          with_checkpoint=with_checkpoint, status=status)
        monkeypatch.setenv("FLIPPED_SESSION_STORE_PATH", str(store_path))
        from api.main import app
        return app, sid
    return _boot


def test_lifespan_resumes_running_goal_without_checkpoint(boot_client, monkeypatch):
    app, sid = boot_client(with_goal=True, with_checkpoint=False)
    resumed: list[str] = []

    async def _spy_resume(session):
        resumed.append(session.id)

    async def _hang_chat(session_id, task_id, description, model_alias, mode):
        await asyncio.Event().wait()  # 续跑后停在第 1 轮 dispatch，便于断言 running 中态

    monkeypatch.setattr("api.main._resume_orchestrator", _spy_resume)
    monkeypatch.setattr("api.main._run_chat", _hang_chat)
    with TestClient(app) as c:
        from api.main import RUNNING_TASKS, store
        deadline = time.time() + 5.0
        while time.time() < deadline and RUNNING_TASKS.get(sid) is None:
            time.sleep(0.01)
        sess = store.get(sid)
        assert sess.status == "running", "goal 会话续跑期间不得标 error"
        assert RUNNING_TASKS.get(sid) is not None, "goal 续跑 task 须注册防重入"
        # 409：续跑中再 POST goal → 冲突
        r = c.post(f"/api/v1/assistant/sessions/{sid}/goal", json={"objective": "重入"})
        assert r.status_code == 409, r.text
        RUNNING_TASKS[sid].cancel()
    assert resumed == [], "goal 会话不得走 orchestrator checkpoint 恢复"


def test_lifespan_running_no_goal_no_checkpoint_marks_error(boot_client):
    app, sid = boot_client(with_goal=False, with_checkpoint=False)
    with TestClient(app):
        from api.main import store
        assert store.get(sid).status == "error", "现状不变：无 goal 无 checkpoint → error"


def test_lifespan_running_checkpoint_no_goal_resumes_orchestrator(boot_client, monkeypatch):
    app, sid = boot_client(with_goal=False, with_checkpoint=True)
    resumed: list[str] = []

    async def _spy_resume(session):
        resumed.append(session.id)

    monkeypatch.setattr("api.main._resume_orchestrator", _spy_resume)
    with TestClient(app):
        pass
    assert resumed == [sid], "现状不变：有 checkpoint 无 goal → orchestrator 恢复"


def test_lifespan_paused_goal_not_resumed(boot_client, monkeypatch):
    """paused（审批中）goal 会话：走 orchestrator checkpoint 恢复，goal 循环不续。"""
    app, sid = boot_client(with_goal=True, with_checkpoint=True, status="paused")
    resumed: list[str] = []

    async def _spy_resume(session):
        resumed.append(session.id)

    monkeypatch.setattr("api.main._resume_orchestrator", _spy_resume)
    with TestClient(app):
        pass
    assert resumed == [sid], "paused 走 checkpoint 恢复"
    from api.main import store
    assert store.get(sid).status == "paused"


def test_lifespan_resumes_goal_with_done_status(boot_client, monkeypatch):
    """锁回归：goal 每轮 dispatch 尾段把 store 状态写成 done，进程死在 dispatch 中时
    status=done（非 running）——lifespan 不得按 status 过滤，仍须续跑。"""
    app, sid = boot_client(with_goal=True, with_checkpoint=False, status="done")

    async def _hang_chat(session_id, task_id, description, model_alias, mode):
        await asyncio.Event().wait()

    monkeypatch.setattr("api.main._run_chat", _hang_chat)
    with TestClient(app):
        from api.main import RUNNING_TASKS
        deadline = time.time() + 5.0
        while time.time() < deadline and RUNNING_TASKS.get(sid) is None:
            time.sleep(0.01)
        assert RUNNING_TASKS.get(sid) is not None, "status=done 的半途 goal 也须续跑"
        RUNNING_TASKS[sid].cancel()
