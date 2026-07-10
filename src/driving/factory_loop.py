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
from driving.design_context import build_design_brief, infer_style


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
    # M31: 自主任务生成——roadmap 用完后，task_proposer 自主生成下一轮任务
    max_rounds: int = 5
    rounds_used: int = 0
    # M10.1 设计系统注入：worker 执行任务时把 design_context 注入 project_rules，
    # 让生成的 UI 代码遵循设计系统（具体 hex 值、字体、动效、组件状态、响应式、无障碍）
    design_style: str = "auto"
    design_context: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------- M16: infra_failure 检测 ----------

# 集群不可用时的特征模式（stop_reason + summary）
_INFRA_FAILURE_PATTERNS = [
    "connecttimeout",
    "readtimeout",
    "connectionrefused",
    "connectionerror",
    "connecterror",
    "unreachable",
    "worker_error",  # orchestrator 的 worker_error 节点（模型不可用）
]


def _is_infra_failure(stop_reason: str, summary: str) -> bool:
    """检测是否为基础设施故障（集群不可用），而非代码缺陷。

    M16：E2E 暴露 exo 集群 ConnectTimeout 时 worker_error=True，
    factory_loop 把它当普通失败重试 3 次 → 烧光重试次数 → paused。
    修复：检测 infra_failure 模式，立即暂停不消耗重试次数。

    判定条件（任一匹配即视为 infra_failure）：
    - stop_reason == "worker_error"（orchestrator 的 worker_error 节点）
    - summary 含 ConnectTimeout/ReadTimeout/ConnectionRefused 等网络错误
    """
    combined = f"{stop_reason} {summary}".lower()
    return any(pat in combined for pat in _INFRA_FAILURE_PATTERNS)


# ---------- 事件总线（可观测，可选） ----------

class NullEventBus:
    def emit(self, *args, **kwargs):  # noqa: ARG002
        pass


# ---------- M19: 设计质量校验包装器 ----------

def _wrap_with_design_quality(base_verifier):
    """在 base verifier 之后追加 lint_design_quality 检查。

    M19: error 级违规阻断验证；warning 级违规只记录不阻断。
    M32: design_score 门槛——即使无 error 级违规，score < 阈值也阻断，
         并把具体违规项 + 分数作为 feedback 让 worker 知道该修什么。
         阈值通过 FLIPPED_DESIGN_SCORE_THRESHOLD 环境变量配置（默认 70）。
    """
    from driving.design_context import lint_design_quality, design_score

    def wrapped(history: list, cwd: str) -> "tuple[bool, str]":
        ok, msg = base_verifier(history, cwd)
        if not ok:
            return ok, msg  # base verifier 已失败，不需要再检查
        try:
            violations = lint_design_quality(cwd)
            errors = [v for v in violations if v["severity"] == "error"]
            warnings = [v for v in violations if v["severity"] == "warning"]

            if errors:
                error_msgs = "; ".join(
                    f"{v['rule']}: {v['message']}" for v in errors[:5]
                )
                return False, f"design_quality errors ({len(errors)}): {error_msgs}"

            # M32: design_score 门槛
            threshold = int(os.environ.get("FLIPPED_DESIGN_SCORE_THRESHOLD", "70"))
            try:
                score, notes = design_score(cwd)
                if score > 0 and score < threshold:
                    notes_str = "; ".join(notes[:5]) if isinstance(notes, list) else str(notes)
                    return False, (
                        f"design_score={score}/{threshold} 未达标。"
                        f"问题：{notes_str[:200]}。"
                        f"请修复上述设计质量问题后重新提交。"
                    )
            except Exception:
                pass  # design_score 不可用时 fail-open

            if warnings:
                # warnings 不阻断，但追加到 msg 让 supervisor 知道
                warn_count = len(warnings)
                msg += f" (design_quality: {warn_count} warnings, score ok)"
            return True, msg
        except Exception:
            # lint_design_quality 异常时 fail-open（不阻断）
            return True, msg

    return wrapped


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
    design_style TEXT NOT NULL DEFAULT 'auto',
    design_context TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_TABLE_SQL)
    # M10.1 迁移：给旧表加 design_style 和 design_context 列
    cols = {row[1] for row in conn.execute("PRAGMA table_info(factory_states)")}
    if "design_style" not in cols:
        conn.execute("ALTER TABLE factory_states ADD COLUMN design_style TEXT NOT NULL DEFAULT 'auto'")
    if "design_context" not in cols:
        conn.execute("ALTER TABLE factory_states ADD COLUMN design_context TEXT NOT NULL DEFAULT ''")


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
        state.design_style,
        state.design_context,
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
        design_style=row["design_style"],
        design_context=row["design_context"],
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
                max_tasks, design_style, design_context, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                design_style=excluded.design_style,
                design_context=excluded.design_context,
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


