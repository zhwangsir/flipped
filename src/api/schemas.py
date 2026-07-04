"""orchestration API 的共享 schema。"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    message = "message"              # 角色文本消息
    tool_call = "tool_call"          # 工具开始调用
    tool_result = "tool_result"      # 工具返回结果
    file_change = "file_change"      # 文件增删改
    terminal = "terminal"            # 终端命令/输出
    browser = "browser"              # 浏览器截图/DOM
    status = "status"                # 会话/任务状态变更
    checkpoint = "checkpoint"        # LangGraph checkpoint 落盘
    approval_request = "approval_request"
    approval_result = "approval_result"
    error = "error"


class Role(str, Enum):
    user = "user"
    supervisor = "supervisor"
    worker = "worker"
    overseer = "overseer"
    verify = "verify"
    system = "system"


class SessionStatus(str, Enum):
    idle = "idle"
    running = "running"
    paused = "paused"
    done = "done"
    review = "review"
    error = "error"


class Event(BaseModel):
    id: str
    session_id: str
    type: EventType
    agent: Role | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    parent_id: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    class Config:
        use_enum_values = True


class Session(BaseModel):
    id: str
    title: str
    status: SessionStatus
    model: str = "coder"
    mode: str = "agent"  # agent(项目) | plan(项目) | chat(对话) — 驱动侧栏项目/对话分区
    project: str | None = None       # 会话所属项目的 host 路径(~/projects/<名>),创建时捕获活动项目
    project_name: str | None = None  # 项目名(basename),供侧栏显示/分组
    goal: str | None = None
    verify_cmd: list[str] = Field(default_factory=list)
    cwd: str = "/workspace"
    checkpoint_db_path: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TaskRequest(BaseModel):
    description: str = Field(..., min_length=1, description="本次任务描述")
    context: dict[str, Any] = Field(default_factory=dict, description="额外上下文，透传给执行器")


class BrowserRenderRequest(BaseModel):
    url: str = Field(..., min_length=1, description="要渲染的目标 URL（仅 http/https）")


class TaskResponse(BaseModel):
    task_id: str
    session_id: str
    status: str


class HealthResponse(BaseModel):
    ok: bool
    proxy: dict[str, Any]
    error: str | None = None


class MetricsResponse(BaseModel):
    """/metrics 端点返回的 LLM / 上下文性能指标。"""
    llm: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
