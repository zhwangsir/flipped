"""P4-4 · 质量趋势追踪。

基于 StructuredLogger 的历史日志和 TaskExecution 记录，
分析改进趋势，识别瓶颈，生成优化建议。

分析维度：
- 胜率趋势：flipped 胜率随时间变化
- 分数趋势：flipped 平均分随时间变化
- 修复成功率：auto_repair 成功率趋势
- 瓶颈维度：哪些维度持续落后
- 改进速度：每轮改进的幅度
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from driving.structured_logger import StructuredLogger, LogEntry, LogLevel


@dataclass
class TrendPoint:
    """趋势数据点。"""
    cycle: int
    timestamp: str
    flipped_score: float
    baseline_score: float
    winner: str
    success: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle,
            "timestamp": self.timestamp,
            "flipped_score": self.flipped_score,
            "baseline_score": self.baseline_score,
            "winner": self.winner,
            "success": self.success,
        }


@dataclass
class TrendAnalysis:
    """趋势分析结果。"""
    trend_direction: str  # improving / declining / stable / insufficient
    total_cycles: int
    win_rate: float
    avg_flipped_score: float
    avg_baseline_score: float
    score_trend: float  # 正=改善, 负=下降
    win_rate_trend: float
    bottleneck_dimensions: list[str]
    data_points: list[TrendPoint] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trend_direction": self.trend_direction,
            "total_cycles": self.total_cycles,
            "win_rate": round(self.win_rate, 3),
            "avg_flipped_score": round(self.avg_flipped_score, 2),
            "avg_baseline_score": round(self.avg_baseline_score, 2),
            "score_trend": round(self.score_trend, 2),
            "win_rate_trend": round(self.win_rate_trend, 3),
            "bottleneck_dimensions": self.bottleneck_dimensions,
            "data_points": [p.to_dict() for p in self.data_points],
            "recommendations": self.recommendations,
        }


def analyze_trend(executions: list[Any]) -> TrendAnalysis:
    """从 TaskExecution 列表分析趋势。

    Args:
        executions: UnmannedLoop.executions 列表
    """
    if not executions:
        return TrendAnalysis(
            trend_direction="insufficient",
            total_cycles=0,
            win_rate=0.0,
            avg_flipped_score=0.0,
            avg_baseline_score=0.0,
            score_trend=0.0,
            win_rate_trend=0.0,
            bottleneck_dimensions=[],
        )

    points: list[TrendPoint] = []
    for i, exec_record in enumerate(executions):
        comp = exec_record.comparison
        if comp is None:
            continue
        points.append(TrendPoint(
            cycle=i + 1,
            timestamp=exec_record.timestamp,
            flipped_score=comp.flipped_score,
            baseline_score=comp.baseline_score,
            winner=comp.winner,
            success=exec_record.success,
        ))

    if not points:
        return TrendAnalysis(
            trend_direction="insufficient",
            total_cycles=len(executions),
            win_rate=0.0,
            avg_flipped_score=0.0,
            avg_baseline_score=0.0,
            score_trend=0.0,
            win_rate_trend=0.0,
            bottleneck_dimensions=[],
        )

    total = len(points)
    wins = sum(1 for p in points if p.winner == "flipped")
    win_rate = wins / total

    avg_flipped = sum(p.flipped_score for p in points) / total
    avg_baseline = sum(p.baseline_score for p in points) / total

    # 分数趋势：后半段 vs 前半段
    mid = max(1, total // 2)
    first_half = points[:mid]
    second_half = points[mid:]
    first_avg = sum(p.flipped_score for p in first_half) / max(1, len(first_half))
    second_avg = sum(p.flipped_score for p in second_half) / max(1, len(second_half))
    score_trend = second_avg - first_avg

    first_wins = sum(1 for p in first_half if p.winner == "flipped")
    second_wins = sum(1 for p in second_half if p.winner == "flipped")
    first_rate = first_wins / max(1, len(first_half))
    second_rate = second_wins / max(1, len(second_half))
    win_rate_trend = second_rate - first_rate

    # 瓶颈维度：持续落后的维度
    dim_losses: dict[str, int] = {}
    for p in points:
        exec_record = executions[p.cycle - 1]
        comp = exec_record.comparison
        if comp:
            for dim in comp.baseline_won_dimensions:
                dim_losses[dim] = dim_losses.get(dim, 0) + 1

    bottleneck_dimensions = sorted(dim_losses, key=dim_losses.get, reverse=True)[:3]

    # 趋势方向
    if score_trend > 2 and win_rate_trend > 0:
        trend_direction = "improving"
    elif score_trend < -2 and win_rate_trend < 0:
        trend_direction = "declining"
    else:
        trend_direction = "stable"

    # 建议
    recommendations: list[str] = []
    if trend_direction == "declining":
        recommendations.append("System is declining - consider rolling back recent changes")
    if bottleneck_dimensions:
        recommendations.append(f"Focus on improving: {', '.join(bottleneck_dimensions)}")
    if win_rate < 0.3:
        recommendations.append("Win rate is critically low - review execution strategy")
    if score_trend > 5:
        recommendations.append("Strong improvement trend - continue current approach")
    if not recommendations:
        recommendations.append("System is stable - maintain current course")

    return TrendAnalysis(
        trend_direction=trend_direction,
        total_cycles=total,
        win_rate=win_rate,
        avg_flipped_score=avg_flipped,
        avg_baseline_score=avg_baseline,
        score_trend=score_trend,
        win_rate_trend=win_rate_trend,
        bottleneck_dimensions=bottleneck_dimensions,
        data_points=points,
        recommendations=recommendations,
    )


def analyze_logger_entries(logger: StructuredLogger) -> dict[str, Any]:
    """从 StructuredLogger 的日志条目中提取统计信息。"""
    try:
        entries = logger.entries
        total = len(entries)
        if total == 0:
            return {"total_entries": 0}

        by_level: dict[str, int] = {}
        by_event: dict[str, int] = {}
        for e in entries:
            by_level[e.level] = by_level.get(e.level, 0) + 1
            by_event[e.event] = by_event.get(e.event, 0) + 1

        errors = [e for e in entries if e.level in ("ERROR", "FATAL")]
        warnings = [e for e in entries if e.level == "WARN"]

        return {
            "total_entries": total,
            "by_level": by_level,
            "by_event": by_event,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "top_events": sorted(by_event.items(), key=lambda x: x[1], reverse=True)[:5],
        }
    except Exception:
        return {"total_entries": len(logger.entries), "error": "analysis failed"}
