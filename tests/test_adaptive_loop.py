"""M106 · 自适应回路检测测试。

根据任务复杂度动态调整 loop_threshold，避免"简单任务熔断太松、复杂任务熔断太紧"。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from driving.adaptive_loop import (
    estimate_task_complexity,
    compute_dynamic_threshold,
    detect_progress,
    check_loop_behavior,
    LoopDiagnosis,
    ComplexityLevel,
)


class TestEstimateComplexity:
    def test_simple_short_task(self):
        level, score = estimate_task_complexity(
            "fix button color",
            file_count=1,
        )
        assert level == ComplexityLevel.simple
        assert score < 30

    def test_complex_multi_file_task(self):
        level, score = estimate_task_complexity(
            "build a full e-commerce dashboard with user management, "
            "order processing, inventory tracking, and analytics charts",
            file_count=15,
        )
        assert level in (ComplexityLevel.medium, ComplexityLevel.complex)
        assert score > 50

    def test_more_files_higher_complexity(self):
        desc = "implement feature X"
        l1, s1 = estimate_task_complexity(desc, file_count=1)
        l2, s2 = estimate_task_complexity(desc, file_count=20)
        assert s2 > s1

    def test_longer_description_higher_complexity(self):
        short = "fix bug"
        long_desc = (
            "fix a complex bug in the authentication flow that involves "
            "multiple layers of validation, session management, token "
            "refreshing, and cross-browser compatibility issues"
        )
        _, s1 = estimate_task_complexity(short, file_count=1)
        _, s2 = estimate_task_complexity(long_desc, file_count=1)
        assert s2 > s1


class TestDynamicThreshold:
    def test_simple_task_low_threshold(self):
        threshold = compute_dynamic_threshold(ComplexityLevel.simple)
        assert threshold <= 3

    def test_complex_task_high_threshold(self):
        threshold = compute_dynamic_threshold(ComplexityLevel.complex)
        assert threshold >= 5

    def test_medium_between_simple_and_complex(self):
        t_simple = compute_dynamic_threshold(ComplexityLevel.simple)
        t_medium = compute_dynamic_threshold(ComplexityLevel.medium)
        t_complex = compute_dynamic_threshold(ComplexityLevel.complex)
        assert t_simple <= t_medium <= t_complex


class TestDetectProgress:
    def test_file_change_is_progress(self):
        prev = {"a.py": "def foo(): pass"}
        curr = {"a.py": "def foo(): return 1"}
        has_progress, reason = detect_progress(prev, curr, verify_output_prev="", verify_output_curr="")
        assert has_progress is True
        assert "文件" in reason

    def test_verify_output_change_is_progress(self):
        prev = {"a.py": "same"}
        curr = {"a.py": "same"}
        has_progress, reason = detect_progress(
            prev, curr,
            verify_output_prev="FAILED: missing import",
            verify_output_curr="FAILED: syntax error on line 5",
        )
        assert has_progress is True
        assert "验证" in reason

    def test_no_change_no_progress(self):
        prev = {"a.py": "def foo(): pass"}
        curr = {"a.py": "def foo(): pass"}
        has_progress, _ = detect_progress(
            prev, curr,
            verify_output_prev="FAILED: same error",
            verify_output_curr="FAILED: same error",
        )
        assert has_progress is False

    def test_empty_files_no_progress(self):
        has_progress, _ = detect_progress({}, {}, "", "")
        assert has_progress is False


class TestCheckLoopBehavior:
    def test_no_progress_triggers_warning(self):
        history = [
            {"files": {"a.py": "v1"}, "verify": "error A"},
            {"files": {"a.py": "v1"}, "verify": "error A"},
            {"files": {"a.py": "v1"}, "verify": "error A"},
        ]
        diagnosis = check_loop_behavior(
            history,
            task_description="simple fix",
            file_count=1,
        )
        assert isinstance(diagnosis, LoopDiagnosis)
        assert diagnosis.should_escalate is True

    def test_progress_does_not_trigger(self):
        history = [
            {"files": {"a.py": "v1"}, "verify": "error A"},
            {"files": {"a.py": "v2"}, "verify": "error B"},
            {"files": {"a.py": "v3"}, "verify": "error C"},
        ]
        diagnosis = check_loop_behavior(
            history,
            task_description="simple fix",
            file_count=1,
        )
        assert diagnosis.should_escalate is False

    def test_below_threshold_no_escalation(self):
        history = [
            {"files": {"a.py": "v1"}, "verify": "error A"},
        ]
        diagnosis = check_loop_behavior(
            history,
            task_description="simple fix",
            file_count=1,
        )
        assert diagnosis.should_escalate is False

    def test_complex_task_allows_more_iterations(self):
        history = [
            {"files": {"a.py": "v1"}, "verify": "error A"},
            {"files": {"a.py": "v1"}, "verify": "error A"},
            {"files": {"a.py": "v1"}, "verify": "error A"},
        ]
        simple_diag = check_loop_behavior(history, "fix bug", file_count=1)
        complex_diag = check_loop_behavior(
            history,
            "build a complex distributed system with many components",
            file_count=20,
        )
        assert simple_diag.current_threshold <= complex_diag.current_threshold


class TestLoopDiagnosis:
    def test_diagnosis_has_expected_fields(self):
        diagnosis = LoopDiagnosis(
            should_escalate=True,
            reason="no progress for 3 iterations",
            complexity_level=ComplexityLevel.simple,
            complexity_score=10,
            current_threshold=3,
            consecutive_stuck=3,
            suggested_action="change_temperature",
        )
        assert diagnosis.should_escalate is True
        assert diagnosis.complexity_level == ComplexityLevel.simple
        assert diagnosis.suggested_action == "change_temperature"
