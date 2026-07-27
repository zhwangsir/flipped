"""M157.11 · Validator 复合验证 TDD 单测。

对标 Trae-Agent 第 2.2 节：Verifier 从"只跑验收命令"升级为"复合验证"：
verify_cmd + lint + typecheck + test_cases 检查。

验证：
- verify_cmd 通过但 lint 失败 → verified=False
- test_cases 部分失败 → test_cases_passed < total
- lint/typecheck 工具未装 → 跳过（skip 不阻断）
- 全部通过 → verified=True
- 无 test_cases 时走原始逻辑（向后兼容）
- 复合验证可注入（mock compound_verifier）
"""
from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from driving.orchestrator import (  # noqa: E402
    build_orchestrator,
    default_compound_verifier,
    _run_lint,
    _run_typecheck,
    _run_test_cases,
)


# ---------- _run_lint / _run_typecheck / _run_test_cases 单测 ----------


def _completed(returncode=0, stdout="", stderr=""):
    """构造 subprocess.CompletedProcess-like 对象。"""
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_run_lint_skip_when_no_tool(monkeypatch):
    """ruff/pyflakes 均未装 → status=skip, ok=True（不阻断）。"""
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    result = _run_lint("/tmp", None)
    assert result["status"] == "skip"
    assert result["ok"] is True  # skip 不阻断


def test_run_lint_pass_with_ruff(monkeypatch):
    """ruff 可用且退出 0 → status=pass。"""
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/ruff" if cmd == "ruff" else None)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _completed(0, "All checks passed!", "")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = _run_lint("/tmp", ["foo.py"])
    assert result["status"] == "pass"
    assert result["ok"] is True
    assert result["tool"] == "ruff"
    assert "ruff" in calls[0][0]


def test_run_lint_fail_with_ruff(monkeypatch):
    """ruff 可用但退出非 0 → status=fail。"""
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/ruff" if cmd == "ruff" else None)

    def fake_run(cmd, **kw):
        return _completed(1, "foo.py:1:1 F841 unused variable", "")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = _run_lint("/tmp", ["foo.py"])
    assert result["status"] == "fail"
    assert result["ok"] is False
    assert "unused variable" in result["output"]


def test_run_lint_fallback_to_pyflakes(monkeypatch):
    """ruff 没装但 pyflakes 可用 → 用 pyflakes。"""
    monkeypatch.setattr("shutil.which",
                        lambda cmd: "/usr/local/bin/pyflakes" if cmd == "pyflakes" else None)

    def fake_run(cmd, **kw):
        return _completed(0, "", "")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = _run_lint("/tmp", ["foo.py"])
    assert result["status"] == "pass"
    assert result["tool"] == "pyflakes"


def test_run_typecheck_skip_when_no_tool(monkeypatch):
    """mypy/pyright 均未装 → status=skip, ok=True。"""
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    result = _run_typecheck("/tmp", None)
    assert result["status"] == "skip"
    assert result["ok"] is True


def test_run_typecheck_pass_with_mypy(monkeypatch):
    """mypy 可用且退出 0 → status=pass。"""
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/mypy" if cmd == "mypy" else None)

    def fake_run(cmd, **kw):
        return _completed(0, "Success: no issues found", "")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = _run_typecheck("/tmp", ["foo.py"])
    assert result["status"] == "pass"
    assert result["tool"] == "mypy"


def test_run_typecheck_fail_with_mypy(monkeypatch):
    """mypy 可用但退出非 0 → status=fail。"""
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/mypy" if cmd == "mypy" else None)

    def fake_run(cmd, **kw):
        return _completed(1, "foo.py:3: error: Incompatible types", "")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = _run_typecheck("/tmp", ["foo.py"])
    assert result["status"] == "fail"
    assert result["ok"] is False


def test_run_test_cases_all_pass(monkeypatch):
    """所有 test_case 命令退出 0 → passed=total。"""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _completed(0, "passed", "")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = _run_test_cases(
        ["pytest tests/test_a.py", "python -c 'assert 1==1'"],
        "/tmp")
    assert result["passed"] == 2
    assert result["total"] == 2
    assert result["failures"] == []


