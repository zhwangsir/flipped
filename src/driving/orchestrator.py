"""驾驭层 · 多 Agent 监督编排（D15 / M3.6）。

Supervisor(GLM 调度) + Worker(Kimi via cline 执行) + Overseer(GLM 专属监督效率/方向)。
- **Supervisor**：把目标拆成"下一步子任务"（干净结构化任务，**不传全量历史**，避免上下文污染），或判定相信已完成。
- **Worker**：cline headless 执行该子任务，产出可观测轨迹 + 动作签名（复用 observe / sidecar.action_signature）。
- **Overseer**：分层监督——先**确定性预检**(复用动作签名: 同动作重复=低效/卡死)，再 **GLM 方向判断**(产出结构化 verdict)，
  条件路由 continue / replan(回 supervisor) / abort。worker=Kimi、overseer=GLM **跨模型族**避免自偏(D15)。
- **末端强制验证**(复用 sidecar 思路: 跑验收命令判定 done)。checkpointer 支持崩溃恢复/审批中断。

所有 LLM/worker 节点可注入 → 单测确定性、无需真 LLM；默认实现用 GLM/Kimi 经 LiteLLM:4000。
"""
from __future__ import annotations

import os
import re
import uuid
from typing import Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from driving.approval import APPROVE_WORDS, classify_risk
from driving.observe import run_and_observe
from driving.sidecar import action_signature
from metrics import MetricsCallbackHandler
from driving.context_manager import CheckpointRetention, compress_history
from driving.model_router import resolve_model_config, resolve_worker_model_config
from driving.safety import is_safe_command

from executor.openhands_worker import OpenHandsWorker


class NullEventBus:
    """在 LangGraph 同步节点中运行 OpenHands Worker 时，不需要向 WebSocket 广播。"""

    def emit(self, *args, **kwargs):  # noqa: ARG002
        pass

    def set_status(self, *args, **kwargs):  # noqa: ARG002
        pass


def _openhands_signature(events: list) -> str:
    """把 OpenHands 动作事件序列转成 sidecar 循环检测可比的签名。"""
    parts: set[str] = set()
    for event in events:
        if type(event).__name__ != "ActionEvent":
            continue
        tool = getattr(event, "tool_name", None) or "unknown"
        action = getattr(event, "action", None)
        target = ""
        if action is not None:
            for attr in ("path", "command", "file", "url"):
                val = getattr(action, attr, None)
                if val:
                    target = str(val)
                    break
            if not target:
                target = getattr(action, "_summary", "") or action.__class__.__name__
        parts.add(f"{tool}:{target[:80]}")
    return "|".join(sorted(parts))

DEFAULT_LOOP_THRESHOLD = 3


class OrchestratorState(TypedDict, total=False):
    goal: str
    cwd: str
    verify_cmd: list[str]
    project_rules: str
    repo_map: str
    data_dir: str
    max_iterations: int
    loop_threshold: int
    iteration: int
    current_subtask: str
    believe_done: bool
    require_approval: bool
    approval_decision: str   # approved / rejected / auto
    worker_error: bool       # 执行器(cline)报错/上游模型不可用 → 快速失败
    # M90 自动交替接力:worker_error 时切换备用模型重试一次,对齐用户核心理念
    # "如果卡死了就让另外一个模型接力并释放上一个模型的内容开始监督"
    relay_attempted: bool    # 本轮迭代是否已接力过(防无限接力,一次性标志)
    worker_alias: str        # 当前 worker 模型别名(coder/architect),默认 coder
    signatures: list[str]
    last_obs: dict
    verdict: dict          # overseer 最近裁决
    feedback: str          # 回灌给 supervisor 的(验收失败/overseer 问题)
    verified: bool
    done: bool
    stop_reason: str       # verified / overseer_abort / loop_detected / circuit_breaker / worker_error / relay_exhausted
    history: list[dict]
    context_summary: dict | None
    max_context_tokens: int
    keep_recent: int


# 可注入节点：(state) -> state 增量
SupervisorFn = Callable[[OrchestratorState], dict]
WorkerFn = Callable[[OrchestratorState], dict]
OverseerFn = Callable[[OrchestratorState], dict]
VerifierFn = Callable[[list, str], "tuple[bool, str]"]


# 默认实现（GLM/Kimi 经 LiteLLM） ----------

def _make_llm(alias: str, temperature: float = 0, callbacks=None):
    """构建 ChatOpenAI（alias=architect/coder）。

    运行时根据 `model_router.resolve_model_config` 自动选择 LiteLLM proxy 或直连 exo。

    关键修复：langchain_openai 的 httpx 会自动走系统代理(macOS System Preferences)，
    导致对内网模型端点(100.64.x.x)的请求被代理 502。这里显式传 http_client 绕过。

    M131 质量优先配置（用户要求：不追求速度，不限制 max_tokens 和超时，只追求质量和完整）：
    - timeout 提到 1800s（30 分钟），不人为限制模型推理时间
    - max_tokens 不传（让模型自然完成，不人为截断）
    - reasoning 开启（enable_thinking=true，深度推理）
    - Kimi 做 overseer 监督监控，防 GLM-5.2 卡死
    """
    from langchain_openai import ChatOpenAI
    import httpx

    base, model = resolve_model_config(alias)
    key = os.environ.get("LITELLM_MASTER_KEY") or os.environ.get("EXO_API_KEY", "dummy")
    # 构造不走代理的 httpx client（内网模型端点必须直连）
    # trust_env=False 让 httpx 忽略系统代理配置(macOS System Preferences / env vars)
    # M131: 质量优先，不限制超时。1800s（30分钟）只作为极端兜底防无限挂起。
    _glm_timeout = float(os.environ.get("FLIPPED_GLM_TIMEOUT", "1800"))
    http_client = httpx.Client(
        timeout=httpx.Timeout(_glm_timeout, connect=10.0),
        trust_env=False,
    )
    return ChatOpenAI(
        model=model, base_url=base, api_key=key, temperature=temperature, timeout=_glm_timeout,
        callbacks=callbacks, http_client=http_client,
        # 禁用 openai SDK 内部重试（默认 max_retries=2 → 3 次请求 × 240s = 720s）
        # langchain 对 GLM 总是解析失败，SDK 重试纯浪费时间；失败立即走 _direct_glm_tool_call
        max_retries=0,
        # M131 质量优先：不传 max_tokens，让模型自然完成
        # enable_thinking 由 _direct_glm_tool_call 内部控制（reasoning_content 独立字段）
    )


def _parse_raw_response(raw, schema_cls):
    """从原始 AIMessage 中尽力解析出结构化对象（应对 GLM function calling 偶发异常）。

    GLM-5.2 经 exo 的 function calling 有三类已知故障：
    1. tool_calls 返回但 arguments 是空串/畸形 JSON
    2. 把结构化数据当成纯文本塞进 content（不带 tool_calls）
    3. list[str] 字段被返回为裸字符串或逗号分隔串

    这里逐层兜底：tool_calls → content JSON → content 键值对 → 字段级强转。
    """
    import json
    import re

    # 1) 优先从 tool_calls 参数里取
    tool_calls = getattr(raw, "tool_calls", None) or []
    for tc in tool_calls:
        if isinstance(tc, dict):
            args = tc.get("function", {}).get("arguments")
            if args is None:
                args = tc.get("args")
        else:
            args = getattr(getattr(tc, "function", None), "arguments", None)
            if args is None:
                args = getattr(tc, "args", None)
        if args:
            try:
                data = json.loads(args) if isinstance(args, str) else dict(args)
                return _coerce_schema(data, schema_cls)
            except Exception:
                pass

    # 2) 从 content 里抠 JSON / 键值对
    text = ""
    content = getattr(raw, "content", None)
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "".join(str(c) for c in content)

    # 2a) JSON object / markdown code block（贪婪匹配，应对嵌套花括号）
    candidates = re.findall(r"\{[\s\S]*\}", text)
    # 2a-bis) 退化容错：GLM-5.2-fp8 长输出偶发量化退化，尾部出乱码（\0 / "0.0 0.0" / "0.0.0"）。
    # 贪婪正则会把乱码里的 } 也吃掉导致 json.loads 失败。逐个尝试时，若失败则截断到最后一个
    # 看起来合法的 } 再试。这让退化输出也能被抢救出前面的有效 JSON。
    if candidates:
        repaired = []
        for cand in candidates:
            repaired.append(cand)
            # 截断到最后一个非乱码 } —— 找最后一个后面只跟空白/```/换行的 }
            for i in range(len(cand) - 1, -1, -1):
                if cand[i] == "}":
                    tail = cand[i + 1:].strip().strip("`").strip()
                    # 合法 } 后面应该是空或只有 ``` markdown 标记
                    if not tail or tail.startswith("```") or tail == "```":
                        repaired.append(cand[: i + 1])
                        break
        candidates = repaired
    if not candidates:
        # 2b) 键值对：efficiency: 0.8
        pairs = re.findall(r"(\w+)\s*[:=]\s*([^\n,]+)", text)
        if pairs:
            data = {}
            for k, v in pairs:
                v = v.strip().strip('"\'')
                if k in ("efficiency", "direction", "believe_done"):
                    try:
                        v = float(v) if k != "believe_done" else v.lower() in ("true", "1", "yes")
                    except ValueError:
                        continue
                data[k] = v
            return _coerce_schema(data, schema_cls)
    for cand in candidates:
        try:
            return _coerce_schema(json.loads(cand), schema_cls)
        except Exception:
            continue
    return None


