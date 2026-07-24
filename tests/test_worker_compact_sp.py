"""M149.16 契约测试：worker 破窗修复（精简 tools + 自定义精简 SP 直传）。

背景：真实 tap 捕获显示 worker 首轮总上下文 28480 chars ≈ 8000+ tok，
远超 GLM-5.2-fp8 经 exo 的稳定窗口 ~14500 chars / ~3300 tok。
修复：默认移除 task_tracker(6585ch)/file_editor(4202ch)，SP 换自定义
精简版(~3300ch) 直传 Agent.system_prompt 绕过 Jinja 模板。

M149.20 追加：ThinkTool 默认移除——arg_key/name 碎片决定性触发器
（scripts/debug_glm_think_bisect.py 对照实验确认）。
"""
import os

from executor.openhands_worker import OpenHandsWorker


def _worker(**kw):
    from api.events import EventBus
    from api.session import SessionStore
    return OpenHandsWorker("s", "t", EventBus(SessionStore()),
                           working_dir=os.path.expanduser("~/projects/x"),
                           manage_session_status=False, **kw)


def test_default_tools_minimal(monkeypatch):
    """默认仅 terminal：task_tracker/file_editor 均移除（破窗修复）。"""
    monkeypatch.delenv("FLIPPED_WORKER_ENABLE_TASK_TRACKER", raising=False)
    monkeypatch.delenv("FLIPPED_WORKER_ENABLE_FILE_EDITOR", raising=False)
    w = _worker()
    names = [t["name"] for t in w.tools]
    assert names == ["terminal"]


def test_env_can_reenable_tools(monkeypatch):
    """env 逃生门：可显式加回 file_editor / task_tracker。"""
    monkeypatch.setenv("FLIPPED_WORKER_ENABLE_FILE_EDITOR", "1")
    monkeypatch.setenv("FLIPPED_WORKER_ENABLE_TASK_TRACKER", "1")
    w = _worker()
    names = [t["name"] for t in w.tools]
    assert names == ["terminal", "file_editor", "task_tracker"]


def test_explicit_tools_not_overridden(monkeypatch):
    """显式传入 tools 时 env 开关不生效（调用方全控）。"""
    monkeypatch.setenv("FLIPPED_WORKER_ENABLE_FILE_EDITOR", "1")
    custom = [{"name": "terminal", "params": {}},
              {"name": "file_editor", "params": {}}]
    w = _worker(tools=custom)
    assert w.tools is custom


def test_compact_system_prompt_default(monkeypatch):
    """默认启用精简 SP：远小于 SDK 模板 10886ch，且无被砍段落残留。"""
    monkeypatch.delenv("FLIPPED_WORKER_SP_DEFAULT", raising=False)
    sp = _worker()._worker_system_prompt()
    assert sp is not None
    assert len(sp) < 5000  # 窗口预算：SP+tools(6273)+user <14500
    # 关键保留段落
    for section in ("<ROLE>", "<EFFICIENCY>", "<PROBLEM_SOLVING_WORKFLOW>",
                    "<TROUBLESHOOTING>"):
        assert section in sp
    # 被砍段落不得残留
    for dropped in ("SELF_DOCUMENTATION", "PULL_REQUESTS", "EXTERNAL_SERVICES",
                    "VERSION_CONTROL", "AGENTS.md"):
        assert dropped not in sp
    # 无 file_editor 时的 bash 替代指引必须在（agent 不会卡在找编辑器）
    assert "heredoc" in sp or "terminal tool" in sp


def test_sdk_template_escape_hatch(monkeypatch):
    """FLIPPED_WORKER_SP_DEFAULT=1 回退 SDK 模板（返回 None）。"""
    monkeypatch.setenv("FLIPPED_WORKER_SP_DEFAULT", "1")
    assert _worker()._worker_system_prompt() is None


# --- M149.20 · ThinkTool 默认移除（arg_key 碎片触发器） ---


def test_think_tool_default_removed(monkeypatch):
    """M149.20：ThinkTool 是 arg_key/name 碎片决定性触发器
    （debug_glm_think_bisect.py：with-think 3/3 碎片，no-think 3/3 干净）。
    默认仅保留 FinishTool。"""
    monkeypatch.delenv("FLIPPED_WORKER_ENABLE_THINK_TOOL", raising=False)
    assert OpenHandsWorker._include_default_tools() == ["FinishTool"]


def test_think_tool_env_reenable(monkeypatch):
    """FLIPPED_WORKER_ENABLE_THINK_TOOL=1 可加回 ThinkTool（不推荐）。"""
    for raw in ("1", "true", "on", "yes"):
        monkeypatch.setenv("FLIPPED_WORKER_ENABLE_THINK_TOOL", raw)
        assert OpenHandsWorker._include_default_tools() == ["FinishTool", "ThinkTool"], raw
