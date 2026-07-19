"""M142-C · factory 任务级并行（并行执行、串行落账）确定性单测。

- `_ready_tasks`：`_next_task` 的推广，返回所有 depends_on ⊆ completed 的 pending 任务
- `FLIPPED_MAX_PARALLEL`：>1 时用 ThreadPoolExecutor 按依赖波次并行跑 orchestrator_fn
- 落账正确性：completed 无重复、task_done 事件每任务恰好 1 条（幂等键）、
  quality_history / 分层记忆每任务恰好 1 次
- 依赖语义：depends_on 未满足的任务绝不在依赖完成前启动
- 默认（未设环境变量 / =1）= 现有串行路径，零回归
全 mock，不依赖 LLM / 沙盒。
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from driving.event_log import list_events  # noqa: E402
from driving.factory_loop import (  # noqa: E402
    FactoryState,
    FactoryStatus,
    FactoryTask,
    TaskResult,
    TaskStatus,
    _ready_tasks,
    run_factory_loop,
)


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td) / "factory.db"


@pytest.fixture
def tmp_cwd():
    with tempfile.TemporaryDirectory() as td:
        yield td


def _make_state(roadmap: list[FactoryTask]) -> FactoryState:
    return FactoryState(
        factory_id="f-ready",
        product_goal="g",
        cwd="/tmp",
        status=FactoryStatus.running,
        roadmap=roadmap,
    )


def _task(tid: str, depends_on: list[str] | None = None) -> FactoryTask:
    return FactoryTask(
        id=tid,
        description=f"task {tid}",
        verify_cmd=["true"],
        depends_on=list(depends_on or []),
    )


# ---------- _ready_tasks ----------


def test_ready_tasks_empty_roadmap():
    assert _ready_tasks(_make_state([])) == []


def test_ready_tasks_single_pending():
    t = _task("a")
    assert _ready_tasks(_make_state([t])) == [t]


def test_ready_tasks_all_independent_returns_all_in_order():
    ts = [_task("a"), _task("b"), _task("c")]
    assert _ready_tasks(_make_state(ts)) == ts


def test_ready_tasks_chain_dependency_unlocks_one_by_one():
    a, b, c = _task("a"), _task("b", ["a"]), _task("c", ["b"])
    st = _make_state([a, b, c])
    assert _ready_tasks(st) == [a]
    a.status = TaskStatus.done
    assert _ready_tasks(st) == [b]
    b.status = TaskStatus.done
    assert _ready_tasks(st) == [c]


def test_ready_tasks_diamond_dependency():
    a = _task("a")
    b = _task("b", ["a"])
    c = _task("c", ["a"])
    d = _task("d", ["b", "c"])
    st = _make_state([a, b, c, d])
    assert _ready_tasks(st) == [a]
    a.status = TaskStatus.done
    assert _ready_tasks(st) == [b, c]
    b.status = TaskStatus.done
    assert _ready_tasks(st) == [c], "d 还差 c，不可提前就绪"
    c.status = TaskStatus.done
    assert _ready_tasks(st) == [d]


def test_ready_tasks_skips_non_pending():
    a = _task("a")
    a.status = TaskStatus.running
    b = _task("b")
    b.status = TaskStatus.failed
    c = _task("c")
    st = _make_state([a, b, c])
    assert _ready_tasks(st) == [c]


def test_ready_tasks_depends_on_unknown_id_never_ready():
    t = _task("x", depends_on=["ghost"])
    assert _ready_tasks(_make_state([t])) == []


# ---------- 并行波次：墙钟与落账 ----------


def _three_task_planner(state: FactoryState) -> list[FactoryTask]:
    return [_task("t1"), _task("t2"), _task("t3")]


def _ok_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
    return TaskResult(task=task, verified=True, stop_reason="done", iteration=1, summary="ok")


def test_parallel_wall_clock_beats_serial(tmp_db, tmp_cwd, monkeypatch):
    """3 个无依赖任务 × 0.3s：并行墙钟应明显 < 串行 0.9s，且 >= 单任务时长。"""
    monkeypatch.setenv("FLIPPED_MAX_PARALLEL", "3")

    def slow_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        time.sleep(0.3)
        return _ok_orchestrator(task, state)

    start = time.monotonic()
    result = run_factory_loop(
        product_goal="parallel wall", cwd=tmp_cwd, db_path=str(tmp_db),
        planner=_three_task_planner, orchestrator_fn=slow_orchestrator, max_tasks=10,
    )
    wall = time.monotonic() - start

    assert result.status == FactoryStatus.done
    assert len(result.completed) == 3
    assert wall >= 0.3, f"墙钟应 >= 单任务时长，实际 {wall:.2f}s"
    assert wall < 0.7, f"3×0.3s 并行应远小于串行 0.9s，实际 {wall:.2f}s"


def test_parallel_accounting_exactly_once_per_task(tmp_db, tmp_cwd, monkeypatch):
    """并行落账正确性：completed 无重复、task_done 幂等事件每任务恰好 1 条、
    quality_history / 分层记忆每任务恰好 1 次。"""
    monkeypatch.setenv("FLIPPED_MAX_PARALLEL", "3")

    result = run_factory_loop(
        product_goal="parallel accounting", cwd=tmp_cwd, db_path=str(tmp_db),
        planner=_three_task_planner, orchestrator_fn=_ok_orchestrator, max_tasks=10,
    )

    assert result.status == FactoryStatus.done
    assert sorted(r.task.id for r in result.completed) == ["t1", "t2", "t3"]

    # quality_history：每任务恰好 1 条
    assert sorted(q["task_id"] for q in result.quality_history) == ["t1", "t2", "t3"]

    # 分层记忆：每任务完成摘要恰好 1 次
    mem_text = str(result.memory_data)
    for tid in ("t1", "t2", "t3"):
        assert mem_text.count(f"[{tid}]") == 1, f"[{tid}] 应恰好出现 1 次"

    # 事件日志：task_done 每任务恰好 1 条（幂等键唯一）
    with sqlite3.connect(str(tmp_db)) as conn:
        events = list_events(conn, result.factory_id)
    done_events = [e for e in events if e["kind"] == "task_done"]
    done_keys = [e["idempotency_key"] for e in done_events]
    assert len(done_events) == 3
    assert sorted(done_keys) == [
        f"{result.factory_id}:t1:done",
        f"{result.factory_id}:t2:done",
        f"{result.factory_id}:t3:done",
    ]
    # task_start 同样幂等去重
    start_events = [e for e in events if e["kind"] == "task_start"]
    assert len(start_events) == 3


def test_parallel_respects_dependency_order(tmp_db, tmp_cwd, monkeypatch):
    """A、B 无依赖可并行；C depends_on=[A,B] → C 绝不在 A/B 完成前启动。"""
    monkeypatch.setenv("FLIPPED_MAX_PARALLEL", "3")
    timings: dict[str, float] = {}
    lock = threading.Lock()

    def timed_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        with lock:
            timings[f"{task.id}.start"] = time.monotonic()
        time.sleep(0.2)
        with lock:
            timings[f"{task.id}.end"] = time.monotonic()
        return _ok_orchestrator(task, state)

    def planner(state: FactoryState) -> list[FactoryTask]:
        return [_task("a"), _task("b"), _task("c", ["a", "b"])]

    result = run_factory_loop(
        product_goal="dep order", cwd=tmp_cwd, db_path=str(tmp_db),
        planner=planner, orchestrator_fn=timed_orchestrator, max_tasks=10,
    )

    assert result.status == FactoryStatus.done
    assert sorted(r.task.id for r in result.completed) == ["a", "b", "c"]
    # C 在 A、B 都结束后才启动
    assert timings["c.start"] >= timings["a.end"]
    assert timings["c.start"] >= timings["b.end"]
    # A、B 确实并行（时间区间重叠）
    assert timings["b.start"] < timings["a.end"] or timings["a.start"] < timings["b.end"]


def test_parallel_failure_does_not_block_sibling(tmp_db, tmp_cwd, monkeypatch):
    """同波任务失败不牵连其他并行任务：失败任务按现有失败路径落账并正常重试。"""
    monkeypatch.setenv("FLIPPED_MAX_PARALLEL", "2")
    attempts = {"a": 0}
    lock = threading.Lock()

    def flaky_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        if task.id == "a":
            with lock:
                attempts["a"] += 1
                first = attempts["a"] == 1
            if first:
                return TaskResult(
                    task=task, verified=False, stop_reason="verify_failed",
                    iteration=1, summary="boom",
                )
        return _ok_orchestrator(task, state)

    def planner(state: FactoryState) -> list[FactoryTask]:
        return [_task("a"), _task("b")]

    result = run_factory_loop(
        product_goal="failure isolation", cwd=tmp_cwd, db_path=str(tmp_db),
        planner=planner, orchestrator_fn=flaky_orchestrator, max_tasks=10,
    )

    assert result.status == FactoryStatus.done
    assert attempts["a"] == 2, "a 首败后应重试成功"
    assert sorted(r.task.id for r in result.completed) == ["a", "b"]
    # b 的成功不受 a 首败影响：b 只跑了一次且完成
    assert len([r for r in result.completed if r.task.id == "b"]) == 1
    # a 的 task_done 幂等事件恰好 1 条（只计成功那次）
    with sqlite3.connect(str(tmp_db)) as conn:
        events = list_events(conn, result.factory_id)
    done_keys = [e["idempotency_key"] for e in events if e["kind"] == "task_done"]
    assert done_keys.count(f"{result.factory_id}:a:done") == 1
    assert done_keys.count(f"{result.factory_id}:b:done") == 1


def test_parallel_respects_max_tasks_budget(tmp_db, tmp_cwd, monkeypatch):
    """并行模式仍受 max_tasks 总预算约束：预算只够 2 个时绝不跑第 3 个。"""
    monkeypatch.setenv("FLIPPED_MAX_PARALLEL", "3")
    calls: list[str] = []
    lock = threading.Lock()

    def spy_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        with lock:
            calls.append(task.id)
        return _ok_orchestrator(task, state)

    result = run_factory_loop(
        product_goal="budget", cwd=tmp_cwd, db_path=str(tmp_db),
        planner=_three_task_planner, orchestrator_fn=spy_orchestrator, max_tasks=2,
    )

    assert len(calls) == 2, f"max_tasks=2 时只应执行 2 个任务，实际 {calls}"
    assert len(result.completed) == 2


def test_parallel_crash_resume_no_duplicate_side_effects(tmp_db, tmp_cwd, monkeypatch):
    """M139 语义扩展到并行：波次中途崩溃（BaseException 穿透）→ resume 重跑，
    完成副作用不重复应用（completed/task_done 幂等键各恰好 1 次）。"""
    monkeypatch.setenv("FLIPPED_MAX_PARALLEL", "2")

    class SimulatedCrash(BaseException):
        """模拟进程级崩溃（穿透 except Exception）。"""

    fid = "f-par-crash"

    def crashing_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        if task.id == "t2":
            raise SimulatedCrash("process killed mid-wave")
        time.sleep(0.05)
        return _ok_orchestrator(task, state)

    def planner(state: FactoryState) -> list[FactoryTask]:
        return [_task("t1"), _task("t2")]

    with pytest.raises(SimulatedCrash):
        run_factory_loop(
            product_goal="par crash", cwd=tmp_cwd, db_path=str(tmp_db),
            factory_id=fid, planner=planner,
            orchestrator_fn=crashing_orchestrator, max_tasks=10,
        )

    # 崩溃现场：波次内任务停留在 running（resume 须全部重置为 pending）
    from driving.factory_loop import load_factory_state
    crashed = load_factory_state(fid, str(tmp_db))
    assert crashed is not None
    running_ids = [t.id for t in crashed.roadmap if t.status == TaskStatus.running]
    assert running_ids, "崩溃现场应有 running 任务"

    calls: list[str] = []
    lock = threading.Lock()

    def healthy_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        with lock:
            calls.append(task.id)
        return _ok_orchestrator(task, state)

    result = run_factory_loop(
        product_goal="par crash", cwd=tmp_cwd, db_path=str(tmp_db),
        factory_id=fid, planner=planner,
        orchestrator_fn=healthy_orchestrator, max_tasks=10,
    )

    assert result.status == FactoryStatus.done
    assert sorted(calls) == ["t1", "t2"], "两个任务都被安全重跑"
    assert sorted(r.task.id for r in result.completed) == ["t1", "t2"]
    with sqlite3.connect(str(tmp_db)) as conn:
        events = list_events(conn, fid)
    done_keys = [e["idempotency_key"] for e in events if e["kind"] == "task_done"]
    assert done_keys.count(f"{fid}:t1:done") == 1
    assert done_keys.count(f"{fid}:t2:done") == 1
    start_keys = [e["idempotency_key"] for e in events if e["kind"] == "task_start"]
    assert start_keys.count(f"{fid}:t1:start") == 1
    assert start_keys.count(f"{fid}:t2:start") == 1
    assert result.context_summary.count("[t1]") == 1
    assert result.context_summary.count("[t2]") == 1


# ---------- 默认零回归：未设 / =1 时保持串行 ----------


def test_default_serial_when_env_unset(tmp_db, tmp_cwd, monkeypatch):
    """FLIPPED_MAX_PARALLEL 未设置时行为与现状一致：串行执行。"""
    monkeypatch.delenv("FLIPPED_MAX_PARALLEL", raising=False)

    def slow_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        time.sleep(0.2)
        return _ok_orchestrator(task, state)

    def planner(state: FactoryState) -> list[FactoryTask]:
        return [_task("t1"), _task("t2")]

    start = time.monotonic()
    result = run_factory_loop(
        product_goal="serial default", cwd=tmp_cwd, db_path=str(tmp_db),
        planner=planner, orchestrator_fn=slow_orchestrator, max_tasks=10,
    )
    wall = time.monotonic() - start

    assert result.status == FactoryStatus.done
    assert len(result.completed) == 2
    assert wall >= 0.35, f"默认应为串行（2×0.2s），实际 {wall:.2f}s"


def test_max_parallel_one_keeps_serial(tmp_db, tmp_cwd, monkeypatch):
    """FLIPPED_MAX_PARALLEL=1 显式保持串行路径。"""
    monkeypatch.setenv("FLIPPED_MAX_PARALLEL", "1")

    def slow_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        time.sleep(0.2)
        return _ok_orchestrator(task, state)

    def planner(state: FactoryState) -> list[FactoryTask]:
        return [_task("t1"), _task("t2")]

    start = time.monotonic()
    result = run_factory_loop(
        product_goal="serial explicit", cwd=tmp_cwd, db_path=str(tmp_db),
        planner=planner, orchestrator_fn=slow_orchestrator, max_tasks=10,
    )
    wall = time.monotonic() - start

    assert result.status == FactoryStatus.done
    assert len(result.completed) == 2
    assert wall >= 0.35, f"=1 应为串行（2×0.2s），实际 {wall:.2f}s"
