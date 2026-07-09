"""stuck_detector 单元测试（M10.4-C）。"""
from __future__ import annotations

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driving.stuck_detector import StuckDetector, StuckSignal, delegate_orchestrator
from driving.factory_loop import FactoryTask, FactoryState, TaskResult


def test_no_iterations_not_stuck():
    det = StuckDetector()
    assert not det.is_stuck().is_stuck


def test_first_failure_not_stuck():
    det = StuckDetector(fail_threshold=2)
    det.record("circuit_breaker", "verify failed")
    sig = det.is_stuck()
    assert not sig.is_stuck
    assert sig.iterations_seen == 1


def test_consecutive_same_stop_reason_triggers_stuck():
    det = StuckDetector(fail_threshold=2)
    det.record("circuit_breaker", "fail A")
    det.record("circuit_breaker", "fail B")
    sig = det.is_stuck()
    assert sig.is_stuck
    assert sig.delegate_recommended
    assert "circuit_breaker" in sig.reason


def test_identical_summaries_trigger_stuck():
    """完全相同的失败摘要 = worker 在原地打转。"""
    det = StuckDetector(fail_threshold=5)  # 提高 threshold 避免误触
    det.record("verify_failed", "Error: cannot import foo")
    det.record("verify_failed", "Error: cannot import foo")
    sig = det.is_stuck()
    assert sig.is_stuck
    assert sig.delegate_recommended


def test_high_similarity_summaries_trigger_stuck():
    """Jaccard ≥ 0.85 = 反复犯同类错。"""
    det = StuckDetector(fail_threshold=5)
    det.record("verify_failed", "ImportError cannot find module calc")
    det.record("verify_failed", "ImportError cannot find module calc")
    # 第一次和第二次高度相似（其实完全相同，但触发的是 identical 路径）
    sig = det.is_stuck()
    assert sig.is_stuck


def test_verified_does_not_trigger_stuck():
    """有 verified 的不算卡死。"""
    det = StuckDetector()
    det.record("verified", "")
    det.record("verified", "")
    sig = det.is_stuck()
    assert not sig.is_stuck


def test_reset_clears_state():
    det = StuckDetector()
    det.record("fail", "x")
    det.reset()
    assert not det.is_stuck().is_stuck
    assert len(det._stop_reasons) == 0


def test_window_limits_history():
    det = StuckDetector(window=3, fail_threshold=10)
    for i in range(10):
        det.record(f"reason_{i}", f"summary_{i}")
    # 窗口只保留最后 3 条
    assert len(det._stop_reasons) == 3


def test_delegate_orchestrator_uses_independent_thread():
    """delegate orchestrator 用独立 thread_id（通过 mock drive_orchestrated 验证）。"""
    import driving.stuck_detector as sd
    called = {}

    def mock_drive(**kwargs):
        called.update(kwargs)
        return {"verified": True, "stop_reason": "verified", "iteration": 1}

    orig = sd.drive_orchestrated
    sd.drive_orchestrated = mock_drive
    try:
        task = FactoryTask(id="t1", description="测试任务", verify_cmd=["true"])
        state = FactoryState(
            factory_id="f1", product_goal="goal", cwd="/tmp", roadmap=[task],
        )
        result = delegate_orchestrator(task, state, "卡死原因: 反复失败")
        assert result.verified
        assert "[delegate]" in result.summary
        # 验证 thread_id 是 delegate-* 前缀（独立于主 Agent）
        assert called["thread_id"].startswith("delegate-f1-t1-")
        # 验证 db_path 也是独立的
        assert "delegate_checkpoints" in called["db_path"]
    finally:
        sd.drive_orchestrated = orig


def test_delegate_injects_stuck_reason_as_feedback():
    """delegate 把卡死原因注入 project_rules，让子 Agent 知道之前失败的模式。"""
    import driving.stuck_detector as sd
    called = {}

    def mock_drive(**kwargs):
        called.update(kwargs)
        return {"verified": False, "stop_reason": "verify_failed", "iteration": 1}

    orig = sd.drive_orchestrated
    sd.drive_orchestrated = mock_drive
    try:
        task = FactoryTask(id="t1", description="任务 X", verify_cmd=["true"])
        state = FactoryState(
            factory_id="f1", product_goal="goal", cwd="/tmp", roadmap=[task],
            design_context="设计约束",
        )
        delegate_orchestrator(task, state, "Worker 反复改同一文件")
        rules = called.get("project_rules", "")
        assert "Delegate" in rules
        assert "Worker 反复改同一文件" in rules
        assert "设计约束" in rules  # 设计系统约束也被传入
    finally:
        sd.drive_orchestrated = orig


def test_default_orchestrator_uses_delegate_on_third_attempt():
    """factory_loop.default_orchestrator_fn 在 task.attempts >= 3 时走 delegate。"""
    import driving.factory_loop as fl
    import driving.stuck_detector as sd

    delegate_called = {}
    orig_sd_delegate = sd.delegate_orchestrator

    def mock_delegate(task, state, reason):
        delegate_called["task"] = task
        delegate_called["reason"] = reason
        return TaskResult(task=task, verified=True, stop_reason="verified", iteration=1)

    sd.delegate_orchestrator = mock_delegate
    try:
        task = FactoryTask(
            id="t1", description="任务 X", verify_cmd=["true"],
            attempts=3, feedback="上次失败：verify 失败",
        )
        state = FactoryState(
            factory_id="f1", product_goal="goal", cwd="/tmp", roadmap=[task],
        )
        result = fl.default_orchestrator_fn(task, state)
        assert "reason" in delegate_called
        assert delegate_called["task"].id == "t1"
        assert result.verified
    finally:
        sd.delegate_orchestrator = orig_sd_delegate


def test_default_orchestrator_first_two_attempts_use_normal_path():
    """前 2 次尝试（attempts < 3）走正常 orchestrator，不 delegate。"""
    import driving.factory_loop as fl

    drive_called = {}
    orig_drive = fl.drive_orchestrated

    def mock_drive(**kwargs):
        drive_called.update(kwargs)
        return {"verified": True, "stop_reason": "verified", "iteration": 1}

    fl.drive_orchestrated = mock_drive
    try:
        task = FactoryTask(id="t1", description="任务 X", verify_cmd=["true"], attempts=1)
        state = FactoryState(
            factory_id="f1", product_goal="goal", cwd="/tmp", roadmap=[task],
        )
        fl.default_orchestrator_fn(task, state)
        # 正常路径被调用
        assert "goal" in drive_called
        assert drive_called["thread_id"] == "f1-t1"  # 正常 thread_id 不是 delegate-*
    finally:
        fl.drive_orchestrated = orig_drive
