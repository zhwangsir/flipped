"""M115 · 基准测试套件。

Benchmark Suite = 量化系统能力的标尺：
- 多维度基准任务（代码生成/Bug修复/重构/UI开发/文档）
- 量化评分（成功率/迭代次数/token消耗/质量分）
- 历史对比（进步/退步）
- 排行榜（不同策略/模型对比）

fail-open: 任何异常都返回安全默认值。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class BenchmarkCategory(str, Enum):
    code_generation = "code_generation"
    bug_fix = "bug_fix"
    refactoring = "refactoring"
    ui_development = "ui_development"
    documentation = "documentation"
    debugging = "debugging"
    testing = "testing"


@dataclass
class BenchmarkTask:
    """基准测试任务。"""
    id: str
    name: str
    category: BenchmarkCategory
    description: str
    difficulty: int = 3
    verify_cmd: list[str] = field(default_factory=list)
    expected_artifacts: list[str] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkResult:
    """基准测试结果。"""
    task_id: str
    success: bool
    iterations: int = 0
    tokens_used: int = 0
    quality_score: float = 0.0
    duration_seconds: float = 0.0
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def composite_score(self) -> float:
        """综合评分：成功率 + 效率 + 质量。"""
        try:
            if not self.success:
                return 0.0
            quality = self.quality_score / 100.0
            efficiency = max(0.1, 1.0 - (self.iterations - 1) * 0.1)
            speed = max(0.1, 1.0 - min(1.0, self.duration_seconds / 300.0) * 0.3)
            return round((quality * 0.5 + efficiency * 0.3 + speed * 0.2) * 100, 2)
        except Exception:
            return 0.0


@dataclass
class BenchmarkSuite:
    """基准测试套件。"""
    tasks: list[BenchmarkTask] = field(default_factory=list)
    results: list[BenchmarkResult] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    def add_task(self, task: BenchmarkTask) -> None:
        """添加基准任务。"""
        try:
            self.tasks.append(task)
        except Exception:
            pass

    def remove_task(self, task_id: str) -> None:
        """移除基准任务。"""
        try:
            self.tasks = [t for t in self.tasks if t.id != task_id]
        except Exception:
            pass

    def get_tasks_by_category(
        self, category: BenchmarkCategory,
    ) -> list[BenchmarkTask]:
        """按分类获取任务。"""
        try:
            return [t for t in self.tasks if t.category == category]
        except Exception:
            return []

    def record_result(self, result: BenchmarkResult) -> None:
        """记录测试结果。"""
        try:
            self.results.append(result)
        except Exception:
            pass

    def get_summary(self) -> dict[str, Any]:
        """获取整体测试摘要。"""
        try:
            if not self.results:
                return {
                    "total_tasks": 0,
                    "success_rate": 0.0,
                    "avg_iterations": 0.0,
                    "avg_quality": 0.0,
                    "avg_duration": 0.0,
                    "avg_composite_score": 0.0,
                    "by_category": {},
                }

            total = len(self.results)
            successes = sum(1 for r in self.results if r.success)
            success_rate = successes / total if total > 0 else 0.0

            iters = [r.iterations for r in self.results]
            avg_iters = sum(iters) / len(iters) if iters else 0.0

            quality = [r.quality_score for r in self.results if r.success]
            avg_quality = sum(quality) / len(quality) if quality else 0.0

            durations = [r.duration_seconds for r in self.results]
            avg_dur = sum(durations) / len(durations) if durations else 0.0

            scores = [r.composite_score for r in self.results]
            avg_score = sum(scores) / len(scores) if scores else 0.0

            by_category: dict[str, dict[str, Any]] = {}
            for task in self.tasks:
                cat_results = [r for r in self.results if r.task_id == task.id]
                if cat_results:
                    cat = task.category.value
                    if cat not in by_category:
                        by_category[cat] = {"count": 0, "successes": 0, "avg_quality": 0.0}
                    by_category[cat]["count"] += len(cat_results)
                    by_category[cat]["successes"] += sum(1 for r in cat_results if r.success)
                    cat_qualities = [r.quality_score for r in cat_results if r.success]
                    if cat_qualities:
                        old_avg = by_category[cat]["avg_quality"]
                        old_count = by_category[cat]["count"] - 1
                        new_q = sum(cat_qualities) / len(cat_qualities)
                        by_category[cat]["avg_quality"] = round(
                            (old_avg * old_count + new_q) / by_category[cat]["count"], 1
                        )

            return {
                "total_tasks": total,
                "success_rate": round(success_rate, 3),
                "avg_iterations": round(avg_iters, 2),
                "avg_quality": round(avg_quality, 1),
                "avg_duration": round(avg_dur, 1),
                "avg_composite_score": round(avg_score, 2),
                "by_category": by_category,
            }
        except Exception:
            return {
                "total_tasks": 0,
                "success_rate": 0.0,
                "avg_iterations": 0.0,
                "avg_quality": 0.0,
                "avg_duration": 0.0,
                "avg_composite_score": 0.0,
                "by_category": {},
                "error": "summary calculation failed",
            }

    def compare_with_baseline(
        self,
        current_results: list[BenchmarkResult],
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        """与基线对比，量化进步/退步。"""
        try:
            if not current_results:
                return {"message": "no results to compare"}

            total = len(current_results)
            successes = sum(1 for r in current_results if r.success)
            success_rate = successes / total if total > 0 else 0.0

            iters = [r.iterations for r in current_results]
            avg_iters = sum(iters) / len(iters) if iters else 0.0

            quality = [r.quality_score for r in current_results if r.success]
            avg_quality = sum(quality) / len(quality) if quality else 0.0

            scores = [r.composite_score for r in current_results]
            avg_score = sum(scores) / len(scores) if scores else 0.0

            sr_delta = success_rate - baseline.get("success_rate", 0.0)
            iter_delta = avg_iters - baseline.get("avg_iterations", 0.0)
            qual_delta = avg_quality - baseline.get("avg_quality", 0.0)
            score_delta = avg_score - baseline.get("avg_composite_score", 0.0)

            overall = "improving" if score_delta > 2 else ("degrading" if score_delta < -2 else "stable")

            return {
                "success_rate_delta": round(sr_delta, 3),
                "iterations_delta": round(iter_delta, 2),
                "quality_delta": round(qual_delta, 1),
                "composite_score_delta": round(score_delta, 2),
                "overall_trend": overall,
                "baseline": baseline,
                "current": {
                    "success_rate": round(success_rate, 3),
                    "avg_iterations": round(avg_iters, 2),
                    "avg_quality": round(avg_quality, 1),
                    "avg_composite_score": round(avg_score, 2),
                },
            }
        except Exception:
            return {"error": "comparison failed", "overall_trend": "unknown"}

    def save_baseline(self, label: str) -> dict[str, Any]:
        """保存当前结果为基线。"""
        try:
            summary = self.get_summary()
            entry = {
                "label": label,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
                "result_count": len(self.results),
            }
            self.history.append(entry)
            return entry
        except Exception:
            return {"error": "save baseline failed"}
