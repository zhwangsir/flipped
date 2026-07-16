"""M114 · 监督引导 Agent 测试。

Supervisor Agent 负责：
- 方向引导：根据当前状态决定下一步优先做什么
- 任务优先级排序：给待办任务排优先级
- 质量把关：判断结果是否达标
- 资源分配：决定每个任务投入多少
"""
from __future__ import annotations

from driving.supervisor_agent import (
    SupervisorAgent,
    TaskCandidate,
    PriorityLevel,
    SupervisorDecision,
)


class TestTaskCandidate:
    def test_candidate_has_expected_fields(self):
        t = TaskCandidate(
            id="t1",
            title="build landing page",
            category="ui",
            impact=8,
            effort=3,
            urgency=5,
        )
        assert t.id == "t1"
        assert t.category == "ui"


class TestPriorityCalculation:
    def test_high_impact_low_effort_is_high_priority(self):
        sup = SupervisorAgent()
        tasks = [
            TaskCandidate("t1", "quick win", "infra", impact=9, effort=2, urgency=5),
            TaskCandidate("t2", "big project", "infra", impact=9, effort=9, urgency=5),
        ]
        prioritized = sup.prioritize(tasks)
        assert prioritized[0].id == "t1"

    def test_urgent_tasks_bump_up(self):
        sup = SupervisorAgent()
        tasks = [
            TaskCandidate("t1", "normal", "ui", impact=7, effort=3, urgency=3),
            TaskCandidate("t2", "urgent", "ui", impact=7, effort=3, urgency=10),
        ]
        prioritized = sup.prioritize(tasks)
        assert prioritized[0].id == "t2"

    def test_empty_tasks_returns_empty(self):
        sup = SupervisorAgent()
        assert sup.prioritize([]) == []


class TestDirectionGuidance:
    def test_suggests_next_direction(self):
        sup = SupervisorAgent()
        context = {
            "completed_tasks": ["M108", "M109", "M110"],
            "current_phase": "capability_expansion",
            "success_rate": 0.85,
        }
        direction = sup.suggest_direction(context)
        assert direction is not None
        assert "next_focus" in direction

    def test_low_success_rate_suggests_consolidation(self):
        sup = SupervisorAgent()
        context = {
            "completed_tasks": ["M108"],
            "current_phase": "expansion",
            "success_rate": 0.4,
        }
        direction = sup.suggest_direction(context)
        assert direction["next_focus"] in ("consolidation", "quality_improvement")


class TestQualityGate:
    def test_passes_quality_gate(self):
        sup = SupervisorAgent()
        result = {
            "success": True,
            "test_passed": 20,
            "test_total": 20,
            "design_score": 85,
        }
        decision = sup.quality_gate(result, threshold=0.8)
        assert decision.approved is True

    def test_fails_quality_gate(self):
        sup = SupervisorAgent()
        result = {
            "success": False,
            "test_passed": 5,
            "test_total": 20,
            "design_score": 30,
        }
        decision = sup.quality_gate(result, threshold=0.8)
        assert decision.approved is False
        assert len(decision.issues) > 0


class TestResourceAllocation:
    def test_allocates_more_for_high_priority(self):
        sup = SupervisorAgent()
        task = TaskCandidate("t1", "critical", "core", impact=10, effort=5, urgency=9)
        allocation = sup.allocate_resources(task)
        assert allocation["max_iterations"] >= 5
        assert allocation["priority_bump"] > 0

    def test_minimum_allocation_for_low_priority(self):
        sup = SupervisorAgent()
        task = TaskCandidate("t1", "nice to have", "misc", impact=3, effort=2, urgency=2)
        allocation = sup.allocate_resources(task)
        assert allocation["max_iterations"] >= 2
