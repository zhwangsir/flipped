"""质量硬化 pass — code-review 发现的 HIGH/MEDIUM 修复回归测试。"""
import asyncio
from pathlib import Path

from api.main import _build_real_nodes, _deliver, _gather_project_context
from api import project_state as ps
from executor.openhands_worker import OpenHandsWorker


# ---- Fix 1: _default_agent_api_key 永不抛(去 TOCTOU) ----

def test_default_agent_api_key_graceful_when_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENHANDS_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # 无 key 文件
    assert OpenHandsWorker._default_agent_api_key() == ""


def test_default_agent_api_key_env_wins(monkeypatch):
    monkeypatch.setenv("OPENHANDS_API_KEY", "sekret")
    assert OpenHandsWorker._default_agent_api_key() == "sekret"


# ---- Fix 1(核心): _deliver 交付失败绝不传播(不翻转已通过的验收) ----

def test_deliver_never_raises_on_sandbox_failure(monkeypatch):
    def boom_factory(*a, **k):
        def deliver(goal):
            raise RuntimeError("sandbox down")
        return deliver

    monkeypatch.setattr("executor.sandbox_deliver.make_sandbox_deliver", boom_factory)
    # 沙盒交付抛错时,_deliver 必须吞掉(否则外层会把已 verified 会话打成 error)
    asyncio.run(_deliver("sess-hardening", "建 API", "/projects/x"))  # 不抛即通过


def test_deliver_never_raises_on_apikey_failure(monkeypatch):
    # 读 key 抛错也不该传播
    monkeypatch.setattr(OpenHandsWorker, "_default_agent_api_key",
                        staticmethod(lambda: (_ for _ in ()).throw(OSError("perm"))))
    asyncio.run(_deliver("sess-hardening2", "x", "/projects/x"))  # 不抛即通过


# ---- Fix 2: _gather_project_context(可放进 to_thread 的同步聚合) ----

def test_gather_project_context(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("务必用 pytest", encoding="utf-8")
    ps.set_active(tmp_path)
    try:
        verify_cmd, rules, repo = _gather_project_context({})
        assert verify_cmd == ["python3", "-m", "pytest", "-q"]
        assert "务必用 pytest" in rules
        assert "技术栈" in repo and "Python" in repo
    finally:
        ps.clear_active()


def test_gather_project_context_no_project():
    ps.clear_active()
    verify_cmd, rules, repo = _gather_project_context({})
    assert verify_cmd == ["true"]
    assert rules == "" and repo == ""


# ---- Fix 3: _build_real_nodes 首跑/resume 共用,恢复也接事件流 ----

def test_build_real_nodes_structure():
    nodes = _build_real_nodes("s1", "/projects/x", ["true"])
    assert set(nodes) == {"supervisor", "worker", "overseer", "verifier"}
    assert all(callable(v) for v in nodes.values())
