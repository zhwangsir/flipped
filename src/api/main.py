"""flipped orchestration API。

入口: uvicorn src.api.main:app --host 127.0.0.1 --port 8001
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .events import EventBus, get_bus
from .schemas import EventType, HealthResponse, Role, Session, SessionStatus, TaskRequest, TaskResponse
from .session import SessionStore, store

MOCK_WORKER = os.environ.get("FLIPPED_MOCK_WORKER", "0") == "1"

API_PREFIX = "/api/v1"
CONSOLE_ORIGIN = "http://127.0.0.1:5273"

bus: EventBus = get_bus(store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bus.set_loop(asyncio.get_running_loop())
    yield
    bus.set_loop(None)
    bus._connections.clear()


app = FastAPI(title="flipped orchestration API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[CONSOLE_ORIGIN, "http://localhost:5273"],
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


# ---------- 会话管理 ----------

@app.post(f"{API_PREFIX}/sessions", response_model=Session)
async def create_session(title: str = "新任务") -> Session:
    session = store.create(title=title)
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
    if MOCK_WORKER:
        asyncio.create_task(_mock_run(session_id, task_id, req.description))
    else:
        asyncio.create_task(_run_openhands(session_id, task_id, req.description))
    return TaskResponse(task_id=task_id, session_id=session_id, status="running")


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


async def _run_openhands(session_id: str, task_id: str, description: str) -> None:
    """在后台线程运行 OpenHands Worker，避免阻塞 FastAPI 主循环。"""
    from executor.openhands_worker import OpenHandsWorker

    worker = OpenHandsWorker(
        session_id=session_id,
        task_id=task_id,
        bus=bus,
        agent_host=os.environ.get("OPENHANDS_AGENT_HOST", "http://localhost:8000"),
        working_dir=os.environ.get("OPENHANDS_WORKING_DIR", "/workspace"),
        model_alias=os.environ.get("OPENHANDS_MODEL", "coder"),
        base_url=os.environ.get("OPENHANDS_BASE_URL"),
    )
    try:
        await asyncio.to_thread(worker.run, description)
    except Exception as exc:
        bus.emit(session_id, EventType.error, Role.system,
                 {"message": f"OpenHands Worker 失败: {exc}"})
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
