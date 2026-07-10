"""factory_loop 确定性单测（不依赖真实 LLM / 沙盒）。"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from driving.factory_loop import (  # noqa: E402
    FactoryState,
    FactoryStatus,
    FactoryTask,
    TaskResult,
    TaskStatus,
    _next_task,
    default_planner,
    list_factories,
    load_factory_state,
    resume_factory_loop,
    run_factory_loop,
    save_factory_state,
)


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td) / "factory.db"


@pytest.fixture
def tmp_cwd():
    with tempfile.TemporaryDirectory() as td:
        yield td


def make_task(description: str, verify_cmd: list[str] | None = None) -> FactoryTask:
    return FactoryTask(
        description=description,
        verify_cmd=verify_cmd or ["true"],
        max_attempts=3,
    )


# ---------- 持久化 ----------


def test_save_and_load_roundtrip(tmp_db):
    state = FactoryState(
        factory_id="f1",
        product_goal="build a calculator",
        cwd="/tmp",
        status=FactoryStatus.running,
        roadmap=[make_task("add")],
        max_tasks=5,
    )
    save_factory_state(state, str(tmp_db))
    loaded = load_factory_state("f1", str(tmp_db))
    assert loaded is not None
    assert loaded.factory_id == "f1"
    assert loaded.product_goal == "build a calculator"
    assert len(loaded.roadmap) == 1
    assert loaded.roadmap[0].description == "add"
    assert loaded.status == FactoryStatus.running


def test_list_factories_order_by_updated(tmp_db):
    for fid in ("f-old", "f-new"):
        save_factory_state(
            FactoryState(
                factory_id=fid,
                product_goal="g",
                cwd="/tmp",
                status=FactoryStatus.pending,
                roadmap=[],
            ),
            str(tmp_db),
        )
    factories = list_factories(str(tmp_db))
    assert factories == ["f-new", "f-old"]


# ---------- 调度 ----------


def test_next_task_respects_dependencies():
    t1 = make_task("a")
    t2 = make_task("b")
    t2.depends_on = [t1.id]
    state = FactoryState(
        factory_id="f",
        product_goal="g",
        cwd="/tmp",
        status=FactoryStatus.running,
        roadmap=[t1, t2],
    )
    assert _next_task(state) == t1
    t1.status = TaskStatus.done
    assert _next_task(state) == t2


def test_next_task_skips_running():
    t1 = make_task("a")
    t1.status = TaskStatus.running
    state = FactoryState(
        factory_id="f",
        product_goal="g",
        cwd="/tmp",
        status=FactoryStatus.running,
        roadmap=[t1],
    )
    assert _next_task(state) is None


# ---------- Master Loop ----------


def test_run_factory_loop_planner_stub_and_executes_two_tasks(tmp_db, tmp_cwd):
    executed = []

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        return [
            make_task("task one", verify_cmd=["echo", "one"]),
            make_task("task two", verify_cmd=["echo", "two"]),
        ]

    def stub_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        executed.append(task.description)
        return TaskResult(
            task=task,
            verified=True,
            stop_reason="completed",
            iteration=1,
            summary="ok",
        )

    result = run_factory_loop(
        product_goal="build calc",
        cwd=tmp_cwd,
        db_path=str(tmp_db),
        planner=stub_planner,
        orchestrator_fn=stub_orchestrator,
        max_tasks=10,
    )

    assert result.status == FactoryStatus.done
    assert len(result.completed) == 2
    assert executed == ["task one", "task two"]

    # 持久化验证
    loaded = load_factory_state(result.factory_id, str(tmp_db))
    assert loaded.status == FactoryStatus.done
    assert len(loaded.completed) == 2


def test_run_factory_loop_retries_then_pauses(tmp_db, tmp_cwd):
    calls = []

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        return [make_task("always fail", verify_cmd=["false"])]

    def stub_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        calls.append(task.attempts)
        return TaskResult(
            task=task,
            verified=False,
            stop_reason="verify_failed",
            iteration=1,
            summary="nope",
        )

    result = run_factory_loop(
        product_goal="build calc",
        cwd=tmp_cwd,
        db_path=str(tmp_db),
        planner=stub_planner,
        orchestrator_fn=stub_orchestrator,
        max_tasks=10,
    )

    # max_attempts=3，三次失败后暂停
    assert calls == [1, 2, 3]
    assert result.status == FactoryStatus.paused
    assert len(result.failed) == 3
    assert result.iteration_count == 3


# ---------- M16: infra_failure 优雅暂停（不烧光重试次数） ----------


def test_infra_failure_pauses_without_consuming_retries(tmp_db, tmp_cwd):
    """集群不可用(ConnectTimeout)时立即暂停，不消耗 max_attempts。

    E2E 暴露：exo 集群 ConnectTimeout 时 worker_error=True → stop_reason="worker_error"，
    factory_loop 把它当普通失败重试 3 次 → 烧光重试次数 → paused。
    修复：检测 infra_failure 模式（ConnectTimeout/ReadTimeout/worker_error 含 timeout），
    立即暂停并标记 infra_failure，不消耗重试次数。
    """
    call_count = [0]

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        return [make_task("any task", verify_cmd=["true"])]

    def stub_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        call_count[0] += 1
        return TaskResult(
            task=task,
            verified=False,
            stop_reason="worker_error",
            iteration=0,
            summary="ConnectTimeout: timed out",
        )

    result = run_factory_loop(
        product_goal="build something",
        cwd=tmp_cwd,
        db_path=str(tmp_db),
        planner=stub_planner,
        orchestrator_fn=stub_orchestrator,
        max_tasks=10,
    )

    # 只调 1 次（而非 3 次），因为 infra_failure → 立即暂停
    assert call_count[0] == 1
    assert result.status == FactoryStatus.paused
    # failed 只有 1 条（不消耗重试次数）
    assert len(result.failed) == 1
    # stop_reason 标记为 infra_failure
    assert "infra" in result.failed[0].stop_reason or "infra" in result.failed[0].summary.lower()


def test_non_infra_failure_still_retries(tmp_db, tmp_cwd):
    """普通失败（verify_failed）仍正常重试 3 次。

    确认 M16 修复不影响普通失败的正常重试逻辑。
    """
    calls = []

    def stub_planner(state: FactoryState) -> list[FactoryTask]:
        return [make_task("verify fail", verify_cmd=["false"])]

    def stub_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        calls.append(task.attempts)
        return TaskResult(
            task=task,
            verified=False,
            stop_reason="verify_failed",
            iteration=1,
            summary="assertion failed",
        )

    result = run_factory_loop(
        product_goal="build something",
        cwd=tmp_cwd,
        db_path=str(tmp_db),
        planner=stub_planner,
        orchestrator_fn=stub_orchestrator,
        max_tasks=10,
    )

    # 普通失败仍重试 3 次
    assert calls == [1, 2, 3]
    assert result.status == FactoryStatus.paused
    assert len(result.failed) == 3


def test_resume_factory_loop_continues_after_crash(tmp_db, tmp_cwd):
    """模拟进程崩溃：直接写入一个 current_task 为 running 的状态，再 resume。"""
    calls = []

    first = make_task("first", verify_cmd=["echo", "first"])
    second = make_task("second", verify_cmd=["echo", "second"])
    first.status = TaskStatus.done
    second.status = TaskStatus.running

    crashed_state = FactoryState(
        factory_id="crash-factory",
        product_goal="build calc",
        cwd=tmp_cwd,
        status=FactoryStatus.running,
        roadmap=[first, second],
        current_task_id=second.id,
        iteration_count=1,
        max_tasks=10,
    )
    crashed_state.completed.append(
        TaskResult(
            task=first,
            verified=True,
            stop_reason="completed",
            iteration=1,
            summary="ok",
        )
    )
    save_factory_state(crashed_state, str(tmp_db))

    def success_orchestrator(task: FactoryTask, state: FactoryState) -> TaskResult:
        calls.append(task.description)
        return TaskResult(
            task=task,
            verified=True,
            stop_reason="completed",
            iteration=1,
            summary="ok",
        )

    resumed = resume_factory_loop(
        factory_id="crash-factory",
        db_path=str(tmp_db),
        orchestrator_fn=success_orchestrator,
        max_tasks=10,
    )

    assert resumed.status == FactoryStatus.done
    assert len(resumed.completed) == 2
    assert "second" in calls


# ---------- default_planner fail-open ----------


def test_default_planner_returns_fallback_on_llm_error():
    # mock _make_llm 快速抛异常，验证 fail-open 兜底
    state = FactoryState(
        factory_id="f",
        product_goal="build a calculator",
        cwd="/tmp",
        status=FactoryStatus.pending,
        roadmap=[],
    )
    with patch("driving.factory_loop._make_llm", side_effect=RuntimeError("no model")):
        tasks = default_planner(state)
    assert len(tasks) == 1
    assert tasks[0].description == "build a calculator"
    assert tasks[0].verify_cmd == ["true"]
    assert "planner fail-open" in tasks[0].feedback


# ---------- schema 迁移兼容 ----------


def test_sqlite_schema_has_expected_columns(tmp_db):
    save_factory_state(
        FactoryState(
            factory_id="schema-check",
            product_goal="g",
            cwd="/tmp",
            status=FactoryStatus.pending,
            roadmap=[],
        ),
        str(tmp_db),
    )
    with sqlite3.connect(str(tmp_db)) as conn:
        cur = conn.execute("PRAGMA table_info(factory_states)")
        cols = {row[1] for row in cur.fetchall()}
    expected = {
        "factory_id",
        "product_goal",
        "cwd",
        "status",
        "roadmap_json",
        "completed_json",
        "failed_json",
        "current_task_id",
        "context_summary",
        "iteration_count",
        "max_tasks",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(cols)
