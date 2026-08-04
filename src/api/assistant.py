"""M151.1 · 代码助手 assistant router。

在既有 :8011 orchestration API 之上叠加一层「对话式代码助手」路由：
- POST /api/v1/assistant/sessions              创建助手会话（默认 mode=agent）
- POST /api/v1/assistant/sessions/{id}/messages 发送消息，返回 task_id
- POST /api/v1/assistant/sessions/{id}/approve  审批放行
- POST /api/v1/assistant/sessions/{id}/reject   审批否决
- GET  /api/v1/assistant/sessions/{id}/history  事件流折叠成对话 turns
- POST /api/v1/assistant/sessions/{id}/goal     M176 goal 自循环（目标驱动逐轮派发+judge）
- GET  /api/v1/assistant/sessions/{id}/goal     M176 事件流重建最新 goal 状态

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
import subprocess
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

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


class DecisionRequest(BaseModel):
    """approve/reject 可选请求体（M165.2b）。

    scope=once（缺省）：仅本次放行；scope=always：approve 时把最近 pending
    approval_request 的 action 作为 pattern 持久化到宿主侧 grants
    （data/approval_grants.json），后续同 cwd 命中自动直通。reject 忽略 scope。
    """
    scope: Literal["once", "always"] = "once"


class DecisionResponse(BaseModel):
    """approve/reject 端点响应：决策已受理 + 异步 resume 派发。"""
    ok: bool
    session_id: str
    decision: str


class CompactResponse(BaseModel):
    """compact 端点响应（M165.1b）：摘要已生成并作为 supervisor message 落库。"""
    ok: bool
    session_id: str
    summary: str


class UndoResponse(BaseModel):
    """undo 端点响应（M168.1）：已回滚到最近快照 + 删除 turn 内新增文件清单。"""
    ok: bool
    session_id: str
    restored: bool
    deleted: list[str] = Field(default_factory=list)


class EditMessageRequest(BaseModel):
    """编辑重跑请求（M174）：截断目标 user 消息及其后事件，以新文本重派发。"""
    text: str = Field(..., min_length=1)
    restore_files: bool = True   # agent/auto 且找到快照才生效；chat/plan 恒 no-op
    mode: str | None = None      # 缺省沿用 session.mode


class EditMessageResponse(BaseModel):
    """编辑重跑响应：截断条数 + 文件还原结果 + 新 task_id。"""
    ok: bool
    session_id: str
    task_id: str
    truncated: int
    restored: bool = False
    deleted: list[str] = Field(default_factory=list)


class CreateGoalRequest(BaseModel):
    """创建 goal 自循环请求（M176）：目标驱动逐轮派发 + judge 校验。"""
    objective: str = Field(..., min_length=1)
    mode: str | None = None            # 缺省沿用 session.mode
    model: str | None = None           # 缺省沿用 session.model
    max_iterations: int | None = None  # 缺省 FLIPPED_GOAL_MAX_ITER(5)，硬上限 20


class CreateGoalResponse(BaseModel):
    """goal 派发响应：wrapper task_id + 生效的最大轮数。"""
    task_id: str
    session_id: str
    objective: str
    max_iterations: int


class GoalInfoResponse(BaseModel):
    """GET /goal 响应（M176）：summarize_goal_events 从事件流重建的最新 goal 状态。

    键集由 goal.py 决定（objective/iteration/max_iterations/status/…），
    extra=allow 原样透传，B 队不与 A 队内部键名硬耦合。
    """
    status: str | None = None
    objective: str | None = None
    iteration: int | None = None
    max_iterations: int | None = None

    model_config = ConfigDict(extra="allow")


class AssistantTurn(BaseModel):
    """对话 turn 视图：把事件流折叠成 user/assistant/tool/approval/goal 五类。"""
    role: str                       # user | assistant | tool | approval | goal
    event_id: str | None = None     # M174：仅 user turn 回填（编辑锚点），其余 None
    refs: list[dict[str, Any]] | None = None  # M175：user turn 的 @ 文件引用清单（FileRef asdict）
    text: str | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    verdict: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
    usage: dict[str, int] | None = None  # M169 per-turn token 用量（usage 事件回扫合并）
    goal: dict[str, Any] | None = None   # M176 goal 事件相位 payload（仅 role=goal turn）
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
    - usage → 合并进最近 assistant turn，不单独成 turn（M169，多事件累加）
    - 其他类型（status/checkpoint/snapshot/error/rca/verifier_verdict/plan/file_change/terminal/browser）
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
                event_id=ev.id if role == "user" else None,
                refs=ev.payload.get("refs") if role == "user" else None,
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
        elif etype == "goal":
            # M176：仅 4 个可见相位折成 goal turn；set/judge 不折
            # （judge 的 gap 已并入下一轮 iter payload；set 与首条 user 消息重复）
            if ev.payload.get("phase") in ("iter", "achieved", "exhausted", "stopped"):
                _flush_pending()
                turns.append(AssistantTurn(
                    role="goal",
                    goal=ev.payload,
                    created_at=ts,
                ))
        elif etype == "usage":
            # M169：回扫合并进最近一个 assistant turn；同 turn 多事件累加（orchestrator 多子任务兜底）
            for t in reversed(turns):
                if t.role == "assistant":
                    p = int(ev.payload.get("prompt", 0) or 0)
                    c = int(ev.payload.get("completion", 0) or 0)
                    n = int(ev.payload.get("calls", 0) or 0)
                    if t.usage:
                        t.usage["prompt"] += p
                        t.usage["completion"] += c
                        t.usage["calls"] += n
                    else:
                        t.usage = {"prompt": p, "completion": c, "calls": n}
                    break
        # 其他事件类型忽略（不污染对话流）

    _flush_pending()
    return turns


# ---------- M168.1 · git shadow snapshot helpers（undo 地基，宿主侧执行） ----------

def _git_head(root) -> str | None:
    """`git rev-parse HEAD`；非 git repo / 无提交 / 超时 → None（兼作 repo 探测）。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def _git_snapshot(root) -> str | None:
    """git shadow snapshot：`git stash create` 产 dangling commit（不动工作区/索引/历史）。

    输出为空（工作区无变更）→ 回退 `git rev-parse HEAD`；非 git repo / 失败 → None。
    调用方须用 asyncio.to_thread 包裹，防 subprocess 阻塞 event loop。
    """
    try:
        out = subprocess.run(
            ["git", "stash", "create"],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    snap = out.stdout.strip()
    if snap:
        return snap
    return _git_head(root)


def _git_restore(root, snapshot: str) -> None:
    """`git restore --source=<snapshot> -- .`：tracked 文件内容回滚到快照态（含恢复被删文件）。

    非零退出 → RuntimeError 带 stderr。不动 untracked 文件（由 undo 端点按 file_change 事件删）。
    """
    try:
        out = subprocess.run(
            ["git", "restore", f"--source={snapshot}", "--", "."],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"git restore 执行失败: {exc}") from exc
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"git restore exit {out.returncode}")


