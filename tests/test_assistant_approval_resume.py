"""M151.2 · 审批 interrupt→resume 闭环 TDD 测试。

覆盖：
- build_orchestrator 的 on_approval_request 回调在 interrupt 前触发
- resume_orchestrated(resume_value="approve") 续跑到 worker
- resume_orchestrated(resume_value="reject") 回 supervisor 重规划
- approve 端点：无 pending approval_request 时返 409
- approval_request payload 含 action + reason

设计原则：
- 1/2/3/5 在 orchestrator 单元层测（直接调 build_orchestrator / resume_orchestrated，
  用 InMemorySaver / SqliteSaver(tmp) 免集群免沙盒）
- 4 在 API 层测（TestClient + 事件流守卫）
- 不破坏既有 test_orchestrator / test_approval* 回归（build_orchestrator / resume_orchestrated
  新参数默认 None / 行为向后兼容）
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient


# ---------- 1/2/3/5: orchestrator 层 ----------

def _high_risk_supervisor(state):
    """supervisor 始终产出高风险子任务（git push），触发 approval_gate interrupt。"""
    return {"current_subtask": "git push origin main", "believe_done": False,
            "history": state.get("history", []) + [{"step": "supervisor"}]}


def _safe_after_reject_supervisor(state):
    """被否决后（feedback 含'否决'）改走安全方案；首次走高风险。"""
    sub = "ls -la" if "否决" in state.get("feedback", "") else "git push origin main"
    return {"current_subtask": sub, "believe_done": False,
            "history": state.get("history", []) + [{"step": "supervisor"}]}


def _approving_worker(c):
    """worker 计数 + 产出验收可过的 last_obs。"""
    def worker(state):
        c["work"] += 1
        return {"last_obs": {"summary": {}}, "signatures": state.get("signatures", []) + ["s"],
                "history": state.get("history", []) + [{"step": "worker"}]}
    return worker


def _continuing_overseer():
    def overseer(state):
        return {"verdict": {"action": "continue"},
                "history": state.get("history", []) + [{"step": "overseer"}]}
    return overseer


def _passing_verifier():
    def verifier(cmd, cwd):
        return True, ""
    return verifier


def _build_graph_for_approval(supervisor_fn, on_approval_request=None):
    """构建带 on_approval_request 回调的 approval 测试图（InMemorySaver）。"""
    from langgraph.checkpoint.memory import InMemorySaver
    from driving.orchestrator import build_orchestrator

    c = {"work": 0, "sup": 0}
    _wrapped = [supervisor_fn]

    def supervisor_wrapped(state):
        c["sup"] += 1
        result = _wrapped[0](state)
        fb = state.get("feedback", "")
        # M89 verify 逻辑：verify ok but believe_done=False 时 feedback 含"已完成且验证通过"
        # → 检测到该标记 → believe_done=True 让整体 verified 结束
        if state.get("iteration", 0) >= 1 and "已完成且验证通过" in fb:
            result["believe_done"] = True
        return result

    g = build_orchestrator(
        supervisor_wrapped, _approving_worker(c), _continuing_overseer(), _passing_verifier(),
        checkpointer=InMemorySaver(), on_approval_request=on_approval_request,
    )
    init = {"goal": "G", "cwd": "/tmp", "verify_cmd": ["true"], "max_iterations": 3, "loop_threshold": 3,
            "require_approval": True, "iteration": 0, "signatures": [], "feedback": "", "verified": False,
            "done": False, "stop_reason": "", "history": []}
    return g, init, c


def test_on_approval_request_callback_fires_before_interrupt():
    """高风险子任务 interrupt 前，on_approval_request 回调被调用（payload 含子任务）。"""
    captured = {"called": False, "state": None}

    def on_approval_request(state):
        captured["called"] = True
        captured["state"] = dict(state)

    g, init, _c = _build_graph_for_approval(_high_risk_supervisor, on_approval_request)
    cfg = {"configurable": {"thread_id": "appr-cb"}}
    res = g.invoke(init, cfg)
    # 回调在 interrupt 前触发
    assert captured["called"] is True, "on_approval_request 必须在 interrupt 前被调用"
    # interrupt 已发生（高风险）
    assert "__interrupt__" in res, "高风险子任务应 interrupt"
    # 回调拿到的 state 含当前子任务（action 来源）
    assert "git push origin main" in str(captured["state"].get("current_subtask", ""))


def test_resume_with_approve_continues_to_worker():
    """resume_orchestrated(resume_value='approve') 续跑 → worker 执行 → 验收通过。"""
    from langgraph.checkpoint.sqlite import SqliteSaver

    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "cp.db")
        # 先首跑：建图 + interrupt
        from driving.orchestrator import build_orchestrator
        c = {"work": 0}
        _wrapped = [_high_risk_supervisor]

        def sup_w(state):
            _wrapped[0](state)
            # approve 后 worker 执行 → verify 通过 → feedback 含标记 → believe_done
            if state.get("iteration", 0) >= 1:
                return {"current_subtask": "done", "believe_done": True,
                        "history": state.get("history", []) + [{"step": "sup"}]}
            return _wrapped[0](state)

        with SqliteSaver.from_conn_string(db_path) as cp:
            g = build_orchestrator(sup_w, _approving_worker(c), _continuing_overseer(),
                                   _passing_verifier(), checkpointer=cp)
            cfg = {"configurable": {"thread_id": "appr-resume"}}
            init = {"goal": "G", "cwd": "/tmp", "verify_cmd": ["true"], "max_iterations": 3,
                    "loop_threshold": 3, "require_approval": True, "iteration": 0, "signatures": [],
                    "feedback": "", "verified": False, "done": False, "stop_reason": "", "history": []}
            res = g.invoke(init, cfg)
            assert "__interrupt__" in res
            assert c["work"] == 0, "审批前 worker 不应执行"
            # approve 续跑
            from langgraph.types import Command
            res2 = g.invoke(Command(resume="approve"), cfg)
            assert res2.get("verified") is True, "approve 后应跑到验收通过"
            assert c["work"] == 1, "approve 后 worker 应执行一次"


def test_resume_orchestrated_with_reject_returns_to_supervisor(tmp_path):
    """resume_orchestrated(resume_value='reject') → 回 supervisor → 安全方案 → 直通到 worker。"""
    from driving.orchestrator import resume_orchestrated, drive_orchestrated

    db_path = str(tmp_path / "cp.db")
    c = {"work": 0, "sup": 0}
    _wrapped = [_safe_after_reject_supervisor]

    def supervisor_wrapped(state):
        c["sup"] += 1
        result = _wrapped[0](state)
        # verify 通过后 feedback 含"已完成且验证通过" → believe_done 收束循环
        fb = state.get("feedback", "")
        if state.get("iteration", 0) >= 1 and "已完成且验证通过" in fb:
            result["believe_done"] = True
        return result

    # 首跑：高风险 → interrupt
    drive_orchestrated(
        goal="G", cwd="/tmp", verify_cmd=["true"],
        project_rules="", repo_map="",
        thread_id="rej-resume", db_path=db_path,
        require_approval=True, max_iterations=3,
        supervisor=supervisor_wrapped,
        worker=_approving_worker(c),
        overseer=_continuing_overseer(),
        verifier=_passing_verifier(),
    )
    assert c["work"] == 0, "首跑 interrupt 前 worker 不执行"
    sup_after_first = c["sup"]

    # reject 续跑：回 supervisor → 安全方案（ls -la）→ 直通 → worker 执行
    final = resume_orchestrated(
        "rej-resume", db_path, resume_value="reject",
        supervisor=supervisor_wrapped,
        worker=_approving_worker(c),
        overseer=_continuing_overseer(),
        verifier=_passing_verifier(),
    )
    assert final is not None, "resume 应返回非 None"
    # reject 后 supervisor 再跑（回 supervisor 重规划）
    assert c["sup"] > sup_after_first, "reject 后应回 supervisor 重规划"
    # 安全方案（ls -la 低风险）直通到 worker
    assert c["work"] >= 1, "reject 后安全方案应直通到 worker"
    assert final.get("verified") is True, "安全方案应验收通过"


def test_approval_request_payload_has_action_and_reason():
    """on_approval_request 回调拿到的 state 含 current_subtask（action）+ interrupt 含 reason。"""
    captured = {"subtask": None}

    def on_approval_request(state):
        captured["subtask"] = state.get("current_subtask", "")

    g, init, _c = _build_graph_for_approval(_high_risk_supervisor, on_approval_request)
    cfg = {"configurable": {"thread_id": "appr-payload"}}
    res = g.invoke(init, cfg)
    # action = 子任务
    assert captured["subtask"] == "git push origin main"
    # interrupt payload 含 reason（LangGraph 把 interrupt({...}) 的参数存进 __interrupt__）
    interrupts = res.get("__interrupt__", [])
    assert len(interrupts) > 0, "应至少一个 interrupt"
    # interrupts[0].value 是 interrupt() 的参数 dict
    intr_val = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
    assert "reason" in intr_val, "interrupt payload 必须含 reason"
    assert "subtask" in intr_val, "interrupt payload 必须含 subtask"


# ---------- 4: API 层 ----------

def test_approve_without_pending_approval_request_returns_409(client):
    """会话无 pending approval_request 事件时 approve → 409（无事可 resume）。"""
    sid = client.post("/api/v1/assistant/sessions",
                      json={"title": "t"}).json()["id"]
    # 没发过消息，没有 approval_request 事件
    r = client.post(f"/api/v1/assistant/sessions/{sid}/approve")
    assert r.status_code == 409
    assert "no pending" in r.json()["detail"].lower() or "pending" in r.json()["detail"].lower()


# ---------- 辅助 fixture ----------

@pytest.fixture()
def client(monkeypatch, tmp_path):
    """隔离 DB + mock orchestrator，返回 TestClient。"""
    monkeypatch.setenv("FLIPPED_MOCK_ORCHESTRATOR", "1")
    monkeypatch.setattr("api.main.FLIPPED_CHECKPOINT_DB", str(tmp_path / "cp.db"))
    from api.main import app
    return TestClient(app)
