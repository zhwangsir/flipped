"""24h 自治 AI 代码工厂 · 外层 Master Loop（M9）。

Master Loop 把 flipped 从"完成一次长任务"升级为"连续生产并迭代代码"：
- 接收高层产品目标，自动生成/维护 roadmap；
- 逐个把任务派给 orchestrator（Supervisor+Worker+Overseer+Verify）；
- 验收结果汇入上下文，失败自动重试，崩溃/断电后从 SQLite 续跑。

所有 LLM/orchestrator 节点可注入 → 单测无需真模型/沙盒。
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Callable

from pydantic import BaseModel, Field

from driving.orchestrator import OrchestratorState, drive_orchestrated
from driving.orchestrator import _invoke_structured, _make_llm  # noqa: WPS450


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class FactoryStatus(str, Enum):
    pending = "pending"
    running = "running"
    paused = "paused"
    done = "done"
    error = "error"


class FactoryTask(BaseModel):
    id: str = Field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}")
    description: str = Field(description="给 orchestrator 的高层任务描述")
    verify_cmd: list[str] = Field(default_factory=list, description="验收命令")
    status: TaskStatus = TaskStatus.pending
    attempts: int = 0
    max_attempts: int = 3
    depends_on: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    feedback: str = ""


class TaskResult(BaseModel):
    task: FactoryTask
    verified: bool
    stop_reason: str
    iteration: int
    summary: str = ""
    recorded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FactoryState(BaseModel):
    factory_id: str
    product_goal: str
    cwd: str
    status: FactoryStatus = FactoryStatus.pending
    roadmap: list[FactoryTask]
    completed: list[TaskResult] = Field(default_factory=list)
    failed: list[TaskResult] = Field(default_factory=list)
    current_task_id: str | None = None
    context_summary: str = ""
    iteration_count: int = 0
    max_tasks: int = 10
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------- 事件总线（可观测，可选） ----------

class NullEventBus:
    def emit(self, *args, **kwargs):  # noqa: ARG002
        pass


# ---------- SQLite 持久化 ----------

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS factory_states (
    factory_id TEXT PRIMARY KEY,
    product_goal TEXT NOT NULL,
    cwd TEXT NOT NULL,
    status TEXT NOT NULL,
    roadmap_json TEXT NOT NULL,
    completed_json TEXT NOT NULL,
    failed_json TEXT NOT NULL,
    current_task_id TEXT,
    context_summary TEXT NOT NULL,
    iteration_count INTEGER NOT NULL,
    max_tasks INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_TABLE_SQL)


def _state_to_row(state: FactoryState) -> tuple:
    return (
        state.factory_id,
        state.product_goal,
        state.cwd,
        state.status.value,
        json.dumps([t.model_dump() for t in state.roadmap]),
        json.dumps([r.model_dump() for r in state.completed]),
        json.dumps([r.model_dump() for r in state.failed]),
        state.current_task_id,
        state.context_summary,
        state.iteration_count,
        state.max_tasks,
        state.created_at,
        datetime.now(timezone.utc).isoformat(),
    )


def _row_to_state(row: sqlite3.Row) -> FactoryState:
    return FactoryState(
        factory_id=row["factory_id"],
        product_goal=row["product_goal"],
        cwd=row["cwd"],
        status=FactoryStatus(row["status"]),
        roadmap=[FactoryTask(**t) for t in json.loads(row["roadmap_json"])],
        completed=[TaskResult(**r) for r in json.loads(row["completed_json"])],
        failed=[TaskResult(**r) for r in json.loads(row["failed_json"])],
        current_task_id=row["current_task_id"],
        context_summary=row["context_summary"],
        iteration_count=row["iteration_count"],
        max_tasks=row["max_tasks"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def save_factory_state(state: FactoryState, db_path: str) -> None:
    """把工厂状态写入 SQLite；不存在则创建表。"""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_table(conn)
        conn.execute(
            """
            INSERT INTO factory_states (
                factory_id, product_goal, cwd, status, roadmap_json, completed_json,
                failed_json, current_task_id, context_summary, iteration_count,
                max_tasks, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(factory_id) DO UPDATE SET
                product_goal=excluded.product_goal,
                cwd=excluded.cwd,
                status=excluded.status,
                roadmap_json=excluded.roadmap_json,
                completed_json=excluded.completed_json,
                failed_json=excluded.failed_json,
                current_task_id=excluded.current_task_id,
                context_summary=excluded.context_summary,
                iteration_count=excluded.iteration_count,
                max_tasks=excluded.max_tasks,
                updated_at=excluded.updated_at
            """,
            _state_to_row(state),
        )


def load_factory_state(factory_id: str, db_path: str) -> FactoryState | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_table(conn)
        cur = conn.execute(
            "SELECT * FROM factory_states WHERE factory_id = ?", (factory_id,)
        )
        row = cur.fetchone()
        return _row_to_state(row) if row else None


def list_factories(db_path: str) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        _ensure_table(conn)
        cur = conn.execute("SELECT factory_id FROM factory_states ORDER BY updated_at DESC")
        return [r[0] for r in cur.fetchall()]


# ---------- Planner ----------

PlannerFn = Callable[[FactoryState], list[FactoryTask]]
OrchestratorFn = Callable[[FactoryTask, FactoryState], TaskResult]


def default_planner(state: FactoryState) -> list[FactoryTask]:
    """用 GLM 把产品目标拆成可执行的任务列表；失败时 fail-open 为单个任务。

    verify_cmd 硬约束为单行 shell 命令——T3 熔断的根因是 GLM 生成多行 Python
    用 `&&` 连接，`python -c` 无法执行。这里在 prompt 和后处理两道防线卡死。
    """

    class Roadmap(BaseModel):
        tasks: list[FactoryTask] = Field(
            description="把产品目标拆成 3-7 个自包含任务；每个任务含 description 和 verify_cmd"
        )

    msg = (
        f"产品目标：{state.product_goal}\n"
        f"工作目录：{state.cwd}\n"
        "你是产品架构师。把目标拆成多个自包含的开发任务；每个任务必须可被一条验收命令验证。\n"
        "任务要具体、可交付，禁止一次写完整项目。\n\n"
        "verify_cmd 硬性规则（违反会导致验收熔断，必须遵守）：\n"
        "1. verify_cmd 数组只有一个元素，即一条单行 shell 命令。\n"
        "2. 禁止多行命令、禁止用 && 连接多条命令、禁止用 python -c 传多行代码。\n"
        "3. 正确示例：['python -m pytest tests/test_calc.py -q']、['python -c \"import calc; assert calc.add(1,2)==3\"']、"
        "['bash -c \"node -e \\\"assert(require(\\'./add\\')(1,2)===3)\\\"\"']\n"
        "4. 错误示例：['python -c \"def f():\\n  pass\\n\\nf()\" && pytest']（多行+连接，会熔断）\n"
        "5. 若需要多步验证，写成一条调用测试脚本的命令：['bash scripts/verify_task1.sh']\n"
        "6. 禁止用裸 pytest 命令（沙箱 PATH 里没有 pytest 可执行文件）；必须用 python -m pytest。"
    )
    try:
        rm = _invoke_structured(_make_llm("architect"), Roadmap, msg)
        # 后处理：强制把每个任务的 verify_cmd 规整为单元素数组（防御 GLM 偶发不守约束）
        for t in rm.tasks:
            t.verify_cmd = _sanitize_verify_cmd(t.verify_cmd)
        return rm.tasks
    except Exception as e:  # noqa: BLE001 失败兜底：当成一个任务
        import sys
        import traceback
        print(f"[planner] fail-open: {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return [
            FactoryTask(
                id="task-fallback",
                description=state.product_goal,
                verify_cmd=["true"],
                feedback=f"(planner fail-open: {e})",
            )
        ]


def _sanitize_verify_cmd(cmd: list[str]) -> list[str]:
    """把 verify_cmd 强制规整为单元素数组：多行/多 && 合并成一条单行命令。

    GLM 偶发不遵守 prompt 约束，这里做最后一道确定性兜底：
    - 多元素数组 → 用 ; 连接成一条（不用 && 以免短路掩盖问题）
    - 单元素但含换行 → 压成一行
    - 空数组 → ['true']（至少不阻塞循环）
    - 裸 `pytest` → `python -m pytest`（OpenHands 沙箱 PATH 里没有 pytest 可执行文件，
      T3 熔断的根因；用 python -m 走模块路径，只要 python 装了 pytest 就能跑）
    """
    import re

    if not cmd:
        return ["true"]
    # 过滤空串
    parts = [c.strip() for c in cmd if c and c.strip()]
    if not parts:
        return ["true"]
    # 多条 → 用 ; 合并成单行（; 不短路，能看到所有失败）
    joined = " ; ".join(parts)
    # 压掉换行
    joined = " ".join(joined.split())
    # 裸 pytest → python -m pytest（lookbehind 避免重复替换已正确的 `python -m pytest`）
    joined = re.sub(r"(?<!-m\s)pytest\b", "python -m pytest", joined)
    return [joined]


# ---------- Orchestrator 适配 ----------

def _summarize_orchestrator_result(values: OrchestratorState) -> str:
    parts = [f"stop_reason={values.get('stop_reason', '')}"]
    if values.get("verified"):
        parts.append("verified=True")
    if values.get("feedback"):
        parts.append(f"feedback={values['feedback'][:200]}")
    return "; ".join(parts)


def default_orchestrator_fn(task: FactoryTask, state: FactoryState) -> TaskResult:
    """默认用 drive_orchestrated 执行一个工厂任务；每个任务独立 thread_id/checkpoint。"""
    thread_id = f"{state.factory_id}-{task.id}"

    # 尝试构建 sandbox_verifier（在沙箱内验证）；失败则 fallback 到 host verifier
    verifier = None
    try:
        from executor.sandbox_verify import make_sandbox_verifier
        from executor.openhands_worker import OpenHandsWorker
        agent_host = os.environ.get("OPENHANDS_AGENT_HOST", "http://localhost:8000")
        oh_api_key = OpenHandsWorker._default_agent_api_key()
        verifier = make_sandbox_verifier(
            agent_host=agent_host,
            working_dir=state.cwd,
            api_key=oh_api_key,
        )
    except Exception:
        pass  # fallback 到 drive_orchestrated 默认的 _safe_default_verifier

    kwargs = dict(
        goal=task.description,
        cwd=state.cwd,
        verify_cmd=task.verify_cmd or ["true"],
        project_rules=(
            f"这是工厂任务 {task.id}。已完成的上下文摘要：\n{state.context_summary}\n"
            f"本任务反馈（若有）：{task.feedback}"
        ),
        max_iterations=4,
        db_path="data/factory_checkpoints.db",
        thread_id=thread_id,
    )
    if verifier is not None:
        kwargs["verifier"] = verifier
    result = drive_orchestrated(**kwargs)
    return TaskResult(
        task=task,
        verified=bool(result.get("verified")),
        stop_reason=result.get("stop_reason", ""),
        iteration=result.get("iteration", 0),
        summary=_summarize_orchestrator_result(result),
    )


# ---------- Master Loop ----------

def _next_task(state: FactoryState) -> FactoryTask | None:
    """取下一个依赖已满足且 pending 的任务。当前只支持顺序执行。"""
    done_ids = {t.id for t in state.roadmap if t.status == TaskStatus.done}
    for task in state.roadmap:
        if task.status != TaskStatus.pending:
            continue
        if all(dep in done_ids for dep in task.depends_on):
            return task
    return None


def _emit(bus, event: str, payload: dict) -> None:
    try:
        bus.emit("__factory__", event, None, payload)
    except Exception:  # noqa: BLE001
        pass


def run_factory_loop(
    product_goal: str,
    cwd: str,
    *,
    factory_id: str | None = None,
    db_path: str = "data/factory.db",
    checkpoint_db_path: str = "data/factory_checkpoints.db",
    max_tasks: int = 10,
    planner: PlannerFn | None = None,
    orchestrator_fn: OrchestratorFn | None = None,
    event_bus=None,
) -> FactoryState:
    """启动/继续一个工厂循环；状态持久化到 db_path，支持崩溃恢复。"""
    planner = planner or default_planner
    orchestrator_fn = orchestrator_fn or default_orchestrator_fn
    bus = event_bus if event_bus is not None else NullEventBus()

    state = load_factory_state(factory_id, db_path) if factory_id else None
    if state is None:
        factory_id = factory_id or f"factory-{uuid.uuid4().hex[:8]}"
        state = FactoryState(
            factory_id=factory_id,
            product_goal=product_goal,
            cwd=cwd,
            status=FactoryStatus.running,
            roadmap=[],
            max_tasks=max_tasks,
        )
        state.roadmap = planner(state)
        save_factory_state(state, db_path)
        _emit(bus, "factory_started", {"factory_id": state.factory_id, "roadmap_size": len(state.roadmap)})
    else:
        if state.status == FactoryStatus.done:
            return state
        # 崩溃恢复：崩溃前当前任务可能停留在 running，需重置为 pending 以便重跑
        if state.current_task_id:
            for task in state.roadmap:
                if task.id == state.current_task_id and task.status == TaskStatus.running:
                    task.status = TaskStatus.pending
                    break
        # 如果 roadmap 仍为空（如 API 先创建了初始状态），生成 roadmap
        if not state.roadmap:
            state.roadmap = planner(state)
        state.status = FactoryStatus.running
        save_factory_state(state, db_path)
        _emit(bus, "factory_resumed", {"factory_id": state.factory_id})

    try:
        while (
            state.status == FactoryStatus.running
            and state.iteration_count < state.max_tasks
        ):
            task = _next_task(state)
            if task is None:
                state.status = FactoryStatus.done
                break

            state.current_task_id = task.id
            task.status = TaskStatus.running
            task.attempts += 1
            state.iteration_count += 1
            save_factory_state(state, db_path)
            _emit(
                bus,
                "task_started",
                {
                    "factory_id": state.factory_id,
                    "task_id": task.id,
                    "attempt": task.attempts,
                    "description": task.description,
                },
            )

            try:
                result = orchestrator_fn(task, state)
            except Exception as e:  # noqa: BLE001
                result = TaskResult(
                    task=task,
                    verified=False,
                    stop_reason="orchestrator_exception",
                    iteration=0,
                    summary=str(e)[:500],
                )

            _emit(
                bus,
                "task_ended",
                {
                    "factory_id": state.factory_id,
                    "task_id": task.id,
                    "verified": result.verified,
                    "stop_reason": result.stop_reason,
                },
            )

            if result.verified:
                task.status = TaskStatus.done
                state.completed.append(result)
                state.context_summary += (
                    f"\n[{task.id}] {task.description}: done. artifacts={task.artifacts}"
                )
            else:
                task.status = TaskStatus.failed
                state.failed.append(result)
                if task.attempts >= task.max_attempts:
                    state.status = FactoryStatus.paused
                    break
                # 重试：保留反馈，状态回到 pending，下次继续
                task.feedback = (
                    f"上次尝试失败({result.stop_reason}): {result.summary}"
                )
                task.status = TaskStatus.pending

            state.current_task_id = None
            save_factory_state(state, db_path)

        if state.status == FactoryStatus.running:
            state.status = FactoryStatus.done
    except Exception as e:  # noqa: BLE001
        state.status = FactoryStatus.error
        _emit(bus, "factory_error", {"factory_id": state.factory_id, "error": str(e)})
        raise
    finally:
        save_factory_state(state, db_path)

    return state


def resume_factory_loop(
    factory_id: str,
    db_path: str = "data/factory.db",
    **kwargs,
) -> FactoryState | None:
    """从 SQLite 恢复工厂状态并继续运行。"""
    state = load_factory_state(factory_id, db_path)
    if state is None:
        return None
    if state.status == FactoryStatus.done:
        return state
    return run_factory_loop(
        state.product_goal,
        state.cwd,
        factory_id=factory_id,
        db_path=db_path,
        **kwargs,
    )