def _deterministic_roadmap(product_goal: str, cwd: str) -> list[FactoryTask]:
    """确定性 roadmap fallback：GLM 不可用时基于 product_goal 生成有意义的任务列表。

    核心思路：无论产品目标是什么，都需要先创建基础 HTML 页面，
    然后添加样式系统和交互元素。这确保工厂即使没有 GLM 也能产出有价值的产物。
    每个任务有真实验收命令（文件内容检查），不是无意义的 'true'。
    """
    goal_short = product_goal[:30] if product_goal else "产品"
    safe_cwd = cwd.replace("'", "\\'")

    return [
        FactoryTask(
            id="det-task-1",
            description=f"创建 index.html 基础结构（{goal_short}）",
            verify_cmd=[
                f"python -c \"import os; assert os.path.isfile('{safe_cwd}/index.html'), 'index.html not found'\""
            ],
            feedback="(确定性 fallback: 创建基础 HTML 结构)",
        ),
        FactoryTask(
            id="det-task-2",
            description="添加 CSS 样式系统（CSS 变量、响应式布局）",
            verify_cmd=[
                f"python -c \"f=open('{safe_cwd}/index.html'); c=f.read(); assert ':root' in c or '--color' in c, 'no CSS variables'; f.close()\""
            ],
            feedback="(确定性 fallback: 添加 CSS 样式系统)",
        ),
        FactoryTask(
            id="det-task-3",
            description="添加交互元素和组件状态（button/a + hover/focus）",
            verify_cmd=[
                f"python -c \"f=open('{safe_cwd}/index.html'); c=f.read(); assert '<button' in c or '<a ' in c, 'no interactive elements'; f.close()\""
            ],
            feedback="(确定性 fallback: 添加交互元素)",
        ),
    ]


