"""M188.1 · verify_cmd 确定性校验 TDD 测试。

覆盖：
- 纯逻辑（goal.py）：verify_available（None/[]/["true"]/正常命令）、
  verify_verdict（达成 / 未达成含输出尾部截断）
- POST /goal verify_cmd 入参：空项 422、安全闸 422、合法落盘到 session.verify_cmd
- _goal_loop 接线：det 命中 → 跳过 LLM judge（judge 事件 source=verify_cmd）；
  未配置 / FLIPPED_GOAL_VERIFY=0 → LLM judge（source=llm，向后兼容）
- _verify_deterministic：安全闸不过 None、执行异常 None（fail-safe）、
  超时 → 非达成、chat 通路 host 子进程真实执行、agent 通路走沙盒 verifier
"""
from __future__ import annotations

import asyncio
import subprocess
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.goal import verify_available, verify_verdict


# ====================================================================
# 1 · 纯逻辑：verify_available / verify_verdict
# ====================================================================

def test_verify_available_none_empty_sentinel():
    assert verify_available(None) is False
    assert verify_available([]) is False
    assert verify_available(["true"]) is False


def test_verify_available_real_command():
    assert verify_available(["pytest", "-q"]) is True
    assert verify_available(["bash", "run.sh"]) is True


def test_verify_verdict_ok():
    assert verify_verdict(True, "anything") == {"achieved": True, "gap": ""}


def test_verify_verdict_fail_tail_truncated():
    out = "x" * 1000
    v = verify_verdict(False, out)
    assert v["achieved"] is False
    assert v["gap"].startswith("verify_cmd 未通过")
    assert "x" * 400 in v["gap"] and "x" * 401 not in v["gap"], "只留输出尾部 400 字符"


def test_verify_verdict_fail_empty_output():
    v = verify_verdict(False, "")
    assert v["achieved"] is False and "无输出" in v["gap"]


# ====================================================================
# 2 · POST /goal verify_cmd 入参校验与落盘
# ====================================================================

@pytest.fixture()
def client(monkeypatch, tmp_path):
    """隔离 DB + mock orchestrator + 防 goal env 污染（沿用 M176 接线测试风格）。"""
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


def _post_goal(client, sid: str, **body):
    return client.post(f"/api/v1/assistant/sessions/{sid}/goal", json=body)


def _events(client, sid: str) -> list[dict]:
    r = client.get(f"/api/v1/sessions/{sid}/events")
    assert r.status_code == 200, r.text
    return r.json()


def _goal_events(client, sid: str) -> list[dict]:
    return [e for e in _events(client, sid) if e["type"] == "goal"]


def _wait_task_gone(sid: str, timeout: float = 8.0) -> None:
    from api.main import RUNNING_TASKS
    deadline = time.time() + timeout
    while time.time() < deadline:
        if RUNNING_TASKS.get(sid) is None:
            return
        time.sleep(0.01)
    raise AssertionError(f"goal task 未在 {timeout}s 内结束: {sid}")


def _fake_chat_recorder(calls: list[str]):
    async def _fake_chat(session_id, task_id, description, model_alias, mode):
        calls.append(description)
    return _fake_chat


def _fake_judge(verdict):
    async def _judge(state, session_id, model_alias):
        return verdict
    return _judge


def _no_judge(state, session_id, model_alias):  # async 化在调用点
    raise AssertionError("LLM judge 不应被调用（det 路径必须短路）")


def test_post_goal_verify_cmd_empty_item_422(client):
    sid = _new_session(client)
    r = _post_goal(client, sid, objective="x", verify_cmd=["echo", "  "])
    assert r.status_code == 422, r.text


def test_post_goal_verify_cmd_blocked_422(client):
    sid = _new_session(client)
    r = _post_goal(client, sid, objective="x", verify_cmd=["sudo", "ls"])
    assert r.status_code == 422, r.text
    assert "安全闸" in r.text


def test_post_goal_verify_cmd_persisted(client, monkeypatch):
    sid = _new_session(client)
    monkeypatch.setattr("api.main._run_chat", _fake_chat_recorder([]))
    monkeypatch.setattr("api.assistant._verify_deterministic",
                        _fake_judge({"achieved": True, "gap": ""}))
    r = _post_goal(client, sid, objective="x", verify_cmd=["bash", "-c", "exit 0"])
    assert r.status_code == 200, r.text
    _wait_task_gone(sid)
    from api.main import store
    sess = store.get(sid)
    assert sess is not None and sess.verify_cmd == ["bash", "-c", "exit 0"]


