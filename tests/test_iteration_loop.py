"""自主迭代闭环集成测试（M33）。

端到端验证 M31（task_proposer）+ M32（design_score 门槛）+ factory_loop 重试机制
的完整交互：

1. design_score 低 → 验证失败 → 重试 → 修复后通过 → proposer 生成下一个任务
2. proposer 连续生成多个任务 → max_rounds 限制空转
3. 所有任务失败 → paused 状态
4. 失败 feedback 包含 design_score 信息
"""
from __future__ import annotations

import os
import tempfile

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driving.factory_loop import (
    run_factory_loop,
    FactoryState,
    FactoryTask,
    FactoryStatus,
    TaskStatus,
    TaskResult,
)


def test_design_score_failure_triggers_retry_then_proposer():
    """design_score 低 → 失败 → 重试 → 修复后通过 → proposer 生成下一个任务。

    M33 核心场景：完整验证"无限迭代"闭环。
    初始任务第一次因 design_score 低而失败，第二次修复后通过，
    然后 task_proposer 基于当前状态生成下一个任务。
    """
    call_count = [0]

    def fake_orchestrator(task, state):
        call_count[0] += 1
        if call_count[0] == 1:
            # 初始任务第一次：design_score 低
            return TaskResult(
                task=task, verified=False,
                stop_reason="design_score=45/70 未达标",
                iteration=1,
                summary="design_score=45/70 未达标。问题：颜色对比度低",
            )
        return TaskResult(
            task=task, verified=True,
            stop_reason="verified", iteration=1,
        )

    proposer_calls = [0]

    def fake_proposer(state):
        proposer_calls[0] += 1
        if proposer_calls[0] == 1:
            return FactoryTask(
                id="proposed-1",
                description="添加响应式导航",
                verify_cmd=["true"],
            )
        return None

    with tempfile.TemporaryDirectory() as d:
        state = run_factory_loop(
            product_goal="做一个 landing page",
            cwd=d,
            db_path=os.path.join(d, "test.db"),
            checkpoint_db_path=os.path.join(d, "ckpt.db"),
            max_tasks=10,
            max_rounds=3,
            planner=lambda s: [FactoryTask(id="t1", description="写 landing page", verify_cmd=["true"])],
            orchestrator_fn=fake_orchestrator,
            task_proposer=fake_proposer,
        )

    # 初始任务 t1：失败1次 + 成功1次 = 2 次
    # proposer 生成 proposed-1：成功1次 = 1 次
    assert call_count[0] == 3
    assert len(state.completed) == 2  # t1 最终完成 + proposed-1 完成
    assert len(state.failed) == 1  # t1 第一次失败
    assert state.status == FactoryStatus.done


def test_proposer_generates_multiple_tasks_until_max_rounds():
    """proposer 连续生成多个任务 → max_rounds 限制空转。"""
    proposer_calls = [0]

    def fake_proposer(state):
        proposer_calls[0] += 1
        return FactoryTask(
            id=f"proposed-{proposer_calls[0]}",
            description=f"自主任务 {proposer_calls[0]}",
            verify_cmd=["true"],
        )

    def fake_orchestrator(task, state):
        return TaskResult(
            task=task, verified=True,
            stop_reason="verified", iteration=1,
        )

    with tempfile.TemporaryDirectory() as d:
        state = run_factory_loop(
            product_goal="test",
            cwd=d,
            db_path=os.path.join(d, "test.db"),
            checkpoint_db_path=os.path.join(d, "ckpt.db"),
            max_tasks=20,
            max_rounds=4,
            planner=lambda s: [FactoryTask(id="t0", description="init", verify_cmd=["true"])],
            orchestrator_fn=fake_orchestrator,
            task_proposer=fake_proposer,
        )

    # 初始 1 + max_rounds=4 = 5 个任务
    assert len(state.completed) == 5
    assert proposer_calls[0] == 4
    assert state.status == FactoryStatus.done


