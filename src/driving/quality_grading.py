"""M119 · 产物质量自动分级。

Quality Grading = S/A/B/C 四级评分，比二元通过/不通过更细粒度。

5 个维度（可配置权重）：
- functionality: 功能完整度（权重最高）
- code_quality: 代码质量
- design: 设计美感/体验
- maintainability: 可维护性
- performance: 性能效率

fail-open: 异常时返回 C 级保守结果。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class QualityGrade(str, Enum):
    S = "S"
    A = "A"
    B = "B"
    C = "C"


class QualityDimension(str, Enum):
    functionality = "functionality"
    code_quality = "code_quality"
    design = "design"
    maintainability = "maintainability"
    performance = "performance"


@dataclass
class QualityScore:
    """质量评分。"""
    functionality: float = 0.0
    code_quality: float = 0.0
    design: float = 0.0
    maintainability: float = 0.0
    performance: float = 0.0
    grade: QualityGrade = QualityGrade.C
    overall: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


DEFAULT_WEIGHTS: dict[str, float] = {
    "functionality": 0.30,
    "code_quality": 0.25,
    "maintainability": 0.20,
    "design": 0.15,
    "performance": 0.10,
}

GRADE_THRESHOLDS: dict[QualityGrade, float] = {
    QualityGrade.S: 90.0,
    QualityGrade.A: 75.0,
    QualityGrade.B: 60.0,
    QualityGrade.C: 0.0,
}


def _calculate_overall(
    metrics: dict[str, float],
    weights: dict[str, float] | None = None,
) -> float:
    """计算加权总分。"""
    try:
        w = weights or DEFAULT_WEIGHTS
        total_weight = 0.0
        total_score = 0.0
        for dim, weight in w.items():
            if dim in metrics:
                total_score += metrics[dim] * weight
                total_weight += weight
        if total_weight == 0:
            return 0.0
        return round(total_score / total_weight * 100 / 100, 2)
    except Exception:
        return 0.0


def _to_grade(score: float) -> QualityGrade:
    """分数转等级。"""
    if score >= GRADE_THRESHOLDS[QualityGrade.S]:
        return QualityGrade.S
    elif score >= GRADE_THRESHOLDS[QualityGrade.A]:
        return QualityGrade.A
    elif score >= GRADE_THRESHOLDS[QualityGrade.B]:
        return QualityGrade.B
    else:
        return QualityGrade.C


def grade_quality(
    metrics: dict[str, Any],
    *,
    weights: dict[str, float] | None = None,
) -> QualityScore:
    """给产物质量打分级。

    metrics 可以包含 functionality / code_quality / design / maintainability / performance。
    缺失的维度取默认值（60分，即 B 以下）。
    """
    try:
        normalized: dict[str, float] = {}
        for dim in DEFAULT_WEIGHTS:
            val = metrics.get(dim)
            if val is None:
                normalized[dim] = 40.0 if not metrics else 60.0
            else:
                try:
                    normalized[dim] = float(val)
                except (ValueError, TypeError):
                    normalized[dim] = 60.0

        overall = _calculate_overall(normalized, weights)
        grade = _to_grade(overall)

        strengths = []
        weaknesses = []
        for dim, score in normalized.items():
            if score >= 85:
                strengths.append(dim)
            elif score < 70:
                weaknesses.append(dim)

        return QualityScore(
            functionality=normalized["functionality"],
            code_quality=normalized["code_quality"],
            design=normalized["design"],
            maintainability=normalized["maintainability"],
            performance=normalized["performance"],
            grade=grade,
            overall=overall,
            details={
                "strengths": strengths,
                "weaknesses": weaknesses,
                "weights_used": weights or DEFAULT_WEIGHTS,
            },
        )
    except Exception:
        return QualityScore(grade=QualityGrade.C, overall=0.0)


def get_quality_trend(
    history: list[QualityScore],
    *,
    window: int = 5,
) -> dict[str, Any]:
    """分析质量趋势。"""
    try:
        if len(history) < 2:
            return {
                "direction": "insufficient_data",
                "improvement_rate": 0.0,
                "message": "数据不足，无法判断趋势",
            }

        recent = history[-window:] if len(history) > window else history
        n = len(recent)

        if n < 2:
            return {"direction": "stable", "improvement_rate": 0.0, "message": "数据太少"}

        first_half = recent[: n // 2]
        second_half = recent[n // 2 :]

        avg_first = sum(s.overall for s in first_half) / max(1, len(first_half))
        avg_second = sum(s.overall for s in second_half) / max(1, len(second_half))

        delta = avg_second - avg_first
        rate = delta / max(1, n)

        if delta > 3:
            direction = "improving"
            msg = f"质量持续提升，平均提升 {delta:.1f} 分"
        elif delta < -3:
            direction = "degrading"
            msg = f"质量有所下降，平均下降 {abs(delta):.1f} 分"
        else:
            direction = "stable"
            msg = "质量保持稳定"

        return {
            "direction": direction,
            "improvement_rate": round(rate, 2),
            "delta": round(delta, 2),
            "message": msg,
            "samples": n,
            "latest_overall": recent[-1].overall,
            "latest_grade": recent[-1].grade.value,
        }
    except Exception:
        return {
            "direction": "unknown",
            "improvement_rate": 0.0,
            "message": "趋势分析异常",
        }
