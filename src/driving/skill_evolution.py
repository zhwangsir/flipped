"""M104 · Skill 进化系统 — 质量评估、自动淘汰、组合应用。

Skill 不只是存和取，它会随着使用次数增加而进化：
- 质量评估：success_rate + avg_iterations → quality_level (high/medium/low/unknown)
- 自动淘汰：低质量且使用次数足够多的 Skill 自动归档
- 组合应用：一个工厂可同时加载多个相关 Skill，叠加效果
- 使用记录：每次使用后更新 total_uses / avg_iterations

fail-open: 任何异常都不阻塞主流程。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from driving.skill_registry import Skill, _signature


MIN_USES_FOR_QUALITY = 5
LOW_QUALITY_THRESHOLD = 0.3
HIGH_QUALITY_THRESHOLD = 0.7
MAX_ITERATIONS_FOR_HIGH = 2.0

_evo_lock = threading.Lock()
_migrated_dbs: set[str] = set()


@dataclass
class SkillQuality:
    """Skill 质量评估结果。"""
    skill_id: str
    quality_level: str
    success_rate: float
    score: float
    total_uses: int
    avg_iterations: float
    factors: list[str] = field(default_factory=list)


@dataclass
class SkillApplyResult:
    """多 Skill 应用结果。"""
    applied_count: int
    skill_ids: list[str]
    merged_brief: dict[str, Any] = field(default_factory=dict)


def _ensure_migration(db_path: str) -> None:
    """确保 skills 表有进化系统需要的新列（向后兼容）。"""
    if db_path in _migrated_dbs:
        return
    try:
        with sqlite3.connect(db_path) as conn:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(skills)").fetchall()]
            if "total_uses" not in cols:
                conn.execute("ALTER TABLE skills ADD COLUMN total_uses INTEGER NOT NULL DEFAULT 0")
            if "avg_iterations" not in cols:
                conn.execute("ALTER TABLE skills ADD COLUMN avg_iterations REAL NOT NULL DEFAULT 0")
            if "archived" not in cols:
                conn.execute("ALTER TABLE skills ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        _migrated_dbs.add(db_path)
    except Exception:
        pass


def compute_skill_quality(skill: Skill) -> SkillQuality:
    """评估 Skill 质量。

    评分 = 0.7 * success_rate + 0.3 * (1 / max(1, avg_iterations / 2))
    - 成功率权重 70%（能不能做成）
    - 迭代效率权重 30%（做几次能成）
    """
    if skill.total_uses < MIN_USES_FOR_QUALITY and skill.success_count < MIN_USES_FOR_QUALITY:
        return SkillQuality(
            skill_id=skill.skill_id,
            quality_level="unknown",
            success_rate=0.0,
            score=0.0,
            total_uses=skill.total_uses,
            avg_iterations=skill.avg_iterations,
            factors=["数据不足，无法评估"],
        )

    total = max(skill.total_uses, skill.success_count)
    success_rate = skill.success_count / total if total > 0 else 0.0

    eff_factor = 1.0 / max(1.0, skill.avg_iterations / MAX_ITERATIONS_FOR_HIGH) if skill.avg_iterations > 0 else 1.0
    score = 0.7 * success_rate + 0.3 * min(eff_factor, 1.0)

    factors: list[str] = []
    if success_rate >= HIGH_QUALITY_THRESHOLD:
        factors.append("成功率高")
    elif success_rate <= LOW_QUALITY_THRESHOLD:
        factors.append("成功率低")

    if skill.avg_iterations > 0 and skill.avg_iterations <= 1.5:
        factors.append("迭代效率高")
    elif skill.avg_iterations >= 4:
        factors.append("迭代效率低")

    if score >= HIGH_QUALITY_THRESHOLD:
        level = "high"
    elif score >= LOW_QUALITY_THRESHOLD + 0.15:
        level = "medium"
    else:
        level = "low"

    return SkillQuality(
        skill_id=skill.skill_id,
        quality_level=level,
        success_rate=success_rate,
        score=score,
        total_uses=total,
        avg_iterations=skill.avg_iterations,
        factors=factors,
    )


def record_skill_usage(
    description: str,
    design_style: str,
    *,
    success: bool,
    iterations: int = 1,
    db_path: str = "data/skills.db",
) -> bool:
    """记录一次 Skill 使用，更新 total_uses / success_count / avg_iterations。

    找不到对应 Skill 时返回 False（fail-open）。
    """
    try:
        _ensure_migration(db_path)
        sig = _signature(description, design_style)
        now = datetime.now(timezone.utc).isoformat()
        with _evo_lock:
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT total_uses, success_count, avg_iterations FROM skills WHERE skill_id = ?",
                    (sig,),
                ).fetchone()
                if not row:
                    return False
                old_total = row[0] or 0
                old_success = row[1] or 0
                old_avg = row[2] or 0.0

                new_total = old_total + 1
                new_success = old_success + (1 if success else 0)
                # 增量平均
                new_avg = (old_avg * old_total + iterations) / new_total if new_total > 0 else iterations

                conn.execute(
                    """UPDATE skills SET total_uses = ?, success_count = ?,
                       avg_iterations = ?, last_used = ? WHERE skill_id = ?""",
                    (new_total, new_success, new_avg, now, sig),
                )
        return True
    except Exception:
        return False


def archive_low_quality_skills(
    db_path: str = "data/skills.db",
    *,
    min_uses: int = MIN_USES_FOR_QUALITY,
    threshold: float = LOW_QUALITY_THRESHOLD,
) -> list[str]:
    """自动归档低质量 Skill。返回被归档的 skill_id 列表。

    条件：total_uses >= min_uses AND quality_score < threshold AND archived = 0
    """
    archived: list[str] = []
    try:
        _ensure_migration(db_path)
        from driving.skill_registry import list_skills
        skills = [s for s in list_skills(db_path) if not s.archived]
        now = datetime.now(timezone.utc).isoformat()
        with _evo_lock:
            with sqlite3.connect(db_path) as conn:
                for s in skills:
                    total = max(s.total_uses, s.success_count)
                    if total < min_uses:
                        continue
                    q = compute_skill_quality(s)
                    if q.quality_level == "low":
                        conn.execute(
                            "UPDATE skills SET archived = 1, last_used = ? WHERE skill_id = ?",
                            (now, s.skill_id),
                        )
                        archived.append(s.skill_id)
    except Exception:
        pass
    return archived


def find_related_skills(
    description: str,
    design_style: str = "auto",
    *,
    db_path: str = "data/skills.db",
    max_results: int = 3,
    include_archived: bool = False,
) -> list[Skill]:
    """查找与描述相关的多个 Skill（用于组合应用）。

    按质量分 + 相似度排序，返回 top N。
    """
    try:
        from driving.skill_registry import query_similar_skill, list_skills

        # 先用语义检索找最相关的 1 个，再找同 product_type 的其他 Skill
        best = query_similar_skill(description, design_style=design_style, db_path=db_path)
        all_skills = [s for s in list_skills(db_path) if include_archived or not s.archived]

        if not all_skills:
            return []

        results: list[Skill] = []
        if best and (include_archived or not best.archived):
            results.append(best)

        # 补充同类型高质量 Skill
        product_type = best.product_type if best else "unknown"
        same_type = [
            s for s in all_skills
            if s.skill_id != (best.skill_id if best else "")
            and s.product_type == product_type
        ]
        same_type.sort(key=lambda s: compute_skill_quality(s).score, reverse=True)
        results.extend(same_type[:max_results - len(results)])

        return results[:max_results]
    except Exception:
        return []


def apply_skills_to_state(
    state: Any,
    skills: list[Skill],
) -> SkillApplyResult:
    """把多个 Skill 应用到 factory state。

    - 合并所有 skill.design_brief（后加载的覆盖先加载的同名字段）
    - 合并所有 worker_prompt_hints
    - 合并所有 constraints
    - 用最高质量 Skill 的 design_style（如果当前是 auto）
    """
    applied_ids: list[str] = []
    merged_brief: dict[str, Any] = {}
    all_hints: list[str] = []
    all_constraints: list[str] = []
    best_style = ""

    try:
        import json as _json

        for skill in skills:
            if skill.archived:
                continue
            applied_ids.append(skill.skill_id)
            if skill.design_brief and isinstance(skill.design_brief, dict):
                merged_brief = _deep_merge(merged_brief, skill.design_brief)
            all_hints.extend(skill.worker_prompt_hints)
            all_constraints.extend(skill.constraints)
            if not best_style and skill.design_style and skill.design_style != "auto":
                best_style = skill.design_style
    except Exception:
        pass

    # 应用到 state
    try:
        import json as _json
        if best_style and (not state.design_style or state.design_style == "auto"):
            state.design_style = best_style

        if merged_brief:
            try:
                current = _json.loads(state.design_context or "{}")
                if not isinstance(current, dict):
                    current = {}
                merged = _deep_merge(merged_brief, current)
                merged["skills_applied"] = applied_ids
                state.design_context = _json.dumps(merged, ensure_ascii=False)
            except Exception:
                pass

        summary_parts = []
        if all_hints:
            summary_parts.append(f"【Skill 经验 x{len(skills)}】" + "; ".join(all_hints[:8]))
        if all_constraints:
            summary_parts.append("【Skill 约束】" + "; ".join(all_constraints[:5]))

        if summary_parts:
            existing = state.context_summary or ""
            state.context_summary = (existing + "\n" + "\n".join(summary_parts)).strip()
    except Exception:
        pass

    return SkillApplyResult(
        applied_count=len(applied_ids),
        skill_ids=applied_ids,
        merged_brief=merged_brief,
    )


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个 dict，override 覆盖 base 中同名字段。"""
    result = dict(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result
