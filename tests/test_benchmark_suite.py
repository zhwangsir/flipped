"""M115 · 基准测试套件测试。

Benchmark Suite = 量化系统能力的标尺：
- 多维度基准任务（代码生成/Bug修复/重构/UI开发/文档）
- 量化评分（成功率/迭代次数/token消耗/质量分）
- 历史对比（进步/退步）
- 排行榜（不同策略/模型对比）
"""
from __future__ import annotations

from driving.benchmark_suite import (
    BenchmarkTask,
    BenchmarkResult,
    BenchmarkSuite,
    BenchmarkCategory,
)


class TestBenchmarkTask:
    def test_task_has_expected_fields(self):
        t = BenchmarkTask(
            id="bm-001",
            name="generate landing page",
            category=BenchmarkCategory.code_generation,
            description="build a SaaS landing page",
            difficulty=3,
            verify_cmd=["echo", "ok"],
        )
        assert t.id == "bm-001"
        assert t.category == BenchmarkCategory.code_generation

    def test_category_enum(self):
        assert BenchmarkCategory.code_generation == "code_generation"
        assert BenchmarkCategory.bug_fix == "bug_fix"
        assert BenchmarkCategory.refactoring == "refactoring"


class TestBenchmarkResult:
    def test_result_calculates_score(self):
        r = BenchmarkResult(
            task_id="bm-001",
            success=True,
            iterations=2,
            tokens_used=1000,
            quality_score=85,
            duration_seconds=30,
        )
        assert r.success is True
        assert r.composite_score > 0


class TestBenchmarkSuite:
    def test_suite_runs_all_tasks(self):
        suite = BenchmarkSuite()
        task1 = BenchmarkTask(
            id="t1",
            name="test task 1",
            category=BenchmarkCategory.code_generation,
            description="simple task",
            difficulty=1,
            verify_cmd=["true"],
        )
        task2 = BenchmarkTask(
            id="t2",
            name="test task 2",
            category=BenchmarkCategory.bug_fix,
            description="medium task",
            difficulty=2,
            verify_cmd=["true"],
        )
        suite.add_task(task1)
        suite.add_task(task2)
        assert len(suite.tasks) == 2

    def test_suite_calculate_summary(self):
        suite = BenchmarkSuite()
        suite.add_task(BenchmarkTask(
            id="t1", name="t1",
            category=BenchmarkCategory.code_generation,
            description="", difficulty=1, verify_cmd=["true"],
        ))
        r1 = BenchmarkResult(
            task_id="t1", success=True, iterations=2,
            tokens_used=500, quality_score=80, duration_seconds=10,
        )
        suite.record_result(r1)
        summary = suite.get_summary()
        assert summary["total_tasks"] == 1
        assert summary["success_rate"] == 1.0

    def test_compare_with_baseline(self):
        suite = BenchmarkSuite()
        baseline = {
            "success_rate": 0.7,
            "avg_iterations": 4.0,
            "avg_quality": 70.0,
        }
        r1 = BenchmarkResult(
            task_id="t1", success=True, iterations=2,
            tokens_used=500, quality_score=85, duration_seconds=10,
        )
        comparison = suite.compare_with_baseline([r1], baseline)
        assert "success_rate_delta" in comparison
        assert "quality_delta" in comparison

    def test_empty_suite_summary(self):
        suite = BenchmarkSuite()
        summary = suite.get_summary()
        assert summary["total_tasks"] == 0
        assert summary["success_rate"] == 0.0