def _coerce_schema(data: dict, schema_cls):
    """把半结构化 dict 强转成 Pydantic schema，对 list[str] / bool 等字段做类型修复。

    GLM 偶发把 list[str] 字段返回为裸字符串或逗号分隔串；bool 返回为 "true"/"false" 字符串。
    """
    if not isinstance(data, dict):
        return None
    # 拿 schema 的字段类型信息做轻量强转
    hints = getattr(schema_cls, "model_fields", {})
    coerced = dict(data)
    for fname, finfo in hints.items():
        if fname not in coerced:
            continue
        val = coerced[fname]
        ftype = finfo.annotation if hasattr(finfo, "annotation") else None
        # list[str] 字段：None → []；裸字符串交给 schema 的 field_validator 处理
        # （不在这里拆分字符串，因为有些 schema 有自定义 validator 把字符串包成 list）
        if ftype is list[str] or (hasattr(ftype, "__origin__") and ftype.__origin__ is list):
            if val is None:
                coerced[fname] = []
        # bool 字段：字符串 "true"/"false" → 真 bool
        elif ftype is bool:
            if isinstance(val, str):
                coerced[fname] = val.strip().lower() in ("true", "1", "yes")
            elif isinstance(val, (int, float)):
                coerced[fname] = bool(val)
        # str 字段：int/float → str（GLM 偶发把字符串答案返回为数字）
        elif ftype is str and not isinstance(val, str):
            coerced[fname] = str(val)
    return schema_cls.model_validate(coerced)


def _invoke_structured(llm, schema_cls, prompt: str, *, max_retries: int = 0):
    """带重试 + 原始响应兜底的结构化输出调用。

    GLM-5.2 经 exo 的 function calling 有已知兼容问题：
    1. langchain_openai 无法解析 GLM 的 tool_calls（function 对象多了 id 字段）→ parsed=None
    2. with_structured_output 内部创建的 openai client 绕过我们传的 http_client(trust_env=False)
       → 走系统代理卡住（macOS System Preferences 的 http_proxy）

    解法：默认直接调 _direct_glm_tool_call（裸 httpx + trust_env=False，绕过 langchain）。
    设 FLIPPED_USE_LANGCHAIN=1 可启用 langchain 路径（调试/对比用）。
    """
    import os
    import sys

    # 默认 fast path：直接走 _direct_glm_tool_call，绕过 langchain
    if os.environ.get("FLIPPED_USE_LANGCHAIN") != "1":
        parsed = None
        err: Exception | None = None
        try:
            parsed = _direct_glm_tool_call(llm, schema_cls, prompt)
        except Exception as e2:  # noqa: BLE001
            print(f"[invoke_structured] _direct_glm_tool_call 抛异常: "
                  f"{type(e2).__name__}: {e2}", file=sys.stderr)
            err = e2
        if parsed is not None:
            return parsed
        raise RuntimeError(
            f"structured output failed: direct_glm_fallback="
            f"{'returned None (GLM 空响应)' if err is None else f'{type(err).__name__}: {err}'}"
        )

    # langchain 路径（仅 FLIPPED_USE_LANGCHAIN=1 时走，调试用）
    import time as _time

    structured = llm.with_structured_output(schema_cls, method="function_calling", include_raw=True)
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = structured.invoke(prompt)
            parsed = resp.get("parsed") if isinstance(resp, dict) else getattr(resp, "parsed", None)
            if parsed is not None:
                return parsed
            raw = resp.get("raw") if isinstance(resp, dict) else getattr(resp, "raw", None)
            if raw is not None:
                parsed = _parse_raw_response(raw, schema_cls)
                if parsed is not None:
                    return parsed
            raise ValueError("langchain structured output returned parsed=None")
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < max_retries:
                _time.sleep(0.5 * (attempt + 1))

    # langchain 失败 → 直调 GLM fallback
    try:
        parsed = _direct_glm_tool_call(llm, schema_cls, prompt)
        if parsed is not None:
            return parsed
    except Exception as e2:  # noqa: BLE001
        print(f"[invoke_structured] _direct_glm_tool_call 抛异常: "
              f"{type(e2).__name__}: {e2}", file=sys.stderr)
    raise last_err or RuntimeError("structured output failed after retries")


def _direct_glm_tool_call(llm, schema_cls, prompt: str, *, max_retries: int = 1):
    """直调 GLM /v1/chat/completions，纯文本模式输出 JSON，自己解析。

    绕过 langchain + 绕过 function calling，直接用纯文本模式让 GLM 输出 JSON。

    **M131 质量优先配置**（用户要求：不追求速度，不限制 max_tokens 和超时，只追求质量和完整）：
    - enable_thinking=True：开启深度推理，reasoning_content 是独立字段不占 content 预算
    - max_tokens 不传：让模型自然完成，不人为截断
    - timeout=1800s：30分钟极端兜底，防无限挂起
    - Kimi overseer 在外层监控，防 GLM-5.2 真卡死

    **为什么不用 function calling**：
    1. langchain_openai 对 GLM/exo 的 tool_calls 格式解析有 bug（function 对象多了 id 字段）
    2. GLM-5.2 reasoning 模式下 tool_calls 可能不为空，但格式不稳定

    prompt 末尾追加 schema 的 JSON 格式说明，GLM 在 content 里输出 JSON，
    用 _parse_raw_response 解析。
    """
    import json
    import sys
    import time as _time
    import httpx

    base_url = getattr(llm, "openai_api_base", "") or getattr(llm, "base_url", "")
    model = getattr(llm, "model_name", "") or getattr(llm, "model", "")
    # M89 Bug #13b: langchain ChatOpenAI 在 Pydantic v2 下 openai_api_key 是 private/property,
    # getattr 读不到真实值返回 ""，fallback 到 "dummy" 被 LiteLLM 鉴权层 400 拒绝。
    # 修复：优先从环境变量读（与 _make_llm 一致），llm 对象只作为最后兜底。
    api_key = (os.environ.get("LITELLM_MASTER_KEY")
               or os.environ.get("EXO_API_KEY")
               or getattr(llm, "openai_api_key", "")
               or "dummy")
    # M131 质量优先：默认 1800s（30分钟），不人为限制模型推理时间
    _glm_timeout = float(os.environ.get("FLIPPED_GLM_TIMEOUT", "1800"))

    schema_json = schema_cls.model_json_schema()
    # 在 prompt 末尾追加 schema 说明，让 GLM 输出 JSON
    full_prompt = (
        f"{prompt}\n\n"
        f"请输出 JSON，符合以下 JSON Schema（只输出 JSON，不要其他内容）：\n"
        f"{json.dumps(schema_json, ensure_ascii=False, indent=2)}"
    )

    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            req_body = {
                "model": model,
                "messages": [{"role": "user", "content": full_prompt}],
                # M131 质量优先：开启深度推理，reasoning_content 独立字段不占 content 预算
                "enable_thinking": True,
                "temperature": 0.1,
            }
            # 不传 max_tokens：让模型自然完成，不人为截断
            # 若环境变量显式设置了则用环境变量值（调试用）
            _env_max_tokens = os.environ.get("FLIPPED_GLM_MAX_TOKENS")
            if _env_max_tokens:
                req_body["max_tokens"] = int(_env_max_tokens)
            r = httpx.post(
                f"{str(base_url).rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=req_body,
                timeout=httpx.Timeout(_glm_timeout, connect=10.0),
                trust_env=False,
            )
            r.raise_for_status()
            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message", {}) or {}
            content = msg.get("content", "") or ""
            if content:
                parsed = _parse_raw_response(
                    type("R", (), {"content": content, "tool_calls": []})(), schema_cls)
                if parsed is not None:
                    return parsed
            # 空响应（GLM 回了内容但 _parse_raw_response 解析失败）
            finish_reason = choice.get("finish_reason", "")
            print(f"[glm_fallback] attempt {attempt + 1}/{max_retries} 空响应: "
                  f"finish_reason={finish_reason} content_len={len(content)}", file=sys.stderr)
            # 调试：打印 content 头尾各 300 字符，看 GLM 实际输出格式
            if content:
                print(f"[glm_fallback] content 头 300: {content[:300]!r}", file=sys.stderr)
                print(f"[glm_fallback] content 尾 300: {content[-300:]!r}", file=sys.stderr)
            last_err = RuntimeError(f"GLM 空响应 finish_reason={finish_reason}")
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[glm_fallback] attempt {attempt + 1}/{max_retries} 异常: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
        if attempt < max_retries - 1:
            _time.sleep(0.5 * (attempt + 1))
    if last_err:
        print(f"[glm_fallback] 全部 {max_retries} 次重试失败: {last_err}", file=sys.stderr)
    return None


