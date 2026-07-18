"""M139-A · 崩溃恢复硬化单测（确定性，无需真 LLM）。

验证 resume 时正在 running 的 task 会被安全重跑，且完成副作用不重复应用：
- completed 无重复条目
- factory_events 中 task_done 幂等键仅 1 条
- context_summary 中同一 task 的完成摘要仅出现 1 次

注意：orchestrator_fn 抛普通 Exception 会被 factory_loop 捕获转为失败重试
（L1287-1296），并不等于"进程崩溃"。真实崩溃（kill -9 / 断电）用
BaseException 子类模拟——它会穿透 `except Exception`，由 finally 块把
"task running 中"的状态落盘后向外传播，与真实崩溃留下的现场一致。
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from driving.factory_loop import (  # noqa: E402
    FactoryState,
    FactoryStatus,
    FactoryTask,
    TaskResult,
    load_factory_state,
    run_factory_loop,
)


class SimulatedCrash(BaseException):
    """模拟进程级崩溃（穿透 factory_loop 的 except Exception 捕获）。"""


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td) / "factory.db"


@pytest.fixture
def tmp_cwd():
    with tempfile.TemporaryDirectory() as td:
        yield td


def _two_task_planner(state: FactoryState) -> list[FactoryTask]:
    return [
        FactoryTask(id="t1", description="task one", verify_cmd=["true"]),
        FactoryTask(id="t2", description="task two", verify_cmd=["true"]),
    ]


def _count_idempotency_key(db_path: str, key: str) -> int:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM factory_events WHERE idempotency_key = ?", (key,)
        )
        return cur.fetchone()[0]


def test_resume_reruns_running_task_without_duplicate_side_effects(tmp_db, tmp_cwd):
    """崩溃恢复：t1 已完成、t2 running 时进程死掉 → resume 后 t2 安全重跑。

    断言：
    - 最终 status == done，completed 恰好 2 条（t1/t2 各一，无重复）
    - factory_events 中 {fid}:t1:done / {fid}:t2:done 各仅 1 条
    - context_summary 中 t1 完成摘要仅出现 1 次（副作用未重复应用）
    """
    fid = "f-crash"

    # ---- 第一次运行：t1 完成，t2 running 时"进程崩溃" ----
    def crashing_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        if task.id == "t2":
            raise SimulatedCrash("process killed mid-task")
        return TaskResult(
            task=task, verified=True, stop_reason="completed", iteration=1, summary="ok",
        )

    with pytest.raises(SimulatedCrash):
        run_factory_loop(
            product_goal="crash test",
            cwd=tmp_cwd,
            factory_id=fid,
            db_path=str(tmp_db),
            planner=_two_task_planner,
            orchestrator_fn=crashing_orchestrator,
            max_tasks=10,
        )

    # 崩溃现场：t1 done、completed 1 条、t2 running、current_task_id=t2
    crashed = load_factory_state(fid, str(tmp_db))
    assert crashed is not None
    assert len(crashed.completed) == 1
    assert crashed.completed[0].task.id == "t1"
    t2 = next(t for t in crashed.roadmap if t.id == "t2")
    assert t2.status.value == "running"
    assert crashed.current_task_id == "t2"

    # ---- 第二次运行：同 factory_id resume，orchestrator 恢复正常 ----
    calls: list[str] = []

    def healthy_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        calls.append(task.id)
        return TaskResult(
            task=task, verified=True, stop_reason="completed", iteration=1, summary="ok",
        )

    state = run_factory_loop(
        product_goal="crash test",
        cwd=tmp_cwd,
        factory_id=fid,
        db_path=str(tmp_db),
        planner=_two_task_planner,
        orchestrator_fn=healthy_orchestrator,
        max_tasks=10,
    )

    # 1) 最终状态：done，completed 恰好 2 条且无重复 task
    assert state.status == FactoryStatus.done
    assert len(state.completed) == 2
    assert sorted(r.task.id for r in state.completed) == ["t1", "t2"]

    # 2) resume 只重跑了 t2（t1 未被执行）
    assert calls == ["t2"]

    # 3) 事件日志：task_done 幂等键各仅 1 条（task_start 重放也被去重）
    assert _count_idempotency_key(str(tmp_db), f"{fid}:t1:done") == 1
    assert _count_idempotency_key(str(tmp_db), f"{fid}:t2:done") == 1
    assert _count_idempotency_key(str(tmp_db), f"{fid}:t1:start") == 1
    assert _count_idempotency_key(str(tmp_db), f"{fid}:t2:start") == 1

    # 4) context_summary 中 t1 完成摘要仅 1 次（无副作用重复应用）
    assert state.context_summary.count("[t1]") == 1
    assert state.context_summary.count("[t2]") == 1


def test_resume_after_completed_factory_is_noop(tmp_db, tmp_cwd):
    """已 done 的 factory 再 resume 直接返回，不重跑任何 task。"""
    fid = "f-done"

    def ok_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        return TaskResult(
            task=task, verified=True, stop_reason="completed", iteration=1, summary="ok",
        )

    first = run_factory_loop(
        product_goal="noop test",
        cwd=tmp_cwd,
        factory_id=fid,
        db_path=str(tmp_db),
        planner=_two_task_planner,
        orchestrator_fn=ok_orchestrator,
        max_tasks=10,
    )
    assert first.status == FactoryStatus.done
    assert len(first.completed) == 2

    calls: list[str] = []

    def spy_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        calls.append(task.id)
        return TaskResult(
            task=task, verified=True, stop_reason="completed", iteration=1, summary="ok",
        )

    second = run_factory_loop(
        product_goal="noop test",
        cwd=tmp_cwd,
        factory_id=fid,
        db_path=str(tmp_db),
        planner=_two_task_planner,
        orchestrator_fn=spy_orchestrator,
        max_tasks=10,
    )
    assert second.status == FactoryStatus.done
    assert calls == []  # 未重跑任何 task
    assert len(second.completed) == 2
    assert _count_idempotency_key(str(tmp_db), f"{fid}:t1:done") == 1
    assert _count_idempotency_key(str(tmp_db), f"{fid}:t2:done") == 1
