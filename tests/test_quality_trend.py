"""P4-4 · 质量趋势追踪测试。"""
from __future__ import annotations

from driving.quality_trend import (
    TrendPoint,
    TrendAnalysis,
    analyze_trend,
    analyze_logger_entries,
)
from driving.structured_logger import StructuredLogger, LogLevel
from driving.quality_comparison import ComparisonResult


def _make_exec(score: float, baseline: float = 80, winner: str = "flipped"):
    """创建模拟 TaskExecution。"""
    class MockExec:
        def __init__(self, flipped_score, baseline_score, win):
            self.comparison = ComparisonResult(
                winner=win,
                flipped_score=flipped_score,
                baseline_score=baseline_score,
                score_delta=flipped_score - baseline_score,
                flipped_won_dimensions=["correctness"] if win == "flipped" else [],
                baseline_won_dimensions=["design"] if win != "flipped" else [],
                tied_dimensions=[],
            )
            self.success = win == "flipped"
            self.timestamp = "2026-01-01T00:00:00Z"

    return MockExec(score, baseline, winner)


class TestTrendPoint:
    def test_to_dict(self):
        p = TrendPoint(cycle=1, timestamp="t", flipped_score=90, baseline_score=80, winner="flipped", success=True)
        d = p.to_dict()
        assert d["cycle"] == 1
        assert d["flipped_score"] == 90


class TestAnalyzeTrend:
    def test_empty_executions(self):
        result = analyze_trend([])
        assert result.trend_direction == "insufficient"
        assert result.total_cycles == 0

    def test_improving_trend(self):
        execs = [
            _make_exec(60, 80, "baseline"),
            _make_exec(70, 80, "baseline"),
            _make_exec(85, 80, "flipped"),
            _make_exec(90, 80, "flipped"),
        ]
        result = analyze_trend(execs)
        assert result.trend_direction == "improving"
        assert result.total_cycles == 4
        assert result.win_rate == 0.5

    def test_declining_trend(self):
        execs = [
            _make_exec(90, 80, "flipped"),
            _make_exec(85, 80, "flipped"),
            _make_exec(60, 80, "baseline"),
            _make_exec(55, 80, "baseline"),
        ]
        result = analyze_trend(execs)
        assert result.trend_direction == "declining"
        assert result.score_trend < 0

    def test_stable_trend(self):
        execs = [
            _make_exec(80, 80, "tie"),
            _make_exec(81, 80, "tie"),
            _make_exec(79, 80, "tie"),
            _make_exec(80, 80, "tie"),
        ]
        result = analyze_trend(execs)
        assert result.trend_direction == "stable"

    def test_bottleneck_dimensions(self):
        execs = [
            _make_exec(90, 80, "baseline"),
            _make_exec(90, 80, "baseline"),
        ]
        result = analyze_trend(execs)
        assert len(result.bottleneck_dimensions) > 0

    def test_recommendations_generated(self):
        execs = [_make_exec(60, 80, "baseline")]
        result = analyze_trend(execs)
        assert len(result.recommendations) >= 1

    def test_data_points_populated(self):
        execs = [_make_exec(90, 80, "flipped"), _make_exec(85, 80, "flipped")]
        result = analyze_trend(execs)
        assert len(result.data_points) == 2


class TestAnalyzeLoggerEntries:
    def test_empty_logger(self):
        logger = StructuredLogger(min_level=LogLevel.info)
        result = analyze_logger_entries(logger)
        assert result["total_entries"] == 0

    def test_with_entries(self):
        logger = StructuredLogger(min_level=LogLevel.trace)
        logger.info("task_completed", {"score": 90})
        logger.error("task_failed", {"error": "test"})
        logger.warn("budget_low")

        result = analyze_logger_entries(logger)
        assert result["total_entries"] == 3
        assert result["error_count"] == 1
        assert result["warning_count"] == 1
        assert "by_level" in result
        assert "top_events" in result