def _build_supervisor_prompt(state: OrchestratorState) -> str:
    """构建 supervisor 拆解 prompt(含项目规则/反馈/历史摘要)。抽出便于单测。"""
    fb = state.get("feedback", "")
    summary_note = ""
    ctx_summary = state.get("context_summary")
    if ctx_summary:
        summary_note = f"\n历史摘要：{ctx_summary.get('digest', '')}"
    rules = state.get("project_rules", "")
    rules_note = f"\n项目规则(务必遵守项目约定)：\n{rules}\n" if rules else ""
    repo = state.get("repo_map", "")
    repo_note = f"\n项目结构(据此把代码放对位置、别重造已有模块)：\n{repo}\n" if repo else ""
    # 验收失败时，把错误输出注入反馈，并明确禁止“推倒重来”
    fb_prefix = ""
    if fb:
        if "验收命令退出非0" in fb or "监督意见" in fb:
            fb_prefix = (
                "反馈(上一轮失败/监督意见，必须据此做**最小精确修复**，\n"
                "严禁删除已写好的文件或重新创建整个项目；只允许改具体错误行/补缺失文件)：\n"
            )
        else:
            fb_prefix = "反馈(上一轮验收失败/监督意见，必须据此调整)："
    return (f"目标：{state['goal']}\n工作目录：{state['cwd']}\n{repo_note}{rules_note}"
            f"{fb_prefix}{fb if fb else '这是首轮。'}{summary_note}\n"
            "你是架构调度者。给出执行者下一步要做的【一个】自包含子任务；"
            "若相信目标已达成则 believe_done=true。"
            "subtask 描述必须简洁（≤200字），只说做什么、不改什么文件，"
            "不要重复设计约束（执行者已有 project_rules）。")


def default_supervisor(state: OrchestratorState) -> dict:
    """GLM 调度：据目标 + 项目规则 + 反馈，给出下一步子任务（干净结构化），或相信已完成。"""
    from pydantic import BaseModel, Field

    class Plan(BaseModel):
        believe_done: bool = Field(description="是否相信目标已达成(将由强制验证核对)")
        subtask: str = Field(description="给执行者(coder)的下一步具体子任务，自包含、含必要上下文，勿引用历史")
        rationale: str = Field(description="一句话理由")

    msg = _build_supervisor_prompt(state)
    try:
        # method="function_calling"：GLM/exo 不支持 json_schema(langchain 默认)，但支持工具调用(M0.4)
        plan = _invoke_structured(_make_llm("architect", callbacks=[MetricsCallbackHandler()]), Plan, msg)
        sub, done, why = plan.subtask, plan.believe_done, plan.rationale
    except Exception as e:  # noqa: BLE001 失败兜底：直接把目标当子任务
        sub, done, why = state["goal"], False, f"(supervisor LLM 失败兜底: {e})"
    hist = state.get("history", []) + [{"step": "supervisor", "subtask": sub, "believe_done": done, "why": why}]
    return {"current_subtask": sub, "believe_done": done, "history": hist}


def cline_worker(state: OrchestratorState) -> dict:
    """Kimi via cline 执行当前子任务（干净上下文：只给子任务字符串）。"""
    obs = run_and_observe(state["current_subtask"], state["cwd"],
                          model="coder", data_dir=state.get("data_dir"))
    sig = action_signature(obs.get("records") or [])
    sigs = state.get("signatures", []) + [sig]
    summ = obs.get("summary") or {}
    # cline 退出非0 且一个工具都没调 = 执行器报错(常为上游模型不可用/429) → 快速失败, 别空转熔断
    werr = (not obs.get("ok")) and summ.get("tool_calls", 0) == 0
    hist = state.get("history", []) + [{"step": "worker", "summary": summ, "signature": sig, "error": werr}]
    return {"last_obs": obs, "signatures": sigs, "history": hist, "worker_error": werr}


def make_openhands_worker(bus=None, session_id: str | None = None) -> WorkerFn:
    """构建 OpenHands worker 节点(Kimi via SDK 在 Docker 沙盒执行子任务)。

    Supervisor(GLM) 拆子任务 -> 本 Worker(Kimi) -> Overseer(GLM) 监督;Worker 经
    `model_router` 动态选 LiteLLM proxy 或直连 exo。

    - bus/session_id 给定 → worker 沙盒轨迹事件推到**真实会话**(F2 全程可见);
    - 省略 → NullEventBus(默认,兼容直连编排/测试,不污染会话流)。
    """

    def node(state: OrchestratorState) -> dict:
        sid = session_id or f"orch-{uuid.uuid4().hex[:8]}"
        task_id = f"subtask-{uuid.uuid4().hex[:8]}"
        event_bus = bus if bus is not None else NullEventBus()
        worker_base_url, worker_model_alias = resolve_worker_model_config(state.get("worker_alias", "coder"))
        worker = OpenHandsWorker(
            session_id=sid,
            task_id=task_id,
            bus=event_bus,
            agent_host=os.environ.get("OPENHANDS_AGENT_HOST", "http://localhost:8000"),
            working_dir=state["cwd"],
            model_alias=worker_model_alias,
            base_url=worker_base_url,
            # 子任务模式:不碰会话状态(F8 实测缺陷——曾提前把外层循环的会话覆盖成 done)
            manage_session_status=False,
        )
        try:
            summary = worker.run(state["current_subtask"])
        except Exception as e:  # noqa: BLE001
            err_text = str(e)
            tool_calls = sum(1 for ev in worker.events if type(ev).__name__ == "ActionEvent")
            # F8 大任务实测缺陷:MaxIterationsReached(子任务卡死在调试循环)/安全审计拦截
            # 是**任务性失败**——应回灌 supervisor 换更小方案重拆,而非当基础设施故障判死。
            # 真正的基础设施故障(连不上/模型不可用)特征是一个工具都没调成。
            task_level = ("MaxIterationsReached" in err_text or "blocked" in err_text
                          or tool_calls > 0)
            if task_level:
                return {
                    "last_obs": {"ok": False, "summary": {"tool_calls": tool_calls}, "error": err_text},
                    "signatures": state.get("signatures", []) + [f"stuck:{type(e).__name__}"],
                    "history": state.get("history", []) + [
                        {"step": "worker", "summary": {"tool_calls": tool_calls}, "stuck": True}],
                    "worker_error": False,
                    "feedback": (state.get("feedback", "")
                                 + f"\n[执行器未完成子任务({err_text[:180]})。"
                                   "请拆一个更小、更简单、避开上次卡点的子任务。]").strip(),
                }
            err_sig = f"error:{type(e).__name__}"
            return {
                "last_obs": {"ok": False, "summary": {"tool_calls": 0}, "error": err_text},
                "signatures": state.get("signatures", []) + [err_sig],
                "history": state.get("history", []) + [{"step": "worker", "summary": {"tool_calls": 0}, "error": True}],
                "worker_error": True,
            }

        sig = _openhands_signature(worker.events)
        tool_calls = sum(1 for e in worker.events if type(e).__name__ == "ActionEvent")
        ok = summary.get("status") == "done"
        werr = (not ok) and tool_calls == 0
        hist = state.get("history", []) + [
            {"step": "worker", "summary": {"tool_calls": tool_calls, **summary}, "signature": sig, "error": werr}
        ]
        return {
            "last_obs": {"ok": ok, "summary": {"tool_calls": tool_calls, **summary}},
            "signatures": state.get("signatures", []) + [sig],
            "history": hist,
            "worker_error": werr,
        }

    return node


