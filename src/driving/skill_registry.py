"""M102 · Skill 沉淀系统 — Self-Improving Loop 核心第一步。

每次 factory 任务验证通过后，把 {design_brief, verify_cmd, worker_prompt_hints,
constraints} 沉淀为 Skill。新工厂创建时自动检索最相似的 Skill 并加载，
让系统越跑越强，而不是每次从零摸索。

设计原则：
- 复用 gold_memory 的 _embed / _cosine_similarity / _signature 基础设施
- SQLite 持久化 + WAL 模式 + 写锁（与 gold_memory 一致的并发安全模型）
- fail-open：Skill 系统任何异常都不阻塞 factory 主流程
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from driving.db import connect, default_db_path
from driving.factory_loop import FactoryState, FactoryTask, TaskResult


_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT NOT NULL UNIQUE,
    product_type TEXT NOT NULL DEFAULT 'unknown',
    design_style TEXT NOT NULL DEFAULT 'auto',
    description TEXT NOT NULL,
    description_vector TEXT NOT NULL DEFAULT '',
    verify_cmd TEXT NOT NULL DEFAULT '',
    design_brief TEXT NOT NULL DEFAULT '{}',
    worker_prompt_hints TEXT NOT NULL DEFAULT '[]',
    constraints TEXT NOT NULL DEFAULT '[]',
    success_count INTEGER NOT NULL DEFAULT 0,
    total_uses INTEGER NOT NULL DEFAULT 0,
    avg_iterations REAL NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    last_used TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
"""

_INDEX_SIGNATURE_SQL = "CREATE INDEX IF NOT EXISTS idx_skill_style ON skills(design_style)"
_INDEX_SKILL_ID_SQL = "CREATE UNIQUE INDEX IF NOT EXISTS idx_skill_id ON skills(skill_id)"


_skill_write_lock = threading.Lock()
_wal_initialized: set[str] = set()


def _enable_wal(db_path: str) -> None:
    if db_path in _wal_initialized:
        return
    try:
        with connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
        _wal_initialized.add(db_path)
    except Exception:
        pass


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_TABLE_SQL)
    conn.execute(_INDEX_SIGNATURE_SQL)
    conn.execute(_INDEX_SKILL_ID_SQL)


def _embed(text: str) -> list[float]:
    try:
        from driving.gold_memory import _embed as _gm_embed
        return _gm_embed(text[:500])
    except Exception:
        return []


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    try:
        from driving.gold_memory import _cosine_similarity as _gm_cos
        return _gm_cos(a, b)
    except Exception:
        import math
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)


def _signature(description: str, design_style: str) -> str:
    try:
        from driving.gold_memory import _signature as _gm_sig
        sig = _gm_sig(description)
    except Exception:
        sig = hashlib.md5(description.lower().encode()).hexdigest()[:12]
    return hashlib.md5(f"{sig}:{design_style}".encode()).hexdigest()[:16]


@dataclass
class Skill:
    skill_id: str
    product_type: str
    design_style: str
    description: str
    verify_cmd: list[str]
    description_vector: list[float] = field(default_factory=list)
    design_brief: dict[str, Any] = field(default_factory=dict)
    worker_prompt_hints: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    success_count: int = 0
    total_uses: int = 0
    avg_iterations: float = 0.0
    archived: bool = False
    last_used: str = ""
    created_at: str = ""


def _row_to_skill(row: sqlite3.Row) -> Skill:
    return Skill(
        skill_id=row["skill_id"],
        product_type=row["product_type"],
        design_style=row["design_style"],
        description=row["description"],
        verify_cmd=json.loads(row["verify_cmd"]) if row["verify_cmd"] else [],
        description_vector=json.loads(row["description_vector"]) if row["description_vector"] else [],
        design_brief=json.loads(row["design_brief"]) if row["design_brief"] else {},
        worker_prompt_hints=json.loads(row["worker_prompt_hints"]) if row["worker_prompt_hints"] else [],
        constraints=json.loads(row["constraints"]) if row["constraints"] else [],
        success_count=row["success_count"],
        total_uses=row["total_uses"] if "total_uses" in row.keys() else 0,
        avg_iterations=float(row["avg_iterations"]) if "avg_iterations" in row.keys() else 0.0,
        archived=bool(row["archived"]) if "archived" in row.keys() else False,
        last_used=row["last_used"],
        created_at=row["created_at"],
    )


def build_skill_from_result(
    task: FactoryTask,
    state: FactoryState,
    result: TaskResult,
) -> Skill:
    """从成功任务结果构建 Skill 对象（不写库）。"""
    sig = _signature(task.description, state.design_style or "auto")
    vector = _embed(task.description)
    now = datetime.now(timezone.utc).isoformat()

    design_brief = {}
    if state.design_context:
        try:
            design_brief = json.loads(state.design_context)
            if not isinstance(design_brief, dict):
                design_brief = {}
        except Exception:
            design_brief = {}

    hints: list[str] = []
    if state.design_style and state.design_style != "auto":
        hints.append(f"设计风格: {state.design_style}")
    if task.verify_cmd:
        hints.append(f"验收命令: {' '.join(task.verify_cmd)}")

    constraints: list[str] = []
    if design_brief:
        colors = design_brief.get("colors", {})
        if isinstance(colors, dict) and colors:
            constraints.append(f"主色调: {list(colors.keys())[:5]}")

    return Skill(
        skill_id=sig,
        product_type=_infer_product_type(task.description, state.product_goal),
        design_style=state.design_style or "auto",
        description=task.description[:500],
        verify_cmd=list(task.verify_cmd) if task.verify_cmd else [],
        description_vector=vector,
        design_brief=design_brief,
        worker_prompt_hints=hints,
        constraints=constraints,
        success_count=1,
        total_uses=1,
        avg_iterations=float(result.iteration) if result.iteration else 1.0,
        last_used=now,
        created_at=now,
    )