def _map_change_to_host(path: str, root: Path, cwd: str | None) -> Path | None:
    """把 file_change 事件的 path（可能是容器路径）映射为宿主 project_root 内路径。

    映射规则：
    - 以 /workspace/ 或 session.cwd 开头 → strip 前缀拼 project_root
    - 其余绝对路径 → 仅当 resolved 后在 project_root 内才接受
    - 相对路径 → 直接当 project_root 相对路径
    任何越界（../ 穿越、root 外、空前缀/空 path）→ None（跳过，防误删）。
    """
    p = (path or "").strip()
    if not p:
        return None
    root_res = root.resolve()
    prefixes = ["/workspace"]
    if cwd and cwd != "/" and cwd not in prefixes:
        prefixes.append(cwd)
    rel: str | None = None
    for prefix in prefixes:
        pref = prefix.rstrip("/")
        if p == pref or p.startswith(pref + "/"):
            rel = p[len(pref):].lstrip("/")
            break
    if rel is None:
        if os.path.isabs(p):
            try:
                rel = str(Path(p).resolve().relative_to(root_res))
            except (ValueError, OSError):
                return None
        else:
            rel = p
    if not rel:
        return None
    try:
        target = (root_res / rel).resolve()
        target.relative_to(root_res)
    except (ValueError, OSError):
        return None
    return target


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
    # M175 · @ 文件引用展开：展示保持原文（@token 可见），LLM 输入用展开文本。
    # FLIPPED_FILE_REFS=0 关闭；fail-open：任何异常 = 不展开。
    send_text = req.text
    file_refs: list[Any] = []
    if os.environ.get("FLIPPED_FILE_REFS", "1") != "0":
        try:
            from .file_refs import expand_file_refs
            from .main import ps
            send_text, file_refs = expand_file_refs(req.text, ps.project_root())
        except Exception:  # noqa: BLE001 fail-open
            send_text, file_refs = req.text, []
    # 把用户消息也作为 message 事件落库（前端 history 直接可见，原文 + refs 元数据）
    payload: dict[str, Any] = {"text": req.text}
    if file_refs:
        payload["refs"] = [asdict(r) for r in file_refs]
    bus.emit(session_id, EventType.message, Role.user, payload)

    # M168.1 · git shadow snapshot（undo 地基）：auto/agent（orchestrator 通路）会改文件，
    # 任务派发前在宿主 project_root 跑 `git stash create` 并 emit snapshot 事件
    # （必须先于 create_task，保证 undo 找得到）。chat/plan 不改文件 → 跳过。
    # 快照失败（非 git 工作区）不阻塞派发，仅提示本轮不可撤销。
    if mode in ("auto", "agent"):
        from .main import ps
        root = ps.project_root()
        snap = await asyncio.to_thread(_git_snapshot, root) if root is not None else None
        if snap:
            head = await asyncio.to_thread(_git_head, root)
            bus.emit(session_id, EventType.snapshot, Role.system,
                     {"snapshot": snap, "head": head, "task_id": task_id})
        else:
            bus.emit(session_id, EventType.message, Role.system,
                     {"text": "非 git 工作区，本轮改动不可撤销"})

    # 构造 TaskRequest（_run_orchestrator 会读 context.orchestrator 作为 cfg）
    # M175：LLM 输入用 send_text（@ 引用已展开），展示层 history 保持 req.text 原文
    task_req = TaskRequest(
        description=send_text,
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
            session_id, task_id, send_text,
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
async def approve_assistant(session_id: str, req: DecisionRequest | None = None) -> DecisionResponse:
    """审批放行 → 调 _resume_with_decision('approve') + 发 approval_result 事件。

    M165.2b：可选 body {"scope": "once"|"always"}，无 body 向后兼容（=once）。
    scope=always 时把最近 pending approval_request 的 action 持久化到宿主侧 grants。
    """
    return await _do_decision(session_id, "approve", scope=(req.scope if req else "once"))


@router.post("/sessions/{session_id}/reject", response_model=DecisionResponse)
async def reject_assistant(session_id: str, req: DecisionRequest | None = None) -> DecisionResponse:
    """审批否决 → 调 _resume_with_decision('reject') + 发 approval_result 事件。

    M165.2b：接受同样可选 body 保持端点形状一致，但 reject 忽略 scope（不落盘）。
    """
    return await _do_decision(session_id, "reject", scope=(req.scope if req else "once"))


async def _do_decision(session_id: str, decision: str, scope: str = "once") -> DecisionResponse:
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

    # M165.2b：approve + scope=always → 最近 pending approval_request 的 action 作为
    # pattern 持久化到**宿主侧** grants（data/approval_grants.json，按 cwd key 隔离）。
    # 严禁写 <cwd>/.flipped/approvals.json——session.cwd 可能是容器路径（/projects/x、/workspace）。
    if decision == "approve" and scope == "always":
        pattern = _latest_pending_action(store, session_id)
        if pattern:
            from driving.approval import remember_host_grant
            remember_host_grant(session.cwd or "/workspace", pattern)

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


def _latest_pending_action(store, session_id: str) -> str | None:
    """最近的 pending approval_request 的 action 文本（M165.2b scope=always 的 pattern 来源）。

    调用前提：_has_pending_approval 已为 True，故反向扫到的第一个 approval_request 即 pending。
    """
    for ev in reversed(store.events(session_id)):
        etype = ev.type.value if hasattr(ev.type, "value") else str(ev.type)
        if etype == "approval_request":
            action = ev.payload.get("action")
            return str(action) if action else None
    return None


# ---------- M165.1b · compact ----------

_COMPACT_SYSTEM = (
    "你是对话压缩器。把以下代码助手对话转录压缩成简洁中文摘要，保留：用户目标、"
    "已完成步骤、关键决策、未决事项。直接输出摘要正文，不要前后寒暄。"
)


async def _summarize_transcript(transcript: str, model: str) -> str:
    """默认摘要实现：走 _run_chat 同款模型通路（resolve_worker_model_config + _llm_chat）。

    模块级 async 函数，测试/部署可 monkeypatch api.assistant._summarize_transcript 注入。
    函数级 lazy import 避免模块级循环导入（main.py 反向 import 本 router）。
    """
    from driving.model_router import resolve_worker_model_config

    from .main import _llm_chat

    base_url, resolved_model = resolve_worker_model_config(model)
    content, _usage = await _llm_chat(base_url, resolved_model, _COMPACT_SYSTEM, transcript)
    return content


@router.post("/sessions/{session_id}/compact", response_model=CompactResponse)
async def compact_assistant(session_id: str) -> CompactResponse:
    """把 message 事件折叠成 transcript → 摘要 → 以 supervisor message 落库（M165.1b）。

    404：session 不存在。409：事件流中无 message 事件（无可压缩内容）。
    摘要失败 → 502 且不 emit（fail-closed，别 emit 半截）。
    """
    from .main import bus, store

    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    # 折叠 message 事件为 transcript（user/assistant 分行，与 _events_to_turns 同映射）
    lines: list[str] = []
    for ev in store.events(session_id):
        etype = ev.type.value if hasattr(ev.type, "value") else str(ev.type)
        if etype != "message":
            continue
        agent = ev.agent.value if hasattr(ev.agent, "value") else (str(ev.agent) if ev.agent else None)
        speaker = "user" if agent == "user" else "assistant"
        lines.append(f"{speaker}: {ev.payload.get('text', '')}")
    if not lines:
        raise HTTPException(status_code=409, detail="no message events to compact")

    try:
        summary = await _summarize_transcript("\n".join(lines), session.model or "coder")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"compact summarize failed: {exc}") from exc

    # supervisor 角色发出：前端 history 折叠把 supervisor 消息呈现为 assistant turn
    bus.emit(session_id, EventType.message, Role.supervisor, {"text": "[compact] " + summary})
    return CompactResponse(ok=True, session_id=session_id, summary=summary)


