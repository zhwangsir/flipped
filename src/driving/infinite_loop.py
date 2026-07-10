"""无限迭代外层循环（M10.2）。

完成一个 factory roadmap 后，基于成果摘要 + 原始方向，自主生成下一轮 roadmap。
这就是"只需要给出方向就可以自行无限迭代"的核心机制。

每轮：
1. 第一轮：product_goal = direction
2. 后续轮：GLM 作为"产品演进者"看上一轮成果 + 原始方向，生成下一轮目标
3. 调用 run_factory_loop 执行这一轮
4. 收集成果摘要，检查停止条件

停止条件：
- 用户停止（stop_requested flag）
- 达到 max_rounds
- GLM 判定产品方向已完全达成
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Callable, Literal
from pydantic import BaseModel, Field

from driving.factory_loop import (
    FactoryState,
    FactoryStatus,
    run_factory_loop,
)
from driving.progress_notes import (
    init_progress,
    record_round,
    summarize_for_evolution,
    design_brief_from_progress,
)


class RoundSummary(BaseModel):
    """一轮工厂循环的摘要。"""
    round_num: int
    factory_id: str
    product_goal: str
    tasks_completed: int
    tasks_failed: int
    summary: str = ""
    artifacts: list[str] = Field(default_factory=list)


class InfiniteLoopState(BaseModel):
    """无限迭代循环的全局状态。"""
    loop_id: str
    direction: str
    cwd: str
    design_style: str = "auto"
    rounds: list[RoundSummary] = Field(default_factory=list)
    max_rounds: int = 10
    status: Literal["running", "stopped", "goal_achieved", "budget_exhausted", "infra_failure"] = "running"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------- 产品演进者 schema ----------

class NextGoal(BaseModel):
    """GLM 产出的下一轮目标。"""
    next_goal: str = Field(description="下一轮的具体产品目标，基于上一轮成果演进")
    goal_achieved: bool = Field(description="产品方向是否已完全达成，不需要再迭代")
    reasoning: str = Field(description="推理过程：为什么这是下一轮该做的")


# ---------- 演进目标生成 ----------

def _evolve_goal(direction: str, rounds: list[RoundSummary], cwd: str = "") -> tuple[str, bool, str]:
    """用 GLM 生成下一轮目标。返回 (goal, achieved, reasoning)。

    M10.4-B 增强：读取 FEATURE_CHECKLIST.json + PROGRESS.md 作为长期记忆，
    让演进者不只是看上一轮摘要（短视），而是看完整进展历史（远视）。

    GLM 看原始方向 + 已完成的轮次摘要 + 完整功能清单，决定下一轮做什么。
    """
    from driving.orchestrator import _invoke_structured, _make_llm

    if not rounds:
        return direction, False, "首轮：直接使用用户给的方向"

    rounds_text = "\n".join(
        f"  第 {r.round_num} 轮：目标={r.product_goal}\n"
        f"    完成 {r.tasks_completed} 个任务，失败 {r.tasks_failed} 个\n"
        f"    成果：{r.summary}\n"
        f"    产出文件：{', '.join(r.artifacts[:10]) if r.artifacts else '无'}"
        for r in rounds
    )

    # M10.4-B：从 PROGRESS.md / FEATURE_CHECKLIST.json 提取长期记忆
    progress_summary = ""
    design_contract = ""
    if cwd:
        try:
            progress_summary = summarize_for_evolution(cwd)
            dc = design_brief_from_progress(cwd)
            if dc:
                design_contract = f"\n{dc}\n"
        except Exception:
            pass

    msg = (
        f"产品方向：{direction}\n\n"
        f"已完成的轮次：\n{rounds_text}\n\n"
        f"完整功能清单（FEATURE_CHECKLIST）：\n{progress_summary}\n"
        f"{design_contract}\n"
        "你是产品演进者。基于产品方向和已完成的工作，决定下一轮应该做什么。\n"
        "要求：\n"
        "1. next_goal 必须是基于上一轮成果的**增量演进**，不要重复已完成的工作。\n"
        "2. 如果产品方向已完全达成（所有核心功能都已实现并验证），设 goal_achieved=true。\n"
        "3. next_goal 要具体、可执行，能被拆成 3-7 个开发任务。\n"
        "4. 优先修复失败的功能（FEATURE_CHECKLIST 里 status=failed 的项）。\n"
    )

    try:
        result = _invoke_structured(_make_llm("architect"), NextGoal, msg)
        return result.next_goal, result.goal_achieved, result.reasoning
    except Exception as e:  # noqa: BLE001
        # 兜底：GLM 失败时，基于方向 + 轮次数生成一个泛化目标
        return (
            f"继续推进产品方向「{direction}」的第 {len(rounds) + 1} 轮迭代，"
            f"完善尚未实现的功能或修复已知问题",
            False,
            f"(evolve fallback: {e})",
        )


# ---------- 成果摘要收集 ----------

def _collect_round_summary(
    round_num: int,
    factory_state: FactoryState,
) -> RoundSummary:
    """从 FactoryState 收集本轮成果摘要。"""
    completed_descs = [
        t.task.description for t in factory_state.completed[:10]
    ]
    artifacts = []
    # 记录产出文件/摘要
    for t in factory_state.completed:
        artifacts.append(t.summary[:200] if t.summary else t.task.id)

    summary = (
        f"完成 {len(factory_state.completed)} 个任务"
        + (f"，失败 {len(factory_state.failed)} 个" if factory_state.failed else "")
        + f"：{'; '.join(completed_descs[:5])}"
    )

    return RoundSummary(
        round_num=round_num,
        factory_id=factory_state.factory_id,
        product_goal=factory_state.product_goal,
        tasks_completed=len(factory_state.completed),
        tasks_failed=len(factory_state.failed),
        summary=summary,
        artifacts=artifacts,
    )


# ---------- SQLite 持久化 ----------

_LOOP_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS infinite_loops (
    loop_id TEXT PRIMARY KEY,
    direction TEXT NOT NULL,
    cwd TEXT NOT NULL,
    design_style TEXT NOT NULL DEFAULT 'auto',
    rounds_json TEXT NOT NULL DEFAULT '[]',
    max_rounds INTEGER NOT NULL DEFAULT 10,
    status TEXT NOT NULL DEFAULT 'running',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _ensure_loop_table(conn: sqlite3.Connection) -> None:
    conn.execute(_LOOP_TABLE_SQL)


def save_loop_state(state: InfiniteLoopState, db_path: str) -> None:
    """把无限循环状态写入 SQLite。"""
    with sqlite3.connect(db_path) as conn:
        _ensure_loop_table(conn)
        conn.execute(
            """
            INSERT INTO infinite_loops (
                loop_id, direction, cwd, design_style, rounds_json,
                max_rounds, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(loop_id) DO UPDATE SET
                direction=excluded.direction,
                cwd=excluded.cwd,
                design_style=excluded.design_style,
                rounds_json=excluded.rounds_json,
                max_rounds=excluded.max_rounds,
                status=excluded.status,
                updated_at=excluded.updated_at
            """,
            (
                state.loop_id,
                state.direction,
                state.cwd,
                state.design_style,
                json.dumps([r.model_dump() for r in state.rounds]),
                state.max_rounds,
                state.status,
                state.created_at,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def load_loop_state(loop_id: str, db_path: str) -> InfiniteLoopState | None:
    """从 SQLite 加载无限循环状态。"""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_loop_table(conn)
        cur = conn.execute(
            "SELECT * FROM infinite_loops WHERE loop_id = ?", (loop_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return InfiniteLoopState(
            loop_id=row["loop_id"],
            direction=row["direction"],
            cwd=row["cwd"],
            design_style=row["design_style"],
            rounds=[RoundSummary(**r) for r in json.loads(row["rounds_json"])],
            max_rounds=row["max_rounds"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def is_stop_requested(loop_id: str, db_path: str) -> bool:
    """检查用户是否请求停止（通过 stop flag 文件）。

    停止方式：创建文件 {cwd}/.flipped_stop_{loop_id}
    或设环境变量 FLIPPED_STOP_LOOP=loop_id
    """
    stop_file = os.environ.get("FLIPPED_STOP_FILE", "")
    if stop_file and os.path.exists(stop_file):
        return True
    env_stop = os.environ.get("FLIPPED_STOP_LOOP", "")
    if env_stop and (env_stop == loop_id or env_stop == "all"):
        return True
    return False


# ---------- 无限迭代主循环 ----------

# 可注入的工厂循环函数（测试用）
FactoryLoopFn = Callable[..., FactoryState]


def run_infinite_loop(
    direction: str,
    cwd: str,
    *,
    loop_id: str | None = None,
    design_style: str = "auto",
    max_rounds: int = 10,
    db_path: str = "data/infinite_loop.db",
    factory_db_path: str = "data/factory.db",
    factory_checkpoint_db_path: str = "data/factory_checkpoints.db",
    evolve_fn: Callable[..., tuple[str, bool, str]] | None = None,
    factory_loop_fn: FactoryLoopFn | None = None,
    planner=None,
    orchestrator_fn=None,
    event_bus=None,
) -> InfiniteLoopState:
    """无限迭代循环：基于方向自主演进产品，每轮完成后生成下一轮 roadmap。

    Args:
        direction: 产品方向（用户给的一句话方向）
        cwd: 工作目录
        design_style: UI/UX 设计风格（auto 自动推断）
        max_rounds: 最大轮次（预算上限，防无限空转）
        evolve_fn: 可注入的目标演进函数（测试用）
        factory_loop_fn: 可注入的工厂循环函数（测试用）

    停止条件：
    - 用户停止（FLIPPED_STOP_LOOP 环境变量或 stop 文件）
    - 达到 max_rounds
    - GLM 判定产品方向已完全达成
    """
    evolve = evolve_fn or _evolve_goal
    factory_loop = factory_loop_fn or run_factory_loop

    # 加载已有状态（支持崩溃恢复）
    state = load_loop_state(loop_id, db_path) if loop_id else None
    if state is None:
        loop_id = loop_id or f"loop-{uuid.uuid4().hex[:8]}"
        state = InfiniteLoopState(
            loop_id=loop_id,
            direction=direction,
            cwd=cwd,
            design_style=design_style,
            max_rounds=max_rounds,
        )
        save_loop_state(state, db_path)
        # M10.4-B：初始化长期记忆文件
        try:
            init_progress(cwd, direction, design_style)
        except Exception:
            pass
    else:
        if state.status == "infra_failure":
            # M18: infra_failure 恢复——集群恢复后续跑
            state.status = "running"
        elif state.status != "running":
            return state  # 已完成（goal_achieved/stopped/budget_exhausted）

    while state.status == "running":
        round_num = len(state.rounds) + 1

        # 检查停止条件
        if round_num > state.max_rounds:
            state.status = "budget_exhausted"
            save_loop_state(state, db_path)
            break

        if is_stop_requested(state.loop_id, db_path):
            state.status = "stopped"
            save_loop_state(state, db_path)
            break

        # 生成本轮目标（传 cwd 让演进者读取 FEATURE_CHECKLIST 长期记忆）
        # 兼容旧签名 evolve(direction, rounds)：若 evolve 不接受 cwd，回退调用
        try:
            goal, achieved, reasoning = evolve(state.direction, state.rounds, cwd=state.cwd)
        except TypeError:
            goal, achieved, reasoning = evolve(state.direction, state.rounds)
        if achieved:
            state.status = "goal_achieved"
            save_loop_state(state, db_path)
            break

        # 执行本轮工厂循环
        factory_db = factory_db_path.replace(".db", f"_{state.loop_id}_r{round_num}.db")
        factory_ckpt_db = factory_checkpoint_db_path.replace(
            ".db", f"_{state.loop_id}_r{round_num}.db"
        )
        factory_state = factory_loop(
            goal,
            cwd,
            design_style=state.design_style,
            db_path=factory_db,
            checkpoint_db_path=factory_ckpt_db,
            planner=planner,
            orchestrator_fn=orchestrator_fn,
            event_bus=event_bus,
        )

        # 收集本轮成果
        round_summary = _collect_round_summary(round_num, factory_state)
        state.rounds.append(round_summary)
        save_loop_state(state, db_path)

        # M17: infra_failure 早停——整轮全是 infra_failure（集群不可用）时立即停止，
        # 不浪费预算跑下一轮。重试集群故障毫无意义，等集群恢复后 resume 即可。
        if (
            round_summary.tasks_completed == 0
            and round_summary.tasks_failed > 0
            and all(
                r.stop_reason == "infra_failure"
                for r in factory_state.failed
            )
        ):
            state.status = "infra_failure"
            save_loop_state(state, db_path)
            break

        # M10.4-B：每轮结束追加 PROGRESS.md 章节 + 更新 checklist rounds_completed
        try:
            record_round(
                state.cwd, round_num, goal,
                tasks_completed=round_summary.tasks_completed,
                tasks_failed=round_summary.tasks_failed,
                summary=round_summary.summary,
            )
        except Exception:
            pass

    return state
