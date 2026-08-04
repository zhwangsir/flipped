"""M170.1 · 编辑器直调 MCP 工具（逻辑模块，薄路由在 api/main.py MCP 段）。

端点：
- GET  /api/v1/mcp/tools                内省 mcp_server.tools.TOOLS 动态生成清单（不硬编码）
- POST /api/v1/mcp/tools/{name}/call    直调工具

快慢分流：
- 快工具（web_search/rag_query/rag_ingest，秒级）：同步 await，200 返回结果；
  run_tool 抛异常 → 200 {"ok": false, "error"}（绝不 500）。
- 长工具（run_coding_task/research_and_code，分钟级）：202 立即受理，
  asyncio.create_task 后台跑，完成/失败回灌指定会话事件流（message/error），
  并注册进 main.RUNNING_TASKS —— 既有 /sessions/{id}/cancel 通路可直接取消，
  任务结束（成功/失败/取消）由 done_callback 清理，语义与既有 assistant 任务一致。

测试注入点（monkeypatch 目标，勿 patch mcp_server.tools 本体）：
- api.mcp_call.run_tool         工具执行入口
- api.mcp_call.list_tool_specs  清单内省入口

mcp_server.tools 会拉 langgraph/chromadb 等重依赖，故生产路径全部函数级
lazy import —— api.main 模块级 import 本模块保持轻量，内省失败也能在
请求期转成明示 500 而非让 app 起不来。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

FAST_TOOLS = frozenset({"web_search", "rag_query", "rag_ingest"})
LONG_TOOLS = frozenset({"run_coding_task", "research_and_code"})

_SUMMARY_LIMIT = 2000  # 回灌会话的摘要长度上限（JSON 过长截断）


# ---------- 数据模型（契约治理：新路由必须用命名 response_model） ----------

class CallToolRequest(BaseModel):
    """POST /mcp/tools/{name}/call 请求体。session_id 仅长工具必填。"""
    arguments: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


class ToolSpec(BaseModel):
    """GET /mcp/tools 的单个工具描述（内省 TOOLS 生成）。"""
    name: str
    description: str
    inputSchema: dict[str, Any]


class ToolListResponse(BaseModel):
    tools: list[ToolSpec]


class CallToolResponse(BaseModel):
    """POST /mcp/tools/{name}/call 响应。

    快工具：ok + result / error（HTTP 200）。
    长工具：ok + accepted + session_id（HTTP 202，由路由据 accepted 置状态码）。
    """
    ok: bool
    tool: str
    accepted: bool = False
    session_id: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


# ---------- 注入点 ----------

async def run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """执行 MCP 工具 —— 模块级名字即测试注入点；生产 lazy 委托 mcp_server.tools。"""
    from mcp_server.tools import run_tool as _impl
    return await _impl(name, arguments)


def list_tool_specs() -> list[dict[str, Any]]:
    """内省 TOOLS → [{name, description, inputSchema}]。失败抛异常，由路由转 500。"""
    from mcp_server.tools import TOOLS
    return [{"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
            for t in TOOLS]


# ---------- 纯函数 ----------

def summarize_result(tool: str, result: Any) -> str:
    """run_tool 返回 → 人类可读摘要：头部带 verified/stop_reason，正文 JSON 截断 ~2000。"""
    flags: list[str] = []
    if isinstance(result, dict):
        if "verified" in result:
            flags.append(f"verified={result['verified']}")
        if result.get("stop_reason"):
            flags.append(f"stop_reason={result['stop_reason']}")
    body = json.dumps(result, ensure_ascii=False, default=str)
    if len(body) > _SUMMARY_LIMIT:
        body = body[:_SUMMARY_LIMIT] + "…(已截断)"
    head = f"🔧 MCP 工具 {tool} 完成"
    if flags:
        head += " · " + " ".join(flags)
    return f"{head}\n{body}"


# ---------- 端点主逻辑 ----------

async def call_tool(name: str, req: CallToolRequest) -> CallToolResponse:
    """快慢分流。HTTPException(404/400/500) 直接上抛，由 FastAPI 渲染。"""
    try:
        known = {spec["name"] for spec in list_tool_specs()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"MCP 工具内省失败: {e}")
    if name not in known:
        raise HTTPException(status_code=404, detail=f"unknown MCP tool: {name}")
    if name in LONG_TOOLS:
        return _accept_long_tool(name, req)
    # 快工具：同步等待，异常折叠成 ok:false（绝不 500）
    try:
        result = await run_tool(name, req.arguments)
    except Exception as e:
        return CallToolResponse(ok=False, tool=name, error=str(e))
    return CallToolResponse(ok=True, tool=name, result=result)


def _accept_long_tool(name: str, req: CallToolRequest) -> CallToolResponse:
    """长工具受理：校验会话 → 后台派发 → 注册 RUNNING_TASKS（取消/清理语义同既有任务）。"""
    from .main import RUNNING_TASKS, store  # 函数级 lazy import 防循环导入

    if not req.session_id:
        raise HTTPException(
            status_code=400,
            detail=f"长耗时工具 {name} 必须携带 session_id（结果回灌该会话事件流）")
    if not store.get(req.session_id):
        raise HTTPException(status_code=404, detail="session not found")
    t = asyncio.create_task(_run_long_tool(name, req.arguments, req.session_id))
    RUNNING_TASKS[req.session_id] = t
    t.add_done_callback(lambda _t, sid=req.session_id: RUNNING_TASKS.pop(sid, None))
    return CallToolResponse(ok=True, tool=name, accepted=True, session_id=req.session_id)


async def _run_long_tool(name: str, arguments: dict[str, Any], session_id: str) -> None:
    """后台执行体：完成 → worker message 摘要；异常 → error 事件。

    Exception 全部兜住（emit 失败也仅静默），绝不炸主事件循环；
    CancelledError（经既有 /cancel 通路 task.cancel()）不捕获、自然传播，
    done_callback 负责从 RUNNING_TASKS 清理 —— 与 main.py 既有 assistant 任务同语义。
    """
    from .main import bus  # 函数级 lazy import 防循环导入
    from .schemas import EventType, Role

    try:
        result = await run_tool(name, arguments)
    except Exception as e:
        try:
            bus.emit(session_id, EventType.error, Role.system,
                     {"message": str(e), "tool": name, "source": "mcp"})
        except Exception:
            pass
        return
    try:
        bus.emit(session_id, EventType.message, Role.worker,
                 {"text": summarize_result(name, result), "tool": name, "source": "mcp"})
    except Exception:
        pass