# 默认 worker 节点(NullEventBus,不推事件)。F2 的可见 worker 由 make_openhands_worker(bus, sid) 构建。
openhands_worker = make_openhands_worker()


# ---------- LocalWorker（绕过 Docker/OpenHands，直接用 Kimi 写文件） ----------

def _needs_continuation(content: str, finish: str) -> bool:
    """检测 worker 输出是否被 max_tokens 截断需要续生成。

    E2E 暴露的问题（M14.4）：worker 生成 HTML 到 max_tokens 上限被截断
    （finish=length），代码块没有闭合的 ```，导致文件不完整 → verify 失败。

    需要续生成的条件：
    1. finish == "length"（到达 max_tokens 上限）
    2. 且 content 含未闭合的代码块（``` 数量为奇数）

    不需要续生成的情况：
    - finish != "length"（正常结束或 overflow retry 处理）
    - finish=length 但代码块已闭合（偶数 ```，可能是正常长输出）
    - content 为空（overflow retry 会处理）
    - 无代码块标记（回退解析会处理）
    """
    if finish != "length" or not content:
        return False
    # 数 ``` 的数量，奇数说明有未闭合的代码块
    return content.count("```") % 2 == 1


def _extract_hex_map(project_rules: str) -> dict[str, str]:
    """从 project_rules（compact design brief）提取 CSS 变量名→精确 hex 值映射。

    M15.1：E2E 暴露 worker(Kimi) 不遵守 compact brief 的 hex 约束，
    把 #0D0D12 替换成 #0b0f19，#F5F5F5 替换成 #f8fafc。
    post-generation hex auto-fix 需要从 project_rules 提取正确 hex 映射，
    在写文件后自动修正错误值。

    compact brief 格式：
        【强制】必须用这些精确 hex 值，禁止替换: --color-accent: #0A84FF; --color-bg: #0D0D12; ...
    """
    hex_map: dict[str, str] = {}
    # 匹配 --color-xxx: #HEX 格式
    for m in re.finditer(r"(--color-[\w-]+)\s*:\s*(#[0-9A-Fa-f]{3,8})", project_rules):
        var_name = m.group(1)
        hex_val = m.group(2)
        # 只在【强制】hex 值约束区域提取（避免误匹配其他上下文）
        hex_map[var_name] = hex_val
    return hex_map


