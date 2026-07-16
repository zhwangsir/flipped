"""P3-5 · 无人值守循环引擎测试。"""
from __future__ import annotations

from driving.unmanned_loop import (
    UnmannedLoop,
    LoopState,
    BudgetTracker,
    CircuitBreaker,
    TaskExecution,
)
from driving.challenge_tasks import ChallengeSet, ChallengeTask, TaskCategory, DifficultyLevel, get_default_challenges


class TestBudgetTracker:
    def test_consume(self):
        bt = BudgetTracker(max_iterations=10)
        bt.consume(iterations=3)
        assert bt.iterations_used == 3

    def test_exhausted_by_iterations(self):
        bt = BudgetTracker(max_iterations=2)
        bt.consume(iterations=2)
        assert bt.exhausted() is True

    def test_exhausted_by_errors(self):
        bt = BudgetTracker(max_errors=3)
        bt.consume(errors=3)
        assert bt.exhausted() is True

    def test_not_exhausted(self):
        bt = BudgetTracker(max_iterations=100, max_time_seconds=86400, max_errors=50)
        bt.consume(iterations=5)
        assert bt.exhausted() is False

    def test_remaining(self):
        bt = BudgetTracker(max_iterations=10, max_time_seconds=100, max_errors=5)
        bt.consume(iterations=3, time_seconds=20, errors=1)
        r = bt.remaining()
        assert r["iterations"] == 7
        assert r["time_seconds"] == 80
        assert r["errors_budget"] == 4


class TestCircuitBreaker:
    def test_record_failure(self):
        cb = CircuitBreaker(threshold=3)
        cb.record_failure("task-1")
        cb.record_failure("task-1")
        assert not cb.is_tripped("task-1")
        cb.record_failure("task-1")
        assert cb.is_tripped("task-1")

    def test_record_success_clears(self):
        cb = CircuitBreaker(threshold=3)
        cb.record_failure("task-1")
        cb.record_failure("task-1")
        cb.record_success("task-1")
        assert not cb.is_tripped("task-1")
        assert cb.failure_counts.get("task-1", 0) == 0

    def test_any_tripped(self):
        cb = CircuitBreaker(threshold=2)
        assert not cb.any_tripped()
        cb.record_failure("t1")
        cb.record_failure("t1")
        assert cb.any_tripped()


class TestTaskExecution:
    def test_to_dict(self):
        e = TaskExecution(task_id="t1", task_title="Test", success=True)
        d = e.to_dict()
        assert d["task_id"] == "t1"
        assert d["success"] is True
        assert d["comparison"] is None


class TestUnmannedLoop:
    def test_loop_initial_state(self):
        loop = UnmannedLoop()
        assert loop.state == LoopState.idle

    def test_run_one(self):
        loop = UnmannedLoop()
        loop.challenge_set = ChallengeSet()
        loop.challenge_set.add_task(ChallengeTask(
            id="t1", title="Test Task",
            category=TaskCategory.code_generation,
            difficulty=DifficultyLevel.easy,
            description="", evaluation_criteria=["correctness"],
        ))
        execution = loop.run_one()
        assert execution.task_id == "t1"
        assert loop.state in (LoopState.idle, LoopState.budget_exhausted, LoopState.circuit_broken)

    def test_run_multiple_cycles(self):
        loop = UnmannedLoop()
        loop.budget = BudgetTracker(max_iterations=3, max_errors=10)
        result = loop.run(max_cycles=3)
        assert "total_executions" in result
        assert result["total_executions"] >= 1

    def test_circuit_breaker_triggers(self):
        loop = UnmannedLoop()
        loop.circuit_breaker = CircuitBreaker(threshold=1)
        # Force failures by using a bad execute_fn
        loop.execute_fn = lambda task: {"correctness": 0}
        loop.baseline_fn = lambda task: {"correctness": 100}
        loop.run(max_cycles=3)
        # Should have some tripped tasks
        assert loop.state == LoopState.circuit_broken or len(loop.circuit_breaker.tripped_tasks) > 0

    def test_budget_exhaustion(self):
        loop = UnmannedLoop()
        loop.budget = BudgetTracker(max_iterations=1, max_errors=1)
        loop.run(max_cycles=10)
        assert loop.budget.exhausted()

    def test_should_stop_no_tasks(self):
        loop = UnmannedLoop()
        loop.challenge_set = ChallengeSet()
        assert loop.should_stop()

    def test_should_stop_budget(self):
        loop = UnmannedLoop()
        loop.budget = BudgetTracker(max_iterations=0)
        assert loop.should_stop()

    def test_get_stats(self):
        loop = UnmannedLoop()
        loop.challenge_set = ChallengeSet()
        loop.challenge_set.add_task(ChallengeTask(
            id="t1", title="T1",
            category=TaskCategory.code_generation,
            difficulty=DifficultyLevel.easy,
            description="", evaluation_criteria=[],
        ))
        loop.run_one()
        stats = loop.get_stats()
        assert stats["total_executions"] >= 1
        assert "win_rate" in stats
        assert "repair_stats" in stats

    def test_injected_execute_fn(self):
        loop = UnmannedLoop()
        loop.challenge_set = ChallengeSet()
        loop.challenge_set.add_task(ChallengeTask(
            id="t1", title="T1",
            category=TaskCategory.code_generation,
            difficulty=DifficultyLevel.easy,
            description="", evaluation_criteria=[],
        ))
        loop.execute_fn = lambda t: {"correctness": 100, "design": 95}
        loop.baseline_fn = lambda t: {"correctness": 80, "design": 75}
        execution = loop.run_one()
        assert execution.success is True
        assert execution.comparison.winner == "flipped"

    def test_auto_repair_on_error(self):
        loop = UnmannedLoop()
        loop.challenge_set = ChallengeSet()
        loop.challenge_set.add_task(ChallengeTask(
            id="t1", title="T1",
            category=TaskCategory.code_generation,
            difficulty=DifficultyLevel.easy,
            description="", evaluation_criteria=[],
        ))

        def bad_execute(task):
            raise ValueError("simulated failure")

        loop.execute_fn = bad_execute
        execution = loop.run_one()
        assert execution.success is False
        assert execution.repair_result is not None
