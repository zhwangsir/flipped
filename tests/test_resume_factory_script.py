"""M5 产线化 — scripts/resume_factory.py CLI 测试（TDD）。

resume_factory.py 是 heartbeat.py 检测到 circuit_breaker_task 后建议人工触发的
恢复入口。本测试覆盖 6 个核心场景：

1. factory 不存在 → exit 2（明显错误，不静默成功）
2. factory 已 done → exit 0（幂等，不重复执行）
3. --dry-run → exit 0，只打印预检信息，不调 resume_factory_loop
4. 成功 resume（最终 status=done）→ exit 0
5. resume 后 status=failed/error → exit 1（区分"恢复了但任务失败"）
6. --db-path / --max-tasks / --max-rounds 正确转发

设计要点：
- 脚本 main(argv) 可导入测试，sys.path 操作在 main() 内部（导入无副作用）
- monkeypatch driving.factory_loop.resume_factory_loop / load_factory_state
- 用 FactoryState 真实模型构造测试夹具，避免字段缺失
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 把 scripts/ 加入 sys.path 以便 import resume_factory 模块
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

# 把 src/ 加入 sys.path 以便 import driving.factory_loop（构造测试夹具用）
_SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import resume_factory  # noqa: E402
from driving.factory_loop import (  # noqa: E402
    FactoryState,
    FactoryStatus,
    FactoryTask,
    TaskResult,
    TaskStatus,
)


def _make_state(
    *,
    factory_id: str = "fac-test",
    status: FactoryStatus = FactoryStatus.paused,
    product_goal: str = "test goal",
    cwd: str = "/tmp/test",
    failed: list[TaskResult] | None = None,
) -> FactoryState:
    """构造一个最小可用 FactoryState 测试夹具。"""
    return FactoryState(
        factory_id=factory_id,
        product_goal=product_goal,
        cwd=cwd,
        status=status,
        roadmap=[],
        completed=[],
        failed=failed or [],
    )


def _cb_result(task_id: str = "task-cb") -> TaskResult:
    """构造一条 stop_reason=circuit_breaker 的 TaskResult。"""
    return TaskResult(
        task=FactoryTask(id=task_id, description="cb task", verify_cmd=["true"]),
        verified=False,
        stop_reason="circuit_breaker",
        iteration=3,
        summary="verify failed 3x",
    )


# --------------------------------------------------------------------
# 1. factory 不存在 → exit 2
# --------------------------------------------------------------------
def test_factory_not_found_returns_2(capsys, monkeypatch):
    """load_factory_state 返回 None → 退出码 2，打印错误到 stderr。"""
    monkeypatch.setattr(
        "driving.factory_loop.load_factory_state",
        lambda fid, db: None,
    )
    rc = resume_factory.main(["fac-missing"])
    assert rc == 2
    captured = capsys.readouterr()
    # 错误消息打到 stderr，含 factory_id
    assert "fac-missing" in captured.err
    assert "不存在" in captured.err or "not found" in captured.err.lower()


# --------------------------------------------------------------------
# 2. factory 已 done → exit 0（幂等）
# --------------------------------------------------------------------
def test_factory_already_done_returns_0(capsys, monkeypatch):
    """status=done → 退出码 0，不调 resume_factory_loop。"""
    state = _make_state(status=FactoryStatus.done)
    monkeypatch.setattr(
        "driving.factory_loop.load_factory_state",
        lambda fid, db: state,
    )
    called = {"n": 0}

    def _no_call(*a, **kw):
        called["n"] += 1
        return state

    monkeypatch.setattr("driving.factory_loop.resume_factory_loop", _no_call)
    rc = resume_factory.main(["fac-done"])
    assert rc == 0
    assert called["n"] == 0  # 幂等：不重复执行
    out = capsys.readouterr().out
    assert "done" in out.lower() or "已完成" in out


# --------------------------------------------------------------------
# 3. --dry-run → exit 0，不调 resume
# --------------------------------------------------------------------
def test_dry_run_shows_state_no_resume(capsys, monkeypatch):
    """--dry-run 打印预检信息（含 circuit_breaker_task），但不执行 resume。"""
    # circuit_breaker 后实际状态是 paused（factory_loop L2230/L2287）
    state = _make_state(
        factory_id="fac-cb",
        status=FactoryStatus.paused,
        failed=[_cb_result("task-cb-1")],
    )
    monkeypatch.setattr(
        "driving.factory_loop.load_factory_state",
        lambda fid, db: state,
    )
    called = {"n": 0}

    def _no_call(*a, **kw):
        called["n"] += 1
        return state

    monkeypatch.setattr("driving.factory_loop.resume_factory_loop", _no_call)
    rc = resume_factory.main(["fac-cb", "--dry-run"])
    assert rc == 0
    assert called["n"] == 0
    out = capsys.readouterr().out
    # 预检信息应包含 factory_id + status + circuit_breaker 任务
    assert "fac-cb" in out
    assert "failed" in out.lower() or "失败" in out
    assert "task-cb-1" in out  # 列出可恢复任务


# --------------------------------------------------------------------
# 4. 成功 resume → exit 0
# --------------------------------------------------------------------
def test_successful_resume_returns_0(capsys, monkeypatch):
    """resume 后 status=done → exit 0。"""
    initial = _make_state(
        status=FactoryStatus.paused,
        failed=[_cb_result()],
    )
    final = _make_state(status=FactoryStatus.done)
    monkeypatch.setattr(
        "driving.factory_loop.load_factory_state",
        lambda fid, db: initial,
    )
    monkeypatch.setattr(
        "driving.factory_loop.resume_factory_loop",
        lambda fid, db_path=None, **kw: final,
    )
    rc = resume_factory.main(["fac-resume"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "done" in out.lower() or "完成" in out


# --------------------------------------------------------------------
# 5. resume 后 status=failed/error → exit 1
# --------------------------------------------------------------------
@pytest.mark.parametrize(
    "final_status",
    [FactoryStatus.error, FactoryStatus.paused],
)
def test_resume_non_done_status_returns_1(capsys, monkeypatch, final_status):
    """resume 后 status 非 done（failed/error）→ exit 1，区分"恢复但任务失败"。"""
    initial = _make_state(status=FactoryStatus.paused)
    final = _make_state(status=final_status)
    monkeypatch.setattr(
        "driving.factory_loop.load_factory_state",
        lambda fid, db: initial,
    )
    monkeypatch.setattr(
        "driving.factory_loop.resume_factory_loop",
        lambda fid, db_path=None, **kw: final,
    )
    rc = resume_factory.main(["fac-still-bad"])
    assert rc == 1
    out = capsys.readouterr().out
    assert final_status.value in out.lower()


# --------------------------------------------------------------------
# 6. --db-path / --max-tasks / --max-rounds 转发
# --------------------------------------------------------------------
def test_db_path_and_kwargs_forwarded(monkeypatch):
    """--db-path / --max-tasks / --max-rounds 正确转发到 resume_factory_loop。"""
    state = _make_state(status=FactoryStatus.paused)
    monkeypatch.setattr(
        "driving.factory_loop.load_factory_state",
        lambda fid, db: state,
    )
    captured = {}

    def _capture(fid, db_path=None, **kw):
        captured["factory_id"] = fid
        captured["db_path"] = db_path
        captured["kw"] = kw
        return _make_state(status=FactoryStatus.done)

    monkeypatch.setattr("driving.factory_loop.resume_factory_loop", _capture)
    rc = resume_factory.main(
        [
            "fac-kwargs",
            "--db-path",
            "/tmp/custom.db",
            "--max-tasks",
            "7",
            "--max-rounds",
            "2",
        ]
    )
    assert rc == 0
    assert captured["factory_id"] == "fac-kwargs"
    assert captured["db_path"] == "/tmp/custom.db"
    assert captured["kw"]["max_tasks"] == 7
    assert captured["kw"]["max_rounds"] == 2


# --------------------------------------------------------------------
# 7. 无参数 → argparse 报错（exit 2）
# --------------------------------------------------------------------
def test_no_args_returns_nonzero(capsys):
    """无 factory_id → argparse error，退出码非 0。"""
    with pytest.raises(SystemExit) as exc:
        resume_factory.main([])
    assert exc.value.code != 0
