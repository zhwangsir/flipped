"""M102 · Skill 沉淀系统测试。

Self-Improving Loop 核心：成功任务自动沉淀为 Skill，新工厂自动加载相似 Skill。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from driving.factory_loop import FactoryState, FactoryTask, TaskResult
from driving.skill_registry import (
    Skill,
    apply_skill_to_state,
    build_skill_from_result,
    list_skills,
    query_similar_skill,
    save_skill,
)


def _make_state(tmp_path: Path, design_style: str = "film_atelier") -> FactoryState:
    from driving.factory_loop import FactoryStatus

    return FactoryState(
        factory_id="test-factory",
        product_goal="开发番茄钟计时器应用",
        cwd=str(tmp_path),
        status=FactoryStatus.running,
        roadmap=[],
        max_tasks=5,
        max_rounds=2,
        design_style=design_style,
        design_context='{"colors":{"bg":"#0D0D12"},"style":"film_atelier"}',
    )


def _make_task(desc: str = "创建番茄钟主页面") -> FactoryTask:
    return FactoryTask(
        id="t1",
        description=desc,
        verify_cmd=["python", "-c", "import sys; sys.exit(0)"],
        status="done",
    )


def _make_result(verified: bool = True) -> TaskResult:
    return TaskResult(
        task=_make_task(),
        verified=verified,
        stop_reason="verified",
        iteration=1,
        summary="番茄钟页面创建成功",
    )


class TestSkillDataModel:
    def test_skill_creation_defaults(self):
        s = Skill(
            skill_id="s1",
            product_type="timer_app",
            design_style="film_atelier",
            description="创建番茄钟",
            verify_cmd=["python", "-c", "print('ok')"],
        )
        assert s.success_count == 0
        assert s.constraints == []
        assert s.worker_prompt_hints == []
        assert s.design_brief == {}
        assert s.description_vector == []


class TestSaveSkill:
    def test_save_verified_task_creates_skill(self, tmp_path):
        db = tmp_path / "skills.db"
        state = _make_state(tmp_path)
        task = _make_task()
        result = _make_result(verified=True)

        save_skill(task, state, result, db_path=str(db))

        skills = list_skills(db_path=str(db))
        assert len(skills) == 1
        s = skills[0]
        assert s.design_style == "film_atelier"
        assert "番茄钟" in s.description
        assert s.verify_cmd == ["python", "-c", "import sys; sys.exit(0)"]
        assert s.success_count == 1

    def test_save_unverified_task_skipped(self, tmp_path):
        db = tmp_path / "skills.db"
        state = _make_state(tmp_path)
        task = _make_task()
        result = _make_result(verified=False)

        save_skill(task, state, result, db_path=str(db))

        assert list_skills(db_path=str(db)) == []

    def test_save_same_signature_increments_count(self, tmp_path):
        db = tmp_path / "skills.db"
        state = _make_state(tmp_path)
        task1 = _make_task("create tomato timer landing page")
        task2 = _make_task("create tomato timer landing page")
        result = _make_result(verified=True)

        save_skill(task1, state, result, db_path=str(db))
        save_skill(task2, state, result, db_path=str(db))

        skills = list_skills(db_path=str(db))
        assert len(skills) == 1
        assert skills[0].success_count == 2

    def test_save_different_style_separate_skills(self, tmp_path):
        db = tmp_path / "skills.db"
        state1 = _make_state(tmp_path, "film_atelier")
        state2 = _make_state(tmp_path, "minimalism")
        task = _make_task()
        result = _make_result(verified=True)

        save_skill(task, state1, result, db_path=str(db))
        save_skill(task, state2, result, db_path=str(db))

        skills = list_skills(db_path=str(db))
        assert len(skills) == 2
        styles = {s.design_style for s in skills}
        assert styles == {"film_atelier", "minimalism"}


class TestQuerySimilarSkill:
    def test_empty_db_returns_none(self, tmp_path):
        db = tmp_path / "skills.db"
        result = query_similar_skill("番茄钟应用", db_path=str(db))
        assert result is None

    def test_keyword_signature_match(self, tmp_path, monkeypatch):
        db = tmp_path / "skills.db"
        state = _make_state(tmp_path)
        task = _make_task("build tomato timer landing page")
        result = _make_result(verified=True)
        save_skill(task, state, result, db_path=str(db))

        monkeypatch.setattr("driving.gold_memory._get_embedding_model", lambda: None)

        found = query_similar_skill("build tomato timer landing page", "film_atelier", db_path=str(db))
        assert found is not None
        assert "tomato" in found.description

    def test_no_match_returns_none(self, tmp_path, monkeypatch):
        db = tmp_path / "skills.db"
        state = _make_state(tmp_path)
        task = _make_task("开发番茄钟计时器主页")
        result = _make_result(verified=True)
        save_skill(task, state, result, db_path=str(db))

        monkeypatch.setattr("driving.gold_memory._get_embedding_model", lambda: None)

        found = query_similar_skill("电商购物网站", db_path=str(db))
        assert found is None


class TestBuildSkillFromResult:
    def test_build_skill_extracts_design_brief(self, tmp_path):
        state = _make_state(tmp_path)
        task = _make_task()
        result = _make_result(verified=True)

        skill = build_skill_from_result(task, state, result)
        assert skill.design_style == "film_atelier"
        assert "film_atelier" in skill.design_brief.get("style", "") or skill.design_brief.get("colors")


class TestApplySkillToState:
    def test_apply_injects_design_context(self, tmp_path):
        state = _make_state(tmp_path, "auto")
        state.design_context = '{"style":"auto"}'

        skill = Skill(
            skill_id="s1",
            product_type="timer_app",
            design_style="film_atelier",
            description="番茄钟",
            verify_cmd=["pytest", "-q"],
            design_brief={"colors": {"bg": "#0D0D12", "accent": "#d4a017"}, "fonts": {"heading": "serif"}},
            worker_prompt_hints=["使用 localStorage 持久化", "配色不超过5种"],
            constraints=["必须实现暗色模式", "必须有呼吸动画效果"],
        )

        apply_skill_to_state(state, skill)

        assert state.design_style == "film_atelier"
        dc = json.loads(state.design_context)
        assert dc.get("skill_applied") is True
        assert dc.get("skill_id") == "s1"

    def test_apply_adds_worker_hints_to_summary(self, tmp_path):
        state = _make_state(tmp_path)
        state.context_summary = ""

        skill = Skill(
            skill_id="s1",
            product_type="timer_app",
            design_style="film_atelier",
            description="番茄钟",
            verify_cmd=["true"],
            worker_prompt_hints=["使用 localStorage 持久化"],
            constraints=["必须有暗色模式"],
        )

        apply_skill_to_state(state, skill)

        assert "Skill" in state.context_summary
        assert "localStorage" in state.context_summary


class TestConcurrency:
    def test_concurrent_save_no_lock_error(self, tmp_path):
        db = tmp_path / "skills.db"
        state = _make_state(tmp_path)
        result = _make_result(verified=True)
        errors = []
        tasks = [
            "build landing page header component",
            "create user authentication form",
            "implement product gallery section",
            "add shopping cart functionality",
            "design about team page",
            "setup contact form validation",
            "build pricing table component",
            "create faq accordion section",
            "implement footer navigation",
            "add dark mode toggle button",
        ]

        def worker(i: int):
            try:
                task = _make_task(tasks[i])
                save_skill(task, state, result, db_path=str(db))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        skills = list_skills(db_path=str(db))
        assert len(skills) == 10


class TestFactoryLoopIntegration:
    def test_factory_loop_success_writes_skill(self, tmp_path, monkeypatch):
        db = tmp_path / "skills.db"
        state = _make_state(tmp_path)
        task = _make_task("生成 landing page")
        result = _make_result(verified=True)

        save_skill(task, state, result, db_path=str(db))

        skills = list_skills(db_path=str(db))
        assert len(skills) == 1
        assert skills[0].success_count == 1

    def test_same_description_no_duplicate_skill(self, tmp_path):
        db = tmp_path / "skills.db"
        state = _make_state(tmp_path)
        task = _make_task("生成 landing page")
        result = _make_result(verified=True)

        save_skill(task, state, result, db_path=str(db))
        save_skill(task, state, result, db_path=str(db))

        skills = list_skills(db_path=str(db))
        assert len(skills) == 1
        assert skills[0].success_count == 2
