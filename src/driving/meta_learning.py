"""M112 · 自我改进元循环。

系统定期回顾自己的表现，识别瓶颈，自动调优超参数。
- analyze_performance: 分析历史任务表现指标
- identify_bottlenecks: 识别性能瓶颈
- suggest_hyperparameters: 给出超参数调优建议
- run_meta_review: 一键运行完整元学习回顾

fail-open: 任何异常都返回安全默认值，不阻塞主流程。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetaLearningResult:
    """元学习回顾结果。"""
    total_tasks: int = 0
    success_rate: float = 0.0
    avg_iterations: float = 0.0
    avg_tokens: float = 0.0
    bottlenecks: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    hyperparam_suggestions: dict[str, Any] = field(default_factory=dict)
    trend: str = "stable"


def analyze_performance(history: list[dict[str, Any]]) -> MetaLearningResult:
    """分析历史任务表现，计算核心指标。"""
    try:
        if not history:
            return MetaLearningResult()

        total = len(history)
        successes = sum(1 for h in history if h.get("success", False))
        success_rate = successes / total if total > 0 else 0.0

        iters = [h.get("iterations", 0) for h in history]
        avg_iters = sum(iters) / len(iters) if iters else 0.0

        tokens = [h.get("tokens", 0) for h in history if h.get("tokens")]
        avg_tokens = sum(tokens) / len(tokens) if tokens else 0.0

        return MetaLearningResult(
            total_tasks=total,
            success_rate=round(success_rate, 3),
            avg_iterations=round(avg_iters, 2),
            avg_tokens=round(avg_tokens, 0),
        )
    except Exception:
        return MetaLearningResult()


def identify_bottlenecks(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """识别性能瓶颈。"""
    try:
        if not history:
            return []

        bottlenecks = []
        total = len(history)

        # 迭代次数瓶颈
        high_iter_count = sum(
            1 for h in history if h.get("iterations", 0) >= 5
        )
        if high_iter_count / max(1, total) > 0.3:
            bottlenecks.append({
                "type": "iteration_limit",
                "severity": "high" if high_iter_count / total > 0.5 else "medium",
                "description": f"{high_iter_count}/{total} 个任务迭代次数偏高(≥5次)",
                "impact": "token消耗大，任务耗时长",
            })

        # 失败率瓶颈
        failure_count = sum(1 for h in history if not h.get("success", False))
        if failure_count / max(1, total) > 0.2:
            bottlenecks.append({
                "type": "high_failure_rate",
                "severity": "high" if failure_count / total > 0.4 else "medium",
                "description": f"失败率 {round(failure_count/total*100, 1)}% ({failure_count}/{total})",
                "impact": "效率低，需要大量重试",
            })

        # 循环卡死瓶颈
        loop_count = sum(
            1 for h in history
            if h.get("stop_reason") in ("max_iterations", "loop_detected")
        )
        if loop_count > 0:
            bottlenecks.append({
                "type": "looping_behavior",
                "severity": "medium",
                "description": f"{loop_count} 个任务出现循环卡死",
                "impact": "浪费token，用户体验差",
            })

        return bottlenecks
    except Exception:
        return []


def suggest_hyperparameters(bottlenecks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """基于瓶颈给出超参数调优建议。"""
    try:
        suggestions = []

        for b in bottlenecks:
            btype = b.get("type", "")

            if btype == "iteration_limit":
                suggestions.append({
                    "param": "max_iterations",
                    "action": "increase",
                    "current": "默认值",
                    "suggested": "+50%",
                    "reason": "高迭代任务多，需要更多空间完成复杂任务",
                })
                suggestions.append({
                    "param": "loop_threshold",
                    "action": "increase",
                    "current": "默认值",
                    "suggested": "+1-2",
                    "reason": "避免误杀合法的多轮探索",
                })
            elif btype == "high_failure_rate":
                suggestions.append({
                    "param": "temperature",
                    "action": "decrease",
                    "current": "默认值",
                    "suggested": "0.1-0.3",
                    "reason": "降低温度减少随机性，提高稳定性",
                })
                suggestions.append({
                    "param": "incremental_mode",
                    "action": "enable_earlier",
                    "current": "第2次失败后",
                    "suggested": "第1次失败后",
                    "reason": "更早进入增量修复模式，减少全量重写风险",
                })
            elif btype == "looping_behavior":
                suggestions.append({
                    "param": "temperature_perturbation",
                    "action": "enable",
                    "current": "未启用",
                    "suggested": "循环时自动 +0.2",
                    "reason": "温度扰动打破局部最优，引入新思路",
                })
                suggestions.append({
                    "param": "adaptive_loop_detection",
                    "action": "enable",
                    "current": "未启用",
                    "suggested": "M106 自适应回路检测",
                    "reason": "根据任务复杂度动态调整循环阈值",
                })

        return suggestions
    except Exception:
        return []


def _detect_trend(history: list[dict[str, Any]]) -> str:
    """检测性能趋势（改善/稳定/恶化）。"""
    try:
        if len(history) < 6:
            return "stable"
        mid = len(history) // 2
        first_half = history[:mid]
        second_half = history[mid:]

        first_rate = sum(1 for h in first_half if h.get("success", False)) / max(1, len(first_half))
        second_rate = sum(1 for h in second_half if h.get("success", False)) / max(1, len(second_half))

        diff = second_rate - first_rate
        if diff > 0.1:
            return "improving"
        elif diff < -0.1:
            return "degrading"
        else:
            return "stable"
    except Exception:
        return "stable"


def run_meta_review(
    history: list[dict[str, Any]],
    *,
    current_params: dict[str, Any] | None = None,
) -> MetaLearningResult:
    """运行完整的元学习回顾。"""
    try:
        result = analyze_performance(history)
        bottlenecks = identify_bottlenecks(history)
        hp_suggestions = suggest_hyperparameters(bottlenecks)
        trend = _detect_trend(history)

        rec_texts = []
        for b in bottlenecks:
            rec_texts.append(f"[{b['severity'].upper()}] {b['description']} — 影响: {b['impact']}")
        for s in hp_suggestions[:5]:
            rec_texts.append(
                f"建议: {s['param']} {s['action']} ({s['suggested']}) — {s['reason']}"
            )

        result.bottlenecks = bottlenecks
        result.recommendations = rec_texts
        result.hyperparam_suggestions = {
            "suggestions": hp_suggestions,
            "current": current_params or {},
        }
        result.trend = trend

        return result
    except Exception:
        return MetaLearningResult()
