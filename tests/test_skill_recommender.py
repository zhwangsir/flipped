"""M110 · Skill 自动发现与推荐测试。

不止匹配最相似的 Skill，还主动推荐相关 Skill、发现 Skill 组合模板。
"""
from __future__ import annotations

import tempfile
import os

import pytest

from driving.skill_recommender import (
    SkillRecommendation,
    recommend_skills,
    discover_skill_combos,
    build_association_network,
    get_trending_skills,
)
from driving.skill_registry import Skill, _TABLE_SQL, _embed

import sqlite3


def _insert_skill(db_path, skill):
    import json
    import threading
    from driving.skill_registry import _enable_wal, _ensure_table

    _enable_wal(db_path)
    with sqlite3.connect(db_path) as conn:
        _ensure_table(conn)
        vector_json = json.dumps(skill.description_vector) if skill.description_vector else ""
        verify_cmd_str = json.dumps(skill.verify_cmd)
        brief_json = json.dumps(skill.design_brief)
        hints_json = json.dumps(skill.worker_prompt_hints)
        constraints_json = json.dumps(skill.constraints)
        conn.execute(
            """
            INSERT OR REPLACE INTO skills (
                skill_id, product_type, design_style, description,
                description_vector, verify_cmd, design_brief,
                worker_prompt_hints, constraints, success_count,
                total_uses, avg_iterations, archived,
                last_used, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                skill.skill_id,
                skill.product_type,
                skill.design_style,
                skill.description,
                vector_json,
                verify_cmd_str,
                brief_json,
                hints_json,
                constraints_json,
                skill.success_count,
                skill.total_uses,
                skill.avg_iterations,
                1 if skill.archived else 0,
                skill.last_used,
                skill.created_at,
            ),
        )
        conn.commit()


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        yield path
    finally:
        if os.path.exists(path):
            os.remove(path)


def _make_skill(skill_id, desc, style="minimalism", product_type="landing_page"):
    from dataclasses import replace
    from driving.skill_registry import Skill
    return Skill(
        skill_id=skill_id,
        product_type=product_type,
        design_style=style,
        description=desc,
        verify_cmd=["true"],
        success_count=5,
        total_uses=8,
        avg_iterations=1.5,
    )


class TestRecommendSkills:
    def test_returns_multiple_recommendations(self, temp_db):
        _insert_skill(temp_db, _make_skill("s1", "build landing page hero section"))
        _insert_skill(temp_db, _make_skill("s2", "create landing page features section"))
        _insert_skill(temp_db, _make_skill("s3", "design footer component"))

        recs = recommend_skills(
            "build a full landing page",
            design_style="minimalism",
            db_path=temp_db,
            top_k=3,
        )
        assert len(recs) >= 1
        assert isinstance(recs[0], SkillRecommendation)
        assert recs[0].skill_id is not None

    def test_recommendations_sorted_by_score(self, temp_db):
        _insert_skill(temp_db, _make_skill("s1", "exact landing page match"))
        _insert_skill(temp_db, _make_skill("s2", "unrelated dashboard admin"))

        recs = recommend_skills(
            "build a landing page",
            db_path=temp_db,
            top_k=5,
        )
        assert len(recs) >= 2
        assert recs[0].relevance_score >= recs[-1].relevance_score

    def test_empty_db_returns_empty(self, temp_db):
        recs = recommend_skills("test", db_path=temp_db)
        assert recs == []

    def test_recommendation_has_quality_score(self, temp_db):
        _insert_skill(temp_db, _make_skill("s1", "landing page hero"))

        recs = recommend_skills("build a landing page", db_path=temp_db, top_k=1)
        assert len(recs) == 1
        assert hasattr(recs[0], "quality_score")
        assert recs[0].quality_score >= 0.0


class TestDiscoverSkillCombos:
    def test_finds_frequently_used_combos(self, temp_db):
        _insert_skill(temp_db, _make_skill("s1", "hero section"))
        _insert_skill(temp_db, _make_skill("s2", "features section"))
        _insert_skill(temp_db, _make_skill("s3", "footer section"))

        combos = discover_skill_combos(
            "build landing page",
            db_path=temp_db,
            min_skills=2,
        )
        assert isinstance(combos, list)

    def test_empty_db_no_combos(self, temp_db):
        combos = discover_skill_combos("test", db_path=temp_db)
        assert combos == []


class TestAssociationNetwork:
    def test_builds_network_from_descriptions(self, temp_db):
        _insert_skill(temp_db, _make_skill("s1", "landing page hero with animation"))
        _insert_skill(temp_db, _make_skill("s2", "features section with animation"))
        _insert_skill(temp_db, _make_skill("s3", "dashboard admin panel"))

        network = build_association_network(db_path=temp_db)
        assert isinstance(network, dict)


class TestGetTrendingSkills:
    def test_trending_returns_sorted_list(self, temp_db):
        s1 = _make_skill("s1", "popular skill")
        s1.success_count = 20
        s1.total_uses = 25
        _insert_skill(temp_db, s1)

        s2 = _make_skill("s2", "less popular")
        s2.success_count = 3
        s2.total_uses = 5
        _insert_skill(temp_db, s2)

        trending = get_trending_skills(db_path=temp_db, limit=5)
        assert isinstance(trending, list)
        assert len(trending) >= 2


class TestSkillRecommendationDataclass:
    def test_has_expected_fields(self):
        rec = SkillRecommendation(
            skill_id="s1",
            description="test skill",
            relevance_score=0.85,
            quality_score=0.75,
            combined_score=0.8,
            reason="high similarity",
            design_style="minimalism",
        )
        assert rec.skill_id == "s1"
        assert rec.relevance_score == 0.85
        assert rec.quality_score == 0.75
        assert rec.combined_score == 0.8
