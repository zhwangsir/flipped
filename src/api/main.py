"""flipped orchestration API。

入口: uvicorn src.api.main:app --host 127.0.0.1 --port 8001
"""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .events import EventBus, get_bus
from .schemas import Event, EventType, HealthResponse, MetricsResponse, Role, Session, SessionStatus, TaskRequest, TaskResponse
from .session import SessionStore, store
from driving.safety import validate_secrets
from metrics import COLLECTOR

MOCK_WORKER = os.environ.get("FLIPPED_MOCK_WORKER", "0") == "1"
RUNNING_TASKS: dict[str, asyncio.Task] = {}  # M6.2 — 每会话运行中任务句柄，供取消
FLIPPED_CHECKPOINT_DB = os.environ.get("FLIPPED_CHECKPOINT_DB", "data/checkpoints.db")

API_PREFIX = "/api/v1"
CONSOLE_ORIGIN = "http://127.0.0.1:5273"

bus: EventBus = get_bus(store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bus.set_loop(asyncio.get_running_loop())
    store.load(os.environ.get("FLIPPED_SESSION_STORE_PATH", ".sessions.json"))
    ok, findings = validate_secrets(Path(__file__).resolve().parent.parent)
    if not ok:
        for f in findings:
            print(f"[safety] {f}", file=sys.stderr)
    for session in store.list():
        if session.status in (SessionStatus.running, SessionStatus.paused) and session.checkpoint_db_path:
            asyncio.create_task(_resume_orchestrator(session))
    yield
    bus.set_loop(None)
    bus._connections.clear()
    store.save()


app = FastAPI(title="flipped orchestration API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[CONSOLE_ORIGIN, "http://localhost:5273"],
    # 桌面壳(Electron,M6.8)从本地静态端口发请求 → 放行 localhost/127.0.0.1 任意端口
    allow_origin_regex=r"http://(127\.0\.0\.1|localhost):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 健康检查 ----------

@app.get(f"{API_PREFIX}/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    proxy_url = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{proxy_url}/models", headers={
                "Authorization": f"Bearer {os.environ.get('LITELLM_MASTER_KEY', 'dummy')}"
            })
        data = r.json() if r.status_code == 200 else {"status_code": r.status_code, "text": r.text}
        return HealthResponse(ok=r.status_code == 200, proxy=data)
    except Exception as e:
        return HealthResponse(ok=False, proxy={}, error=str(e))


# ---------- 性能指标 ----------

@app.get(f"{API_PREFIX}/metrics", response_model=MetricsResponse)
async def metrics() -> MetricsResponse:
    return MetricsResponse(**COLLECTOR.snapshot())


# ---------- MCP 服务器（M7.3 真实列表 + 开关） ----------

@app.get(f"{API_PREFIX}/mcp/servers")
async def get_mcp_servers() -> list[dict[str, Any]]:
    from api.mcp_registry import list_servers
    return list_servers()


@app.post(f"{API_PREFIX}/mcp/servers/{{name}}/toggle")
async def toggle_mcp_server(name: str, enabled: bool = Query(...)) -> dict[str, Any]:
    from api.mcp_registry import toggle_server
    try:
        return toggle_server(name, enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown MCP server: {name}")


# ---------- 项目上下文（Stage 3 — composer 上下文行 / 状态栏真实分支） ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]


@app.websocket(f"{API_PREFIX}/terminal")
async def terminal_ws(websocket: WebSocket) -> None:
    """Stage 5 — 真实 pty 终端（作用域=项目根，等价内置终端）。"""
    from api.terminal import terminal_bridge
    await terminal_bridge(websocket)


@app.get(f"{API_PREFIX}/project/context")
async def project_context() -> dict[str, str]:
    """返回项目名 + 当前 git 分支（供 composer 上下文行与状态栏显示真实值）。"""
    import subprocess

    branch = "unknown"
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=3, cwd=str(_REPO_ROOT),
        )
        if out.returncode == 0:
            branch = out.stdout.strip() or "detached"
    except (OSError, subprocess.SubprocessError):
        pass
    return {"project": _REPO_ROOT.name, "branch": branch, "mode": "本地模式"}


# ---------- 会话管理 ----------

@app.post(f"{API_PREFIX}/sessions", response_model=Session)
async def create_session(title: str = "新任务", mode: str = "agent") -> Session:
    session = store.create(title=title, mode=mode)
    bus.emit(session.id, EventType.status, Role.system,
             {"status": session.status, "progress": 0, "note": "会话已创建"})
    return session


@app.get(f"{API_PREFIX}/sessions", response_model=list[Session])
async def list_sessions() -> list[Session]:
    return store.list()


@app.get(f"{API_PREFIX}/sessions/{{session_id}}", response_model=Session)
async def get_session(session_id: str) -> Session:
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.delete(f"{API_PREFIX}/sessions/{{session_id}}")
async def delete_session(session_id: str) -> dict:
    """删除会话及其事件;若正在运行先取消其任务。"""
    if not store.get(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    task = RUNNING_TASKS.pop(session_id, None)
    if task and not task.done():
        task.cancel()
    store.delete(session_id)
    return {"ok": True, "id": session_id}


@app.get(f"{API_PREFIX}/sessions/{{session_id}}/events", response_model=list[Event])
async def get_events(session_id: str, after_id: str | None = Query(None)) -> list[Event]:
    """REST 事件历史(回放/调试用),WebSocket 之外的兜底。"""
    if not store.get(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return store.events(session_id, after_id)


@app.post(f"{API_PREFIX}/sessions/{{session_id}}/cancel", response_model=Session)
async def cancel_session(session_id: str) -> Session:
    """取消会话运行中的任务:cancel asyncio 任务 + 状态回 idle + emit。"""
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    task = RUNNING_TASKS.pop(session_id, None)
    if task and not task.done():
        task.cancel()
    updated = store.update_status(session_id, SessionStatus.idle)
    bus.emit(session_id, EventType.status, Role.system,
             {"status": "idle", "progress": 0, "note": "任务已取消"})
    return updated


# ---------- 任务派发 ----------

@app.post(f"{API_PREFIX}/sessions/{{session_id}}/tasks", response_model=TaskResponse)
async def create_task(session_id: str, req: TaskRequest) -> TaskResponse:
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    task_id = f"task-{datetime.now(timezone.utc).strftime('%H%M%S')}"
    store.update_status(session_id, SessionStatus.running)
    bus.emit(session_id, EventType.status, Role.system,
             {"status": "running", "progress": 0, "note": f"任务 {task_id} 已派发"})
    mode = req.context.get("mode", "agent")
    if req.context.get("orchestrator"):
        t = asyncio.create_task(_run_orchestrator(session_id, task_id, req))
    elif mode in ("chat", "plan"):
        # 对话/规划模式：直连本地模型，不启动沙盒
        t = asyncio.create_task(
            _run_chat(session_id, task_id, req.description, req.context.get("model", "coder"), mode)
        )
    elif MOCK_WORKER:
        t = asyncio.create_task(_mock_run(session_id, task_id, req.description))
    else:
        t = asyncio.create_task(_run_openhands(session_id, task_id, req.description, req.context.get("model", "coder")))
    RUNNING_TASKS[session_id] = t
    t.add_done_callback(lambda _t, sid=session_id: RUNNING_TASKS.pop(sid, None))
    return TaskResponse(task_id=task_id, session_id=session_id, status="running")


@app.post(f"{API_PREFIX}/sessions/{{session_id}}/resume", response_model=Session)
async def resume_session(session_id: str) -> Session:
    """从持久化的 LangGraph checkpoint 恢复并继续运行 orchestrator 会话。"""
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    if not session.checkpoint_db_path:
        raise HTTPException(status_code=400, detail="session has no checkpoint_db_path")
    asyncio.create_task(_resume_orchestrator(session))
    return session


# ---------- WebSocket 事件流 ----------

@app.websocket(f"{API_PREFIX}/sessions/{{session_id}}/events")
async def events_ws(websocket: WebSocket, session_id: str,
                    last_event_id: str | None = Query(None)):
    await bus.connect(session_id, websocket)
    try:
        # 重连回放
        if store.get(session_id):
            await bus.replay(session_id, websocket, last_event_id)
        # 保持连接，接收客户端 pong / approval 结果
        while True:
            data = await websocket.receive_json()
            await _handle_client_message(session_id, data)
    except WebSocketDisconnect:
        await bus.disconnect(session_id, websocket)
    except Exception:
        await bus.disconnect(session_id, websocket)


def _mock_orchestrator_fns():
    """Deterministic orchestrator nodes for API recovery tests."""
    verify_count = [0]

    def supervisor(state):
        count = len([h for h in state.get("history", []) if h.get("step") == "supervisor"])
        return {
            "current_subtask": f"sub{count}",
            "believe_done": count == 1,
            "history": state.get("history", []) + [{"step": "supervisor"}],
        }

    def worker(state):
        return {
            "last_obs": {"summary": {"tool_calls": 1}},
            "signatures": state.get("signatures", []) + ["mock"],
            "history": state.get("history", []) + [{"step": "worker"}],
            "worker_error": False,
        }

    def overseer(state):
        return {
            "verdict": {"action": "continue"},
            "history": state.get("history", []) + [{"step": "overseer"}],
        }

    def verifier(cmd, cwd):
        verify_count[0] += 1
        return verify_count[0] == 2, ("fail" if verify_count[0] == 1 else "ok")

    return supervisor, worker, overseer, verifier


async def _run_orchestrator(session_id: str, task_id: str, req: TaskRequest) -> None:
    """在后台线程运行 orchestrator，并持久化 checkpoint。"""
    from driving.orchestrator import drive_orchestrated

    cfg = req.context.get("orchestrator") or {}
    goal = req.description
    verify_cmd = cfg.get("verify_cmd", ["true"])
    cwd = cfg.get("cwd", "/workspace")
    db_path = FLIPPED_CHECKPOINT_DB
    store.update(session_id, goal=goal, verify_cmd=verify_cmd, cwd=cwd, checkpoint_db_path=db_path)
    try:
        if os.environ.get("FLIPPED_MOCK_ORCHESTRATOR"):
            sup, work, over, ver = _mock_orchestrator_fns()
            final = await asyncio.to_thread(
                drive_orchestrated,
                goal=goal, cwd=cwd, verify_cmd=verify_cmd,
                thread_id=session_id, db_path=db_path,
                require_approval=cfg.get("require_approval", False),
                supervisor=sup, worker=work, overseer=over, verifier=ver,
            )
        else:
            final = await asyncio.to_thread(
                drive_orchestrated,
                goal=goal, cwd=cwd, verify_cmd=verify_cmd,
                thread_id=session_id, db_path=db_path,
                require_approval=cfg.get("require_approval", False),
            )
        if final.get("verified"):
            store.update_status(session_id, SessionStatus.done)
        elif final.get("stop_reason") in ("worker_error", "overseer_abort", "loop_detected", "circuit_breaker"):
            store.update_status(session_id, SessionStatus.error)
        else:
            store.update_status(session_id, SessionStatus.review)
    except Exception as exc:
        store.update_status(session_id, SessionStatus.error)
        bus.emit(session_id, EventType.error, Role.system,
                 {"message": f"Orchestrator failed: {exc}"})


async def _resume_orchestrator(session: Session) -> None:
    """从 checkpoint 恢复一个 orchestrator 会话。"""
    from driving.orchestrator import resume_orchestrated

    bus.emit(session.id, EventType.status, Role.system,
             {"status": "running", "progress": 0, "note": "从 checkpoint 恢复继续执行"})
    try:
        if os.environ.get("FLIPPED_MOCK_ORCHESTRATOR"):
            sup, work, over, ver = _mock_orchestrator_fns()
            final = await asyncio.to_thread(
                resume_orchestrated,
                session.id,
                session.checkpoint_db_path,
                supervisor=sup, worker=work, overseer=over, verifier=ver,
            )
        else:
            final = await asyncio.to_thread(
                resume_orchestrated,
                session.id,
                session.checkpoint_db_path,
            )
        if final is None:
            store.update_status(session.id, SessionStatus.error)
            bus.emit(session.id, EventType.error, Role.system,
                     {"message": "没有找到 checkpoint"})
            return
        if final.get("verified"):
            store.update_status(session.id, SessionStatus.done)
        elif final.get("done"):
            store.update_status(session.id, SessionStatus.error)
        else:
            store.update_status(session.id, SessionStatus.running)
    except Exception as exc:
        store.update_status(session.id, SessionStatus.error)
        bus.emit(session.id, EventType.error, Role.system,
                 {"message": f"Resume failed: {exc}"})


async def _run_openhands(session_id: str, task_id: str, description: str, model_alias: str = "coder") -> None:
    """在后台线程运行 OpenHands Worker，避免阻塞 FastAPI 主循环。

    模型端点经 model_router 自动选择(M6.6):LiteLLM proxy 健康走 proxy，
    否则回退 exo 直连(FLIPPED_MODEL_BASE_URL / 默认 exo)。
    """
    from executor.openhands_worker import OpenHandsWorker
    from driving.model_router import resolve_worker_model_config
    from api.mcp_registry import enabled_mcp_config

    base_url, model = resolve_worker_model_config(model_alias)
    worker = OpenHandsWorker(
        session_id=session_id,
        task_id=task_id,
        bus=bus,
        agent_host=os.environ.get("OPENHANDS_AGENT_HOST", "http://localhost:8000"),
        working_dir=os.environ.get("OPENHANDS_WORKING_DIR", "/workspace"),
        model_alias=model,
        base_url=base_url,
        mcp_config=enabled_mcp_config(),
    )
    try:
        await asyncio.to_thread(worker.run, description)
    except Exception as exc:
        bus.emit(session_id, EventType.error, Role.system,
                 {"message": f"OpenHands Worker 失败: {exc}"})
        store.update_status(session_id, SessionStatus.error)


CHAT_SYSTEM = (
    "你是 flipped 的对话助手。用简洁中文回答用户的问题；涉及代码时给出可直接运行的片段。"
    "你只负责对话，不执行任何操作、不修改文件。"
)
PLAN_SYSTEM = (
    "你是 flipped 的规划助手。把用户目标拆解为可执行的有序步骤，每一步给出【要做什么】与【如何验证】。"
    "用 markdown 有序列表输出，聚焦计划本身，不要编写实现代码、不要执行任何操作。"
)


async def _llm_chat(base_url: str, model: str, system: str, user: str, timeout: float = 120.0) -> str:
    """直连 OpenAI 兼容端点做一次非流式对话补全。"""
    url = base_url.rstrip("/") + "/chat/completions"
    api_key = os.environ.get("EXO_API_KEY") or os.environ.get("OPENAI_API_KEY") or "dummy"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {api_key}"})
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


async def _run_chat(session_id: str, task_id: str, description: str, model_alias: str, mode: str) -> None:
    """对话/规划模式：直连本地模型返回文本，不启动沙盒、不用工具。"""
    from driving.model_router import resolve_worker_model_config

    base_url, model = resolve_worker_model_config(model_alias)
    system = PLAN_SYSTEM if mode == "plan" else CHAT_SYSTEM
    note = "规划" if mode == "plan" else "对话"
    bus.emit(session_id, EventType.status, Role.system,
             {"status": "running", "progress": 20, "note": f"{note}中（{model_alias}）"})
    try:
        reply = await _llm_chat(base_url, model, system, description)
        bus.emit(session_id, EventType.message, Role.worker, {"text": reply, "source": "agent"})
        bus.emit(session_id, EventType.status, Role.system,
                 {"status": "done", "progress": 100, "note": f"{note}完成"})
        store.update_status(session_id, SessionStatus.done)
    except Exception as exc:
        bus.emit(session_id, EventType.error, Role.system, {"message": f"{note}失败: {exc}"})
        bus.emit(session_id, EventType.status, Role.system,
                 {"status": "error", "progress": 100, "note": str(exc)})
        store.update_status(session_id, SessionStatus.error)


async def _handle_client_message(session_id: str, data: dict[str, Any]) -> None:
    msg_type = data.get("type")
    if msg_type == "approval_result":
        bus.emit(session_id, EventType.approval_result, Role.user,
                 {"decision": data.get("decision"), "reason": data.get("reason")})
    elif msg_type == "ping":
        pass
    else:
        bus.emit(session_id, EventType.message, Role.user,
                 {"text": data.get("text", ""), "raw": data})


# ---------- Mock 执行流（B1 仅验证通路，B2 替换为 OpenHands Worker） ----------

async def _mock_run(session_id: str, task_id: str, description: str) -> None:
    """模拟一次 Supervisor→Worker→Overseer→Verify 的完整事件流。"""
    def e(type_: EventType, agent: Role | None, payload: dict[str, Any]) -> None:
        bus.emit(session_id, type_, agent, payload, parent_id=task_id)

    e(EventType.message, Role.user, {"text": description})
    await asyncio.sleep(0.3)

    e(EventType.message, Role.supervisor,
      {"text": "拆解目标 → 子任务①：创建 app.py 与 test_app.py，跑 pytest 通过。", "model": "GLM-5.2"})
    await asyncio.sleep(0.2)

    e(EventType.tool_call, Role.worker, {"tool": "file_editor", "summary": "创建 app.py", "status": "running"})
    await asyncio.sleep(0.2)
    e(EventType.file_change, Role.worker, {"path": "/workspace/app.py", "change": "add", "language": "python"})
    e(EventType.tool_result, Role.worker, {"tool": "file_editor", "summary": "创建 app.py", "status": "ok"})
    await asyncio.sleep(0.2)
    if os.environ.get("FLIPPED_MOCK_APPROVAL") == "1":
        bus.emit(session_id, EventType.approval_request, Role.system,
                 {"action": "Worker 写入 /workspace/app.py", "reason": "文件系统写操作，需人工确认", "risk": "medium"})
        approval = await _wait_for_event(session_id, EventType.approval_result)
        decision = str(approval.get("decision", "")).lower()
        if decision not in ("approve", "approved", "yes", "y", "true", "1", "ok", "放行", "同意"):
            store.update_status(session_id, SessionStatus.review)
            bus.emit(session_id, EventType.status, Role.system,
                     {"status": "review", "progress": 20, "note": "审批被否决"})
            bus.emit(session_id, EventType.error, Role.system, {"message": "审批被否决，任务中止"})
            return

    e(EventType.tool_call, Role.worker, {"tool": "file_editor", "summary": "创建 test_app.py", "status": "running"})
    await asyncio.sleep(0.2)
    e(EventType.file_change, Role.worker, {"path": "/workspace/test_app.py", "change": "add", "language": "python"})
    e(EventType.tool_result, Role.worker, {"tool": "file_editor", "summary": "创建 test_app.py", "status": "ok"})
    await asyncio.sleep(0.2)

    e(EventType.tool_call, Role.worker, {"tool": "terminal", "summary": "pytest -q", "status": "running"})
    await asyncio.sleep(0.3)
    e(EventType.terminal, Role.worker, {"command": "pytest -q", "output": "...\n3 passed in 0.42s", "exit_code": 0})
    e(EventType.tool_result, Role.worker, {"tool": "terminal", "summary": "pytest -q", "status": "ok"})
    await asyncio.sleep(0.2)

    e(EventType.message, Role.overseer,
      {"verdict": {"efficiency": 0.9, "direction": 1.0, "action": "continue",
                   "note": "建档+测试完成，方向正确。"}, "model": "GLM-5.2"})
    await asyncio.sleep(0.2)

    e(EventType.message, Role.supervisor,
      {"text": "子任务②：启动 uvicorn，用内置浏览器打开 /docs 截图确认。", "model": "GLM-5.2"})
    await asyncio.sleep(0.2)

    e(EventType.tool_call, Role.worker, {"tool": "terminal", "summary": "uvicorn app:app --port 8000", "status": "running"})
    await asyncio.sleep(0.2)
    e(EventType.terminal, Role.worker, {"command": "uvicorn app:app --port 8000 &",
                                        "output": "Uvicorn running on http://127.0.0.1:8000", "exit_code": 0})
    e(EventType.tool_result, Role.worker, {"tool": "terminal", "summary": "uvicorn app:app --port 8000", "status": "ok"})
    await asyncio.sleep(0.2)

    e(EventType.tool_call, Role.worker, {"tool": "browser", "summary": "打开 /docs 并截图", "status": "running"})
    await asyncio.sleep(0.3)
    e(EventType.browser, Role.worker, {"url": "http://127.0.0.1:8000/docs",
                                       "title": "Todo API - Swagger UI",
                                       "screenshot": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="})
    e(EventType.tool_result, Role.worker, {"tool": "browser", "summary": "打开 /docs 并截图", "status": "ok"})
    await asyncio.sleep(0.2)

    e(EventType.message, Role.overseer,
      {"verdict": {"efficiency": 0.95, "direction": 1.0, "action": "continue",
                   "note": "服务起、页面通、截图有据。"}, "model": "GLM-5.2"})
    await asyncio.sleep(0.2)

    e(EventType.message, Role.verify,
      {"text": "强制验收：pytest 全通过 + /docs HTTP 200 + Swagger 标题匹配 → 目标达成。", "ok": True})
    store.update_status(session_id, SessionStatus.done)
    e(EventType.status, Role.system, {"status": "done", "progress": 100, "note": "任务完成"})
async def _wait_for_event(session_id: str, event_type: EventType, timeout: float = 15.0) -> dict:
    """在 store 中轮询等待指定类型的事件返回。"""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        for ev in reversed(store.events(session_id)):
            if ev.type == event_type:
                return ev.payload
        await asyncio.sleep(0.2)
    return {}
