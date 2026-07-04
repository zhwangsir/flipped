"""F8 大任务实测 — worker 异常分类:卡死回灌重拆 vs 基础设施故障快速失败。"""
from driving import orchestrator as orch


class _FakeWorker:
    """monkeypatch 替身:run 抛指定异常,events 可配。"""

    exc: Exception = RuntimeError("boom")
    fake_events: list = []

    def __init__(self, **kwargs):
        self.events = list(self.fake_events)

    def run(self, task):
        raise self.exc


# 分类逻辑靠 type(ev).__name__ == "ActionEvent" 计数 → 动态造同名类
ActionEvent = type("ActionEvent", (object,), {"tool_name": "terminal", "action": None})


def _run_node(monkeypatch, exc, events):
    monkeypatch.setattr(orch, "OpenHandsWorker", _FakeWorker)
    monkeypatch.setattr(orch, "resolve_worker_model_config", lambda *a, **k: ("http://x", "m"))
    _FakeWorker.exc = exc
    _FakeWorker.fake_events = events
    node = orch.make_openhands_worker()
    return node({"cwd": "/projects/x", "current_subtask": "做点事",
                 "feedback": "", "signatures": [], "history": []})


def test_max_iterations_is_task_level_replan(monkeypatch):
    upd = _run_node(monkeypatch,
                    RuntimeError("MaxIterationsReached: Agent reached maximum iterations limit (50)."),
                    [ActionEvent() for _ in range(50)])
    assert upd["worker_error"] is False           # 不判死任务
    assert "更小" in upd["feedback"]               # 回灌重拆指引
    assert upd["signatures"][-1].startswith("stuck:")  # 连续卡死仍会被循环检测抓
    assert upd["last_obs"]["ok"] is False


def test_audit_blocked_is_task_level(monkeypatch):
    upd = _run_node(monkeypatch, RuntimeError("terminal command blocked: rm -rf / (pattern)"), [])
    assert upd["worker_error"] is False
    assert "卡点" in upd["feedback"]


def test_infra_failure_fast_fails(monkeypatch):
    # 一个工具都没调成 + 非卡死类异常 = 基础设施故障 → 快速失败
    upd = _run_node(monkeypatch, ConnectionError("agent-server unreachable"), [])
    assert upd["worker_error"] is True
    assert "feedback" not in upd


def test_partial_progress_then_crash_is_task_level(monkeypatch):
    # 调过工具后崩(如超时):有真实进展,值得重拆而非判死
    upd = _run_node(monkeypatch, TimeoutError("conversation timed out"), [ActionEvent()])
    assert upd["worker_error"] is False