@router.post("/sessions/{session_id}/undo", response_model=UndoResponse)
async def undo_assistant(session_id: str) -> UndoResponse:
    """撤销最近一次助手 turn 的文件改动（M168.1，对标 opencode /undo）。

    机制：从事件流找最近一条未被 undo 覆盖的 snapshot 事件 →
    `git restore --source=<hash> -- .` 回滚 tracked 文件内容 →
    删除该快照之后 file_change(add/create) 的 turn 内新增文件（路径穿越防护）→
    emit undo 结果事件（message/system, payload.undo=True 记录已撤销 hash，多轮幂等）。

    守卫：404 会话不存在；409 运行中不能撤销；409 没有可撤销的改动；
    400 project_root 非 git 仓库；500 git restore 失败（带 stderr）。
    """
    from .main import RUNNING_TASKS, bus, ps, store

    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    # 并发守卫：运行中不能撤销（orchestrator 可能正在写文件）
    existing = RUNNING_TASKS.get(session_id)
    if existing and not existing.done():
        raise HTTPException(status_code=409, detail="运行中不能撤销")

    events = store.events(session_id)

    # 已被 undo 覆盖的 snapshot hash 集合（undo 结果事件 payload.undo=True）
    undone: set[str] = set()
    for ev in events:
        etype = ev.type.value if hasattr(ev.type, "value") else str(ev.type)
        if etype == "message" and ev.payload.get("undo") and ev.payload.get("snapshot"):
            undone.add(ev.payload["snapshot"])

    # 时间倒序找第一条未被覆盖的快照事件
    target_idx: int | None = None
    target_hash: str | None = None
    for i in range(len(events) - 1, -1, -1):
        ev = events[i]
        etype = ev.type.value if hasattr(ev.type, "value") else str(ev.type)
        if etype != "snapshot":
            continue
        h = ev.payload.get("snapshot")
        if h and h not in undone:
            target_idx, target_hash = i, h
            break
    if target_hash is None or target_idx is None:
        raise HTTPException(status_code=409, detail="没有可撤销的改动")

    root = ps.project_root()
    if root is None or await asyncio.to_thread(_git_head, root) is None:
        raise HTTPException(status_code=400, detail="项目目录不是 git 仓库，无法撤销")

    try:
        await asyncio.to_thread(_git_restore, root, target_hash)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=f"git restore 失败: {exc}") from exc

    # 删除该快照之后 turn 内新增的文件（change ∈ add/create）；缺失文件跳过
    deleted: list[str] = []
    skipped: list[str] = []
    for ev in events[target_idx + 1:]:
        etype = ev.type.value if hasattr(ev.type, "value") else str(ev.type)
        if etype != "file_change":
            continue
        if ev.payload.get("change") not in ("add", "create"):
            continue
        raw = str(ev.payload.get("path") or "")
        target = _map_change_to_host(raw, root, session.cwd)
        if target is None:
            skipped.append(raw)
            continue
        try:
            target.unlink()
            deleted.append(raw)
        except FileNotFoundError:
            pass
        except OSError:
            skipped.append(raw)

    bus.emit(session_id, EventType.message, Role.system, {
        "text": f"已撤销到快照 {target_hash[:8]}：tracked 文件已还原，"
                f"删除 {len(deleted)} 个新增文件",
        "undo": True,
        "snapshot": target_hash,
        "deleted": deleted,
        "skipped": skipped,
    })
    return UndoResponse(ok=True, session_id=session_id, restored=True, deleted=deleted)


