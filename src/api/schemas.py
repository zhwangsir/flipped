"""orchestration API 的共享 schema。"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventType(str, Enum):
    message = "message"              # 角色文本消息
    tool_call = "tool_call"          # 工具开始调用
    tool_result = "tool_result"      # 工具返回结果
    file_change = "file_change"      # 文件增删改
    terminal = "terminal"            # 终端命令/输出
    browser = "browser"              # 浏览器截图/DOM
    status = "status"                # 会话/任务状态变更
    plan = "plan"                    # 自主循环计划清单快照(F4 · 可见脊柱)
    checkpoint = "checkpoint"        # LangGraph checkpoint 落盘
    snapshot = "snapshot"            # M168 git shadow 快照（assistant undo 地基）
    usage = "usage"                  # M169 token 用量（per-turn opencode 对标）
    approval_request = "approval_request"
    approval_result = "approval_result"
    error = "error"
    rca = "rca"                            # M95 失败根因分析结果
    verifier_verdict = "verifier_verdict"  # M95 并行验证 SemanticVerdict
    token = "token"                        # M166 token 级流式分片（transient，不落盘）
    goal = "goal"                          # M176 goal 模式事件（set/iter/judge/achieved/exhausted/stopped 相位）


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

    model_config = ConfigDict(use_enum_values=True)


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


class ModelAliasEntry(BaseModel):
    """M195.3 · 单个模型 alias → 解析后模型 id。"""
    alias: str
    model: str


class ModelAliasesResponse(BaseModel):
    """M195.3 · GET /models/aliases 响应：可用 alias 清单。"""
    aliases: list[ModelAliasEntry] = Field(default_factory=list)


class ProjectMapInfo(BaseModel):
    """M173 · 项目结构地图（Zread 式全局概览）。"""
    markdown: str
    generated_at: str
    stale: bool
    from_cache: bool
    stack: list[str] = Field(default_factory=list)


class ProjectMapResponse(BaseModel):
    """GET /project/map 与 POST /project/map/regenerate 的统一响应。"""
    map: ProjectMapInfo | None = None
    needs_project: bool = False
