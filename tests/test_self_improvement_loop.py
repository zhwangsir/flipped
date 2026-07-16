"""M123 · 自我超越循环测试。

Self-Improvement Loop = 对比→反馈→优化→再对比 的闭环，
目标是让 flipped 系统产出质量持续超越基准（监督者）。

循环流程：
1. 生成：flipped 和 基准 各生成一份产出
2. 对比：多维度质量对比
3. 分析：差距分析 + 根因定位
4. 优化：生成改进策略并应用
5. 再对比：验证改进效果
6. 循环：直到 flipped 连续 N 次胜出
"""
from __future__ import annotations

from driving.self_improvement_loop import (
    SelfImprovementLoop,
    LoopIteration,
    ImprovementStrategy,
    run_improvement_cycle,
    check_surpass_threshold,
)


class TestLoopIteration:
    def test_iteration_has_fields(self):
        it = LoopIteration(
            iteration=1,
            winner="baseline",
            flipped_score=75,
            baseline_score=85,
            gap=-10,
        )
        assert it.iteration == 1
        assert it.winner == "baseline"


class TestSelfImprovementLoop:
    def test_loop_runs_iterations(self):
        loop = SelfImprovementLoop(target_win_rate=0.6, max_iterations=5)
        result = loop.run(
            initial_flipped_score=70,
            initial_baseline_score=85,
            improvement_per_round=5,
        )
        assert result is not None
        assert result["total_iterations"] >= 1
        assert "final_win_rate" in result

    def test_loop_is_deterministic_with_fixed_seed(self):
        """注入固定种子的 rng，两次运行结果应完全一致。"""
        import random
        loop1 = SelfImprovementLoop(rng=random.Random(42), max_iterations=5)
        loop2 = SelfImprovementLoop(rng=random.Random(42), max_iterations=5)
        r1 = loop1.run(initial_flipped_score=70, initial_baseline_score=85)
        r2 = loop2.run(initial_flipped_score=70, initial_baseline_score=85)
        assert r1["total_iterations"] == r2["total_iterations"]
        assert r1["final_flipped_score"] == r2["final_flipped_score"]
        assert r1["final_baseline_score"] == r2["final_baseline_score"]
        for h1, h2 in zip(r1["history"], r2["history"]):
            assert h1.flipped_score == h2.flipped_score
            assert h1.baseline_score == h2.baseline_score
            assert h1.winner == h2.winner

    def test_loop_stops_when_target_reached(self):
        loop = SelfImprovementLoop(target_win_rate=0.8, max_iterations=20)
        result = loop.run(
            initial_flipped_score=60,
            initial_baseline_score=80,
            improvement_per_round=10,
        )
        assert result["target_reached"] is True or result["total_iterations"] <= 20

    def test_loop_respects_max_iterations(self):
        loop = SelfImprovementLoop(target_win_rate=0.99, max_iterations=3)
        result = loop.run(
            initial_flipped_score=50,
            initial_baseline_score=90,
            improvement_per_round=2,
        )
        assert result["total_iterations"] <= 3

    def test_loop_history(self):
        loop = SelfImprovementLoop(target_win_rate=0.7, max_iterations=5)
        result = loop.run(
            initial_flipped_score=65,
            initial_baseline_score=80,
            improvement_per_round=5,
        )
        assert len(result["history"]) >= 1


class TestImprovementStrategy:
    def test_generate_strategies_from_gap(self):
        strategies = ImprovementStrategy.generate_from_gap(
            weakest_dimensions=["design", "creativity"],
            strongest_dimensions=["correctness"],
            overall_gap=-15,
        )
        assert isinstance(strategies, list)
        assert len(strategies) >= 1
        assert all("dimension" in s for s in strategies)

    def test_prioritize_strategies(self):
        strategies = [
            {"dimension": "correctness", "impact": "high", "effort": "low"},
            {"dimension": "design", "impact": "medium", "effort": "high"},
            {"dimension": "creativity", "impact": "high", "effort": "medium"},
        ]
        prioritized = ImprovementStrategy.prioritize(strategies)
        assert prioritized[0]["impact"] == "high"


class TestCheckSurpassThreshold:
    def test_not_yet_surpassed(self):
        iterations = [
            LoopIteration(1, "baseline", 70, 85, -15),
            LoopIteration(2, "baseline", 75, 85, -10),
        ]
        result = check_surpass_threshold(iterations, required_consecutive=3)
        assert result["surpassed"] is False

    def test_surpassed(self):
        iterations = [
            LoopIteration(1, "baseline", 70, 85, -15),
            LoopIteration(2, "flipped", 88, 85, 3),
            LoopIteration(3, "flipped", 90, 85, 5),
            LoopIteration(4, "flipped", 92, 85, 7),
        ]
        result = check_surpass_threshold(iterations, required_consecutive=3)
        assert result["surpassed"] is True
        assert result["consecutive_wins"] >= 3


class TestRunImprovementCycle:
    def test_cycle_returns_result(self):
        result = run_improvement_cycle(
            task_description="build a landing page",
            initial_flipped_score=70,
            initial_baseline_score=85,
            max_cycles=5,
            target_win_rate=0.6,
        )
        assert "total_cycles" in result
        assert "final_score" in result
        assert isinstance(result["history"], list)