@router.post("/sessions/{session_id}/messages/{event_id}/edit", response_model=EditMessageResponse)
async def edit_assistant_message(session_id: str, event_id: str, req: EditMessageRequest) -> EditMessageResponse:
    """编辑一条 user 消息并重跑（M174）：截断 + 可选文件还原 + 重新派发。

    流程（顺序钉死）：
    1. 404 会话不存在；404 事件不存在；422 事件非 (message 且 user)。
    2. 409 运行中（RUNNING_TASKS 未完成句柄）；409 pending approval。
    3. mode = (req.mode or session.mode).lower()，非法值 422。
    4. 截断前收集：目标事件之后第一条 snapshot（取 hash）+ 该快照之后所有
       file_change(add/create) 的 path 清单。
    5. 有快照且 mode∈{auto,agent} 且 restore_files → git restore 回滚 tracked
       （失败 500，fail-closed 不截断）+ 删除收集到的新增文件。
    6. store.truncate_from 截断（含目标消息本身）。
    7. 重派发（同 send_assistant_message 后半段，user 消息 payload 带 edited=True）。
    """
    from .main import RUNNING_TASKS, bus, ps, store

    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    events = store.events(session_id)
    idx = next((i for i, e in enumerate(events) if e.id == event_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="event not found")
    target = events[idx]
    etype = target.type.value if hasattr(target.type, "value") else str(target.type)
    agent = target.agent.value if hasattr(target.agent, "value") else (str(target.agent) if target.agent else None)
    if etype != "message" or agent != "user":
        raise HTTPException(status_code=422, detail="只能编辑 user 消息事件")

    # 并发守卫：运行中不能编辑重跑（orchestrator 可能正在写文件）
    existing = RUNNING_TASKS.get(session_id)
    if existing and not existing.done():
        raise HTTPException(status_code=409, detail="session already has a running task")

    # 有未回答的 approval_request：先审批再编辑（否则截断会吞掉审批决策点）
    if _has_pending_approval(store, session_id):
        raise HTTPException(status_code=409, detail="pending approval_request must be resolved before editing")

    mode = (req.mode or session.mode).lower()
    if mode not in _ALLOWED_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {_ALLOWED_MODES}")

    # 截断前收集：目标消息之后第一条 snapshot + 该快照之后 file_change(add/create) 清单。
    # 必须在 truncate_from 之前完成——截断后这些事件就没了。
    snapshot_hash: str | None = None
    added_paths: list[str] = []
    if mode in ("auto", "agent") and req.restore_files:
        snap_idx: int | None = None
        for i in range(idx + 1, len(events)):
            et = events[i].type.value if hasattr(events[i].type, "value") else str(events[i].type)
            if et == "snapshot":
                snap_idx = i
                snapshot_hash = events[i].payload.get("snapshot")
                break
        if snap_idx is not None and snapshot_hash:
            for ev in events[snap_idx + 1:]:
                et = ev.type.value if hasattr(ev.type, "value") else str(ev.type)
                if et == "file_change" and ev.payload.get("change") in ("add", "create"):
                    added_paths.append(str(ev.payload.get("path") or ""))

    # 文件还原（有快照才执行；chat/plan 与 restore_files=False 恒跳过）
    restored = False
    deleted: list[str] = []
    if snapshot_hash:
        root = ps.project_root()
        if root is None or await asyncio.to_thread(_git_head, root) is None:
            raise HTTPException(status_code=400, detail="项目目录不是 git 仓库，无法还原文件")
        try:
            await asyncio.to_thread(_git_restore, root, snapshot_hash)
        except RuntimeError as exc:
            # fail-closed：restore 失败不准截断，事件流保持原样
            raise HTTPException(status_code=500, detail=f"git restore 失败: {exc}") from exc
        restored = True
        for raw in added_paths:
            target_path = _map_change_to_host(raw, root, session.cwd)
            if target_path is None:
                continue
            try:
                target_path.unlink()
                deleted.append(raw)
            except FileNotFoundError:
                pass
            except OSError:
                pass  # 跳过不炸（权限/目录非空等）

    truncated = store.truncate_from(session_id, event_id)

    # ---- 重派发（同 send_assistant_message 后半段）----
    task_id = f"task-{datetime.now(timezone.utc).strftime('%H%M%S')}-{uuid.uuid4().hex[:4]}"
    store.update_status(session_id, SessionStatus.running)
    bus.emit(session_id, EventType.status, Role.system,
             {"status": "running", "progress": 0, "note": f"编辑重跑已派发 {task_id}"})
    bus.emit(session_id, EventType.message, Role.user, {"text": req.text, "edited": True})

    # auto/agent 改文件 → 重派发前重新快照（undo 地基），失败仅提示不阻塞
    if mode in ("auto", "agent"):
        root = ps.project_root()
        snap = await asyncio.to_thread(_git_snapshot, root) if root is not None else None
        if snap:
            head = await asyncio.to_thread(_git_head, root)
            bus.emit(session_id, EventType.snapshot, Role.system,
                     {"snapshot": snap, "head": head, "task_id": task_id})
        else:
            bus.emit(session_id, EventType.message, Role.system,
                     {"text": "非 git 工作区，本轮改动不可撤销"})

    task_req = TaskRequest(
        description=req.text,
        context={
            "mode": mode,
            "model": session.model or "coder",
            "orchestrator": {"require_approval": True},
        },
    )

    # lazy import 取 _run_orchestrator / _run_chat（monkeypatch api.main.* 生效）
    from .main import _run_chat, _run_orchestrator
    if mode in ("auto", "agent"):
        coro = _run_orchestrator(session_id, task_id, task_req)
    else:  # chat / plan
        coro = _run_chat(
            session_id, task_id, req.text,
            session.model or "coder", mode,
        )

    t = asyncio.create_task(coro)
    RUNNING_TASKS[session_id] = t
    t.add_done_callback(lambda _t, sid=session_id: RUNNING_TASKS.pop(sid, None))
    return EditMessageResponse(
        ok=True, session_id=session_id, task_id=task_id,
        truncated=truncated, restored=restored, deleted=deleted,
    )


# ---------- M176 · Goal 模式（目标驱动自循环 + 逐轮 judge 校验） ----------

_GOAL_MAX_ITER_HARD_LIMIT = 20  # 硬上限，环境变量/请求都不可突破


def _goal_max_iterations(requested: int | None) -> int:
    """生效轮数 = min(req 或 FLIPPED_GOAL_MAX_ITER(默认 5), 20)，且 ≥1。"""
    try:
        env_max = int(os.environ.get("FLIPPED_GOAL_MAX_ITER", "5"))
    except ValueError:
        env_max = 5
    return max(1, min(requested or env_max, _GOAL_MAX_ITER_HARD_LIMIT))


@router.post("/sessions/{session_id}/goal", response_model=CreateGoalResponse)
async def create_assistant_goal(session_id: str, req: CreateGoalRequest) -> CreateGoalResponse:
    """创建 goal 自循环（M176，对标 ZCode Goal Mode）。

    - FLIPPED_GOAL=0 → 404（整体开关）；会话不存在 → 404；RUNNING_TASKS 守卫 → 409
    - mode 校验同 send（缺省沿用 session.mode）
    - emit message(user, {text, goal.started=True}) + goal set 事件
    - wrapper 协程注册为 RUNNING_TASKS 条目 → 既有 409 并发守卫与
      /sessions/{id}/cancel 直接可停 goal，零新机制
    """
    if os.environ.get("FLIPPED_GOAL", "1") == "0":
        raise HTTPException(status_code=404, detail="goal mode disabled")
    from .goal import GoalState, goal_payload
    from .main import RUNNING_TASKS, bus, store

    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    # 并发守卫：同会话已有未完成任务 → 409（与 send 同款）
    existing = RUNNING_TASKS.get(session_id)
    if existing and not existing.done():
        raise HTTPException(status_code=409, detail="session already has a running task")

    mode = (req.mode or session.mode or "agent").lower()
    if mode not in _ALLOWED_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {_ALLOWED_MODES}")

    max_iterations = _goal_max_iterations(req.max_iterations)
    model_alias = req.model or session.model or "coder"
    task_id = f"task-{datetime.now(timezone.utc).strftime('%H%M%S')}-{uuid.uuid4().hex[:4]}"
    state = GoalState(objective=req.objective, max_iterations=max_iterations)

    # 用户消息落库（原文 + goal 标记，前端据此渲染 goal 起始标记行）
    bus.emit(session_id, EventType.message, Role.user,
             {"text": req.objective, "goal": {"started": True}})
    bus.emit(session_id, EventType.goal, Role.system, goal_payload("set", state))

    t = asyncio.create_task(_goal_loop(session_id, task_id, state, mode, model_alias))
    RUNNING_TASKS[session_id] = t
    t.add_done_callback(lambda _t, sid=session_id: RUNNING_TASKS.pop(sid, None))
    return CreateGoalResponse(
        task_id=task_id, session_id=session_id,
        objective=req.objective, max_iterations=max_iterations,
    )


@router.get("/sessions/{session_id}/goal", response_model=GoalInfoResponse)
async def get_assistant_goal(session_id: str) -> GoalInfoResponse:
    """从事件流重建最新 goal 状态（M176）。无 goal 事件 → 404。"""
    from .goal import summarize_goal_events
    from .main import store

    if not store.get(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    info = summarize_goal_events(store.events(session_id))
    if info is None:
        raise HTTPException(status_code=404, detail="no goal in this session")
    return GoalInfoResponse(**info)


async def _goal_loop(session_id: str, task_id: str, state, mode: str, model_alias: str) -> None:
    """M176 · goal 自循环 wrapper：逐轮派发 → judge 校验 → 未达成续跑/终态收尾。

    轮内顺序 await _run_chat/_run_orchestrator（不嵌套 create_task）→ cancel 时
    CancelledError 沿 await 链传播进轮内，catch 后 emit goal stopped 再 re-raise。
    judge 任何失败 = None（fail-safe），由 record_verdict 的 judge_errors 熔断计数。
    终态（achieved/exhausted）把会话状态置 done；stopped/cancelled 由 cancel 端点自管。
    """
    from .goal import build_iter_prompt, goal_payload, record_verdict
    from .main import bus, store

    def _emit(phase: str, **extra) -> None:
        bus.emit(session_id, EventType.goal, Role.system, goal_payload(phase, state, **extra))

    for i in range(1, state.max_iterations + 1):
        state.iteration = i
        prompt = build_iter_prompt(state)
        _emit("iter", prompt=prompt, gap=state.last_gap)
        try:
            if mode in ("auto", "agent"):
                # 与 send 同款：orchestrator 通路会改文件 → 派发前 git shadow 快照
                from .main import _run_orchestrator, ps
                root = ps.project_root()
                snap = await asyncio.to_thread(_git_snapshot, root) if root is not None else None
                if snap:
                    head = await asyncio.to_thread(_git_head, root)
                    bus.emit(session_id, EventType.snapshot, Role.system,
                             {"snapshot": snap, "head": head, "task_id": task_id})
                task_req = TaskRequest(
                    description=prompt,
                    context={
                        "mode": mode,
                        "model": model_alias,
                        "orchestrator": {"require_approval": True},
                    },
                )
                await _run_orchestrator(session_id, task_id, task_req)
            else:  # chat / plan
                from .main import _run_chat
                await _run_chat(session_id, task_id, prompt, model_alias, mode)
        except asyncio.CancelledError:
            state.status = "stopped"
            _emit("stopped")
            raise
        if state.stop_requested:
            state.status = "stopped"
            _emit("stopped")
            return
        if i == state.max_iterations:
            state.status = "exhausted"
            _emit("exhausted", reason="max_iter", gap=state.last_gap)
            store.update_status(session_id, SessionStatus.done)
            return
        verdict = await _judge(state, session_id, model_alias)
        _emit("judge",
              achieved=bool(verdict and verdict.get("achieved")),
              gap=(verdict or {}).get("gap", "") or ("judge 失败" if verdict is None else ""))
        decision = record_verdict(state, verdict)
        if decision == "achieved":
            _emit("achieved")
            store.update_status(session_id, SessionStatus.done)
            return
        if decision.startswith("exhausted"):
            _emit("exhausted", reason=decision.removeprefix("exhausted_"), gap=state.last_gap)
            store.update_status(session_id, SessionStatus.done)
            return
        # "continue" → 下一轮（gap 已由 record_verdict 记入 state.last_gap）


async def _judge(state, session_id: str, model_alias: str) -> dict | None:
    """M176 · LLM judge：校验当前进度是否达成目标，返回 {"achieved": bool, "gap": str}。

    fail-safe 红线：FLIPPED_GOAL_JUDGE=0、JudgeParseError、任何调用异常 → None
    （绝不视为达成、绝不上抛炸 loop；None 由 record_verdict 计入 judge_errors 熔断）。
    """
    if os.environ.get("FLIPPED_GOAL_JUDGE", "1") == "0":
        return None
    try:
        from driving.model_router import resolve_worker_model_config

        from .goal import build_judge_messages, parse_judge_reply
        from .main import _llm_chat, store

        # 回扫事件流：最近一条非 user message 文本 + 最近一条 tool_result summary
        last_assistant = ""
        last_tool = ""
        for ev in reversed(store.events(session_id)):
            etype = ev.type.value if hasattr(ev.type, "value") else str(ev.type)
            if not last_assistant and etype == "message":
                agent = ev.agent.value if hasattr(ev.agent, "value") else (
                    str(ev.agent) if ev.agent else None)
                if agent and agent != "user":
                    last_assistant = str(ev.payload.get("text", "") or "")
            elif not last_tool and etype == "tool_result":
                last_tool = str(ev.payload.get("summary", "") or "")
            if last_assistant and last_tool:
                break
        msgs = build_judge_messages(state, last_assistant[:800], last_tool[:400])
        base_url, model = resolve_worker_model_config(model_alias)
        reply, _usage = await _llm_chat(base_url, model, msgs[0]["content"], msgs[1]["content"])
        return parse_judge_reply(reply)
    except Exception:  # noqa: BLE001 fail-safe：judge 失败 = None，绝不上抛
        return None


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
