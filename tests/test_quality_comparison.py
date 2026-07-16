"""M122 · 质量对比评估系统测试。

对比两组产出（flipped vs 基准），多维度评分，判定胜负，分析差距。
"""
from __future__ import annotations

from driving.quality_comparison import (
    QualityComparison,
    ComparisonDimension,
    ComparisonResult,
    compare_outputs,
    calculate_gap,
)


class TestComparisonDimension:
    def test_dimension_enum(self):
        assert ComparisonDimension.correctness == "correctness"
        assert ComparisonDimension.completeness == "completeness"
        assert ComparisonDimension.code_quality == "code_quality"
        assert ComparisonDimension.design == "design"
        assert ComparisonDimension.efficiency == "efficiency"
        assert ComparisonDimension.creativity == "creativity"


class TestCompareOutputs:
    def test_flipped_wins_on_correctness(self):
        result = compare_outputs(
            flipped_output={"correctness": 95, "code_quality": 80},
            baseline_output={"correctness": 85, "code_quality": 80},
            dimensions=["correctness", "code_quality"],
        )
        assert result.winner == "flipped"
        assert result.flipped_score > result.baseline_score

    def test_baseline_wins(self):
        result = compare_outputs(
            flipped_output={"correctness": 70, "design": 60},
            baseline_output={"correctness": 90, "design": 85},
            dimensions=["correctness", "design"],
        )
        assert result.winner == "baseline"

    def test_tie(self):
        result = compare_outputs(
            flipped_output={"correctness": 80, "completeness": 80},
            baseline_output={"correctness": 80, "completeness": 80},
            dimensions=["correctness", "completeness"],
        )
        assert result.winner == "tie"

    def test_dimension_breakdown(self):
        result = compare_outputs(
            flipped_output={"correctness": 90, "design": 70},
            baseline_output={"correctness": 80, "design": 85},
            dimensions=["correctness", "design"],
        )
        assert "correctness" in result.dimension_details
        assert result.dimension_details["correctness"]["flipped_wins"] is True
        assert result.dimension_details["design"]["flipped_wins"] is False

    def test_custom_weights(self):
        result = compare_outputs(
            flipped_output={"correctness": 70, "design": 95},
            baseline_output={"correctness": 80, "design": 70},
            dimensions=["correctness", "design"],
            weights={"correctness": 0.8, "design": 0.2},
        )
        assert result.winner == "baseline"


class TestCalculateGap:
    def test_gap_calculation(self):
        result = compare_outputs(
            flipped_output={"correctness": 85, "completeness": 75},
            baseline_output={"correctness": 90, "completeness": 70},
            dimensions=["correctness", "completeness"],
        )
        gap = calculate_gap(result)
        assert "overall_gap" in gap
        assert "weakest_dimension" in gap
        assert "strongest_dimension" in gap

    def test_gap_when_flipped_is_ahead(self):
        result = compare_outputs(
            flipped_output={"correctness": 95, "efficiency": 90},
            baseline_output={"correctness": 85, "efficiency": 75},
            dimensions=["correctness", "efficiency"],
        )
        gap = calculate_gap(result)
        assert gap["overall_gap"] > 0


class TestQualityComparisonClass:
    def test_add_comparison_and_get_stats(self):
        qc = QualityComparison()
        r1 = compare_outputs(
            {"correctness": 90}, {"correctness": 80}, ["correctness"]
        )
        r2 = compare_outputs(
            {"correctness": 70}, {"correctness": 85}, ["correctness"]
        )
        qc.add_result(r1)
        qc.add_result(r2)
        stats = qc.get_stats()
        assert stats["total_comparisons"] == 2
        assert stats["flipped_wins"] == 1
        assert stats["baseline_wins"] == 1
        assert "win_rate" in stats

    def test_empty_stats(self):
        qc = QualityComparison()
        stats = qc.get_stats()
        assert stats["total_comparisons"] == 0
        assert stats["win_rate"] == 0.0
