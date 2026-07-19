"""M142-B · orchestrator supervisor 接入 IDE 工具面 · TDD 单测。

覆盖：Plan schema 解析 ide_action / prompt 工具清单注入 / ide_action 执行路径
（deny 拦截 + allow 执行 + feedback 回灌）/ factory_events 审计 / 三态互斥 /
真实 GLM e2e（门控：无 LITELLM_MASTER_KEY 或 4000 不可达则 skip）。
除 e2e 外全部确定性（注入 stub + mock caller），无需真 LLM/VS Code 宿主。
"""
from __future__ import annotations

import json
import os
import socket
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from driving.event_log import list_events  # noqa: E402
from driving.ide_tools import IDE_TOOL_REGISTRY  # noqa: E402
from driving.orchestrator import (  # noqa: E402
    Plan,
    _build_supervisor_prompt,
    build_orchestrator,
)


class _Recorder:
    def __init__(self, result=None):
        self.calls = []
        self.result = result if result is not None else {"ok": True}

    def __call__(self, name, args):
        self.calls.append((name, args))
        return self.result


def _run_graph(*, sup_updates, caller, verify_results=None, max_iter=5):
    """注入 stub supervisor（按轮次弹出预置增量）+ stub worker/overseer/verifier 跑图。"""
    c = {"sup": 0, "work": 0}
    vseq = list(verify_results if verify_results is not None else [True])

    def supervisor(state):
        i = c["sup"]; c["sup"] += 1
        upd = dict(sup_updates[i]) if i < len(sup_updates) else {"believe_done": True}
        upd.setdefault("current_subtask", f"sub{i}")
        upd.setdefault("believe_done", False)
        upd["history"] = state.get("history", []) + [{"step": "supervisor"}]
        return upd

    def worker(state):
        c["work"] += 1
        return {"last_obs": {"summary": {"tool_calls": 1}},
                "signatures": state.get("signatures", []) + [f"sig{c['work']}"],
                "history": state.get("history", []) + [{"step": "worker"}]}

    def overseer(state):
        v = {"action": "continue", "efficiency": 0.8, "direction": 0.8, "issues": [], "rationale": "stub"}
        return {"verdict": v, "history": state.get("history", []) + [{"step": "overseer"}]}

    def verifier(cmd, cwd):
        ok = vseq.pop(0) if vseq else True
        return ok, ("" if ok else "FAIL")

    g = build_orchestrator(supervisor, worker, overseer, verifier,
                           checkpointer=None, ide_caller=caller)
    final = g.invoke({
        "goal": "G", "cwd": "/tmp", "verify_cmd": ["true"],
        "max_iterations": max_iter, "loop_threshold": 3,
        "iteration": 0, "signatures": [], "feedback": "", "verified": False,
        "done": False, "stop_reason": "", "history": [],
    })
    return final, c


# ---------- Plan schema ----------


def test_plan_schema_parses_ide_action():
    plan = Plan(believe_done=False, subtask="s", rationale="r",
                ide_action={"name": "ide.getSetting", "args": {"section": "python.defaultInterpreter"}})
    assert plan.ide_action is not None
    assert plan.ide_action.name == "ide.getSetting"
    assert plan.ide_action.args == {"section": "python.defaultInterpreter"}


def test_plan_schema_ide_action_defaults_none():
    plan = Plan(believe_done=False, subtask="s", rationale="r")
    assert plan.ide_action is None


# ---------- prompt 工具清单注入 ----------


def test_supervisor_prompt_includes_ide_tool_registry():
    prompt = _build_supervisor_prompt({"goal": "G", "cwd": "/tmp"})
    assert "ide.getSetting" in prompt
    assert "env.miseUse" in prompt
    assert "ide_action" in prompt


# ---------- ide_action 执行路径 ----------


def test_ide_action_deny_never_executes_and_feeds_back():
    rec = _Recorder()
    final, _ = _run_graph(
        sup_updates=[{"ide_action": {"name": "ide.openTerminal", "args": {"command": "rm -rf /"}}}],
        caller=rec)
    assert rec.calls == [], "deny 路径绝不允许执行 caller"
    assert "[IDE 工具被拦截: deny]" in final["feedback"]
    steps = [h.get("step") for h in final["history"]]
    assert "ide_action" in steps and "worker" not in steps, "ide_action 轮不应派 worker"