def test_run_test_cases_partial_fail(monkeypatch):
    """部分 test_case 失败 → passed < total, failures 记录失败命令。"""
    results = [_completed(0, "ok", ""), _completed(1, "FAIL: boundary", ""),
               _completed(0, "ok", "")]

    def fake_run(cmd, **kw):
        return results.pop(0)

    monkeypatch.setattr("subprocess.run", fake_run)
    result = _run_test_cases(
        ["pytest test_normal", "pytest test_boundary", "pytest test_error"],
        "/tmp")
    assert result["passed"] == 2
    assert result["total"] == 3
    assert len(result["failures"]) == 1
    assert "test_boundary" in result["failures"][0]


def test_run_test_cases_empty_list():
    """空 test_cases → passed=0, total=0, failures=[]。"""
    result = _run_test_cases([], "/tmp")
    assert result["passed"] == 0
    assert result["total"] == 0
    assert result["failures"] == []


# ---------- default_compound_verifier 集成单测 ----------


def test_compound_verifier_all_pass(monkeypatch):
    """verify_cmd + lint + typecheck + test_cases 全过 → verified=True。"""
    monkeypatch.setattr("shutil.which",
                        lambda cmd: f"/usr/bin/{cmd}" if cmd in ("ruff", "mypy") else None)
    monkeypatch.setattr("subprocess.run",
                        lambda cmd, **kw: _completed(0, "ok", ""))
    state = {
        "verify_cmd": ["pytest", "-q"],
        "cwd": "/tmp",
        "test_cases": ["pytest test_normal", "pytest test_boundary"],
        "last_obs": {"summary": {"files": ["foo.py"]}},
    }
    base_verifier = lambda cmd, cwd: (True, "2 passed")
    verdict = default_compound_verifier(state, base_verifier)
    assert verdict["verified"] is True
    assert verdict["verify_cmd_ok"] is True
    assert verdict["lint_ok"] is True
    assert verdict["typecheck_ok"] is True
    assert verdict["test_cases_passed"] == 2
    assert verdict["test_cases_total"] == 2
    assert verdict["failures"] == []


def test_compound_verifier_verify_cmd_pass_lint_fail(monkeypatch):
    """verify_cmd 通过但 lint 失败 → verified=False, lint_ok=False。"""
    monkeypatch.setattr("shutil.which",
                        lambda cmd: f"/usr/bin/{cmd}" if cmd in ("ruff", "mypy") else None)

    def fake_run(cmd, **kw):
        # ruff check 失败, mypy 通过
        if "ruff" in str(cmd[0] if isinstance(cmd, list) else cmd):
            return _completed(1, "foo.py:1:1 F841 unused", "")
        return _completed(0, "ok", "")

    monkeypatch.setattr("subprocess.run", fake_run)
    state = {
        "verify_cmd": ["pytest", "-q"],
        "cwd": "/tmp",
        "test_cases": ["pytest test_normal"],
        "last_obs": {"summary": {"files": ["foo.py"]}},
    }
    base_verifier = lambda cmd, cwd: (True, "1 passed")
    verdict = default_compound_verifier(state, base_verifier)
    assert verdict["verified"] is False, "lint 失败 → verified=False"
    assert verdict["verify_cmd_ok"] is True
    assert verdict["lint_ok"] is False
    assert any("lint" in f for f in verdict["failures"])


def test_compound_verifier_test_cases_partial_fail(monkeypatch):
    """test_cases 部分失败 → test_cases_passed < total, verified=False。"""
    monkeypatch.setattr("shutil.which",
                        lambda cmd: f"/usr/bin/{cmd}" if cmd in ("ruff", "mypy") else None)

    def fake_run(cmd, **kw):
        cmd_str = str(cmd)
        if "test_boundary" in cmd_str:
            return _completed(1, "FAIL: boundary", "")
        return _completed(0, "ok", "")

    monkeypatch.setattr("subprocess.run", fake_run)
    state = {
        "verify_cmd": ["pytest", "-q"],
        "cwd": "/tmp",
        "test_cases": ["pytest test_normal", "pytest test_boundary", "pytest test_error"],
        "last_obs": {"summary": {"files": ["foo.py"]}},
    }
    base_verifier = lambda cmd, cwd: (True, "ok")
    verdict = default_compound_verifier(state, base_verifier)
    assert verdict["verified"] is False
    assert verdict["test_cases_passed"] == 2
    assert verdict["test_cases_total"] == 3
    assert any("test_cases" in f for f in verdict["failures"])


