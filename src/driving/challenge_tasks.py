"""M124 · 挑战性任务集。

Challenge Tasks = 不同类型、不同难度、不同角度的基准任务，
用于全面、多角度评估 flipped 系统的能力。

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

fail-open: 异常时返回空列表或默认集合。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskCategory(str, Enum):
    code_generation = "code_generation"
    bug_fix = "bug_fix"
    refactoring = "refactoring"
    ui_design = "ui_design"
    debugging = "debugging"
    architecture = "architecture"
    optimization = "optimization"
    documentation = "documentation"
    testing = "testing"
    integration = "integration"


class DifficultyLevel(str, Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"
    expert = "expert"


@dataclass
class ChallengeTask:
    """挑战性任务。"""
    id: str
    title: str
    category: TaskCategory
    difficulty: DifficultyLevel
    description: str
    evaluation_criteria: list[str]
    hints: list[str] = field(default_factory=list)
    expected_output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def difficulty_score(self) -> int:
        return {
            DifficultyLevel.easy: 1,
            DifficultyLevel.medium: 2,
            DifficultyLevel.hard: 3,
            DifficultyLevel.expert: 4,
        }.get(self.difficulty, 2)


@dataclass
class ChallengeSet:
    """任务集。"""
    tasks: list[ChallengeTask] = field(default_factory=list)
    name: str = "default"

    def add_task(self, task: ChallengeTask) -> None:
        """添加任务。"""
        try:
            self.tasks.append(task)
        except Exception:
            pass

    def get_by_category(self, category: TaskCategory) -> list[ChallengeTask]:
        """按分类获取任务。"""
        try:
            return [t for t in self.tasks if t.category == category]
        except Exception:
            return []

    def get_by_difficulty(self, difficulty: DifficultyLevel) -> list[ChallengeTask]:
        """按难度获取任务。"""
        try:
            return [t for t in self.tasks if t.difficulty == difficulty]
        except Exception:
            return []

    def get_random_sample(
        self,
        count: int,
        *,
        categories: list[TaskCategory] | None = None,
        difficulties: list[DifficultyLevel] | None = None,
    ) -> list[ChallengeTask]:
        """随机抽取任务样本。"""
        try:
            pool = self.tasks
            if categories:
                pool = [t for t in pool if t.category in categories]
            if difficulties:
                pool = [t for t in pool if t.difficulty in difficulties]
            if len(pool) <= count:
                return list(pool)
            return random.sample(pool, count)
        except Exception:
            return []

    def get_stats(self) -> dict[str, Any]:
        """获取任务集统计。"""
        try:
            by_category: dict[str, int] = {}
            by_difficulty: dict[str, int] = {}
            for t in self.tasks:
                cat = t.category.value
                by_category[cat] = by_category.get(cat, 0) + 1
                diff = t.difficulty.value
                by_difficulty[diff] = by_difficulty.get(diff, 0) + 1
            return {
                "total_tasks": len(self.tasks),
                "by_category": by_category,
                "by_difficulty": by_difficulty,
                "avg_difficulty": (
                    round(sum(t.difficulty_score for t in self.tasks) / max(1, len(self.tasks)), 2)
                ),
            }
        except Exception:
            return {"total_tasks": len(self.tasks)}


def get_default_challenges() -> ChallengeSet:
    """获取默认挑战性任务集。"""
    try:
        cs = ChallengeSet(name="default_suite")

        tasks = [
            ChallengeTask(
                id="cg-easy-001",
                title="生成一个按钮组件",
                category=TaskCategory.code_generation,
                difficulty=DifficultyLevel.easy,
                description="创建一个可复用的 HTML/CSS 按钮组件，支持多种状态",
                evaluation_criteria=["correctness", "code_quality", "design"],
            ),
            ChallengeTask(
                id="cg-medium-001",
                title="构建 SaaS 落地页",
                category=TaskCategory.code_generation,
                difficulty=DifficultyLevel.medium,
                description="创建一个现代化的 SaaS 产品落地页，包含 Hero、特性、定价、FAQ 等板块",
                evaluation_criteria=["design", "completeness", "code_quality", "creativity"],
            ),
            ChallengeTask(
                id="cg-hard-001",
                title="全栈仪表盘应用",
                category=TaskCategory.code_generation,
                difficulty=DifficultyLevel.hard,
                description="构建一个数据可视化仪表盘，包含图表、表格、筛选器、用户认证",
                evaluation_criteria=["architecture", "correctness", "design", "performance"],
            ),
            ChallengeTask(
                id="bf-medium-001",
                title="修复表单验证 Bug",
                category=TaskCategory.bug_fix,
                difficulty=DifficultyLevel.medium,
                description="定位并修复表单提交时验证逻辑失效的问题",
                evaluation_criteria=["correctness", "debugging", "code_quality"],
            ),
            ChallengeTask(
                id="bf-hard-001",
                title="定位内存泄漏",
                category=TaskCategory.bug_fix,
                difficulty=DifficultyLevel.hard,
                description="找出并修复长期运行后的内存泄漏问题",
                evaluation_criteria=["debugging", "correctness", "performance"],
            ),
            ChallengeTask(
                id="ref-medium-001",
                title="重构大型函数",
                category=TaskCategory.refactoring,
                difficulty=DifficultyLevel.medium,
                description="将一个 500 行的巨型函数重构为模块化的清晰结构",
                evaluation_criteria=["code_quality", "maintainability", "correctness"],
            ),
            ChallengeTask(
                id="ui-medium-001",
                title="设计数据可视化页面",
                category=TaskCategory.ui_design,
                difficulty=DifficultyLevel.medium,
                description="设计一个展示业务关键指标的数据可视化页面",
                evaluation_criteria=["design", "creativity", "completeness"],
            ),
            ChallengeTask(
                id="arch-hard-001",
                title="微服务架构设计",
                category=TaskCategory.architecture,
                difficulty=DifficultyLevel.hard,
                description="设计一个高并发电商系统的微服务架构方案",
                evaluation_criteria=["architecture", "scalability", "correctness"],
            ),
            ChallengeTask(
                id="opt-medium-001",
                title="优化页面加载速度",
                category=TaskCategory.optimization,
                difficulty=DifficultyLevel.medium,
                description="将一个慢加载的首屏性能提升 50% 以上",
                evaluation_criteria=["performance", "correctness", "code_quality"],
            ),
            ChallengeTask(
                id="doc-easy-001",
                title="编写 API 文档",
                category=TaskCategory.documentation,
                difficulty=DifficultyLevel.easy,
                description="为一组 REST API 编写清晰的文档",
                evaluation_criteria=["completeness", "correctness", "code_quality"],
            ),
        ]

        for t in tasks:
            cs.add_task(t)

        return cs
    except Exception:
        return ChallengeSet()


def get_task_by_id(cs: ChallengeSet, task_id: str) -> ChallengeTask | None:
    """按 ID 获取任务。"""
    try:
        for t in cs.tasks:
            if t.id == task_id:
                return t
        return None
    except Exception:
        return None


def get_tasks_by_category(cs: ChallengeSet, category: TaskCategory) -> list[ChallengeTask]:
    """按分类获取任务（便捷函数）。"""
    return cs.get_by_category(category)


def get_tasks_by_difficulty(cs: ChallengeSet, difficulty: DifficultyLevel) -> list[ChallengeTask]:
    """按难度获取任务（便捷函数）。"""
    return cs.get_by_difficulty(difficulty)
