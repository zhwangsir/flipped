"""M124 · 挑战性任务集测试。

Challenge Tasks = 不同类型、不同难度、不同角度的基准任务，
用于全面评估 flipped 系统的能力。

任务类型：
- code_generation: 代码生成
- bug_fix: Bug 修复
- refactoring: 重构
- ui_design: UI 设计
- debugging: 调试
- architecture: 架构设计
- optimization: 性能优化
- documentation: 文档

难度：easy / medium / hard / expert
"""
from __future__ import annotations

from driving.challenge_tasks import (
    ChallengeTask,
    TaskCategory,
    DifficultyLevel,
    ChallengeSet,
    get_task_by_id,
    get_tasks_by_category,
    get_tasks_by_difficulty,
    get_default_challenges,
)


class TestChallengeTask:
    def test_task_has_fields(self):
        t = ChallengeTask(
            id="ct-001",
            title="Build a landing page",
            category=TaskCategory.ui_design,
            difficulty=DifficultyLevel.medium,
            description="Create a SaaS landing page",
            evaluation_criteria=["design", "functionality"],
        )
        assert t.id == "ct-001"
        assert t.difficulty == DifficultyLevel.medium


class TestChallengeSet:
    def test_add_and_list_tasks(self):
        cs = ChallengeSet()
        cs.add_task(ChallengeTask(
            id="t1", title="Task 1", category=TaskCategory.code_generation,
            difficulty=DifficultyLevel.easy, description="", evaluation_criteria=[],
        ))
        cs.add_task(ChallengeTask(
            id="t2", title="Task 2", category=TaskCategory.bug_fix,
            difficulty=DifficultyLevel.hard, description="", evaluation_criteria=[],
        ))
        assert len(cs.tasks) == 2

    def test_get_by_category(self):
        cs = ChallengeSet()
        cs.add_task(ChallengeTask(
            id="t1", title="T1", category=TaskCategory.code_generation,
            difficulty=DifficultyLevel.easy, description="", evaluation_criteria=[],
        ))
        cs.add_task(ChallengeTask(
            id="t2", title="T2", category=TaskCategory.code_generation,
            difficulty=DifficultyLevel.medium, description="", evaluation_criteria=[],
        ))
        cs.add_task(ChallengeTask(
            id="t3", title="T3", category=TaskCategory.bug_fix,
            difficulty=DifficultyLevel.hard, description="", evaluation_criteria=[],
        ))
        result = cs.get_by_category(TaskCategory.code_generation)
        assert len(result) == 2

    def test_get_by_difficulty(self):
        cs = ChallengeSet()
        cs.add_task(ChallengeTask(
            id="t1", title="T1", category=TaskCategory.code_generation,
            difficulty=DifficultyLevel.easy, description="", evaluation_criteria=[],
        ))
        cs.add_task(ChallengeTask(
            id="t2", title="T2", category=TaskCategory.code_generation,
            difficulty=DifficultyLevel.hard, description="", evaluation_criteria=[],
        ))
        result = cs.get_by_difficulty(DifficultyLevel.easy)
        assert len(result) == 1

    def test_get_random_sample(self):
        cs = ChallengeSet()
        for i in range(10):
            cs.add_task(ChallengeTask(
                id=f"t{i}", title=f"T{i}",
                category=TaskCategory.code_generation,
                difficulty=DifficultyLevel.medium,
                description="", evaluation_criteria=[],
            ))
        sample = cs.get_random_sample(5)
        assert len(sample) == 5

    def test_get_stats(self):
        cs = ChallengeSet()
        cs.add_task(ChallengeTask(
            id="t1", title="T1", category=TaskCategory.code_generation,
            difficulty=DifficultyLevel.easy, description="", evaluation_criteria=[],
        ))
        cs.add_task(ChallengeTask(
            id="t2", title="T2", category=TaskCategory.bug_fix,
            difficulty=DifficultyLevel.hard, description="", evaluation_criteria=[],
        ))
        stats = cs.get_stats()
        assert stats["total_tasks"] == 2
        assert "by_category" in stats
        assert "by_difficulty" in stats


class TestHelperFunctions:
    def test_get_default_challenges(self):
        challenges = get_default_challenges()
        assert len(challenges.tasks) >= 5

    def test_get_task_by_id(self):
        challenges = get_default_challenges()
        first_id = challenges.tasks[0].id
        task = get_task_by_id(challenges, first_id)
        assert task is not None
        assert task.id == first_id

    def test_get_tasks_by_category(self):
        challenges = get_default_challenges()
        tasks = get_tasks_by_category(challenges, TaskCategory.code_generation)
        assert isinstance(tasks, list)

    def test_get_tasks_by_difficulty(self):
        challenges = get_default_challenges()
        tasks = get_tasks_by_difficulty(challenges, DifficultyLevel.medium)
        assert isinstance(tasks, list)