def test_ide_action_allow_executes_once_and_feeds_back():
    rec = _Recorder(result={"value": "/usr/bin/python3"})
    final, _ = _run_graph(
        sup_updates=[{"ide_action": {"name": "ide.getSetting",
                                     "args": {"section": "python.defaultInterpreter"}}}],
        caller=rec)
    assert rec.calls == [("ide.getSetting", {"section": "python.defaultInterpreter"})]
    assert "[IDE 工具已执行: ide.getSetting]" in final["feedback"]
    assert "/usr/bin/python3" in final["feedback"]


def test_ide_action_unknown_tool_never_executes():
    rec = _Recorder()
    final, _ = _run_graph(
        sup_updates=[{"ide_action": {"name": "ide.nope", "args": {}}}],
        caller=rec)
    assert rec.calls == []
    assert "未知工具" in final["feedback"]


# ---------- 三态互斥：believe_done 优先于 ide_action ----------


def test_believe_done_takes_priority_over_ide_action():
    rec = _Recorder()
    final, _ = _run_graph(
        sup_updates=[{"believe_done": True,
                      "ide_action": {"name": "ide.getSetting", "args": {"section": "x"}}}],
        caller=rec)
    assert rec.calls == [], "believe_done=True 时不执行 ide_action"
    assert final["stop_reason"] == "verified"
    steps = [h.get("step") for h in final["history"]]
    assert "ide_action" not in steps


# ---------- factory_events 审计 ----------


def test_ide_action_audited_to_factory_events(tmp_path, monkeypatch):
    audit_db = tmp_path / "audit.db"
    monkeypatch.setenv("FLIPPED_DB", str(audit_db))
    rec = _Recorder()
    final, _ = _run_graph(
        sup_updates=[{"ide_action": {"name": "ide.getSetting", "args": {"section": "editor.fontSize"}}}],
        caller=rec)
    assert rec.calls, "allow 路径应已执行"
    fid = final.get("factory_id", "")
    assert fid.startswith("orch-"), "graph 入口应生成 orch- 前缀 session 级 factory_id"
    conn = sqlite3.connect(str(audit_db))
    try:
        events = list_events(conn, fid)
    finally:
        conn.close()
    calls = [e for e in events if e["kind"] == "ide_tool_call"]
    assert len(calls) == 1, "ide_tool_call 事件应写入一次"
    payload = calls[0]["payload"]
    assert payload["name"] == "ide.getSetting"
    assert payload["decision"] == "allow"
    assert payload["args"] == {"section": "editor.fontSize"}


# ---------- 真实 GLM e2e（门控） ----------


def _litellm_reachable() -> bool:
    if not os.environ.get("LITELLM_MASTER_KEY"):
        return False
    try:
        with socket.create_connection(("127.0.0.1", 4000), timeout=2):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _litellm_reachable(),
                    reason="无 LITELLM_MASTER_KEY 或 LiteLLM 127.0.0.1:4000 不可达")
def test_e2e_real_glm_supervisor_emits_legal_ide_action():
    """真实 GLM 单轮：goal 要求读 IDE 设置 → supervisor 应输出注册表内的 ide_action，
    mock caller 记录到调用即算通（不依赖真实 VS Code 桥）。"""
    from driving.orchestrator import default_supervisor

    rec = _Recorder(result={"value": "mocked"})

    def worker(state):  # 兜底：GLM 若改派 subtask 也不崩
        return {"last_obs": {"summary": {"tool_calls": 1}},
                "signatures": state.get("signatures", []) + ["stub"],
                "history": state.get("history", []) + [{"step": "worker"}]}

    def overseer(state):
        return {"verdict": {"action": "continue", "efficiency": 0.8, "direction": 0.8,
                            "issues": [], "rationale": "stub"},
                "history": state.get("history", []) + [{"step": "overseer"}]}

    g = build_orchestrator(default_supervisor, worker, overseer,
                           lambda cmd, cwd: (True, ""), checkpointer=None, ide_caller=rec)
    final = g.invoke({
        "goal": "读取工作区设置 python.defaultInterpreter 的值（用 IDE 工具 ide.getSetting 读取）",
        "cwd": os.path.dirname(__file__) + "/..", "verify_cmd": ["true"],
        "max_iterations": 3, "loop_threshold": 3,
        "iteration": 0, "signatures": [], "feedback": "", "verified": False,
        "done": False, "stop_reason": "", "history": [],
    })
    assert rec.calls, f"GLM 未产生任何 IDE 工具调用；history={json.dumps(final['history'], ensure_ascii=False)[:800]}"
    for name, _args in rec.calls:
        assert name in IDE_TOOL_REGISTRY, f"GLM 调了注册表外工具: {name}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