def test_compound_verifier_tools_unavailable_skip_not_blocking(monkeypatch):
    """lint/typecheck 工具未装 → skip, 不阻断, 只要 verify_cmd + test_cases 过就 verified=True。"""
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    monkeypatch.setattr("subprocess.run",
                        lambda cmd, **kw: _completed(0, "ok", ""))
    state = {
        "verify_cmd": ["pytest", "-q"],
        "cwd": "/tmp",
        "test_cases": ["pytest test_normal"],
        "last_obs": {"summary": {"files": ["foo.py"]}},
    }
    base_verifier = lambda cmd, cwd: (True, "ok")
    verdict = default_compound_verifier(state, base_verifier)
    assert verdict["verified"] is True, "skip 不阻断, 全过应 verified=True"
    assert verdict["lint_status"] == "skip"
    assert verdict["typecheck_status"] == "skip"
    assert verdict["lint_ok"] is True  # skip 算 ok


def test_compound_verifier_verify_cmd_fail(monkeypatch):
    """verify_cmd 失败 → verified=False, verify_cmd_ok=False。"""
    monkeypatch.setattr("shutil.which",
                        lambda cmd: f"/usr/bin/{cmd}" if cmd in ("ruff", "mypy") else None)
    monkeypatch.setattr("subprocess.run",
                        lambda cmd, **kw: _completed(0, "ok", ""))
    state = {
        "verify_cmd": ["pytest", "-q"],
        "cwd": "/tmp",
        "test_cases": ["pytest test_normal"],
        "last_obs": {"summary": {"files": ["foo.py"]}},
    }
    base_verifier = lambda cmd, cwd: (False, "1 failed")
    verdict = default_compound_verifier(state, base_verifier)
    assert verdict["verified"] is False
    assert verdict["verify_cmd_ok"] is False
    assert any("verify_cmd" in f for f in verdict["failures"])


def test_compound_verifier_no_test_cases_in_state(monkeypatch):
    """state 无 test_cases → test_cases_total=0, 不影响 verified（只要其他过）。"""
    monkeypatch.setattr("shutil.which",
                        lambda cmd: f"/usr/bin/{cmd}" if cmd in ("ruff", "mypy") else None)
    monkeypatch.setattr("subprocess.run",
                        lambda cmd, **kw: _completed(0, "ok", ""))
    state = {
        "verify_cmd": ["pytest", "-q"],
        "cwd": "/tmp",
        "last_obs": {"summary": {"files": ["foo.py"]}},
    }
    base_verifier = lambda cmd, cwd: (True, "ok")
    verdict = default_compound_verifier(state, base_verifier)
    assert verdict["test_cases_total"] == 0
    assert verdict["test_cases_passed"] == 0


# ---------- verify() 图节点：复合验证路径 vs 原始路径 ----------


def _make_graph_with_compound(*, sup_test_cases=None, base_verifier=None,
                              compound_verifier=None, monkeypatch_subproc=None,
                              believe_done=True):
    """构建带 compound_verifier 的图，注入 stub supervisor/worker/overseer。"""
    c = {"work": 0, "over": 0}

    def supervisor(state):
        return {"current_subtask": "sub", "believe_done": believe_done,
                "test_cases": sup_test_cases or [],
                "history": state.get("history", []) + [{"step": "supervisor"}]}

    def worker(state):
        c["work"] += 1
        return {"last_obs": {"summary": {"tool_calls": 1, "files": ["foo.py"]}},
                "signatures": state.get("signatures", []) + ["sig"],
                "history": state.get("history", []) + [{"step": "worker"}]}

    def overseer(state):
        c["over"] += 1
        return {"verdict": {"action": "continue"}, "history": state.get("history", [])}

    if base_verifier is None:
        base_verifier = lambda cmd, cwd: (True, "ok")

    g = build_orchestrator(supervisor, worker, overseer, base_verifier,
                           checkpointer=None, compound_verifier=compound_verifier)
    return g, c


def test_verify_node_uses_compound_when_test_cases_present(monkeypatch):
    """state 有 test_cases → verify() 走复合验证路径。"""
    monkeypatch.setattr("shutil.which",
                        lambda cmd: f"/usr/bin/{cmd}" if cmd in ("ruff", "mypy") else None)
    monkeypatch.setattr("subprocess.run",
                        lambda cmd, **kw: _completed(0, "ok", ""))
    compound_calls = []

    def my_compound(state, verifier):
        compound_calls.append(state.get("test_cases"))
        return {"verified": True, "verify_cmd_ok": True,
                "lint_ok": True, "typecheck_ok": True,
                "test_cases_passed": 2, "test_cases_total": 2,
                "failures": [], "output": "ok"}

    g, c = _make_graph_with_compound(
        sup_test_cases=["pytest test_normal", "pytest test_boundary"],
        compound_verifier=my_compound)
    final = g.invoke({
        "goal": "G", "cwd": "/tmp", "verify_cmd": ["true"],
        "max_iterations": 3, "loop_threshold": 3,
        "iteration": 0, "signatures": [], "feedback": "", "verified": False,
        "done": False, "stop_reason": "", "history": [],
    })
    assert final["verified"] is True
    assert final["stop_reason"] == "verified"
    assert len(compound_calls) == 1, "compound_verifier 应被调用一次"
    assert compound_calls[0] == ["pytest test_normal", "pytest test_boundary"]