# ====================================================================
# 3 · _goal_loop 接线：det 优先 / LLM 回落
# ====================================================================

def test_goal_verify_exit0_achieved_skips_llm_judge(client, monkeypatch):
    sid = _new_session(client)
    monkeypatch.setattr("api.main._run_chat", _fake_chat_recorder([]))

    async def _boom(state, session_id, model_alias):
        raise AssertionError("LLM judge 不应被调用")

    monkeypatch.setattr("api.assistant._judge", _boom)
    r = _post_goal(client, sid, objective="确定性验收", verify_cmd=["bash", "-c", "exit 0"])
    assert r.status_code == 200, r.text
    _wait_task_gone(sid)
    ge = _goal_events(client, sid)
    phases = [e["payload"].get("phase") for e in ge]
    assert phases == ["set", "iter", "judge", "achieved"], f"1 轮即确定性达成: {phases}"
    judge = [e["payload"] for e in ge if e["payload"].get("phase") == "judge"][0]
    assert judge["achieved"] is True
    assert judge["source"] == "verify_cmd"


def test_goal_verify_fail_gap_signature_no_progress(client, monkeypatch, tmp_path):
    """恒失败且输出不变 → 两轮相同 gap 签名 → no-progress 熔断（确定性行为）。"""
    script = tmp_path / "fail.sh"
    script.write_text("#!/bin/sh\necho SOMEGAP\nexit 1\n", encoding="utf-8")
    sid = _new_session(client)
    monkeypatch.setattr("api.main._run_chat", _fake_chat_recorder([]))

    async def _boom(state, session_id, model_alias):
        raise AssertionError("LLM judge 不应被调用")

    monkeypatch.setattr("api.assistant._judge", _boom)
    r = _post_goal(client, sid, objective="x", max_iterations=5,
                   verify_cmd=["bash", str(script)])
    assert r.status_code == 200, r.text
    _wait_task_gone(sid)
    ge = _goal_events(client, sid)
    phases = [e["payload"].get("phase") for e in ge]
    assert phases == ["set", "iter", "judge", "iter", "judge", "exhausted"], phases
    judges = [e["payload"] for e in ge if e["payload"].get("phase") == "judge"]
    assert len(judges) == 2
    for j in judges:
        assert j["achieved"] is False and j["source"] == "verify_cmd"
        assert "SOMEGAP" in j["gap"], "gap 须含命令输出尾部"
    exhausted = [e["payload"] for e in ge if e["payload"].get("phase") == "exhausted"][0]
    assert exhausted["reason"] == "no_progress"


def test_goal_without_verify_cmd_llm_judge_source_llm(client, monkeypatch):
    """向后兼容：未配置 verify_cmd → LLM judge，judge 事件 source=llm。"""
    sid = _new_session(client)
    monkeypatch.setattr("api.main._run_chat", _fake_chat_recorder([]))
    monkeypatch.setattr("api.assistant._judge",
                        _fake_judge({"achieved": True, "gap": ""}))
    r = _post_goal(client, sid, objective="x")
    assert r.status_code == 200, r.text
    _wait_task_gone(sid)
    judge = [e["payload"] for e in _goal_events(client, sid)
             if e["payload"].get("phase") == "judge"][0]
    assert judge["achieved"] is True and judge["source"] == "llm"


def test_goal_verify_disabled_falls_back_to_llm(client, monkeypatch):
    """FLIPPED_GOAL_VERIFY=0 → 即使显式 verify_cmd 也走 LLM judge。"""
    monkeypatch.setenv("FLIPPED_GOAL_VERIFY", "0")
    sid = _new_session(client)
    monkeypatch.setattr("api.main._run_chat", _fake_chat_recorder([]))
    monkeypatch.setattr("api.assistant._judge",
                        _fake_judge({"achieved": True, "gap": ""}))
    r = _post_goal(client, sid, objective="x", verify_cmd=["bash", "-c", "exit 0"])
    assert r.status_code == 200, r.text
    _wait_task_gone(sid)
    judge = [e["payload"] for e in _goal_events(client, sid)
             if e["payload"].get("phase") == "judge"][0]
    assert judge["source"] == "llm"


