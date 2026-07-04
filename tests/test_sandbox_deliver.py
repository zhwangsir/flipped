"""F7 — 交付步(沙盒内自动提交成果)。注入假 workspace,无需真沙盒。"""
from types import SimpleNamespace

from executor.sandbox_deliver import (
    build_commit_command,
    build_commit_message,
    make_sandbox_deliver,
)


class _FakeResult(SimpleNamespace):
    pass


class _FakeWorkspace:
    last: dict = {}

    def __init__(self, **kwargs):
        _FakeWorkspace.last = {"init": kwargs, "calls": []}
        self._store = _FakeWorkspace.last

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute_command(self, command, cwd=None, timeout=120.0):
        self._store["calls"].append({"command": command, "cwd": cwd, "timeout": timeout})
        return self._result

    @classmethod
    def factory(cls, result):
        def _make(**kwargs):
            ws = cls(**kwargs)
            ws._result = result
            return ws
        return _make


# ---- 提交信息 ----

def test_commit_message_from_goal():
    msg = build_commit_message("给项目加一个待办 API")
    assert msg.startswith("feat: 给项目加一个待办 API")
    assert "自主循环" in msg  # trailer


def test_commit_message_truncates_long_subject():
    msg = build_commit_message("x" * 200)
    subject = msg.splitlines()[0]
    assert len(subject) <= len("feat: ") + 72


def test_commit_message_empty_goal_fallback():
    assert build_commit_message("").startswith("feat: 自主开发变更")
    assert build_commit_message("   ").startswith("feat: 自主开发变更")


# ---- 提交命令(注入安全 + 结构) ----

def test_commit_command_has_add_and_commit():
    cmd = build_commit_command("feat: x")
    assert "git add -A" in cmd
    assert "__NOCHANGE__" in cmd and "__COMMITTED__" in cmd
    assert "git init -q" in cmd


def test_commit_command_escapes_single_quotes():
    # 恶意目标里的单引号/分号不能逃出提交信息去执行
    cmd = build_commit_command("feat: '; rm -rf / #")
    # 转义后单引号变 '\'' 序列,rm 只是信息文本
    assert "'\\''" in cmd


# ---- deliver 端到端(假沙盒) ----

def test_deliver_committed():
    result = _FakeResult(stdout="__COMMITTED__\n", stderr="", exit_code=0)
    deliver = make_sandbox_deliver("h", "/projects/demo", "k",
                                   workspace_factory=_FakeWorkspace.factory(result))
    out = deliver("建待办 API")
    assert out["committed"] is True
    assert out["nochange"] is False
    assert out["message"].startswith("feat: 建待办 API")
    call = _FakeWorkspace.last["calls"][0]
    assert call["cwd"] == "/projects/demo"
    assert "commit -q -m" in call["command"]


def test_deliver_nochange():
    result = _FakeResult(stdout="__NOCHANGE__\n", stderr="", exit_code=0)
    deliver = make_sandbox_deliver("h", "/projects/demo",
                                   workspace_factory=_FakeWorkspace.factory(result))
    out = deliver("无改动任务")
    assert out["nochange"] is True
    assert out["committed"] is False


def test_deliver_reports_raw_output_when_neither_marker():
    result = _FakeResult(stdout="", stderr="fatal: something", exit_code=1)
    deliver = make_sandbox_deliver("h", "/projects/demo",
                                   workspace_factory=_FakeWorkspace.factory(result))
    out = deliver("x")
    assert out["committed"] is False and out["nochange"] is False
    assert "fatal" in out["output"]
