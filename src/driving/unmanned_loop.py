"""P3-5 · 无人值守循环引擎。

24H 持续改进的 outer loop，集成：
- 自我改进循环 (SelfImprovementLoop)
- 质量对比评估 (QualityComparison)
- 错误自动修复 (AutoRepairEngine)
- 结构化日志 (StructuredLogger)
- 挑战性任务集 (ChallengeSet)

循环模式：
    while not should_stop():
        task = select_next_task()
        flipped_result = execute(task)
        baseline_result = execute_baseline(task)
        comparison = compare(flipped, baseline)
        if comparison.winner != "flipped":
            strategies = generate_improvements(gap)
            apply_strategies(strategies)
            re_compare()
        log_and_record()
        check_budget()

熔断条件：
- 同一任务连续失败 ≥3 次
- 总迭代超过 max_total_iterations
- 预算耗尽 (max_tokens / max_time_seconds)
- 无更多待处理任务
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from driving.auto_repair import AutoRepairEngine, RepairResult
from driving.challenge_tasks import ChallengeSet, ChallengeTask, get_default_challenges
from driving.errors import LoopError, classify_exception
from driving.quality_comparison import (
    ComparisonResult,
    ComparisonConfig,
    compare_outputs,
    calculate_gap,
)
from driving.self_improvement_loop import (
    SelfImprovementLoop,
    LoopIteration,
    ImprovementStrategy,
)
from driving.structured_logger import StructuredLogger, LogLevel
from driving.repair_kb import (
    save_repair_knowledge,
    get_repair_warnings,
    build_repair_warning_text,
)
from driving.knowledge_preflight import KnowledgePreflight, KnowledgeContext


class LoopState(str, Enum):
    idle = "idle"
    running = "running"
    paused = "paused"
    stopped = "stopped"
    circuit_broken = "circuit_broken"
    budget_exhausted = "budget_exhausted"


@dataclass
class TaskExecution:
    """单次任务执行记录。"""
    task_id: str
    task_title: str
    flipped_output: dict[str, Any] = field(default_factory=dict)
    baseline_output: dict[str, Any] = field(default_factory=dict)
    comparison: ComparisonResult | None = None
    repair_result: RepairResult | None = None
    strategies_applied: list[str] = field(default_factory=list)
    repair_warnings: list[dict[str, Any]] = field(default_factory=list)
    repair_knowledge_saved: bool = False
    knowledge_context: KnowledgeContext | None = None
    knowledge_preflight_done: bool = False
    success: bool = False
    duration_ms: float = 0.0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_title": self.task_title,
            "comparison": self.comparison.to_dict() if self.comparison else None,
            "repair_result": self.repair_result.to_dict() if self.repair_result else None,
            "strategies_applied": self.strategies_applied,
            "repair_warnings": self.repair_warnings,
            "repair_knowledge_saved": self.repair_knowledge_saved,
            "knowledge_preflight_done": self.knowledge_preflight_done,
            "knowledge_results_count": len(self.knowledge_context.results) if self.knowledge_context else 0,
            "knowledge_cached": self.knowledge_context.cached if self.knowledge_context else False,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
        }


@dataclass
class BudgetTracker:
    """预算追踪器。"""
    max_iterations: int = 100
    max_time_seconds: float = 86400  # 24H
    max_errors: int = 50
    iterations_used: int = 0
    time_elapsed: float = 0.0
    errors_count: int = 0

    def consume(self, *, iterations: int = 1, time_seconds: float = 0.0, errors: int = 0) -> None:
        self.iterations_used += iterations
        self.time_elapsed += time_seconds
        self.errors_count += errors

    def exhausted(self) -> bool:
        if self.iterations_used >= self.max_iterations:
            return True
        if self.time_elapsed >= self.max_time_seconds:
            return True
        if self.errors_count >= self.max_errors:
            return True
        return False

    def remaining(self) -> dict[str, float]:
        return {
            "iterations": max(0, self.max_iterations - self.iterations_used),
            "time_seconds": max(0, self.max_time_seconds - self.time_elapsed),
            "errors_budget": max(0, self.max_errors - self.errors_count),
        }


@dataclass
class CircuitBreaker:
    """熔断器：同一任务连续失败 N 次后熔断。"""
    threshold: int = 3
    failure_counts: dict[str, int] = field(default_factory=dict)
    tripped_tasks: set[str] = field(default_factory=set)

    def record_failure(self, task_id: str) -> None:
        self.failure_counts[task_id] = self.failure_counts.get(task_id, 0) + 1
        if self.failure_counts[task_id] >= self.threshold:
            self.tripped_tasks.add(task_id)

    def record_success(self, task_id: str) -> None:
        self.failure_counts.pop(task_id, None)
        self.tripped_tasks.discard(task_id)

    def is_tripped(self, task_id: str) -> bool:
        return task_id in self.tripped_tasks

    def any_tripped(self) -> bool:
        return len(self.tripped_tasks) > 0


@dataclass
class UnmannedLoop:
    """无人值守循环引擎。

    execute_fn: 可注入的任务执行函数，签名 (task: ChallengeTask) -> dict[str, Any]。
    baseline_fn: 基准执行函数，签名同上。
    """
    challenge_set: ChallengeSet = field(default_factory=get_default_challenges)
    improvement_loop: SelfImprovementLoop = field(default_factory=SelfImprovementLoop)
    repair_engine: AutoRepairEngine = field(default_factory=AutoRepairEngine)
    logger: StructuredLogger = field(default_factory=lambda: StructuredLogger(module_name="unmanned_loop"))
    budget: BudgetTracker = field(default_factory=BudgetTracker)
    circuit_breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    comparison_config: ComparisonConfig = field(default_factory=ComparisonConfig)
    knowledge_preflight: KnowledgePreflight | None = None
    state: LoopState = LoopState.idle
    executions: list[TaskExecution] = field(default_factory=list)
    execute_fn: Callable[[ChallengeTask], dict[str, Any]] | None = None
    baseline_fn: Callable[[ChallengeTask], dict[str, Any]] | None = None

    def _default_execute(self, task: ChallengeTask) -> dict[str, Any]:
        """默认执行函数：返回基于任务难度的模拟分数。"""
        base = {"correctness": 85, "completeness": 80, "code_quality": 75, "design": 70, "efficiency": 80, "creativity": 65}
        difficulty_mod = {"easy": 5, "medium": 0, "hard": -10, "expert": -20}
        mod = difficulty_mod.get(task.difficulty.value, 0)
        return {k: max(0, min(100, v + mod)) for k, v in base.items()}

    def _default_baseline(self, task: ChallengeTask) -> dict[str, Any]:
        """默认基准：比 flipped 略强。"""
        base = {"correctness": 90, "completeness": 85, "code_quality": 85, "design": 82, "efficiency": 85, "creativity": 80}
        difficulty_mod = {"easy": 3, "medium": 0, "hard": -5, "expert": -15}
        mod = difficulty_mod.get(task.difficulty.value, 0)
        return {k: max(0, min(100, v + mod)) for k, v in base.items()}

    def select_next_task(self) -> ChallengeTask | None:
        """选择下一个未熔断的任务。"""
        for task in self.challenge_set.tasks:
            if not self.circuit_breaker.is_tripped(task.id):
                return task
        return None

    def run_one(self) -> TaskExecution:
        """执行单次任务循环。"""
        self.state = LoopState.running
        start_time = datetime.now(timezone.utc)

        task = self.select_next_task()
        if task is None:
            self.logger.warn("no_tasks_available")
            self.state = LoopState.stopped
            return TaskExecution(task_id="", task_title="")

        self.logger.info("task_selected", {"task_id": task.id, "title": task.title})

        # P4-3: 执行前检索历史修复知识，注入预警
        repair_warnings: list[dict[str, Any]] = []
        try:
            repair_warnings = get_repair_warnings(task.description or task.title)
            if repair_warnings:
                self.logger.info("repair_warnings_loaded", {
                    "task_id": task.id,
                    "warning_count": len(repair_warnings),
                })
        except Exception:
            pass

        # P5: 执行前联网查询获取最新知识
        knowledge_context: KnowledgeContext | None = None
        preflight_done = False
        if self.knowledge_preflight is not None:
            try:
                knowledge_context = self.knowledge_preflight.preflight(task)
                preflight_done = True
                self.logger.info("knowledge_preflight_done", {
                    "task_id": task.id,
                    "results": len(knowledge_context.results),
                    "cached": knowledge_context.cached,
                    "time_ms": knowledge_context.search_time_ms,
                })
            except Exception as exc:
                self.logger.warn("knowledge_preflight_failed", {
                    "task_id": task.id,
                    "error": str(exc),
                })

        exec_fn = self.execute_fn or self._default_execute
        base_fn = self.baseline_fn or self._default_baseline

        try:
            flipped_output = exec_fn(task)
            baseline_output = base_fn(task)

            dims = list(flipped_output.keys())
            comparison = compare_outputs(
                flipped_output, baseline_output, dims,
                config=self.comparison_config,
            )

            strategies_applied: list[str] = []
            repair_result: RepairResult | None = None

            if comparison.winner != "flipped":
                gap = calculate_gap(comparison)
                strategies = ImprovementStrategy.generate_from_gap(
                    weakest_dimensions=gap.get("dimensions_behind", []),
                    strongest_dimensions=gap.get("dimensions_ahead", []),
                    overall_gap=gap.get("overall_gap", 0),
                )
                strategies_applied = [s["action"] for s in strategies]

                self.logger.info("improvement_strategies", {
                    "strategies": strategies_applied,
                    "gap": gap.get("overall_gap"),
                })

            duration = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            execution = TaskExecution(
                task_id=task.id,
                task_title=task.title,
                flipped_output=flipped_output,
                baseline_output=baseline_output,
                comparison=comparison,
                strategies_applied=strategies_applied,
                repair_result=repair_result,
                repair_warnings=repair_warnings,
                knowledge_context=knowledge_context,
                knowledge_preflight_done=preflight_done,
                success=comparison.winner == "flipped",
                duration_ms=round(duration, 2),
            )

            if execution.success:
                self.circuit_breaker.record_success(task.id)
            else:
                self.circuit_breaker.record_failure(task.id)
                if self.circuit_breaker.is_tripped(task.id):
                    self.logger.error("circuit_broken", {"task_id": task.id})
                    self.state = LoopState.circuit_broken

            self.executions.append(execution)
            self.budget.consume(iterations=1, time_seconds=duration / 1000)

            self.logger.info("task_completed", {
                "task_id": task.id,
                "winner": comparison.winner,
                "flipped_score": comparison.flipped_score,
                "baseline_score": comparison.baseline_score,
                "success": execution.success,
            })

            if self.budget.exhausted():
                self.logger.warn("budget_exhausted", self.budget.remaining())
                self.state = LoopState.budget_exhausted
            else:
                self.state = LoopState.idle

            return execution

        except Exception as exc:
            error_record = classify_exception(exc)
            self.logger.error("task_failed", {
                "task_id": task.id,
                "error": error_record.to_dict(),
            })
            self.budget.consume(iterations=1, errors=1)
            self.circuit_breaker.record_failure(task.id)

            repair_result = self.repair_engine.repair(exc, {"task_id": task.id})
            self.logger.info("auto_repair_attempted", {
                "success": repair_result.success,
                "actions": len(repair_result.actions),
            })

            # P4-1: 修复结果沉淀到知识库
            knowledge_saved = False
            try:
                knowledge = save_repair_knowledge(
                    task.description or task.title, repair_result
                )
                knowledge_saved = knowledge is not None
                if knowledge_saved:
                    self.logger.info("repair_knowledge_saved", {
                        "task_id": task.id,
                        "reusable": knowledge.reusable if knowledge else False,
                    })
            except Exception:
                pass

            execution = TaskExecution(
                task_id=task.id,
                task_title=task.title,
                repair_result=repair_result,
                repair_warnings=repair_warnings,
                repair_knowledge_saved=knowledge_saved,
                knowledge_context=knowledge_context,
                knowledge_preflight_done=preflight_done,
                success=False,
                duration_ms=round(
                    (datetime.now(timezone.utc) - start_time).total_seconds() * 1000, 2
                ),
            )
            self.executions.append(execution)
            return execution

    def run(self, max_cycles: int = 100) -> dict[str, Any]:
        """运行循环直到停止条件。"""
        self.state = LoopState.running
        self.logger.info("loop_started", {
            "max_cycles": max_cycles,
            "budget": self.budget.max_iterations,
        })

        for cycle in range(max_cycles):
            if self.state in (LoopState.stopped, LoopState.circuit_broken, LoopState.budget_exhausted):
                break
            if self.budget.exhausted():
                self.state = LoopState.budget_exhausted
                break

            self.logger.info("cycle_start", {"cycle": cycle + 1})
            self.run_one()

        stats = self.get_stats()
        self.logger.info("loop_finished", stats)
        return stats

    def should_stop(self) -> bool:
        """检查是否应该停止。"""
        if self.budget.exhausted():
            return True
        if self.state in (LoopState.circuit_broken, LoopState.stopped, LoopState.budget_exhausted):
            return True
        if self.select_next_task() is None:
            return True
        return False

    def get_stats(self) -> dict[str, Any]:
        """获取运行统计。"""
        total = len(self.executions)
        if total == 0:
            return {"total_executions": 0, "state": self.state.value}

        successes = sum(1 for e in self.executions if e.success)
        flips = sum(1 for e in self.executions if e.comparison and e.comparison.winner == "flipped")

        scores = [
            e.comparison.flipped_score for e in self.executions
            if e.comparison
        ]
        avg_flipped = sum(scores) / len(scores) if scores else 0

        repair_stats = self.repair_engine.get_stats()

        # P5: 知识预检统计
        preflight_count = sum(1 for e in self.executions if e.knowledge_preflight_done)
        preflight_cached = sum(
            1 for e in self.executions
            if e.knowledge_context and e.knowledge_context.cached
        )
        preflight_results_total = sum(
            len(e.knowledge_context.results) for e in self.executions
            if e.knowledge_context
        )

        return {
            "total_executions": total,
            "successful": successes,
            "flipped_wins": flips,
            "win_rate": round(flips / total, 3) if total > 0 else 0,
            "avg_flipped_score": round(avg_flipped, 2),
            "state": self.state.value,
            "budget_remaining": self.budget.remaining(),
            "circuit_breaker_tripped": list(self.circuit_breaker.tripped_tasks),
            "repair_stats": repair_stats,
            "knowledge_preflight": {
                "preflight_count": preflight_count,
                "cached_count": preflight_cached,
                "total_results": preflight_results_total,
                "cache_stats": self.knowledge_preflight.get_stats()["cache"] if self.knowledge_preflight else None,
            },
            "total_log_entries": len(self.logger.entries),
        }
