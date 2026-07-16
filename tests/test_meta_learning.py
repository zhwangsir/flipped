"""M112 · 自我改进元循环测试。

系统定期回顾自己的表现，识别瓶颈，自动调优超参数。
"""
from __future__ import annotations

from driving.meta_learning import (
    MetaLearningResult,
    analyze_performance,
    identify_bottlenecks,
    suggest_hyperparameters,
    run_meta_review,
)


class TestAnalyzePerformance:
    def test_analyze_with_data(self):
        history = [
            {"success": True, "iterations": 2, "tokens": 1000},
            {"success": True, "iterations": 3, "tokens": 1500},
            {"success": False, "iterations": 5, "tokens": 2000},
            {"success": True, "iterations": 1, "tokens": 800},
        ]
        result = analyze_performance(history)
        assert result.total_tasks == 4
        assert result.success_rate > 0.5
        assert result.avg_iterations > 0

    def test_analyze_empty(self):
        result = analyze_performance([])
        assert result.total_tasks == 0
        assert result.success_rate == 0.0


class TestIdentifyBottlenecks:
    def test_identify_iteration_bottleneck(self):
        history = [
            {"success": True, "iterations": 6, "tokens": 3000, "stop_reason": "max_iterations"},
            {"success": True, "iterations": 5, "tokens": 2500, "stop_reason": "max_iterations"},
            {"success": False, "iterations": 7, "tokens": 3500, "stop_reason": "max_iterations"},
        ]
        bottlenecks = identify_bottlenecks(history)
        assert len(bottlenecks) >= 1

    def test_empty_history_no_bottlenecks(self):
        assert identify_bottlenecks([]) == []


class TestSuggestHyperparameters:
    def test_suggest_based_on_bottlenecks(self):
        bottlenecks = [{"type": "iteration_limit", "severity": "high"}]
        suggestions = suggest_hyperparameters(bottlenecks)
        assert isinstance(suggestions, list)
        assert len(suggestions) >= 1


class TestRunMetaReview:
    def test_meta_review_returns_result(self):
        history = [
            {"success": True, "iterations": 2, "tokens": 1000, "stop_reason": "verified"},
            {"success": False, "iterations": 4, "tokens": 2000, "stop_reason": "max_iterations"},
            {"success": True, "iterations": 1, "tokens": 500, "stop_reason": "verified"},
        ]
        result = run_meta_review(history)
        assert isinstance(result, MetaLearningResult)
        assert result.total_tasks == 3
        assert len(result.bottlenecks) >= 0
        assert isinstance(result.recommendations, list)
