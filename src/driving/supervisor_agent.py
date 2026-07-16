"""M114 · 监督引导 Agent。

Supervisor Agent = 系统的"产品经理+技术总监"，负责：
- 方向引导：根据当前状态决定下一步优先做什么
- 任务优先级排序：给待办任务排优先级（impact/effort/urgency 加权）
- 质量把关：判断结果是否达标
- 资源分配：决定每个任务投入多少

fail-open: 任何异常都返回保守默认决策。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PriorityLevel(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


@dataclass
class TaskCandidate:
    """待办任务候选。"""
    id: str
    title: str
    category: str
    impact: int = 5
    effort: int = 5
    urgency: int = 5
    dependencies: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SupervisorDecision:
    """监督者决策。"""
    approved: bool
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    confidence: float = 0.5
    next_action: str = "proceed"


@dataclass
class SupervisorAgent:
    """监督引导 Agent。

    负责方向引导、任务排序、质量把关、资源分配。
    """
    default_threshold: float = 0.8
    max_default_iterations: int = 5

    def prioritize(
        self,
        tasks: list[TaskCandidate],
        *,
        weights: dict[str, float] | None = None,
    ) -> list[TaskCandidate]:
        """给任务排序，返回按优先级从高到低的列表。

        评分公式: score = impact * w_i + urgency * w_u - effort * w_e
        默认权重: impact 0.4, urgency 0.3, effort 0.3（越大越靠前=减分）
        """
        try:
            if not tasks:
                return []

            w = weights or {"impact": 0.4, "urgency": 0.3, "effort": 0.3}

            scored = []
            for t in tasks:
                score = (
                    t.impact * w.get("impact", 0.4)
                    + t.urgency * w.get("urgency", 0.3)
                    - t.effort * w.get("effort", 0.3)
                )
                scored.append((score, t))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [t for _, t in scored]
        except Exception:
            return tasks

    def suggest_direction(self, context: dict[str, Any]) -> dict[str, Any]:
        """根据当前状态建议下一步方向。"""
        try:
            success_rate = context.get("success_rate", 0.7)
            completed = context.get("completed_tasks", [])
            phase = context.get("current_phase", "exploration")

            result: dict[str, Any] = {
                "next_focus": "capability_expansion",
                "reasoning": "",
                "suggested_tasks": [],
                "warnings": [],
            }

            if success_rate < 0.5:
                result["next_focus"] = "consolidation"
                result["reasoning"] = "成功率偏低，先巩固质量再扩展"
                result["suggested_tasks"] = [
                    "修复已知失败模式",
                    "加固稳定性",
                    "增加测试覆盖",
                ]
                result["warnings"].append("低成功率警告：扩展前先稳基础")
                return result

            if success_rate < 0.7:
                result["next_focus"] = "quality_improvement"
                result["reasoning"] = "成功率中等，质量和功能并行推进"
                result["suggested_tasks"] = [
                    "提升核心模块稳定性",
                    "渐进式新增功能",
                    "加强验证强度",
                ]
                return result

            if len(completed) < 3:
                result["next_focus"] = "foundation_building"
                result["reasoning"] = "早期阶段，优先打基础能力"
                result["suggested_tasks"] = [
                    "核心能力建设",
                    "基础设施搭建",
                    "测试体系建立",
                ]
                return result

            result["reasoning"] = "状态良好，可加速扩展能力版图"
            result["suggested_tasks"] = [
                "新能力探索",
                "效率优化",
                "体验提升",
            ]
            return result
        except Exception:
            return {
                "next_focus": "conservative_proceed",
                "reasoning": "评估异常，保守推进",
                "suggested_tasks": ["小步验证"],
                "warnings": ["监督者异常，降级为保守模式"],
            }

    def quality_gate(
        self,
        result: dict[str, Any],
        *,
        threshold: float | None = None,
    ) -> SupervisorDecision:
        """质量把关：判断结果是否达标。"""
        try:
            thresh = threshold if threshold is not None else self.default_threshold
            issues: list[str] = []
            suggestions: list[str] = []
            score = 0.0
            factors = 0

            if result.get("success") is True:
                score += 0.4
            else:
                issues.append("任务未成功完成")
                suggestions.append("先修复核心失败原因")
            factors += 0.4

            if "test_passed" in result and "test_total" in result:
                total = max(1, result["test_total"])
                pass_rate = result["test_passed"] / total
                score += pass_rate * 0.3
                if pass_rate < thresh:
                    issues.append(f"测试通过率 {pass_rate:.1%} 低于阈值 {thresh:.0%}")
                    suggestions.append("修复失败的测试用例")
            else:
                score += 0.3
            factors += 0.3

            if "design_score" in result:
                ds = result["design_score"] / 100.0
                score += ds * 0.2
                if ds < 0.6:
                    issues.append(f"设计质量 {result['design_score']} 分偏低")
                    suggestions.append("优化设计质量")
            else:
                score += 0.2
            factors += 0.2

            if "iterations" in result:
                iters = result["iterations"]
                if iters <= 2:
                    score += 0.1
                elif iters <= 5:
                    score += 0.07
                else:
                    score += 0.03
                    suggestions.append("考虑优化减少迭代次数")
            else:
                score += 0.05
            factors += 0.1

            normalized = score / max(0.1, factors)
            approved = normalized >= thresh

            return SupervisorDecision(
                approved=approved,
                issues=issues,
                suggestions=suggestions,
                confidence=round(normalized, 3),
                next_action="proceed" if approved else "revise",
            )
        except Exception:
            return SupervisorDecision(
                approved=False,
                issues=["质量把关异常"],
                suggestions=["人工审核"],
                confidence=0.0,
                next_action="manual_review",
            )

    def allocate_resources(self, task: TaskCandidate) -> dict[str, Any]:
        """根据任务优先级分配资源。"""
        try:
            score = task.impact + task.urgency - task.effort * 0.5

            if score >= 12:
                return {
                    "max_iterations": max(8, self.max_default_iterations + 3),
                    "priority_bump": 3,
                    "parallel_workers": 2,
                    "quality_bar": "high",
                }
            elif score >= 7:
                return {
                    "max_iterations": self.max_default_iterations,
                    "priority_bump": 1,
                    "parallel_workers": 1,
                    "quality_bar": "standard",
                }
            else:
                return {
                    "max_iterations": max(2, self.max_default_iterations - 2),
                    "priority_bump": 0,
                    "parallel_workers": 1,
                    "quality_bar": "basic",
                }
        except Exception:
            return {
                "max_iterations": self.max_default_iterations,
                "priority_bump": 0,
                "parallel_workers": 1,
                "quality_bar": "standard",
            }
