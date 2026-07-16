"""M119 · 产物质量自动分级测试。

Quality Grading = 给产物打 S/A/B/C 四个等级，而不是二元的通过/不通过。
维度：功能完整度、代码质量、设计美感、可维护性、性能效率
"""
from __future__ import annotations

from driving.quality_grading import (
    QualityGrade,
    QualityScore,
    grade_quality,
    QualityDimension,
    get_quality_trend,
)


class TestQualityScore:
    def test_score_has_dimensions(self):
        s = grade_quality({
            "functionality": 90,
            "code_quality": 85,
            "design": 80,
            "maintainability": 88,
            "performance": 92,
        })
        assert s.overall >= 80
        assert s.overall <= 95


class TestGradeQuality:
    def test_s_grade(self):
        result = grade_quality({
            "functionality": 95,
            "code_quality": 92,
            "design": 94,
            "maintainability": 90,
            "performance": 93,
        })
        assert result.grade == QualityGrade.S

    def test_a_grade(self):
        result = grade_quality({
            "functionality": 85,
            "code_quality": 82,
            "design": 88,
            "maintainability": 80,
            "performance": 84,
        })
        assert result.grade == QualityGrade.A

    def test_b_grade(self):
        result = grade_quality({
            "functionality": 70,
            "code_quality": 72,
            "design": 68,
            "maintainability": 75,
            "performance": 70,
        })
        assert result.grade == QualityGrade.B

    def test_c_grade(self):
        result = grade_quality({
            "functionality": 50,
            "code_quality": 55,
            "design": 45,
            "maintainability": 52,
            "performance": 48,
        })
        assert result.grade == QualityGrade.C

    def test_dimension_weights(self):
        result = grade_quality({
            "functionality": 100,
            "code_quality": 100,
            "design": 0,
            "maintainability": 100,
            "performance": 100,
        })
        assert result.overall > 70
        assert result.overall < 100

    def test_empty_metrics_returns_c(self):
        result = grade_quality({})
        assert result.grade == QualityGrade.C


class TestQualityTrend:
    def test_improving_trend(self):
        history = [
            QualityScore(functionality=50, code_quality=55, design=50, maintainability=52, performance=48, overall=51),
            QualityScore(functionality=65, code_quality=62, design=60, maintainability=63, performance=58, overall=62),
            QualityScore(functionality=80, code_quality=78, design=75, maintainability=78, performance=75, overall=77),
            QualityScore(functionality=90, code_quality=88, design=85, maintainability=88, performance=86, overall=87),
        ]
        trend = get_quality_trend(history)
        assert trend["direction"] == "improving"
        assert trend["improvement_rate"] > 0

    def test_degrading_trend(self):
        history = [
            QualityScore(functionality=90, code_quality=88, design=92, maintainability=85, performance=90, overall=89),
            QualityScore(functionality=78, code_quality=76, design=75, maintainability=77, performance=75, overall=76),
            QualityScore(functionality=65, code_quality=63, design=60, maintainability=64, performance=62, overall=63),
            QualityScore(functionality=50, code_quality=48, design=45, maintainability=50, performance=47, overall=48),
        ]
        trend = get_quality_trend(history)
        assert trend["direction"] == "degrading"

    def test_stable_trend(self):
        history = [
            QualityScore(functionality=80, code_quality=78, design=82, maintainability=80, performance=81, overall=80),
            QualityScore(functionality=81, code_quality=79, design=81, maintainability=81, performance=80, overall=80),
            QualityScore(functionality=80, code_quality=80, design=80, maintainability=79, performance=81, overall=80),
            QualityScore(functionality=79, code_quality=81, design=80, maintainability=80, performance=80, overall=80),
        ]
        trend = get_quality_trend(history)
        assert trend["direction"] == "stable"