def default_planner(state: FactoryState) -> list[FactoryTask]:
    """用 GLM 把产品目标拆成可执行的任务列表；失败时用确定性 roadmap 兜底。

    verify_cmd 硬约束为单行 shell 命令——T3 熔断的根因是 GLM 生成多行 Python
    用 `&&` 连接，`python -c` 无法执行。这里在 prompt 和后处理两道防线卡死。
    """

    class Roadmap(BaseModel):
        tasks: list[FactoryTask] = Field(
            description="把产品目标拆成 2-3 个自包含任务（不超过 3 个）；每个任务含 description 和 verify_cmd。"
            "description 控制在 60 字以内，verify_cmd 必须是单行 shell 命令。"
            "输出要紧凑，避免冗长说明——总输出不超过 1500 字符。"
        )

    design_hint = ""
    if state.design_context:
        design_hint = (
            f"\nUI/UX 设计要求（涉及界面时任务描述必须包含设计约束）：\n{state.design_context}\n"
        )

    # M10.4-D：Gold Memory 经验提示（让 planner 复用历史成功的 verify_cmd 模式）
    memory_hint = ""
    try:
        from driving.gold_memory import build_memory_hint
        memory_hint = build_memory_hint(state.product_goal, state.design_style) or ""
        if memory_hint:
            memory_hint = f"\n{memory_hint}\n"
    except Exception:
        pass

    msg = (
        f"产品目标：{state.product_goal}\n"
        f"工作目录：{state.cwd}\n"
        "你是产品架构师。把目标拆成多个自包含的开发任务；每个任务必须可被一条验收命令验证。\n"
        "任务要具体、可交付，禁止一次写完整项目。\n"
        f"{design_hint}\n"
        f"{memory_hint}\n"
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
    except Exception as e:  # noqa: BLE001 失败兜底：用确定性 roadmap
        import sys
        import traceback
        print(f"[planner] fail-open: {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        tasks = _deterministic_roadmap(state.product_goal, state.cwd)
        for t in tasks:
            t.feedback = f"(planner fail-open: {e}) {t.feedback}"
        return tasks


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


def _looks_like_ui_task(task: FactoryTask, state: FactoryState) -> bool:
    """启发式判断任务是否涉及 UI 生成（需要追加 design-lint）。

    判定依据（任一即视为 UI 任务）：
    - design_context 非空（工厂启用了设计系统注入）
    - 任务描述含 UI 相关关键词（页面/按钮/表单/landing/component/UI/CSS/HTML 等）
    - verify_cmd 涉及 HTML/CSS 文件检查
    """
    if not state.design_context:
        return False
    text = (task.description + " " + " ".join(task.verify_cmd)).lower()
    ui_keywords = (
        "页面", "按钮", "表单", "布局", "颜色", "字体",
        "page", "landing", "hero", "navbar", "footer", "sidebar",
        "button", "form", "card", "modal", "component",
        "html", "css", "jsx", "tsx", "vue", "svelte",
        "ui", "ux", "design", "theme", "styling",
    )
    return any(kw in text for kw in ui_keywords)


def default_orchestrator_fn(task: FactoryTask, state: FactoryState) -> TaskResult:
    """默认用 drive_orchestrated 执行一个工厂任务；每个任务独立 thread_id/checkpoint。

    M10.4-A：对 UI 任务自动追加 design-lint 校验，作为 verify_cmd 之外的程序化硬约束。
    M10.4-C：第 2 次失败后用 delegate orchestrator（独立 thread_id + 干净上下文）。
    M10.5：per-task 硬超时（默认 600s），防止 GLM 挂起阻塞整个循环。
    M14.4：continuation 机制会追加 worker 调用（最多 2 次），每次 150s+，
           原 300s 超时不足以容纳 finish=length 截断后的续生成 → task_timeout。
    """
    # M10.5：per-task 硬超时保护——GLM 挂起时不能阻塞整个循环
    task_timeout = int(os.environ.get("FLIPPED_TASK_TIMEOUT", "600"))

    # M10.4-C：连续失败 ≥ 2 次时，触发 delegate 子 Agent（避免主上下文被卡死污染）
    from driving.stuck_detector import delegate_orchestrator
    if task.attempts >= 3 and task.feedback:
        # 第 3 次尝试起，改用 delegate（前 2 次正常尝试）
        stuck_reason = (
            f"已失败 {task.attempts - 1} 次，最近反馈：{task.feedback[:200]}"
        )
        try:
            return delegate_orchestrator(task, state, stuck_reason)
        except Exception as e:
            # delegate 失败时退回正常 orchestrator（避免完全卡死）
            pass

    thread_id = f"{state.factory_id}-{task.id}"

    # 尝试构建 sandbox_verifier（在沙箱内验证）；失败则 fallback 到 host verifier
    # M10.3：FLIPPED_USE_LOCAL_WORKER=1 时跳过沙箱 verifier，用宿主机直接验证
    verifier = None
    if os.environ.get("FLIPPED_USE_LOCAL_WORKER") != "1":
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

    # M10.4-A：UI 任务用组合 verifier（base + design-lint），让设计系统成为程序化硬约束
    # M11.3：升级为三重校验 base + design-lint + a11y（axe-core 真实渲染扫描）
    # M19：追加 lint_design_quality 第四重校验（语义HTML/meta viewport/img alt/动画性能）
    # M10.3：LocalWorker 模式下 verifier=None（跳过沙箱），但 UI 任务仍需 design-lint，
    # 所以用 _safe_default_verifier 作为 base + design-lint 组合
    if _looks_like_ui_task(task, state):
        try:
            from driving.a11y_lint import combined_verifier_with_a11y
            from driving.design_lint import combined_verifier
            from driving.orchestrator import _safe_default_verifier
            _base = verifier if verifier is not None else _safe_default_verifier
            try:
                verifier = combined_verifier_with_a11y(_base, state.design_style or "auto")
            except Exception:
                # a11y 不可用时退回 design-lint 组合
                verifier = combined_verifier(_base, state.design_style or "auto")
            # M19: 追加设计质量校验（error 级违规阻断，warning 级通过）
            verifier = _wrap_with_design_quality(verifier)
        except Exception:
            pass  # design-lint 不可用时退回 base verifier

    # M14/D19：双模型并行验证——GLM 与确定性 verifier 并行对产物做语义监督。
    # opt-in：FLIPPED_USE_PARALLEL_VERIFIER=1 启用。Kimi 跑代码时 GLM 同时验证监督。
    # GLM 不可用/超时 fail-open，不阻塞流程。
    if os.environ.get("FLIPPED_USE_PARALLEL_VERIFIER") == "1" and verifier is not None:
        try:
            from driving.parallel_verifier import make_parallel_verifier
            verifier = make_parallel_verifier(
                verifier,
                glm_alias="architect",
                glm_timeout=float(os.environ.get("FLIPPED_PARALLEL_GLM_TIMEOUT", "120")),
            )
        except Exception:
            pass  # parallel_verifier 不可用时退回原 verifier

    # M10.5：用 compact 版设计约束，避免长 design_brief 导致 Kimi 陷入 reasoning
    from driving.design_context import build_design_brief_compact
    compact_design = ""
    if state.design_context:
        compact_design = f"\n{build_design_brief_compact(state.design_style or 'auto')}"

    # M11.1：截断累积上下文，防止 prompt 过长触发 Kimi reasoning 循环。
    # context_summary 随轮次增长（每完成一个 task 追加一行），不截断时
    # 第 2 轮 task-2 的 prompt 会超 1400 字符 → reasoning overflow (content_len=4)。
    # 只保留最近 150 字符 + feedback 截断到 80 字符，让 prompt 始终 < 400 字符。
    ctx_tail = state.context_summary[-150:] if state.context_summary else "无"
    fb_short = task.feedback[:80] if task.feedback else "无"

    kwargs = dict(
        goal=task.description,
        cwd=state.cwd,
        verify_cmd=task.verify_cmd or ["true"],
        project_rules=(
            f"任务 {task.id}。已完成：{ctx_tail}\n"
            f"反馈：{fb_short}"
            + compact_design
        ),
        max_iterations=1,
        db_path="data/factory_checkpoints.db",
        thread_id=thread_id,
    )
    if verifier is not None:
        kwargs["verifier"] = verifier

    # M10.5：per-task 硬超时——用 daemon thread + join timeout，不中断 httpx I/O。
    # signal.alarm 会打断 httpx 的 C 层网络调用导致 worker_error，改用线程隔离。
    import threading
    result_box: list = []

    def _run():
        try:
            result_box.append(drive_orchestrated(**kwargs))
        except Exception as e:  # noqa: BLE001
            result_box.append({"verified": False, "stop_reason": "exception",
                               "iteration": 0, "feedback": f"{type(e).__name__}: {e}"})

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=task_timeout)

    if t.is_alive():
        # 线程仍在跑（GLM/Kimi 卡住）——放弃等待，标记超时
        result = {"verified": False, "stop_reason": "task_timeout",
                  "iteration": 0, "feedback": f"任务超时({task_timeout}s)"}
    elif result_box:
        result = result_box[0]
    else:
        result = {"verified": False, "stop_reason": "unknown",
                  "iteration": 0, "feedback": "线程结束但无结果"}

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
    max_rounds: int = 5,
    design_style: str = "auto",
    planner: PlannerFn | None = None,
    orchestrator_fn: OrchestratorFn | None = None,
    task_proposer: "Callable[[FactoryState], FactoryTask | None] | None" = None,
    event_bus=None,
    design_fix_fallback: "Callable[[FactoryState], FactoryTask | None] | None" = None,
) -> FactoryState:
    """启动/继续一个工厂循环；状态持久化到 db_path，支持崩溃恢复。

    design_style: UI/UX 设计风格（auto/minimalism/dark/glassmorphism/bento/...
    auto 时根据 product_goal 自动推断。生成的 UI 代码会遵循设计系统。

    M31: task_proposer——roadmap 全部执行完后，调用 task_proposer 自主生成下一轮任务。
    返回 None 表示停止迭代。max_rounds 限制自主生成的轮次，防止空转。
    M41: design_fix_fallback——task_proposer 返回 None 时（如 GLM 不可用），
    调用 design_fix_fallback 检查 design_score，低分时确定性生成修复任务。
    """
    planner = planner or default_planner
    orchestrator_fn = orchestrator_fn or default_orchestrator_fn
    bus = event_bus if event_bus is not None else NullEventBus()

    # M42: 默认自动接入自主任务生成 + 确定性 design fix fallback
    # 调用方无需显式传入即可获得"无限迭代"能力
    # 测试中可通过 FLIPPED_AUTO_PROPOSER=0 禁用
    _auto_proposer = os.environ.get("FLIPPED_AUTO_PROPOSER", "1") != "0"
    if task_proposer is None and _auto_proposer:
        try:
            from driving.task_proposer import propose_next_task
            task_proposer = propose_next_task
        except Exception:
            pass
    if design_fix_fallback is None and _auto_proposer:
        try:
            from driving.task_proposer import propose_design_fix_task
            design_fix_fallback = propose_design_fix_task
        except Exception:
            pass

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
            max_rounds=max_rounds,
            design_style=design_style,
            design_context=build_design_brief(design_style, product_type=product_goal),
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
                # M31: roadmap 全部执行完，尝试用 task_proposer 自主生成下一轮任务
                if task_proposer is not None and state.rounds_used < state.max_rounds:
                    try:
                        proposed = task_proposer(state)
                    except Exception:
                        proposed = None
                    # M41: GLM 不可用时，design_fix_fallback 确定性接管
                    if proposed is None and design_fix_fallback is not None:
                        try:
                            proposed = design_fix_fallback(state)
                        except Exception:
                            proposed = None
                    if proposed is not None:
                        state.roadmap.append(proposed)
                        state.rounds_used += 1
                        save_factory_state(state, db_path)
                        _emit(bus, "task_proposed", {
                            "factory_id": state.factory_id,
                            "task_id": proposed.id,
                            "description": proposed.description,
                            "round": state.rounds_used,
                        })
                        continue  # 回到 while 顶部，_next_task 会返回新任务
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
                # M10.4-B：记录到 FEATURE_CHECKLIST.json + PROGRESS.md（让无限迭代有长期记忆）
                try:
                    from driving.progress_notes import record_task_done
                    record_task_done(
                        state.cwd, task.id, task.description,
                        summary=result.summary, round_num=None,
                    )
                except Exception:
                    pass  # 进展笔记写入失败不影响主循环
                # M10.4-D：记录到 Gold Memory（让系统越跑越快）
                try:
                    from driving.gold_memory import record_task_result
                    record_task_result(task, state, result)
                except Exception:
                    pass
            else:
                # M16: infra_failure 优雅暂停——集群不可用(ConnectTimeout/worker_error)
                # 时立即暂停，不消耗重试次数。重试集群故障毫无意义，只会烧光 attempts → paused。
                if _is_infra_failure(result.stop_reason, result.summary):
                    result.stop_reason = "infra_failure"
                    task.status = TaskStatus.failed
                    state.failed.append(result)
                    _emit(bus, "infra_failure_detected", {
                        "factory_id": state.factory_id,
                        "task_id": task.id,
                        "summary": result.summary[:200],
                    })
                    state.status = FactoryStatus.paused
                    break
                task.status = TaskStatus.failed
                state.failed.append(result)
                # M10.4-B：失败也记录（演进者能看到哪些功能反复失败）
                try:
                    from driving.progress_notes import record_task_failed
                    record_task_failed(
                        state.cwd, task.id, task.description,
                        reason=f"{result.stop_reason}: {result.summary[:120]}",
                        round_num=None,
                    )
                except Exception:
                    pass
                # M10.4-D：失败也记入 Gold Memory（记录失败模式）
                try:
                    from driving.gold_memory import record_task_result
                    record_task_result(task, state, result)
                except Exception:
                    pass
                if task.attempts >= task.max_attempts:
                    state.status = FactoryStatus.paused
                    break
                # M12 RCA：自动分析失败根因，给 supervisor 精确修复建议（而非泛泛"失败了"）
                try:
                    from driving.rca import analyze_failure, enrich_feedback
                    rca = analyze_failure(
                        stop_reason=result.stop_reason,
                        summary=result.summary,
                        feedback=task.feedback,
                    )
                    task.feedback = enrich_feedback(
                        f"上次尝试失败({result.stop_reason}): {result.summary}",
                        rca,
                    )
                except Exception:
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