def _auto_fix_hex_in_dir(cwd: str, hex_map: dict[str, str]) -> bool:
    """扫描 cwd 下 HTML/CSS 文件，自动修正 CSS 变量定义中的错误 hex 值。

    M15.1：worker(Kimi) 经常不遵守 compact brief 的 hex 约束，
    用自选颜色（如 #0b0f19）替换设计系统指定的精确 hex 值（如 #0D0D12）。
    此函数在文件写入后扫描 `--color-*: #hex` 模式，
    如果变量名匹配但 hex 值不匹配，直接替换为正确的 hex 值。

    不依赖模型遵守约束，在代码层面强制修正（类似 linter auto-fix）。
    """
    if not hex_map:
        return False
    fixed_any = False
    for fname in os.listdir(cwd):
        if not fname.endswith((".html", ".css")):
            continue
        fpath = os.path.join(cwd, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        changed = False
        for var_name, correct_hex in hex_map.items():
            # 匹配 --color-xxx: #wrong_hex（变量名匹配但 hex 值不匹配）
            pattern = re.compile(
                r"(" + re.escape(var_name) + r"\s*:\s*)(#[0-9A-Fa-f]{3,8})"
            )
            for m in pattern.finditer(content):
                actual_hex = m.group(2)
                if actual_hex.upper() != correct_hex.upper():
                    content = content[:m.start(2)] + correct_hex + content[m.end(2):]
                    changed = True
        if changed:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
            fixed_any = True
            import sys as _sys
            print(f"[local_worker] hex_auto_fix: {fname} 修正了 CSS 变量 hex 值", file=_sys.stderr, flush=True)
    return fixed_any


def _read_file_context(cwd: str) -> str:
    """读取 cwd 下已有 index.html，返回简洁结构摘要。

    M51: 让 worker 知道已有文件内容，避免每次从零生成。
    无限迭代中每个任务应在前一个任务的成果上构建，而非替换。
    只提取关键结构信息（CSS 变量名 + 标签计数），控制 prompt 长度。
    """
    import os
    import re

    html_path = os.path.join(cwd, "index.html")
    if not os.path.isfile(html_path):
        return ""
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return ""
    if not content.strip() or len(content) < 50:
        return ""

    # 提取 CSS 变量名（不含值，控制长度）
    css_vars = re.findall(r'(--[\w-]+)\s*:', content)
    # 提取主要 HTML 标签
    tags = re.findall(r'<(header|main|section|footer|nav|article|h[1-6]|button|a|form|input|@media)\b', content)

    parts = []
    if css_vars:
        unique_vars = sorted(set(css_vars))[:6]
        parts.append(f"CSS变量: {','.join(unique_vars)}")
    if tags:
        from collections import Counter
        tc = Counter(tags)
        parts.append(f"标签: {','.join(f'{t}×{c}' for t, c in tc.most_common(8))}")

    if not parts:
        return ""

    return f"现有 index.html 已有[{'; '.join(parts)}]。在其基础上扩展，保留已有结构，只添加新内容。"


def _check_design_regression(cwd: str, old_content: str) -> bool:
    """检测 design_score 是否回归（新版本比旧版本差）。

    M52: 防止 worker 生成的低质量代码覆盖已有的高质量代码。
    如果新版本 design_score 低于旧版本，返回 True（检测到回归）。
    无旧版本或异常时 fail-open 返回 False。
    """
    if not old_content or len(old_content) < 50:
        return False

    try:
        from driving.design_context import design_score
        import tempfile
        import os as _os

        # 新版本分数（cwd 磁盘上的）
        new_score, _ = design_score(cwd)

        # 旧版本分数：写到临时目录计算
        with tempfile.TemporaryDirectory() as td:
            with open(_os.path.join(td, "index.html"), "w") as f:
                f.write(old_content)
            old_score, _ = design_score(td)

        return new_score < old_score
    except Exception:
        return False


def local_worker(state: OrchestratorState) -> dict:
    """本地 worker：直接调 Kimi 生成代码并写文件到 cwd，无需 Docker/沙箱。

    适用场景：简单 UI 任务（landing page / 组件 / 静态页面）。
    优势：无 Docker 依赖、无 polling 超时、verify_cmd 直接在宿主机跑。
    劣势：无沙箱隔离，仅用于可信任务。

    协议：让 Kimi 用 ```language:path/to/file 格式的代码块输出文件，
    worker 解析后写到 cwd 下对应路径。
    """
    import os
    import re
    import httpx

    cwd = state.get("cwd", ".")
    subtask = state.get("current_subtask", state.get("goal", ""))
    project_rules = state.get("project_rules", "")
    feedback = state.get("feedback", "")

    base_url, model = resolve_worker_model_config(state.get("worker_alias", "coder"))
    api_key = os.environ.get("EXO_API_KEY") or os.environ.get("LITELLM_MASTER_KEY", "dummy")

    # M11.1：截断 project_rules 和 feedback，防止 prompt 过长触发 reasoning 循环。
    # E2E 实测：prompt > 1400 字符时 Kimi reasoning_tokens 占满 max_tokens，content ≈ 0。
    # project_rules 限制 300 字符，feedback 限制 80 字符，subtask 限制 500 字符。
    _subtask_short = subtask[:500] if subtask else ""
    _rules_short = project_rules[-300:] if project_rules and len(project_rules) > 300 else (project_rules or "")
    _feedback_short = feedback[:80] if feedback else ""

    # M51: 读取已有文件结构，让 worker 在其基础上扩展而非从零生成。
    _file_ctx = _read_file_context(cwd)

    # M52: 保存旧 index.html 内容用于 design_score 回归检测。
    _old_html = ""
    _old_path = os.path.join(cwd, "index.html")
    if os.path.isfile(_old_path):
        try:
            with open(_old_path, "r", encoding="utf-8") as f:
                _old_html = f.read()
        except Exception:
            pass

    # M103: 增量修复模式 — verify 失败后基于现有产物精准修复而非重写
    _incremental_mode = False
    _iteration = state.get("iteration", 0)
    _has_artifacts = bool(_old_html) or os.path.isfile(os.path.join(cwd, "index.html"))
    try:
        from driving.incremental_mode import (
            IncrementalContext,
            build_incremental_prompt,
            should_use_incremental,
        )
        _incremental_mode = should_use_incremental(_iteration, _has_artifacts)
    except Exception:
        _incremental_mode = False

    if _incremental_mode:
        try:
            _failure_output = state.get("feedback", "")[-500:] if state.get("feedback") else ""
            _ctx = IncrementalContext(
                cwd=cwd,
                failure_output=_failure_output,
                round_num=_iteration,
                rca_cause=state.get("rca_cause", ""),
                rca_suggestion=state.get("rca_suggestion", ""),
            )
            prompt = build_incremental_prompt(_ctx, _subtask_short)
        except Exception:
            _incremental_mode = False
            prompt = (
                f"在 `{cwd}` 下完成：\n{_subtask_short}\n\n"
                + (f"{_file_ctx}\n" if _file_ctx else "")
                + (f"约束：{_rules_short}\n" if _rules_short else "")
                + (f"反馈：{_feedback_short}\n" if _feedback_short else "")
                + "用 ```html:index.html 格式输出完整代码，末尾 ```。只输出代码块。\n"
            )
    else:
        prompt = (
            f"在 `{cwd}` 下完成：\n{_subtask_short}\n\n"
            + (f"{_file_ctx}\n" if _file_ctx else "")
            + (f"约束：{_rules_short}\n" if _rules_short else "")
            + (f"反馈：{_feedback_short}\n" if _feedback_short else "")
            + "用 ```html:index.html 格式输出完整代码，末尾 ```。只输出代码块。\n"
        )

    # M10.5 根因修复：Kimi-K2.7-Code 在 exo 上即使传 enable_thinking=false，
    # 仍会交错生成 reasoning_content（reasoning_tokens 占 max_tokens 的 60-90%）。
    # 在 non-streaming 模式下，reasoning 先生成用光 max_tokens，content 几乎为空（len=2）。
    # 解法：改用 streaming 模式，只收集 content deltas，忽略 reasoning_content deltas。
    # 实测 streaming 能拿到完整 content（2899 bytes），non-streaming 只有 2 bytes。
    import json as _json
    import time as _time
    _kimi_timeout = float(os.environ.get("FLIPPED_KIMI_TIMEOUT", "300"))
    _content_parts: list[str] = []
    finish = ""
    t0 = _time.monotonic()
    try:
        with httpx.stream(
            "POST",
            f"{str(base_url).rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 4096,
                "temperature": 0.1,
                "enable_thinking": False,
                "chat_template_kwargs": {"enable_thinking": False},
                "stream": True,
            },
            timeout=httpx.Timeout(_kimi_timeout, connect=10.0),
            trust_env=False,
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    d = _json.loads(payload)
                except Exception:
                    continue
                choices = d.get("choices") or []
                if not choices:
                    continue
                ch = choices[0]
                delta = ch.get("delta", {})
                # 只收集 content，忽略 reasoning_content——reasoning 是 Kimi 的内部思考
                if delta.get("content"):
                    _content_parts.append(delta["content"])
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
        content = "".join(_content_parts)
        import sys as _sys
        print(f"[local_worker] finish={finish} content_len={len(content)} time={_time.monotonic()-t0:.1f}s", file=_sys.stderr, flush=True)

        # M11.1：reasoning overflow 检测 + 最小 prompt 重试。
        # 累积上下文/delegate feedback 过长时，Kimi 仍会把 tokens 全用在 reasoning 上，
        # content_len < 50 说明几乎没产出内容。用最小 prompt（只含任务描述）重试一次。
        # M14.4：finish=length 且有未闭合代码块时跳过 overflow_retry——那是正常截断，
        # 应走 continuation 续生成；overflow_retry 会替换 content 丢失文件块开头。
        if len(content) < 50 and not _needs_continuation(content, finish):
            _minimal_prompt = (
                f"在 `{cwd}` 下完成以下任务，只输出代码块：\n{subtask[:300]}\n"
                "用 ```html:index.html 格式输出完整 HTML，末尾 ```。"
            )
            _retry_parts: list[str] = []
            _t1 = _time.monotonic()
            try:
                with httpx.stream(
                    "POST",
                    f"{str(base_url).rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": _minimal_prompt}],
                        "max_tokens": 4096,
                        "temperature": 0.1,
                        "enable_thinking": False,
                        "chat_template_kwargs": {"enable_thinking": False},
                        "stream": True,
                    },
                    timeout=httpx.Timeout(_kimi_timeout, connect=10.0),
                    trust_env=False,
                ) as r2:
                    r2.raise_for_status()
                    for line2 in r2.iter_lines():
                        if not line2 or not line2.startswith("data:"):
                            continue
                        payload2 = line2[5:].strip()
                        if payload2 == "[DONE]":
                            break
                        try:
                            d2 = _json.loads(payload2)
                        except Exception:
                            continue
                        choices2 = d2.get("choices") or []
                        if not choices2:
                            continue
                        delta2 = choices2[0].get("delta", {})
                        if delta2.get("content"):
                            _retry_parts.append(delta2["content"])
                content = "".join(_retry_parts)
                print(f"[local_worker] overflow_retry content_len={len(content)} time={_time.monotonic()-_t1:.1f}s", file=_sys.stderr, flush=True)
            except Exception as e2:  # noqa: BLE001
                print(f"[local_worker] overflow_retry failed: {type(e2).__name__}", file=_sys.stderr, flush=True)

        # M14.4: finish=length 输出截断自动续生成。
        # E2E 暴露：worker 生成 HTML 到 max_tokens 上限被截断（finish=length），
        # 代码块没有闭合的 ```，导致文件不完整 → verify 失败。
        # continuation 机制把已生成 content 的末尾作为上下文，让模型继续输出剩余部分。
        _max_continues = int(os.environ.get("FLIPPED_MAX_CONTINUATIONS", "2"))
        while _needs_continuation(content, finish) and _max_continues > 0:
            _cont_prompt = (
                f"以下是未完成的代码输出（被截断）。从中断处继续输出剩余部分，"
                f"不要重复已生成内容，直接输出剩余代码并闭合 ```：\n"
                f"...{content[-1500:]}"
            )
            _cont_parts: list[str] = []
            _cont_finish = ""
            try:
                with httpx.stream(
                    "POST",
                    f"{str(base_url).rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": _cont_prompt}],
                        "max_tokens": 4096,
                        "temperature": 0.1,
                        "enable_thinking": False,
                        "chat_template_kwargs": {"enable_thinking": False},
                        "stream": True,
                    },
                    timeout=httpx.Timeout(_kimi_timeout, connect=10.0),
                    trust_env=False,
                ) as rc:
                    rc.raise_for_status()
                    for line_c in rc.iter_lines():
                        if not line_c or not line_c.startswith("data:"):
                            continue
                        payload_c = line_c[5:].strip()
                        if payload_c == "[DONE]":
                            break
                        try:
                            dc = _json.loads(payload_c)
                        except Exception:
                            continue
                        choices_c = dc.get("choices") or []
                        if not choices_c:
                            continue
                        ch_c = choices_c[0]
                        delta_c = ch_c.get("delta", {})
                        if delta_c.get("content"):
                            _cont_parts.append(delta_c["content"])
                        if ch_c.get("finish_reason"):
                            _cont_finish = ch_c["finish_reason"]
                _cont_content = "".join(_cont_parts)
                content = content + _cont_content
                finish = _cont_finish or "stop"
                _max_continues -= 1
                print(f"[local_worker] continuation content_len={len(content)} finish={finish} continues_left={_max_continues}", file=_sys.stderr, flush=True)
            except Exception as ec:  # noqa: BLE001
                print(f"[local_worker] continuation failed: {type(ec).__name__}", file=_sys.stderr, flush=True)
                break
    except Exception as e:  # noqa: BLE001
        import sys
        print(f"[local_worker] httpx failed: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr, flush=True)
        return {
            "last_obs": {"ok": False, "summary": {"tool_calls": 0}, "error": str(e)[:200]},
            "signatures": state.get("signatures", []) + [f"local_worker_error:{type(e).__name__}"],
            "history": state.get("history", []) + [
                {"step": "worker", "summary": {"tool_calls": 0}, "error": True}],
            "worker_error": True,
        }

    # 解析 ```lang:path 格式的文件块
    files_written: list[str] = []
    pattern = re.compile(r"```(?:[\w]+)?:([^\n]+)\n([\s\S]*?)```")
    for m in pattern.finditer(content):
        rel_path = m.group(1).strip().strip("`")
        file_content = m.group(2)
        # 去掉末尾多余换行
        if file_content.endswith("\n"):
            file_content = file_content[:-1]
        # 安全检查：路径不能逃逸 cwd
        full_path = os.path.join(cwd, rel_path)
        norm_cwd = os.path.normpath(cwd)
        norm_full = os.path.normpath(full_path)
        if not norm_full.startswith(norm_cwd):
            continue
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(file_content)
        files_written.append(rel_path)

    # 回退解析：Kimi 有时不加 ```lang:path 前缀，或加了前缀但没有闭合的 ```。
    # 1. 先尝试无闭合 ``` 的 pattern（```lang:path\n... 到末尾）
    if not files_written:
        no_close_pattern = re.compile(r"```(?:[\w]+)?:([^\n]+)\n([\s\S]+)$")
        for m in no_close_pattern.finditer(content):
            rel_path = m.group(1).strip().strip("`")
            file_content = m.group(2)
            # 去掉末尾可能的 ``` 和多余换行
            file_content = file_content.rstrip("`").rstrip()
            if file_content.endswith("\n"):
                file_content = file_content[:-1]
            full_path = os.path.join(cwd, rel_path)
            norm_cwd = os.path.normpath(cwd)
            norm_full = os.path.normpath(full_path)
            if not norm_full.startswith(norm_cwd):
                continue
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(file_content)
            files_written.append(rel_path)

    # 2. 仍然没解析出文件块 → 检测裸 HTML/CSS（去掉 markdown 标记后写文件）
    if not files_written:
        stripped = content.strip()
        # 去掉开头的 ```lang:path 标记（如果有）
        stripped = re.sub(r"^```[^\n]*\n", "", stripped).strip()
        stripped = stripped.rstrip("`").rstrip()
        if stripped.startswith("<!DOCTYPE") or stripped.startswith("<html") or "<html" in stripped[:200]:
            path = os.path.join(cwd, "index.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(stripped)
            files_written.append("index.html")
        elif stripped.startswith(":root") or stripped.startswith("@media") or stripped.startswith("/*"):
            path = os.path.join(cwd, "style.css")
            with open(path, "w", encoding="utf-8") as f:
                f.write(stripped)
            files_written.append("style.css")

    # M15.1: post-generation hex auto-fix。
    # E2E 暴露 worker(Kimi) 不遵守 compact brief 的 hex 约束，
    # 把 #0D0D12 替换成 #0b0f19，#F5F5F5 替换成 #f8fafc。
    # 在写文件后自动扫描 CSS 变量定义，替换为正确 hex 值（不依赖模型遵守约束）。
    if files_written:
        _hex_map = _extract_hex_map(state.get("project_rules", ""))
        if _hex_map:
            _auto_fix_hex_in_dir(cwd, _hex_map)

        # M24: post-generation 间距/字体 auto-fix。
        # 与 hex auto-fix 同理：不依赖模型遵守 8px 网格 / 模块化字体比例约束，
        # 在代码层面把非网格间距修正为最近网格值、非标准字号修正为最近标准字号。
        try:
            from driving.design_context import auto_fix_design_issues
            auto_fix_design_issues(cwd)
        except Exception:
            pass

        # M52: design_score 回归检测 — 如果新版本分数低于旧版本，回退到旧版本。
        # 防止 worker 生成的低质量代码覆盖已有的高质量代码。
        if _old_html and _check_design_regression(cwd, _old_html):
            with open(_old_path, "w", encoding="utf-8") as f:
                f.write(_old_html)
            import sys as _sys
            print(f"[local_worker] design_regression: 回退到旧版本（design_score 回归）", file=_sys.stderr, flush=True)

    tool_calls = len(files_written)
    # 即使没解析出文件块，只要 Kimi 有响应内容，就不算 infrastructure error。
    # 让 verifier 决定成败——也许之前的 iteration 已经写了文件，这次只是补充说明。
    # worker_error=True 会导致 orchestrator 跳过 verify 直接判定失败。
    ok = tool_calls > 0 or bool(content.strip())
    sig = f"local:{','.join(sorted(files_written[:5]))}" if files_written else "local:no_files"

    return {
        "last_obs": {"ok": ok, "summary": {"tool_calls": tool_calls, "files": files_written}},
        "signatures": state.get("signatures", []) + [sig],
        "history": state.get("history", []) + [
            {"step": "worker", "summary": {"tool_calls": tool_calls, "files": files_written},
             "signature": sig, "error": not ok}],
        "worker_error": not ok,
    }


# 环境变量切换：FLIPPED_USE_LOCAL_WORKER=1 用本地 worker（绕过 Docker）
default_worker = local_worker if os.environ.get("FLIPPED_USE_LOCAL_WORKER") == "1" else openhands_worker


def default_overseer(state: OrchestratorState) -> dict:
    """专属监督：确定性预检(效率) + GLM 方向判断 → 结构化 verdict + 路由动作。"""
    sigs = state.get("signatures", [])
    last = sigs[-1] if sigs else None
    repeats = sigs.count(last) if last else 0
    threshold = state.get("loop_threshold", DEFAULT_LOOP_THRESHOLD)

    # 1) 确定性预检：同一动作重复达阈值 = 低效/卡死 → 直接 replan（省一次 LLM）
    if last and repeats >= threshold:
        verdict = {"efficiency": 0.1, "direction": 0.5, "action": "replan",
                   "issues": [f"同一动作签名重复 {repeats} 次(低效/卡死)"],
                   "rationale": "确定性预检命中重复动作"}
        return _overseer_ret(state, verdict)

    # 2) GLM 方向判断（是否偏离目标 / 效率如何）
    from pydantic import BaseModel, Field, field_validator

    class Verdict(BaseModel):
        efficiency: float = Field(description="0-1，worker 这步效率(是否绕路/低产)")
        direction: float = Field(description="0-1，是否朝目标正确方向推进")
        action: Literal["continue", "replan", "abort"] = Field(description="继续/回调度重规划/中止")
        issues: list[str] = Field(default_factory=list, description="发现的问题")
        rationale: str = Field(description="一句话理由")

        @field_validator("issues", mode="before")
        @classmethod
        def _coerce_issues(cls, v):
            """GLM 偶尔把 list[str] 返回为裸字符串 → 统一包成 list。"""
            if isinstance(v, str):
                return [v] if v else []
            return v or []

    summary = (state.get("last_obs") or {}).get("summary", {})
    msg = (f"目标：{state['goal']}\n子任务：{state.get('current_subtask','')}\n"
           f"执行者本步轨迹概览：{summary}\n"
           "你是专属监督者：评估执行者这一步的【效率】(有无绕路/重复/低产)与【方向】(是否朝目标)。"
           "方向明显跑偏→replan；严重无望/危险→abort；正常→continue。")
    try:
        # M131 模型分工：overseer 用 Kimi-K2.7-Code（监控者），不再复用 architect(GLM-5.2)。
        # 用户要求：GLM-5.2 作为主模型(架构师/编排者)，K2.7-Code 作为监控和子模型。
        # Kimi 工具调用快(2.6s)、监控判断快(13.8s)，适合实时监督；GLM-5.2 专注规划。
        v = _invoke_structured(_make_llm("overseer", callbacks=[MetricsCallbackHandler()]), Verdict, msg)
        verdict = {"efficiency": v.efficiency, "direction": v.direction, "action": v.action,
                   "issues": v.issues, "rationale": v.rationale}
    except Exception as e:  # noqa: BLE001 监督失败 fail-open: 不阻塞，交给强制验证兜底
        verdict = {"efficiency": 0.5, "direction": 0.5, "action": "continue",
                   "issues": [], "rationale": f"(overseer LLM 失败 fail-open: {e})"}
    return _overseer_ret(state, verdict)


def _overseer_ret(state: OrchestratorState, verdict: dict) -> dict:
    hist = state.get("history", []) + [{"step": "overseer", "verdict": verdict}]
    upd = {"verdict": verdict, "history": hist}
    if verdict["action"] != "continue":
        upd["feedback"] = f"监督意见: {verdict.get('rationale')} 问题: {verdict.get('issues')}"
    return upd


def _safe_default_verifier(cmd: list, cwd: str) -> "tuple[bool, str]":
    from driving.approval import classify_risk
    command_str = " ".join(cmd)
    ok, reason = is_safe_command(command_str)
    if not ok:
        return False, f"command blocked: {reason}"
    if classify_risk(command_str) == "high":
        return False, "high-risk command requires approval"
    # M89 防御:cwd 是沙盒路径(/projects/X)在 host 上不存在 → 回退 home,
    # 避免 subprocess.run(cwd=...) 抛 FileNotFoundError。
    if cwd and not os.path.isdir(cwd):
        cwd = os.path.expanduser("~")
    import shlex
    import subprocess
    # M14 修复：bash -c "...$var..." 经 shell=True 执行时，外层 /bin/sh 会先展开 $var
    # （此时 $var 为空），导致内层 bash 拿到空路径。用 shlex.split 提取内层命令，
    # 直接传 ['bash', '-c', inner_cmd] 绕过外层 shell。
    if len(cmd) == 1 and cmd[0].startswith(("bash -c ", "sh -c ")):
        try:
            tokens = shlex.split(cmd[0])
            if len(tokens) >= 3 and tokens[0] in ("bash", "sh") and tokens[1] == "-c":
                inner_cmd = tokens[2]
                p = subprocess.run(
                    [tokens[0], "-c", inner_cmd],
                    cwd=cwd, capture_output=True, text=True, timeout=300,
                )
                return p.returncode == 0, (p.stdout + p.stderr)[-2000:]
        except Exception:  # noqa: BLE001 — shlex 解析失败时回退到 shell=True
            pass
    p = subprocess.run(command_str, shell=True, cwd=cwd, capture_output=True, text=True, timeout=300)
    return p.returncode == 0, (p.stdout + p.stderr)[-2000:]


# ---------- 图 ----------

def build_orchestrator(supervisor: SupervisorFn = default_supervisor,
                       worker: WorkerFn = default_worker,
                       overseer: OverseerFn = default_overseer,
                       verifier: VerifierFn = _safe_default_verifier,
                       checkpointer=None,
                       max_context_tokens: int = 10000,
                       keep_recent: int = 4,
                       summarizer: Callable | None = None):
    """编译 Supervisor→Worker→Overseer→(条件)→Verify 多 agent 监督图。节点可注入。"""

    def verify(state: OrchestratorState) -> dict:
        # Worker 刚 finish 后沙箱可能还在清理 → 短暂等待 + 一次重试
        import time as _time
        ok, output = verifier(state["verify_cmd"], state["cwd"])
        if not ok and not output.strip():
            _time.sleep(3)
            ok, output = verifier(state["verify_cmd"], state["cwd"])
        it = state.get("iteration", 0) + 1
        hist = state.get("history", []) + [{"step": "verify", "ok": ok, "iteration": it}]
        # M89 修复:只在 supervisor believe_done=True AND verify 通过时才整体 verified。
        # 否则 verify 通过仅代表当前子任务(或无验收命令)→ 回 supervisor 拆下一个子任务。
        # 旧逻辑只看 ok → no-op verifier 总 True → 第一个子任务后就误判整体完成。
        believe_done = state.get("believe_done", False)
        verified = ok and believe_done
        upd = {"iteration": it, "verified": verified, "history": hist}
        if verified:
            upd["done"] = True
            upd["stop_reason"] = "verified"
        elif not ok:
            upd["feedback"] = (state.get("feedback", "") + f"\n验收命令退出非0:\n{output}").strip()
        else:
            # M89 修复:ok=True but believe_done=False → 当前子任务验证通过,但整体目标未达成。
            # 必须给 supervisor 明确 feedback,否则它读到原 goal 会重新拆同样的子任务(死循环)。
            last_sub = state.get("current_subtask", "")
            upd["feedback"] = (state.get("feedback", "") +
                f"\n子任务「{last_sub[:80]}」已完成且验证通过。请基于历史已完成的步骤,拆解下一个不同的子任务,不要重复已完成的内容。").strip()
        return upd

    def route_overseer(state: OrchestratorState) -> str:
        action = (state.get("verdict") or {}).get("action", "continue")
        if action == "abort":
            return "abort"
        if action == "replan":
            return "replan"
        return "verify"

    def mark_abort(state: OrchestratorState) -> dict:
        return {"done": True, "stop_reason": "overseer_abort"}

    def route_verify(state: OrchestratorState) -> str:
        if state.get("verified"):
            return END
        sigs = state.get("signatures", [])
        last = sigs[-1] if sigs else None
        if last and sigs.count(last) >= state.get("loop_threshold", DEFAULT_LOOP_THRESHOLD):
            return "loop"
        if state.get("iteration", 0) >= state.get("max_iterations", 3):
            return "breaker"
        return "supervisor"

    def mark_loop(state: OrchestratorState) -> dict:
        return {"done": True, "stop_reason": "loop_detected"}

    def mark_breaker(state: OrchestratorState) -> dict:
        return {"done": True, "stop_reason": "circuit_breaker"}

    def compress_node(state: OrchestratorState) -> dict:
        history = state.get("history", [])
        if not history:
            return {}
        result = compress_history(
            history,
            max_tokens=max_context_tokens,
            keep_recent=keep_recent,
            summarizer=summarizer,
        )
        if not result.get("compressed"):
            return {}
        return {"history": result["history"], "context_summary": result.get("summary")}

    g = StateGraph(OrchestratorState)
    g.add_node("supervisor", supervisor)
    g.add_node("worker", worker)
    g.add_node("overseer", overseer)
    g.add_node("verify", verify)
    g.add_node("abort", mark_abort)
    g.add_node("loop", mark_loop)
    g.add_node("breaker", mark_breaker)
    g.add_node("compress", compress_node)
    def approval_gate(state: OrchestratorState) -> dict:
        # 高风险子任务（逸出沙箱/不可逆，§7）在派给 worker 前硬暂停审批；require_approval=False 时直通
        if state.get("require_approval") and classify_risk(state.get("current_subtask", "")) == "high":
            decision = interrupt({"subtask": state.get("current_subtask"),
                                  "reason": "高风险子任务，需人工放行（§7 沙箱外要审批）"})
            if str(decision).strip().lower() in APPROVE_WORDS:
                return {"approval_decision": "approved"}
            return {"approval_decision": "rejected",
                    "feedback": (state.get("feedback", "") + "\n[人工否决了上一子任务，请换方案]").strip()}
        return {"approval_decision": "auto"}

    def _route_sup(state: OrchestratorState) -> str:
        # supervisor 相信已完成 → 直接强制验证（跳过冗余 worker 步）
        return "verify" if state.get("believe_done") else "approval_gate"

    def _route_approval(state: OrchestratorState) -> str:
        # 被否决 → 回 supervisor 重规划；否则 → worker 执行
        return "supervisor" if state.get("approval_decision") == "rejected" else "worker"

    g.add_node("approval_gate", approval_gate)
    g.add_edge(START, "supervisor")
    g.add_edge("compress", "supervisor")
    g.add_conditional_edges("supervisor", _route_sup, {"approval_gate": "approval_gate", "verify": "verify"})
    g.add_conditional_edges("approval_gate", _route_approval, {"supervisor": "compress", "worker": "worker"})
    def mark_worker_error(state: OrchestratorState) -> dict:
        return {"done": True, "stop_reason": "worker_error"}

    def route_worker(state: OrchestratorState) -> str:
        # M90 自动交替接力:worker_error 时优先切换备用模型重试一次
        # 已接力过(relay_attempted=True)则不再重试,直接终结避免无限接力
        if state.get("worker_error"):
            if state.get("relay_attempted"):
                return "worker_error"
            return "relay"
        return "overseer"

    # M90 relay 节点:切换 worker 模型 alias(coder↔architect)+ 清除 worker_error
    # + 压缩上下文(释放上一个模型的内容,对齐"释放上一个模型的内容开始监督")
    # 下一轮 worker 会用新 alias 重试同一子任务
    def relay_node(state: OrchestratorState) -> dict:
        current_alias = state.get("worker_alias", "coder")
        new_alias = "architect" if current_alias == "coder" else "coder"
        import sys as _sys
        print(f"[M90 relay] worker {current_alias} 卡死,切换 {new_alias} 接力,清除 worker_error",
              file=_sys.stderr, flush=True)
        # 压缩 history 释放上一个模型的上下文(对齐用户理念)
        history = state.get("history", [])
        compressed: dict = {}
        if history:
            try:
                result = compress_history(
                    history,
                    max_tokens=state.get("max_context_tokens", 10000),
                    keep_recent=state.get("keep_recent", 4),
                    summarizer=summarizer,
                )
                if result.get("compressed"):
                    compressed = {"history": result["history"],
                                  "context_summary": result.get("summary")}
            except Exception as e:  # noqa: BLE001
                print(f"[M90 relay] 压缩失败,保留原 history: {type(e).__name__}: {e}",
                      file=_sys.stderr, flush=True)
        update: dict = {
            "worker_alias": new_alias,
            "relay_attempted": True,
            "worker_error": False,
            "feedback": (state.get("feedback", "")
                         + f"\n[M90 接力] {current_alias} 卡死,{new_alias} 接力重试该子任务。]").strip(),
        }
        if compressed:
            update.update(compressed)
        return update

    g.add_node("worker_error", mark_worker_error)
    g.add_node("relay", relay_node)
    g.add_conditional_edges("worker", route_worker,
                            {"overseer": "overseer", "worker_error": "worker_error", "relay": "relay"})
    g.add_edge("worker_error", END)
    g.add_edge("relay", "worker")  # 接力后回到 worker 用新 alias 重试
    g.add_conditional_edges("overseer", route_overseer,
                            {"verify": "verify", "replan": "compress", "abort": "abort"})
    g.add_conditional_edges("verify", route_verify,
                            {"supervisor": "compress", "loop": "loop", "breaker": "breaker", END: END})
    g.add_edge("abort", END)
    g.add_edge("loop", END)
    g.add_edge("breaker", END)
    return g.compile(checkpointer=checkpointer)


def drive_orchestrated(goal: str, cwd: str, verify_cmd: list, *,
                       max_iterations: int = 4, loop_threshold: int = DEFAULT_LOOP_THRESHOLD,
                       thread_id: str = "default", db_path: str = ":memory:",
                       data_dir: str | None = None, require_approval: bool = False,
                       project_rules: str = "", repo_map: str = "",
                       max_context_tokens: int = 10000, keep_recent: int = 4,
                       summarizer: Callable | None = None,
                       max_checkpoints: int = 50,
                       supervisor: SupervisorFn = default_supervisor,
                       worker: WorkerFn = default_worker,
                       overseer: OverseerFn = default_overseer,
                       verifier: VerifierFn = _safe_default_verifier) -> OrchestratorState:
    """多 Agent 监督编排驱动一个目标到验收通过 / 监督中止 / 循环 / 熔断。

    require_approval=True：高风险子任务在执行前 interrupt 等人工放行（命中需用 Command(resume=...) 续跑）。
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    initial: OrchestratorState = {
        "goal": goal, "cwd": cwd, "verify_cmd": verify_cmd, "data_dir": data_dir,
        "project_rules": project_rules, "repo_map": repo_map,
        "max_iterations": max_iterations, "loop_threshold": loop_threshold,
        "require_approval": require_approval, "worker_error": False,
        "iteration": 0, "signatures": [], "feedback": "", "verified": False,
        "done": False, "stop_reason": "", "history": [],
        "relay_attempted": False, "worker_alias": "coder",
        "context_summary": None, "max_context_tokens": max_context_tokens,
        "keep_recent": keep_recent,
    }
    with SqliteSaver.from_conn_string(db_path) as cp:
        graph = build_orchestrator(
            supervisor=supervisor,
            worker=worker,
            overseer=overseer,
            verifier=verifier,
            checkpointer=cp,
            max_context_tokens=max_context_tokens,
            keep_recent=keep_recent,
            summarizer=summarizer,
        )
        result = graph.invoke(initial, config={"configurable": {"thread_id": thread_id}})
        CheckpointRetention(cp, max_checkpoints=max_checkpoints).trim(thread_id)
        return result


def resume_orchestrated(thread_id: str, db_path: str = "data/checkpoints.db", *,
                        supervisor: SupervisorFn = default_supervisor,
                        worker: WorkerFn = default_worker,
                        overseer: OverseerFn = default_overseer,
                        verifier: VerifierFn = _safe_default_verifier,
                        max_context_tokens: int = 10000, keep_recent: int = 4,
                        summarizer: Callable | None = None,
                        max_checkpoints: int = 50) -> OrchestratorState | None:
    """从 LangGraph checkpoint 恢复并继续一次未完成的 orchestrator 运行。

    适用于：orchestration-api 崩溃重启后，扫描到 `status=running` 的会话，
    从持久化的 SqliteSaver 断点续跑。
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    with SqliteSaver.from_conn_string(db_path) as cp:
        # 先确认数据库里真的有该 thread 的 checkpoint，避免 LangGraph 把空状态当成新 run
        with cp.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM checkpoints WHERE thread_id = ? LIMIT 1",
                (str(thread_id),),
            )
            if not cur.fetchone():
                return None

        graph = build_orchestrator(
            supervisor=supervisor,
            worker=worker,
            overseer=overseer,
            verifier=verifier,
            checkpointer=cp,
            max_context_tokens=max_context_tokens,
            keep_recent=keep_recent,
            summarizer=summarizer,
        )
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = graph.get_state(config)
        if snapshot is None:
            return None
        values = snapshot.values
        if values.get("done"):
            return values
        # 若上一 checkpoint 已被 interrupt（如审批断点），不自动恢复，等待外部 Command(resume=...)
        if "__interrupt__" in values:
            return values
        result = graph.invoke(None, config)
        CheckpointRetention(cp, max_checkpoints=max_checkpoints).trim(thread_id)
        return result
