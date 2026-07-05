"""OpenHands SDK Worker 封装。

把 OpenHands RemoteConversation 的事件翻译成 flipped 统一事件 schema，
并通过 EventBus 实时广播给 Console。
"""
from __future__ import annotations

import os
import threading
from typing import Any

# 抑制 OpenHands SDK banner 与 litellm 远程 cost map 拉取超时警告
os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_LOG", "ERROR")

from openhands.sdk.agent.agent import Agent
from openhands.sdk.conversation.impl.remote_conversation import RemoteConversation
from openhands.sdk.conversation.state import ConversationExecutionStatus
from openhands.sdk.event.base import Event as OHEvent
from openhands.sdk.event.llm_convertible.action import ActionEvent
from openhands.sdk.event.llm_convertible.message import MessageEvent
from openhands.sdk.event.llm_convertible.observation import ObservationEvent
from openhands.sdk.llm.llm import LLM
from openhands.sdk.tool.registry import get_tool_module_qualnames
from openhands.sdk.workspace.remote.base import RemoteWorkspace

# 预注册工具定义，让 agent-server 能动态加载
import openhands.tools.file_editor  # noqa: F401
import openhands.tools.task_tracker  # noqa: F401
import openhands.tools.terminal  # noqa: F401

from api.events import EventBus
from api.schemas import EventType, Role
from driving.safety import audit_openhands_events
from metrics import COLLECTOR


def _sum_conversation_usage(state) -> tuple[int, int, int]:
    """从 OpenHands ConversationState.stats 汇总 (prompt, completion, llm调用数)。

    Worker(Kimi)的推理不经我们的 LangChain callback,F10 用量曾大幅低估——
    经 SDK 的 ConversationStats.usage_to_metrics 补上。防御式:任何缺字段返回 0。
    """
    prompt = completion = calls = 0
    stats = getattr(state, "stats", None)
    mapping = getattr(stats, "usage_to_metrics", None) or {}
    for m in mapping.values():
        acc = getattr(m, "accumulated_token_usage", None)
        if acc is not None:
            prompt += int(getattr(acc, "prompt_tokens", 0) or 0)
            completion += int(getattr(acc, "completion_tokens", 0) or 0)
        calls += len(getattr(m, "token_usages", []) or [])
    return prompt, completion, calls


