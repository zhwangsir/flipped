"""M110 · Skill 自动发现与推荐。

不止匹配最相似的 Skill，还主动推荐相关 Skill、发现 Skill 组合模板。
- recommend_skills: 推荐 Skill（综合相关性 + 质量评分）
- discover_skill_combos: 发现 Skill 组合模板
- build_association_network: 构建 Skill 关联网络
- get_trending_skills: 热门/高质量 Skill 排行

fail-open: 任何异常都返回空结果，不阻塞主流程。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from driving.skill_registry import (
    Skill,
    list_skills,
    _embed,
    _cosine_similarity,
)


@dataclass
class SkillRecommendation:
    """Skill 推荐结果。"""
    skill_id: str
    description: str
    relevance_score: float
    quality_score: float
    combined_score: float
    reason: str
    design_style: str
    product_type: str = ""


def _compute_quality_score(skill: Skill) -> float:
    """计算 Skill 质量分（0-1）。"""
    try:
        if skill.total_uses == 0:
            return 0.5
        success_rate = skill.success_count / max(1, skill.total_uses)
        efficiency = 1.0 / max(1.0, skill.avg_iterations / 2.0)
        use_bonus = min(0.2, skill.total_uses / 50.0)
        score = 0.5 * success_rate + 0.3 * efficiency + 0.2 * use_bonus
        return max(0.0, min(1.0, score))
    except Exception:
        return 0.5


def _load_all_skills(db_path: str) -> list[Skill]:
    """加载所有未归档的 Skill。"""
    try:
        all_skills = list_skills(db_path)
        return [s for s in all_skills if not getattr(s, 'archived', False)]
    except Exception:
        return []


def recommend_skills(
    description: str,
    design_style: str = "auto",
    *,
    db_path: str = "data/skills.db",
    top_k: int = 5,
    relevance_weight: float = 0.6,
    quality_weight: float = 0.4,
) -> list[SkillRecommendation]:
    """推荐 Skill（综合相关性 + 质量评分）。

    不仅返回最相似的，还按"相关性 × 质量"综合排序，推荐真正好用的 Skill。
    """
    try:
        skills = _load_all_skills(db_path)
        if not skills:
            return []

        desc_vec = _embed(description)

        recommendations: list[SkillRecommendation] = []
        for skill in skills:
            skill_vec = skill.description_vector or _embed(skill.description)
            relevance = _cosine_similarity(desc_vec, skill_vec)

            quality = _compute_quality_score(skill)

            combined = relevance_weight * relevance + quality_weight * quality

            reason_parts = []
            if relevance > 0.7:
                reason_parts.append("高度相关")
            elif relevance > 0.5:
                reason_parts.append("相关")
            if quality > 0.7:
                reason_parts.append("高质量")
            if skill.total_uses > 10:
                reason_parts.append(f"常用({skill.total_uses}次)")
            reason = " + ".join(reason_parts) if reason_parts else "匹配"

            recommendations.append(SkillRecommendation(
                skill_id=skill.skill_id,
                description=skill.description,
                relevance_score=round(relevance, 3),
                quality_score=round(quality, 3),
                combined_score=round(combined, 3),
                reason=reason,
                design_style=skill.design_style,
                product_type=skill.product_type,
            ))

        recommendations.sort(key=lambda r: r.combined_score, reverse=True)
        return recommendations[:top_k]
    except Exception:
        return []


def discover_skill_combos(
    description: str,
    design_style: str = "auto",
    *,
    db_path: str = "data/skills.db",
    min_skills: int = 2,
    max_skills: int = 4,
) -> list[dict[str, Any]]:
    """发现 Skill 组合模板。

    基于任务描述和 Skill 关联网络，推荐 2-4 个 Skill 的组合，
    每个 Skill 覆盖任务的不同侧面。
    """
    try:
        recs = recommend_skills(
            description, design_style, db_path=db_path, top_k=10
        )
        if len(recs) < min_skills:
            return []

        combos = []
        for n in range(min_skills, min(max_skills, len(recs)) + 1):
            combo = recs[:n]
            avg_score = sum(r.combined_score for r in combo) / len(combo)
            coverage = sum(r.relevance_score for r in combo)
            combos.append({
                "size": n,
                "skills": [
                    {"skill_id": r.skill_id, "description": r.description}
                    for r in combo
                ],
                "avg_quality": round(sum(r.quality_score for r in combo) / len(combo), 3),
                "estimated_coverage": round(min(1.0, coverage * 0.5), 2),
                "recommendation": (
                    f"推荐使用 {n} 个 Skill 的组合，"
                    f"平均质量 {round(avg_score, 2)}"
                ),
            })

        return combos
    except Exception:
        return []


def build_association_network(
    *,
    db_path: str = "data/skills.db",
    min_similarity: float = 0.3,
) -> dict[str, Any]:
    """构建 Skill 关联网络（用于前端可视化）。

    返回 {
        "nodes": [{"id": ..., "name": ..., "style": ...}],
        "edges": [{"source": ..., "target": ..., "weight": ...}],
    }
    """
    try:
        skills = _load_all_skills(db_path)
        if not skills:
            return {"nodes": [], "edges": []}

        nodes = [
            {
                "id": s.skill_id,
                "name": s.description[:30],
                "style": s.design_style,
                "product_type": s.product_type,
                "quality": round(_compute_quality_score(s), 2),
                "uses": s.total_uses,
            }
            for s in skills
        ]

        edges = []
        for i, s1 in enumerate(skills):
            v1 = s1.description_vector or _embed(s1.description)
            for j, s2 in enumerate(skills):
                if j <= i:
                    continue
                v2 = s2.description_vector or _embed(s2.description)
                sim = _cosine_similarity(v1, v2)
                if sim >= min_similarity:
                    edges.append({
                        "source": s1.skill_id,
                        "target": s2.skill_id,
                        "weight": round(sim, 3),
                    })

        return {"nodes": nodes, "edges": edges}
    except Exception:
        return {"nodes": [], "edges": []}


def get_trending_skills(
    *,
    db_path: str = "data/skills.db",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """热门/高质量 Skill 排行榜。"""
    try:
        skills = _load_all_skills(db_path)
        if not skills:
            return []

        scored = []
        for s in skills:
            quality = _compute_quality_score(s)
            trending = quality * 0.6 + min(1.0, s.total_uses / 20.0) * 0.4
            scored.append({
                "skill_id": s.skill_id,
                "description": s.description,
                "design_style": s.design_style,
                "product_type": s.product_type,
                "success_rate": round(
                    s.success_count / max(1, s.total_uses), 2
                ),
                "total_uses": s.total_uses,
                "avg_iterations": s.avg_iterations,
                "quality_score": round(quality, 3),
                "trending_score": round(trending, 3),
            })

        scored.sort(key=lambda x: x["trending_score"], reverse=True)
        return scored[:limit]
    except Exception:
        return []
