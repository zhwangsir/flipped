"""24h 自治 AI 代码工厂 · REST API 端点（M9.6）。

把 factory_loop 的 Master Loop 暴露为 HTTP 端点，让 Console 可启动/监控/恢复工厂。
工厂在后台 asyncio.to_thread 中运行，状态持久化到 SQLite。
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from driving.factory_loop import (
    FactoryRcaEntry,
    FactoryState,
    FactoryStatus,
    TaskResult,
    TaskStatus,
    list_factories,
    load_factory_state,
    resume_factory_loop,
    run_factory_loop,
    save_factory_state,
)

router = APIRouter(prefix="/api/v1/factories", tags=["factory"])

# 运行中的工厂任务句柄（factory_id -> asyncio.Task）
_RUNNING: dict[str, asyncio.Task] = {}

FACTORY_DB = os.environ.get("FLIPPED_FACTORY_DB", "data/factory.db")


# ---------- Schemas ----------


class CreateFactoryRequest(BaseModel):
    product_goal: str = Field(..., description="高层产品目标")
    cwd: str | None = Field(None, description="工作目录（默认=活动项目沙盒路径）")
    max_tasks: int = Field(10, ge=1, le=100, description="最大任务数")


class FactorySummary(BaseModel):
    factory_id: str
    product_goal: str
    cwd: str
    status: str
    total_tasks: int
    completed: int
    failed: int
    current_task_id: str | None = None
    iteration_count: int
    max_tasks: int
    created_at: str
    updated_at: str


# ---------- 辅助 ----------


def _to_summary(state: FactoryState) -> FactorySummary:
    return FactorySummary(
        factory_id=state.factory_id,
        product_goal=state.product_goal,
        cwd=state.cwd,
        status=state.status.value,
        total_tasks=len(state.roadmap),
        completed=len(state.completed),
        failed=len(state.failed),
        current_task_id=state.current_task_id,
        iteration_count=state.iteration_count,
        max_tasks=state.max_tasks,
        created_at=state.created_at,
        updated_at=state.updated_at,
    )


def _resolve_cwd(explicit: str | None) -> str:
    if explicit:
        return explicit
    # 默认=活动项目沙盒路径
    try:
        from api import project_state as ps
        cwd = ps.sandbox_cwd()
        if cwd:
            return cwd
    except Exception:
        pass
    return "/workspace"


class _BusAdapter:
    """把 factory_loop 的 _emit 调用桥接到 FastAPI EventBus。"""

    def __init__(self, bus, factory_id: str):
        self._bus = bus
        self._factory_id = factory_id

    def emit(self, _channel: str, event: str, _agent, payload: dict[str, Any]) -> None:
        from api.schemas import EventType, Role
        type_map = {
            "factory_started": EventType.status,
            "factory_resumed": EventType.status,
            "factory_error": EventType.error,
            "task_started": EventType.status,
            "task_ended": EventType.status,
        }
        et = type_map.get(event, EventType.message)
        try:
            self._bus.emit(self._factory_id, et, Role.system, {
                "factory_event": event,
                **payload,
            })
        except Exception:
            pass


# ---------- 端点 ----------


@router.post("", response_model=FactorySummary)
async def create_factory(req: CreateFactoryRequest) -> FactorySummary:
    """启动一个新的 24h 工厂循环。"""
    factory_id = f"factory-{uuid.uuid4().hex[:8]}"
    cwd = _resolve_cwd(req.cwd)

    # 同步生成初始状态（含 planner 调用），避免后台线程还没跑就查不到
    state = FactoryState(
        factory_id=factory_id,
        product_goal=req.product_goal,
        cwd=cwd,
        status=FactoryStatus.running,
        roadmap=[],
        max_tasks=req.max_tasks,
    )
    save_factory_state(state, FACTORY_DB)

    # 后台线程运行 Master Loop
    from api.main import bus
    adapter = _BusAdapter(bus, factory_id)

    async def _run():
        try:
            await asyncio.to_thread(
                run_factory_loop,
                req.product_goal,
                cwd,
                factory_id=factory_id,
                db_path=FACTORY_DB,
                max_tasks=req.max_tasks,
                event_bus=adapter,
            )
        except Exception as exc:  # noqa: BLE001
            state = load_factory_state(factory_id, FACTORY_DB)
            if state:
                state.status = FactoryStatus.error
                save_factory_state(state, FACTORY_DB)
            from api.schemas import EventType, Role
            bus.emit(factory_id, EventType.error, Role.system,
                     {"message": f"Factory crashed: {exc}"})
        finally:
            _RUNNING.pop(factory_id, None)

    task = asyncio.create_task(_run())
    _RUNNING[factory_id] = task

    loaded = load_factory_state(factory_id, FACTORY_DB)
    return _to_summary(loaded or state)


@router.get("", response_model=list[FactorySummary])
async def list_factories_endpoint() -> list[FactorySummary]:
    """列出所有工厂（按更新时间倒序）。"""
    ids = list_factories(FACTORY_DB)
    out: list[FactorySummary] = []
    for fid in ids:
        st = load_factory_state(fid, FACTORY_DB)
        if st:
            out.append(_to_summary(st))
    return out


@router.get("/{factory_id}", response_model=FactorySummary)
async def get_factory(factory_id: str) -> FactorySummary:
    """获取单个工厂的状态。"""
    state = load_factory_state(factory_id, FACTORY_DB)
    if state is None:
        raise HTTPException(status_code=404, detail="factory not found")
    return _to_summary(state)


@router.get("/{factory_id}/detail")
async def get_factory_detail(factory_id: str) -> dict[str, Any]:
    """获取工厂完整状态（含 roadmap/completed/failed 详情）。"""
    state = load_factory_state(factory_id, FACTORY_DB)
    if state is None:
        raise HTTPException(status_code=404, detail="factory not found")
    return state.model_dump(mode="json")


@router.get("/{factory_id}/rca_history")
async def get_factory_rca_history(factory_id: str) -> dict[str, Any]:
    """M100 — 返回工厂级 RCA 历史聚合视图。

    每次 verify 失败触发 analyze_failure_with_memory 后,
    RCA 结果被追加到 FactoryState.rca_history。本端点返回完整历史 + cause_stats 分布。

    fail-open 原则:任何异常都返回空列表,不阻塞 factory 主流程。

    Returns:
        {
            "factory_id": "xxx",
            "rca_history": [{cause, confidence, fix_suggestion, ...}],
            "cause_stats": {"syntax_error": 2, "timeout": 1}
        }
    """
    state = load_factory_state(factory_id, FACTORY_DB)
    if state is None:
        raise HTTPException(status_code=404, detail="factory not found")

    # fail-open: rca_history 字段缺失或损坏时返回空列表
    try:
        rca_history = state.rca_history or []
        entries = [r.model_dump(mode="json") for r in rca_history]
    except Exception:
        entries = []

    # 聚合 cause_stats
    cause_stats: dict[str, int] = {}
    for entry in entries:
        cause = str(entry.get("cause", "unknown"))
        cause_stats[cause] = cause_stats.get(cause, 0) + 1

    return {
        "factory_id": factory_id,
        "rca_history": entries,
        "cause_stats": cause_stats,
    }


@router.get("/{factory_id}/quality-trend")
async def get_factory_quality_trend(factory_id: str) -> dict[str, Any]:
    """M135-B — 返回工厂质量趋势视图,前端 FactoryPanel 画曲线。

    每次 task 完成(verified=True)时,grade_quality 打分被追加到 FactoryState.quality_history。
    本端点返回趋势分析(direction/delta/latest_grade) + 完整历史(前端画迷你曲线)。

    fail-open 原则:任何异常都返回空历史 + insufficient_data,不阻塞 factory 主流程。

    Returns:
        {
            "factory_id": "xxx",
            "trend": {"direction": "improving", "delta": 5.2, "latest_grade": "A", ...},
            "history": [{"task_id": "t1", "timestamp": "...", "score": {...}}]
        }
    """
    state = load_factory_state(factory_id, FACTORY_DB)
    if state is None:
        raise HTTPException(status_code=404, detail="factory not found")

    # fail-open: quality_history 字段缺失或损坏时返回空列表
    try:
        history = state.quality_history or []
    except Exception:
        history = []

    # 趋势分析:把 dict 转回 QualityScore 给 get_quality_trend 消费
    try:
        from driving.quality_grading import QualityScore, get_quality_trend
        scores = []
        for entry in history:
            try:
                score_dict = entry.get("score", {})
                # QualityScore 是 dataclass,从 dict 重建(grade 字段是 str,要转回 enum)
                from driving.quality_grading import QualityGrade
                if "grade" in score_dict and isinstance(score_dict["grade"], str):
                    score_dict["grade"] = QualityGrade(score_dict["grade"])
                scores.append(QualityScore(**score_dict))
            except Exception:
                continue  # 单条损坏跳过,不影响整体
        trend = get_quality_trend(scores)
    except Exception:
        trend = {"direction": "unknown", "improvement_rate": 0.0, "message": "趋势分析异常"}

    return {
        "factory_id": factory_id,
        "trend": trend,
        "history": history,
    }


@router.post("/{factory_id}/resume", response_model=FactorySummary)
async def resume_factory(factory_id: str) -> FactorySummary:
    """恢复一个暂停/崩溃的工厂。"""
    state = load_factory_state(factory_id, FACTORY_DB)
    if state is None:
        raise HTTPException(status_code=404, detail="factory not found")
    if state.status == FactoryStatus.done:
        return _to_summary(state)
    # 已在运行则不重复启动
    existing = _RUNNING.get(factory_id)
    if existing and not existing.done():
        return _to_summary(state)

    from api.main import bus
    adapter = _BusAdapter(bus, factory_id)

    async def _run():
        try:
            await asyncio.to_thread(
                resume_factory_loop,
                factory_id,
                FACTORY_DB,
                event_bus=adapter,
            )
        except Exception as exc:  # noqa: BLE001
            st = load_factory_state(factory_id, FACTORY_DB)
            if st:
                st.status = FactoryStatus.error
                save_factory_state(st, FACTORY_DB)
            from api.schemas import EventType, Role
            bus.emit(factory_id, EventType.error, Role.system,
                     {"message": f"Factory resume crashed: {exc}"})
        finally:
            _RUNNING.pop(factory_id, None)

    task = asyncio.create_task(_run())
    _RUNNING[factory_id] = task

    return _to_summary(state)


@router.post("/{factory_id}/pause", response_model=FactorySummary)
async def pause_factory(factory_id: str) -> FactorySummary:
    """暂停一个运行中的工厂（取消后台任务，状态保存为 paused）。"""
    state = load_factory_state(factory_id, FACTORY_DB)
    if state is None:
        raise HTTPException(status_code=404, detail="factory not found")
    task = _RUNNING.get(factory_id)
    if task and not task.done():
        task.cancel()
    _RUNNING.pop(factory_id, None)
    state.status = FactoryStatus.paused
    save_factory_state(state, FACTORY_DB)
    return _to_summary(state)