def test_verify_node_original_logic_when_no_test_cases(monkeypatch):
    """state 无 test_cases → verify() 走原始逻辑（向后兼容, 不调 compound_verifier）。"""
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    compound_calls = []

    def my_compound(state, verifier):
        compound_calls.append(True)
        return {"verified": True, "verify_cmd_ok": True,
                "lint_ok": True, "typecheck_ok": True,
                "test_cases_passed": 0, "test_cases_total": 0,
                "failures": [], "output": "ok"}

    g, c = _make_graph_with_compound(
        sup_test_cases=[],  # 无 test_cases
        compound_verifier=my_compound)
    final = g.invoke({
        "goal": "G", "cwd": "/tmp", "verify_cmd": ["true"],
        "max_iterations": 3, "loop_threshold": 3,
        "iteration": 0, "signatures": [], "feedback": "", "verified": False,
        "done": False, "stop_reason": "", "history": [],
    })
    assert final["verified"] is True
    assert final["stop_reason"] == "verified"
    assert compound_calls == [], "无 test_cases 时不应调用 compound_verifier"


def test_verify_node_compound_failure_feeds_back_to_supervisor(monkeypatch):
    """复合验证失败 → feedback 回灌给 supervisor, 不判 done。"""
    monkeypatch.setattr("shutil.which",
                        lambda cmd: f"/usr/bin/{cmd}" if cmd in ("ruff", "mypy") else None)

    def my_compound(state, verifier):
        return {"verified": False, "verify_cmd_ok": True,
                "lint_ok": False, "typecheck_ok": True,
                "test_cases_passed": 1, "test_cases_total": 2,
                "failures": ["lint 失败: foo.py:1 F841", "test_cases 部分失败 (1/2)"],
                "output": "FAIL"}

    g, c = _make_graph_with_compound(
        sup_test_cases=["pytest test_normal", "pytest test_boundary"],
        compound_verifier=my_compound,
        believe_done=False)  # 不 believe_done, 让 verify 跑完后回 sup
    final = g.invoke({
        "goal": "G", "cwd": "/tmp", "verify_cmd": ["true"],
        "max_iterations": 3, "loop_threshold": 3,
        "iteration": 0, "signatures": [], "feedback": "", "verified": False,
        "done": False, "stop_reason": "", "history": [],
    })
    # 复合验证失败 → feedback 含 "复合验证失败"
    assert "复合验证失败" in final.get("feedback", ""), \
        f"复合验证失败应回灌 feedback, 实: {final.get('feedback', '')[:200]}"
    assert final.get("verified") is False


def test_verify_node_compound_pass_but_not_believe_done(monkeypatch):
    """复合验证通过 but believe_done=False → 拆下一个子任务（feedback 含'已完成'提示）。"""
    monkeypatch.setattr("shutil.which",
                        lambda cmd: f"/usr/bin/{cmd}" if cmd in ("ruff", "mypy") else None)

    def my_compound(state, verifier):
        return {"verified": True, "verify_cmd_ok": True,
                "lint_ok": True, "typecheck_ok": True,
                "test_cases_passed": 2, "test_cases_total": 2,
                "failures": [], "output": "ok"}

    g, c = _make_graph_with_compound(
        sup_test_cases=["pytest test_normal", "pytest test_boundary"],
        compound_verifier=my_compound,
        believe_done=False)
    final = g.invoke({
        "goal": "G", "cwd": "/tmp", "verify_cmd": ["true"],
        "max_iterations": 3, "loop_threshold": 3,
        "iteration": 0, "signatures": [], "feedback": "", "verified": False,
        "done": False, "stop_reason": "", "history": [],
    })
    # 复合验证通过但未 believe_done → feedback 含"复合验证通过"提示
    assert "复合验证通过" in final.get("feedback", "") or "已完成" in final.get("feedback", "")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
