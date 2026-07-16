"""M104 · Skill 进化系统测试。

Skill 不只是存和取，还要有质量评估、自动淘汰、组合应用。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from driving.skill_registry import Skill, save_skill, list_skills
from driving.skill_evolution import (
    compute_skill_quality,
    archive_low_quality_skills,
    find_related_skills,
    apply_skills_to_state,
    record_skill_usage,
    SkillQuality,
    MIN_USES_FOR_QUALITY,
    LOW_QUALITY_THRESHOLD,
)
from driving.factory_loop import FactoryState, FactoryTask, TaskResult


def _make_state(tmp_path, style="auto"):
    from driving.factory_loop import FactoryStatus
    return FactoryState(
        factory_id="test-factory",
        product_goal="测试",
        cwd=str(tmp_path),
        status=FactoryStatus.running,
        roadmap=[],
        max_tasks=5,
        max_rounds=2,
        design_style=style,
        design_context='{"style":"auto"}',
    )


def _save_skill(db, desc, style="film_atelier", success=True, count=1):
    state = _make_state(Path(db).parent, style)
    task = FactoryTask(id="t1", description=desc, verify_cmd=["true"], status="done")
    result = TaskResult(task=task, verified=success, stop_reason="verified", iteration=1, summary="ok")
    for _ in range(count):
        save_skill(task, state, result, db_path=db)


class TestComputeSkillQuality:
    def test_high_success_rate_is_high_quality(self):
        skill = Skill(
            skill_id="s1", product_type="web", design_style="dark",
            description="test", verify_cmd=["true"],
            success_count=9, total_uses=10, avg_iterations=1.5,
        )
        q = compute_skill_quality(skill)
        assert q.quality_level == "high"
        assert q.success_rate == 0.9
        assert q.score > 0.7

    def test_low_success_rate_is_low_quality(self):
        skill = Skill(
            skill_id="s2", product_type="web", design_style="dark",
            description="test", verify_cmd=["true"],
            success_count=1, total_uses=10, avg_iterations=5,
        )
        q = compute_skill_quality(skill)
        assert q.quality_level == "low"
        assert q.success_rate == 0.1

    def test_medium_quality(self):
        skill = Skill(
            skill_id="s3", product_type="web", design_style="dark",
            description="test", verify_cmd=["true"],
            success_count=5, total_uses=10, avg_iterations=2.5,
        )
        q = compute_skill_quality(skill)
        assert q.quality_level == "medium"

    def test_insufficient_data_returns_unknown(self):
        skill = Skill(
            skill_id="s4", product_type="web", design_style="dark",
            description="test", verify_cmd=["true"],
            success_count=1, total_uses=2, avg_iterations=1,
        )
        q = compute_skill_quality(skill)
        assert q.quality_level == "unknown"

    def test_fewer_iterations_is_better(self):
        s1 = Skill(skill_id="a", product_type="w", design_style="d", description="t",
                   verify_cmd=["true"], success_count=8, total_uses=10, avg_iterations=1)
        s2 = Skill(skill_id="b", product_type="w", design_style="d", description="t",
                   verify_cmd=["true"], success_count=8, total_uses=10, avg_iterations=5)
        assert compute_skill_quality(s1).score > compute_skill_quality(s2).score


class TestArchiveLowQuality:
    def test_archives_low_quality(self, tmp_path):
        db = str(tmp_path / "skills.db")
        _save_skill(db, "low quality landing page", count=2)

        for i in range(10):
            record_skill_usage("low quality landing page", "film_atelier",
                             success=False, db_path=db)

        archived = archive_low_quality_skills(db_path=db)
        assert len(archived) >= 1

    def test_keeps_high_quality(self, tmp_path):
        db = str(tmp_path / "skills.db")
        _save_skill(db, "high quality skill", count=10)

        archived = archive_low_quality_skills(db_path=db)
        assert len(archived) == 0

    def test_archives_only_if_enough_uses(self, tmp_path):
        db = str(tmp_path / "skills.db")
        _save_skill(db, "new skill", count=2)

        archived = archive_low_quality_skills(db_path=db)
        assert len(archived) == 0


class TestFindRelatedSkills:
    def test_finds_related_by_product_type(self, tmp_path):
        db = str(tmp_path / "skills.db")
        _save_skill(db, "build landing page header", count=2)
        _save_skill(db, "create pricing table component", count=2)
        _save_skill(db, "开发番茄钟计时器", count=2)

        related = find_related_skills(
            "landing page with header and pricing",
            db_path=db,
            max_results=2,
        )
        assert len(related) >= 1

    def test_empty_db_returns_empty(self, tmp_path):
        db = str(tmp_path / "skills.db")
        related = find_related_skills("anything", db_path=db)
        assert related == []


class TestApplySkillsToState:
    def test_applies_multiple_skills(self, tmp_path):
        state = _make_state(tmp_path, "auto")
        state.design_context = '{"style":"auto"}'
        state.context_summary = ""

        s1 = Skill(
            skill_id="s1", product_type="landing", design_style="dark",
            description="dark mode skill", verify_cmd=["true"],
            design_brief={"colors": {"bg": "#111"}, "mode": "dark"},
            worker_prompt_hints=["使用深色背景"],
            constraints=["必须有暗色模式"],
        )
        s2 = Skill(
            skill_id="s2", product_type="landing", design_style="dark",
            description="animation skill", verify_cmd=["true"],
            design_brief={"animation": {"enabled": True}},
            worker_prompt_hints=["添加过渡动画"],
            constraints=["必须有呼吸动画"],
        )

        result = apply_skills_to_state(state, [s1, s2])
        assert result.applied_count == 2
        assert "s1" in state.design_context
        assert "s2" in state.design_context
        assert "深色背景" in state.context_summary
        assert "呼吸动画" in state.context_summary

    def test_empty_skills_list(self, tmp_path):
        state = _make_state(tmp_path)
        result = apply_skills_to_state(state, [])
        assert result.applied_count == 0


class TestRecordSkillUsage:
    def test_record_success_increments(self, tmp_path):
        db = str(tmp_path / "skills.db")
        _save_skill(db, "test usage skill", count=1)

        ok = record_skill_usage("test usage skill", "film_atelier",
                               success=True, db_path=db)
        assert ok is True

        skills = list_skills(db_path=db)
        assert len(skills) == 1
        assert skills[0].success_count >= 1
        assert skills[0].total_uses >= 2

    def test_record_failure_increments_total_only(self, tmp_path):
        db = str(tmp_path / "skills.db")
        _save_skill(db, "fail test skill", count=1)

        ok = record_skill_usage("fail test skill", "film_atelier",
                               success=False, db_path=db)
        assert ok is True

        skills = list_skills(db_path=db)
        assert len(skills) == 1
        s = skills[0]
        assert s.total_uses > s.success_count