class OpenHandsWorker:
    """单个沙盒会话 Worker：一个任务 = 一次 RemoteConversation 运行。"""

    DEFAULT_TOOLS = [
        {"name": "terminal", "params": {}},
        {"name": "file_editor", "params": {}},
        {"name": "task_tracker", "params": {}},
    ]

    def __init__(
        self,
        session_id: str,
        task_id: str,
        bus: EventBus,
        *,
        agent_host: str = "http://localhost:8000",
        working_dir: str = "/workspace",
        model_alias: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        mcp_config: dict[str, Any] | None = None,
        timeout: float | None = None,
        manage_session_status: bool = True,
    ):
        self.session_id = session_id
        self.task_id = task_id
        self.bus = bus
        self.agent_host = agent_host
        self.working_dir = working_dir
        self.model_alias = model_alias or os.environ.get("OPENHANDS_MODEL", "coder")
        self.base_url = base_url or os.environ.get("OPENHANDS_BASE_URL", "http://host.docker.internal:4000/v1")
        self.api_key = api_key or self._default_agent_api_key()
        self.tools = tools or self.DEFAULT_TOOLS
        self.mcp_config = mcp_config or {}
        # F8 实测经验:两个可调旋钮(默认与原值一致)。卡死类子任务达迭代上限后由
        # orchestrator 分类回灌重拆——上限越小止损越快, 但太小会截断正常长任务。
        self.timeout = timeout if timeout is not None else float(
            os.environ.get("FLIPPED_WORKER_TIMEOUT", "600"))
        self.max_iterations = int(os.environ.get("FLIPPED_WORKER_MAX_ITERATIONS", "50"))
        # F8 实测缺陷:orchestrator 模式下 worker 一跑完就把会话状态设 done,
        # 覆盖了还在继续的外层循环(overseer/verify/下一轮)。False=子任务模式,不碰会话状态。
        self.manage_session_status = manage_session_status
        self._events: list[OHEvent] = []
        self._lock = threading.Lock()

    @staticmethod
    def _default_agent_api_key() -> str:
        if os.environ.get("OPENHANDS_API_KEY"):
            return os.environ["OPENHANDS_API_KEY"]
        # 去 TOCTOU:直接 try open,文件缺失/权限问题都优雅返回空(绝不抛,免拖垮调用方)
        key_file = os.path.expanduser("~/.openhands/agent-canvas/api-key.txt")
        try:
            with open(key_file) as f:
                return f.read().strip()
        except OSError:
            return ""

    def _emit(self, type_: EventType, agent: Role | None, payload: dict[str, Any]) -> None:
        self.bus.emit(self.session_id, type_, agent, payload, parent_id=self.task_id)

    def _on_event(self, event: OHEvent) -> None:
        with self._lock:
            self._events.append(event)
        self._translate_and_emit(event)

    def _translate_and_emit(self, event: OHEvent) -> None:
        kind = event.__class__.__name__
        try:
            if isinstance(event, MessageEvent):
                text = ""
                if event.llm_message and event.llm_message.content:
                    for c in event.llm_message.content:
                        if hasattr(c, "text"):
                            text += c.text
                role = Role.worker if event.source == "agent" else Role.system
                self._emit(EventType.message, role, {"text": text, "source": event.source})

            elif isinstance(event, ActionEvent):
                tool = event.tool_name or "unknown"
                summary = ""
                if event.thought:
                    summary = " ".join(t.text for t in event.thought if hasattr(t, "text"))
                if event.action is not None:
                    summary = summary or getattr(event.action, "_summary", "") or tool
                self._emit(EventType.tool_call, Role.worker,
                           {"tool": tool, "summary": summary, "status": "running"})
                # M7.2 — 从 file_editor 动作抓真实文件内容(供编辑器 Tab 展示)
                if tool == "file_editor" and event.action is not None:
                    fpath = getattr(event.action, "path", None)
                    fcontent = getattr(event.action, "file_text", None) or getattr(event.action, "new_str", None)
                    if fpath and fcontent:
                        self._emit(EventType.file_change, Role.worker,
                                   {"path": fpath, "change": getattr(event.action, "command", "mod"),
                                    "content": str(fcontent)[:8000]})

            elif isinstance(event, ObservationEvent):
                tool = event.tool_name or "unknown"
                status = "error" if getattr(event.observation, "success", True) is False else "ok"
                payload: dict[str, Any] = {"tool": tool, "summary": tool, "status": status}
                extra: dict[str, Any] = {}
                obs = event.observation
                if obs is not None:
                    payload["summary"] = getattr(obs, "_summary", tool)
                    # 提取通用字段(F8 实测:TerminalObservation 的输出字段是 content 而非 output)
                    for attr in ("command", "output", "path", "content", "url", "screenshot", "exit_code"):
                        if hasattr(obs, attr):
                            extra[attr] = getattr(obs, attr)
                    # 终端输出单独给 terminal 事件(content 兜底 output,截尾防灌爆)
                    if tool == "terminal" and ("command" in extra or "output" in extra or "content" in extra):
                        raw_out = extra.get("output") or extra.get("content") or ""
                        # content 是 TextContent 对象列表(F8 实测) → 提取 .text 而非 repr
                        if isinstance(raw_out, list):
                            raw_out = "\n".join(
                                getattr(c, "text", None) or str(c) for c in raw_out
                            )
                        self._emit(EventType.terminal, Role.worker,
                                   {"command": extra.get("command", ""),
                                    "output": str(raw_out)[-4000:],
                                    "exit_code": extra.get("exit_code", 0)})
                    # 文件变更事件由上游 ActionEvent 携带真实内容发出（含 path/change/content），
                    # observation 只保留 tool_result 确认，避免冗余覆盖与把 view 误报成变更。
                    # 浏览器单独给 browser 事件
                    if tool.startswith("browser") and ("url" in extra or "screenshot" in extra):
                        self._emit(EventType.browser, Role.worker,
                                   {"url": extra.get("url", ""),
                                    "title": extra.get("title", ""),
                                    "screenshot": extra.get("screenshot", "")})
                self._emit(EventType.tool_result, Role.worker, payload)
        except Exception as exc:
            self._emit(EventType.error, Role.system,
                       {"message": f"事件翻译失败({kind}): {exc}", "event_kind": kind})

    def run(self, task_description: str) -> dict[str, Any]:
        """同步阻塞运行一次任务；返回摘要。"""
        self._emit(EventType.status, Role.system,
                   {"status": "running", "progress": 5, "note": "连接 OpenHands agent-server"})
        try:
            # 对 OpenAI 兼容端点，litellm 需要 provider 前缀才能识别路由
            model_name = self.model_alias
            if self.base_url and "/v1" in self.base_url and not model_name.startswith("openai/"):
                model_name = f"openai/{model_name}"
            llm = LLM(
                model=model_name,
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=300,
                num_retries=2,
                drop_params=True,
                native_tool_calling=True,
            )
            agent_kwargs: dict[str, Any] = dict(
                llm=llm, tools=self.tools, include_default_tools=["FinishTool", "ThinkTool"]
            )
            # M7.3 — 仅在有启用的 MCP 服务器时注入，保持默认执行路径不变
            if self.mcp_config:
                agent_kwargs["mcp_config"] = self.mcp_config
            agent = Agent(**agent_kwargs)
            workspace = RemoteWorkspace(host=self.agent_host, working_dir=self.working_dir, api_key=self.api_key)
            with workspace:
                conversation = RemoteConversation(
                    agent=agent,
                    workspace=workspace,
                    callbacks=[self._on_event],
                    max_iteration_per_run=self.max_iterations,
                    delete_on_close=True,
                )
                self._emit(EventType.status, Role.system,
                           {"status": "running", "progress": 10, "note": "派发任务到沙盒"})
                conversation.send_message(task_description, sender="flipped-supervisor")
                conversation.run(blocking=True, poll_interval=1.0, timeout=self.timeout)
                violations = audit_openhands_events(self._events)
                if violations:
                    raise RuntimeError(violations[0])

                final_state = conversation.state
                status = getattr(final_state, "execution_status", None)
                status_done = status == ConversationExecutionStatus.FINISHED
                # F10 补全:Worker(Kimi)沙盒会话的 token 用量汇入全局统计(尽力而为)
                try:
                    p, c, n = _sum_conversation_usage(final_state)
                    if p or c:
                        COLLECTOR.record_usage(prompt_tokens=p, completion_tokens=c, calls=n)
                except Exception:  # noqa: BLE001 统计失败绝不影响任务
                    pass
                if self.manage_session_status:
                    self._emit(EventType.status, Role.system,
                               {"status": "done" if status_done else str(status),
                                "progress": 100,
                                "note": f"执行结束: {status}",
                                "total_events": len(getattr(final_state, "events", []) or [])})
                    self.bus.set_status(self.session_id, "done" if status_done else str(status))
                else:
                    # 子任务模式:只报进度,不定会话终态(外层循环还在跑)
                    self._emit(EventType.status, Role.system,
                               {"status": "running", "progress": 60,
                                "note": f"子任务执行结束: {status}"})
                return {
                    "status": str(status),
                    "events_count": len(self._events),
                    "conversation_id": str(conversation.id),
                }
        except Exception as exc:
            self._emit(EventType.error, Role.system, {"message": str(exc)})
            if self.manage_session_status:
                self._emit(EventType.status, Role.system, {"status": "error", "progress": 100, "note": str(exc)})
                self.bus.set_status(self.session_id, "error")
            raise

    @property
    def events(self) -> list[OHEvent]:
        with self._lock:
            return list(self._events)
