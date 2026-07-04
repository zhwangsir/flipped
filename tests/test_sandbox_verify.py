"""F1d — 沙盒 verifier 单测(注入假 workspace,无需真沙盒/LLM)。"""
from types import SimpleNamespace

from executor.sandbox_verify import make_sandbox_verifier


class _FakeResult(SimpleNamespace):
    """模拟 openhands CommandResult(exit_code/stdout/stderr/timeout_occurred)。"""


class _FakeWorkspace:
    """记录构造参数与 execute_command 调用的假 RemoteWorkspace。"""

    last: "dict" = {}

    def __init__(self, **kwargs):
        _FakeWorkspace.last = {"init": kwargs, "calls": []}
        self._store = _FakeWorkspace.last

    def __enter__(self):
        self._store["entered"] = True
        return self

    def __exit__(self, *exc):
        self._store["exited"] = True
        return False

    def execute_command(self, command, cwd=None, timeout=300.0):
        self._store["calls"].append({"command": command, "cwd": cwd, "timeout": timeout})
        return self._result

    @classmethod
    def factory(cls, result):
        def _make(**kwargs):
            ws = cls(**kwargs)
            ws._result = result
            return ws
        return _make


def test_passing_command_runs_in_sandbox():
    result = _FakeResult(command="pytest -q", exit_code=0, stdout="3 passed", stderr="",
                         timeout_occurred=False)
    verify = make_sandbox_verifier(
        "http://localhost:8000", "/projects/demo", "key",
        workspace_factory=_FakeWorkspace.factory(result),
    )
    ok, output = verify(["pytest", "-q"], "/projects/demo")
    assert ok is True
    assert "3 passed" in output
    # 命令确实在沙盒里、按沙盒 cwd 执行
    call = _FakeWorkspace.last["calls"][0]
    assert call["command"] == "pytest -q"
    assert call["cwd"] == "/projects/demo"
    assert _FakeWorkspace.last["entered"] and _FakeWorkspace.last["exited"]
    assert _FakeWorkspace.last["init"]["working_dir"] == "/projects/demo"


def test_failing_command_returns_false_with_output():
    result = _FakeResult(command="pytest -q", exit_code=1, stdout="", stderr="1 failed",
                         timeout_occurred=False)
    verify = make_sandbox_verifier(
        "http://localhost:8000", "/projects/demo",
        workspace_factory=_FakeWorkspace.factory(result),
    )
    ok, output = verify(["pytest", "-q"], "/projects/demo")
    assert ok is False
    assert "1 failed" in output


def test_blocked_command_never_touches_sandbox():
    # frobnicate 不在白名单 → 拦截,不应连沙盒
    calls_marker = _FakeResult(exit_code=0, stdout="", stderr="", timeout_occurred=False)
    factory = _FakeWorkspace.factory(calls_marker)
    _FakeWorkspace.last = {"init": {}, "calls": []}
    verify = make_sandbox_verifier("h", "/projects/demo", workspace_factory=factory)
    ok, output = verify(["frobnicate", "x"], "/projects/demo")
    assert ok is False
    assert "blocked" in output
    assert _FakeWorkspace.last["calls"] == []  # 未执行


def test_dangerous_pattern_blocked():
    verify = make_sandbox_verifier("h", "/projects/demo",
                                   workspace_factory=_FakeWorkspace.factory(None))
    ok, output = verify(["rm", "-rf", "/"], "/projects/demo")
    assert ok is False
    assert "blocked" in output


def test_high_risk_command_requires_approval():
    # git push 过白名单但属高风险 → 拦截(自主验证不该私自 push)
    _FakeWorkspace.last = {"init": {}, "calls": []}
    verify = make_sandbox_verifier("h", "/projects/demo",
                                   workspace_factory=_FakeWorkspace.factory(None))
    ok, output = verify(["git", "push", "origin", "main"], "/projects/demo")
    assert ok is False
    assert "high-risk" in output
    assert _FakeWorkspace.last["calls"] == []


def test_timeout_reported_as_failure():
    result = _FakeResult(command="pytest", exit_code=0, stdout="partial", stderr="",
                         timeout_occurred=True)
    verify = make_sandbox_verifier("h", "/projects/demo",
                                   workspace_factory=_FakeWorkspace.factory(result))
    ok, output = verify(["pytest", "-q"], "/projects/demo")
    assert ok is False
    assert "超时" in output


def test_empty_cwd_falls_back_to_working_dir():
    result = _FakeResult(command="pytest", exit_code=0, stdout="", stderr="",
                         timeout_occurred=False)
    verify = make_sandbox_verifier("h", "/projects/fallback",
                                   workspace_factory=_FakeWorkspace.factory(result))
    verify(["pytest", "-q"], "")
    assert _FakeWorkspace.last["calls"][0]["cwd"] == "/projects/fallback"
