"""P5 · 联网知识预检端到端集成测试。"""
from __future__ import annotations

from driving.unmanned_loop import (
    UnmannedLoop,
    BudgetTracker,
    CircuitBreaker,
)
from driving.challenge_tasks import (
    ChallengeSet,
    ChallengeTask,
    TaskCategory,
    DifficultyLevel,
)
from driving.knowledge_preflight import KnowledgePreflight, KnowledgeCache


def _mock_search_fn(query, max_results):
    """模拟搜索函数。"""
    return [
        {"title": f"Latest guide for {query}", "url": "http://example.com/guide", "snippet": "Comprehensive guide"},
        {"title": f"Best practices {query}", "url": "http://best.com/practices", "snippet": "Industry best practices"},
    ]


class TestE2EKnowledgePreflight:
    """端到端：联网知识预检 → 任务执行 → 质量对比。"""

    def test_preflight_runs_before_execution(self):
        """验证知识预检在任务执行前运行。"""
        loop = UnmannedLoop()
        loop.knowledge_preflight = KnowledgePreflight(search_fn=_mock_search_fn)
        loop.challenge_set = ChallengeSet()
        loop.challenge_set.add_task(ChallengeTask(
            id="kp-001",
            title="Build React Component",
            category=TaskCategory.code_generation,
            difficulty=DifficultyLevel.easy,
            description="Create a reusable React component",
            evaluation_criteria=["correctness"],
        ))

        execution = loop.run_one()
        assert execution.knowledge_preflight_done is True
        assert execution.knowledge_context is not None
        assert len(execution.knowledge_context.results) > 0
        assert len(execution.knowledge_context.queries) >= 1

    def test_preflight_cached_on_second_run(self):
        """第二次执行相同任务时，知识预检使用缓存。"""
        loop = UnmannedLoop()
        loop.knowledge_preflight = KnowledgePreflight(search_fn=_mock_search_fn)
        loop.challenge_set = ChallengeSet()
        loop.challenge_set.add_task(ChallengeTask(
            id="kp-002",
            title="Build React Component",
            category=TaskCategory.code_generation,
            difficulty=DifficultyLevel.easy,
            description="Create a reusable React component",
            evaluation_criteria=[],
        ))

        # 第一次执行 — 实际搜索
        exec1 = loop.run_one()
        assert exec1.knowledge_context.cached is False

        # 第二次执行 — 应使用缓存
        # 重置 circuit breaker 以允许重选
        loop.circuit_breaker.record_success("kp-002")
        exec2 = loop.run_one()
        assert exec2.knowledge_context.cached is True

    def test_preflight_fail_open(self):
        """搜索失败时不阻塞任务执行。"""
        def failing_search(query, max_results):
            raise ConnectionError("network down")

        loop = UnmannedLoop()
        loop.knowledge_preflight = KnowledgePreflight(search_fn=failing_search)
        loop.challenge_set = ChallengeSet()
        loop.challenge_set.add_task(ChallengeTask(
            id="kp-003",
            title="Test Task",
            category=TaskCategory.code_generation,
            difficulty=DifficultyLevel.easy,
            description="test",
            evaluation_criteria=[],
        ))
        loop.execute_fn = lambda t: {"correctness": 100, "design": 95}
        loop.baseline_fn = lambda t: {"correctness": 70, "design": 65}

        execution = loop.run_one()
        # 知识预检完成但无结果
        assert execution.knowledge_preflight_done is True
        assert len(execution.knowledge_context.results) == 0
        # 任务仍然正常执行
        assert execution.success is True

    def test_preflight_without_preflight_engine(self):
        """未配置 knowledge_preflight 时，任务正常执行。"""
        loop = UnmannedLoop()
        loop.knowledge_preflight = None
        loop.challenge_set = ChallengeSet()
        loop.challenge_set.add_task(ChallengeTask(
            id="kp-004",
            title="Test",
            category=TaskCategory.code_generation,
            difficulty=DifficultyLevel.easy,
            description="test",
            evaluation_criteria=[],
        ))

        execution = loop.run_one()
        assert execution.knowledge_preflight_done is False
        assert execution.knowledge_context is None

    def test_stats_include_preflight_info(self):
        """统计信息包含知识预检数据。"""
        loop = UnmannedLoop()
        loop.knowledge_preflight = KnowledgePreflight(search_fn=_mock_search_fn)
        loop.challenge_set = ChallengeSet()
        loop.challenge_set.add_task(ChallengeTask(
            id="kp-005",
            title="Test Stats",
            category=TaskCategory.code_generation,
            difficulty=DifficultyLevel.easy,
            description="test stats",
            evaluation_criteria=[],
        ))

        loop.run_one()
        stats = loop.get_stats()
        assert "knowledge_preflight" in stats
        assert stats["knowledge_preflight"]["preflight_count"] == 1
        assert stats["knowledge_preflight"]["total_results"] > 0
        assert stats["knowledge_preflight"]["cache_stats"] is not None

    def test_full_loop_with_preflight(self):
        """完整循环带联网预检。"""
        loop = UnmannedLoop()
        loop.knowledge_preflight = KnowledgePreflight(search_fn=_mock_search_fn)
        loop.budget = BudgetTracker(max_iterations=3, max_errors=3)

        result = loop.run(max_cycles=3)
        assert result["total_executions"] >= 1
        assert result["knowledge_preflight"]["preflight_count"] >= 1

    def test_preflight_knowledge_in_execution_record(self):
        """执行记录中包含知识预检的完整上下文。"""
        loop = UnmannedLoop()
        loop.knowledge_preflight = KnowledgePreflight(search_fn=_mock_search_fn)
        loop.challenge_set = ChallengeSet()
        loop.challenge_set.add_task(ChallengeTask(
            id="kp-006",
            title="Design Landing Page",
            category=TaskCategory.ui_design,
            difficulty=DifficultyLevel.medium,
            description="Design a modern landing page",
            evaluation_criteria=["design"],
        ))

        execution = loop.run_one()
        d = execution.to_dict()
        assert d["knowledge_preflight_done"] is True
        assert d["knowledge_results_count"] > 0
