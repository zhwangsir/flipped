"""M108 · 任务分解与子任务派发测试。

复杂任务自动分解为 3-5 个子任务，每个子任务独立执行、独立验证，
成功后再合并。降低单次任务复杂度，提升成功率。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from driving.task_decomposer import (
    SubTask,
    DecompositionResult,
    estimate_task_complexity_for_decompose,
    should_decompose,
    decompose_task,
    merge_subtask_results,
    DEFAULT_COMPLEXITY_THRESHOLD,
)


class TestEstimateComplexity:
    def test_simple_task_low_score(self):
        score = estimate_task_complexity_for_decompose(
            "fix button color",
            file_count=1,
        )
        assert score < 30

    def test_complex_task_high_score(self):
        score = estimate_task_complexity_for_decompose(
            "build a full e-commerce dashboard with user management, "
            "order processing, inventory tracking, and analytics charts",
            file_count=15,
        )
        assert score > 60

    def test_more_files_higher_score(self):
        desc = "implement feature X"
        s1 = estimate_task_complexity_for_decompose(desc, file_count=1)
        s2 = estimate_task_complexity_for_decompose(desc, file_count=20)
        assert s2 > s1


class TestShouldDecompose:
    def test_simple_task_no_decompose(self):
        assert should_decompose("fix typo", file_count=1) is False

    def test_complex_task_should_decompose(self):
        assert should_decompose(
            "build a full-stack app with backend, frontend, and database",
            file_count=10,
        ) is True

    def test_below_threshold_no_decompose(self):
        assert should_decompose(
            "medium complexity task",
            file_count=3,
            threshold=80,
        ) is False


class TestDecomposeTask:
    def test_simple_task_returns_single_subtask(self):
        result = decompose_task("fix button color", file_count=1)
        assert isinstance(result, DecompositionResult)
        assert result.should_decompose is False
        assert len(result.subtasks) == 1
        assert result.subtasks[0].description == "fix button color"

    def test_complex_task_returns_multiple_subtasks(self):
        desc = (
            "build a full e-commerce dashboard with user authentication, "
            "product catalog, shopping cart, and admin panel"
        )
        result = decompose_task(desc, file_count=8)
        assert isinstance(result, DecompositionResult)
        assert result.should_decompose is True
        assert len(result.subtasks) >= 3
        assert len(result.subtasks) <= 5

    def test_subtasks_have_order(self):
        desc = (
            "build a blog with user system, post management, and comments"
        )
        result = decompose_task(desc, file_count=6)
        assert result.should_decompose
        for i, st in enumerate(result.subtasks):
            assert st.order == i

    def test_subtasks_have_verify_cmd(self):
        desc = (
            "build a landing page with hero section, features, and footer"
        )
        result = decompose_task(desc, file_count=5)
        assert result.should_decompose
        for st in result.subtasks:
            assert isinstance(st.verify_cmd, list)
            assert len(st.verify_cmd) >= 1

    def test_empty_description_fails_gracefully(self):
        result = decompose_task("", file_count=0)
        assert result.should_decompose is False
        assert len(result.subtasks) == 1


class TestSubTaskDataclass:
    def test_subtask_has_expected_fields(self):
        st = SubTask(
            subtask_id="st-1",
            description="build header",
            order=0,
            verify_cmd=["true"],
            dependencies=[],
        )
        assert st.subtask_id == "st-1"
        assert st.description == "build header"
        assert st.order == 0
        assert st.verify_cmd == ["true"]
        assert st.dependencies == []


class TestDecompositionResultDataclass:
    def test_result_has_expected_fields(self):
        subtasks = [
            SubTask("st-1", "task 1", 0, ["true"], []),
            SubTask("st-2", "task 2", 1, ["true"], ["st-1"]),
        ]
        result = DecompositionResult(
            should_decompose=True,
            subtasks=subtasks,
            original_task="build app",
            complexity_score=75.0,
            reason="complexity above threshold",
        )
        assert result.should_decompose is True
        assert len(result.subtasks) == 2
        assert result.complexity_score == 75.0


class TestMergeSubtaskResults:
    def test_merge_success_all_passed(self):
        subtask_results = [
            {"subtask_id": "st-1", "success": True, "output": "header done"},
            {"subtask_id": "st-2", "success": True, "output": "footer done"},
        ]
        merged = merge_subtask_results(subtask_results)
        assert merged["all_success"] is True
        assert merged["completed_count"] == 2
        assert merged["failed_count"] == 0

    def test_merge_with_failures(self):
        subtask_results = [
            {"subtask_id": "st-1", "success": True, "output": "header done"},
            {"subtask_id": "st-2", "success": False, "error": "syntax error"},
        ]
        merged = merge_subtask_results(subtask_results)
        assert merged["all_success"] is False
        assert merged["completed_count"] == 1
        assert merged["failed_count"] == 1
        assert len(merged["failed_subtasks"]) == 1

    def test_merge_empty_list(self):
        merged = merge_subtask_results([])
        assert merged["all_success"] is True
        assert merged["completed_count"] == 0
        assert merged["failed_count"] == 0