def test_all_tasks_fail_leads_to_paused():
    """所有任务都失败 → paused 状态（不无限重试）。"""
    call_count = [0]

    def fake_orchestrator(task, state):
        call_count[0] += 1
        return TaskResult(
            task=task, verified=False,
            stop_reason="design_score=30/70",
            iteration=1,
            summary="design_score=30/70 未达标",
        )

    with tempfile.TemporaryDirectory() as d:
        state = run_factory_loop(
            product_goal="test",
            cwd=d,
            db_path=os.path.join(d, "test.db"),
            checkpoint_db_path=os.path.join(d, "ckpt.db"),
            max_tasks=10,
            max_rounds=3,
            planner=lambda s: [FactoryTask(
                id="t1", description="写页面",
                verify_cmd=["true"], max_attempts=2,
            )],
            orchestrator_fn=fake_orchestrator,
            task_proposer=lambda s: None,  # proposer 不会被调用（任务一直失败）
        )

    # 任务重试 max_attempts=2 次后 paused
    assert state.status == FactoryStatus.paused
    assert len(state.failed) >= 1
    assert call_count[0] == 2  # max_attempts=2


def test_feedback_contains_design_score_info():
    """失败 feedback 包含 design_score 信息，让 worker 知道该修什么。"""
    feedbacks = []

    def fake_orchestrator(task, state):
        feedbacks.append(task.feedback)
        if "t1" in task.id and not task.feedback:
            return TaskResult(
                task=task, verified=False,
                stop_reason="design_score=45/70",
                iteration=1,
                summary="design_score=45/70 未达标。问题：颜色对比度低；缺少响应式断点",
            )
        return TaskResult(
            task=task, verified=True,
            stop_reason="verified", iteration=1,
        )

    with tempfile.TemporaryDirectory() as d:
        state = run_factory_loop(
            product_goal="test",
            cwd=d,
            db_path=os.path.join(d, "test.db"),
            checkpoint_db_path=os.path.join(d, "ckpt.db"),
            max_tasks=10,
            max_rounds=3,
            planner=lambda s: [FactoryTask(id="t1", description="写页面", verify_cmd=["true"])],
            orchestrator_fn=fake_orchestrator,
            task_proposer=lambda s: None,
        )

    # 第一次执行时 feedback 为空
    # 第二次执行时 feedback 应包含上一次的失败信息
    assert len(feedbacks) == 2
    assert feedbacks[0] == ""
    assert "design_score" in feedbacks[1] or "45" in feedbacks[1] or "未达标" in feedbacks[1]


def test_proposer_receives_context_summary():
    """proposer 收到的 state 包含已完成任务的 context_summary。"""
    proposer_states = []

    def fake_proposer(state):
        proposer_states.append(state.context_summary)
        return None

    def fake_orchestrator(task, state):
        return TaskResult(
            task=task, verified=True,
            stop_reason="verified", iteration=1,
        )

    with tempfile.TemporaryDirectory() as d:
        state = run_factory_loop(
            product_goal="test",
            cwd=d,
            db_path=os.path.join(d, "test.db"),
            checkpoint_db_path=os.path.join(d, "ckpt.db"),
            max_tasks=10,
            max_rounds=3,
            planner=lambda s: [FactoryTask(id="t1", description="写 landing page", verify_cmd=["true"])],
            orchestrator_fn=fake_orchestrator,
            task_proposer=fake_proposer,
        )

    # proposer 应该收到包含已完成任务信息的 context_summary
    assert len(proposer_states) == 1
    assert "t1" in proposer_states[0] or "landing" in proposer_states[0]


def test_iteration_count_tracks_total_executions():
    """iteration_count 追踪总执行次数（包括失败重试）。"""
    call_count = [0]

    def fake_orchestrator(task, state):
        call_count[0] += 1
        if call_count[0] == 1:
            return TaskResult(
                task=task, verified=False,
                stop_reason="design_score=40/70",
                iteration=1, summary="低分",
            )
        return TaskResult(
            task=task, verified=True,
            stop_reason="verified", iteration=1,
        )

    def fake_proposer(state):
        return FactoryTask(id="p1", description="next", verify_cmd=["true"])

    with tempfile.TemporaryDirectory() as d:
        state = run_factory_loop(
            product_goal="test",
            cwd=d,
            db_path=os.path.join(d, "test.db"),
            checkpoint_db_path=os.path.join(d, "ckpt.db"),
            max_tasks=10,
            max_rounds=1,
            planner=lambda s: [FactoryTask(id="t1", description="init", verify_cmd=["true"])],
            orchestrator_fn=fake_orchestrator,
            task_proposer=fake_proposer,
        )

    # t1 失败 + t1 重试成功 + p1 成功 = 3 次
    assert state.iteration_count == 3
    assert call_count[0] == 3
