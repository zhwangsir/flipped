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
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TaskRequest(BaseModel):
    description: str = Field(..., min_length=1, description="本次任务描述")
    context: dict[str, Any] = Field(default_factory=dict, description="额外上下文，透传给执行器")


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
