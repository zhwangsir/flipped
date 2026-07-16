"""M122 · 质量对比评估系统。

对比两组产出（flipped vs 基准/监督者），多维度评分，判定胜负，分析差距。

对比维度：
- correctness: 正确性（功能是否正确）
- completeness: 完整度（是否覆盖所有需求）
- code_quality: 代码质量（可读性/可维护性/最佳实践）
- design: 设计质量（架构/美学/体验）
- efficiency: 效率（token数/迭代次数/耗时）
- creativity: 创造性（思路/方案新颖度）

fail-open: 异常时返回 tie 或保守估计。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from driving.errors import ConfigurationError, ComparisonError


class ComparisonDimension(str, Enum):
    correctness = "correctness"
    completeness = "completeness"
    code_quality = "code_quality"
    design = "design"
    efficiency = "efficiency"
    creativity = "creativity"
    maintainability = "maintainability"
    scalability = "scalability"


DEFAULT_WEIGHTS: dict[str, float] = {
    "correctness": 0.25,
    "completeness": 0.20,
    "code_quality": 0.20,
    "design": 0.15,
    "efficiency": 0.10,
    "creativity": 0.10,
}


@dataclass
class ComparisonConfig:
    """对比评估配置。"""
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    default_score: float | None = None
    score_range: tuple[float, float] = (0.0, 100.0)
    win_margin: float = 1.0

    def __post_init__(self) -> None:
        lo, hi = self.score_range
        if not (0 <= lo < hi <= 1000):
            raise ConfigurationError(
                f"score_range must satisfy 0 <= lo < hi <= 1000, got {self.score_range}",
                context={"score_range": list(self.score_range)},
            )
        if self.win_margin < 0:
            raise ConfigurationError(
                f"win_margin must be non-negative, got {self.win_margin}",
                context={"win_margin": self.win_margin},
            )
        invalid = [k for k, v in self.weights.items() if v < 0]
        if invalid:
            raise ConfigurationError(
                f"weights must be non-negative, invalid keys: {invalid}",
                context={"invalid_keys": invalid},
            )


@dataclass
class ComparisonResult:
    """单次对比结果。"""
    winner: str
    flipped_score: float
    baseline_score: float
    score_delta: float
    dimension_details: dict[str, dict[str, Any]] = field(default_factory=dict)
    flipped_won_dimensions: list[str] = field(default_factory=list)
    baseline_won_dimensions: list[str] = field(default_factory=list)
    tied_dimensions: list[str] = field(default_factory=list)
    task_type: str = ""
    task_difficulty: str = "medium"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "winner": self.winner,
            "flipped_score": self.flipped_score,
            "baseline_score": self.baseline_score,
            "score_delta": self.score_delta,
            "dimension_details": self.dimension_details,
            "flipped_won_dimensions": self.flipped_won_dimensions,
            "baseline_won_dimensions": self.baseline_won_dimensions,
            "tied_dimensions": self.tied_dimensions,
            "task_type": self.task_type,
            "task_difficulty": self.task_difficulty,
            "metadata": self.metadata,
        }


@dataclass
class QualityComparison:
    """质量对比管理器。"""
    results: list[ComparisonResult] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    def add_result(self, result: ComparisonResult) -> None:
        """添加一次对比结果。"""
        try:
            self.results.append(result)
        except Exception:
            pass

    def get_stats(self) -> dict[str, Any]:
        """获取统计数据。"""
        try:
            if not self.results:
                return {
                    "total_comparisons": 0,
                    "flipped_wins": 0,
                    "baseline_wins": 0,
                    "ties": 0,
                    "win_rate": 0.0,
                    "avg_score_delta": 0.0,
                }

            total = len(self.results)
            flipped_wins = sum(1 for r in self.results if r.winner == "flipped")
            baseline_wins = sum(1 for r in self.results if r.winner == "baseline")
            ties = sum(1 for r in self.results if r.winner == "tie")
            win_rate = flipped_wins / total if total > 0 else 0.0
            avg_delta = sum(r.score_delta for r in self.results) / total

            by_dimension: dict[str, dict[str, int]] = {}
            for r in self.results:
                for dim, details in r.dimension_details.items():
                    if dim not in by_dimension:
                        by_dimension[dim] = {"flipped_wins": 0, "baseline_wins": 0, "ties": 0}
                    if details.get("flipped_wins"):
                        by_dimension[dim]["flipped_wins"] += 1
                    elif details.get("baseline_wins"):
                        by_dimension[dim]["baseline_wins"] += 1
                    else:
                        by_dimension[dim]["ties"] += 1

            return {
                "total_comparisons": total,
                "flipped_wins": flipped_wins,
                "baseline_wins": baseline_wins,
                "ties": ties,
                "win_rate": round(win_rate, 3),
                "avg_score_delta": round(avg_delta, 2),
                "by_dimension": by_dimension,
            }
        except Exception:
            return {
                "total_comparisons": len(self.results),
                "flipped_wins": 0,
                "baseline_wins": 0,
                "ties": 0,
                "win_rate": 0.0,
                "avg_score_delta": 0.0,
            }

    def get_trend(self, window: int = 5) -> dict[str, Any]:
        """获取近期趋势。"""
        try:
            if len(self.results) < 3:
                return {"trend": "insufficient_data", "recent_win_rate": 0.0}

            recent = self.results[-window:]
            recent_wins = sum(1 for r in recent if r.winner == "flipped")
            recent_rate = recent_wins / len(recent)

            earlier = self.results[:-window] if len(self.results) > window else []
            if earlier:
                earlier_wins = sum(1 for r in earlier if r.winner == "flipped")
                earlier_rate = earlier_wins / len(earlier)
                delta = recent_rate - earlier_rate
            else:
                delta = 0.0
                earlier_rate = 0.0

            if delta > 0.1:
                trend = "improving"
            elif delta < -0.1:
                trend = "declining"
            else:
                trend = "stable"

            return {
                "trend": trend,
                "recent_win_rate": round(recent_rate, 3),
                "earlier_win_rate": round(earlier_rate, 3),
                "rate_delta": round(delta, 3),
                "window_size": len(recent),
            }
        except Exception:
            return {"trend": "error", "recent_win_rate": 0.0}


def compare_outputs(
    flipped_output: dict[str, Any],
    baseline_output: dict[str, Any],
    dimensions: list[str],
    *,
    config: ComparisonConfig | None = None,
    weights: dict[str, float] | None = None,
    default_score: float | None = None,
    task_type: str = "",
    task_difficulty: str = "medium",
) -> ComparisonResult:
    """对比两组产出的质量。

    每个维度 0-100 分，加权求和。

    Args:
        config: ComparisonConfig 配置对象。若提供，weights/default_score/win_margin 从中读取。
        weights: 自定义权重（当 config 为 None 时生效）。
        default_score: 当维度缺失时的默认得分（当 config 为 None 时生效）。
            None（默认）= fail-fast，缺失时抛出 ValueError。
            float = 使用该值作为默认值。
    """
    if not dimensions:
        raise ComparisonError("dimensions must not be empty")
    if not isinstance(flipped_output, dict):
        raise ComparisonError("flipped_output must be a dict")
    if not isinstance(baseline_output, dict):
        raise ComparisonError("baseline_output must be a dict")

    cfg = config or ComparisonConfig()
    w = weights or cfg.weights or {d: DEFAULT_WEIGHTS.get(d, 0.1) for d in dimensions}
    ds = default_score if default_score is not None else cfg.default_score
    margin = cfg.win_margin

    invalid_weights = [dim for dim, weight in w.items() if weight < 0]
    if invalid_weights:
        raise ComparisonError(
            f"weights must be non-negative, invalid: {invalid_weights}",
            context={"invalid_dims": invalid_weights},
        )

    total_weight_explicit = sum(w.get(d, 0) for d in dimensions)
    if total_weight_explicit == 0:
        raise ComparisonError(
            "total weight for given dimensions must not be zero",
            context={"dimensions": dimensions},
        )

    dimension_details: dict[str, dict[str, Any]] = {}
    flipped_won: list[str] = []
    baseline_won: list[str] = []
    tied: list[str] = []

    flipped_total = 0.0
    baseline_total = 0.0
    total_weight = 0.0

    for dim in dimensions:
        if ds is None:
            if dim not in flipped_output:
                raise ComparisonError(
                    f"dimension '{dim}' missing from flipped_output",
                    context={"dimension": dim, "source": "flipped"},
                )
            if dim not in baseline_output:
                raise ComparisonError(
                    f"dimension '{dim}' missing from baseline_output",
                    context={"dimension": dim, "source": "baseline"},
                )
            f_score = float(flipped_output[dim])
            b_score = float(baseline_output[dim])
        else:
            f_score = float(flipped_output.get(dim, ds))
            b_score = float(baseline_output.get(dim, ds))

        weight = w.get(dim, 0.1)

        flipped_total += f_score * weight
        baseline_total += b_score * weight
        total_weight += weight

        f_wins = f_score > b_score + margin
        b_wins = b_score > f_score + margin

        if f_wins:
            flipped_won.append(dim)
        elif b_wins:
            baseline_won.append(dim)
        else:
            tied.append(dim)

        dimension_details[dim] = {
            "flipped_score": f_score,
            "baseline_score": b_score,
            "delta": round(f_score - b_score, 2),
            "flipped_wins": f_wins,
            "baseline_wins": b_wins,
            "weight": weight,
        }

    f_final = round(flipped_total / total_weight, 2)
    b_final = round(baseline_total / total_weight, 2)
    delta = round(f_final - b_final, 2)

    if f_final > b_final + margin:
        winner = "flipped"
    elif b_final > f_final + margin:
        winner = "baseline"
    else:
        winner = "tie"

    return ComparisonResult(
        winner=winner,
        flipped_score=f_final,
        baseline_score=b_final,
        score_delta=delta,
        dimension_details=dimension_details,
        flipped_won_dimensions=flipped_won,
        baseline_won_dimensions=baseline_won,
        tied_dimensions=tied,
        task_type=task_type,
        task_difficulty=task_difficulty,
    )


def calculate_gap(result: ComparisonResult) -> dict[str, Any]:
    """计算差距分析：最弱项、最强项、改进优先级。

    >>> from driving.quality_comparison import compare_outputs, calculate_gap
    >>> r = compare_outputs(
    ...     {"correctness": 90, "design": 60},
    ...     {"correctness": 80, "design": 85},
    ...     ["correctness", "design"],
    ... )
    >>> g = calculate_gap(r)
    >>> g["weakest_dimension"]
    'design'
    >>> g["strongest_dimension"]
    'correctness'
    """
    try:
        if not result.dimension_details:
            return {"overall_gap": result.score_delta}

        deltas = {
            dim: details["delta"]
            for dim, details in result.dimension_details.items()
        }

        weakest = min(deltas, key=deltas.get) if deltas else ""
        strongest = max(deltas, key=deltas.get) if deltas else ""

        improvement_priority = sorted(
            deltas.items(),
            key=lambda x: x[1],
        )

        return {
            "overall_gap": result.score_delta,
            "weakest_dimension": weakest,
            "weakest_delta": deltas.get(weakest, 0),
            "strongest_dimension": strongest,
            "strongest_delta": deltas.get(strongest, 0),
            "improvement_priority": [
                {"dimension": dim, "delta": delta, "gap_to_close": max(0, -delta)}
                for dim, delta in improvement_priority
                if delta < 0
            ],
            "dimensions_ahead": [dim for dim, d in deltas.items() if d > 0],
            "dimensions_behind": [dim for dim, d in deltas.items() if d < 0],
        }
    except Exception:
        return {"overall_gap": result.score_delta, "error": "gap calculation failed"}
