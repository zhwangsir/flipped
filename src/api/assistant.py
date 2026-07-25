"""M151.1 · 代码助手 assistant router。

在既有 :8011 orchestration API 之上叠加一层「对话式代码助手」路由：
- POST /api/v1/assistant/sessions              创建助手会话（默认 mode=agent）
- POST /api/v1/assistant/sessions/{id}/messages 发送消息，返回 task_id
- POST /api/v1/assistant/sessions/{id}/approve  审批放行
- POST /api/v1/assistant/sessions/{id}/reject   审批否决
- GET  /api/v1/assistant/sessions/{id}/history  事件流折叠成对话 turns

设计原则（按 M151 计划）：
- 纯增量：不重写 _run_orchestrator / _run_chat / RUNNING_TASKS / bus / store / ps
- 函数级 lazy import：不在模块级 `from .main import ...`，否则 main.py 反向
  `from .assistant import router` 时本模块只执行到 import 行，router 虽已创建但
  所有 @router.post 装饰器尚未执行 → app.include_router 注册的是空 router。
  函数级 import 在端点被调用时才取 main 的符号，此时 main 已完整加载。
  monkeypatch 目标改为 api.main._run_chat（源头），_resume_with_decision 留在
  本模块（模块级名，monkeypatch api.assistant._resume_with_decision 生效）。
- 端点全部 async def：asyncio.create_task 需在事件循环线程内调用
- 并发守卫复用 RUNNING_TASKS（409）
- mode 路由：auto/agent → _run_orchestrator（require_approval=True）；chat/plan → _run_chat
- _resume_with_decision 本文件为 stub（M151.1 仅更新状态 + emit），
  M151.2 接通真实 resume_orchestrated(resume_value=decision)
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .schemas import Event, EventType, Role, Session, SessionStatus, TaskRequest

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


# ---------- 数据模型 ----------

_ALLOWED_MODES = {"auto", "agent", "chat", "plan"}


class CreateSessionRequest(BaseModel):
    """创建助手会话请求。"""
    title: str = "新对话"
    mode: str = "agent"
    cwd: str | None = None
    model_alias: str = "coder"


class SendMessageRequest(BaseModel):
    """发送消息请求。"""
    text: str = Field(..., min_length=1)
    mode: str | None = None
    model: str | None = None
    orchestrator: dict[str, Any] | None = None


class MessageResponse(BaseModel):
    task_id: str
    session_id: str


class DecisionResponse(BaseModel):
    """approve/reject 端点响应：决策已受理 + 异步 resume 派发。"""
    ok: bool
    session_id: str
    decision: str


class AssistantTurn(BaseModel):
    """对话 turn 视图：把事件流折叠成 user/assistant/tool/approval 四类。"""
    role: str                       # user | assistant | tool | approval
    text: str | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    verdict: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
    created_at: str

    model_config = ConfigDict(use_enum_values=True)


# ---------- 纯函数：事件流 → turns ----------

# supervisor/worker/overseer/verify 在工厂视角是不同角色，
# 在代码助手对话视角统一呈现为 "assistant"（用户不关心内部三角分工）
_ASSISTANT_ROLES = {"supervisor", "worker", "overseer", "verify"}


def _events_to_turns(events: list[Event]) -> list[AssistantTurn]:
    """把 Event 流折叠成对话 turns。

    折叠规则：
    - message(user) → turn{role=user, text}
    - message(supervisor/worker/overseer/verify) → turn{role=assistant, text}
    - tool_call + 紧随其后的 tool_result → 合并成 turn{role=tool, tools=[{tool,args,status,summary}]}
    - approval_request → turn{role=approval, approval=payload}
    - 其他类型（status/checkpoint/error/rca/verifier_verdict/plan/file_change/terminal/browser）
      暂不单独成 turn（前端可在工具卡内展示，避免对话流被系统事件淹没）
    """
    turns: list[AssistantTurn] = []
    pending_tool: dict[str, Any] | None = None

    def _flush_pending():
        nonlocal pending_tool
        if pending_tool is not None:
            turns.append(AssistantTurn(
                role="tool",
                tools=[pending_tool],
                created_at=pending_tool.get("_ts", datetime.now(timezone.utc).isoformat()),
            ))
            pending_tool = None

    for ev in events:
        # 用 ev.type 字符串比较，兼容 Event.type 是 EventType 或 str
        etype = ev.type.value if hasattr(ev.type, "value") else str(ev.type)
        agent = ev.agent.value if hasattr(ev.agent, "value") else (str(ev.agent) if ev.agent else None)
        ts = ev.created_at

        if etype == "message":
            _flush_pending()
            role = "user" if agent == "user" else "assistant"
            turns.append(AssistantTurn(
                role=role,
                text=ev.payload.get("text", ""),
                created_at=ts,
            ))
        elif etype == "tool_call":
            _flush_pending()
            pending_tool = {
                "tool": ev.payload.get("tool", ""),
                "args": ev.payload.get("args", {}),
                "status": "running",
                "_ts": ts,
            }
        elif etype == "tool_result":
            if pending_tool is not None:
                pending_tool["status"] = ev.payload.get("status", "ok")
                pending_tool["summary"] = ev.payload.get("summary", "")
                pending_tool["output"] = ev.payload.get("output", "")
                _flush_pending()
            else:
                # 孤儿 tool_result（无前置 tool_call）→ 单独成 tool turn
                turns.append(AssistantTurn(
                    role="tool",
                    tools=[{
                        "tool": ev.payload.get("tool", ""),
                        "status": ev.payload.get("status", "ok"),
                        "summary": ev.payload.get("summary", ""),
                    }],
                    created_at=ts,
                ))
        elif etype == "approval_request":
            _flush_pending()
            turns.append(AssistantTurn(
                role="approval",
                approval=ev.payload,
                created_at=ts,
            ))
        # 其他事件类型忽略（不污染对话流）

    _flush_pending()
    return turns


# ---------- 端点 ----------

@router.post("/sessions", response_model=Session)
async def create_assistant_session(req: CreateSessionRequest) -> Session:
    """创建助手会话。默认 mode=agent（完整 agent 管线）。

    复用既有 store.create + bus.emit + ps.active_project()，与 /api/v1/sessions 同语义，
    区别仅在默认 surface（对话助手）和 model_alias 字段（前端展示用）。
    """
    if req.mode not in _ALLOWED_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {_ALLOWED_MODES}")
    # 函数级 lazy import：避免模块级循环导入（main.py 反向 import 本 router）
    from .main import bus, ps, store

    proj = ps.active_project()
    session = store.create(
        title=req.title,
        model=req.model_alias,
        mode=req.mode,
        project=proj["host"] if proj else None,
        project_name=proj["name"] if proj else None,
    )
    bus.emit(session.id, EventType.status, Role.system,
             {"status": session.status, "progress": 0, "note": "助手会话已创建"})
    return session


@router.post("/sessions/{session_id}/messages", response_model=MessageResponse)
async def send_assistant_message(session_id: str, req: SendMessageRequest) -> MessageResponse:
    """发送消息 → 后台派发 orchestrator / chat，返回 task_id。

    - mode=auto/agent（默认）→ _run_orchestrator（require_approval=True）
    - mode=chat/plan         → _run_chat（轻量直连模型，不启沙盒）

    并发守卫复用 RUNNING_TASKS（409），与既有 /sessions/{id}/tasks 一致。
    async def：asyncio.create_task 必须在事件循环线程内调用（同步 def 会被
    FastAPI 丢进 threadpool，那里没有 running loop → RuntimeError）。

    monkeypatch：测试通过 `monkeypatch.setattr("api.main._run_chat", fake)` 替换
    源头引用；本函数 lazy import 时取到的就是替换后的版本。
    """
    from .main import RUNNING_TASKS, bus, store

    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    # 并发守卫：同会话已有未完成任务 → 409
    existing = RUNNING_TASKS.get(session_id)
    if existing and not existing.done():
        raise HTTPException(status_code=409, detail="session already has a running task")

    mode = (req.mode or session.mode or "agent").lower()
    if mode not in _ALLOWED_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {_ALLOWED_MODES}")

    task_id = f"task-{datetime.now(timezone.utc).strftime('%H%M%S')}-{uuid.uuid4().hex[:4]}"
    store.update_status(session_id, SessionStatus.running)
    bus.emit(session_id, EventType.status, Role.system,
             {"status": "running", "progress": 0, "note": f"助手消息已派发 {task_id}"})
    # 把用户消息也作为 message 事件落库（前端 history 直接可见）
    bus.emit(session_id, EventType.message, Role.user, {"text": req.text})

    # 构造 TaskRequest（_run_orchestrator 会读 context.orchestrator 作为 cfg）
    task_req = TaskRequest(
        description=req.text,
        context={
            "mode": mode,
            "model": req.model or session.model or "coder",
            "orchestrator": req.orchestrator or {"require_approval": True},
        },
    )

    # lazy import 取 _run_orchestrator / _run_chat（在调用时取，支持 monkeypatch api.main.*）
    from .main import _run_chat, _run_orchestrator
    if mode in ("auto", "agent"):
        coro = _run_orchestrator(session_id, task_id, task_req)
    else:  # chat / plan
        coro = _run_chat(
            session_id, task_id, req.text,
            req.model or session.model or "coder", mode,
        )

    t = asyncio.create_task(coro)
    RUNNING_TASKS[session_id] = t
    t.add_done_callback(lambda _t, sid=session_id: RUNNING_TASKS.pop(sid, None))
    return MessageResponse(task_id=task_id, session_id=session_id)


@router.get("/sessions/{session_id}/history", response_model=list[AssistantTurn])
async def get_assistant_history(session_id: str) -> list[AssistantTurn]:
    """返回对话 turns 视图（事件流折叠）。"""
    from .main import store

    if not store.get(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    events = store.events(session_id)
    return _events_to_turns(events)


@router.post("/sessions/{session_id}/approve", response_model=DecisionResponse)
async def approve_assistant(session_id: str) -> DecisionResponse:
    """审批放行 → 调 _resume_with_decision('approve') + 发 approval_result 事件。"""
    return await _do_decision(session_id, "approve")


@router.post("/sessions/{session_id}/reject", response_model=DecisionResponse)
async def reject_assistant(session_id: str) -> DecisionResponse:
    """审批否决 → 调 _resume_with_decision('reject') + 发 approval_result 事件。"""
    return await _do_decision(session_id, "reject")


async def _do_decision(session_id: str, decision: str) -> DecisionResponse:
    """approve/reject 共用实现。返回 DecisionResponse。

    404 守卫：session 不存在。
    409 守卫（M151.2）：会话无 pending approval_request 事件时拒绝（无事可 resume）。
    _resume_with_decision 是本模块模块级函数，monkeypatch
    api.assistant._resume_with_decision 可直接替换。
    """
    from .main import bus, store

    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    # M151.2 守卫：必须存在「未被回答的 approval_request」才允许 approve/reject。
    # 判定 = 事件流中有 approval_request，且其后无 approval_result。
    if not _has_pending_approval(store, session_id):
        raise HTTPException(status_code=409, detail="no pending approval_request to resume")

    # 异步派发 resume（M151.2：接通真实 resume_orchestrated(resume_value=decision)）
    asyncio.create_task(_resume_with_decision(session_id, decision))

    bus.emit(session_id, EventType.approval_result, Role.system,
             {"decision": decision, "note": f"用户{ '放行' if decision == 'approve' else '否决' }"})
    return DecisionResponse(ok=True, session_id=session_id, decision=decision)


def _has_pending_approval(store, session_id: str) -> bool:
    """事件流中是否存在「未被 approval_result 回答的 approval_request」。

    扫描顺序：从最后一个事件往前找最近的 approval_request 或 approval_result。
    若最近的是 approval_request → pending=True；若 approval_result 或都没有 → False。
    """
    events = store.events(session_id)
    for ev in reversed(events):
        etype = ev.type.value if hasattr(ev.type, "value") else str(ev.type)
        if etype == "approval_request":
            return True
        if etype == "approval_result":
            return False
    return False


async def _resume_with_decision(session_id: str, decision: str) -> None:
    """M151.2：接通真实 resume_orchestrated(resume_value=decision)。

    取 session → 取 checkpoint_db_path → 构建 nodes（mock/real 与 _run_orchestrator 一致）
    → resume_orchestrated(resume_value=decision) 在工作线程跑 → 按结果更新状态。
    resume_value=approve → 续跑到 worker；reject → 回 supervisor 重规划。
    """
    import asyncio
    from .main import FLIPPED_CHECKPOINT_DB, _build_real_nodes, _mock_orchestrator_fns, bus, ps, store

    session = store.get(session_id)
    if not session:
        return
    db_path = session.checkpoint_db_path or FLIPPED_CHECKPOINT_DB
    from driving.orchestrator import resume_orchestrated

    store.update_status(session_id, SessionStatus.running)
    try:
        if os.environ.get("FLIPPED_MOCK_ORCHESTRATOR"):
            sup, work, over, ver = _mock_orchestrator_fns()
            final = await asyncio.to_thread(
                resume_orchestrated,
                session_id, db_path,
                resume_value=decision,
                supervisor=sup, worker=work, overseer=over, verifier=ver,
            )
        else:
            nodes = _build_real_nodes(session_id, session.cwd or "/workspace", session.verify_cmd or ["true"])
            final = await asyncio.to_thread(
                resume_orchestrated,
                session_id, db_path,
                resume_value=decision,
                **nodes,
            )
        if final is None:
            store.update_status(session_id, SessionStatus.error)
            bus.emit(session_id, EventType.error, Role.system,
                     {"message": "resume: no checkpoint found for session"})
            return
        if final.get("verified"):
            store.update_status(session_id, SessionStatus.done)
        elif final.get("stop_reason") in ("worker_error", "overseer_abort", "loop_detected", "circuit_breaker"):
            store.update_status(session_id, SessionStatus.error)
        else:
            store.update_status(session_id, SessionStatus.review)
    except Exception as exc:
        store.update_status(session_id, SessionStatus.error)
        bus.emit(session_id, EventType.error, Role.system,
                 {"message": f"resume failed: {exc}"})