def test_goal_agent_dispatch_cfg_carries_explicit_verify_cmd(client, monkeypatch):
    """agent 通路：显式 verify_cmd 注入 orchestrator cfg（防每轮探测覆盖丢显式值）。"""
    sid = _new_session(client, mode="agent")
    seen: list[dict] = []

    async def _fake_orch(session_id, task_id, req):
        seen.append(req.context.get("orchestrator") or {})

    monkeypatch.setattr("api.main._run_orchestrator", _fake_orch)
    monkeypatch.setattr("api.assistant._verify_deterministic",
                        _fake_judge({"achieved": True, "gap": ""}))
    monkeypatch.setattr("api.assistant._git_snapshot", lambda root: None)
    r = _post_goal(client, sid, objective="x",
                   verify_cmd=["bash", "-c", "exit 0"])
    assert r.status_code == 200, r.text
    _wait_task_gone(sid)
    assert seen and seen[0].get("verify_cmd") == ["bash", "-c", "exit 0"], seen


# ====================================================================
# 4 · _verify_deterministic 直接单测
# ====================================================================

def _mk_session_with_verify(verify_cmd) -> str:
    from api.main import store
    s = store.create("t", mode="chat")
    store.update(s.id, verify_cmd=list(verify_cmd))
    return s.id


def test_det_gate_blocked_returns_none():
    sid = _mk_session_with_verify(["sudo", "ls"])
    assert asyncio.run(_det(sid, "chat")) is None


def test_det_unavailable_returns_none():
    from api.main import store
    s = store.create("t", mode="chat")  # verify_cmd 缺省 []
    assert asyncio.run(_det(s.id, "chat")) is None
    store.update(s.id, verify_cmd=["true"])
    assert asyncio.run(_det(s.id, "chat")) is None


def test_det_unknown_session_returns_none():
    assert asyncio.run(_det("sess-不存在的", "chat")) is None


def test_det_env_off_returns_none(monkeypatch):
    monkeypatch.setenv("FLIPPED_GOAL_VERIFY", "0")
    sid = _mk_session_with_verify(["bash", "-c", "exit 0"])
    assert asyncio.run(_det(sid, "chat")) is None


def test_det_host_exit0_achieved():
    sid = _mk_session_with_verify(["bash", "-c", "exit 0"])
    assert asyncio.run(_det(sid, "chat")) == {"achieved": True, "gap": ""}


def test_det_host_nonzero_with_output(tmp_path):
    script = tmp_path / "f.sh"
    script.write_text("#!/bin/sh\necho TAILMARK\nexit 3\n", encoding="utf-8")
    sid = _mk_session_with_verify(["bash", str(script)])
    v = asyncio.run(_det(sid, "chat"))
    assert v is not None and v["achieved"] is False and "TAILMARK" in v["gap"]


def test_det_host_exception_returns_none(monkeypatch):
    sid = _mk_session_with_verify(["bash", "-c", "exit 0"])

    def _boom(*a, **k):
        raise OSError("disk on fire")

    monkeypatch.setattr("api.assistant.subprocess.run", _boom)
    assert asyncio.run(_det(sid, "chat")) is None


def test_det_host_timeout_not_achieved(monkeypatch):
    sid = _mk_session_with_verify(["bash", "-c", "exit 0"])

    def _timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="bash", timeout=120)

    monkeypatch.setattr("api.assistant.subprocess.run", _timeout)
    v = asyncio.run(_det(sid, "chat"))
    assert v is not None and v["achieved"] is False and "超时" in v["gap"]


def test_det_agent_uses_sandbox_verifier(monkeypatch):
    sid = _mk_session_with_verify(["pytest", "-q"])
    called: list[tuple] = []

    def _fake_make(agent_host, working_dir, api_key, **kw):
        def _verify(cmd, cwd):
            called.append((tuple(cmd), cwd))
            return True, "ok"
        return _verify

    monkeypatch.setattr("executor.sandbox_verify.make_sandbox_verifier", _fake_make)
    monkeypatch.setattr(
        "executor.openhands_worker.OpenHandsWorker._default_agent_api_key",
        staticmethod(lambda: ""))
    v = asyncio.run(_det(sid, "agent"))
    assert v == {"achieved": True, "gap": ""}
    assert called and called[0][0] == ("pytest", "-q"), "agent 通路必须走沙盒 verifier"


def test_det_agent_sandbox_exception_returns_none(monkeypatch):
    sid = _mk_session_with_verify(["pytest", "-q"])

    def _boom(*a, **k):
        raise ConnectionError("sandbox down")

    monkeypatch.setattr("executor.sandbox_verify.make_sandbox_verifier", _boom)
    monkeypatch.setattr(
        "executor.openhands_worker.OpenHandsWorker._default_agent_api_key",
        staticmethod(lambda: ""))
    assert asyncio.run(_det(sid, "agent")) is None


async def _det(sid: str, mode: str):
    from api.assistant import _verify_deterministic
    return await _verify_deterministic(sid, mode)