def _infer_product_type(description: str, goal: str) -> str:
    text = (goal + " " + description).lower()
    keywords = {
        "landing_page": ["landing", "着陆页", "落地页", "营销页", "官网"],
        "timer_app": ["番茄钟", "timer", "计时", "倒计时", "pomodoro"],
        "note_app": ["笔记", "note", "markdown", "md", "记事"],
        "dashboard": ["dashboard", "仪表板", "数据面板", "监控"],
        "portfolio": ["portfolio", "作品集", "个人主页"],
    }
    for ptype, kws in keywords.items():
        for kw in kws:
            if kw in text:
                return ptype
    return "unknown"


def save_skill(
    task: FactoryTask,
    state: FactoryState,
    result: TaskResult,
    db_path: str | None = None,
) -> Skill | None:
    """任务验证通过后沉淀为 Skill。失败则跳过。

    任何异常都 fail-open，不影响 factory 主流程。
    """
    if not result.verified:
        return None

    db_path = db_path or default_db_path()
    try:
        skill = build_skill_from_result(task, state, result)
        vector_json = json.dumps(skill.description_vector) if skill.description_vector else ""
        verify_cmd_str = json.dumps(skill.verify_cmd)
        brief_json = json.dumps(skill.design_brief)
        hints_json = json.dumps(skill.worker_prompt_hints)
        constraints_json = json.dumps(skill.constraints)

        _enable_wal(db_path)
        with _skill_write_lock:
            with connect(db_path) as conn:
                _ensure_table(conn)
                conn.execute(
                    """
                    INSERT INTO skills (
                        skill_id, product_type, design_style, description,
                        description_vector, verify_cmd, design_brief,
                        worker_prompt_hints, constraints, success_count,
                        total_uses, avg_iterations, archived,
                        last_used, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(skill_id) DO UPDATE SET
                        success_count = success_count + 1,
                        total_uses = total_uses + 1,
                        avg_iterations = (avg_iterations * total_uses + excluded.avg_iterations) / (total_uses + 1),
                        last_used = excluded.last_used,
                        description = excluded.description,
                        description_vector = excluded.description_vector
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
                        0,
                        skill.last_used,
                        skill.created_at,
                    ),
                )
        return skill
    except Exception:
        return None


def query_similar_skill(
    description: str,
    design_style: str = "auto",
    db_path: str | None = None,
    threshold: float = 0.6,
) -> Skill | None:
    """语义检索最相似的 Skill。未命中或任何异常返回 None（fail-open）。"""
    db_path = db_path or default_db_path()
    try:
        _enable_wal(db_path)
        with connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_table(conn)
            rows = conn.execute(
                "SELECT * FROM skills WHERE design_style = ? OR design_style = 'auto'",
                (design_style,),
            ).fetchall()

        if not rows:
            return None

        query_vec = _embed(description)
        if query_vec:
            best = None
            best_score = 0.0
            for row in rows:
                vec_json = row["description_vector"]
                if not vec_json:
                    continue
                try:
                    vec = json.loads(vec_json)
                except Exception:
                    continue
                score = _cosine_similarity(query_vec, vec)
                if score > best_score:
                    best_score = score
                    best = row
            if best is not None and best_score >= threshold:
                _touch_skill(best["skill_id"], db_path)
                return _row_to_skill(best)

        sig = _signature(description, design_style)
        for row in rows:
            if row["skill_id"] == sig:
                _touch_skill(row["skill_id"], db_path)
                return _row_to_skill(row)

        return None
    except Exception:
        return None


def _touch_skill(skill_id: str, db_path: str) -> None:
    try:
        now = datetime.now(timezone.utc).isoformat()
        with _skill_write_lock:
            with connect(db_path) as conn:
                conn.execute(
                    "UPDATE skills SET last_used = ? WHERE skill_id = ?",
                    (now, skill_id),
                )
    except Exception:
        pass


def list_skills(db_path: str | None = None) -> list[Skill]:
    """列出所有 Skill（按 success_count 降序）。"""
    db_path = db_path or default_db_path()
    try:
        _enable_wal(db_path)
        with connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_table(conn)
            rows = conn.execute(
                "SELECT * FROM skills ORDER BY success_count DESC, last_used DESC"
            ).fetchall()
        return [_row_to_skill(r) for r in rows]
    except Exception:
        return []


def apply_skill_to_state(state: FactoryState, skill: Skill) -> None:
    """把 Skill 应用到 factory state。

    - 更新 design_style 为 Skill 的风格（如果当前是 auto）
    - 把 skill.design_brief 合并到 state.design_context
    - 把 worker_prompt_hints + constraints 注入 state.context_summary
    """
    if state.design_style == "auto" or not state.design_style:
        state.design_style = skill.design_style

    if skill.design_brief:
        try:
            current = json.loads(state.design_context or "{}")
            if not isinstance(current, dict):
                current = {}
            merged = {**skill.design_brief, **current}
            merged["skill_applied"] = True
            merged["skill_id"] = skill.skill_id
            state.design_context = json.dumps(merged, ensure_ascii=False)
        except Exception:
            pass

    summary_parts = []
    if skill.worker_prompt_hints:
        summary_parts.append("【Skill 经验】" + "; ".join(skill.worker_prompt_hints[:5]))
    if skill.constraints:
        summary_parts.append("【Skill 约束】" + "; ".join(skill.constraints[:5]))
    if skill.verify_cmd:
        summary_parts.append(f"【Skill 验证】{' '.join(skill.verify_cmd)}")

    if summary_parts:
        existing = state.context_summary or ""
        state.context_summary = (existing + "\n" + "\n".join(summary_parts)).strip()
