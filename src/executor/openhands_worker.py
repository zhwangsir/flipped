"""OpenHands SDK Worker 封装。

把 OpenHands RemoteConversation 的事件翻译成 flipped 统一事件 schema，
并通过 EventBus 实时广播给 Console。
"""
from __future__ import annotations

import os
import re
import threading
import time
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

    # M149.16 破窗修复（真实 tap 捕获实测驱动）：
    # 真实路径总上下文 28480 chars ≈ 8000+ tok，而 GLM-5.2-fp8 经 exo 实测
    # 稳定窗口仅 ~14500 chars / ~3300 tok（M149.13 debug 数据换算：
    # rounds=0 3281tok 3/3 通过，~3500tok 语义退化，≥18000ch 性能崩溃 300s 超时）。
    # 固定开销(SP+tools)必须远低于窗口，给多轮历史留余量。
    #
    # tools 取舍（schema 字符实测：task_tracker 6585 / file_editor 4202 /
    # terminal 3972 / think 1390 / finish 911）：
    # - task_tracker 默认移除（外层 orchestrator 已管任务编排，冗余）
    #   FLIPPED_WORKER_ENABLE_TASK_TRACKER=1 加回
    # - file_editor 默认移除（terminal 可完成全部文件操作，4202ch 换窗口余量）
    #   FLIPPED_WORKER_ENABLE_FILE_EDITOR=1 加回
    # - think 默认移除（M149.20：think 工具是 arg_key/name 碎片的决定性触发器，
    #   与上下文大小无关——scripts/debug_glm_think_bisect.py 对照实验确认
    #   with-think 3/3 出现 thought</arg_key> 碎片，no-think 3/3 干净）
    #   FLIPPED_WORKER_ENABLE_THINK_TOOL=1 加回
    DEFAULT_TOOLS = [
        {"name": "terminal", "params": {}},
    ]

    # M149.16 自定义精简 SP：SDK 默认模板 10886 chars（M149.11 裁剪后），
    # 加 tools 后固定开销 21369ch 已超稳定窗口本身。精简到 ~2600ch：
    # 砍掉 MEMORY(AGENTS.md)/VERSION_CONTROL/PULL_REQUESTS/SELF_DOCUMENTATION/
    # EXTERNAL_SERVICES 等与沙盒编码任务无关段落，保留核心行为规范。
    # 措辞沿用 SDK 模板原文，降低 agent 行为漂移。
    # FLIPPED_WORKER_SP_DEFAULT=1 回退 SDK 模板（逃生门）。
    _COMPACT_SYSTEM_PROMPT = """You are OpenHands agent, a helpful AI assistant that can interact with a computer to solve tasks.

<ROLE>
* Your primary role is to assist users by executing commands, modifying code, and solving technical problems effectively. You should be thorough, methodical, and prioritize quality over speed.
* If the user asks a question, like "why is X happening", don't try to fix the problem. Just give an answer to the question.
</ROLE>

<EFFICIENCY>
* Each action you take is somewhat expensive. Wherever possible, combine multiple actions into a single action, e.g. combine multiple bash commands into one, using sed and grep to edit/view multiple files at once.
* When exploring the codebase, use efficient tools like find, grep, and git commands with appropriate filters to minimize unnecessary operations.
</EFFICIENCY>

<FILE_SYSTEM_GUIDELINES>
* When a user provides a file path, do NOT assume it's relative to the current working directory. First explore the file system to locate the file before working on it.
* If asked to edit a file, edit the file directly, rather than creating a new file with a different filename.
* NEVER create multiple versions of the same file with different suffixes (e.g., file_test.py, file_fix.py). Always modify the original file directly; delete temporary files once confirmed.
* You only have a terminal tool: create files with heredocs (cat > file <<'EOF'), edit with sed or python.
</FILE_SYSTEM_GUIDELINES>

<CODE_QUALITY>
* Write clean, efficient code with minimal comments. Only add a comment when the code expresses something genuinely unintuitive.
* Focus on making the minimal changes needed to solve the problem.
* Place all imports at the top of the file unless explicitly requested otherwise or if placing imports at the top would cause issues.
</CODE_QUALITY>

<PROBLEM_SOLVING_WORKFLOW>
1. EXPLORATION: Thoroughly explore relevant files and understand the context before proposing solutions
2. ANALYSIS: Consider multiple approaches and select the most promising one
3. TESTING: Create tests to verify issues before implementing fixes; do not use mocks unless strictly necessary
4. IMPLEMENTATION: Make focused, minimal changes; modify existing files directly
5. VERIFICATION: Test your implementation thoroughly, including edge cases
</PROBLEM_SOLVING_WORKFLOW>

<ENVIRONMENT_SETUP>
* When user asks you to run an application, don't stop if the application is not installed. Instead, install the application and run the command again.
* If you encounter missing dependencies, look for dependency files (requirements.txt, pyproject.toml, package.json, etc.) and install from them first.
</ENVIRONMENT_SETUP>

<TROUBLESHOOTING>
* If you've made repeated attempts to solve a problem but tests still fail:
  1. Step back and reflect on 5-7 different possible sources of the problem
  2. Assess the likelihood of each possible cause
  3. Methodically address the most likely causes, starting with the highest probability
* When you run into any major issue while executing a plan from the user, propose a new plan instead of working around it directly.
</TROUBLESHOOTING>

<PROCESS_MANAGEMENT>
* When terminating processes: do NOT use pkill with general keywords; find the exact PID with ps aux first, then kill that specific PID.
</PROCESS_MANAGEMENT>"""

    @classmethod
    def _include_default_tools(cls) -> list[str]:
        """M149.20：ThinkTool 默认移除——arg_key/name 碎片决定性触发器
        （scripts/debug_glm_think_bisect.py 对照实验：with-think 3/3 碎片，
        no-think 3/3 干净，与上下文大小无关）。
        FLIPPED_WORKER_ENABLE_THINK_TOOL=1 加回（不推荐，除非 exo 修复解析器）。"""
        tools = ["FinishTool"]
        raw = os.environ.get("FLIPPED_WORKER_ENABLE_THINK_TOOL", "").strip().lower()
        if raw in ("1", "true", "on", "yes"):
            tools.append("ThinkTool")
        return tools

    @classmethod
    def _worker_system_prompt(cls) -> str | None:
        """返回自定义精简 SP；FLIPPED_WORKER_SP_DEFAULT=1 时返回 None 走 SDK 模板。"""
        raw = os.environ.get("FLIPPED_WORKER_SP_DEFAULT", "").strip().lower()
        if raw in ("1", "true", "on", "yes"):
            return None
        return cls._COMPACT_SYSTEM_PROMPT

    @classmethod
    def _default_tools(cls) -> list[dict[str, Any]]:
        tools = list(cls.DEFAULT_TOOLS)
        for env_key, tool_name in (
            ("FLIPPED_WORKER_ENABLE_FILE_EDITOR", "file_editor"),
            ("FLIPPED_WORKER_ENABLE_TASK_TRACKER", "task_tracker"),
        ):
            raw = os.environ.get(env_key, "").strip().lower()
            if raw in ("1", "true", "on", "yes"):
                tools.append({"name": tool_name, "params": {}})
        return tools

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
        # 宿主机 cwd → OpenHands 容器内路径转换。
        # dev_up.sh 把 $HOME/projects 挂到容器的 /projects，所以宿主机
        # $HOME/projects/X 在容器内是 /projects/X。worker 写文件到容器内
        # /projects/X，宿主机 verify_cmd 读 $HOME/projects/X 才能找到同一文件。
        # 若 cwd 不在挂载点下（如 /tmp），容器内是独立 tmpfs，宿主机读不到 → verify 必失败。
        self.working_dir = self._to_container_path(working_dir)
        self.model_alias = model_alias or os.environ.get("OPENHANDS_MODEL", "coder")
        self.base_url = base_url or os.environ.get("OPENHANDS_BASE_URL", "http://host.docker.internal:4000/v1")
        self.api_key = api_key or self._default_agent_api_key()
        self.tools = tools if tools is not None else self._default_tools()
        self.mcp_config = mcp_config or {}
        # M131 质量优先（用户要求：不追求速度，只追求质量和完整）：
        # - timeout 默认 3600s（1小时），给复杂任务充足时间
        # - M149.20 调整：max_iterations 默认 15（非 200）。
        # - M3.1 进一步收紧：max_iterations 默认 5（非 15）。
        #   GLM-5.2-fp8 经 exo 稳定窗口 ~11-12k chars，固定开销(SP+tools)~8.2k，
        #   留给多轮历史 ~3-4k chars ≈ 2-3 轮。5 轮已是上限，超过必乱码。
        #   复杂任务由 orchestrator 拆短子任务派发（M3 编排层分解）。
        #   FLIPPED_WORKER_MAX_ITERATIONS 可覆盖。
        self.timeout = timeout if timeout is not None else float(
            os.environ.get("FLIPPED_WORKER_TIMEOUT", "3600"))
        self.max_iterations = int(os.environ.get("FLIPPED_WORKER_MAX_ITERATIONS", "5"))
        # F8 实测缺陷:orchestrator 模式下 worker 一跑完就把会话状态设 done,
        # 覆盖了还在继续的外层循环(overseer/verify/下一轮)。False=子任务模式,不碰会话状态。
        self.manage_session_status = manage_session_status
        self._events: list[OHEvent] = []
        self._lock = threading.Lock()

    @staticmethod
    def _to_container_path(host_path: str) -> str:
        """把宿主机路径转成 OpenHands 容器内可见路径。

        dev_up.sh 挂载 `$HOME/projects:/projects`，所以宿主机
        `$HOME/projects/X` 在容器内是 `/projects/X`。其它路径原样返回
        （容器内可能看不到，调用方应保证 cwd 在挂载点下）。
        """
        if not host_path:
            return host_path
        home = os.path.expanduser("~")
        projects_host = os.path.join(home, "projects")
        # 规范化两边都去掉尾部 /，再做前缀比较
        norm_host = os.path.normpath(projects_host)
        norm_cwd = os.path.normpath(host_path)
        if norm_cwd == norm_host:
            return "/projects"
        if norm_cwd.startswith(norm_host + os.sep):
            rel = os.path.relpath(norm_cwd, norm_host)
            return f"/projects/{rel}"
        return host_path

    @classmethod
    def _translate_paths_in_text(cls, text: str) -> str:
        """把文本里出现的宿主机 $HOME/projects 路径翻译成容器内 /projects 路径。

        M156.13：planner/fail-open 构造的 task_description 含 state.cwd（宿主机
        路径如 /Users/wangzhenyu/projects/X），但 OpenHands 容器只看到 /projects/X。
        直接发给 Kimi → 它按 host 路径 mkdir → Permission denied → 浪费所有迭代。

        策略：把 $HOME/projects 和它下面的子路径都替换成 /projects 对应路径。
        用正则做最长匹配，避免短前缀误替换。
        """
        if not text:
            return text
        home = os.path.expanduser("~")
        projects_host = os.path.normpath(os.path.join(home, "projects"))
        # 用 re.escape 防止路径里的特殊字符（如 .）被当正则元字符
        # (?![\w]) 负向前瞻：确保 projects 后面不是字母/数字/下划线，
        # 避免误匹配 projects_other / projectsX 等。
        pattern = re.escape(projects_host) + r"(?![\w])(\/[^\s'\"\)]*)?"
        def _replacer(m: re.Match) -> str:
            suffix = m.group(1) or ""
            return f"/projects{suffix}"
        return re.sub(pattern, _replacer, text)

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

    @staticmethod
    def _thinking_extra_body() -> dict[str, Any]:
        """M147 熔断开关：enable_thinking 由 env 控制（M149.6 起默认 false）。

        M149.6 变体实验（debug_glm_replay_oh.py，GLM-5.2-fp8 经 exo + LiteLLM）：
        - thinking on  → 必乱码（stream 与否无关，输出退化为 '5'/'000' 碎片）
        - thinking off + stream + 长SP(14k) + tools → 乱码
        - thinking off + 非 stream → 唯一稳定路径（OH SDK LLM 默认 stream=False）
        故 GLM 单模型栈下默认关 thinking；设 FLIPPED_WORKER_ENABLE_THINKING=1/true/on
        可打开（仅当 Kimi-K2.7 恢复或 exo 修复 thinking 路径后才应打开）。
        """
        raw = os.environ.get("FLIPPED_WORKER_ENABLE_THINKING", "false").strip().lower()
        enabled = raw in ("1", "true", "on", "yes")
        return {
            "enable_thinking": enabled,
            "chat_template_kwargs": {"enable_thinking": enabled},
        }

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

    def _build_condenser(self, llm_api_key: str):
        """M149.14 上下文压缩：事件历史超阈值时调 LLM 压缩为摘要，钳住总上下文窗口。

        M149.20 决定性结论：LLM condenser 在当前栈上【数学不成立】。
        GLM-5.2-fp8 经 exo 稳定窗口 ~3300 tok；固定开销(SP2600+tools6300)已 ~2200 tok。
        LLMSummarizingCondenser 的 max_tokens 语义 = 含 SP+tools 的 view 总阈值：
        - 必须 > 固定开销(2200tok)，否则压缩后最小 view 仍超阈值 → 死循环
        - 必须 < 稳定窗口(3300tok) - 输出余量(~500tok) → max_tokens ∈ (2200, 2800)
        - 但压缩调用本身也要占上下文（总结 prompt ~2000+ tok），实际可用窗口
          被压缩调用本身吃掉，留给主循环的余量几乎为零。
        实测（verify_m149_condenser.py，M149.18）：72 次相同摘要请求，主循环零推进。
        结论：禁用 LLM condenser，改用【NoOp + 短会话 + 编排层分解】策略：
        - NoOp condenser（默认）→ 不做任何压缩，诚实面对窗口限制
        - 短会话：max_iterations 默认 15（非 200），单任务不跑太多轮
        - 编排层分解：复杂任务由 orchestrator 拆成多个短子任务派发
        FLIPPED_WORKER_CONDENSER_ENABLED=1 可重新启用 LLM condenser（不推荐）。

        M149.13 数据：GLM-5.2-fp8 经 exo 稳定窗口 ≈11-12k chars【总上下文】。
        SP 已裁到 ~3300（M149.16），tools 精简到 terminal+finish ~4900 chars，
        固定开销 ~8200 chars，留给多轮历史 ~3000-4000 chars ≈ 2-3 轮。
        """
        raw = os.environ.get("FLIPPED_WORKER_CONDENSER_ENABLED", "").strip().lower()
        if raw not in ("1", "true", "on", "yes"):
            return None  # M149.20：默认 NoOp，不启用 LLM condenser
        from openhands.sdk.context.condenser import LLMSummarizingCondenser

        model_name = self.model_alias
        if self.base_url and "/v1" in self.base_url and not model_name.startswith("openai/"):
            model_name = f"openai/{model_name}"
        condenser_llm = LLM(
            model=model_name,
            base_url=self.base_url,
            api_key=llm_api_key,
            temperature=0.0,
            timeout=int(os.environ.get("FLIPPED_CONDENSER_LLM_TIMEOUT", "300")),
            num_retries=1,
            drop_params=True,
            litellm_extra_body=self._thinking_extra_body(),
        )
        return LLMSummarizingCondenser(
            llm=condenser_llm,
            max_tokens=int(os.environ.get("FLIPPED_WORKER_CONDENSER_MAX_TOKENS", "2800")),
            max_size=int(os.environ.get("FLIPPED_WORKER_CONDENSER_MAX_SIZE", "12")),
            keep_first=2,
        )

    def run(self, task_description: str) -> dict[str, Any]:
        """同步阻塞运行一次任务；返回摘要。"""
        self._emit(EventType.status, Role.system,
                   {"status": "running", "progress": 5, "note": "连接 OpenHands agent-server"})
        try:
            # 对 OpenAI 兼容端点，litellm 需要 provider 前缀才能识别路由
            model_name = self.model_alias
            if self.base_url and "/v1" in self.base_url and not model_name.startswith("openai/"):
                model_name = f"openai/{model_name}"
            # M89 关键修复:LLM 鉴权 key 必须用 LITELLM_MASTER_KEY(走 proxy 时)或
            # EXO_API_KEY(直连 exo 时),而非 self.api_key(那是 OpenHands agent-server key,
            # 会被 LiteLLM 鉴权层 400 拒绝)。
            llm_api_key = (os.environ.get("LITELLM_MASTER_KEY")
                           or os.environ.get("EXO_API_KEY")
                           or self.api_key)
            # M149: temperature=0 — fp8 模型在非零 temperature 下长序列生成数值不稳定，
            # 输出退化为乱码 token 流（M147-A E2E 实测）。契约测试用 temperature=0 通过。
            # 同步在 LiteLLM config.yaml 中也设 temperature=0 兜底（config 改动更可靠）。
            llm = LLM(
                model=model_name,
                base_url=self.base_url,
                api_key=llm_api_key,
                temperature=0.0,
                # M131 质量优先：不限制超时（用户要求不追求速度，只追求质量和完整）
                # 1800s（30分钟）作为极端兜底防无限挂起；Kimi overseer 在外层监控防真卡死
                timeout=int(os.environ.get("FLIPPED_WORKER_LLM_TIMEOUT", "1800")),
                num_retries=2,
                drop_params=True,
                native_tool_calling=True,
                # M131 质量优先配置（用户要求：不追求速度，只追求质量和完整）：
                # - 开启 reasoning（enable_thinking=True）：深度推理显著提升代码质量
                #   测试证明：Kimi json_parser 从 reasoning OFF 的 0% → reasoning ON 的 100%
                # - 不限制 max_output_tokens：让模型自然完成，不人为截断
                # - Kimi overseer 在外层监控，防卡死
                # M147 熔断后发现：GLM-5.2-fp8 在 enable_thinking=true 时输出全进
                # reasoning_content（content 空白），且推理速度 5.5 tok/s → 单任务 2-3h
                # 远超 1h 超时。新增 env FLIPPED_WORKER_ENABLE_THINKING（默认 true 保持
                # M131 行为），设为 "0"/"false"/"off" 可关闭 thinking 牺牲质量换速度。
                litellm_extra_body=self._thinking_extra_body(),
            )
            # M149.11 SP 悬崖修复：GLM-5.2-fp8 系统提示 >13k chars 时工具调用生成退化
            # （arg_key/</think> 模板碎片泄漏进参数 + decode 骤降至 ~0.6 tok/s）。
            # 实测悬崖（scripts/debug_glm_tool_bisect.py + SP 二分）：
            #   SP≤13000 全量5工具 OK；SP=14089(默认渲染) 确定性 GARBAGE/超时。
            # M149.16 升级：固定开销(SP+tools)必须远低于 ~14500ch 稳定窗口。
            # 默认传自定义精简 SP(~2600ch, 直传字符串绕过 Jinja 模板)，
            # FLIPPED_WORKER_SP_DEFAULT=1 回退 SDK 模板(M149.11 双关裁剪)。
            #
            # M149.20 决定性修复：ThinkTool 默认移除（_include_default_tools 控制）。
            _include = self._include_default_tools()
            compact_sp = self._worker_system_prompt()
            if compact_sp is not None:
                agent_kwargs: dict[str, Any] = dict(
                    llm=llm, tools=self.tools, include_default_tools=_include,
                    system_prompt=compact_sp,
                )
            else:
                agent_kwargs = dict(
                    llm=llm, tools=self.tools, include_default_tools=_include,
                    security_policy_filename="",
                    system_prompt_kwargs={"llm_security_analyzer": False},
                )
            # M149.14：上下文压缩钳住总窗口（M149.13 多轮破窗根因修复）
            condenser = self._build_condenser(llm_api_key)
            if condenser is not None:
                agent_kwargs["condenser"] = condenser
            # M7.3 — 仅在有启用的 MCP 服务器时注入，保持默认执行路径不变
            if self.mcp_config:
                agent_kwargs["mcp_config"] = self.mcp_config
            agent = Agent(**agent_kwargs)
            workspace = RemoteWorkspace(host=self.agent_host, working_dir=self.working_dir, api_key=self.api_key)
            with workspace:
                _session_start = time.monotonic()
                conversation = RemoteConversation(
                    agent=agent,
                    workspace=workspace,
                    callbacks=[self._on_event],
                    max_iteration_per_run=self.max_iterations,
                    delete_on_close=True,
                )
                self._emit(EventType.status, Role.system,
                           {"status": "running", "progress": 10, "note": "派发任务到沙盒"})
                # M156.13：把 task_description 里的宿主机路径翻译成容器内路径。
                # planner/fail-open 构造的描述含 state.cwd（宿主机路径如
                # /Users/wangzhenyu/projects/X），但 OpenHands 容器只看到 /projects/X。
                # 不翻译 → Kimi 按 host 路径 mkdir → Permission denied → 浪费迭代。
                task_description = self._translate_paths_in_text(task_description)
                conversation.send_message(task_description, sender="flipped-supervisor")
                conversation.run(blocking=True, poll_interval=1.0, timeout=self.timeout)
                violations = audit_openhands_events(self._events)
                if violations:
                    raise RuntimeError(violations[0])

                final_state = conversation.state
                status = getattr(final_state, "execution_status", None)
                status_done = status == ConversationExecutionStatus.FINISHED
                # M150 修复：记录 OpenHands 会话总耗时，汇入 metrics 延迟统计。
                # conversation 无 per-LLM 时间戳，用整体会话耗时近似（含多轮 LLM+工具）。
                _session_latency = time.monotonic() - _session_start
                # F10 补全:Worker(Kimi)沙盒会话的 token 用量汇入全局统计(尽力而为)
                try:
                    p, c, n = _sum_conversation_usage(final_state)
                    if p or c:
                        COLLECTOR.record_usage(prompt_tokens=p, completion_tokens=c, calls=n,
                                               latency=_session_latency)
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
